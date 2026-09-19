from football_data import NFLState
from matchup import build_defense_vs_position


def make_rows():
    rows = []
    allowed = {"BUF": (200, 10), "MIA": (100, 2), "NE": (150, 5)}
    for week in range(1, 5):
        for defense, (yards, receptions) in allowed.items():
            rows.append({
                "season": "2026", "week": str(week), "season_type": "REG",
                "position": "WR", "opponent_team": defense,
                "player_display_name": f"Receiver {defense}", "team": "DAL",
                "receiving_yards": str(yards), "receptions": str(receptions),
            })
    for week in range(1, 4):
        rows.append({
            "season": "2026", "week": str(week), "season_type": "REG",
            "position": "WR", "opponent_team": "DAL", "player_display_name": "Short Sample",
            "team": "NYG", "receiving_yards": "150", "receptions": "5",
        })
    return rows


def test_matchup_labels_and_league_average():
    result = build_defense_vs_position(make_rows(), NFLState(2026, 5, "regular"), {"rec_yd": .1})
    assert result[("BUF", "WR")].label == "FAVORABLE"
    assert result[("MIA", "WR")].label == "DIFFICULT"
    assert result[("NE", "WR")].label == "NEUTRAL"
    assert result[("DAL", "WR")].label == "INSUFFICIENT DATA"
    assert result[("BUF", "WR")].league_average > 0


def test_matchup_respects_scoring_settings():
    standard = build_defense_vs_position(make_rows(), NFLState(2026, 5, "regular"), {"rec_yd": .1})
    ppr = build_defense_vs_position(make_rows(), NFLState(2026, 5, "regular"), {"rec_yd": .1, "rec": 1})
    assert ppr[("BUF", "WR")].fantasy_points_allowed_per_game > standard[("BUF", "WR")].fantasy_points_allowed_per_game
