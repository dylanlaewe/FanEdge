from datetime import UTC, datetime
from dataclasses import replace

from football_data import PlayerWeeklyContext
from intelligence import ParticipationSummary, RoleProfile
from memory import LeagueScope, Lifecycle
from news import Freshness, NewsFact, NewsFactType
from news_intelligence import integrate_news_intelligence, serialize_impact_graph
from opportunity import PlayerOpportunity
from sleeper_api import Player, Roster
from storage import SQLiteRepository
from waiver_engine import RosterNeeds


def news_fact(player: Player, state: str = "OUT", *, fact_id: str = "news-1") -> NewsFact:
    return NewsFact(fact_id, player.player_id, player.name, player.position, player.team, NewsFactType.PLAYER_STATUS_CHANGE.value, None, state, None, "HIGH", ("story-1",), ("ESPN",), ("https://example.com/story",), datetime(2026, 9, 19, 15, tzinfo=UTC).isoformat(), f"{player.name} has been ruled out.", Freshness.BREAKING.value, "REPUTABLE_REPORTING")


def profile(*, quality: str = "HIGH") -> RoleProfile:
    participation = ParticipationSummary(4, .42, .54, 26, 34, None, None, None, "ROLE EXPANDING")
    return RoleProfile("STARTER", "ROLE EXPANDING", quality, 4, 1, None, participation)


def opportunity(player: Player) -> PlayerOpportunity:
    return PlayerOpportunity(
        games=4, season_attempts=None, recent_attempts=None,
        season_carries=7, recent_carries=9, season_targets=2, recent_targets=3,
        season_receptions=1, recent_receptions=2, season_touches=8,
        recent_touches=11, usage_trend="RISING",
    )


def needs(*, shallow: bool = True) -> RosterNeeds:
    return RosterNeeds({"QB": 2, "RB": 3 if shallow else 5, "WR": 5, "TE": 2}, {"QB": 1, "RB": 2, "WR": 2, "TE": 1}, {"QB": 1, "RB": 1, "WR": 3, "TE": 1}, ("RB",) if shallow else (), {"QB": 0, "RB": 0, "WR": 0, "TE": 0}, {"QB": 0, "RB": 0, "WR": 0, "TE": 0})


def integrate(injured, roster, available, *, role=True, shallow=True, roster_profiles=None):
    available_profiles = {available[0].player_id: profile()} if available and role else {}
    available_ops = {available[0].player_id: opportunity(available[0])} if available and role else {}
    return integrate_news_intelligence([], [news_fact(injured)], roster, {}, available, available_ops, available_profiles, roster_profiles or {}, needs(shallow=shallow), week=2)


def test_starter_injury_creates_corroborated_waiver_opportunity() -> None:
    injured, backup = Player("rb1", "Lead Runner", "RB", "LAR"), Player("rb2", "Next Runner", "RB", "LAR")
    result = integrate(injured, Roster([injured], []), [backup])
    waiver = next(item for item in result.feed if item.subject_player == backup)
    assert waiver.opportunity_type == "WAIVER_OPPORTUNITY"
    assert waiver.recommended_action == "CONSIDER_ADD"
    assert {signal.signal_type for signal in waiver.signals} >= {"NEWS_STATUS_REPORT", "AVAILABLE_IN_LEAGUE", "ROLE_EXPANSION", "ROSTER_DEPTH_PRESSURE"}
    assert any(text.startswith("Reported fact") for text in waiver.explanation_context)
    assert any(text.startswith("FanEdge inference") for text in waiver.explanation_context)
    assert serialize_impact_graph(result)["edges"]


def test_news_for_users_starter_creates_lineup_risk_without_fabricated_backup() -> None:
    injured = Player("rb1", "Lead Runner", "RB", "LAR")
    result = integrate(injured, Roster([injured], []), [])
    risk = result.feed[0]
    assert risk.opportunity_type == "INJURY_RISK"
    assert risk.recommended_action == "REVIEW"
    assert risk.related_player is None


def test_bench_news_is_relevant_but_not_promoted_to_start_action() -> None:
    injured = Player("rb1", "Bench Runner", "RB", "LAR")
    result = integrate(injured, Roster([], [injured]), [])
    assert result.feed[0].recommended_action == "MONITOR"
    assert "USER_BENCH" in result.feed[0].relevance


def test_owned_backup_is_monitored_instead_of_recommended_as_add() -> None:
    injured, backup = Player("rb1", "Lead Runner", "RB", "LAR"), Player("rb2", "Owned Backup", "RB", "LAR")
    result = integrate(injured, Roster([], [backup]), [], roster_profiles={backup.player_id: profile()})
    assert len(result.feed) == 1
    assert result.feed[0].subject_player == backup
    assert result.feed[0].recommended_action == "MONITOR"


def test_irrelevant_backup_without_role_evidence_creates_no_event() -> None:
    injured, backup = Player("rb1", "Lead Runner", "RB", "LAR"), Player("rb2", "Unknown Backup", "RB", "LAR")
    result = integrate(injured, Roster([], []), [backup], role=False)
    assert not result.feed
    assert not result.relevant_facts


def test_unrelated_team_news_is_suppressed() -> None:
    injured, other = Player("rb1", "Lead Runner", "RB", "LAR"), Player("rb2", "Other Runner", "RB", "NYG")
    assert not integrate(injured, Roster([], []), [other]).feed


def test_roster_weakness_increases_priority_and_relevance() -> None:
    injured, backup = Player("rb1", "Lead Runner", "RB", "LAR"), Player("rb2", "Next Runner", "RB", "LAR")
    strong = integrate(injured, Roster([], []), [backup], shallow=True).feed[0]
    quiet = integrate(injured, Roster([], []), [backup], shallow=False).feed[0]
    assert strong.priority == "HIGH"
    assert quiet.priority == "MEDIUM"
    assert "ROSTER_DEPTH_PRESSURE" in {signal.signal_type for signal in strong.signals}
    assert "ROSTER_DEPTH_PRESSURE" not in {signal.signal_type for signal in quiet.signals}


def test_same_news_event_is_stable_and_later_status_strengthens_memory(tmp_path) -> None:
    injured = Player("rb1", "Lead Runner", "RB", "LAR")
    repo, scope = SQLiteRepository(tmp_path / "memory.db"), LeagueScope("u", "l", 2026, 2)
    questionable = news_fact(injured, "QUESTIONABLE", fact_id="q")
    first_result = integrate_news_intelligence([], [questionable], Roster([injured], []), {}, [], {}, {}, {}, needs(), week=2)
    first = repo.reconcile(scope, first_result.feed, data_fresh=True, observation_id="one")
    out_result = integrate_news_intelligence([], [news_fact(injured, "OUT", fact_id="out")], Roster([injured], []), {}, [], {}, {}, {}, needs(), week=2)
    second = repo.reconcile(scope, out_result.feed, data_fresh=True, observation_id="two")
    assert first.current[0].event_key == second.current[0].event_key
    assert second.current[0].lifecycle in {Lifecycle.STRENGTHENED.value, Lifecycle.CHANGED.value}


def test_provider_failure_reuses_cached_fact_and_does_not_resolve(tmp_path) -> None:
    injured = Player("rb1", "Lead Runner", "RB", "LAR")
    repo, scope = SQLiteRepository(tmp_path / "memory.db"), LeagueScope("u", "l", 2026, 2)
    fact = news_fact(injured)
    repo.save_news_facts(scope, [fact])
    cached = repo.load_news_facts(scope)
    assert cached == (fact,)
    first_result = integrate_news_intelligence([], cached, Roster([injured], []), {}, [], {}, {}, {}, needs(), week=2)
    repo.reconcile(scope, first_result.feed, data_fresh=True, observation_id="one")
    failure = repo.reconcile(scope, first_result.feed, data_fresh=True, observation_id="two")
    assert failure.current[0].lifecycle == Lifecycle.ACTIVE.value


def test_stale_cached_fact_is_preserved_only_during_provider_failure() -> None:
    injured = Player("rb1", "Lead Runner", "RB", "LAR")
    stale = replace(news_fact(injured), freshness=Freshness.STALE.value)
    fresh_provider = integrate_news_intelligence([], [stale], Roster([injured], []), {}, [], {}, {}, {}, needs(), week=2)
    failed_provider = integrate_news_intelligence([], [replace(stale, provider_fresh=False)], Roster([injured], []), {}, [], {}, {}, {}, needs(), week=2)
    assert not fresh_provider.feed
    assert failed_provider.feed[0].opportunity_type == "INJURY_RISK"
