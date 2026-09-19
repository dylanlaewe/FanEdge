"""League-slot-aware deterministic lineup comparison engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from football_data import PlayerWeeklyContext
from opportunity import PlayerOpportunity
from sleeper_api import Player, Roster


SLOT_ELIGIBILITY = {
    "QB": ("QB",), "RB": ("RB",), "WR": ("WR",), "TE": ("TE",),
    "K": ("K",), "DEF": ("DEF",),
    "FLEX": ("RB", "WR", "TE"), "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"), "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}


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


def comparison_score(player: Player, context: PlayerWeeklyContext | None, opportunity: PlayerOpportunity | None) -> float:
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
    return round(production + usage + usage_trend + availability, 2)


def optimize_lineup(
    slots: list[LineupSlot], roster: Roster,
    contexts: dict[str, PlayerWeeklyContext], opportunities: dict[str, PlayerOpportunity],
) -> tuple[list[LineupDecision], LineupHealth]:
    edges: list[tuple[float, str, str, LineupSlot, Player, tuple[str, ...]]] = []
    for slot in slots:
        starter_score = comparison_score(slot.current_player, contexts.get(slot.current_player.player_id), opportunities.get(slot.current_player.player_id)) if slot.current_player else -100.0
        for bench in roster.bench:
            if bench.position not in slot.eligible_positions:
                continue
            context = contexts.get(bench.player_id)
            if not context or context.is_bye or str(context.status or "").lower() in {"out", "ir", "pup"}:
                continue
            challenger_score = comparison_score(bench, context, opportunities.get(bench.player_id))
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
        decisions.append(LineupDecision(slot.slot_id, slot.slot_type, slot.current_player, bench, label, difference, reasons))
    injury_watches = sum(1 for slot in slots if slot.current_player and str((contexts.get(slot.current_player.player_id).status if contexts.get(slot.current_player.player_id) else "") or "").lower() in {"questionable", "doubtful", "out", "ir", "pup"})
    bye_conflicts = sum(1 for slot in slots if slot.current_player and contexts.get(slot.current_player.player_id) and contexts[slot.current_player.player_id].is_bye)
    return decisions, LineupHealth(len(decisions), injury_watches, bye_conflicts)
