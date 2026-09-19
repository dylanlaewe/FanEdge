from football_data import PerformanceSummary, PlayerWeeklyContext
from lineup_optimizer import build_current_lineup, normalize_lineup_slots, optimize_lineup
from opportunity import PlayerOpportunity
from sleeper_api import Player, Roster


def weekly(player, avg, *, status=None, bye=False, games=4):
    summary = None if avg is None else PerformanceSummary(games, avg, avg, "steady")
    return PlayerWeeklyContext(player.player_id, player.name, player.position, player.team, "BUF", "home", None, bye, status, None, (), summary)


def usage(games=4, value=10, trend="STEADY", position="RB"):
    return PlayerOpportunity(games, value if position == "QB" else None, value if position == "QB" else None, value if position == "RB" else None, value if position == "RB" else None, value if position in {"WR", "TE", "RB"} else None, value if position in {"WR", "TE", "RB"} else None, None, None, value if position == "RB" else None, value if position == "RB" else None, trend)


def test_slot_normalization_flex_superflex_duplicates_k_def():
    slots = normalize_lineup_slots(["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "WRRB_FLEX", "REC_FLEX", "K", "DEF", "BN"])
    assert slots[6][1] == ("RB", "WR", "TE")
    assert "QB" in slots[7][1] and "QB" not in slots[6][1]
    assert slots[8][1] == ("RB", "WR") and slots[9][1] == ("WR", "TE")
    assert [slot[0] for slot in slots].count("RB") == 2
    assert slots[-2:] == [("K", ("K",)), ("DEF", ("DEF",))]


def test_current_lineup_preserves_duplicate_slots_and_empty_slot():
    metadata = {"r1": {"full_name": "One", "position": "RB", "team": "A"}}
    slots = build_current_lineup({"starters": ["r1", "0"]}, metadata, ["RB", "RB", "BN"])
    assert [slot.slot_id for slot in slots] == ["RB1", "RB2"]
    assert slots[0].current_player and slots[1].current_player is None


def test_obvious_upgrade_and_starter_retained_threshold():
    starter, bench = Player("s", "Starter", "RB", "A"), Player("b", "Bench", "RB", "B")
    slots = build_current_lineup({"starters": ["s"]}, {"s": {"full_name": "Starter", "position": "RB", "team": "A"}}, ["RB"])
    roster = Roster([starter], [bench])
    contexts = {"s": weekly(starter, 5), "b": weekly(bench, 15)}
    decisions, _ = optimize_lineup(slots, roster, contexts, {})
    assert decisions and decisions[0].label == "STRONG SWAP"
    contexts["b"] = weekly(bench, 5.5)
    assert optimize_lineup(slots, roster, contexts, {})[0] == []


def test_close_call_threshold():
    starter, bench = Player("s", "Starter", "WR", "A"), Player("b", "Bench", "WR", "B")
    slots = build_current_lineup({"starters": ["s"]}, {"s": {"full_name": "Starter", "position": "WR", "team": "A"}}, ["WR"])
    decisions, _ = optimize_lineup(slots, Roster([starter], [bench]), {"s": weekly(starter, 8), "b": weekly(bench, 10.5)}, {})
    assert decisions and decisions[0].label == "CLOSE CALL"


def test_small_sample_suppresses_close_call():
    starter, bench = Player("s", "Starter", "WR", "A"), Player("b", "Bench", "WR", "B")
    slots = build_current_lineup({"starters": ["s"]}, {"s": {"full_name": "Starter", "position": "WR", "team": "A"}}, ["WR"])
    decisions, _ = optimize_lineup(slots, Roster([starter], [bench]), {"s": weekly(starter, 8, games=1), "b": weekly(bench, 11, games=1)}, {})
    assert decisions == []


def test_injured_and_bye_starter_elevate_healthy_replacement():
    starter, bench = Player("s", "Starter", "TE", "A"), Player("b", "Bench", "TE", "B")
    slots = build_current_lineup({"starters": ["s"]}, {"s": {"full_name": "Starter", "position": "TE", "team": "A"}}, ["TE"])
    for context in (weekly(starter, 15, status="Out"), weekly(starter, 15, bye=True)):
        decisions, health = optimize_lineup(slots, Roster([starter], [bench]), {"s": context, "b": weekly(bench, 3)}, {})
        assert decisions[0].label == "STRONG SWAP"
        assert health.injury_watches + health.bye_conflicts == 1


def test_one_bench_player_cannot_fill_two_slots_and_positions_are_valid():
    s1, s2, bench = Player("s1", "S1", "WR", "A"), Player("s2", "S2", "WR", "A"), Player("b", "Bench", "WR", "B")
    metadata = {p.player_id: {"full_name": p.name, "position": p.position, "team": p.team} for p in (s1, s2)}
    slots = build_current_lineup({"starters": ["s1", "s2"]}, metadata, ["WR", "FLEX"])
    contexts = {"s1": weekly(s1, 2), "s2": weekly(s2, 3), "b": weekly(bench, 15)}
    decisions, _ = optimize_lineup(slots, Roster([s1, s2], [bench]), contexts, {})
    assert len(decisions) == 1
    assert decisions[0].challenger.player_id == "b"
    assert bench.position in next(slot.eligible_positions for slot in slots if slot.slot_id == decisions[0].slot_id)


def test_qb_cannot_replace_standard_flex_but_can_superflex():
    rb, qb = Player("r", "Runner", "RB", "A"), Player("q", "Quarterback", "QB", "B")
    metadata = {"r": {"full_name": "Runner", "position": "RB", "team": "A"}}
    contexts = {"r": weekly(rb, 1), "q": weekly(qb, 30)}
    flex = build_current_lineup({"starters": ["r"]}, metadata, ["FLEX"])
    superflex = build_current_lineup({"starters": ["r"]}, metadata, ["SUPER_FLEX"])
    assert optimize_lineup(flex, Roster([rb], [qb]), contexts, {})[0] == []
    assert optimize_lineup(superflex, Roster([rb], [qb]), contexts, {})[0]


def test_multiple_challengers_choose_best_valid_assignment():
    s1, s2 = Player("s1", "S1", "RB", "A"), Player("s2", "S2", "WR", "A")
    b1, b2 = Player("b1", "B1", "RB", "B"), Player("b2", "B2", "WR", "B")
    metadata = {p.player_id: {"full_name": p.name, "position": p.position, "team": p.team} for p in (s1, s2)}
    slots = build_current_lineup({"starters": ["s1", "s2"]}, metadata, ["RB", "WR"])
    contexts = {p.player_id: weekly(p, avg) for p, avg in ((s1, 3), (s2, 4), (b1, 15), (b2, 14))}
    decisions, _ = optimize_lineup(slots, Roster([s1, s2], [b1, b2]), contexts, {})
    assert {(d.slot_type, d.challenger.position) for d in decisions} == {("RB", "RB"), ("WR", "WR")}


def test_global_assignment_beats_greedy_flex_conflict():
    flex_starter, rb_starter = Player("sf", "Flex Starter", "WR", "A"), Player("sr", "RB Starter", "RB", "A")
    rb_bench, wr_bench = Player("br", "RB Bench", "RB", "B"), Player("bw", "WR Bench", "WR", "B")
    metadata = {p.player_id: {"full_name": p.name, "position": p.position, "team": p.team} for p in (flex_starter, rb_starter)}
    slots = build_current_lineup({"starters": ["sf", "sr"]}, metadata, ["FLEX", "RB"])
    contexts = {
        "sf": weekly(flex_starter, 1), "sr": weekly(rb_starter, 2),
        "br": weekly(rb_bench, 12), "bw": weekly(wr_bench, 9),
    }
    decisions, _ = optimize_lineup(slots, Roster([flex_starter, rb_starter], [rb_bench, wr_bench]), contexts, {})
    assert {(d.slot_type, d.challenger.player_id) for d in decisions} == {("FLEX", "bw"), ("RB", "br")}
