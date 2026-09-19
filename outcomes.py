"""Deterministic post-game evaluation for stored FanEdge decisions."""

from __future__ import annotations

import json
from typing import Any

from football_data import GamePerformance
from memory import LeagueScope, evaluate_lineup_outcome
from player_identity import normalize_name
from storage import SQLiteRepository


def _points_for(
    raw_player: str | None,
    week: int,
    performances: dict[Any, list[GamePerformance]],
) -> float | None:
    if not raw_player:
        return None
    player = json.loads(raw_player)
    key = (
        normalize_name(str(player.get("name") or "")),
        str(player.get("team") or "").upper(),
        str(player.get("position") or "").upper(),
    )
    game = next((value for value in performances.get(key, ()) if value.week == week), None)
    return game.fantasy_points if game else None


def evaluate_pending_lineup_decisions(
    repository: SQLiteRepository,
    scope: LeagueScope,
    current_week: int,
    performances: dict[Any, list[GamePerformance]],
) -> int:
    """Evaluate completed prior-week comparisons when both league-scored results exist."""
    evaluated = 0
    for decision in repository.pending_lineup_decisions(scope, before_week=current_week):
        week = int(decision["week"])
        recommended = _points_for(decision.get("subject_json"), week, performances)
        alternative = _points_for(decision.get("related_json"), week, performances)
        outcome = evaluate_lineup_outcome(recommended, alternative, week_complete=current_week > week)
        repository.record_outcome(
            str(decision["decision_key"]), outcome.value, recommended, alternative,
        )
        evaluated += 1
    return evaluated
