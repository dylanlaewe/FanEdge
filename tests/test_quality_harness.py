"""M14 deterministic calibration/coherence/planning scenarios; no live providers."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from test_copilot import resolver, state
from test_trades import fixture_engine

from action_planner import goal_for, plan_actions
from backend.data_health import DataHealth, ProviderCache
from calibration import evidence_tier, resolve_adp
from copilot import CopilotAnswer, QueryIntent
from intelligence import RoleProfile
from quality import audit_state, enforce_state, waiver_is_actionable
from sleeper_api import Player, Roster
from trades import TradeOptions


@pytest.mark.parametrize(
    "quality,games,history,confidence,tier",
    [
        (30, 1, 0, "MODERATE", "SPECULATIVE"),
        (30, 1, 16, "MODERATE", "FOUNDATION"),
        (22, 4, 0, "HIGH", "HIGH_END"),
        (17, 4, 0, "HIGH", "STARTER"),
        (12, 4, 0, "HIGH", "DEPTH"),
        (5, 4, 0, "HIGH", "BENCH"),
        (30, 10, 16, "LOW", "SPECULATIVE"),
    ],
)
def test_star_and_one_game_spike_have_explicit_evidence_tiers(
    quality, games, history, confidence, tier
):
    assert (
        evidence_tier(
            quality, 20, games=games, historical_games=history, confidence=confidence
        )
        == tier
    )


def payload(**updates):
    return {
        "meta": {
            "end_date": "2026-09-18",
            "teams": 12,
            "total_drafts": 100,
            "type": "Half-PPR",
        },
        "players": [
            {
                "name": "Casey Available",
                "position": "RB",
                "team": "MIA",
                "adp": 20,
                "times_drafted": 30,
                **updates,
            }
        ],
    }


def resolve(value, players=None, **kwargs):
    return resolve_adp(
        value,
        players or state().active_players,
        season=2026,
        week=2,
        teams=12,
        scoring="half-ppr",
        today=date(2026, 9, 19),
        **kwargs,
    )


def test_adp_is_attributed_corroboration_not_replacement_rank():
    found, diagnostic = resolve(payload())
    assert diagnostic["status"] == "USABLE" and found["free-a"].samples == 30
    market = found["free-a"]
    assert (
        evidence_tier(
            17, 20, games=1, historical_games=16, confidence="MODERATE", market=market
        )
        == "HIGH_END"
    )
    assert (
        evidence_tier(17, 20, games=1, confidence="MODERATE", market=market)
        == "SPECULATIVE"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"times_drafted": 6},
        {"adp": float("nan")},
        {"team": "XXX"},
        {"position": "WR"},
        {"name": "Unmatched"},
    ],
)
def test_adp_rejects_weak_samples_and_identity_guesses(updates):
    assert resolve(payload(**updates))[0] == {}


def test_adp_rejects_stale_wrong_format_duplicate_or_ambiguous():
    value = payload()
    value["meta"]["end_date"] = "2026-08-01"
    assert not resolve(value)[0]
    value = payload()
    value["meta"]["teams"] = 10
    assert not resolve(value)[0]
    value = payload()
    value["players"] *= 2
    assert not resolve(value)[0]
    duplicate = replace(state().waiver_candidates[0].player, player_id="ambiguous")
    assert not resolve(payload(), (*state().active_players, duplicate))[0]


def ready():
    value = state()
    role = RoleProfile("EMERGING", "ROLE EXPANDING", "MODERATE", 4, 1, None, None)
    candidate = replace(value.waiver_candidates[0], intelligence=role)
    spare = Player("spare", "Spare Receiver", "WR", "DAL")
    drop = replace(value.drop_candidates[0], player=spare)
    return replace(
        value,
        roster=Roster(value.roster.starters, (*value.roster.bench, spare)),
        active_players=(*value.active_players, spare),
        waiver_candidates=(candidate,),
        drop_candidates=(drop,),
        available_ids=frozenset({"free-a"}),
        ownership={
            "roster-a": "mine",
            "roster-b": "mine",
            "spare": "mine",
            "league-a": "other",
        },
        user_roster_id="mine",
    )


def test_thin_rb_waiver_before_trade_with_release_cost():
    value = ready()
    idea = {
        "incoming": ["league-a"],
        "outgoing": ["spare"],
        "why_you": ["RB need"],
        "why_them": ["WR need"],
    }
    trade = CopilotAnswer("Trade", trades={"ideas": [idea]})
    answer = plan_actions(
        value,
        "I need an RB",
        QueryIntent("ACTION_PLAN", position="RB"),
        trade_answer=trade,
    )
    assert [a["kind"] for a in answer.plan["actions"]][:2] == ["WAIVER", "TRADE"]
    assert "releases Spare Receiver" in answer.plan["actions"][0]["cost"]
    assert "not be recoverable" in answer.plan["actions"][0]["reversibility"]


def test_deep_position_and_false_spike_do_not_become_adds():
    value = ready()
    deep = replace(
        value, roster_needs=replace(value.roster_needs, shallow_depth_positions=())
    )
    assert not waiver_is_actionable(deep.waiver_candidates[0], deep)
    weak = replace(
        value.waiver_candidates[0],
        intelligence=replace(
            value.waiver_candidates[0].intelligence, evidence_quality="LOW"
        ),
    )
    assert not waiver_is_actionable(weak, value)


def test_injured_starter_backup_emerging_role_and_bye_gates():
    value = ready()
    injured = replace(
        value,
        roster_needs=replace(
            value.roster_needs, shallow_depth_positions=(), injury_pressure={"RB": 1}
        ),
    )
    assert waiver_is_actionable(injured.waiver_candidates[0], injured)
    candidate = replace(
        injured.waiver_candidates[0],
        context=replace(injured.waiver_candidates[0].context, is_bye=True),
    )
    assert not waiver_is_actionable(candidate, injured)
    assert (
        goal_for("replace injured RB", QueryIntent("ACTION_PLAN", position="RB"))
        == "REPLACE_INJURED"
    )


def test_lineup_first_no_drop_of_recommended_starter_and_protected_release():
    value = ready()
    answer = plan_actions(value, "weekly plan", QueryIntent("WEEKLY_PLAN"))
    assert answer.action == "LINEUP_SWAP"
    answer = plan_actions(
        value,
        "I need an RB",
        QueryIntent("ACTION_PLAN", position="RB"),
        protected=("spare",),
    )
    assert answer.action == "MONITOR"
    cleaned = enforce_state(state())
    assert cleaned.drop_candidates == ()
    assert any(i["code"] == "START_DROP_CONFLICT" for i in cleaned.quality_issues)


def test_ownership_conflict_is_quarantined_across_actions_and_memory():
    value = ready()
    event = replace(
        value.opportunity_feed[0],
        subject_player=value.waiver_candidates[0].player,
        relevance=("AVAILABLE_IN_LEAGUE",),
    )
    temporal = replace(value.memory.current[0], opportunity=event)
    value = replace(
        value,
        ownership={**value.ownership, "free-a": "other"},
        opportunity_feed=(event,),
        memory=replace(value.memory, current=(temporal,), changes=(temporal,)),
    )
    clean = enforce_state(value)
    assert (
        not clean.waiver_candidates
        and not clean.opportunity_feed
        and not clean.memory.current
        and not clean.memory.changes
    )
    assert "AVAILABILITY_COLLISION" in {i["code"] for i in clean.quality_issues}


def test_ineligible_lineup_bye_schedule_and_resolved_event_invariants():
    value = ready()
    context = replace(
        value.contexts["roster-b"], is_bye=True, schedule_status="SCHEDULED"
    )
    value = replace(
        value,
        contexts={**value.contexts, "roster-b": context},
        memory=replace(
            value.memory,
            current=(replace(value.memory.current[0], lifecycle="RESOLVED"),),
        ),
    )
    codes = {i.code for i in audit_state(value)}
    assert {"SCHEDULE_CONFLICT", "ILLEGAL_LINEUP", "RESOLVED_ACTIONABLE"} <= codes
    clean = enforce_state(value)
    assert not clean.lineup_decisions and not clean.memory.current


def test_news_requires_provenance_and_trade_ownership_conflict_explained():
    value = ready()
    fact = SimpleNamespace(
        sources=(),
        urls=(),
        evidence_text="Claim",
        published_at=None,
        subject_player_id="free-a",
    )
    value = replace(value, news_facts=(fact,))
    issues = audit_state(
        value,
        ({"incoming": ["free-a"], "outgoing": ["roster-b"], "partner_id": "other"},),
    )
    assert {"NEWS_WITHOUT_PROVENANCE", "TRADE_OWNERSHIP", "START_TRADE_CONFLICT"} <= {
        i.code for i in issues
    }


def test_complementary_and_bad_quantity_trades_have_reconciled_diagnostics():
    engine = fixture_engine()
    assert engine.partners()[0]["score"] > 0
    assert engine.analyze(["ar2", "aw2"], ["br"], TradeOptions(protect_core=False))[
        "accepted"
    ]
    bad = engine.analyze(["aw", "ar"], ["br2"], TradeOptions(protect_core=False))
    assert not bad["accepted"] and bad["codes"]
    for scenario in (engine, fixture_engine(missing=True), fixture_engine(bye=True)):
        result = scenario.search(TradeOptions(protect_core=False))
        diagnostic = result["diagnostics"]
        assert (
            diagnostic["considered"] == diagnostic["rejected"] + diagnostic["surviving"]
        )
        assert sum(diagnostic["primary_reasons"].values()) == diagnostic["rejected"]
        assert diagnostic["surfaced"] == len(result["ideas"])


def test_provider_fetch_age_is_not_cache_hit_age_or_content_freshness():
    clock = [1000.0]
    health = DataHealth(lambda: clock[0])
    cache = ProviderCache(health)
    key = ("stats", 2026)
    cache.get(key, 60, lambda: [{"week": 1}])
    clock[0] += 10
    cache.get(key, 60, lambda: pytest.fail("cache hit must not refresh"))
    row = health.report({key}, expected_week=2, season=2026)[0]
    assert row["age_seconds"] == 10 and row["status"] == "DELAYED"
    assert len(health.report({key}, expected_week=2, season=2026)[0]["warnings"]) == 1
    health.observe(key, 60, failed=True)
    row = health.report({key})[0]
    assert row["status"] == "UNAVAILABLE" and row["last_success"]
    assert row["records"] == 1
    health.observe(key, 60, [])
    assert health.report({key})[0]["status"] == "EMPTY"
    clock[0] += 61
    assert health.report({key})[0]["status"] == "STALE"
    assert all("manager" not in str(r) for r in health.report())


def test_provider_failure_hold_and_goal_routes():
    from copilot import classify_query

    value = ready()
    assert (
        plan_actions(
            value, "weekly plan", QueryIntent("WEEKLY_PLAN"), fresh=False
        ).action
        == "HOLD"
    )
    for question in (
        "I need an RB",
        "Add depth",
        "Fix my lineup",
        "Replace my injured RB",
        "Get me Alex Other",
    ):
        assert classify_query(question, resolver(value)).primary_intent == "ACTION_PLAN"
    assert (
        classify_query("Find me an RB trade", resolver(value)).primary_intent
        == "TRADE_FIND"
    )


def test_depth_is_not_lineup_swap_and_target_does_not_accept_unrelated_trade():
    from copilot import classify_query

    value = ready()
    depth = plan_actions(value, "Add depth", QueryIntent("ACTION_PLAN"))
    assert depth.plan["goal"] == "ADD_DEPTH" and depth.action != "LINEUP_SWAP"
    intent = classify_query("Get me Jordan Bench", resolver(value))
    unrelated = CopilotAnswer(
        "trade",
        trades={
            "ideas": [
                {
                    "outgoing": ["spare"],
                    "incoming": ["league-a"],
                    "why_you": ["need"],
                    "why_them": ["fit"],
                }
            ]
        },
    )
    answer = plan_actions(value, "Get me Jordan Bench", intent, trade_answer=unrelated)
    assert all(a["kind"] != "TRADE" for a in answer.plan["actions"])
    unsupported = CopilotAnswer("Clarify the protection", unsupported=True)
    assert (
        plan_actions(
            value,
            "I need an RB without Mystery",
            QueryIntent("ACTION_PLAN", position="RB"),
            trade_answer=unsupported,
        )
        == unsupported
    )
