from datetime import datetime

from football_data import GamePerformance, PerformanceSummary, PlayerWeeklyContext
from sleeper_api import Player, Roster
from intelligence import ParticipationSummary, RoleProfile
from opportunity import PlayerOpportunity
from waiver_engine import (
    analyze_roster_needs,
    build_available_players,
    build_rostered_player_ids,
    find_drop_candidates,
    rank_waiver_candidates,
)


def context(player, avg=None, recent=None, trend="steady", status=None, bye=False):
    summary = None if avg is None else PerformanceSummary(3, avg, recent if recent is not None else avg, trend)
    return PlayerWeeklyContext(player.player_id, player.name, player.position, player.team, "NYG", "home", datetime(2026, 9, 20), bye, status, None, (GamePerformance(1, avg or 0),), summary)


def test_ownership_unions_starter_bench_ir_taxi_and_duplicates():
    rosters = [
        {"players": ["starter", "bench", "duplicate"], "starters": ["starter"], "reserve": ["ir"], "taxi": ["taxi"]},
        {"players": ["duplicate"], "practice_squad": ["practice"]},
    ]
    assert build_rostered_player_ids(rosters) == {"starter", "bench", "duplicate", "ir", "taxi", "practice"}


def test_available_universe_filters_owned_inactive_and_positions():
    metadata = {
        "owned": {"full_name": "Owned Star", "position": "WR", "team": "DAL", "status": "Active"},
        "free": {"full_name": "Free Runner", "position": "RB", "team": "BUF", "status": "Active"},
        "retired": {"full_name": "Old Player", "position": "QB", "team": "FA", "status": "Inactive"},
        "inactive_flag": {"full_name": "Past Player", "position": "QB", "team": "SEA", "status": "Active", "active": False},
        "k": {"full_name": "Kicker", "position": "K", "team": "BAL", "status": "Active"},
        "bad": {"full_name": "", "position": "TE", "team": "KC"},
    }
    available = build_available_players(metadata, {"owned"})
    assert [player.player_id for player in available] == ["free"]


def test_roster_needs_distinguish_shallow_and_injury_pressure():
    players = [Player("q", "Q", "QB", "A"), Player("r", "R", "RB", "B"), Player("w1", "W1", "WR", "C"), Player("w2", "W2", "WR", "D"), Player("t", "T", "TE", "E")]
    roster = Roster(players[:4], [players[4]])
    contexts = {p.player_id: context(p, 5, status="Out" if p.player_id == "r" else None) for p in players}
    needs = analyze_roster_needs(roster, contexts)
    assert "RB" in needs.shallow_depth_positions and "WR" in needs.shallow_depth_positions
    assert needs.injury_pressure["RB"] == 1
    assert needs.starter_counts["WR"] == 2 and needs.bench_counts["TE"] == 1


def test_balanced_roster_has_no_shallow_positions():
    positions = ["QB"] * 2 + ["RB"] * 4 + ["WR"] * 4 + ["TE"] * 2
    players = [Player(str(i), f"P{i}", pos, "BUF") for i, pos in enumerate(positions)]
    needs = analyze_roster_needs(Roster(players[:6], players[6:]), {p.player_id: context(p) for p in players})
    assert needs.shallow_depth_positions == ()


def test_ranking_is_deterministic_handles_injury_and_missing_stats():
    rb = Player("a", "Alpha", "RB", "BUF")
    wr = Player("b", "Beta", "WR", "DAL")
    no_stats = Player("c", "Charlie", "TE", "KC")
    injured = Player("d", "Delta", "RB", "MIA")
    roster = Roster([Player("q", "Q", "QB", "SEA")], [])
    needs = analyze_roster_needs(roster, {})
    contexts = {
        "a": context(rb, 8, 12, "up"), "b": context(wr, 10, 10),
        "c": context(no_stats), "d": context(injured, 14, 14, status="Out"),
    }
    first = rank_waiver_candidates([no_stats, injured, wr, rb], contexts, needs)
    second = rank_waiver_candidates([rb, wr, injured, no_stats], contexts, needs)
    assert [x.player.player_id for x in first] == [x.player.player_id for x in second]
    assert first[0].player.player_id == "a"
    assert any(x.player.player_id == "c" for x in first)


def test_drop_candidates_are_bench_only_conservative_and_evidence_backed():
    starter = Player("s", "Starter", "WR", "A")
    bench = [Player(str(i), f"Bench {i}", "WR", "B") for i in range(5)]
    roster = Roster([starter], bench)
    contexts = {starter.player_id: context(starter, 1)}
    contexts.update({p.player_id: context(p, i + 2, status="Out" if i == 0 else None) for i, p in enumerate(bench)})
    needs = analyze_roster_needs(roster, contexts)
    drops = find_drop_candidates(roster, contexts, needs)
    assert all(item.player.player_id != "s" for item in drops)
    assert all(item.player.player_id != "0" for item in drops)
    assert drops[0].player.player_id == "1"


def test_usage_breakout_outranks_touchdown_spike_without_usage():
    spike = Player("spike", "Touchdown Spike", "WR", "BUF")
    breakout = Player("breakout", "Usage Breakout", "WR", "DAL")
    needs = analyze_roster_needs(Roster([], []), {})
    contexts = {"spike": context(spike, 20, 20), "breakout": context(breakout, 8, 8)}
    opps = {
        "spike": PlayerOpportunity(4,None,None,None,None,2,2,1,1,1,1,"STEADY"),
        "breakout": PlayerOpportunity(4,None,None,None,None,9,11,6,7,6,7,"RISING"),
    }
    part = ParticipationSummary(4,.6,.75,40,52,None,None,None,"ROLE EXPANDING")
    profiles = {
        "spike": RoleProfile("LIMITED","ROLE STABLE","HIGH",4,1,None,None),
        "breakout": RoleProfile("EMERGING","ROLE EXPANDING","HIGH",4,1,None,part),
    }
    ranked = rank_waiver_candidates([spike, breakout], contexts, needs, opportunities=opps, profiles=profiles)
    assert ranked[0].player.player_id == "breakout"
    assert "Opportunity rising" in ranked[0].reasons
