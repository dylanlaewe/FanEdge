from football_data import PlayerWeeklyContext, ScheduleStatus
from sleeper_api import Player
from components import player_row, status_badge


def context(*, status=None, body=None, schedule_status=ScheduleStatus.SCHEDULED.value):
    return PlayerWeeklyContext(
        "1", "Player", "WR", "LAR", "SF", "home", None, False,
        status, body, (), None, schedule_status,
    )


def test_injury_badges_are_explicit_and_restrained():
    assert "Questionable · Hamstring" in status_badge(context(status="Questionable", body="Hamstring"))
    assert 'class="fe-status-badge out"' in status_badge(context(status="Out"))


def test_unknown_state_does_not_look_like_out_or_bye():
    badge = status_badge(context(schedule_status=ScheduleStatus.UNKNOWN.value))
    assert "Unknown" in badge
    assert "out" not in badge
    assert "bye" not in badge


def test_long_player_names_remain_in_the_reusable_row():
    player = Player("1", "A Very Long Hyphenated Player Name Junior", "WR", "LAR")
    rendered = player_row(player, "WR1", context(), None, None, None)
    assert player.name in rendered
    assert 'title="A Very Long Hyphenated Player Name Junior"' in rendered
