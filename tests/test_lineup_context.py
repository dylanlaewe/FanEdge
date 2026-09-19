from football_data import PlayerWeeklyContext
from lineup_optimizer import LineupDecision, LineupSlot
from sleeper_api import Player
from strategy_engine import build_lineup_context


def test_ai_serializes_only_deterministic_decisions_without_claims():
    starter, bench = Player("s", "Starter", "RB", "A"), Player("b", "Bench", "RB", "B")
    weekly = {p.player_id: PlayerWeeklyContext(p.player_id, p.name, p.position, p.team, None, None, None, None, None, None, (), None) for p in (starter, bench)}
    slot = LineupSlot("RB1", "RB", ("RB",), starter)
    decision = LineupDecision("RB1", "RB", starter, bench, "CLOSE CALL", 2.5, ("Stronger recent factual profile",))
    payload = build_lineup_context([slot], [decision], weekly, {})
    assert len(payload["deterministic_decisions"]) == 1
    assert payload["deterministic_decisions"][0]["challenger"]["player_id"] == "b"
    assert "projection" in payload["data_limits"].lower()
    assert "unlisted-player" not in str(payload)
