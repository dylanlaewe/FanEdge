from memory import (
    LeagueScope, Lifecycle, OutcomeStatus, classify_lifecycle,
    evaluate_lineup_outcome, evidence_fingerprint, stable_event_key,
)
from opportunity_engine import FantasyOpportunity, Signal
from sleeper_api import Player


def opportunity(*, kind="BREAKOUT_WATCH", related=None, priority="MEDIUM", action="MONITOR", value=6, week=5):
    player = Player("p1", "Player One", "WR", "LAR")
    signal = Signal("TARGET_INCREASE", "p1", "LAR", value, 4, value - 4, 4, "HIGH", "nflverse", week)
    return FantasyOpportunity(
        "watch:p1", kind, priority, player, related, (signal,),
        ("ON_USER_ROSTER",), action, "HIGH", (f"Targets increased: 4 → {value}",), week, week,
    )


def test_stable_event_identity_ignores_evidence_but_separates_type_and_related_player():
    scope = LeagueScope("user", "league", 2026, 5)
    first = opportunity(value=6)
    stronger = opportunity(value=9)
    other_type = opportunity(kind="ROLE_DECLINE")
    related = opportunity(related=Player("p2", "Player Two", "WR", "SF"))
    assert stable_event_key(scope, first) == stable_event_key(scope, stronger)
    assert stable_event_key(scope, first) != stable_event_key(scope, other_type)
    assert stable_event_key(scope, first) != stable_event_key(scope, related)


def test_fingerprint_ignores_observation_week_but_changes_with_meaningful_evidence():
    first = opportunity(value=6, week=5)
    later_same = opportunity(value=6, week=6)
    changed = opportunity(value=8, week=6)
    assert evidence_fingerprint(first) == evidence_fingerprint(later_same)
    assert evidence_fingerprint(first) != evidence_fingerprint(changed)


def test_lifecycle_rules_are_deterministic():
    assert classify_lifecycle(previous_fingerprint=None, current_fingerprint="a", previous_strength=None, current_strength=1, was_current=False) == Lifecycle.NEW
    assert classify_lifecycle(previous_fingerprint="a", current_fingerprint="a", previous_strength=1, current_strength=1, was_current=True) == Lifecycle.ACTIVE
    assert classify_lifecycle(previous_fingerprint="a", current_fingerprint="b", previous_strength=1, current_strength=2, was_current=True) == Lifecycle.STRENGTHENED
    assert classify_lifecycle(previous_fingerprint="a", current_fingerprint="b", previous_strength=2, current_strength=1, was_current=True) == Lifecycle.WEAKENED
    assert classify_lifecycle(previous_fingerprint="a", current_fingerprint="b", previous_strength=1, current_strength=1, was_current=True) == Lifecycle.CHANGED
    assert classify_lifecycle(previous_fingerprint="a", current_fingerprint="b", previous_strength=1, current_strength=1, was_current=False) == Lifecycle.REOPENED


def test_lineup_outcome_uses_neutral_observed_comparison_states():
    assert evaluate_lineup_outcome(18.4, 11.2, week_complete=True) == OutcomeStatus.RECOMMENDATION_OUTSCORED_ALTERNATIVE
    assert evaluate_lineup_outcome(7.0, 12.0, week_complete=True) == OutcomeStatus.ALTERNATIVE_OUTSCORED_RECOMMENDATION
    assert evaluate_lineup_outcome(10.0, 10.0, week_complete=True) == OutcomeStatus.TIED
    assert evaluate_lineup_outcome(None, 10.0, week_complete=True) == OutcomeStatus.UNAVAILABLE_GAME_DATA
    assert evaluate_lineup_outcome(10.0, 5.0, week_complete=False) == OutcomeStatus.UNRESOLVED_WEEK
