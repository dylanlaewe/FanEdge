"""Completed-game opportunity metrics derived from nflverse weekly statistics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from football_data import NFLState, SEASON_TYPES, _identity, _number
from player_identity import PlayerIdentity
from sleeper_api import Player


@dataclass(frozen=True)
class OpportunityGame:
    week: int
    attempts: float | None
    completions: float | None
    carries: float | None
    targets: float | None
    receptions: float | None
    touches: float | None


@dataclass(frozen=True)
class PlayerOpportunity:
    games: int
    season_attempts: float | None
    recent_attempts: float | None
    season_carries: float | None
    recent_carries: float | None
    season_targets: float | None
    recent_targets: float | None
    season_receptions: float | None
    recent_receptions: float | None
    season_touches: float | None
    recent_touches: float | None
    usage_trend: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    return _number(value)


def build_opportunity_index(rows: Iterable[dict[str, str]], state: NFLState) -> dict[Any, list[OpportunityGame]]:
    index: dict[Any, list[OpportunityGame]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            season, week = int(row.get("season", "")), int(row.get("week", ""))
        except (TypeError, ValueError):
            continue
        if season != state.season or week >= state.week or row.get("season_type") != SEASON_TYPES[state.season_type]:
            continue
        name = row.get("player_display_name") or row.get("player_name")
        team, position = row.get("team") or row.get("recent_team"), row.get("position")
        if not name or not team or not position:
            continue
        carries = _optional_number(row, "carries")
        receptions = _optional_number(row, "receptions")
        touches = None if carries is None and receptions is None else (carries or 0) + (receptions or 0)
        game = OpportunityGame(
            week, _optional_number(row, "attempts"), _optional_number(row, "completions"),
            carries, _optional_number(row, "targets"), receptions, touches,
        )
        index.setdefault(_identity(name, team, position), []).append(game)
        if row.get("player_id"):
            index.setdefault(("gsis", str(row["player_id"])), []).append(game)
    for games in index.values():
        games.sort(key=lambda item: item.week)
    return index


def _average(games: list[OpportunityGame], field: str) -> float | None:
    values = [getattr(game, field) for game in games if getattr(game, field) is not None]
    return round(sum(values) / len(values), 1) if values else None


def summarize_opportunity(games: Iterable[OpportunityGame], position: str) -> PlayerOpportunity | None:
    values = list(games)
    if not values:
        return None
    recent = values[-3:]
    primary = "attempts" if position == "QB" else "touches" if position == "RB" else "targets"
    trend = "INSUFFICIENT DATA"
    if len(values) >= 4:
        latest = values[-2:]
        baseline = values[:-2]
        recent_value, baseline_value = _average(latest, primary), _average(baseline, primary)
        if recent_value is not None and baseline_value is not None:
            threshold = max(1.5, abs(baseline_value) * 0.2)
            trend = "RISING" if recent_value - baseline_value >= threshold else "FALLING" if baseline_value - recent_value >= threshold else "STEADY"
    return PlayerOpportunity(
        games=len(values),
        season_attempts=_average(values, "attempts"), recent_attempts=_average(recent, "attempts"),
        season_carries=_average(values, "carries"), recent_carries=_average(recent, "carries"),
        season_targets=_average(values, "targets"), recent_targets=_average(recent, "targets"),
        season_receptions=_average(values, "receptions"), recent_receptions=_average(recent, "receptions"),
        season_touches=_average(values, "touches"), recent_touches=_average(recent, "touches"),
        usage_trend=trend,
    )


def build_player_opportunities(
    players: Iterable[Player],
    index: dict[Any, list[OpportunityGame]],
    identities: dict[str, PlayerIdentity] | None = None,
) -> dict[str, PlayerOpportunity]:
    result: dict[str, PlayerOpportunity] = {}
    for player in players:
        if player.position not in {"QB", "RB", "WR", "TE"}:
            continue
        identity = (identities or {}).get(player.player_id)
        games = index.get(("gsis", identity.gsis_id), []) if identity and identity.gsis_id else index.get(_identity(player.name, player.team, player.position), [])
        summary = summarize_opportunity(games, player.position)
        if summary:
            result[player.player_id] = summary
    return result
