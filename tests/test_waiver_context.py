from datetime import datetime

from football_data import PlayerWeeklyContext
from sleeper_api import Player
from strategy_engine import build_waiver_context, parse_waiver_recommendations
from waiver_engine import RosterNeeds, WaiverCandidate


def test_strategy_context_contains_only_supplied_available_candidates():
    player = Player("free", "Free Player", "RB", "BUF")
    weekly = PlayerWeeklyContext("free", "Free Player", "RB", "BUF", None, None, None, None, None, None, (), None)
    needs = RosterNeeds({"QB": 1, "RB": 1, "WR": 4, "TE": 2}, {}, {}, ("RB",), {}, {})
    payload = build_waiver_context(needs, [WaiverCandidate(player, weekly, 2.0, ("RB depth",))], [])
    serialized = str(payload)
    assert "free" in serialized
    assert "owned-star" not in serialized


def test_parse_waiver_recommendations():
    result = parse_waiver_recommendations("TOP ADD: Add A.\nADD/DROP: Swap carefully.\nWATCHLIST: Watch B.")
    assert [item["title"] for item in result] == ["TOP ADD", "ADD/DROP", "WATCHLIST"]
