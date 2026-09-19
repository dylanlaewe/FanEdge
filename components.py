"""Reusable sports-native HTML components for FanEdge."""

from __future__ import annotations

from html import escape
from typing import Any, Iterable

from football_data import PlayerWeeklyContext, ScheduleStatus
from opportunity import PlayerOpportunity
from player_identity import PlayerIdentity
from sleeper_api import Player
from visuals import player_visual, team_mark


INJURY_STATES = {"questionable", "doubtful", "out", "ir", "pup"}


def page_header(eyebrow: str, title: str, description: str) -> str:
    return (
        '<header class="fe-page-head"><div>'
        f'<div class="fe-eyebrow">{escape(eyebrow)}</div><h1>{escape(title)}</h1>'
        f'<p>{escape(description)}</p></div></header>'
    )


def section_title(title: str, count: int | None = None, suffix: str = "players") -> str:
    meta = f"{count} {suffix}" if count is not None else ""
    return f'<div class="fe-section-title"><h2>{escape(title)}</h2><span>{escape(meta)}</span></div>'


def topbar(league_name: str, scoring: str, username: str, week: int | None) -> str:
    week_label = f"WEEK {week}" if week else "NFL"
    return (
        '<div class="fe-app-shell-marker"></div><header class="fe-topbar">'
        f'<div class="fe-topbar-main"><div class="fe-topbar-league">{escape(league_name)}</div>'
        f'<div class="fe-topbar-team">{escape(scoring)} · AI fantasy general manager</div></div>'
        f'<div class="fe-topbar-week"><span class="fe-week-pill">{escape(week_label)}</span>'
        f'<span class="fe-profile">@{escape(username)}</span></div></header>'
    )


def matchup_html(player: Player, context: PlayerWeeklyContext | None, *, rich: bool = True) -> str:
    if not context:
        return '<span class="unknown">Matchup unavailable</span>'
    if context.is_bye:
        return f'{team_mark(player.team)} &nbsp; <strong>BYE</strong>'
    if not context.opponent:
        return f'{team_mark(player.team)} &nbsp; <span class="unknown">Matchup unknown</span>'
    marker = "vs" if context.home_away == "home" else "@"
    if rich:
        return f'{team_mark(player.team)} &nbsp; {marker} &nbsp; {team_mark(context.opponent)}'
    return f'{escape(player.team)} {marker} {escape(context.opponent)}'


def kickoff_text(context: PlayerWeeklyContext | None) -> str:
    return context.kickoff.strftime("%a %-I:%M %p ET") if context and context.kickoff else "Time unavailable"


def status_badge(context: PlayerWeeklyContext | None) -> str:
    if not context:
        return '<span class="fe-status-badge unknown">Unknown</span>'
    if context.is_bye:
        return '<span class="fe-status-badge bye">Bye</span>'
    status = str(context.status or "").strip()
    if status:
        lowered = status.lower()
        css = "out" if lowered in {"out", "ir", "pup", "doubtful"} else ""
        label = status
        if context.injury_body_part:
            label = f"{status} · {context.injury_body_part}"
        return f'<span class="fe-status-badge {css}">{escape(label)}</span>'
    if context.schedule_status == ScheduleStatus.UNKNOWN.value:
        return '<span class="fe-status-badge unknown">Unknown</span>'
    return ""


def role_badge(profile: Any | None) -> str:
    if not profile or str(profile.role).upper() == "UNKNOWN":
        return '<span class="fe-role-badge">Role unknown</span>'
    return f'<span class="fe-role-badge">{escape(str(profile.role).title())}</span>'


def trend_label(opportunity: PlayerOpportunity | None, profile: Any | None) -> str:
    trend = opportunity.usage_trend if opportunity else "INSUFFICIENT DATA"
    role_trend = str(profile.role_trend) if profile else ""
    if trend == "RISING" or role_trend == "ROLE EXPANDING":
        return '<span class="fe-trend up">↑ Rising role</span>'
    if trend == "FALLING" or role_trend == "ROLE SHRINKING":
        return '<span class="fe-trend down">↓ Declining usage</span>'
    if trend == "STEADY" or role_trend == "ROLE STABLE":
        return '<span class="fe-trend stable">Stable role</span>'
    return ""


def _metric(value: float | None, label: str, *, percent: bool = False) -> str:
    if value is None:
        return ""
    formatted = f"{value:.0%}" if percent else f"{value:.1f}"
    return f'<span class="fe-signal"><strong>{formatted}</strong><span>{escape(label)}</span></span>'


def position_signals(
    player: Player,
    context: PlayerWeeklyContext | None,
    opportunity: PlayerOpportunity | None,
    profile: Any | None,
) -> str:
    values: list[str] = []
    if context and context.season_stats:
        values.append(_metric(context.season_stats.season_average, "PPG"))
    snap = profile.participation.recent_snap_share if profile and profile.participation else None
    if player.position == "QB":
        values.append(_metric(opportunity.recent_attempts if opportunity else None, "ATT/G"))
        if opportunity and (opportunity.recent_carries or 0) >= 1:
            values.append(_metric(opportunity.recent_carries, "RUSH/G"))
    elif player.position == "RB":
        values.append(_metric(opportunity.recent_touches if opportunity else None, "TOUCH/G"))
        values.append(_metric(opportunity.recent_targets if opportunity else None, "TGT/G"))
        values.append(_metric(snap, "SNAPS", percent=True))
    elif player.position in {"WR", "TE"}:
        values.append(_metric(opportunity.recent_targets if opportunity else None, "TGT/G"))
        values.append(_metric(opportunity.recent_receptions if opportunity else None, "REC/G"))
        values.append(_metric(snap, "SNAPS", percent=True))
    else:
        values.append(_metric(snap, "SNAPS", percent=True))
    return "".join(value for value in values if value)


def player_row(
    player: Player | None,
    slot: str,
    context: PlayerWeeklyContext | None,
    opportunity: PlayerOpportunity | None,
    profile: Any | None,
    identity: PlayerIdentity | None,
    *,
    recommended: bool = False,
) -> str:
    if not player:
        return f'<div class="fe-empty-row"><strong>{escape(slot)}</strong> &nbsp; Empty lineup slot</div>'
    css = "fe-player-row recommended" if recommended else "fe-player-row"
    trend = trend_label(opportunity, profile)
    role = role_badge(profile)
    status = status_badge(context)
    return (
        f'<article class="{css}" style="--team-color:#52606d">'
        f'<div class="fe-slot">{escape(slot)}</div>'
        f'<div class="fe-player-cell">{player_visual(identity, player.name, player.position, player.team, size="compact")}'
        f'<div class="fe-player-identity"><span class="fe-player-name" title="{escape(player.name)}">{escape(player.name)}</span>'
        f'<div class="fe-player-sub"><span>{escape(player.position)} · {escape(player.team)}</span>{status}</div></div></div>'
        f'<div class="fe-matchup-cell"><strong>{matchup_html(player, context)}</strong><span class="fe-kickoff">{escape(kickoff_text(context))}</span></div>'
        f'<div class="fe-signals">{position_signals(player, context, opportunity, profile)}</div>'
        f'<div class="fe-role-column">{role}{trend}</div></article>'
    )


def swap_comparison(decision: Any, identities: dict[str, PlayerIdentity]) -> str:
    challenger = decision.challenger
    starter = decision.starter
    starter_name = starter.name if starter else "Empty slot"
    starter_visual = player_visual(identities.get(starter.player_id), starter.name, starter.position, starter.team, size="compact") if starter else ""
    return (
        '<section class="fe-swap"><div class="fe-swap-side"><div>'
        f'<div class="fe-swap-label">BENCH OPTION</div><div class="fe-swap-name">{escape(challenger.name)}</div>'
        f'<div class="fe-confidence">{escape(decision.confidence)} CONFIDENCE</div></div>'
        f'{player_visual(identities.get(challenger.player_id), challenger.name, challenger.position, challenger.team, size="compact")}</div>'
        '<div class="fe-swap-arrow">→</div>'
        f'<div class="fe-swap-side right">{starter_visual}<div><div class="fe-swap-label">CURRENT {escape(decision.slot_id)}</div>'
        f'<div class="fe-swap-name">{escape(starter_name)}</div><div class="fe-confidence">{escape(decision.label)}</div></div></div></section>'
    )


def waiver_row(
    candidate: Any,
    rank: int,
    identity: PlayerIdentity | None,
    opportunity: PlayerOpportunity | None,
) -> str:
    player = candidate.player
    context = candidate.context
    profile = candidate.intelligence
    reason = candidate.reasons[0] if candidate.reasons else "Available in your league"
    fit = " · ".join(candidate.reasons[1:]) or "League-aware availability"
    return (
        '<article class="fe-waiver-row">'
        f'<div class="fe-rank">{rank:02d}</div><div class="fe-player-cell">'
        f'{player_visual(identity, player.name, player.position, player.team, size="compact")}'
        f'<div class="fe-player-identity"><span class="fe-player-name">{escape(player.name)}</span>'
        f'<div class="fe-player-sub"><span>{escape(player.position)} · {escape(player.team)}</span>{status_badge(context)}</div></div></div>'
        f'<div class="fe-matchup-cell"><strong>{matchup_html(player, context)}</strong><span class="fe-kickoff">{escape(kickoff_text(context))}</span></div>'
        f'<div class="fe-fit"><strong>{escape(reason)}</strong>{escape(fit)}</div>'
        f'<div class="fe-signals">{position_signals(player, context, opportunity, profile)}</div></article>'
    )


def action_row(index: int, kind: str, title: str, detail: str, state: str) -> str:
    return (
        '<article class="fe-action">'
        f'<span class="fe-action-index">{index}</span><span class="fe-action-kind">{escape(kind)}</span>'
        f'<div class="fe-action-copy"><strong>{escape(title)}</strong><p>{escape(detail)}</p></div>'
        f'<span class="fe-action-state">{escape(state)}</span></article>'
    )


def prompt_tiles(prompts: Iterable[str]) -> str:
    return '<div class="fe-prompt-grid">' + "".join(f'<div class="fe-prompt">{escape(prompt)}</div>' for prompt in prompts) + "</div>"


def opportunity_card(item: Any, identity: PlayerIdentity | None) -> str:
    player = item.subject_player
    category = {
        "INJURY_RISK": "RISK",
        "ROLE_DECLINE": "WATCH",
        "BREAKOUT_WATCH": "WATCH",
        "WAIVER_OPPORTUNITY": "OPPORTUNITY",
        "LINEUP_OPPORTUNITY": "ACTION NEEDED",
        "MATCHUP_EDGE": "OPPORTUNITY",
        "ROSTER_WEAKNESS": "ROSTER",
    }.get(item.opportunity_type, "YOUR EDGE")
    title = player.name if player else item.opportunity_type.replace("_", " ").title()
    subtitle = f"{player.position} · {player.team}" if player else "Team-level opportunity"
    facts = "".join(f'<li>{escape(fact)}</li>' for fact in item.explanation_context[:3])
    media = player_visual(identity, player.name, player.position, player.team, size="large") if player else '<span class="fe-edge-icon">FE</span>'
    return (
        f'<article class="fe-edge-card priority-{escape(item.priority.lower())}">'
        f'<div class="fe-edge-media">{media}</div><div class="fe-edge-main">'
        f'<div class="fe-edge-meta"><span>{escape(category)}</span><b>{escape(item.priority)} PRIORITY</b></div>'
        f'<h3>{escape(title)}</h3><p>{escape(subtitle)}</p><ul>{facts}</ul></div>'
        f'<div class="fe-edge-action"><span>{escape(item.confidence)} CONFIDENCE</span>'
        f'<strong>{escape(item.recommended_action.replace("_", " "))}</strong></div></article>'
    )
