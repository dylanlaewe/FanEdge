from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from football_data import (
    FootballDataError,
    GamePerformance,
    NFLState,
    ScheduleStatus,
    WeeklySchedule,
    WeeklyGame,
    build_performance_index,
    build_player_weekly_contexts,
    build_weekly_schedule,
    fantasy_points,
    normalize_nfl_state,
    normalize_player_status,
    summarize_performance,
)
from sleeper_api import Player, Roster


def test_normalize_nfl_state() -> None:
    state = normalize_nfl_state({"season": "2026", "week": 2, "season_type": "regular"})
    assert state == NFLState(2026, 2, "regular")


@pytest.mark.parametrize("raw", [None, {}, {"season": "x", "week": 2, "season_type": "regular"}])
def test_malformed_nfl_state(raw) -> None:
    with pytest.raises(FootballDataError):
        normalize_nfl_state(raw)


def test_schedule_maps_home_away_and_kickoff() -> None:
    rows = [{
        "season": "2026", "week": "2", "game_type": "REG", "gameday": "2026-09-20",
        "gametime": "13:00", "away_team": "BUF", "home_team": "MIA",
    }]
    schedule = build_weekly_schedule(rows, NFLState(2026, 2, "regular"))
    assert schedule["BUF"].opponent == "MIA" and not schedule["BUF"].is_home
    assert schedule["MIA"].opponent == "BUF" and schedule["MIA"].is_home
    assert schedule["BUF"].kickoff == datetime(2026, 9, 20, 13, tzinfo=ZoneInfo("America/New_York"))


def test_schedule_skips_malformed_rows() -> None:
    schedule = build_weekly_schedule([{}, {"season": "bad"}], NFLState(2026, 2, "regular"))
    assert schedule.games == {} and not schedule.complete


def test_status_and_missing_status() -> None:
    assert normalize_player_status({"status": "Active", "injury_status": None}) == (None, None)
    assert normalize_player_status({"status": "Active", "injury_status": "Questionable", "injury_body_part": "Knee"}) == ("Questionable", "Knee")
    assert normalize_player_status(None) == (None, None)


def test_fantasy_points_and_unsupported_bonus() -> None:
    scoring = {"pass_yd": .04, "pass_td": 4, "pass_int": -2, "rush_yd": .1, "rush_td": 6, "rec": 1, "rec_yd": .1, "rec_td": 6, "fum_lost": -2}
    row = {"rushing_yards": 50, "rushing_tds": 1, "receptions": 4, "receiving_yards": 20}
    assert fantasy_points(row, scoring, "RB") == 17.0
    assert fantasy_points(row, {**scoring, "bonus_rush_yd_100": 3}, "RB") is None
    assert fantasy_points(row, {**scoring, "rush_fd": .5}, "RB") is None


def test_performance_summary_and_missing_stats() -> None:
    assert summarize_performance([]) is None
    summary = summarize_performance([GamePerformance(1, 8), GamePerformance(2, 10), GamePerformance(3, 18)])
    assert summary and summary.games_played == 3
    assert summary.season_average == 12.0
    assert summary.recent_average == 12.0
    assert summary.trend == "steady"


def test_performance_trends() -> None:
    up = summarize_performance([GamePerformance(1, 2), GamePerformance(2, 2), GamePerformance(3, 2), GamePerformance(4, 12), GamePerformance(5, 12), GamePerformance(6, 12)])
    down = summarize_performance([GamePerformance(1, 12), GamePerformance(2, 12), GamePerformance(3, 12), GamePerformance(4, 2), GamePerformance(5, 2), GamePerformance(6, 2)])
    assert up and up.trend == "up"
    assert down and down.trend == "down"


def test_performance_index_excludes_current_week_and_handles_bad_rows() -> None:
    rows = [
        {"season": "2026", "week": "1", "season_type": "REG", "player_display_name": "Test Player", "team": "BUF", "position": "RB", "rushing_yards": "100"},
        {"season": "2026", "week": "2", "season_type": "REG", "player_display_name": "Test Player", "team": "BUF", "position": "RB", "rushing_yards": "100"},
        {"season": "bad"},
    ]
    index = build_performance_index(rows, NFLState(2026, 2, "regular"), {"rush_yd": .1})
    assert list(index.values()) == [[GamePerformance(1, 10.0)]]


def test_context_missing_game_vs_verified_bye() -> None:
    player = Player("1", "Test Player", "RB", "BUF")
    roster = Roster([player], [])
    missing = build_player_weekly_contexts(roster, {}, {}, {})["1"]
    bye = build_player_weekly_contexts(roster, {}, WeeklySchedule({}, True), {})["1"]
    assert missing.opponent is None and missing.is_bye is False
    assert bye.opponent is None and bye.is_bye is True
    assert missing.schedule_status == ScheduleStatus.UNKNOWN.value
    assert bye.schedule_status == ScheduleStatus.BYE.value


def test_context_with_game_and_unknown_stats() -> None:
    player = Player("1", "Test Player", "RB", "BUF")
    game = WeeklyGame("BUF", "MIA", False, None)
    context = build_player_weekly_contexts(Roster([player], []), {}, {"BUF": game}, {})["1"]
    assert context.opponent == "MIA" and context.home_away == "away"
    assert context.status is None and context.season_stats is None and not context.is_bye
