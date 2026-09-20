"""API contracts, cache boundaries, failure handling and engine parity."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.cache import TTLCache
from backend.main import create_app
from backend.services import IntelligenceService
from football_data import FootballDataError
from news import NewsError
from sleeper_api import SleeperAPIError
from storage import SQLiteRepository


class Sleeper:
    calls = 0

    def get_user(self, username):
        if username == "missing":
            raise SleeperAPIError('No Sleeper user was found for "missing".')
        if username == "offline":
            raise SleeperAPIError(
                "Could not connect to Sleeper. Please try again shortly."
            )
        return {"user_id": username, "username": username}

    def get_leagues(self, user_id, season):
        return [
            {
                "league_id": "league",
                "name": "Test league",
                "season": "2026",
                "scoring_settings": {"rec": 0.5},
                "roster_positions": ["WR", "BN"],
            }
        ]

    def get_rosters(self, league_id):
        self.calls += 1
        return [
            {
                "owner_id": "manager",
                "players": ["one", "two"],
                "starters": ["one"],
                "metadata": {"team_name": "Test Team"},
            }
        ]

    def get_players(self):
        return {
            key: {"full_name": name, "position": "WR", "team": "LAR", "active": True}
            for key, name in [
                ("one", "Player One"),
                ("two", "Player Two"),
                ("free", "Free Receiver"),
            ]
        }

    def get_nfl_state(self):
        return {"season": "2026", "week": 2, "season_type": "regular"}


class Nflverse:
    def get_schedule_rows(self):
        return []

    def get_stat_rows(self, season):
        return []

    def get_snap_rows(self, season):
        return []

    def get_injury_rows(self, season):
        return []

    def get_player_rows(self):
        return []


class News:
    def fetch(self):
        return []


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    svc = IntelligenceService(
        SQLiteRepository(tmp_path / "test.db"), Sleeper(), Nflverse(), News()
    )
    yield svc
    svc.close()


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as value:
        yield value


def test_health_and_normalized_connection(client):
    assert client.get("/health").json()["status"] == "ok"
    result = client.get("/api/users/manager/leagues")
    assert result.status_code == 200
    assert result.json()["leagues"][0]["scoring"] == "Half PPR"
    assert "scoring_settings" not in result.text and "owner_id" not in result.text


@pytest.mark.parametrize(
    "route",
    ["overview", "roster", "lineup", "waivers", "events", "history", "snapshot"],
)
def test_read_endpoints_and_typed_contracts(client, service, route):
    response = client.get(f"/api/leagues/league/{route}?username=manager")
    assert response.status_code == 200
    assert "Server-Timing" in response.headers
    assert "player_id" not in response.text
    assert service.build_count == 1


def test_navigation_reuses_snapshot_and_does_not_advance_memory(client, service):
    first = client.get("/api/leagues/league/snapshot?username=manager").json()
    snapshot, _ = service.get_snapshot("manager", "league")
    observed = service.repository.snapshot_count(snapshot.scope)
    for route in ["overview", "roster", "waivers", "events", "snapshot"]:
        assert (
            client.get(f"/api/leagues/league/{route}?username=manager").status_code
            == 200
        )
    assert service.build_count == 1
    assert service.sleeper.calls == 1
    assert service.repository.snapshot_count(snapshot.scope) == observed
    assert first["league"]["team_name"] == "Test Team"
    assert first["starters"][0]["player"]["name"] == "Player One"
    assert first["bench"][0]["name"] == "Player Two"
    assert all(w["player"]["id"] not in {"one", "two"} for w in first["waivers"])


def test_copilot_followup_and_no_raw_transcript_persistence(client, service):
    url = "/api/leagues/league/copilot?username=manager"
    first = client.post(
        url, json={"question": "Who is the best WR available?", "suggested": True}
    )
    assert first.status_code == 200
    assert first.json()["intent"] == "WAIVERS"
    second = client.post(
        url,
        json={"question": "Why?", "conversation_id": first.json()["conversation_id"]},
    )
    assert second.status_code == 200
    assert second.json()["intent"] == "EXPLAIN_RECOMMENDATION"
    assert service.repository.analytics_count("copilot_followup_used") == 1
    with service.repository._connect() as db:
        payloads = " ".join(
            row[0] for row in db.execute("SELECT metadata_json FROM analytics_events")
        )
    assert "Who is the best" not in payloads and "Why?" not in payloads


def test_invalid_user_league_and_provider_failure(client):
    assert client.get("/api/users/missing/leagues").status_code == 404
    assert client.get("/api/users/offline/leagues").status_code == 502
    assert (
        client.get("/api/leagues/unrelated/overview?username=manager").status_code
        == 404
    )
    assert client.get("/api/leagues/league/roster").status_code == 422
    assert (
        client.post(
            "/api/leagues/league/copilot?username=manager", json={"question": "x" * 501}
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/leagues/league/players/no-such-player?username=manager"
        ).status_code
        == 404
    )


def test_partial_provider_failure_degrades_without_inventing_data(service):
    def broken():
        raise FootballDataError("offline")

    def no_news():
        raise NewsError("offline")

    service.nflverse.get_schedule_rows = broken
    service.news.fetch = no_news
    snapshot, _ = service.get_snapshot("manager", "league")
    assert not snapshot.data_fresh and len(snapshot.warnings) == 2
    assert snapshot.state.contexts["one"].schedule_status == "UNKNOWN"
    assert not snapshot.state.contexts["one"].is_bye


def test_cache_expiry_single_flight_and_bounded_storage():
    now, calls = [0], [0]
    cache = TTLCache(max_entries=2, clock=lambda: now[0])

    def build():
        calls[0] += 1
        return calls[0]

    with ThreadPoolExecutor(max_workers=5) as pool:
        assert (
            list(pool.map(lambda _: cache.get("a", 10, build), range(10))) == [1] * 10
        )
    now[0] = 11
    assert cache.get("a", 10, build) == 2
    cache.get("b", 10, build)
    cache.get("c", 10, build)
    assert len(cache.entries) == 2 and "a" not in cache.entries
    cache.close()


def test_background_refresh_keeps_current_page_usable():
    cache = TTLCache()
    entered, release = Event(), Event()
    cache.put("league", "old", 10)

    def build():
        entered.set()
        release.wait(2)
        return "new"

    assert cache.get("league", 10, build, force=True, background=True) == "old"
    assert entered.wait(1)
    assert cache.status("league")["refreshing"]
    assert cache.get("league", 10, build) == "old"
    release.set()
    cache.close()
    assert cache.entries["league"].value == "new"


def test_failed_background_refresh_preserves_old_snapshot_and_marks_error():
    cache = TTLCache()
    cache.put("league", "old", -1)

    def broken():
        raise RuntimeError("provider down")

    assert cache.get("league", 10, broken, background=True) == "old"
    cache.close()
    assert cache.status("league")["stale"]
    assert cache.status("league")["refresh_error"]


def test_schema_is_documented_and_available(client):
    spec = client.get("/openapi.json").json()
    assert "Snapshot" in spec["components"]["schemas"]
    assert "CopilotResponse" in spec["components"]["schemas"]


def test_explicit_refresh_observes_changed_league_scoring(client, service):
    first = client.get("/api/leagues/league/snapshot?username=manager").json()
    original = service.sleeper.get_leagues

    def changed(user, season):
        leagues = original(user, season)
        leagues[0]["scoring_settings"] = {"rec": 1}
        return leagues

    service.sleeper.get_leagues = changed
    refreshed = client.post("/api/leagues/league/refresh?username=manager")
    assert refreshed.status_code == 200
    assert refreshed.json()["league"]["scoring"] == "PPR"
    assert refreshed.json()["meta"]["id"] != first["meta"]["id"]
    assert service.build_count == 2


def test_feedback_rejects_unknown_event_and_invalid_status(client):
    url = "/api/leagues/league/events/not-real/feedback?username=manager"
    assert client.post(url, json={"status": "DONE"}).status_code == 404
    assert client.post(url, json={"status": "REMOVE"}).status_code == 422


def test_feedback_persists_without_recomputing_intelligence(client, service):
    from dataclasses import replace
    from opportunity_engine import FantasyOpportunity, Signal

    snapshot, _ = service.get_snapshot("manager", "league")
    player = snapshot.state.roster.starters[0]
    signal = Signal(
        "TARGET_INCREASE", player.player_id, "LAR", 6, 4, 2, 4, "HIGH", "nflverse", 2
    )
    event = FantasyOpportunity(
        "watch:one",
        "BREAKOUT_WATCH",
        "MEDIUM",
        player,
        None,
        (signal,),
        ("ON_USER_ROSTER",),
        "MONITOR",
        "HIGH",
        ("Targets increased",),
        2,
        2,
    )
    memory = service.repository.reconcile(snapshot.scope, [event], data_fresh=True)
    snapshot.state = replace(snapshot.state, memory=memory)
    event_id = memory.current[0].event_key
    url = f"/api/leagues/league/events/{event_id}/feedback?username=manager"
    assert client.post(url, json={"status": "SAVED"}).status_code == 200
    assert (
        client.get("/api/leagues/league/events?username=manager").json()[0]["feedback"]
        == "SAVED"
    )
    assert (
        client.get("/api/leagues/league/history?username=manager").json()[0]["feedback"]
        == "SAVED"
    )
    assert service.build_count == 1


def test_conversation_isolation_between_leagues(service):
    from dataclasses import replace

    snapshot, _ = service.get_snapshot("manager", "league")
    conversation, _, _ = service.ask(snapshot, "Who is the best WR available?")
    other = replace(snapshot, scope=replace(snapshot.scope, league_id="other"))
    _, intent, _ = service.ask(other, "Why?", conversation)
    assert not intent.follow_up


@pytest.fixture
def trade_context(service):
    from dataclasses import replace
    from test_trades import fixture_engine

    engine = fixture_engine()
    snap, _ = service.get_snapshot("manager", "league")
    snap.state = replace(
        snap.state,
        active_players=tuple(engine.players.values()),
        roster=engine.state.roster,
        contexts=engine.state.contexts,
        profiles={},
        opportunities={},
        ownership=engine.owners,
        user_roster_id="a",
    )
    engine.state = snap.state
    service.trade_engine = lambda snapshot: engine
    return engine


def test_trade_endpoints_and_cache_preserve_base_snapshot(
    client, service, trade_context
):
    base = "/api/leagues/league/trades"
    overview = client.get(base + "?username=manager")
    assert overview.status_code == 200
    assert len(overview.json()["teams"]) == 2
    assert overview.json()["players"]["br2"]["is_opponent"]
    request = {"goal": "RB", "protect_core": False}
    first = client.post(base + "/search?username=manager", json=request)
    assert first.status_code == 200 and first.json()["ideas"]
    assert (
        client.post(base + "/search?username=manager", json=request).json()
        == first.json()
    )
    assert service.build_count == 1
    result = client.post(
        base + "/analyze?username=manager",
        json={**request, "outgoing": ["aw2"], "incoming": ["br2"]},
    )
    assert result.status_code == 200 and result.json()["accepted"]
    assert service.repository.analytics_count("TRADE_ANALYZED") == 1
    assert (
        client.post(
            base + "/search?username=manager", json={"protected": ["br2"]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            base + "/search?username=manager", json={"goal": "DYNASTY"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "question,intent",
    [
        ("Find me an RB trade", "TRADE_FIND"),
        ("Get me Player br2", "TRADE_TARGET"),
        ("Shop Player aw2", "TRADE_AWAY"),
        ("Trade Player aw2 for Player br2", "TRADE_ANALYZE"),
        ("Who should I trade with?", "TRADE_PARTNER"),
    ],
)
def test_trade_copilot_uses_engine_not_model(client, trade_context, question, intent):
    result = client.post(
        "/api/leagues/league/copilot?username=manager", json={"question": question}
    )
    assert result.status_code == 200
    assert result.json()["intent"] == intent
    if intent != "TRADE_PARTNER":
        assert result.json()["trades"]["ideas"]
    assert result.json()["model_text"] is None


def test_copilot_protection_and_dynasty_guard(client, trade_context):
    url = "/api/leagues/league/copilot?username=manager"
    response = client.post(
        url, json={"question": "Find me an RB trade without giving up Player aw2"}
    )
    assert all(
        "aw2" not in idea["outgoing"] for idea in response.json()["trades"]["ideas"]
    )
    response = client.post(
        url, json={"question": "Find a dynasty trade with draft picks"}
    )
    assert response.json()["unsupported"]


def test_trade_followup_obeys_new_protections(client, trade_context):
    url = "/api/leagues/league/copilot?username=manager"
    first = client.post(url, json={"question": "Find me an RB trade"}).json()
    response = client.post(
        url,
        json={
            "question": "why",
            "conversation_id": first["conversation_id"],
            "trade_preferences": {"protected": ["aw2"]},
        },
    )
    assert response.status_code == 200
    assert all(
        "aw2" not in idea["outgoing"] for idea in response.json()["trades"]["ideas"]
    )


def test_trade_analysis_does_not_silently_reverse_explicit_sides(client, trade_context):
    result = client.post(
        "/api/leagues/league/copilot?username=manager",
        json={"question": "I send Player br2 for Player aw2"},
    )
    assert result.status_code == 200
    assert "clarify the direction" in result.json()["answer"]
    assert result.json()["trades"] is None
