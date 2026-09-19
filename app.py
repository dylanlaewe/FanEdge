"""FanEdge Streamlit application."""

from __future__ import annotations

import os
from datetime import datetime
from html import escape
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from football_data import (
    FootballDataError,
    NFLState,
    NflverseClient,
    PlayerWeeklyContext,
    WeeklySchedule,
    build_performance_index,
    build_player_weekly_contexts,
    build_weekly_schedule,
    normalize_nfl_state,
)
from lineup_optimizer import LineupDecision, build_current_lineup, optimize_lineup
from matchup import DefenseVsPosition, build_defense_vs_position
from opportunity import PlayerOpportunity, build_opportunity_index, build_player_opportunities
from intelligence import (
    build_availability_changes, build_historical_index,
    build_participation_index, build_role_profiles,
)
from sleeper_api import Roster, SleeperAPIError, SleeperClient, build_roster, find_user_roster
from player_identity import PlayerIdentity, PlayerIdentityResolver
from strategy_engine import generate_lineup_advice, generate_strategy, generate_waiver_advice
from waiver_engine import (
    WaiverCandidate,
    analyze_roster_needs,
    build_available_players,
    build_rostered_player_ids,
    find_drop_candidates,
    rank_waiver_candidates,
)

load_dotenv()
st.set_page_config(page_title="FanEdge — AI Fantasy Strategist", page_icon="🏈", layout="wide")

st.html("""
<style>
:root{--bg:#090b0f;--surface:#12171f;--raised:#161c25;--border:#252d38;--bright:#354150;--lime:#b6f23a;--text:#f5f7fa;--muted:#8b95a5;--radius:14px}
html,.stApp{background:var(--bg);color:var(--text)}
.block-container{max-width:1180px;padding:0 2.25rem 5rem}
header[data-testid="stHeader"],footer,#MainMenu{display:none}[data-testid="stToolbar"]{visibility:hidden}
h1,h2,h3,p{color:var(--text)}
.fe-nav{height:76px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border)}
.fe-wordmark{font-size:1rem;font-weight:900;letter-spacing:.12em}.fe-wordmark span,.fe-eyebrow{color:var(--lime)}
.fe-nav-context{color:var(--muted);font-size:.7rem;font-weight:750;letter-spacing:.12em}
.fe-nav-context:before{content:"";display:inline-block;width:6px;height:6px;margin-right:8px;border-radius:50%;background:var(--lime);box-shadow:0 0 10px rgba(182,242,58,.35);vertical-align:1px}
.fe-hero{max-width:780px;margin:0 auto;padding:3.2rem 0 1.8rem;text-align:center}
.fe-eyebrow{font-size:.7rem;font-weight:850;letter-spacing:.17em;text-transform:uppercase}
.fe-hero h1{margin:1.05rem 0 1.1rem;font-size:clamp(3.2rem,5.6vw,4.8rem);line-height:.92;letter-spacing:-.065em;font-weight:900}.fe-hero h1 span{color:var(--lime)}
.fe-hero p{max-width:560px;margin:0 auto;color:var(--muted);font-size:1.05rem;line-height:1.65}
.fe-connect-copy{max-width:620px;margin:0 auto -1px;padding:1.55rem 1.8rem .65rem;background:linear-gradient(145deg,#151b23,#11161d);border:1px solid var(--border);border-bottom:0;border-radius:var(--radius) var(--radius) 0 0}
.fe-connect-copy h2{margin:.55rem 0 .3rem;font-size:1.3rem;letter-spacing:-.025em}.fe-connect-copy p{margin:0;color:var(--muted);font-size:.88rem}
div[data-testid="stForm"]{max-width:620px;margin:-1rem auto 0;padding:.55rem 1.8rem 1.45rem;background:linear-gradient(145deg,#151b23,#11161d);border:1px solid var(--border);border-top:0;border-radius:0 0 var(--radius) var(--radius)}
.fe-trust{max-width:620px;margin:.65rem auto 0;text-align:center;color:#687383;font-size:.73rem}
.stTextInput input,.stSelectbox [data-baseweb="select"]>div{background:#0d1117!important;border-color:var(--border)!important;border-radius:9px!important;color:var(--text)!important}.stTextInput input{min-height:48px}.stTextInput input:focus{border-color:var(--lime)!important;box-shadow:0 0 0 2px rgba(182,242,58,.12)!important}
.stButton button,.stFormSubmitButton button{min-height:48px;border-radius:9px;font-weight:850;letter-spacing:.045em;transition:transform .15s ease,filter .15s ease}.stButton button[kind="primary"],.stFormSubmitButton button[kind="primary"]{background:var(--lime);color:#0b0e08;border-color:var(--lime)}.stButton button:hover,.stFormSubmitButton button:hover{transform:translateY(-1px);filter:brightness(1.06)}
.fe-connected{margin-top:1.7rem;padding:1.35rem 1.5rem 1.2rem;background:linear-gradient(145deg,#141a22,#10151b);border:1px solid var(--border);border-radius:var(--radius)}.fe-connected:has(.fe-league-select-label){padding-bottom:5rem}.fe-context h1{margin:.4rem 0 .45rem;font-size:clamp(2rem,4vw,3rem);line-height:1;letter-spacing:-.05em}.fe-meta{display:flex;align-items:center;gap:.55rem;flex-wrap:wrap;color:var(--muted);font-size:.78rem}.fe-meta span{color:#d6dce3}.fe-meta .dot{color:#505b69}.fe-league-select-label{color:var(--muted);font-size:.65rem;font-weight:800;letter-spacing:.12em;margin:1rem 0 .3rem}.stSelectbox{max-width:420px;margin:-4.35rem 0 1rem 1.5rem}
.fe-roster-title{display:flex;align-items:end;justify-content:space-between;margin:2rem 0 .55rem;padding-bottom:.85rem;border-bottom:1px solid var(--border)}.fe-roster-title h2{margin:.35rem 0 0;font-size:1.75rem;letter-spacing:-.035em}.fe-section-header{display:flex;align-items:center;justify-content:space-between;margin:1.5rem 0 .7rem}.fe-section-header h3{margin:0;font-size:.72rem;letter-spacing:.13em;text-transform:uppercase}.fe-count{color:var(--muted);font-size:.68rem;font-weight:750;letter-spacing:.1em}
.fe-roster-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.72rem}.fe-player-card{box-sizing:border-box;display:flex;flex-direction:column;justify-content:center;min-width:0;min-height:106px;padding:.9rem 1rem;background:var(--surface);border:1px solid var(--border);border-radius:11px;transition:border-color .15s ease,transform .15s ease,background .15s ease}.fe-player-card:hover{transform:translateY(-1px);border-color:var(--bright);background:var(--raised)}.fe-player-card.starter{border-top-color:rgba(182,242,58,.55)}.fe-player-top{display:flex;align-items:center;gap:.6rem;min-width:0;line-height:1.15}.fe-position{box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;flex:0 0 34px;height:24px;border-radius:6px;background:rgba(182,242,58,.1);color:var(--lime);font-size:.63rem;font-weight:850;text-align:center}.fe-player-name{overflow:hidden;font-size:.93rem;font-weight:750;white-space:nowrap;text-overflow:ellipsis}.fe-player-meta{margin:.45rem 0 0 2.95rem;color:var(--muted);font-size:.7rem;line-height:1}.fe-player-detail{display:flex;align-items:center;flex-wrap:wrap;gap:.38rem .55rem;margin:.55rem 0 0 2.95rem;color:#b7c0ca;font-size:.64rem;line-height:1}.fe-status{color:#ffc66d;font-weight:800;letter-spacing:.06em;text-transform:uppercase}.fe-performance{color:#d5dce4}.fe-performance span{color:var(--lime)}
.fe-waiver{margin-top:2.8rem;padding-top:1.6rem;border-top:1px solid var(--border)}.fe-waiver-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:1rem}.fe-waiver-head h2{margin:.35rem 0 0;font-size:1.8rem;letter-spacing:-.04em}.fe-waiver-head p{margin:.3rem 0 0;color:var(--muted);font-size:.82rem}.fe-waiver-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.7rem}.fe-waiver-card{padding:1rem 1.1rem;background:var(--surface);border:1px solid var(--border);border-radius:11px}.fe-waiver-main{display:flex;align-items:center;gap:.65rem}.fe-waiver-name{font-weight:800}.fe-waiver-meta{margin:.45rem 0;color:var(--muted);font-size:.7rem}.fe-waiver-stats{color:#ccd4dd;font-size:.7rem}.fe-waiver-stats strong{color:var(--lime)}.fe-reasons{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.65rem}.fe-reason{padding:.2rem .42rem;border:1px solid #34404c;border-radius:999px;color:#aeb8c4;font-size:.58rem;font-weight:750}.fe-waiver-note{margin-top:.7rem;color:var(--muted);font-size:.7rem}
.fe-lineup{margin-top:2.4rem;padding:1.35rem 1.45rem;background:linear-gradient(145deg,#151b23,#10151b);border:1px solid var(--border);border-radius:var(--radius)}.fe-lineup-head{display:flex;align-items:end;justify-content:space-between}.fe-lineup h2{margin:.35rem 0 0;font-size:1.8rem;letter-spacing:-.04em}.fe-health{display:flex;gap:.8rem;flex-wrap:wrap;margin:.9rem 0 0;color:var(--muted);font-size:.68rem;font-weight:750}.fe-health strong{color:var(--text)}.fe-decision{margin-top:.75rem;padding:1rem 1.1rem;background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--lime);border-radius:10px}.fe-decision-label{color:var(--lime);font-size:.62rem;font-weight:900;letter-spacing:.11em}.fe-swap{margin:.5rem 0;color:#dce3ea;font-size:.9rem}.fe-swap strong{color:#fff}.fe-ai-lineup{margin-top:.8rem;padding:.9rem 1rem;background:rgba(182,242,58,.05);border:1px solid var(--border);border-radius:9px;color:#dce3ea;font-size:.82rem;line-height:1.55}
.fe-ai-panel{box-sizing:border-box;max-width:920px;margin:2.5rem auto 0;padding:1.8rem 2rem;overflow:hidden;position:relative;background:linear-gradient(135deg,#171e26,#10151b 72%);border:1px solid #303b47;border-radius:var(--radius)}.fe-ai-panel:after{content:"";position:absolute;width:210px;height:210px;right:-95px;top:-120px;border-radius:50%;background:rgba(182,242,58,.07)}.fe-ai-copy{max-width:470px}.fe-ai-panel h2{margin:.5rem 0 .35rem;font-size:1.55rem;letter-spacing:-.035em}.fe-ai-panel p{margin:0;color:var(--muted);font-size:.86rem;line-height:1.5}.st-key-strategy_button{margin-top:-3.85rem;margin-right:calc((100% - 920px)/2 + 2rem);margin-left:auto;width:285px}.fe-ai-unavailable{box-sizing:border-box;max-width:920px;margin:.8rem auto 0;padding:.75rem .95rem;background:rgba(139,149,165,.06);border:1px solid var(--border);border-radius:9px;color:var(--muted);font-size:.75rem}.fe-ai-unavailable strong{display:block;margin-bottom:.15rem;color:#c6ced7;font-size:.64rem;letter-spacing:.11em}
.fe-results-header{margin:3.6rem 0 1rem}.fe-results-header h2{margin:.4rem 0 0;font-size:2rem;letter-spacing:-.04em}.fe-strategy-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.85rem}.fe-strategy-card{min-height:190px;padding:1.35rem;background:var(--surface);border:1px solid var(--border);border-radius:12px}.fe-strategy-card:first-child{border-top-color:var(--lime)}.fe-strategy-label{color:var(--lime);font-size:.67rem;font-weight:850;letter-spacing:.12em}.fe-strategy-card p{margin:1rem 0 0;color:#dce2e9;font-size:.9rem;line-height:1.65}
[data-testid="stAlert"]{border-radius:10px;font-size:.85rem}[data-testid="stSpinner"]{color:var(--muted)}
@media(max-width:984px){.fe-roster-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.st-key-strategy_button{margin:1rem auto 0;max-width:920px;width:100%}}
@media(max-width:640px){.block-container{padding:0 1rem 3.5rem}.fe-nav{height:64px}.fe-hero{padding:3.3rem 0 1.7rem;text-align:left}.fe-hero h1{font-size:clamp(3rem,16vw,4.2rem)}.fe-hero p{margin-left:0;font-size:.95rem}.fe-connect-copy{padding:1.35rem 1.2rem .55rem}div[data-testid="stForm"]{padding:.45rem 1.2rem 1.25rem}.fe-connected{margin-top:1.1rem;padding:1.15rem}.fe-connected:has(.fe-league-select-label){padding-bottom:4.8rem}.stSelectbox{max-width:none;margin:-4.15rem .75rem .8rem}.fe-context h1{font-size:2rem}.fe-meta{gap:.4rem}.fe-roster-title{margin-top:1.6rem}.fe-section-header{margin-top:1.25rem}.fe-roster-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem}.fe-player-card{min-height:102px;padding:.8rem}.fe-player-name{font-size:.84rem}.fe-player-meta,.fe-player-detail{margin-left:2.7rem}.fe-ai-panel{margin-top:2rem;padding:1.4rem}.fe-strategy-grid{grid-template-columns:1fr}.fe-strategy-card{min-height:auto}}
@media(max-width:390px){.fe-roster-grid{grid-template-columns:1fr}}
</style>
""")


st.html("""<style>
.fe-brief{padding:2.6rem 0 1.2rem}.fe-brief h2,.fe-view-head h2{margin:.45rem 0 .35rem;font-size:clamp(2rem,4vw,3rem);letter-spacing:-.055em}.fe-brief p,.fe-view-head p{margin:0;color:var(--muted);font-size:.9rem}.fe-kpi{padding:1.1rem 1.2rem;background:linear-gradient(145deg,#151c24,#10151b);border:1px solid var(--border);border-radius:12px}.fe-kpi-value{font-size:2rem;font-weight:850;letter-spacing:-.06em;color:var(--lime)}.fe-kpi-label{margin-top:.2rem;color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.1em}.fe-overview-grid{margin-top:1.2rem;border-top:1px solid var(--border)}.fe-brief-row{display:flex;gap:1rem;align-items:center;padding:1.1rem .2rem;border-bottom:1px solid var(--border)}.fe-brief-icon{flex:0 0 82px;color:var(--lime);font-size:.62rem;font-weight:850;letter-spacing:.12em}.fe-brief-row strong{font-size:1rem}.fe-brief-row p{margin:.25rem 0 0;color:var(--muted);font-size:.78rem}.fe-view-head{padding:2.4rem 0 1.2rem}.fe-no-change{display:flex;gap:1rem;align-items:flex-start;margin-top:.7rem;padding:1.5rem;background:linear-gradient(145deg,#162019,#111a15);border:1px solid #304735;border-radius:14px}.fe-no-change-mark{display:grid;place-items:center;width:34px;height:34px;border-radius:50%;background:rgba(182,242,58,.13);color:var(--lime);font-size:1.1rem}.fe-no-change h3{margin:.45rem 0 .35rem;font-size:1.25rem}.fe-no-change p{max-width:650px;margin:0;color:#aeb9b0;font-size:.82rem;line-height:1.55}
.fe-role{padding:.18rem .35rem;border:1px solid rgba(182,242,58,.28);border-radius:999px;color:var(--lime);font-size:.58rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em}
@media(max-width:640px){.fe-brief{padding-top:1.8rem}.fe-kpi{padding:.85rem}.fe-kpi-value{font-size:1.55rem}.fe-brief-icon{flex-basis:64px}.fe-brief-row{gap:.6rem}.fe-brief-row strong{font-size:.88rem}}
</style>""")

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
        {},  # Current-only 51 MB depth chart is not loaded: no trustworthy change history.
    )


@st.cache_data(ttl=86400, show_spinner=False)
def cached_identities(players: dict[str, dict[str, Any]]) -> dict[str, PlayerIdentity]:
    return PlayerIdentityResolver(NflverseClient().get_player_rows()).resolve_all(players)


def scoring_label(league: dict[str, Any]) -> str:
    reception = (league.get("scoring_settings") or {}).get("rec", 0)
    if reception == 1:
        return "PPR"
    if reception == 0.5:
        return "Half PPR"
    if reception == 0:
        return "Standard"
    return f"{reception} PPR"


def render_player_grid(
    title: str,
    roster_players: list[Any],
    weekly_contexts: dict[str, PlayerWeeklyContext],
    opportunities: dict[str, PlayerOpportunity] | None = None,
    profiles: dict[str, Any] | None = None,
    *,
    starters: bool = False,
) -> None:
    count = len(roster_players)
    st.html(
        f'<div class="fe-section-header"><h3>{escape(title)}</h3>'
        f'<div class="fe-count">{count} PLAYER{"" if count == 1 else "S"}</div></div>'
    )
    if not roster_players:
        st.caption("No players in this group.")
        return
    card_class = "fe-player-card starter" if starters else "fe-player-card"
    cards = ""
    for player in roster_players:
        context = weekly_contexts.get(player.player_id)
        matchup = escape(player.team)
        if context and context.opponent:
            marker = "vs" if context.home_away == "home" else "@"
            matchup = f'{escape(player.team)} · {marker} {escape(context.opponent)}'
        elif context and context.is_bye:
            matchup = f'{escape(player.team)} · BYE'
        details: list[str] = []
        if context and context.kickoff:
            kickoff = context.kickoff.strftime("%a %-I:%M %p ET")
            details.append(f'<span>{escape(kickoff)}</span>')
        if context and context.status:
            status = context.status
            if context.injury_body_part:
                status = f"{status} · {context.injury_body_part}"
            details.append(f'<span class="fe-status">{escape(status)}</span>')
        if context and context.season_stats:
            summary = context.season_stats
            details.append(
                f'<span class="fe-performance">AVG <span>{summary.season_average:.1f}</span>'
                f' · LAST {min(3, summary.games_played)} <span>{summary.recent_average:.1f}</span></span>'
            )
        opportunity = (opportunities or {}).get(player.player_id)
        if opportunity:
            usage = opportunity.recent_attempts if player.position == "QB" else opportunity.recent_touches if player.position == "RB" else opportunity.recent_targets
            label = "ATT" if player.position == "QB" else "TOUCH" if player.position == "RB" else "TGT"
            if usage is not None:
                details.append(f'<span class="fe-performance">{label} <span>{usage:.1f}/G</span></span>')
        profile = (profiles or {}).get(player.player_id) if player.position in {"QB", "RB", "WR", "TE"} else None
        if profile:
            details.append(f'<span class="fe-role">{escape(profile.role.title())}</span>')
            if profile.participation and profile.participation.recent_snap_share is not None:
                details.append(f'<span class="fe-performance">SNAPS <span>{profile.participation.recent_snap_share:.0%}</span></span>')
        detail_row = f'<div class="fe-player-detail">{"".join(details)}</div>' if details else ""
        cards += (
            f'<article class="{card_class}"><div class="fe-player-top">'
            f'<span class="fe-position">{escape(player.position)}</span>'
            f'<span class="fe-player-name" title="{escape(player.name)}">{escape(player.name)}</span></div>'
            f'<div class="fe-player-meta">{matchup}</div>{detail_row}</article>'
        )
    st.html(f'<div class="fe-roster-grid">{cards}</div>')


def render_waiver_candidate(candidate: WaiverCandidate) -> str:
    context = candidate.context
    marker = "vs" if context.home_away == "home" else "@"
    matchup = f"{candidate.player.team} · {marker} {context.opponent}" if context.opponent else candidate.player.team
    summary = context.season_stats
    stats = ""
    if summary:
        arrow = {"up": "↑", "down": "↓", "steady": "→"}.get(summary.trend, "")
        stats = (
            f'<div class="fe-waiver-stats">SEASON <strong>{summary.season_average:.1f}</strong> &nbsp; '
            f'LAST {min(3, summary.games_played)} <strong>{summary.recent_average:.1f}</strong> &nbsp; {arrow}</div>'
        )
    reasons = "".join(f'<span class="fe-reason">{escape(reason)}</span>' for reason in candidate.reasons)
    return (
        '<article class="fe-waiver-card"><div class="fe-waiver-main">'
        f'<span class="fe-position">{escape(candidate.player.position)}</span>'
        f'<span class="fe-waiver-name">{escape(candidate.player.name)}</span></div>'
        f'<div class="fe-waiver-meta">{escape(matchup)}</div>{stats}'
        f'<div class="fe-reasons">{reasons}</div></article>'
    )


def render_lineup_check(decisions: list[LineupDecision], health: Any) -> None:
    headline = f'{health.decisions} decision{"" if health.decisions == 1 else "s"} worth reviewing' if health.decisions else "No material lineup changes found"
    st.html(
        '<section class="fe-lineup"><div class="fe-lineup-head"><div><div class="fe-eyebrow">LINEUP CHECK</div>'
        f'<h2>{escape(headline)}</h2></div></div>'
        f'<div class="fe-health"><span><strong>{health.decisions}</strong> DECISIONS</span>'
        f'<span><strong>{health.injury_watches}</strong> INJURY WATCHES</span>'
        f'<span><strong>{health.bye_conflicts}</strong> BYE CONFLICTS</span></div></section>'
    )
    for decision in decisions:
        starter_name = decision.starter.name if decision.starter else "Empty slot"
        reasons = " · ".join(decision.reasons)
        st.html(
            f'<article class="fe-decision"><div class="fe-decision-label">{escape(decision.label)}</div>'
            f'<div class="fe-swap">START <strong>{escape(decision.challenger.name)}</strong> over '
            f'<strong>{escape(starter_name)}</strong> in {escape(decision.slot_id)}</div>'
            f'<div class="fe-waiver-meta">{escape(reasons)}</div></article>'
        )
        with st.expander(f"Why this move · {decision.challenger.name}"):
            st.caption(f"Evidence confidence: {decision.confidence} — not an outcome probability.")
            if decision.evidence:
                st.caption(f"Reason codes: {', '.join(decision.reason_codes)}")
                if "SMALL_SAMPLE_WARNING" in decision.reason_codes:
                    st.warning("Limited sample — only one current-season game may be available, so this recommendation is intentionally conservative.", icon=":material/warning:")
                groups: dict[str, list[Any]] = {}
                for item in decision.evidence: groups.setdefault(item.category, []).append(item)
                order = ("OPPORTUNITY", "PARTICIPATION", "ROLE", "MATCHUP", "AVAILABILITY", "INJURY", "BYE", "CONTEXT", "PRODUCTION", "USAGE_TREND")
                for category in order:
                    if category not in groups: continue
                    st.markdown(f"**{category.replace('_', ' ')}**")
                    for item in groups[category]:
                        st.markdown(f"{item.label}: {item.factual_value} {item.comparison}")
                        st.caption(f"Source: {item.source_type}")
            else:
                st.caption("No additional structured evidence is available.")


def _role_label(candidate: WaiverCandidate) -> str:
    return candidate.intelligence.role.title() if candidate.intelligence else "Role unknown"


def render_overview(league: dict[str, Any], nfl_state: NFLState | None, lineup_health: Any, lineup_decisions: list[LineupDecision], waiver_candidates: list[WaiverCandidate], weekly_contexts: dict[str, PlayerWeeklyContext], roster: Roster, data_available: bool = True) -> None:
    week = f"Week {nfl_state.week}" if nfl_state else "This week"
    st.html(f'<section class="fe-brief"><div class="fe-eyebrow">FANEDGE BRIEFING</div><h2>{escape(week)} · {escape(str(league.get("name") or "Your league"))}</h2><p>Only the decisions and watch items worth your attention right now.</p></section>')
    if not data_available:
        st.info("Some weekly football data is unavailable, so FanEdge is withholding unsupported lineup or waiver conclusions.", icon=":material/info:")
    cols = st.columns(3)
    for col, value, label in zip(cols, (lineup_health.decisions, lineup_health.injury_watches, min(3, len(waiver_candidates))), ("Lineup decisions", "Injury watches", "Waiver targets")):
        with col:
            st.html(f'<div class="fe-kpi"><div class="fe-kpi-value">{value}</div><div class="fe-kpi-label">{label}</div></div>')
    st.html('<div class="fe-overview-grid">')
    lineup_text = "No change is justified by the current evidence." if not lineup_decisions else f"{len(lineup_decisions)} decision worth reviewing"
    lineup_detail = "FanEdge did not find a bench player with enough evidence to justify changing your starters." if not lineup_decisions else " · ".join(f"{d.challenger.name} over {d.starter.name if d.starter else 'an empty slot'}" for d in lineup_decisions[:2])
    waiver_names = " · ".join(c.player.name for c in waiver_candidates[:3]) or "No trustworthy targets surfaced"
    injury_names = [p.name for p in (*roster.starters, *roster.bench) if (weekly_contexts.get(p.player_id) and str(weekly_contexts[p.player_id].status or '').lower() in {'questionable','doubtful','out','ir','pup'})]
    st.html(f'<article class="fe-brief-row"><span class="fe-brief-icon">LINEUP</span><div><strong>{escape(lineup_text)}</strong><p>{escape(lineup_detail)}</p></div></article>')
    st.html(f'<article class="fe-brief-row"><span class="fe-brief-icon">WAIVERS</span><div><strong>{escape(waiver_names)}</strong><p>Available in your league · ranked for roster fit.</p></div></article>')
    st.html(f'<article class="fe-brief-row"><span class="fe-brief-icon">HEALTH</span><div><strong>{escape(" · ".join(injury_names[:3]) if injury_names else "No active starter warnings")}</strong><p>{"Monitor these players before kickoff." if injury_names else "No current status requires action."}</p></div></article>')
    st.html('</div>')


def render_lineup_view(lineup_slots: list[Any], lineup_decisions: list[LineupDecision], lineup_health: Any, roster: Roster, weekly_contexts: dict[str, PlayerWeeklyContext], opportunities: dict[str, PlayerOpportunity], profiles: dict[str, Any], has_openai_key: bool) -> None:
    st.html('<div class="fe-view-head"><div class="fe-eyebrow">LINEUP</div><h2>Set your best lineup</h2><p>Review only the changes supported by enough evidence.</p></div>')
    if not lineup_decisions:
        st.html('<section class="fe-no-change"><div class="fe-no-change-mark">✓</div><div><div class="fe-eyebrow">LINEUP LOOKS GOOD</div><h3>No change is justified this week</h3><p>FanEdge did not find a bench player with enough evidence to justify changing your starters. That is a confidence signal, not a claim of perfection.</p></div></section>')
    else:
        render_lineup_check(lineup_decisions, lineup_health)
        if st.button("Explain these decisions", width="stretch", disabled=not has_openai_key, key="lineup_button"):
            try:
                with st.spinner("Building your evidence summary…"):
                    st.session_state.lineup_advice = generate_lineup_advice(lineup_slots, lineup_decisions, weekly_contexts, opportunities, profiles)
            except Exception:
                st.error("We couldn’t explain the lineup decisions right now. Please try again.", icon=":material/error:")
        if st.session_state.get("lineup_advice"):
            st.html(f'<div class="fe-ai-lineup"><div class="fe-eyebrow">FANEDGE ANALYSIS</div>{escape(st.session_state.lineup_advice)}</div>')


def render_waivers_view(waiver_candidates: list[WaiverCandidate], roster_needs: Any, roster: Roster, drop_candidates: list[Any], has_openai_key: bool) -> None:
    st.html('<div class="fe-view-head"><div class="fe-eyebrow">WAIVERS</div><h2>Best players actually available</h2><p>Priority adds and lower-risk watchlist signals, separated by evidence.</p></div>')
    adds = [c for c in waiver_candidates if c.intelligence and (c.intelligence.role in {"FEATURED", "STARTER", "EMERGING"} or any("Opportunity rising" in r or "Role expanding" in r for r in c.reasons))][:4]
    watchlist = [c for c in waiver_candidates if c not in adds]
    st.markdown("### Top adds")
    if adds:
        st.html(f'<div class="fe-waiver-grid">{"".join(render_waiver_candidate(item) for item in adds)}</div>')
    else:
        st.caption("No candidate has enough evidence to be a confident add.")
    st.markdown("### Watchlist")
    if watchlist:
        st.html(f'<div class="fe-waiver-grid">{"".join(render_waiver_candidate(item) for item in watchlist[:4])}</div>')
    else:
        st.caption("No additional watchlist signals surfaced.")
    if not waiver_candidates:
        st.info("No trustworthy QB, RB, WR, or TE waiver candidates were found in this league.", icon=":material/info:")
    if waiver_candidates and st.button("Explain my waiver options", width="stretch", disabled=not has_openai_key, key="waiver_button"):
        try:
            with st.spinner("Summarizing your waiver options…"):
                st.session_state.waiver_advice = generate_waiver_advice(roster_needs, waiver_candidates, drop_candidates)
        except Exception:
            st.error("We couldn’t explain the waiver shortlist right now. Please try again.", icon=":material/error:")
    if st.session_state.get("waiver_advice"):
        cards = "".join(f'<article class="fe-strategy-card"><div class="fe-strategy-label">{escape(item["title"])}</div><p>{escape(item["body"])}</p></article>' for item in st.session_state.waiver_advice)
        st.html(f'<div class="fe-strategy-grid">{cards}</div>')


def render_roster_view(roster: Roster, weekly_contexts: dict[str, PlayerWeeklyContext], opportunities: dict[str, PlayerOpportunity], profiles: dict[str, Any]) -> None:
    st.html('<div class="fe-view-head"><div class="fe-eyebrow">ROSTER</div><h2>Your team at a glance</h2><p>Reference your starters and bench without burying the weekly decisions.</p></div>')
    render_player_grid("Starters", roster.starters, weekly_contexts, opportunities, profiles, starters=True)
    render_player_grid("Bench", roster.bench, weekly_contexts, opportunities, profiles)


def reset_team() -> None:
    for key in ("user", "leagues", "roster", "raw_roster", "selected_league_id", "strategy", "waiver_advice", "lineup_advice"):
        st.session_state.pop(key, None)


try:
    nfl_state: NFLState | None = cached_nfl_state()
except (SleeperAPIError, FootballDataError):
    nfl_state = None
nav_context = f"NFL · WEEK {nfl_state.week}" if nfl_state and nfl_state.week > 0 else "NFL FANTASY"
st.html(
    f'<nav class="fe-nav"><div class="fe-wordmark">FAN<span>EDGE</span></div>'
    f'<div class="fe-nav-context">{escape(nav_context)}</div></nav>'
)
leagues = st.session_state.get("leagues", [])

if not leagues:
    st.html('<section class="fe-hero"><div class="fe-eyebrow">AI FANTASY STRATEGIST</div><h1>YOUR TEAM.<br>YOUR LEAGUE.<br><span>YOUR EDGE.</span></h1><p>AI-powered fantasy intelligence built around your actual Sleeper roster.</p></section><section class="fe-connect-copy"><div class="fe-eyebrow">CONNECT YOUR TEAM</div><h2>Enter your Sleeper username</h2><p>We’ll find your leagues and import your roster automatically.</p></section>')
    with st.form("connect_form", border=False):
        username = st.text_input("Sleeper username", placeholder="Your Sleeper username", label_visibility="collapsed")
        submitted = st.form_submit_button("CONNECT SLEEPER  →", type="primary", width="stretch")
    st.html('<div class="fe-trust">No password required &nbsp;•&nbsp; Read-only Sleeper data</div>')
    if submitted:
        reset_team()
        if not username.strip():
            st.warning("Enter your Sleeper username to continue.", icon=":material/warning:")
        else:
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
else:
    league_by_id = {str(league["league_id"]): league for league in leagues}
    current_id = st.session_state.get("selected_league_id")
    preview_id = current_id if current_id in league_by_id else next(iter(league_by_id))
    preview_league = league_by_id[preview_id]
    preview_settings = preview_league.get("settings") or {}
    user = st.session_state.user
    username = user.get("display_name") or user.get("username") or "Sleeper manager"
    selector_label = '<div class="fe-league-select-label">SWITCH LEAGUE</div>' if len(leagues) > 1 else ""
    st.html(
        f'<section class="fe-connected"><div class="fe-context"><div class="fe-eyebrow">TEAM OVERVIEW</div>'
        f'<h1>{escape(str(preview_league.get("name") or "Unnamed league"))}</h1>'
        f'<div class="fe-meta"><span>{escape(str(preview_settings.get("num_teams", "—")))} teams</span>'
        f'<span class="dot">•</span><span>{escape(scoring_label(preview_league))}</span>'
        f'<span class="dot">•</span><span>@{escape(str(username))}</span></div></div>'
        f'{selector_label}</section>'
    )
    if len(leagues) > 1:
        selected_id = st.selectbox(
            "Switch league",
            list(league_by_id),
            index=list(league_by_id).index(preview_id),
            format_func=lambda league_id: league_by_id[league_id].get("name") or "Unnamed league",
            label_visibility="collapsed",
            key="league_selector",
        )
    else:
        selected_id = preview_id
    league = league_by_id[selected_id]
    if st.session_state.get("selected_league_id") != selected_id or "roster" not in st.session_state or "raw_roster" not in st.session_state:
        st.session_state.pop("roster", None)
        st.session_state.pop("strategy", None)
        st.session_state.pop("waiver_advice", None)
        st.session_state.pop("lineup_advice", None)
        try:
            with st.spinner("Importing your roster…", show_time=True):
                raw = find_user_roster(cached_rosters(selected_id), str(user["user_id"]))
                st.session_state.roster = build_roster(raw, cached_players())
                st.session_state.raw_roster = raw
                st.session_state.selected_league_id = selected_id
            st.rerun()
        except SleeperAPIError as exc:
            st.error(str(exc), icon=":material/error:")
    roster: Roster | None = st.session_state.get("roster")
    if roster:
        metadata = cached_players()
        league_rosters = cached_rosters(selected_id)
        schedule: WeeklySchedule | dict[str, Any] = WeeklySchedule({}, False, ("schedule unavailable",))
        performances: dict[Any, Any] = {}
        opportunity_index: dict[Any, Any] = {}
        matchup_index: dict[tuple[str, str], DefenseVsPosition] = {}
        historical_index: dict[Any, Any] = {}; participation_index: dict[Any, Any] = {}
        historical_participation: dict[Any, Any] = {}; availability_index: dict[Any, Any] = {}; depth_ranks: dict[str, int] = {}
        if nfl_state:
            with st.status(f"Loading Week {nfl_state.week} intelligence", expanded=False) as load_status:
                try:
                    schedule = cached_weekly_schedule(nfl_state)
                    performances, opportunity_index, matchup_index, historical_index, participation_index, historical_participation, availability_index, depth_ranks = cached_weekly_indexes(nfl_state, league.get("scoring_settings") or {})
                    load_status.update(label="Week intelligence ready", state="complete")
                except FootballDataError:
                    load_status.update(label="Some weekly data is unavailable", state="error")
        try:
            identities = cached_identities(metadata)
        except FootballDataError:
            identities = {}
        weekly_contexts = build_player_weekly_contexts(
            roster,
            metadata,
            schedule,
            performances,
            identities=identities,
        )
        opportunities = build_player_opportunities(
            (*roster.starters, *roster.bench), opportunity_index, identities
        )
        profiles = build_role_profiles((*roster.starters, *roster.bench), opportunities, identities, historical_index, participation_index, availability_index, depth_ranks, historical_participation)
        lineup_slots = build_current_lineup(
            st.session_state.raw_roster, metadata, league.get("roster_positions") or []
        )
        lineup_decisions, lineup_health = optimize_lineup(
            lineup_slots,
            roster,
            weekly_contexts,
            opportunities,
            matchup_index,
            {player_id: bool(identity.gsis_id) for player_id, identity in identities.items()},
            profiles,
        )
        has_openai_key = bool(os.getenv("OPENAI_API_KEY"))
        owned_ids = build_rostered_player_ids(league_rosters)
        available_players = build_available_players(metadata, owned_ids)
        available_contexts = build_player_weekly_contexts(
            Roster(starters=available_players, bench=[]),
            metadata,
            schedule,
            performances,
            identities=identities,
        )
        roster_needs = analyze_roster_needs(roster, weekly_contexts)
        available_opportunities = build_player_opportunities(available_players, opportunity_index, identities)
        available_profiles = build_role_profiles(available_players, available_opportunities, identities, historical_index, participation_index, availability_index, depth_ranks, historical_participation)
        waiver_candidates = rank_waiver_candidates(available_players, available_contexts, roster_needs, opportunities=available_opportunities, profiles=available_profiles)
        drop_candidates = find_drop_candidates(roster, weekly_contexts, roster_needs)
        view = st.segmented_control("Your weekly workspace", ["Overview", "Lineup", "Waivers", "Roster"], default="Overview", key="workspace_view", label_visibility="collapsed")
        if view == "Overview":
            render_overview(league, nfl_state, lineup_health, lineup_decisions, waiver_candidates, weekly_contexts, roster, bool(performances))
        elif view == "Lineup":
            render_lineup_view(lineup_slots, lineup_decisions, lineup_health, roster, weekly_contexts, opportunities, profiles, has_openai_key)
        elif view == "Waivers":
            render_waivers_view(waiver_candidates, roster_needs, roster, drop_candidates, has_openai_key)
        else:
            render_roster_view(roster, weekly_contexts, opportunities, profiles)
        with st.container(border=True):
            st.markdown("**FanEdge analysis**")
            st.caption("FanEdge analyzed your roster and evidence. AI can explain the decisions; it does not source additional sports facts.")
            if st.button("Generate weekly strategy", type="primary", width="stretch", disabled=not has_openai_key, key="strategy_button"):
                try:
                    with st.spinner("Summarizing the decisions that matter…", show_time=True):
                        st.session_state.strategy = generate_strategy(
                            roster,
                            league,
                            nfl_state=nfl_state,
                            weekly_contexts=weekly_contexts,
                        )
                except Exception:
                    st.error("We couldn’t build your strategy right now. Please try again in a moment.", icon=":material/error:")
        if not has_openai_key:
            st.html(
                '<div class="fe-ai-unavailable"><strong>AI STRATEGY UNAVAILABLE</strong>'
                'Strategy generation isn’t configured in this environment.</div>'
            )
        strategy = st.session_state.get("strategy")
        if strategy:
            st.html('<div class="fe-results-header"><div class="fe-eyebrow">YOUR WEEKLY EDGE</div><h2>Three decisions that matter</h2></div>')
            cards = "".join(f'<article class="fe-strategy-card"><div class="fe-strategy-label">{escape(recommendation["title"].replace("/", " / "))}</div><p>{escape(recommendation["body"])}</p></article>' for recommendation in strategy)
            st.html(f'<div class="fe-strategy-grid">{cards}</div>')
