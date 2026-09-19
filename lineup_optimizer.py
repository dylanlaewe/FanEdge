"""League-slot-aware deterministic lineup comparison engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

from football_data import PlayerWeeklyContext
from matchup import DefenseVsPosition
from opportunity import PlayerOpportunity
from sleeper_api import Player, Roster


SLOT_ELIGIBILITY = {
    "QB": ("QB",), "RB": ("RB",), "WR": ("WR",), "TE": ("TE",),
    "K": ("K",), "DEF": ("DEF",),
    "FLEX": ("RB", "WR", "TE"), "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"), "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}


class ReasonCode(StrEnum):
    HIGHER_RECENT_PRODUCTION = "HIGHER_RECENT_PRODUCTION"
    HIGHER_SEASON_PRODUCTION = "HIGHER_SEASON_PRODUCTION"
    MORE_TARGETS = "MORE_TARGETS"
    MORE_TOUCHES = "MORE_TOUCHES"
    MORE_ATTEMPTS = "MORE_ATTEMPTS"
    RISING_USAGE = "RISING_USAGE"
    STARTER_INJURY = "STARTER_INJURY"
    BENCH_PLAYER_HEALTHIER = "BENCH_PLAYER_HEALTHIER"
    STARTER_BYE = "STARTER_BYE"
    FAVORABLE_MATCHUP = "FAVORABLE_MATCHUP"


@dataclass(frozen=True)
class DecisionEvidence:
    category: str
    label: str
    factual_value: str
    comparison: str
    source_type: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class LineupSlot:
    slot_id: str
    slot_type: str
    eligible_positions: tuple[str, ...]
    current_player: Player | None


@dataclass(frozen=True)
class LineupDecision:
    slot_id: str
    slot_type: str
    starter: Player | None
    challenger: Player
    label: str
    difference: float
    reasons: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    evidence: tuple[DecisionEvidence, ...] = ()
    confidence: str = "LOW"

    def to_dict(self, contexts: dict[str, PlayerWeeklyContext], opportunities: dict[str, PlayerOpportunity]) -> dict[str, Any]:
        def player_data(player: Player | None) -> dict[str, Any] | None:
            if not player:
                return None
            context = contexts.get(player.player_id)
            return {
                **asdict(player),
                "weekly": context.to_dict() if context else None,
                "opportunity": opportunities[player.player_id].to_dict() if player.player_id in opportunities else None,
            }
        return {
            "slot_id": self.slot_id, "slot_type": self.slot_type,
            "starter": player_data(self.starter), "challenger": player_data(self.challenger),
            "label": self.label, "difference": self.difference, "reasons": list(self.reasons),
            "reason_codes": list(self.reason_codes),
            "evidence": [item.to_dict() for item in self.evidence],
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class LineupHealth:
    decisions: int
    injury_watches: int
    bye_conflicts: int


def normalize_lineup_slots(roster_positions: list[Any]) -> list[tuple[str, tuple[str, ...]]]:
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for raw in roster_positions:
        slot = str(raw or "").upper()
        if slot in {"BN", "IR", "TAXI"}:
            continue
        if slot in SLOT_ELIGIBILITY:
            normalized.append((slot, SLOT_ELIGIBILITY[slot]))
    return normalized


def build_current_lineup(raw_roster: dict[str, Any], metadata: dict[str, dict[str, Any]], roster_positions: list[Any]) -> list[LineupSlot]:
    definitions = normalize_lineup_slots(roster_positions)
    starter_ids = raw_roster.get("starters") if isinstance(raw_roster.get("starters"), list) else []
    counts: dict[str, int] = {}
    slots: list[LineupSlot] = []
    for index, (slot_type, eligible) in enumerate(definitions):
        counts[slot_type] = counts.get(slot_type, 0) + 1
        player_id = str(starter_ids[index]) if index < len(starter_ids) and starter_ids[index] not in (None, "0", 0) else None
        raw = metadata.get(player_id or "", {})
        name = str(raw.get("full_name") or " ".join(str(raw.get(k) or "") for k in ("first_name", "last_name"))).strip()
        player = Player(player_id, name or f"Unknown player ({player_id})", str(raw.get("position") or "—"), str(raw.get("team") or "FA")) if player_id else None
        slots.append(LineupSlot(f"{slot_type}{counts[slot_type]}", slot_type, eligible, player))
    return slots


def _usage_value(player: Player, opportunity: PlayerOpportunity | None) -> float:
    if not opportunity:
        return 0.0
    if player.position == "QB":
        return (opportunity.recent_attempts or 0) * 0.08 + (opportunity.recent_carries or 0) * 0.35
    if player.position == "RB":
        return (opportunity.recent_carries or 0) * 0.45 + (opportunity.recent_targets or 0) * 0.65
    return (opportunity.recent_targets or 0) * 0.8 + (opportunity.recent_receptions or 0) * 0.35


def comparison_score(
    player: Player, context: PlayerWeeklyContext | None, opportunity: PlayerOpportunity | None,
    matchup: DefenseVsPosition | None = None,
) -> float:
    if not context:
        return 0.0
    summary = context.season_stats
    production = 0.0
    if summary:
        confidence = min(1.0, 0.6 + 0.1 * summary.games_played)
        production = ((0.65 * summary.recent_average) + (0.35 * summary.season_average)) * confidence
    usage = _usage_value(player, opportunity)
    usage_trend = 1.5 if opportunity and opportunity.usage_trend == "RISING" else -1.5 if opportunity and opportunity.usage_trend == "FALLING" else 0.0
    status = str(context.status or "").lower()
    availability = {"questionable": -2.0, "doubtful": -8.0, "out": -100.0, "ir": -100.0, "pup": -100.0}.get(status, 0.0)
    if context.is_bye:
        availability = -100.0
    matchup_adjustment = 2.0 if matchup and matchup.label == "FAVORABLE" else -2.0 if matchup and matchup.label == "DIFFICULT" else 0.0
    return round(production + usage + usage_trend + availability + matchup_adjustment, 2)


def _matchup_for(player: Player, context: PlayerWeeklyContext | None, matchups: dict[tuple[str, str], DefenseVsPosition]) -> DefenseVsPosition | None:
    return matchups.get((context.opponent, player.position)) if context and context.opponent else None


def _decision_evidence(
    starter: Player | None, challenger: Player,
    contexts: dict[str, PlayerWeeklyContext], opportunities: dict[str, PlayerOpportunity],
    matchups: dict[tuple[str, str], DefenseVsPosition],
) -> tuple[tuple[str, ...], tuple[DecisionEvidence, ...]]:
    codes: list[str] = []
    evidence: list[DecisionEvidence] = []
    starter_context = contexts.get(starter.player_id) if starter else None
    challenger_context = contexts.get(challenger.player_id)
    starter_summary = starter_context.season_stats if starter_context else None
    challenger_summary = challenger_context.season_stats if challenger_context else None
    if starter_summary and challenger_summary:
        if challenger_summary.recent_average - starter_summary.recent_average >= 2:
            codes.append(ReasonCode.HIGHER_RECENT_PRODUCTION.value)
            evidence.append(DecisionEvidence("PRODUCTION", "Higher recent production", f"{challenger_summary.recent_average:.1f} points/game", f"vs {starter_summary.recent_average:.1f}", "nflverse player stats + league scoring"))
        if min(challenger_summary.games_played, starter_summary.games_played) >= 2 and challenger_summary.season_average - starter_summary.season_average >= 2:
            codes.append(ReasonCode.HIGHER_SEASON_PRODUCTION.value)
            evidence.append(DecisionEvidence("PRODUCTION", "Higher season production", f"{challenger_summary.season_average:.1f} points/game", f"vs {starter_summary.season_average:.1f}", "nflverse player stats + league scoring"))
    starter_opp = opportunities.get(starter.player_id) if starter else None
    challenger_opp = opportunities.get(challenger.player_id)
    if starter and starter.position == challenger.position and starter_opp and challenger_opp:
        if challenger.position == "RB" and (challenger_opp.recent_touches or 0) - (starter_opp.recent_touches or 0) >= 1.5:
            codes.append(ReasonCode.MORE_TOUCHES.value)
            evidence.append(DecisionEvidence("OPPORTUNITY", "More recent touches", f"{challenger_opp.recent_touches:.1f}/game", f"vs {starter_opp.recent_touches:.1f}/game", "nflverse player stats"))
        elif challenger.position in {"WR", "TE"} and (challenger_opp.recent_targets or 0) - (starter_opp.recent_targets or 0) >= 1.5:
            codes.append(ReasonCode.MORE_TARGETS.value)
            evidence.append(DecisionEvidence("OPPORTUNITY", "More recent targets", f"{challenger_opp.recent_targets:.1f}/game", f"vs {starter_opp.recent_targets:.1f}/game", "nflverse player stats"))
        elif challenger.position == "QB" and (challenger_opp.recent_attempts or 0) - (starter_opp.recent_attempts or 0) >= 3:
            codes.append(ReasonCode.MORE_ATTEMPTS.value)
            evidence.append(DecisionEvidence("OPPORTUNITY", "More recent attempts", f"{challenger_opp.recent_attempts:.1f}/game", f"vs {starter_opp.recent_attempts:.1f}/game", "nflverse player stats"))
    if challenger_opp and challenger_opp.usage_trend == "RISING":
        codes.append(ReasonCode.RISING_USAGE.value)
        evidence.append(DecisionEvidence("USAGE_TREND", "Rising usage", "RISING", "four-game minimum satisfied", "derived by FanEdge"))
    starter_status = str(starter_context.status or "").lower() if starter_context else ""
    challenger_status = str(challenger_context.status or "").lower() if challenger_context else ""
    if starter_context and starter_context.is_bye:
        codes.append(ReasonCode.STARTER_BYE.value)
        evidence.append(DecisionEvidence("BYE", "Verified starter bye", starter_context.schedule_status, "challenger is scheduled", "nflverse schedule + FanEdge integrity validation"))
    elif starter_status in {"out", "ir", "pup", "doubtful", "questionable"}:
        codes.extend((ReasonCode.STARTER_INJURY.value, ReasonCode.BENCH_PLAYER_HEALTHIER.value))
        evidence.append(DecisionEvidence("INJURY", "Starter availability concern", starter_context.status or "Unknown", f"challenger: {challenger_context.status or 'no supplied designation'}", "Sleeper"))
    starter_matchup = _matchup_for(starter, starter_context, matchups) if starter else None
    challenger_matchup = _matchup_for(challenger, challenger_context, matchups)
    if challenger_matchup and challenger_matchup.label == "FAVORABLE" and (not starter_matchup or starter_matchup.label != "FAVORABLE"):
        codes.append(ReasonCode.FAVORABLE_MATCHUP.value)
        evidence.append(DecisionEvidence("MATCHUP", "Favorable completed-game matchup", f"{challenger_matchup.fantasy_points_allowed_per_game:.1f} allowed/game", f"{challenger_matchup.relative_to_league_average:+.1f}% vs league average over {challenger_matchup.games} games", "derived from nflverse player stats"))
    return tuple(dict.fromkeys(codes)), tuple(evidence)


def _confidence(
    starter: Player | None, challenger: Player, difference: float,
    contexts: dict[str, PlayerWeeklyContext], opportunities: dict[str, PlayerOpportunity],
    identity_resolved: dict[str, bool], evidence: tuple[DecisionEvidence, ...],
) -> str:
    points = 0
    player_ids = [player.player_id for player in (starter, challenger) if player]
    summaries = [contexts[player_id].season_stats for player_id in player_ids if player_id in contexts]
    if len(summaries) == len(player_ids) and all(summaries): points += 2
    if all(player_id in opportunities for player_id in player_ids): points += 2
    if summaries and all(summary and summary.games_played >= 3 for summary in summaries): points += 1
    if difference >= 8: points += 1
    if any(item.category in {"INJURY", "BYE"} for item in evidence): points += 2
    if player_ids and all(identity_resolved.get(player_id, False) for player_id in player_ids): points += 1
    minimum_games = min((summary.games_played for summary in summaries if summary), default=0)
    if minimum_games < 2:
        return "MODERATE" if points >= 3 else "LOW"
    return "HIGH" if points >= 6 else "MODERATE" if points >= 3 else "LOW"


def optimize_lineup(
    slots: list[LineupSlot], roster: Roster,
    contexts: dict[str, PlayerWeeklyContext], opportunities: dict[str, PlayerOpportunity],
    matchups: dict[tuple[str, str], DefenseVsPosition] | None = None,
    identity_resolved: dict[str, bool] | None = None,
) -> tuple[list[LineupDecision], LineupHealth]:
    matchups = matchups or {}
    identity_resolved = identity_resolved or {}
    edges: list[tuple[float, str, str, LineupSlot, Player, tuple[str, ...]]] = []
    for slot in slots:
        starter_context = contexts.get(slot.current_player.player_id) if slot.current_player else None
        starter_score = comparison_score(slot.current_player, starter_context, opportunities.get(slot.current_player.player_id), _matchup_for(slot.current_player, starter_context, matchups)) if slot.current_player else -100.0
        for bench in roster.bench:
            if bench.position not in slot.eligible_positions:
                continue
            context = contexts.get(bench.player_id)
            if not context or context.is_bye or str(context.status or "").lower() in {"out", "ir", "pup"}:
                continue
            challenger_score = comparison_score(bench, context, opportunities.get(bench.player_id), _matchup_for(bench, context, matchups))
            difference = round(challenger_score - starter_score, 2)
            if difference < 2.0:
                continue
            starter_games = contexts.get(slot.current_player.player_id).season_stats.games_played if slot.current_player and contexts.get(slot.current_player.player_id) and contexts[slot.current_player.player_id].season_stats else 0
            challenger_games = context.season_stats.games_played if context.season_stats else 0
            if difference < 4.0 and min(starter_games, challenger_games) < 2:
                continue
            reasons: list[str] = []
            starter_context = contexts.get(slot.current_player.player_id) if slot.current_player else None
            if not slot.current_player:
                reasons.append("Empty eligible starting slot")
            elif starter_context and starter_context.is_bye:
                reasons.append("Current starter is on bye")
            elif starter_context and str(starter_context.status or "").lower() in {"out", "ir", "pup"}:
                reasons.append("Current starter is unavailable")
            elif starter_context and str(starter_context.status or "").lower() == "doubtful":
                reasons.append("Current starter is doubtful")
            bench_opp, starter_opp = opportunities.get(bench.player_id), opportunities.get(slot.current_player.player_id) if slot.current_player else None
            if bench_opp and bench_opp.usage_trend == "RISING":
                reasons.append("Challenger usage is rising")
            if _usage_value(bench, bench_opp) > _usage_value(slot.current_player, starter_opp) + 1.5 if slot.current_player else True:
                reasons.append("Higher recent opportunity")
            if not reasons:
                reasons.append("Stronger recent factual profile")
            edges.append((difference, bench.name.lower(), slot.slot_id, slot, bench, tuple(reasons[:3])))
    edges.sort(key=lambda edge: (-edge[0], edge[1], edge[2]))
    slot_order = [slot.slot_id for slot in slots]
    bench_order = sorted({edge[4].player_id for edge in edges})
    bench_bits = {player_id: 1 << index for index, player_id in enumerate(bench_order)}
    by_slot = {slot_id: [edge for edge in edges if edge[3].slot_id == slot_id] for slot_id in slot_order}

    @lru_cache(maxsize=None)
    def best(slot_index: int, used_mask: int) -> tuple[float, tuple[tuple[float, str, str, LineupSlot, Player, tuple[str, ...]], ...]]:
        if slot_index >= len(slot_order):
            return 0.0, ()
        best_score, selected = best(slot_index + 1, used_mask)
        for edge in by_slot[slot_order[slot_index]]:
            bit = bench_bits[edge[4].player_id]
            if used_mask & bit:
                continue
            remainder_score, remainder = best(slot_index + 1, used_mask | bit)
            candidate_score = edge[0] + remainder_score
            candidate = (edge,) + remainder
            if candidate_score > best_score or (candidate_score == best_score and tuple((x[1], x[2]) for x in candidate) < tuple((x[1], x[2]) for x in selected)):
                best_score, selected = candidate_score, candidate
        return best_score, selected

    _, selected_edges = best(0, 0)
    decisions: list[LineupDecision] = []
    for difference, _, _, slot, bench, reasons in sorted(selected_edges, key=lambda edge: (-edge[0], edge[2])):
        label = "STRONG SWAP" if difference >= 8 else "CONSIDER SWAP" if difference >= 4 else "CLOSE CALL"
        reason_codes, evidence = _decision_evidence(slot.current_player, bench, contexts, opportunities, matchups)
        evidence_reasons = tuple(item.label for item in evidence) or reasons
        confidence = _confidence(slot.current_player, bench, difference, contexts, opportunities, identity_resolved, evidence)
        decisions.append(LineupDecision(slot.slot_id, slot.slot_type, slot.current_player, bench, label, difference, evidence_reasons[:3], reason_codes, evidence, confidence))
    injury_watches = sum(1 for slot in slots if slot.current_player and str((contexts.get(slot.current_player.player_id).status if contexts.get(slot.current_player.player_id) else "") or "").lower() in {"questionable", "doubtful", "out", "ir", "pup"})
    bye_conflicts = sum(1 for slot in slots if slot.current_player and contexts.get(slot.current_player.player_id) and contexts[slot.current_player.player_id].is_bye)
    return decisions, LineupHealth(len(decisions), injury_watches, bye_conflicts)
