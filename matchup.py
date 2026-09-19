"""Completed-game fantasy production allowed by defense and position."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from football_data import NFLState, fantasy_points
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
    evidence_basis: str = "CURRENT"
    current_games: int = 0
    historical_games: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_defense_vs_position(
    rows: Iterable[dict[str, str]], state: NFLState, scoring: dict[str, Any],
    historical_rows: Iterable[dict[str, str]] = (),
) -> dict[tuple[str, str], DefenseVsPosition]:
    current = _season_defense_values(rows, state.season, state.week, scoring)
    historical = _season_defense_values(historical_rows, state.season - 1, 99, scoring)
    result: dict[tuple[str, str], DefenseVsPosition] = {}
    keys = set(current) | set(historical)
    for key in keys:
        current_values, prior_values = current.get(key, []), historical.get(key, [])
        combined_count = len(current_values) + len(prior_values)
        if combined_count < 4:
            values = current_values or prior_values
            if values:
                result[key] = DefenseVsPosition(
                    key[0], key[1], combined_count, round(sum(values) / len(values), 1),
                    round(sum(values[-3:]) / len(values[-3:]), 1), 0.0, 0.0,
                    "INSUFFICIENT DATA", "CURRENT" if current_values else "HISTORICAL",
                    len(current_values), len(prior_values),
                )
            continue
        current_weight = min(1.0, len(current_values) / 4)
        if not prior_values: current_weight = 1.0
        if not current_values: current_weight = 0.0
        current_avg = sum(current_values) / len(current_values) if current_values else 0.0
        prior_avg = sum(prior_values) / len(prior_values) if prior_values else 0.0
        allowed = current_avg * current_weight + prior_avg * (1-current_weight)
        position = key[1]
        league_samples = [values for (defense, pos), values in current.items() if pos == position]
        prior_samples = [values for (defense, pos), values in historical.items() if pos == position]
        league_current = sum(map(sum, league_samples))/sum(map(len, league_samples)) if league_samples else 0
        league_prior = sum(map(sum, prior_samples))/sum(map(len, prior_samples)) if prior_samples else 0
        league = league_current*current_weight + league_prior*(1-current_weight)
        relative = ((allowed-league)/league*100) if league else 0.0
        basis = "CURRENT" if current_weight == 1 else "HISTORICAL" if current_weight == 0 else "MIXED"
        label = "FAVORABLE" if relative >= 15 else "DIFFICULT" if relative <= -15 else "NEUTRAL"
        recent = current_values[-3:] or prior_values[-3:]
        result[key] = DefenseVsPosition(key[0], position, combined_count, round(allowed,1), round(sum(recent)/len(recent),1), round(league,1), round(relative,1), label, basis, len(current_values), len(prior_values))
    return result


def _season_defense_values(rows: Iterable[dict[str, str]], season_target: int, before_week: int, scoring: dict[str, Any]) -> dict[tuple[str, str], list[float]]:
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
        if season != season_target or week >= before_week or row.get("season_type") != "REG" or position not in POSITIONS or not defense:
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

    defense_values: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for (defense, position, week), points in totals.items():
        defense_values.setdefault((defense, position), []).append((week, points))

    result: dict[tuple[str, str], list[float]] = {}
    for (defense, position), weekly in defense_values.items():
        weekly.sort()
        values = [points for _, points in weekly]
        result[(defense, position)] = values
    return result
