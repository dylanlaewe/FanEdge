import sqlite3

import pytest

from memory import FeedbackStatus, LeagueScope, Lifecycle, OutcomeStatus
from opportunity_engine import FantasyOpportunity, Signal
from sleeper_api import Player
from storage import SQLiteRepository


def item(*, priority="MEDIUM", action="MONITOR", value=6, kind="BREAKOUT_WATCH", related=None):
    player = Player("p1", "Player One", "WR", "LAR")
    signal = Signal("TARGET_INCREASE", "p1", "LAR", value, 4, value - 4, 4, "HIGH", "nflverse", 5)
    return FantasyOpportunity(
        "watch:p1", kind, priority, player, related, (signal,),
        ("ON_USER_ROSTER",), action, "HIGH", (f"Targets increased: 4 → {value}",), 5, 5,
    )


@pytest.fixture
def repository(tmp_path):
    return SQLiteRepository(tmp_path / "memory.db")


@pytest.fixture
def scope():
    return LeagueScope("user", "league", 2026, 5)


def test_schema_initializes_and_duplicate_snapshot_is_idempotent(repository, scope):
    assert repository.schema_version() == 1
    first = repository.reconcile(scope, [item()], data_fresh=True, captured_at="2026-09-01T12:00:00+00:00")
    second = repository.reconcile(scope, [item()], data_fresh=True, captured_at="2026-09-01T12:05:00+00:00")
    assert first.current[0].lifecycle == Lifecycle.NEW
    assert second.current[0].lifecycle == Lifecycle.ACTIVE
    assert repository.snapshot_count(scope) == 1
    assert len(repository.journal(scope)) == 1


def test_users_and_leagues_are_isolated(repository, scope):
    repository.reconcile(scope, [item()], data_fresh=True)
    other_user = LeagueScope("other", "league", 2026, 5)
    other_league = LeagueScope("user", "other-league", 2026, 5)
    repository.reconcile(other_user, [item()], data_fresh=True)
    repository.reconcile(other_league, [item()], data_fresh=True)
    assert len(repository.journal(scope)) == 1
    assert len(repository.journal(other_user)) == 1
    assert len(repository.journal(other_league)) == 1
    assert len({repository.journal(value)[0].event_key for value in (scope, other_user, other_league)}) == 3


def test_strengthen_weaken_resolve_and_reopen_lifecycle(repository, scope):
    new = repository.reconcile(scope, [item(priority="LOW")], data_fresh=True, observation_id="one")
    strengthened = repository.reconcile(scope, [item(priority="HIGH", action="CONSIDER_ADD", value=8)], data_fresh=True, observation_id="two")
    weakened = repository.reconcile(scope, [item(priority="MEDIUM", action="MONITOR", value=7)], data_fresh=True, observation_id="three")
    first_missing = repository.reconcile(scope, [], data_fresh=True, observation_id="four")
    resolved = repository.reconcile(scope, [], data_fresh=True, observation_id="five")
    reopened = repository.reconcile(scope, [item(priority="MEDIUM", value=7)], data_fresh=True, observation_id="six")
    assert new.current[0].lifecycle == Lifecycle.NEW
    assert strengthened.current[0].lifecycle == Lifecycle.STRENGTHENED
    assert weakened.current[0].lifecycle == Lifecycle.WEAKENED
    assert not first_missing.changes
    assert resolved.changes[0].lifecycle == Lifecycle.RESOLVED
    assert reopened.current[0].lifecycle == Lifecycle.REOPENED


def test_provider_failure_does_not_resolve_or_advance_missing_count(repository, scope):
    repository.reconcile(scope, [item()], data_fresh=True, observation_id="initial")
    for index in range(3):
        result = repository.reconcile(scope, [], data_fresh=False, observation_id=f"failed-{index}")
        assert not result.changes
        assert result.current[0].freshness == "UNCERTAIN"
        assert result.current[0].opportunity.priority == "MEDIUM"
    first_fresh = repository.reconcile(scope, [], data_fresh=True, observation_id="fresh-one")
    assert not first_fresh.changes
    assert repository.journal(scope)[0].lifecycle != Lifecycle.RESOLVED


def test_duplicate_rerun_cannot_resolve_event(repository, scope):
    repository.reconcile(scope, [item()], data_fresh=True, observation_id="initial")
    repository.reconcile(scope, [], data_fresh=True, observation_id="missing-one")
    duplicate = repository.reconcile(scope, [], data_fresh=True, observation_id="missing-one")
    assert not duplicate.changes
    assert repository.journal(scope)[0].lifecycle != Lifecycle.RESOLVED


def test_injury_resolves_only_after_two_distinct_fresh_observations(repository, scope):
    injury = item(kind="INJURY_RISK", action="REVIEW")
    repository.reconcile(scope, [injury], data_fresh=True, observation_id="initial")
    repository.reconcile(scope, [], data_fresh=True, observation_id="fresh-one")
    resolved = repository.reconcile(scope, [], data_fresh=True, observation_id="fresh-two")
    assert resolved.changes[0].opportunity.opportunity_type == "INJURY_RISK"
    assert resolved.changes[0].lifecycle == Lifecycle.RESOLVED


@pytest.mark.parametrize("status", [FeedbackStatus.SAVED, FeedbackStatus.DISMISSED, FeedbackStatus.DONE])
def test_feedback_is_upserted_safely(repository, scope, status):
    result = repository.reconcile(scope, [item()], data_fresh=True)
    event_key = result.current[0].event_key
    repository.record_feedback(scope, event_key, status)
    repository.record_feedback(scope, event_key, status)
    assert repository.feedback_for(event_key) == status
    assert repository.journal(scope)[0].feedback == status


def test_outcome_is_attached_to_structured_decision(repository, scope):
    lineup = item(kind="LINEUP_OPPORTUNITY", related=Player("p2", "Alternative", "WR", "SF"), action="CONSIDER_START")
    repository.reconcile(scope, [lineup], data_fresh=True)
    pending = repository.pending_lineup_decisions(scope, before_week=6)
    assert len(pending) == 1
    repository.record_outcome(pending[0]["decision_key"], OutcomeStatus.RECOMMENDATION_OUTSCORED_ALTERNATIVE, 18.4, 11.2)
    entry = repository.journal(scope)[0]
    assert entry.outcome == OutcomeStatus.RECOMMENDATION_OUTSCORED_ALTERNATIVE
    assert entry.recommended_points == 18.4
    assert entry.alternative_points == 11.2


def test_analytics_records_events_idempotently_and_rejects_sensitive_metadata(repository, scope):
    repository.record_analytics(scope, "overview_viewed", metadata={"items": 2}, idempotency_key="view-1")
    repository.record_analytics(scope, "overview_viewed", metadata={"items": 2}, idempotency_key="view-1")
    assert repository.analytics_count("overview_viewed") == 1
    with pytest.raises(ValueError):
        repository.record_analytics(scope, "bad", metadata={"api_token": "secret"})
    with sqlite3.connect(repository.path) as connection:
        raw = connection.execute("SELECT metadata_json FROM analytics_events").fetchone()[0]
    assert "secret" not in raw
