"""Pure temporal models for FanEdge intelligence memory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from opportunity_engine import FantasyOpportunity


class Lifecycle(StrEnum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    STRENGTHENED = "STRENGTHENED"
    WEAKENED = "WEAKENED"
    CHANGED = "CHANGED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class FeedbackStatus(StrEnum):
    SAVED = "SAVED"
    DONE = "DONE"
    DISMISSED = "DISMISSED"


class OutcomeStatus(StrEnum):
    RECOMMENDATION_OUTSCORED_ALTERNATIVE = "RECOMMENDATION_OUTSCORED_ALTERNATIVE"
    ALTERNATIVE_OUTSCORED_RECOMMENDATION = "ALTERNATIVE_OUTSCORED_RECOMMENDATION"
    TIED = "TIED"
    UNAVAILABLE_GAME_DATA = "UNAVAILABLE_GAME_DATA"
    UNRESOLVED_WEEK = "UNRESOLVED_WEEK"


@dataclass(frozen=True)
class LeagueScope:
    sleeper_user_id: str
    league_id: str
    season: int
    week: int


@dataclass(frozen=True)
class TemporalOpportunity:
    opportunity: FantasyOpportunity
    event_key: str
    lifecycle: str
    first_seen: str
    last_seen: str
    freshness: str = "FRESH"
    feedback: str | None = None


@dataclass(frozen=True)
class TemporalSummary:
    new: int = 0
    strengthened: int = 0
    weakened: int = 0
    changed: int = 0
    resolved: int = 0
    reopened: int = 0


@dataclass(frozen=True)
class ReconciliationResult:
    snapshot_id: int
    has_previous_snapshot: bool
    current: tuple[TemporalOpportunity, ...]
    changes: tuple[TemporalOpportunity, ...]
    summary: TemporalSummary


@dataclass(frozen=True)
class JournalEntry:
    event_key: str
    opportunity_type: str
    subject_name: str | None
    related_name: str | None
    priority: str
    action: str
    confidence: str
    lifecycle: str
    week: int
    first_seen: str
    last_seen: str
    feedback: str | None
    outcome: str | None
    recommended_points: float | None
    alternative_points: float | None
    evidence: tuple[str, ...]


PRIORITY_STRENGTH = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
ACTION_STRENGTH = {
    "NO_ACTION": 0, "MONITOR": 1, "HOLD": 1, "REVIEW": 2,
    "CONSIDER_ADD": 2, "CONSIDER_START": 2, "ADD": 3, "START": 3,
}
CONFIDENCE_STRENGTH = {"LOW": 1, "MODERATE": 2, "HIGH": 3}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def stable_event_key(scope: LeagueScope, item: FantasyOpportunity) -> str:
    """Identify a conceptual event independently from changing evidence."""
    slot = item.opportunity_id.split(":", 2)[1] if item.opportunity_id.startswith("lineup:") else None
    identity = {
        "user": scope.sleeper_user_id,
        "league": scope.league_id,
        "season": scope.season,
        "type": item.opportunity_type,
        "subject": item.subject_player.player_id if item.subject_player else None,
        "related": item.related_player.player_id if item.related_player else None,
        "slot": slot,
    }
    return f"fe1:{_digest(identity)[:24]}"


def evidence_payload(item: FantasyOpportunity) -> dict[str, Any]:
    """Return meaningful evidence only; run timestamps and observed week are excluded."""
    signals = [
        {
            "type": signal.signal_type,
            "player": signal.player_id,
            "team": signal.team,
            "current": signal.current_value,
            "baseline": signal.baseline_value,
            "magnitude": signal.magnitude,
            "sample_size": signal.sample_size,
            "quality": signal.evidence_quality,
            "source": signal.source,
        }
        for signal in item.signals
    ]
    signals.sort(key=lambda value: _canonical(value))
    return {
        "signals": signals,
        "facts": sorted(item.explanation_context),
        "priority": item.priority,
        "action": item.recommended_action,
        "confidence": item.confidence,
        "relevance": sorted(item.relevance),
    }


def evidence_fingerprint(item: FantasyOpportunity) -> str:
    return _digest(evidence_payload(item))


def feed_fingerprint(items: Iterable[FantasyOpportunity]) -> str:
    payload = sorted((item.opportunity_id, evidence_fingerprint(item)) for item in items)
    return _digest(payload)


def evidence_strength(item: FantasyOpportunity) -> int:
    distinct_signals = len({signal.signal_type for signal in item.signals})
    return (
        PRIORITY_STRENGTH.get(item.priority, 0) * 1000
        + ACTION_STRENGTH.get(item.recommended_action, 0) * 100
        + CONFIDENCE_STRENGTH.get(item.confidence, 0) * 10
        + min(distinct_signals, 9)
    )


def classify_lifecycle(
    *, previous_fingerprint: str | None, current_fingerprint: str,
    previous_strength: int | None, current_strength: int, was_current: bool,
) -> Lifecycle:
    if previous_fingerprint is None:
        return Lifecycle.NEW
    if not was_current:
        return Lifecycle.REOPENED
    if previous_fingerprint == current_fingerprint:
        return Lifecycle.ACTIVE
    if current_strength > (previous_strength or 0):
        return Lifecycle.STRENGTHENED
    if current_strength < (previous_strength or 0):
        return Lifecycle.WEAKENED
    return Lifecycle.CHANGED


def evaluate_lineup_outcome(
    recommended_points: float | None,
    alternative_points: float | None,
    *,
    week_complete: bool,
) -> OutcomeStatus:
    """Compare observed scores neutrally; this is not a causal success claim."""
    if not week_complete:
        return OutcomeStatus.UNRESOLVED_WEEK
    if recommended_points is None or alternative_points is None:
        return OutcomeStatus.UNAVAILABLE_GAME_DATA
    if recommended_points > alternative_points:
        return OutcomeStatus.RECOMMENDATION_OUTSCORED_ALTERNATIVE
    if alternative_points > recommended_points:
        return OutcomeStatus.ALTERNATIVE_OUTSCORED_RECOMMENDATION
    return OutcomeStatus.TIED
