from player_identity import PlayerIdentity
from visuals import ESPN_HEADSHOT_URL, TEAM_NAMES, player_visual, resolve_player_image, team_visual


def identity(espn_id=None):
    return PlayerIdentity("s", "g", "p", espn_id, "Test Player", "testplayer", "WR", "LAR", "gsis_id")


def test_all_current_team_visuals_are_centralized():
    assert len(TEAM_NAMES) == 32
    assert all(team_visual(team) and team_visual(team).logo_url for team in TEAM_NAMES)


def test_player_image_is_deterministic_and_fallback_is_designed():
    assert resolve_player_image(identity("123")) == ESPN_HEADSHOT_URL.format(espn_id="123")
    assert resolve_player_image(identity()) is None
    fallback = player_visual(identity(), "Test Player", "WR", "LAR")
    assert "Test Player" in fallback or "TP" in fallback
    assert "LAR" not in fallback  # team identity belongs in the adjacent matchup mark


def test_unknown_team_and_identity_do_not_break_component():
    assert team_visual("FA") is None
    component = player_visual(None, "Unknown Player", "RB", "FA")
    assert "Unknown Player" in component
    assert "UNKNOWN PLAYER" not in component
    assert "UP" in component
