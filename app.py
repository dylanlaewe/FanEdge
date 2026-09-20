"""FanEdge: an AI fantasy general manager for real Sleeper leagues."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from components import opportunity_card, page_header, player_row, prompt_tiles, section_title, swap_comparison, topbar, waiver_row
from football_data import (
    FootballDataError, NFLState, NflverseClient, PlayerWeeklyContext, WeeklySchedule,
    build_performance_index, build_player_weekly_contexts, build_weekly_schedule, normalize_nfl_state,
)
from intelligence import build_availability_changes, build_historical_index, build_participation_index, build_role_profiles
from lineup_optimizer import LineupDecision, build_current_lineup, optimize_lineup
from matchup import DefenseVsPosition, build_defense_vs_position
from memory import FeedbackStatus, LeagueScope, Lifecycle, ReconciliationResult, TemporalOpportunity
from news import ESPNNewsClient, NewsError, NewsFact, NewsItem, NewsEntityResolver, extract_facts, freshness_bucket, reconcile_facts
from news_intelligence import NewsIntelligenceResult, integrate_news_intelligence
from opportunity import PlayerOpportunity, build_opportunity_index, build_player_opportunities
from opportunity_engine import FantasyOpportunity, build_opportunity_feed
from outcomes import evaluate_pending_lineup_decisions
from player_identity import PlayerIdentity, PlayerIdentityResolver
from sleeper_api import Roster, SleeperAPIError, SleeperClient, build_roster, find_user_roster
from storage import SQLiteRepository
from strategy_engine import generate_lineup_advice, generate_strategy, generate_waiver_advice
from styles import APP_CSS
from waiver_engine import (
    WaiverCandidate, analyze_roster_needs, build_available_players, build_rostered_player_ids,
    find_drop_candidates, rank_waiver_candidates,
)

load_dotenv()
st.set_page_config(page_title="FanEdge — AI Fantasy GM", page_icon="🏈", layout="wide")
st.html(APP_CSS)


@st.cache_resource
def memory_repository(path: str) -> SQLiteRepository:
    return SQLiteRepository(path)


def current_nfl_season(now: datetime | None = None) -> int:
    today = now or datetime.now()
    return today.year - 1 if today.month <= 2 else today.year


@st.cache_data(ttl=900, show_spinner=False)
def cached_user_and_leagues(username: str, season: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    client = SleeperClient()
    user = client.get_user(username)
    return user, client.get_leagues(str(user["user_id"]), season)


@st.cache_data(ttl=300, show_spinner=False)
def cached_rosters(league_id: str) -> list[dict[str, Any]]:
    return SleeperClient().get_rosters(league_id)


@st.cache_data(ttl=86400, show_spinner=False)
def cached_players() -> dict[str, dict[str, Any]]:
    return SleeperClient(timeout=30).get_players()


@st.cache_data(ttl=300, show_spinner=False)
def cached_nfl_state() -> NFLState:
    return normalize_nfl_state(SleeperClient().get_nfl_state())


@st.cache_data(ttl=21600, show_spinner=False)
def cached_weekly_schedule(state: NFLState) -> WeeklySchedule:
    return build_weekly_schedule(NflverseClient().get_schedule_rows(), state)


@st.cache_data(ttl=21600, show_spinner=False)
def cached_weekly_indexes(state: NFLState, scoring: dict[str, Any]) -> tuple[Any, ...]:
    client = NflverseClient()
    rows = client.get_stat_rows(state.season)
    prior_rows = client.get_stat_rows(state.season - 1)
    return (
        build_performance_index(rows, state, scoring),
        build_opportunity_index(rows, state),
        build_defense_vs_position(rows, state, scoring, prior_rows),
        build_historical_index(prior_rows, state.season - 1, scoring),
        build_participation_index(client.get_snap_rows(state.season), state),
        build_participation_index(client.get_snap_rows(state.season - 1), NFLState(state.season - 1, 99, "regular")),
        build_availability_changes(client.get_injury_rows(state.season), state),
        {},  # No trustworthy historical depth-chart snapshots.
    )


@st.cache_data(ttl=86400, show_spinner=False)
def cached_identities(players: dict[str, dict[str, Any]]) -> dict[str, PlayerIdentity]:
    return PlayerIdentityResolver(NflverseClient().get_player_rows()).resolve_all(players)


@st.cache_data(ttl=900, max_entries=2, show_spinner=False)
def cached_news_items() -> list[NewsItem]:
    """One responsible batch request per cache window; never fetch article pages."""
    return ESPNNewsClient().fetch()


def scoring_label(league: dict[str, Any]) -> str:
    reception = (league.get("scoring_settings") or {}).get("rec", 0)
    if reception == 1:
        return "PPR"
    if reception == 0.5:
        return "Half PPR"
    if reception == 0:
        return "Standard"
    return f"{reception} PPR"


def reset_team() -> None:
    for key in ("user", "leagues", "roster", "raw_roster", "selected_league_id", "strategy", "waiver_advice", "lineup_advice", "application_nav"):
        st.session_state.pop(key, None)


def render_landing(nfl_state: NFLState | None) -> None:
    week = f"NFL · WEEK {nfl_state.week}" if nfl_state and nfl_state.week else "NFL FANTASY"
    st.html('<nav class="fe-landing-nav"><div class="fe-wordmark">FAN<span>EDGE</span></div>' f'<div class="fe-landing-meta">{escape(week)}</div></nav>')
    left, right = st.columns([1.12, .88], gap="large", vertical_alignment="center")
    with left:
        st.html(
            '<section class="fe-landing-copy"><div class="fe-eyebrow">AI FANTASY GENERAL MANAGER</div>'
            '<h1>KNOW YOUR<br>TEAM. FIND<br><span>YOUR EDGE.</span></h1>'
            '<p>League-aware lineup, waiver, role, and opportunity intelligence built around the players you actually manage.</p></section>'
        )
    with right:
        st.html('<section class="fe-connect"><div class="fe-eyebrow">CONNECT SLEEPER</div><h2>Bring your league into FanEdge</h2><p>Read-only access. No password required.</p></section>')
        with st.form("connect_form", border=False):
            username = st.text_input("Sleeper username", placeholder="Sleeper username", label_visibility="collapsed")
            submitted = st.form_submit_button("CONNECT MY TEAM", type="primary", width="stretch")
        st.html('<div class="fe-trust">Public Sleeper data · Nothing is changed in your league</div>')
    if submitted:
        reset_team()
        if not username.strip():
            st.warning("Enter your Sleeper username to continue.", icon=":material/warning:")
            return
        try:
            with st.spinner("Finding your leagues…", show_time=True):
                user, found_leagues = cached_user_and_leagues(username.strip(), current_nfl_season())
            if not found_leagues:
                st.warning(f"We couldn’t find any NFL leagues for the {current_nfl_season()} season.", icon=":material/info:")
            else:
                st.session_state.user = user
                st.session_state.leagues = found_leagues
                st.rerun()
        except SleeperAPIError as exc:
            st.error(str(exc), icon=":material/error:")


def top_adds(candidates: list[WaiverCandidate]) -> list[WaiverCandidate]:
    return [candidate for candidate in candidates if candidate.intelligence and (candidate.intelligence.role in {"FEATURED", "STARTER", "EMERGING"} or any(reason in {"Opportunity rising", "Role expanding", "Snap share rising"} for reason in candidate.reasons))][:4]


def render_overview(
    league: dict[str, Any], nfl_state: NFLState | None, feed: list[FantasyOpportunity],
    identities: dict[str, PlayerIdentity], data_available: bool,
    memory: ReconciliationResult | None = None,
    repository: SQLiteRepository | None = None,
    scope: LeagueScope | None = None,
    news_result: NewsIntelligenceResult | None = None,
    news_uncertain: bool = False,
) -> None:
    week = f"Week {nfl_state.week}" if nfl_state else "This week"
    temporal = memory.current if memory else tuple(TemporalOpportunity(item, item.opportunity_id, Lifecycle.ACTIVE.value, "", "") for item in feed)
    resolved = tuple(item for item in (memory.changes if memory else ()) if item.lifecycle == Lifecycle.RESOLVED.value)
    display_feed = (*temporal, *resolved)
    st.html(page_header("Your edge", "What changed", f"{week} · Proactive decisions for {league.get('name') or 'your league'}."))
    headline = f"FanEdge found {len(temporal)} {'thing' if len(temporal) == 1 else 'things'} worth your attention." if temporal else f"{len(resolved)} previous {'situation has' if len(resolved) == 1 else 'situations have'} resolved." if resolved else "No major changes."
    detail = "Prioritized from changes in role, opportunity, availability, matchup, and your actual roster." if temporal else "FanEdge did not find new evidence strong enough to change your current plan."
    st.html(
        '<section class="fe-briefing"><div class="fe-briefing-kicker">FANEDGE OPPORTUNITY ENGINE</div>'
        f'<h2>{escape(headline)}</h2><p>{escape(detail)}</p></section>'
    )
    if not data_available:
        st.info("Some weekly football data is unavailable. Unsupported conclusions are withheld.", icon=":material/info:")
    if news_uncertain:
        st.info("Current NFL reporting could not be refreshed. Last verified reports are preserved and marked as freshness-uncertain.", icon=":material/update:")
    if memory and memory.has_previous_snapshot:
        summary = memory.summary
        summary_items = [
            (summary.new, "new"), (summary.strengthened, "strengthened"),
            (summary.weakened, "weakened"), (summary.changed, "changed"),
            (summary.resolved, "resolved"), (summary.reopened, "reopened"),
        ]
        values = "".join(f'<span><strong>{count}</strong> {label}</span>' for count, label in summary_items if count)
        if values:
            st.html(f'<div class="fe-eyebrow">SINCE YOUR LAST CHECK</div><div class="fe-since">{values}</div>')
        else:
            st.caption("Since your last check: no meaningful evidence changes.")
    if not display_feed:
        st.html('<section class="fe-quiet"><div class="fe-eyebrow">PLAN HOLDS</div><h3>No action required</h3><p>Quiet weeks are useful: FanEdge will not manufacture a recommendation.</p></section>')
        render_journal(repository, scope)
        return
    st.html(section_title("Prioritized feed", len(display_feed), "item" if len(display_feed) == 1 else "items"))
    st.html('<div class="fe-edge-feed">')
    for temporal_item in display_feed:
        item = temporal_item.opportunity
        identity = identities.get(item.subject_player.player_id) if item.subject_player else None
        st.html(opportunity_card(item, identity, lifecycle=temporal_item.lifecycle))
        if temporal_item.freshness == "UNCERTAIN":
            st.caption("Freshness uncertain — the last verified evidence is preserved.")
        label = item.subject_player.name if item.subject_player else item.opportunity_type
        details = st.expander(f"Why this matters · {label}", key=f"explain_{temporal_item.event_key}", on_change="rerun")
        with details:
            for fact in item.explanation_context:
                st.markdown(f"- {fact}")
            if news_result:
                fact_index = {fact.fact_id: fact for fact in news_result.relevant_facts}
                for fact_id in news_result.facts_for(item.opportunity_id):
                    fact = fact_index.get(fact_id)
                    if not fact:
                        continue
                    st.markdown(f"> {fact.evidence_text}")
                    source = fact.sources[0] if fact.sources else "Source"
                    reported = datetime.fromisoformat(fact.published_at.replace("Z", "+00:00")).strftime("%b %-d, %-I:%M %p UTC")
                    st.caption(f"Source: {source} · Reported: {reported} · {fact.freshness.title()}")
                    if fact.urls:
                        st.link_button(f"Read on {source}", fact.urls[0], icon=":material/open_in_new:")
            st.caption(f"Action: {item.recommended_action.replace('_', ' ')} · Confidence: {item.confidence} · Relevance: {', '.join(item.relevance)}")
        if repository and scope and temporal_item.lifecycle != Lifecycle.RESOLVED.value:
            if temporal_item.feedback:
                st.caption(f"Journal status: {temporal_item.feedback.title()}")
            with st.container(horizontal=True, gap="small"):
                for status, icon in ((FeedbackStatus.DONE, ":material/check:"), (FeedbackStatus.SAVED, ":material/bookmark:"), (FeedbackStatus.DISMISSED, ":material/close:")):
                    if st.button(status.value.title(), icon=icon, key=f"feedback_{status.value}_{temporal_item.event_key}"):
                        repository.record_feedback(scope, temporal_item.event_key, status.value)
                        repository.record_analytics(scope, f"recommendation_{status.value.lower()}", event_key=temporal_item.event_key)
                        st.toast(f"Recommendation {status.value.lower()}.", icon=icon)
                        st.rerun()
    st.html('</div>')
    render_journal(repository, scope)


def render_journal(repository: SQLiteRepository | None, scope: LeagueScope | None) -> None:
    if not repository or not scope:
        return
    history = st.expander("Decision journal", icon=":material/history:", key="decision_journal", on_change="rerun")
    with history:
        entries = repository.journal(scope)
        if not entries:
            st.caption("Recommendations will appear here after FanEdge surfaces them.")
            return
        for entry in entries:
            timing = "This week" if entry.week == scope.week else f"Week {entry.week}"
            name = entry.subject_name or entry.opportunity_type.replace("_", " ").title()
            with st.container(border=True):
                st.markdown(f"**{name}** · {timing} · {entry.lifecycle.title()}")
                st.caption(f"{entry.action.replace('_', ' ').title()} · {entry.priority.title()} priority · {entry.confidence.title()} confidence")
                if entry.related_name:
                    st.caption(f"Compared with {entry.related_name}")
                if entry.feedback:
                    st.badge(entry.feedback.title(), color="green" if entry.feedback == FeedbackStatus.DONE.value else "blue" if entry.feedback == FeedbackStatus.SAVED.value else "gray")
                if entry.outcome:
                    score = ""
                    if entry.recommended_points is not None and entry.alternative_points is not None:
                        score = f" · {entry.recommended_points:.1f} vs {entry.alternative_points:.1f}"
                    st.caption(f"Observed result: {entry.outcome.replace('_', ' ').title()}{score}")


def render_decision_evidence(decision: LineupDecision) -> None:
    st.caption(f"Evidence confidence: {decision.confidence} — not an outcome probability.")
    if not decision.evidence:
        st.caption("No additional structured evidence is available.")
        return
    if "SMALL_SAMPLE_WARNING" in decision.reason_codes:
        st.warning("Limited sample — this recommendation is intentionally conservative.", icon=":material/warning:")
    for item in decision.evidence:
        st.markdown(f"**{item.label}** · {item.factual_value} {item.comparison}")
        st.caption(f"Source: {item.source_type}")


def render_my_team(
    lineup_slots: list[Any], roster: Roster, contexts: dict[str, PlayerWeeklyContext],
    opportunities: dict[str, PlayerOpportunity], profiles: dict[str, Any],
    identities: dict[str, PlayerIdentity], decisions: list[LineupDecision],
    has_openai_key: bool,
) -> None:
    st.html(page_header("My team", "Your lineup, in context", "Actual league slots with the signal that matters for each position."))
    if not decisions:
        st.success("Lineup check complete — no bench player currently justifies a change.", icon=":material/check_circle:")
    by_slot = {decision.slot_id: decision for decision in decisions}
    st.html(section_title("Starters", len(lineup_slots), "slots"))
    st.html('<div class="fe-roster-list">')
    for slot in lineup_slots:
        player = slot.current_player
        st.html(player_row(player, slot.slot_id, contexts.get(player.player_id) if player else None, opportunities.get(player.player_id) if player else None, profiles.get(player.player_id) if player else None, identities.get(player.player_id) if player else None, recommended=slot.slot_id in by_slot))
        if slot.slot_id in by_slot:
            decision = by_slot[slot.slot_id]
            st.html(swap_comparison(decision, identities))
            with st.expander(f"Why this move · {decision.challenger.name}"):
                render_decision_evidence(decision)
    st.html("</div>")
    challenger_ids = {item.challenger.player_id for item in decisions}
    st.html(section_title("Bench", len(roster.bench)))
    st.html('<div class="fe-roster-list">')
    for index, player in enumerate(roster.bench, start=1):
        st.html(player_row(player, f"BN{index}", contexts.get(player.player_id), opportunities.get(player.player_id), profiles.get(player.player_id), identities.get(player.player_id), recommended=player.player_id in challenger_ids))
    st.html("</div>")
    if decisions and st.button("Explain my lineup", type="primary", width="stretch", disabled=not has_openai_key, key="lineup_explanation"):
        try:
            with st.spinner("Building your lineup explanation…"):
                st.session_state.lineup_advice = generate_lineup_advice(lineup_slots, decisions, contexts, opportunities, profiles)
        except Exception:
            st.error("We couldn’t explain the lineup decisions right now.", icon=":material/error:")
    if st.session_state.get("lineup_advice"):
        st.html('<section class="fe-ai-result"><div class="fe-eyebrow">FANEDGE ANALYSIS</div>' f'<p>{escape(st.session_state.lineup_advice)}</p></section>')


def render_waivers(
    candidates: list[WaiverCandidate], opportunities: dict[str, PlayerOpportunity], identities: dict[str, PlayerIdentity],
    roster_needs: Any, drop_candidates: list[Any], has_openai_key: bool,
    feed: list[FantasyOpportunity],
) -> None:
    st.html(page_header("Waivers", "Find the next useful player", "Ranked against your roster needs, league ownership, and role evidence."))
    position = st.segmented_control("Filter by position", ["All", "RB", "WR", "TE", "QB"], default="All", key="waiver_position", label_visibility="collapsed")
    opportunity_ids = {item.subject_player.player_id for item in feed if item.subject_player and item.opportunity_type in {"WAIVER_OPPORTUNITY", "BREAKOUT_WATCH"}}
    ordered = sorted(candidates, key=lambda item: (item.player.player_id not in opportunity_ids, -item.score, item.player.name.lower()))
    filtered = [item for item in ordered if position == "All" or item.player.position == position]
    adds = [item for item in filtered if item.player.player_id in opportunity_ids or item in top_adds(candidates)][:4]
    watchlist = [item for item in filtered if item not in adds]
    st.html(section_title("Top adds", len(adds)))
    if adds:
        st.html('<div class="fe-waiver-list">')
        for rank, candidate in enumerate(adds, start=1):
            st.html(waiver_row(candidate, rank, identities.get(candidate.player.player_id), opportunities.get(candidate.player.player_id)))
        st.html("</div>")
    else:
        st.caption("No player in this filter has enough role evidence to qualify as a priority add.")
    st.html(section_title("Watchlist", len(watchlist)))
    if watchlist:
        st.html('<div class="fe-waiver-list fe-watchlist">')
        for rank, candidate in enumerate(watchlist, start=len(adds) + 1):
            st.html(waiver_row(candidate, rank, identities.get(candidate.player.player_id), opportunities.get(candidate.player.player_id)))
        st.html("</div>")
    else:
        st.caption("No additional player signals surfaced for this filter.")
    if candidates and st.button("Explain my waiver options", type="primary", width="stretch", disabled=not has_openai_key, key="waiver_explanation"):
        try:
            with st.spinner("Summarizing your waiver options…"):
                st.session_state.waiver_advice = generate_waiver_advice(roster_needs, candidates, drop_candidates)
        except Exception:
            st.error("We couldn’t explain the waiver shortlist right now.", icon=":material/error:")
    if st.session_state.get("waiver_advice"):
        for item in st.session_state.waiver_advice:
            st.html('<section class="fe-ai-result">' f'<h3>{escape(item["title"])}</h3><p>{escape(item["body"])}</p></section>')


def render_ask_fanedge(
    roster: Roster, league: dict[str, Any], nfl_state: NFLState | None,
    contexts: dict[str, PlayerWeeklyContext], has_openai_key: bool,
    feed: list[FantasyOpportunity],
    repository: SQLiteRepository | None = None,
    scope: LeagueScope | None = None,
    news_facts: tuple[NewsFact, ...] = (),
) -> None:
    st.html(
        '<section class="fe-ai-hero"><div><div class="fe-eyebrow">ASK FANEDGE</div><h1>Your league context, explained.</h1>'
        '<p>FanEdge can turn lineup, waiver, role, availability, and relevant recent reporting into a concise weekly plan.</p></div>'
        '<aside class="fe-capability"><strong>What this can do now</strong><br>Explain FanEdge decisions using your roster, verified evidence, and the cited recent reports supplied here. It cannot invent or search for missing news.</aside></section>'
    )
    st.html(section_title("Suggested questions"))
    st.html(prompt_tiles(("What changed with my team today?", "Did any injuries create an opportunity?", "What should I monitor before kickoff?")))
    if st.button("Build my weekly strategy", type="primary", width="stretch", disabled=not has_openai_key, key="strategy_button"):
        try:
            with st.spinner("Building your weekly strategy…", show_time=True):
                st.session_state.strategy = generate_strategy(roster, league, nfl_state=nfl_state, weekly_contexts=contexts, opportunity_feed=feed, news_facts=news_facts)
                if repository and scope:
                    repository.record_analytics(scope, "ask_fanedge_used")
        except Exception:
            st.error("We couldn’t build your strategy right now.", icon=":material/error:")
    if not has_openai_key:
        st.info("AI explanation is not configured in this environment. Your deterministic lineup and waiver intelligence remains available.", icon=":material/info:")
    strategy = st.session_state.get("strategy")
    if strategy:
        st.html(section_title("Your weekly edge"))
        for recommendation in strategy:
            st.html('<section class="fe-ai-result">' f'<h3>{escape(recommendation["title"].replace("/", " / "))}</h3><p>{escape(recommendation["body"])}</p></section>')


def connected_app(leagues: list[dict[str, Any]], nfl_state: NFLState | None) -> None:
    league_by_id = {str(league["league_id"]): league for league in leagues}
    current_id = st.session_state.get("selected_league_id")
    preview_id = current_id if current_id in league_by_id else next(iter(league_by_id))
    preview_league = league_by_id[preview_id]
    user = st.session_state.user
    username = str(user.get("display_name") or user.get("username") or "Sleeper manager")
    st.radio("Primary navigation", ["Overview", "My Team", "Waivers", "Ask FanEdge"], key="application_nav", label_visibility="collapsed")
    st.html(topbar(str(preview_league.get("name") or "Unnamed league"), scoring_label(preview_league), username, nfl_state.week if nfl_state else None))
    if len(leagues) > 1:
        selected_id = st.selectbox("League", list(league_by_id), index=list(league_by_id).index(preview_id), format_func=lambda league_id: league_by_id[league_id].get("name") or "Unnamed league", key="league_selector")
    else:
        selected_id = preview_id
    league = league_by_id[selected_id]
    if st.session_state.get("selected_league_id") != selected_id or "roster" not in st.session_state or "raw_roster" not in st.session_state:
        for key in ("roster", "strategy", "waiver_advice", "lineup_advice"):
            st.session_state.pop(key, None)
        try:
            with st.spinner("Importing your roster…", show_time=True):
                raw = find_user_roster(cached_rosters(selected_id), str(user["user_id"]))
                st.session_state.roster = build_roster(raw, cached_players())
                st.session_state.raw_roster = raw
                st.session_state.selected_league_id = selected_id
            st.rerun()
        except SleeperAPIError as exc:
            st.error(str(exc), icon=":material/error:")
            return
    roster: Roster | None = st.session_state.get("roster")
    if not roster:
        return
    metadata = cached_players()
    league_rosters = cached_rosters(selected_id)
    schedule: WeeklySchedule | dict[str, Any] = WeeklySchedule({}, False, ("schedule unavailable",))
    performances: dict[Any, Any] = {}
    opportunity_index: dict[Any, Any] = {}
    matchup_index: dict[tuple[str, str], DefenseVsPosition] = {}
    historical_index: dict[Any, Any] = {}
    participation_index: dict[Any, Any] = {}
    historical_participation: dict[Any, Any] = {}
    availability_index: dict[Any, Any] = {}
    depth_ranks: dict[str, int] = {}
    weekly_data_fresh = False
    if nfl_state:
        with st.status(f"Preparing Week {nfl_state.week}", expanded=False) as load_status:
            try:
                schedule = cached_weekly_schedule(nfl_state)
                performances, opportunity_index, matchup_index, historical_index, participation_index, historical_participation, availability_index, depth_ranks = cached_weekly_indexes(nfl_state, league.get("scoring_settings") or {})
                weekly_data_fresh = bool(schedule.complete)
                load_status.update(label="Week intelligence ready", state="complete")
            except FootballDataError:
                load_status.update(label="Some weekly evidence is unavailable", state="error")
    try:
        identities = cached_identities(metadata)
    except FootballDataError:
        identities = {}
        weekly_data_fresh = False
    contexts = build_player_weekly_contexts(roster, metadata, schedule, performances, identities=identities)
    opportunities = build_player_opportunities((*roster.starters, *roster.bench), opportunity_index, identities)
    profiles = build_role_profiles((*roster.starters, *roster.bench), opportunities, identities, historical_index, participation_index, availability_index, depth_ranks, historical_participation)
    lineup_slots = build_current_lineup(st.session_state.raw_roster, metadata, league.get("roster_positions") or [])
    decisions, lineup_health = optimize_lineup(lineup_slots, roster, contexts, opportunities, matchup_index, {player_id: bool(identity.gsis_id) for player_id, identity in identities.items()}, profiles)
    owned_ids = build_rostered_player_ids(league_rosters)
    available_players = build_available_players(metadata, owned_ids)
    available_contexts = build_player_weekly_contexts(Roster(starters=available_players, bench=[]), metadata, schedule, performances, identities=identities)
    roster_needs = analyze_roster_needs(roster, contexts)
    available_opportunities = build_player_opportunities(available_players, opportunity_index, identities)
    available_profiles = build_role_profiles(available_players, available_opportunities, identities, historical_index, participation_index, availability_index, depth_ranks, historical_participation)
    waiver_candidates = rank_waiver_candidates(available_players, available_contexts, roster_needs, opportunities=available_opportunities, profiles=available_profiles)
    drop_candidates = find_drop_candidates(roster, contexts, roster_needs)
    opportunity_feed = build_opportunity_feed(
        roster, contexts, opportunities, profiles, lineup_slots, decisions,
        waiver_candidates, available_opportunities, roster_needs, matchup_index,
        week=nfl_state.week if nfl_state else None,
    )
    repository: SQLiteRepository | None = None
    scope: LeagueScope | None = None
    memory: ReconciliationResult | None = None
    database_path = os.getenv("FANEDGE_DB_PATH") or str(Path(".fanedge") / "fanedge.db")
    repository = memory_repository(database_path)
    scope_season = nfl_state.season if nfl_state else int(league.get("season") or current_nfl_season())
    settings = league.get("settings") if isinstance(league.get("settings"), dict) else {}
    scope_week = nfl_state.week if nfl_state else int(settings.get("leg") or 0)
    scope = LeagueScope(str(user["user_id"]), selected_id, scope_season, scope_week)
    news_uncertain = False
    news_fetch_succeeded = False
    try:
        raw_news = cached_news_items()
        all_active_players = build_available_players(metadata, set())
        resolved_news = NewsEntityResolver(all_active_players, identities).resolve_all(raw_news)
        news_facts = tuple(reconcile_facts(extract_facts(resolved_news)))
        news_fetch_succeeded = True
    except NewsError:
        news_uncertain = True
        news_facts = tuple(replace(fact, freshness=freshness_bucket(fact.published_at), provider_fresh=False) for fact in repository.load_news_facts(scope))
    news_result = integrate_news_intelligence(
        opportunity_feed, news_facts, roster, contexts, available_players,
        available_opportunities, available_profiles, profiles, roster_needs,
        week=nfl_state.week if nfl_state else None,
    )
    if news_fetch_succeeded:
        repository.save_news_facts(scope, news_result.relevant_facts)
    opportunity_feed = list(news_result.feed)
    memory = repository.reconcile(scope, opportunity_feed, data_fresh=weekly_data_fresh)
    if weekly_data_fresh:
        evaluate_pending_lineup_decisions(repository, scope, scope_week, performances)
    repository.record_analytics(
        scope, "league_connected",
        idempotency_key=f"league-connected:{scope.sleeper_user_id}:{scope.league_id}:{scope.season}",
    )
    has_openai_key = bool(os.getenv("OPENAI_API_KEY"))
    view = st.session_state.application_nav
    if view == "Overview":
        if repository and scope and memory:
            repository.record_analytics(scope, "overview_viewed", metadata={"items": len(memory.current)}, idempotency_key=f"overview:{memory.snapshot_id}")
            for item in memory.current:
                repository.record_analytics(scope, "recommendation_viewed", event_key=item.event_key, metadata={"type": item.opportunity.opportunity_type}, idempotency_key=f"recommendation:{memory.snapshot_id}:{item.event_key}")
        render_overview(league, nfl_state, opportunity_feed, identities, weekly_data_fresh, memory, repository, scope, news_result, news_uncertain)
    elif view == "My Team":
        if repository and scope and memory:
            for item in memory.current:
                if item.opportunity.opportunity_type == "LINEUP_OPPORTUNITY":
                    repository.record_analytics(scope, "lineup_recommendation_viewed", event_key=item.event_key, idempotency_key=f"lineup-view:{memory.snapshot_id}:{item.event_key}")
        render_my_team(lineup_slots, roster, contexts, opportunities, profiles, identities, decisions, has_openai_key)
    elif view == "Waivers":
        if repository and scope and memory:
            for item in memory.current:
                if item.opportunity.opportunity_type in {"WAIVER_OPPORTUNITY", "BREAKOUT_WATCH"}:
                    repository.record_analytics(scope, "waiver_recommendation_viewed", event_key=item.event_key, idempotency_key=f"waiver-view:{memory.snapshot_id}:{item.event_key}")
        render_waivers(waiver_candidates, available_opportunities, identities, roster_needs, drop_candidates, has_openai_key, opportunity_feed)
    else:
        render_ask_fanedge(roster, league, nfl_state, contexts, has_openai_key, opportunity_feed, repository, scope, news_result.relevant_facts)


try:
    nfl_state: NFLState | None = cached_nfl_state()
except (SleeperAPIError, FootballDataError):
    nfl_state = None

leagues = st.session_state.get("leagues", [])
if leagues:
    connected_app(leagues, nfl_state)
else:
    render_landing(nfl_state)
