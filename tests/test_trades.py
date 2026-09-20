from dataclasses import replace
from types import SimpleNamespace
import pytest
from football_data import PerformanceSummary, PlayerWeeklyContext
from sleeper_api import Player, Roster
from trades import TradeEngine, TradeOptions, assign_lineup
from copilot import CopilotEntityResolver, classify_query


def fixture_engine(
    *,
    missing=False,
    injury=None,
    capacity=5,
    bye=False,
    reserved=False,
    slots=None,
    free_injury=None,
):
    specs = [
        ("ar", "RB", 5),
        ("aw", "WR", 20),
        ("aw2", "WR", 16),
        ("ar2", "RB", 1),
        ("br", "RB", 20),
        ("bw", "WR", 5),
        ("br2", "RB", 16),
        ("bw2", "WR", 1),
        ("free_r", "RB", 3),
        ("free_w", "WR", 3),
    ]
    players = [Player(pid, f"Player {pid}", pos, "LAR") for pid, pos, _ in specs]
    contexts = {
        p.player_id: PlayerWeeklyContext(
            p.player_id,
            p.name,
            p.position,
            p.team,
            "NYG",
            "home",
            None,
            bye and p.player_id == "ar",
            injury
            if p.player_id == "ar"
            else free_injury
            if p.player_id == "free_r"
            else None,
            None,
            (),
            None if missing else PerformanceSummary(4, value, value, "steady"),
        )
        for p, (_, _, value) in zip(players, specs)
    }
    rosters = [
        {
            "roster_id": "a",
            "owner_id": "user",
            "starters": ["ar", "aw"],
            "players": ["ar", "aw", "ar2", "aw2"],
        },
        {
            "roster_id": "b",
            "owner_id": "other",
            "starters": ["br", "bw"],
            "players": ["br", "bw", "br2", "bw2"],
        },
    ]
    metadata = {
        p.player_id: {"full_name": p.name, "position": p.position, "team": p.team}
        for p in players
    }
    if reserved:
        rosters[0]["reserve"] = ["aw2"]
    state = SimpleNamespace(
        active_players=players,
        contexts=contexts,
        profiles={},
        opportunities={},
        league={"roster_positions": slots or ["RB", "WR"] + ["BN"] * (capacity - 2)},
        roster=Roster(players[:2], players[2:4]),
    )
    return TradeEngine(state, rosters, metadata, "user")


def test_profiles_explain_surplus_need_balanced_and_shallow_rosters():
    engine = fixture_engine()
    assert engine.profiles["a"]["positions"]["WR"]["status"] == "SURPLUS"
    assert engine.profiles["a"]["positions"]["RB"]["status"] == "NEED"
    shallow = engine.profile(["aw"])
    assert shallow["positions"]["RB"]["status"] == "STRONG_NEED"
    assert not shallow["valid"]
    assert engine.profile(["aw", "br"])["positions"]["RB"]["status"] == "BALANCED"


def test_two_starter_consolidation_requires_strong_evidence_even_when_unlocked():
    result = fixture_engine().analyze(
        ["aw", "ar"], ["br2"], TradeOptions(protect_core=False)
    )
    assert not result["accepted"]
    assert any("stronger evidence" in reason for reason in result["rejections"])


def test_default_core_lock_can_be_overridden_by_trade_block_but_not_explicit_lock():
    engine = fixture_engine()
    assert "aw" in engine.default_protected
    assert "aw" not in engine.protections(TradeOptions(trade_block=("aw",)))
    assert "aw" in engine.protections(
        TradeOptions(trade_block=("aw",), protected=("aw",))
    )


def test_bye_reserve_and_unsupported_slots_fail_closed():
    engine = fixture_engine(bye=True)
    assert engine.profiles["a"]["positions"]["RB"]["bye_pressure"] == 1
    assert not engine.values["ar"].available
    reserved = fixture_engine(reserved=True)
    assert "aw2" not in reserved.teams["a"]["player_ids"]
    assert not reserved.analyze(["aw2"], ["br2"])["accepted"]
    unsupported = fixture_engine(slots=["RB", "WR", "IDP", "BN", "BN"])
    assert not unsupported.enabled
    assert not unsupported.search(TradeOptions(protect_core=False))["ideas"]


def test_third_one_qb_backup_does_not_count_as_more_depth():
    engine = fixture_engine()
    for pid in ("ar", "ar2", "br", "br2"):
        engine.players[pid] = replace(engine.players[pid], position="QB")
        engine.values[pid] = replace(
            engine.values[pid], quality=20, supported=True, available=True
        )
    engine.typical["QB"], engine.replacement["QB"] = 20, 3
    engine.slots = [("QB", ("QB",))]
    engine._profiles.clear()
    assert (
        engine.profile(["ar", "ar2"])["depth_quality"]
        == engine.profile(["ar", "ar2", "br"])["depth_quality"]
    )


def test_injury_pressure_and_unknown_are_not_surplus():
    engine = fixture_engine(injury="Out")
    assert engine.profiles["a"]["positions"]["RB"]["injury_pressure"] == 1
    unknown = fixture_engine(missing=True)
    assert not unknown.values["ar"].supported
    assert unknown.search()["ideas"] == []


def test_complementary_partner_rank_and_no_complementary_fit():
    engine = fixture_engine()
    assert engine.partners()[0]["score"] >= 6
    engine.profiles["b"] = engine.profiles["a"]
    assert engine.partners()[0]["score"] == 0
    assert not engine.search()["ideas"]


def test_relative_and_replacement_values_use_unowned_evidence():
    engine = fixture_engine()
    assert (
        engine.values["aw"].relative_value
        > engine.values["aw2"].relative_value
        > engine.values["bw"].relative_value
    )
    assert engine.replacement["RB"] == 3
    assert engine.values["ar"].typical_starter == 18


def test_unavailable_free_agent_is_not_a_usable_replacement_baseline():
    assert fixture_engine(free_injury="Out").replacement["RB"] is None


@pytest.mark.parametrize(
    "outgoing,incoming",
    [(("aw2",), ("br2",)), (("aw2", "ar2"), ("br2",)), (("aw2",), ("br2", "bw2"))],
)
def test_all_package_shapes_simulate_both_rosters(outgoing, incoming):
    result = fixture_engine().analyze(
        outgoing, incoming, TradeOptions(goal="RB", protect_core=False)
    )
    assert result["accepted"], result["rejections"]
    idea = result["idea"]
    assert idea["user_impact"]["lineup_delta"] > 0
    assert idea["partner_impact"]["lineup_delta"] > 0
    assert idea["user_impact"]["before"]["RB"]["status"] == "NEED"
    assert idea["user_impact"]["after"]["RB"]["status"] != "NEED"
    assert idea["partner_impact"]["changes"]


def test_protected_overrides_block_and_block_preserves_value():
    engine = fixture_engine()
    value = engine.values["aw2"].relative_value
    result = engine.search(
        TradeOptions(
            goal="RB", protected=("aw2",), trade_block=("aw2",), protect_core=False
        )
    )
    assert all("aw2" not in i["outgoing"] for i in result["ideas"])
    assert engine.values["aw2"].relative_value == value
    blocked = engine.analyze(
        ["aw2"], ["br2"], TradeOptions(protected=("aw2",), trade_block=("aw2",))
    )
    assert not blocked["accepted"]


@pytest.mark.parametrize(
    "outgoing,incoming",
    [
        (["aw2", "aw2"], ["br2"]),
        (["br2"], ["aw2"]),
        (["aw2"], ["free_r"]),
        (["unknown"], ["br2"]),
        (["aw2"], ["br2", "ar2"]),
    ],
)
def test_invalid_ownership_duplicates_unknown_rejected(outgoing, incoming):
    assert not fixture_engine().analyze(outgoing, incoming)["accepted"]


def test_garbage_one_sided_and_unaddressed_goal_are_rejected():
    engine = fixture_engine()
    assert not engine.analyze(["ar2"], ["br"], TradeOptions(protect_core=False))[
        "accepted"
    ]
    assert not engine.analyze(
        ["aw2"], ["br2"], TradeOptions(goal="TE", protect_core=False)
    )["accepted"]
    assert not engine.analyze(["aw2"], ["bw"], TradeOptions(protect_core=False))[
        "accepted"
    ]


def test_capacity_is_explicit_and_post_trade_assignment_has_no_duplicates():
    result = fixture_engine(capacity=4).analyze(
        ["aw2"], ["br2", "bw2"], TradeOptions(protect_core=False)
    )
    assert not result["accepted"] or result["idea"]["user_impact"]["required_drops"]
    slots = [("FLEX", ("WR", "RB")), ("RB", ("RB",))]
    players = [Player("r", "Runner", "RB", "LAR"), Player("w", "Receiver", "WR", "LAR")]
    assignment, score = assign_lineup(slots, players, {"r": 20, "w": 15})
    assert assignment == ("w", "r") and score == 35


def test_search_target_trade_block_determinism_and_variation():
    engine = fixture_engine()
    options = TradeOptions(
        goal="RB", trade_block=("aw2",), target_id="br2", protect_core=False
    )
    result = engine.search(options)
    assert result["ideas"] and all(
        "br2" in idea["incoming"] for idea in result["ideas"]
    )
    assert result["ideas"] == engine.search(options)["ideas"]
    other = engine.search(replace(options, exclude_ids=(result["ideas"][0]["id"],)))
    assert result["ideas"][0]["id"] not in [idea["id"] for idea in other["ideas"]]


@pytest.mark.parametrize(
    "question,intent",
    [
        ("Find me an RB trade", "TRADE_FIND"),
        ("Find me a running back", "ACTION_PLAN"),
        ("Get me Player br2", "ACTION_PLAN"),
        ("Who should I shop?", "TRADE_AWAY"),
        ("Trade Player aw2 for Player br2", "TRADE_ANALYZE"),
        ("Which team is the best trade partner?", "TRADE_PARTNER"),
        ("Find trades without giving up Player aw", "TRADE_FIND"),
    ],
)
def test_trade_intent_routes(question, intent):
    engine = fixture_engine()
    resolver = CopilotEntityResolver(
        engine.state.roster,
        (),
        [engine.players[p] for p in engine.teams["b"]["player_ids"]],
        engine.players.values(),
    )
    assert classify_query(question, resolver).primary_intent == intent
