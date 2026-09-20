"""Deterministic signal, event, relevance, and fantasy-opportunity pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Iterable

from football_data import PlayerWeeklyContext
from intelligence import RoleProfile
from lineup_optimizer import LineupDecision, LineupSlot
from matchup import DefenseVsPosition
from opportunity import PlayerOpportunity
from sleeper_api import Player, Roster
from waiver_engine import RosterNeeds, WaiverCandidate


class SignalType(StrEnum):
    SNAP_SHARE_INCREASE = "SNAP_SHARE_INCREASE"
    SNAP_SHARE_DECREASE = "SNAP_SHARE_DECREASE"
    TARGET_INCREASE = "TARGET_INCREASE"
    TARGET_DECREASE = "TARGET_DECREASE"
    TOUCH_INCREASE = "TOUCH_INCREASE"
    TOUCH_DECREASE = "TOUCH_DECREASE"
    ATTEMPT_INCREASE = "ATTEMPT_INCREASE"
    ATTEMPT_DECREASE = "ATTEMPT_DECREASE"
    ROLE_EXPANSION = "ROLE_EXPANSION"
    ROLE_DECLINE = "ROLE_DECLINE"
    FANTASY_PRODUCTION_CHANGE = "FANTASY_PRODUCTION_CHANGE"
    INJURY_STATUS = "INJURY_STATUS"
    TEAMMATE_UNAVAILABLE = "TEAMMATE_UNAVAILABLE"
    FAVORABLE_MATCHUP = "FAVORABLE_MATCHUP"
    DIFFICULT_MATCHUP = "DIFFICULT_MATCHUP"
    BYE = "BYE"
    AVAILABLE_IN_LEAGUE = "AVAILABLE_IN_LEAGUE"
    ROSTER_DEPTH_PRESSURE = "ROSTER_DEPTH_PRESSURE"
    NEWS_STATUS_REPORT = "NEWS_STATUS_REPORT"
    NEWS_PRACTICE_REPORT = "NEWS_PRACTICE_REPORT"
    NEWS_ROLE_REPORT = "NEWS_ROLE_REPORT"
    NEWS_TRANSACTION_REPORT = "NEWS_TRANSACTION_REPORT"


class EventType(StrEnum):
    ROLE_CHANGE = "ROLE_CHANGE"
    OPPORTUNITY_CHANGE = "OPPORTUNITY_CHANGE"
    AVAILABILITY_CHANGE = "AVAILABILITY_CHANGE"
    MATCHUP_EVENT = "MATCHUP_EVENT"
    LINEUP_RISK = "LINEUP_RISK"
    BREAKOUT_WATCH = "BREAKOUT_WATCH"
    DECLINE_WATCH = "DECLINE_WATCH"


class OpportunityType(StrEnum):
    WAIVER_OPPORTUNITY = "WAIVER_OPPORTUNITY"
    LINEUP_OPPORTUNITY = "LINEUP_OPPORTUNITY"
    INJURY_RISK = "INJURY_RISK"
    BREAKOUT_WATCH = "BREAKOUT_WATCH"
    ROLE_DECLINE = "ROLE_DECLINE"
    MATCHUP_EDGE = "MATCHUP_EDGE"
    ROSTER_WEAKNESS = "ROSTER_WEAKNESS"


class Priority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Action(StrEnum):
    ADD = "ADD"
    CONSIDER_ADD = "CONSIDER_ADD"
    START = "START"
    CONSIDER_START = "CONSIDER_START"
    MONITOR = "MONITOR"
    HOLD = "HOLD"
    REVIEW = "REVIEW"
    NO_ACTION = "NO_ACTION"


class Relevance(StrEnum):
    ON_USER_ROSTER = "ON_USER_ROSTER"
    CURRENT_STARTER = "CURRENT_STARTER"
    USER_BENCH = "USER_BENCH"
    AVAILABLE_IN_LEAGUE = "AVAILABLE_IN_LEAGUE"
    SAME_POSITION_AS_ROSTER_WEAKNESS = "SAME_POSITION_AS_ROSTER_WEAKNESS"
    DIRECT_LINEUP_ALTERNATIVE = "DIRECT_LINEUP_ALTERNATIVE"
    TEAMMATE_OF_USER_PLAYER = "TEAMMATE_OF_USER_PLAYER"


@dataclass(frozen=True)
class Signal:
    signal_type: str
    player_id: str
    team: str
    current_value: Any
    baseline_value: Any
    magnitude: float | None
    sample_size: int
    evidence_quality: str
    source: str
    week: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpportunityEvent:
    event_type: str
    subject_player: Player
    supporting_signals: tuple[Signal, ...]
    evidence_quality: str
    summary_facts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "subject_player": asdict(self.subject_player),
            "supporting_signals": [signal.to_dict() for signal in self.supporting_signals],
            "evidence_quality": self.evidence_quality,
            "summary_facts": list(self.summary_facts),
        }


@dataclass(frozen=True)
class FantasyOpportunity:
    opportunity_id: str
    opportunity_type: str
    priority: str
    subject_player: Player | None
    related_player: Player | None
    signals: tuple[Signal, ...]
    relevance: tuple[str, ...]
    recommended_action: str
    confidence: str
    explanation_context: tuple[str, ...]
    first_seen_week: int | None = None
    last_seen_week: int | None = None
    resolved: bool | None = None
    action_taken: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["signals"] = [signal.to_dict() for signal in self.signals]
        return value


POSITIVE_CHANGE = {
    SignalType.SNAP_SHARE_INCREASE, SignalType.TARGET_INCREASE,
    SignalType.TOUCH_INCREASE, SignalType.ATTEMPT_INCREASE,
    SignalType.ROLE_EXPANSION, SignalType.TEAMMATE_UNAVAILABLE,
}
NEGATIVE_CHANGE = {
    SignalType.SNAP_SHARE_DECREASE, SignalType.TARGET_DECREASE,
    SignalType.TOUCH_DECREASE, SignalType.ATTEMPT_DECREASE, SignalType.ROLE_DECLINE,
}
PRIORITY_ORDER = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}


def _quality(values: Iterable[str]) -> str:
    qualities = list(values)
    if qualities and all(value == "HIGH" for value in qualities):
        return "HIGH"
    if any(value in {"HIGH", "MODERATE"} for value in qualities):
        return "MODERATE"
    return "LOW"


def _fact(signal: Signal) -> str:
    labels = {
        SignalType.SNAP_SHARE_INCREASE: "Snap share increased",
        SignalType.SNAP_SHARE_DECREASE: "Snap share decreased",
        SignalType.TARGET_INCREASE: "Targets increased",
        SignalType.TARGET_DECREASE: "Targets decreased",
        SignalType.TOUCH_INCREASE: "Touches increased",
        SignalType.TOUCH_DECREASE: "Touches decreased",
        SignalType.ATTEMPT_INCREASE: "Pass attempts increased",
        SignalType.ATTEMPT_DECREASE: "Pass attempts decreased",
        SignalType.ROLE_EXPANSION: "Role is expanding",
        SignalType.ROLE_DECLINE: "Role is declining",
        SignalType.TEAMMATE_UNAVAILABLE: "Same-position teammate became unavailable",
        SignalType.INJURY_STATUS: "Injury status requires attention",
        SignalType.FAVORABLE_MATCHUP: "Matchup grades favorable",
        SignalType.DIFFICULT_MATCHUP: "Matchup grades difficult",
    }
    label = labels.get(SignalType(signal.signal_type), signal.signal_type.replace("_", " ").title())
    if signal.baseline_value is not None and signal.current_value is not None:
        return f"{label}: {signal.baseline_value} → {signal.current_value}"
    return f"{label}: {signal.current_value}"


def detect_player_signals(
    player: Player,
    context: PlayerWeeklyContext | None,
    opportunity: PlayerOpportunity | None,
    profile: RoleProfile | None,
    *,
    matchup: DefenseVsPosition | None = None,
    available: bool = False,
    week: int | None = None,
) -> tuple[Signal, ...]:
    """Detect material changes only; state alone does not become a trend."""
    signals: list[Signal] = []
    quality = profile.evidence_quality if profile else "LOW"
    sample = max(opportunity.games if opportunity else 0, profile.current_games if profile else 0)

    def add(kind: SignalType, current: Any, baseline: Any, magnitude: float | None, source: str, *, signal_quality: str | None = None) -> None:
        signals.append(Signal(kind.value, player.player_id, player.team, current, baseline, magnitude, sample, signal_quality or quality, source, week))

    participation = profile.participation if profile else None
    if participation and participation.games >= 4 and participation.recent_snap_share is not None and participation.season_snap_share is not None:
        delta = participation.recent_snap_share - participation.season_snap_share
        if participation.trend == "ROLE EXPANDING" and delta >= .06:
            add(SignalType.SNAP_SHARE_INCREASE, round(participation.recent_snap_share, 2), round(participation.season_snap_share, 2), round(delta, 2), "nflverse snap counts")
        elif participation.trend == "ROLE SHRINKING" and delta <= -.06:
            add(SignalType.SNAP_SHARE_DECREASE, round(participation.recent_snap_share, 2), round(participation.season_snap_share, 2), round(abs(delta), 2), "nflverse snap counts")

    if opportunity and opportunity.games >= 4:
        if player.position == "QB":
            current, baseline, threshold = opportunity.recent_attempts, opportunity.season_attempts, 2.5
            increase, decrease = SignalType.ATTEMPT_INCREASE, SignalType.ATTEMPT_DECREASE
        elif player.position == "RB":
            current, baseline, threshold = opportunity.recent_touches, opportunity.season_touches, 1.0
            increase, decrease = SignalType.TOUCH_INCREASE, SignalType.TOUCH_DECREASE
        else:
            current, baseline, threshold = opportunity.recent_targets, opportunity.season_targets, .75
            increase, decrease = SignalType.TARGET_INCREASE, SignalType.TARGET_DECREASE
        if current is not None and baseline is not None:
            delta = current - baseline
            if opportunity.usage_trend == "RISING" and delta >= threshold:
                add(increase, current, baseline, round(delta, 1), "nflverse player stats")
            elif opportunity.usage_trend == "FALLING" and delta <= -threshold:
                add(decrease, current, baseline, round(abs(delta), 1), "nflverse player stats")

    if profile and profile.current_games >= 4:
        if profile.role_trend == "ROLE EXPANDING":
            add(SignalType.ROLE_EXPANSION, profile.role, None, None, "FanEdge role model")
        elif profile.role_trend == "ROLE SHRINKING":
            add(SignalType.ROLE_DECLINE, profile.role, None, None, "FanEdge role model")
    if context and context.season_stats and context.season_stats.games_played >= 4:
        production_delta = context.season_stats.recent_average - context.season_stats.season_average
        if context.season_stats.trend in {"up", "down"} and abs(production_delta) >= 2:
            add(SignalType.FANTASY_PRODUCTION_CHANGE, context.season_stats.recent_average, context.season_stats.season_average, round(abs(production_delta), 1), "nflverse player stats + league scoring")
    if context:
        status = str(context.status or "").lower()
        if status in {"questionable", "doubtful", "out", "ir", "pup"}:
            add(SignalType.INJURY_STATUS, status.upper(), None, {"questionable": 1, "doubtful": 2, "out": 3, "ir": 3, "pup": 3}[status], "Sleeper player status", signal_quality="HIGH")
        if context.is_bye:
            add(SignalType.BYE, "BYE", "SCHEDULED", 3, "validated nflverse schedule", signal_quality="HIGH")
    if profile:
        for change in profile.teammate_changes[:2]:
            add(SignalType.TEAMMATE_UNAVAILABLE, f"{change.teammate}: {change.current_status}", change.previous_status, 1, change.source)
    if matchup and matchup.label in {"FAVORABLE", "DIFFICULT"}:
        kind = SignalType.FAVORABLE_MATCHUP if matchup.label == "FAVORABLE" else SignalType.DIFFICULT_MATCHUP
        matchup_quality = "HIGH" if matchup.games >= 8 and matchup.evidence_basis == "CURRENT" else "MODERATE"
        add(kind, matchup.label, "LEAGUE AVERAGE", abs(matchup.relative_to_league_average), "nflverse defense-vs-position + league scoring", signal_quality=matchup_quality)
    if available:
        add(SignalType.AVAILABLE_IN_LEAGUE, "AVAILABLE", None, None, "Sleeper league ownership", signal_quality="HIGH")
    return tuple(signals)


def combine_signals_into_events(player: Player, signals: Iterable[Signal]) -> tuple[OpportunityEvent, ...]:
    """Corroboration creates events; weak or contradictory trend evidence is suppressed."""
    values = tuple(signals)
    positive = tuple(signal for signal in values if SignalType(signal.signal_type) in POSITIVE_CHANGE)
    negative = tuple(signal for signal in values if SignalType(signal.signal_type) in NEGATIVE_CHANGE)
    events: list[OpportunityEvent] = []
    positive_types = {signal.signal_type for signal in positive}
    negative_types = {signal.signal_type for signal in negative}
    if len(positive_types) >= 2 and not negative:
        events.append(OpportunityEvent(EventType.BREAKOUT_WATCH.value, player, positive, _quality(signal.evidence_quality for signal in positive), tuple(_fact(signal) for signal in positive)))
    elif len(negative_types) >= 2 and not positive:
        events.append(OpportunityEvent(EventType.DECLINE_WATCH.value, player, negative, _quality(signal.evidence_quality for signal in negative), tuple(_fact(signal) for signal in negative)))
    injuries = tuple(signal for signal in values if signal.signal_type in {SignalType.INJURY_STATUS.value, SignalType.BYE.value})
    if injuries:
        events.append(OpportunityEvent(EventType.AVAILABILITY_CHANGE.value, player, injuries, _quality(signal.evidence_quality for signal in injuries), tuple(_fact(signal) for signal in injuries)))
    matchup = tuple(signal for signal in values if signal.signal_type in {SignalType.FAVORABLE_MATCHUP.value, SignalType.DIFFICULT_MATCHUP.value})
    if matchup:
        events.append(OpportunityEvent(EventType.MATCHUP_EVENT.value, player, matchup, _quality(signal.evidence_quality for signal in matchup), tuple(_fact(signal) for signal in matchup)))
    return tuple(events)


def priority_from(*, actionability: int, relevance: int, evidence: int, urgency: int) -> str:
    total = actionability + relevance + evidence + urgency
    return (Priority.CRITICAL if total >= 11 else Priority.HIGH if total >= 8 else Priority.MEDIUM if total >= 5 else Priority.LOW).value


def _eligible_replacement(player: Player, slot: LineupSlot | None, roster: Roster, contexts: dict[str, PlayerWeeklyContext]) -> Player | None:
    eligible = slot.eligible_positions if slot else (player.position,)
    for candidate in roster.bench:
        context = contexts.get(candidate.player_id)
        unavailable = str(context.status or "").lower() in {"out", "ir", "pup", "doubtful"} if context else False
        if candidate.position in eligible and not unavailable and not (context and context.is_bye):
            return candidate
    return None


def build_opportunity_feed(
    roster: Roster,
    contexts: dict[str, PlayerWeeklyContext],
    opportunities: dict[str, PlayerOpportunity],
    profiles: dict[str, RoleProfile],
    lineup_slots: list[LineupSlot],
    lineup_decisions: list[LineupDecision],
    waiver_candidates: list[WaiverCandidate],
    available_opportunities: dict[str, PlayerOpportunity],
    roster_needs: RosterNeeds,
    matchup_index: dict[tuple[str, str], DefenseVsPosition],
    *,
    week: int | None = None,
) -> list[FantasyOpportunity]:
    """Build a quiet-by-default, user-specific feed from deterministic evidence."""
    result: list[FantasyOpportunity] = []
    starters = {player.player_id for player in roster.starters}
    slots_by_player = {slot.current_player.player_id: slot for slot in lineup_slots if slot.current_player}

    for decision in lineup_decisions:
        related = decision.starter
        signals = tuple(Signal(code, decision.challenger.player_id, decision.challenger.team, reason, None, decision.difference, len(decision.evidence), decision.confidence, "FanEdge lineup optimizer", week) for code, reason in zip(decision.reason_codes, decision.reasons))
        priority = Priority.HIGH.value if decision.label == "STRONG SWAP" else Priority.MEDIUM.value
        result.append(FantasyOpportunity(
            f"lineup:{decision.slot_id}:{decision.challenger.player_id}", OpportunityType.LINEUP_OPPORTUNITY.value,
            priority, decision.challenger, related, signals,
            (Relevance.DIRECT_LINEUP_ALTERNATIVE.value, Relevance.USER_BENCH.value),
            Action.START.value if decision.label == "STRONG SWAP" else Action.CONSIDER_START.value,
            decision.confidence, tuple(decision.reasons), week, week,
        ))

    for player in (*roster.starters, *roster.bench):
        context = contexts.get(player.player_id)
        matchup = matchup_index.get((context.opponent, player.position)) if context and context.opponent else None
        signals = detect_player_signals(player, context, opportunities.get(player.player_id), profiles.get(player.player_id), matchup=matchup, week=week)
        events = combine_signals_into_events(player, signals)
        rel = (Relevance.ON_USER_ROSTER.value, Relevance.CURRENT_STARTER.value if player.player_id in starters else Relevance.USER_BENCH.value)
        availability_event = next((event for event in events if event.event_type == EventType.AVAILABILITY_CHANGE.value), None)
        if availability_event:
            starter = player.player_id in starters
            replacement = _eligible_replacement(player, slots_by_player.get(player.player_id), roster, contexts) if starter else None
            status = str(context.status or "").lower() if context else ""
            if not starter and status != "questionable":
                continue
            severe = status in {"out", "ir", "pup", "doubtful"} or bool(context and context.is_bye)
            priority = priority_from(actionability=3 if starter else 1, relevance=3 if starter else 1, evidence=3 if starter else 2, urgency=3 if severe and starter else 0)
            action = Action.REVIEW.value if starter else Action.MONITOR.value
            facts = list(availability_event.summary_facts)
            if starter:
                facts.append(f"Eligible bench replacement: {replacement.name}" if replacement else "No eligible healthy bench replacement found")
            result.append(FantasyOpportunity(f"injury:{player.player_id}", OpportunityType.INJURY_RISK.value, priority, player, replacement, availability_event.supporting_signals, rel, action, availability_event.evidence_quality, tuple(facts), week, week))
        decline = next((event for event in events if event.event_type == EventType.DECLINE_WATCH.value), None)
        if decline:
            priority = Priority.MEDIUM.value if player.player_id in starters else Priority.LOW.value
            result.append(FantasyOpportunity(f"decline:{player.player_id}", OpportunityType.ROLE_DECLINE.value, priority, player, None, decline.supporting_signals, rel, Action.MONITOR.value, decline.evidence_quality, decline.summary_facts, week, week))

    for candidate in waiver_candidates:
        player, context, profile = candidate.player, candidate.context, candidate.intelligence
        matchup = matchup_index.get((context.opponent, player.position)) if context.opponent else None
        signals = detect_player_signals(player, context, available_opportunities.get(player.player_id), profile, matchup=matchup, available=True, week=week)
        events = combine_signals_into_events(player, signals)
        breakout = next((event for event in events if event.event_type == EventType.BREAKOUT_WATCH.value), None)
        if not breakout:
            continue
        weakness = player.position in roster_needs.shallow_depth_positions
        relevance = [Relevance.AVAILABLE_IN_LEAGUE.value]
        if weakness:
            relevance.append(Relevance.SAME_POSITION_AS_ROSTER_WEAKNESS.value)
        production = context.season_stats
        production_lagging = not production or production.recent_average <= production.season_average + 2
        opportunity_type = OpportunityType.BREAKOUT_WATCH.value if production_lagging and not weakness else OpportunityType.WAIVER_OPPORTUNITY.value
        action = Action.CONSIDER_ADD.value if weakness or len(breakout.supporting_signals) >= 3 else Action.MONITOR.value
        priority = priority_from(actionability=2 if action == Action.CONSIDER_ADD else 1, relevance=3 if weakness else 2, evidence=3 if breakout.evidence_quality == "HIGH" else 2, urgency=1)
        facts = list(breakout.summary_facts)
        facts.append("Available in this league")
        if weakness:
            facts.append(f"Your {player.position} depth is shallow")
        if production_lagging:
            facts.append("Opportunity is improving before production has clearly separated")
        result.append(FantasyOpportunity(f"waiver:{player.player_id}", opportunity_type, priority, player, None, breakout.supporting_signals, tuple(relevance), action, breakout.evidence_quality, tuple(facts), week, week))

    result.sort(key=lambda item: (PRIORITY_ORDER[Priority(item.priority)], item.opportunity_type, item.subject_player.name.lower() if item.subject_player else "", item.opportunity_id))
    return result[:7]
