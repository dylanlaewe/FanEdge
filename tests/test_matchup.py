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


def test_early_season_blends_history_then_transitions_current():
    current = [{"season":"2026","week":"1","season_type":"REG","position":"WR","opponent_team":"BUF","receiving_yards":"200"}]
    prior = [{"season":"2025","week":str(i),"season_type":"REG","position":"WR","opponent_team":"BUF","receiving_yards":"40"} for i in range(1,5)]
    prior += [{"season":"2025","week":str(i),"season_type":"REG","position":"WR","opponent_team":"MIA","receiving_yards":"100"} for i in range(1,5)]
    result = build_defense_vs_position(current, NFLState(2026,2,"regular"), {"rec_yd":.1}, prior)
    assert result[("BUF","WR")].evidence_basis == "MIXED"
    assert result[("BUF","WR")].current_games == 1
    current = [{**current[0], "week": str(i)} for i in range(1,5)]
    result = build_defense_vs_position(current, NFLState(2026,5,"regular"), {"rec_yd":.1}, prior)
    assert result[("BUF","WR")].evidence_basis == "CURRENT"
    assert result[("BUF", "WR")].league_average > 0


def test_matchup_respects_scoring_settings():
    standard = build_defense_vs_position(make_rows(), NFLState(2026, 5, "regular"), {"rec_yd": .1})
    ppr = build_defense_vs_position(make_rows(), NFLState(2026, 5, "regular"), {"rec_yd": .1, "rec": 1})
    assert ppr[("BUF", "WR")].fantasy_points_allowed_per_game > standard[("BUF", "WR")].fantasy_points_allowed_per_game
