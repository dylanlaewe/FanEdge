"""Deterministic league-aware waiver candidate generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from football_data import PlayerWeeklyContext
from sleeper_api import Player, Roster


SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
ROSTER_CONTAINERS = ("players", "starters", "reserve", "taxi", "practice_squad")
SHALLOW_THRESHOLDS = {"QB": 2, "RB": 4, "WR": 4, "TE": 2}
UNAVAILABLE_STATUSES = {"inactive", "suspended", "pup"}
INJURY_STATUSES = {"out", "doubtful", "ir", "pup"}


@dataclass(frozen=True)
class RosterNeeds:
    positional_counts: dict[str, int]
    starter_counts: dict[str, int]
    bench_counts: dict[str, int]
    shallow_depth_positions: tuple[str, ...]
    injury_pressure: dict[str, int]
    bye_pressure: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WaiverCandidate:
    player: Player
    context: PlayerWeeklyContext
    score: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "player": asdict(self.player),
            "weekly": self.context.to_dict(),
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class DropCandidate:
    player: Player
    context: PlayerWeeklyContext
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {"player": asdict(self.player), "weekly": self.context.to_dict(), "rationale": self.rationale}


def build_rostered_player_ids(rosters: Iterable[dict[str, Any]]) -> set[str]:
    """Union every Sleeper roster container that can represent ownership."""
    owned: set[str] = set()
    for roster in rosters:
        if not isinstance(roster, dict):
            continue
        for container in ROSTER_CONTAINERS:
            values = roster.get(container)
            if isinstance(values, list):
                owned.update(str(value) for value in values if value not in (None, "0", 0))
    return owned


def build_available_players(
    metadata: dict[str, dict[str, Any]], owned_ids: set[str]
) -> list[Player]:
    """Create the active QB/RB/WR/TE universe, minus league ownership."""
    available: list[Player] = []
    for player_id, raw in metadata.items():
        if str(player_id) in owned_ids or not isinstance(raw, dict):
            continue
        position = str(raw.get("position") or "").upper()
        team = str(raw.get("team") or "").upper()
        status = str(raw.get("status") or "active").lower()
        sport = str(raw.get("sport") or "nfl").lower()
        name = str(raw.get("full_name") or " ".join(
            str(raw.get(key) or "") for key in ("first_name", "last_name")
        )).strip()
        if (
            position not in SKILL_POSITIONS
            or not team
            or not name
            or sport != "nfl"
            or status in UNAVAILABLE_STATUSES
            or raw.get("active") is False
        ):
            continue
        available.append(Player(str(player_id), name, position, team))
    return sorted(available, key=lambda player: (player.position, player.name.lower(), player.player_id))


def analyze_roster_needs(
    roster: Roster, contexts: dict[str, PlayerWeeklyContext]
) -> RosterNeeds:
    all_players = (*roster.starters, *roster.bench)
    counts = {position: 0 for position in SKILL_POSITIONS}
    starters = counts.copy()
    bench = counts.copy()
    injuries = counts.copy()
    byes = counts.copy()
    for player in all_players:
        if player.position in counts:
            counts[player.position] += 1
            context = contexts.get(player.player_id)
            if context and str(context.status or "").lower() in INJURY_STATUSES:
                injuries[player.position] += 1
            if context and context.is_bye:
                byes[player.position] += 1
    for player in roster.starters:
        if player.position in starters:
            starters[player.position] += 1
    for player in roster.bench:
        if player.position in bench:
            bench[player.position] += 1
    shallow = tuple(position for position in SKILL_POSITIONS if counts[position] < SHALLOW_THRESHOLDS[position])
    return RosterNeeds(counts, starters, bench, shallow, injuries, byes)


def _candidate_score(context: PlayerWeeklyContext, position: str, needs: RosterNeeds) -> float:
    summary = context.season_stats
    production = 0.0
    sample = 0.45
    trend = 0.0
    if summary:
        production = (0.6 * summary.recent_average) + (0.4 * summary.season_average)
        sample = min(1.0, 0.6 + (0.1 * summary.games_played))
        trend = 1.25 if summary.trend == "up" else -1.25 if summary.trend == "down" else 0.0
    need = 2.0 if position in needs.shallow_depth_positions else 0.0
    need += min(2.0, float(needs.injury_pressure.get(position, 0)))
    need += min(1.0, float(needs.bye_pressure.get(position, 0)))
    status = str(context.status or "").lower()
    availability = {"questionable": -0.75, "doubtful": -2.5, "out": -4.0, "ir": -6.0, "pup": -6.0}.get(status, 0.0)
    return round((production * sample) + trend + need + availability, 2)


def rank_waiver_candidates(
    players: Iterable[Player],
    contexts: dict[str, PlayerWeeklyContext],
    needs: RosterNeeds,
    *,
    limit: int = 8,
) -> list[WaiverCandidate]:
    ranked: list[WaiverCandidate] = []
    for player in players:
        context = contexts.get(player.player_id)
        if not context:
            continue
        reasons: list[str] = []
        if player.position in needs.shallow_depth_positions:
            reasons.append(f"{player.position} depth")
        if needs.injury_pressure.get(player.position, 0):
            reasons.append("Injury coverage")
        if needs.bye_pressure.get(player.position, 0):
            reasons.append("Bye coverage")
        if context.season_stats:
            reasons.append("Recent production")
            if context.season_stats.trend == "up":
                reasons.append("Trending up")
        if not reasons:
            reasons.append("Available in your league")
        ranked.append(WaiverCandidate(player, context, _candidate_score(context, player.position, needs), tuple(reasons[:3])))
    ranked.sort(key=lambda item: (
        -item.score,
        -(item.context.season_stats.recent_average if item.context.season_stats else -1),
        -(item.context.season_stats.season_average if item.context.season_stats else -1),
        item.player.name.lower(),
        item.player.player_id,
    ))
    result: list[WaiverCandidate] = []
    position_counts: dict[str, int] = {}
    for candidate in ranked:
        if position_counts.get(candidate.player.position, 0) >= 3:
            continue
        result.append(candidate)
        position_counts[candidate.player.position] = position_counts.get(candidate.player.position, 0) + 1
        if len(result) >= limit:
            break
    return result


def find_drop_candidates(
    roster: Roster,
    contexts: dict[str, PlayerWeeklyContext],
    needs: RosterNeeds,
    *,
    limit: int = 3,
) -> list[DropCandidate]:
    """Return only evidence-backed bench options; never starters or injured stashes."""
    eligible: list[tuple[float, Player, PlayerWeeklyContext]] = []
    for player in roster.bench:
        context = contexts.get(player.player_id)
        summary = context.season_stats if context else None
        if not context or not summary or summary.games_played < 2:
            continue
        if str(context.status or "").lower() in INJURY_STATUSES:
            continue
        if needs.positional_counts.get(player.position, 0) <= SHALLOW_THRESHOLDS.get(player.position, 0):
            continue
        evidence = (0.6 * summary.recent_average) + (0.4 * summary.season_average)
        eligible.append((evidence, player, context))
    eligible.sort(key=lambda item: (item[0], item[1].name.lower(), item[1].player_id))
    return [
        DropCandidate(player, context, "Lower recent and season production among evidence-backed bench options")
        for _, player, context in eligible[:limit]
    ]
