"""Completed-game fantasy production allowed by defense and position."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from football_data import NFLState, SEASON_TYPES, fantasy_points
from team_identity import normalize_team_id


POSITIONS = {"QB", "RB", "WR", "TE"}


@dataclass(frozen=True)
class DefenseVsPosition:
    defense_team: str
    position: str
    games: int
    fantasy_points_allowed_per_game: float
    recent_allowed_per_game: float
    league_average: float
    relative_to_league_average: float
    label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_defense_vs_position(
    rows: Iterable[dict[str, str]], state: NFLState, scoring: dict[str, Any]
) -> dict[tuple[str, str], DefenseVsPosition]:
    totals: dict[tuple[str, str, int], float] = {}
    defense_weeks: set[tuple[str, int]] = set()
    scoring_supported = True
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            season, week = int(row.get("season", "")), int(row.get("week", ""))
        except (TypeError, ValueError):
            continue
        position = str(row.get("position") or "").upper()
        defense = normalize_team_id("nflverse", row.get("opponent_team"))
        if season != state.season or week >= state.week or row.get("season_type") != SEASON_TYPES[state.season_type] or position not in POSITIONS or not defense:
            continue
        defense_weeks.add((defense, week))
        points = fantasy_points(row, scoring, position)
        if points is None:
            scoring_supported = False
            continue
        key = (defense, position, week)
        totals[key] = totals.get(key, 0.0) + points

    if not scoring_supported:
        return {}
    for defense, week in defense_weeks:
        for position in POSITIONS:
            totals.setdefault((defense, position, week), 0.0)

    league_values: dict[str, list[float]] = {position: [] for position in POSITIONS}
    defense_values: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for (defense, position, week), points in totals.items():
        league_values[position].append(points)
        defense_values.setdefault((defense, position), []).append((week, points))

    result: dict[tuple[str, str], DefenseVsPosition] = {}
    for (defense, position), weekly in defense_values.items():
        weekly.sort()
        values = [points for _, points in weekly]
        average = sum(values) / len(values)
        recent = values[-3:]
        league_average = sum(league_values[position]) / len(league_values[position]) if league_values[position] else 0.0
        relative = ((average - league_average) / league_average * 100) if league_average else 0.0
        label = "INSUFFICIENT DATA"
        if len(values) >= 4:
            label = "FAVORABLE" if relative >= 15 else "DIFFICULT" if relative <= -15 else "NEUTRAL"
        result[(defense, position)] = DefenseVsPosition(
            defense, position, len(values), round(average, 1), round(sum(recent) / len(recent), 1),
            round(league_average, 1), round(relative, 1), label,
        )
    return result
