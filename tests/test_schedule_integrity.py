import requests
import pytest

from football_data import FootballDataError, NFLState, NflverseClient, ScheduleStatus, build_player_weekly_contexts, build_weekly_schedule
from sleeper_api import Player, Roster
from team_identity import NFL_TEAMS, normalize_team_id


STATE = NFLState(2026, 2, "regular")


def rows_for(teams, *, monday_lar=False):
    values = []
    teams = list(teams)
    for index in range(0, len(teams), 2):
        away, home = teams[index], teams[index + 1]
        if monday_lar and home == "LAR":
            home = "LA"
        values.append({
            "season": "2026", "week": "2", "game_type": "REG",
            "gameday": "2026-09-21" if monday_lar and home == "LA" else "2026-09-20",
            "gametime": "20:15" if monday_lar and home == "LA" else "13:00",
            "away_team": away, "home_team": home,
        })
    return values


def test_team_alias_normalization_is_explicit():
    assert normalize_team_id("nflverse", "LA") == "LAR"
    assert normalize_team_id("sleeper", "LAR") == "LAR"
    assert normalize_team_id("nflverse", "WSH") == "WAS"
    assert normalize_team_id("nflverse", "JAC") == "JAX"
    assert normalize_team_id("nflverse", "???") is None


def test_rams_monday_game_regression_is_scheduled():
    teams = sorted(NFL_TEAMS)
    teams.remove("LAR")
    teams.remove("NYG")
    teams.extend(["NYG", "LAR"])
    schedule = build_weekly_schedule(rows_for(teams, monday_lar=True), STATE)
    assert schedule.complete
    assert schedule.status_for("LAR") == ScheduleStatus.SCHEDULED
    assert schedule["LAR"].opponent == "NYG"
    assert schedule["LAR"].is_home
    assert schedule["LAR"].kickoff and schedule["LAR"].kickoff.strftime("%A %H:%M") == "Monday 20:15"
    for player in (Player("2133", "Davante Adams", "WR", "LAR"), Player("9493", "Puka Nacua", "WR", "LAR")):
        context = build_player_weekly_contexts(Roster([player], []), {}, schedule, {})[player.player_id]
        assert context.schedule_status == ScheduleStatus.SCHEDULED.value
        assert context.opponent == "NYG" and not context.is_bye


def test_legitimate_bye_requires_complete_schedule():
    playing = [team for team in sorted(NFL_TEAMS) if team not in {"BUF", "MIA", "NE", "NYJ", "DAL", "PHI", "NYG", "WAS"}]
    schedule = build_weekly_schedule(rows_for(playing), STATE)
    assert schedule.complete and schedule.status_for("BUF") == ScheduleStatus.BYE
    player = Player("buf", "Bye Player", "RB", "BUF")
    context = build_player_weekly_contexts(Roster([player], []), {}, schedule, {})["buf"]
    assert context.is_bye and context.schedule_status == ScheduleStatus.BYE.value


def test_incomplete_or_malformed_schedule_never_implies_bye():
    incomplete = build_weekly_schedule(rows_for(sorted(NFL_TEAMS)[:10]), STATE)
    malformed_rows = rows_for(sorted(NFL_TEAMS))
    malformed_rows[0]["home_team"] = "INVALID"
    malformed = build_weekly_schedule(malformed_rows, STATE)
    assert not incomplete.complete and incomplete.status_for("BUF") == ScheduleStatus.UNKNOWN
    assert not malformed.complete and malformed.status_for("BUF") == ScheduleStatus.UNKNOWN


def test_unrecognized_player_team_and_mapping_failure_are_unknown():
    schedule = build_weekly_schedule(rows_for(sorted(NFL_TEAMS)), STATE)
    unknown = Player("x", "Unknown", "RB", "XXX")
    context = build_player_weekly_contexts(Roster([unknown], []), {}, schedule, {})["x"]
    assert context.schedule_status == ScheduleStatus.UNKNOWN.value and not context.is_bye


def test_provider_fetch_failure_is_explicit(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(FootballDataError):
        NflverseClient().get_schedule_rows()
