from football_data import PerformanceSummary, PlayerWeeklyContext, ScheduleStatus
from intelligence import ParticipationSummary, RoleProfile
from lineup_optimizer import LineupDecision, LineupSlot
from opportunity import PlayerOpportunity
from opportunity_engine import (
    Action, EventType, OpportunityType, Priority, Relevance, SignalType,
    build_opportunity_feed, combine_signals_into_events, detect_player_signals,
    priority_from,
)
from sleeper_api import Player, Roster
from waiver_engine import RosterNeeds, WaiverCandidate


def player(pid="p", position="WR", team="LAR", name="Test Player"):
    return Player(pid, name, position, team)


def context(p=None, *, status=None, points=8, recent=8, games=4, trend="steady", bye=False):
    p = p or player()
    summary = PerformanceSummary(games, points, recent, trend) if points is not None else None
    return PlayerWeeklyContext(p.player_id, p.name, p.position, p.team, "SF", "home", None, bye, status, None, (), summary, ScheduleStatus.SCHEDULED.value)


def usage(*, position="WR", games=4, season=4, recent=6, trend="RISING"):
    return PlayerOpportunity(
        games,
        season if position == "QB" else None, recent if position == "QB" else None,
        season if position == "RB" else None, recent if position == "RB" else None,
        season if position in {"WR", "TE"} else 2, recent if position in {"WR", "TE"} else 3,
        2, 3,
        season if position == "RB" else None, recent if position == "RB" else None,
        trend,
    )


def profile(*, games=4, snap_season=.42, snap_recent=.65, part_trend="ROLE EXPANDING", role="EMERGING", role_trend="ROLE EXPANDING", quality="HIGH", teammate=()):
    participation = ParticipationSummary(games, snap_season, snap_recent, 30, 45, None, None, None, part_trend)
    return RoleProfile(role, role_trend, quality, games, 1, None, participation, teammate, None, ())


def needs(*, shallow=("WR",), injuries=None, byes=None):
    zero = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
    return RosterNeeds(zero, zero, zero, shallow, injuries or zero, byes or zero)


def test_meaningful_snap_increase_but_not_trivial_noise():
    p = player()
    strong = detect_player_signals(p, context(p), usage(), profile(), week=5)
    noise = detect_player_signals(p, context(p), usage(trend="STEADY", season=5, recent=5), profile(snap_season=.60, snap_recent=.64), week=5)
    assert SignalType.SNAP_SHARE_INCREASE.value in {signal.signal_type for signal in strong}
    assert SignalType.SNAP_SHARE_INCREASE.value not in {signal.signal_type for signal in noise}


def test_target_and_touch_increases_are_position_specific():
    wr = player(position="WR")
    rb = player("rb", "RB")
    wr_types = {signal.signal_type for signal in detect_player_signals(wr, context(wr), usage(position="WR"), profile())}
    rb_types = {signal.signal_type for signal in detect_player_signals(rb, context(rb), usage(position="RB", season=8, recent=12), profile())}
    assert SignalType.TARGET_INCREASE.value in wr_types
    assert SignalType.TOUCH_INCREASE.value in rb_types


def test_decline_and_insufficient_sample():
    p = player()
    decline = detect_player_signals(p, context(p), usage(season=8, recent=5, trend="FALLING"), profile(snap_season=.75, snap_recent=.55, part_trend="ROLE SHRINKING", role="DECLINING", role_trend="ROLE SHRINKING"))
    short = detect_player_signals(p, context(p, games=1), usage(games=1), profile(games=1), week=2)
    types = {signal.signal_type for signal in decline}
    assert {SignalType.TARGET_DECREASE.value, SignalType.SNAP_SHARE_DECREASE.value, SignalType.ROLE_DECLINE.value} <= types
    assert not {SignalType.TARGET_INCREASE.value, SignalType.SNAP_SHARE_INCREASE.value, SignalType.ROLE_EXPANSION.value} & {signal.signal_type for signal in short}


def test_corroborating_signals_combine_and_isolated_signal_is_suppressed():
    p = player()
    signals = detect_player_signals(p, context(p), usage(), profile())
    events = combine_signals_into_events(p, signals)
    isolated = combine_signals_into_events(p, signals[:1])
    assert EventType.BREAKOUT_WATCH.value in {event.event_type for event in events}
    assert not isolated


def test_contradictory_signals_do_not_create_breakout_or_decline():
    p = player()
    positive = detect_player_signals(p, context(p), usage(), profile())
    negative = detect_player_signals(p, context(p), usage(season=8, recent=5, trend="FALLING"), profile(snap_season=.75, snap_recent=.55, part_trend="ROLE SHRINKING", role_trend="ROLE SHRINKING"))
    events = combine_signals_into_events(p, (positive[0], positive[1], negative[0], negative[1]))
    assert not {EventType.BREAKOUT_WATCH.value, EventType.DECLINE_WATCH.value} & {event.event_type for event in events}


def test_duplicate_teammate_changes_do_not_fake_corroboration():
    p = player()
    from intelligence import TeammateAvailabilityChange
    changes = (
        TeammateAvailabilityChange("One", "WR", "Questionable", "Out"),
        TeammateAvailabilityChange("Two", "WR", None, "Out"),
    )
    signals = detect_player_signals(p, context(p), None, profile(games=1, role_trend="INSUFFICIENT DATA", part_trend="INSUFFICIENT DATA", teammate=changes))
    assert EventType.BREAKOUT_WATCH.value not in {event.event_type for event in combine_signals_into_events(p, signals)}


def test_breakout_requires_usage_not_touchdown_production():
    p = player()
    spike_context = context(p, points=8, recent=20, trend="up")
    signals = detect_player_signals(p, spike_context, usage(season=5, recent=5, trend="STEADY"), profile(snap_season=.6, snap_recent=.6, part_trend="ROLE STABLE", role_trend="ROLE STABLE"))
    assert SignalType.FANTASY_PRODUCTION_CHANGE.value in {signal.signal_type for signal in signals}
    assert EventType.BREAKOUT_WATCH.value not in {event.event_type for event in combine_signals_into_events(p, signals)}


def test_priority_orders_urgent_risk_over_low_watch():
    urgent = priority_from(actionability=3, relevance=3, evidence=3, urgency=3)
    watch = priority_from(actionability=1, relevance=1, evidence=1, urgency=1)
    assert urgent == Priority.CRITICAL.value
    assert watch == Priority.LOW.value


def test_quiet_state_does_not_create_fake_content():
    p = player()
    roster = Roster([p], [])
    feed = build_opportunity_feed(roster, {p.player_id: context(p)}, {p.player_id: usage(season=5, recent=5, trend="STEADY")}, {p.player_id: profile(snap_season=.6, snap_recent=.6, part_trend="ROLE STABLE", role_trend="ROLE STABLE")}, [LineupSlot("WR1", "WR", ("WR",), p)], [], [], {}, needs(shallow=()), {}, week=5)
    assert feed == []


def test_available_breakout_aligned_to_weakness_becomes_waiver_opportunity():
    starter = player("s", "WR", name="Starter")
    candidate = player("a", "WR", name="Available")
    candidate_context = context(candidate, points=5, recent=6)
    candidate_profile = profile()
    waiver = WaiverCandidate(candidate, candidate_context, 10, ("Role expanding",), candidate_profile)
    feed = build_opportunity_feed(Roster([starter], []), {starter.player_id: context(starter)}, {}, {}, [LineupSlot("WR1", "WR", ("WR",), starter)], [], [waiver], {candidate.player_id: usage()}, needs(shallow=("WR",)), {}, week=5)
    item = feed[0]
    assert item.opportunity_type == OpportunityType.WAIVER_OPPORTUNITY.value
    assert item.recommended_action == Action.CONSIDER_ADD.value
    assert Relevance.AVAILABLE_IN_LEAGUE.value in item.relevance
    assert Relevance.SAME_POSITION_AS_ROSTER_WEAKNESS.value in item.relevance


def test_unrelated_owned_player_is_suppressed():
    user = player("u")
    unrelated = player("x", name="Other Team Player")
    feed = build_opportunity_feed(Roster([user], []), {user.player_id: context(user), unrelated.player_id: context(unrelated)}, {unrelated.player_id: usage()}, {unrelated.player_id: profile()}, [LineupSlot("WR1", "WR", ("WR",), user)], [], [], {}, needs(), {}, week=5)
    assert feed == []


def test_real_decline_surfaces_but_one_bad_game_does_not():
    veteran = player("v", name="Veteran")
    real = build_opportunity_feed(Roster([veteran], []), {"v": context(veteran)}, {"v": usage(season=8, recent=5, trend="FALLING")}, {"v": profile(snap_season=.75, snap_recent=.55, part_trend="ROLE SHRINKING", role="DECLINING", role_trend="ROLE SHRINKING")}, [LineupSlot("WR1", "WR", ("WR",), veteran)], [], [], {}, needs(), {}, week=5)
    one_week = build_opportunity_feed(Roster([veteran], []), {"v": context(veteran, games=1, points=16, recent=4, trend="down")}, {"v": usage(games=1, season=8, recent=2, trend="FALLING")}, {"v": profile(games=1, role_trend="ROLE SHRINKING")}, [LineupSlot("WR1", "WR", ("WR",), veteran)], [], [], {}, needs(), {}, week=2)
    assert real[0].opportunity_type == OpportunityType.ROLE_DECLINE.value
    assert one_week == []


def test_starter_out_tracks_replacement_and_bench_questionable_is_lower_priority():
    starter = player("s", "WR", name="Starter")
    replacement = player("b", "WR", name="Replacement")
    roster = Roster([starter], [replacement])
    feed = build_opportunity_feed(roster, {"s": context(starter, status="Out"), "b": context(replacement, status="Questionable")}, {}, {}, [LineupSlot("WR1", "WR", ("WR",), starter)], [], [], {}, needs(), {}, week=5)
    starter_item = next(item for item in feed if item.subject_player.player_id == "s")
    bench_item = next(item for item in feed if item.subject_player.player_id == "b")
    assert starter_item.related_player == replacement
    assert starter_item.priority == Priority.CRITICAL.value
    assert bench_item.priority == Priority.LOW.value


def test_starter_out_without_replacement_is_explicit():
    starter = player("s")
    feed = build_opportunity_feed(Roster([starter], []), {"s": context(starter, status="Out")}, {}, {}, [LineupSlot("WR1", "WR", ("WR",), starter)], [], [], {}, needs(), {}, week=5)
    assert "No eligible healthy bench replacement found" in feed[0].explanation_context


def test_persistent_bench_ir_does_not_crowd_feed():
    starter = player("s")
    stash = player("ir", name="IR Stash")
    feed = build_opportunity_feed(Roster([starter], [stash]), {"s": context(starter), "ir": context(stash, status="IR")}, {}, {}, [LineupSlot("WR1", "WR", ("WR",), starter)], [], [], {}, needs(), {}, week=5)
    assert feed == []


def test_lineup_decision_becomes_unified_opportunity():
    starter, challenger = player("s", name="Starter"), player("b", name="Bench")
    decision = LineupDecision("WR1", "WR", starter, challenger, "CONSIDER SWAP", 4, ("More targets",), ("MORE_TARGETS",), (), "MODERATE")
    feed = build_opportunity_feed(Roster([starter], [challenger]), {"s": context(starter), "b": context(challenger)}, {}, {}, [LineupSlot("WR1", "WR", ("WR",), starter)], [decision], [], {}, needs(), {}, week=5)
    item = next(item for item in feed if item.opportunity_type == OpportunityType.LINEUP_OPPORTUNITY.value)
    assert item.recommended_action == Action.CONSIDER_START.value
    assert Relevance.DIRECT_LINEUP_ALTERNATIVE.value in item.relevance
