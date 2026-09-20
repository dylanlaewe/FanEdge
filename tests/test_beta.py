import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from backend.beta import BetaStore, RateLimiter, log_request
from beta_config import build_version, capabilities
from scripts.beta_report import report
from scripts.calibration_report import aggregate, release_gates
from test_backend import service, client

BASE = "/api/leagues/league/"
SUFFIX = "?username=manager"


def test_flags_fail_closed(monkeypatch):
    for name in ("NEWS", "PLAYER_IMAGES", "TEAM_LOGOS", "AI", "MARKET_ADP"):
        monkeypatch.delenv(f"FANEDGE_{name}_ENABLED", raising=False)
    assert not any(v for k, v in capabilities().items() if k.endswith("enabled"))
    monkeypatch.setenv("FANEDGE_AI_ENABLED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert not capabilities()["ai_enabled"]


def test_build_and_capabilities(client):
    response = client.get("/api/capabilities")
    assert response.json()["build"] == build_version()
    assert response.headers["X-FanEdge-Build"] == build_version()
    assert len(response.headers["X-Request-ID"]) == 32


def test_product_visuals_default_to_local_fallback(client, monkeypatch):
    monkeypatch.delenv("FANEDGE_PLAYER_IMAGES_ENABLED", raising=False)
    monkeypatch.delenv("FANEDGE_TEAM_LOGOS_ENABLED", raising=False)
    response = client.get(BASE + "snapshot" + SUFFIX)
    assert response.status_code == 200 and "espncdn" not in response.text
    from backend.presenter import team
    from visuals import TEAM_NAMES
    assert all(team(code).logo_url is None for code in TEAM_NAMES)


def test_sliding_rate_limit():
    time = [0]
    limiter = RateLimiter(clock=lambda: time[0])
    assert limiter.allow("a", 2) and limiter.allow("a", 2)
    assert not limiter.allow("a", 2)
    assert limiter.allow("b", 2)
    time[0] = 60
    assert limiter.allow("a", 2)


def test_rate_limit_http(client):
    for _ in range(12):
        response = client.post(BASE + "copilot" + SUFFIX, json={"question": "weather?"})
        assert response.status_code == 200
    response = client.post(BASE + "copilot" + SUFFIX, json={"question": "weather?"})
    assert response.status_code == 429 and response.headers["Retry-After"] == "60"


def test_duplicate_ask_single_flight(service, monkeypatch):
    snap, _ = service.get_snapshot("manager", "league")
    calls = []
    original = service._ask
    def observed(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(service, "_ask", observed)
    with ThreadPoolExecutor(4) as pool:
        values = list(pool.map(lambda _: service.ask(snap, "What's my biggest roster weakness?"), range(4)))
    assert len(calls) == 1
    assert len({v[0] for v in values}) == 1
    conversation = values[0][0]
    first = service.ask(snap, "Why?", conversation)
    count = len(calls)
    assert service.ask(snap, "Why?", conversation) == first
    assert len(calls) == count


def test_feedback_context_and_no_analytics_question(client, service):
    sid = str(uuid4())
    response = client.post(BASE + "beta/feedback" + SUFFIX, json={
        "category": "DATA_LOOKS_WRONG", "feature": "team", "text": "Test report", "event_id": "test-event"
    }, headers={"X-FanEdge-Session": sid})
    assert response.status_code == 201
    with BetaStore(service.repository.path).connect() as db:
        row = dict(db.execute("SELECT * FROM beta_events WHERE event='feedback'").fetchone())
    assert row["session_id"] == sid and row["league_id"] == "league"
    context = json.loads(row["context_json"])
    assert "providers" in context and "snapshot_id" in context and row["build"]
    assert "Test report" not in json.dumps(report(service.repository.path))
    assert client.post(BASE + "beta/analytics" + SUFFIX, json={"event": "my raw question"}).status_code == 422


def test_feedback_bounded_and_scoped(client):
    assert client.post(BASE + "beta/feedback" + SUFFIX, json={"category": "OTHER", "feature": "ask", "text": "x" * 1001}).status_code == 422
    assert client.post("/api/leagues/wrong/beta/feedback" + SUFFIX, json={"category": "OTHER", "feature": "ask"}).status_code == 404


def test_telemetry_funnel(client, service):
    sid = str(uuid4())
    headers = {"X-FanEdge-Session": sid}
    assert client.post("/api/beta/analytics", json={"event": "landing"}, headers=headers).status_code == 204
    for event in ("home", "intelligence_ready"):
        assert client.post(BASE + "beta/analytics" + SUFFIX, json={"event": event}, headers=headers).status_code == 204
    result = report(service.repository.path)
    assert result["sessions"] == 1 and result["users"] == 1
    assert result["activation_sessions"] == 1 and result["feature_adoption_users"]["home"] == 1


def test_ops_protected_and_clear(client, service, monkeypatch):
    monkeypatch.delenv("FANEDGE_OPS_TOKEN", raising=False)
    assert client.post("/internal/ops/clear-cache").status_code == 404
    monkeypatch.setenv("FANEDGE_OPS_TOKEN", "a" * 32)
    assert client.post("/internal/ops/clear-cache", headers={"Authorization": "Bearer wrong"}).status_code == 404
    service.get_snapshot("manager", "league")
    assert service.snapshots.entries
    response = client.post("/internal/ops/clear-cache", headers={"Authorization": "Bearer " + "a" * 32})
    assert response.status_code == 200 and not service.snapshots.entries
    assert client.post("/internal/ops/status", headers={"Authorization": "Bearer " + "a" * 32}).json()["build"]


def sample(label=None):
    audit = {"audit_id": "one", "league": {"id": "l", "user_id": "u", "format": {"scoring": "PPR"}},
             "review_items": [{"id": "r", "feature": "lineup", "position": "WR", "recommendation_type": "SWAP", "evidence_quality": "LOW"}],
             "data_quality": {"issues": []}, "searches": {"RB": {"diagnostics": {"primary_reasons": {"VALUE_GAP": 3}}}}}
    return audit, {"audit_id": "one", "reviewer": "Test reviewer", "items": [{"id": "r", "label": label}]}


@pytest.mark.parametrize("label,status", [(None, "FAIL"), ("BAD", "FAIL"), ("DEFENSIBLE", "PASS")])
def test_labels_and_gates(label, status):
    result = aggregate([sample(label)])
    assert result["recommendation_safety"] == status
    assert result["trade_rejections_per_search"]["VALUE_GAP"] == 3
    assert release_gates(result, {})["decision"] == "NO-GO"


def test_labels_reject_mismatch():
    audit, labels = sample()
    labels["audit_id"] = "other"
    with pytest.raises(ValueError):
        aggregate([(audit, labels)])


def test_release_gate_cannot_hide_bad_with_manual_pass():
    from scripts.calibration_report import GATES
    first, labels = sample("BAD")
    second, second_labels = sample("GOOD")
    second["audit_id"] = second_labels["audit_id"] = "two"
    second["league"]["id"] = "second-league"
    second["league"]["user_id"] = "second-user"
    evidence = {g: {"status": "PASS", "evidence": "Fixture only"} for g in GATES}
    result = release_gates(aggregate([(first, labels), (second, second_labels)]), evidence)
    assert result["decision"] == "NO-GO"
    assert result["gates"]["recommendation_safety"]["status"] == "FAIL"


def test_safe_structured_log():
    value = log_request("/api/leagues/{league_id}/copilot", "TIMEOUT", "id", 8, provider="OpenAI")
    assert set(value) == {"timestamp", "build", "route", "stage", "category", "provider", "correlation_id", "duration_ms"}


def test_retention(service):
    store = BetaStore(service.repository.path)
    store.record("landing")
    with store.connect() as db:
        db.execute("UPDATE beta_events SET occurred_at='2000-01-01T00:00:00Z'")
    assert store.prune() == 1


def test_openai_timeout_limits_and_fallback(monkeypatch):
    from test_copilot import state
    from copilot import CopilotEntityResolver, classify_query, answer_query
    value = state()
    intent = classify_query("What should I do this week?", CopilotEntityResolver(value.roster, [], value.league_players, value.active_players))
    seen = {}
    class TimeoutClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.responses = self
        def create(self, **kwargs):
            seen.update(kwargs)
            raise TimeoutError("private provider detail")
    monkeypatch.setattr("copilot.OpenAI", TimeoutClient)
    answer, _ = answer_query("What should I do this week?", intent, value, api_key="test")
    assert answer.provider_fallback and answer.answer
    assert seen["timeout"] == 8 and seen["max_retries"] == 0
    assert seen["max_output_tokens"] == 320 and seen["store"] is False


def test_disabled_news_not_requested(service):
    service.news_enabled = False
    service.news.fetch = lambda: (_ for _ in ()).throw(AssertionError("Disabled provider called"))
    snap, _ = service.get_snapshot("manager", "league")
    assert not snap.state.news_facts
    assert next(r for r in service.data_health(snap)["providers"] if r["dataset"] == "news_facts")["status"] == "DISABLED"


def test_disabling_news_does_not_claim_historical_resolution(service, monkeypatch):
    service.news_enabled = False
    monkeypatch.setattr(service.repository, "load_news_facts", lambda scope: (object(),))
    original = service.repository.reconcile
    calls = []
    def reconcile(*args, **kwargs):
        calls.append(kwargs["data_fresh"])
        return original(*args, **kwargs)
    monkeypatch.setattr(service.repository, "reconcile", reconcile)
    service.get_snapshot("manager", "league")
    assert calls == [False]
