"""League-aware impact graph and corroboration for normalized news facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable

from football_data import PlayerWeeklyContext
from intelligence import RoleProfile
from news import Freshness, NewsFact, NewsFactType
from opportunity import PlayerOpportunity
from opportunity_engine import (
    Action, FantasyOpportunity, OpportunityType, PRIORITY_ORDER, Priority, Relevance,
    Signal, SignalType,
)
from sleeper_api import Player, Roster
from waiver_engine import RosterNeeds


@dataclass(frozen=True)
class ImpactNode:
    node_id: str
    node_type: str
    label: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class ImpactEdge:
    source: str
    target: str
    relationship: str


@dataclass(frozen=True)
class NewsIntelligenceResult:
    feed: tuple[FantasyOpportunity, ...]
    relevant_facts: tuple[NewsFact, ...]
    nodes: tuple[ImpactNode, ...]
    edges: tuple[ImpactEdge, ...]
    opportunity_news: tuple[tuple[str, tuple[str, ...]], ...]

    def facts_for(self, opportunity_id: str) -> tuple[str, ...]:
        return next((fact_ids for key, fact_ids in self.opportunity_news if key == opportunity_id), ())


SEVERE_STATES = {"OUT", "IR", "SUSPENDED", "RELEASED", "WAIVED"}
STATUS_FACTS = {NewsFactType.PLAYER_STATUS_CHANGE.value, NewsFactType.PRACTICE_STATUS.value}


def _news_signal(fact: NewsFact, *, week: int | None) -> Signal:
    signal_type = {
        NewsFactType.PRACTICE_STATUS.value: SignalType.NEWS_PRACTICE_REPORT,
        NewsFactType.ROLE_COMMENT.value: SignalType.NEWS_ROLE_REPORT,
        NewsFactType.TRANSACTION.value: SignalType.NEWS_TRANSACTION_REPORT,
    }.get(fact.fact_type, SignalType.NEWS_STATUS_REPORT)
    source = f"{fact.sources[0]} report {fact.source_item_ids[0]}" if fact.sources and fact.source_item_ids else "attributed news report"
    return Signal(signal_type.value, fact.subject_player_id, fact.team, fact.new_state, fact.old_state, None, len(fact.sources), fact.confidence, source, week)


def _reported_fact(fact: NewsFact) -> str:
    source = ", ".join(fact.sources)
    return f"Reported fact ({source}): {fact.subject_name} — {fact.new_state.replace('_', ' ').lower()}"


def _unique_signals(signals: Iterable[Signal]) -> tuple[Signal, ...]:
    result: dict[tuple[Any, ...], Signal] = {}
    for signal in signals:
        key = (signal.signal_type, signal.player_id, str(signal.current_value), signal.source)
        result[key] = signal
    return tuple(result.values())


def _best_teammate(
    fact: NewsFact,
    players: Iterable[Player],
    profiles: dict[str, RoleProfile],
    opportunities: dict[str, PlayerOpportunity],
) -> Player | None:
    candidates: list[tuple[tuple[int, int, float, str], Player]] = []
    role_score = {"FEATURED": 6, "STARTER": 5, "EMERGING": 4, "ROTATIONAL": 3, "LIMITED": 1, "UNKNOWN": 0}
    for player in players:
        if player.player_id == fact.subject_player_id or player.team != fact.team or player.position != fact.subject_position:
            continue
        profile, opportunity = profiles.get(player.player_id), opportunities.get(player.player_id)
        has_role_evidence = bool(profile and profile.current_games > 0 and profile.role != "UNKNOWN") or bool(opportunity and opportunity.games > 0)
        if not has_role_evidence:
            continue
        workload = 0.0
        if opportunity:
            workload = opportunity.recent_attempts or 0 if player.position == "QB" else opportunity.recent_touches or 0 if player.position == "RB" else opportunity.recent_targets or 0
        depth_rank = profile.depth_rank if profile and profile.depth_rank is not None else 99
        candidates.append(((role_score.get(profile.role if profile else "UNKNOWN", 0), -depth_rank, float(workload), player.name.lower()), player))
    return max(candidates, key=lambda value: value[0])[1] if candidates else None


def _role_signal(player: Player, profile: RoleProfile | None, opportunity: PlayerOpportunity | None, week: int | None) -> Signal | None:
    if profile and profile.participation and profile.participation.recent_snap_share is not None:
        return Signal(SignalType.ROLE_EXPANSION.value, player.player_id, player.team, round(profile.participation.recent_snap_share, 2), profile.participation.season_snap_share, None, profile.current_games, profile.evidence_quality, "nflverse snap counts", week)
    if opportunity and opportunity.games:
        value = opportunity.recent_attempts if player.position == "QB" else opportunity.recent_touches if player.position == "RB" else opportunity.recent_targets
        return Signal(SignalType.ROLE_EXPANSION.value, player.player_id, player.team, value, None, None, opportunity.games, "MODERATE", "nflverse player usage", week)
    return None


def integrate_news_intelligence(
    base_feed: Iterable[FantasyOpportunity],
    facts: Iterable[NewsFact],
    roster: Roster,
    contexts: dict[str, PlayerWeeklyContext],
    available_players: Iterable[Player],
    available_opportunities: dict[str, PlayerOpportunity],
    available_profiles: dict[str, RoleProfile],
    roster_profiles: dict[str, RoleProfile],
    roster_needs: RosterNeeds,
    *,
    week: int | None = None,
) -> NewsIntelligenceResult:
    """Connect reported facts to ownership and structured role evidence."""
    feed = {item.opportunity_id: item for item in base_feed}
    roster_players = {player.player_id: player for player in (*roster.starters, *roster.bench)}
    starters = {player.player_id for player in roster.starters}
    available = tuple(available_players)
    relevant: dict[str, NewsFact] = {}
    nodes: dict[str, ImpactNode] = {}
    edges: list[ImpactEdge] = []
    mapping: dict[str, list[str]] = {}

    def connect(opportunity_id: str, fact: NewsFact) -> None:
        relevant[fact.fact_id] = fact
        mapping.setdefault(opportunity_id, []).append(fact.fact_id)

    def add_graph(fact: NewsFact, target: Player | None, action: str | None) -> None:
        news_id, affected_id = f"news:{fact.fact_id}", f"player:{fact.subject_player_id}"
        nodes[news_id] = ImpactNode(news_id, "NEWS_FACT", fact.new_state, {"source": list(fact.sources), "reported_at": fact.published_at})
        nodes[affected_id] = ImpactNode(affected_id, "AFFECTED_PLAYER", fact.subject_name, {"team": fact.team})
        edges.append(ImpactEdge(news_id, affected_id, "REPORTS_STATE_FOR"))
        if target:
            target_id = f"player:{target.player_id}"
            nodes[target_id] = ImpactNode(target_id, "ROLE_RELATED_PLAYER", target.name, {"team": target.team, "position": target.position})
            edges.append(ImpactEdge(affected_id, target_id, "CHANGES_POTENTIAL_OPPORTUNITY_FOR"))
            if action:
                action_id = f"action:{target.player_id}:{action}"
                nodes[action_id] = ImpactNode(action_id, "FANEDGE_ACTION", action, {})
                edges.append(ImpactEdge(target_id, action_id, "SUPPORTS"))

    for fact in facts:
        if fact.freshness == Freshness.STALE.value and fact.provider_fresh:
            continue
        news_signal = _news_signal(fact, week=week)
        owned = roster_players.get(fact.subject_player_id)
        if owned:
            opportunity_id = f"injury:{owned.player_id}" if fact.fact_type in STATUS_FACTS else f"news:{fact.fact_type.lower()}:{owned.player_id}"
            if fact.fact_type in STATUS_FACTS:
                existing = feed.get(opportunity_id)
                starter = owned.player_id in starters
                replacement = existing.related_player if existing else next((player for player in roster.bench if player.position == owned.position), None) if starter else None
                corroborated = any(str(contexts.get(owned.player_id).status or "").upper() == fact.new_state for _ in (0,) if contexts.get(owned.player_id))
                signals = _unique_signals((*existing.signals, news_signal)) if existing else (news_signal,)
                facts_text = tuple(dict.fromkeys((*(existing.explanation_context if existing else ()), _reported_fact(fact))))
                confidence = "HIGH" if corroborated else "MODERATE" if fact.confidence == "HIGH" else "LOW"
                priority = existing.priority if existing else Priority.HIGH.value if starter and fact.new_state in SEVERE_STATES else Priority.MEDIUM.value
                action = existing.recommended_action if existing else Action.REVIEW.value if starter else Action.MONITOR.value
                relevance = existing.relevance if existing else (Relevance.ON_USER_ROSTER.value, Relevance.CURRENT_STARTER.value if starter else Relevance.USER_BENCH.value)
                feed[opportunity_id] = FantasyOpportunity(opportunity_id, OpportunityType.INJURY_RISK.value, priority, owned, replacement, signals, relevance, action, confidence, facts_text, week, week)
                connect(opportunity_id, fact)
                add_graph(fact, replacement, action)
            elif fact.fact_type in {NewsFactType.ROLE_COMMENT.value, NewsFactType.TRANSACTION.value}:
                opportunity_id = f"news:monitor:{owned.player_id}"
                feed[opportunity_id] = FantasyOpportunity(opportunity_id, OpportunityType.BREAKOUT_WATCH.value, Priority.LOW.value, owned, None, (news_signal,), (Relevance.ON_USER_ROSTER.value,), Action.MONITOR.value, fact.confidence, (_reported_fact(fact), "FanEdge inference: monitor for confirmation in structured usage data"), week, week)
                connect(opportunity_id, fact)
                add_graph(fact, owned, Action.MONITOR.value)

        # A severe availability fact can create a waiver opportunity only when
        # an unowned teammate also has independent role/usage evidence.
        if fact.new_state not in SEVERE_STATES:
            continue
        owned_teammate = next((
            player for player in roster_players.values()
            if player.player_id != fact.subject_player_id and player.team == fact.team and player.position == fact.subject_position
        ), None)
        if owned_teammate and not owned:
            role_signal = _role_signal(owned_teammate, roster_profiles.get(owned_teammate.player_id), None, week)
            if role_signal:
                opportunity_id = f"news:monitor:{owned_teammate.player_id}"
                feed[opportunity_id] = FantasyOpportunity(
                    opportunity_id, OpportunityType.BREAKOUT_WATCH.value, Priority.MEDIUM.value,
                    owned_teammate, None, (news_signal, role_signal),
                    (Relevance.ON_USER_ROSTER.value, Relevance.TEAMMATE_OF_USER_PLAYER.value),
                    Action.MONITOR.value, "MODERATE",
                    (_reported_fact(fact), f"FanEdge inference: monitor {owned_teammate.name}'s role after the teammate availability change"), week, week,
                )
                connect(opportunity_id, fact)
                add_graph(fact, owned_teammate, Action.MONITOR.value)
            continue
        candidate = _best_teammate(fact, available, available_profiles, available_opportunities)
        if not candidate:
            continue
        profile, player_opportunity = available_profiles.get(candidate.player_id), available_opportunities.get(candidate.player_id)
        role_signal = _role_signal(candidate, profile, player_opportunity, week)
        if not role_signal:
            continue
        signals = [news_signal, Signal(SignalType.AVAILABLE_IN_LEAGUE.value, candidate.player_id, candidate.team, "AVAILABLE", None, None, 1, "HIGH", "Sleeper league ownership", week), role_signal]
        relevance = [Relevance.AVAILABLE_IN_LEAGUE.value]
        if owned:
            relevance.append(Relevance.TEAMMATE_OF_USER_PLAYER.value)
        explanation = [_reported_fact(fact), f"FanEdge inference: {candidate.name} is an available same-position teammate with existing role evidence", "League fact: available in this league"]
        shallow = candidate.position in roster_needs.shallow_depth_positions
        if shallow:
            signals.append(Signal(SignalType.ROSTER_DEPTH_PRESSURE.value, candidate.player_id, candidate.team, f"SHALLOW_{candidate.position}", None, None, roster_needs.positional_counts.get(candidate.position, 0), "HIGH", "FanEdge roster analysis", week))
            relevance.append(Relevance.SAME_POSITION_AS_ROSTER_WEAKNESS.value)
            explanation.append(f"Roster fact: your {candidate.position} depth is shallow")
        strong_role = bool(profile and profile.evidence_quality == "HIGH")
        priority = Priority.HIGH.value if shallow and strong_role and fact.confidence == "HIGH" else Priority.MEDIUM.value
        action = Action.CONSIDER_ADD.value if shallow or strong_role else Action.MONITOR.value
        opportunity_id = f"waiver:{candidate.player_id}"
        existing = feed.get(opportunity_id)
        if existing:
            signals = list(_unique_signals((*existing.signals, *signals)))
            explanation = list(dict.fromkeys((*existing.explanation_context, *explanation)))
            relevance = list(dict.fromkeys((*existing.relevance, *relevance)))
            priority = min((existing.priority, priority), key=lambda value: PRIORITY_ORDER[Priority(value)])
            action = existing.recommended_action if existing.recommended_action in {Action.ADD.value, Action.CONSIDER_ADD.value} else action
        feed[opportunity_id] = FantasyOpportunity(opportunity_id, OpportunityType.WAIVER_OPPORTUNITY.value, priority, candidate, None, tuple(signals), tuple(dict.fromkeys(relevance)), action, "HIGH" if strong_role and fact.confidence == "HIGH" else "MODERATE", tuple(explanation), week, week)
        connect(opportunity_id, fact)
        add_graph(fact, candidate, action)

    ordered = sorted(feed.values(), key=lambda item: (PRIORITY_ORDER[Priority(item.priority)], item.opportunity_type, item.subject_player.name.lower() if item.subject_player else "", item.opportunity_id))[:7]
    retained = {item.opportunity_id for item in ordered}
    mapping_values = tuple((key, tuple(dict.fromkeys(ids))) for key, ids in mapping.items() if key in retained)
    retained_fact_ids = {fact_id for _, ids in mapping_values for fact_id in ids}
    return NewsIntelligenceResult(tuple(ordered), tuple(value for key, value in relevant.items() if key in retained_fact_ids), tuple(nodes.values()), tuple(edges), mapping_values)


def serialize_impact_graph(result: NewsIntelligenceResult) -> dict[str, Any]:
    return {"nodes": [asdict(node) for node in result.nodes], "edges": [asdict(edge) for edge in result.edges]}
