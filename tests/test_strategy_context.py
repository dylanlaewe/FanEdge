import json

from football_data import NFLState, PlayerWeeklyContext
from opportunity_engine import Action, FantasyOpportunity, OpportunityType, Priority
from sleeper_api import Player, Roster
from strategy_engine import build_roster_context


def test_strategy_context_serializes_weekly_facts_and_unknowns() -> None:
    player = Player("1", "Test Player", "WR", "BUF")
    weekly = PlayerWeeklyContext(
        player_id="1", name="Test Player", position="WR", team="BUF",
        opponent="MIA", home_away="away", kickoff=None, is_bye=False,
        status=None, injury_body_part=None, recent_stats=(), season_stats=None,
    )
    context = build_roster_context(
        Roster([player], []),
        {"name": "League", "season": "2026", "settings": {"num_teams": 12}, "scoring_settings": {"rec": 1}},
        NFLState(2026, 2, "regular"),
        {"1": weekly},
    )
    encoded = json.dumps(context)
    assert context["nfl_state"]["week"] == 2
    assert context["starters"][0]["weekly"]["opponent"] == "MIA"
    assert context["starters"][0]["weekly"]["status"] is None
    assert "null" in encoded


def test_strategy_context_serializes_deterministic_opportunity_feed() -> None:
    player = Player("1", "A Player", "WR", "LAR")
    item = FantasyOpportunity(
        "watch:1", OpportunityType.BREAKOUT_WATCH.value, Priority.MEDIUM.value,
        player, None, (), ("ON_USER_ROSTER",), Action.MONITOR.value,
        "MODERATE", ("Targets increased",), 5, 5,
    )
    context = build_roster_context(Roster([player], []), {"name": "League"}, opportunity_feed=[item])
    serialized = context["deterministic_opportunity_feed"][0]
    assert serialized["opportunity_id"] == "watch:1"
    assert serialized["recommended_action"] == "MONITOR"
