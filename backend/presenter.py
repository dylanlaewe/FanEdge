"""Translate existing Python intelligence into typed consumer product models."""

from backend import schemas as api
from copilot import contextual_suggestions
from visuals import resolve_player_image, team_visual


def team(code):
    value = team_visual(code)
    return (
        api.Team(
            abbreviation=value.abbreviation,
            display_name=value.display_name,
            logo_url=value.logo_url,
            color=value.color,
        )
        if value
        else api.Team(abbreviation=code or "FA", display_name=code or "Free agent")
    )


def news(fact):
    return api.NewsEvidence(
        player_id=fact.subject_player_id,
        headline=f"{fact.subject_name} · {fact.new_state.replace('_', ' ').lower()}",
        detail=fact.evidence_text,
        source=", ".join(fact.sources),
        url=fact.urls[0] if fact.urls else None,
        published_at=fact.published_at,
        freshness=fact.freshness,
    )


def player(value, state):
    if value is None:
        return None
    pid = value.player_id
    context, role, usage = (
        state.contexts.get(pid),
        state.profiles.get(pid),
        state.opportunities.get(pid),
    )
    matchup = (
        state.matchup_index.get((context.opponent, value.position))
        if context and context.opponent
        else None
    )
    metrics = [
        api.Metric(
            label="Fantasy / G",
            value=context.season_stats.season_average
            if context and context.season_stats
            else None,
        )
    ]
    if usage:
        workload = (
            usage.recent_attempts
            if value.position == "QB"
            else usage.recent_touches
            if value.position == "RB"
            else usage.recent_targets
        )
        metrics.append(
            api.Metric(
                label="Attempts / G"
                if value.position == "QB"
                else "Touches / G"
                if value.position == "RB"
                else "Targets / G",
                value=workload,
            )
        )
    if role and role.participation:
        snap = role.participation.recent_snap_share
        metrics.append(
            api.Metric(
                label="Snap share",
                value=round(snap * 100) if snap is not None else None,
                unit="%",
            )
        )
    evidence = []
    if role:
        evidence.append(
            api.Evidence(
                label="Role",
                detail=f"{role.role.title()} · {role.current_games} completed games · {role.evidence_quality.lower()} evidence",
                source="FanEdge role model / nflverse",
            )
        )
        if role.historical:
            evidence.append(
                api.Evidence(
                    label="Historical baseline",
                    detail=f"{role.historical.season} · {role.historical.games} games · {role.historical.points_per_game if role.historical.points_per_game is not None else 'Unknown'} points per game",
                    source="nflverse completed games",
                )
            )
    if context:
        evidence.append(
            api.Evidence(
                label="Schedule",
                detail=context.schedule_status,
                source="Validated nflverse schedule",
            )
        )
    status = (
        context.status
        if context and context.status
        else "BYE"
        if context and context.is_bye
        else "NO DESIGNATION"
        if context
        else "UNKNOWN"
    )
    return api.Player(
        id=pid,
        name=value.name,
        position=value.position,
        team=team(value.team),
        image_url=resolve_player_image(state.identities.get(pid)),
        status=status.upper(),
        matchup=api.Matchup(
            opponent=team(context.opponent) if context and context.opponent else None,
            venue=context.home_away if context else None,
            kickoff=context.kickoff.isoformat()
            if context and context.kickoff
            else None,
            schedule_status=context.schedule_status if context else "UNKNOWN",
            difficulty=matchup.label if matchup else None,
            evidence_basis=matchup.evidence_basis if matchup else None,
        ),
        role=role.role if role else "UNKNOWN",
        trend=role.role_trend if role else "INSUFFICIENT DATA",
        confidence=role.evidence_quality if role else "LOW",
        metrics=metrics,
        news=[news(fact) for fact in state.news_facts if fact.subject_player_id == pid],
        evidence=evidence,
    )


def league(value, team_name):
    from backend.services import scoring_label

    return api.League(
        id=str(value["league_id"]),
        name=value.get("name") or "Unnamed league",
        season=int(value.get("season") or 0),
        scoring=scoring_label(value),
        team_name=team_name,
    )


def present(snapshot, repository):
    if snapshot.product is not None:
        return snapshot.product
    state = snapshot.state
    players = {}

    def p(value):
        if value is None:
            return None
        if value.player_id not in players:
            players[value.player_id] = player(value, state)
        return players[value.player_id]

    recommendations = [
        api.Recommendation(
            slot=item.slot_id,
            player=p(item.challenger),
            alternative=p(item.starter),
            action=item.label,
            confidence=item.confidence,
            reasons=list(item.reasons),
            evidence=[
                api.Evidence(
                    label=ev.label,
                    detail=f"{ev.factual_value} {ev.comparison}",
                    source=ev.source_type,
                )
                for ev in item.evidence
            ],
        )
        for item in state.lineup_decisions
    ]
    facts = {fact.fact_id: fact for fact in state.news_facts}
    events = []
    for temporal in state.memory.current if state.memory else []:
        item = temporal.opportunity
        events.append(
            api.OpportunityEvent(
                id=temporal.event_key,
                type=item.opportunity_type,
                priority=item.priority,
                player=p(item.subject_player),
                related_player=p(item.related_player),
                action=item.recommended_action,
                confidence=item.confidence,
                reasons=list(item.explanation_context),
                evidence=[
                    api.Evidence(
                        label=signal.signal_type.replace("_", " ").title(),
                        detail=str(signal.current_value),
                        source=signal.source,
                    )
                    for signal in item.signals
                ],
                news=[
                    news(facts[fid])
                    for fid in snapshot.news_result.facts_for(item.opportunity_id)
                    if fid in facts
                ],
                lifecycle=temporal.lifecycle,
                freshness=temporal.freshness,
                feedback=temporal.feedback,
            )
        )
    add_ids = {
        item.subject_player.player_id
        for item in state.opportunity_feed
        if item.subject_player
        and item.opportunity_type in {"WAIVER_OPPORTUNITY", "BREAKOUT_WATCH"}
    }
    # Preserve the reference UI's top-add qualification, then surface news-supported watches.
    waivers = []
    seen = set()
    for index, item in enumerate(state.waiver_candidates):
        is_add = item.player.player_id in add_ids or bool(
            item.intelligence
            and (
                item.intelligence.role in {"FEATURED", "STARTER", "EMERGING"}
                or any(
                    reason
                    in {"Opportunity rising", "Role expanding", "Snap share rising"}
                    for reason in item.reasons
                )
            )
        )
        waivers.append(
            api.WaiverCandidate(
                player=p(item.player),
                rank=index + 1,
                reasons=list(item.reasons),
                category="WAIVERS" if is_add else "WATCHLIST",
            )
        )
        seen.add(item.player.player_id)
    for item in state.opportunity_feed:
        if (
            item.subject_player
            and item.subject_player.player_id not in seen
            and "AVAILABLE_IN_LEAGUE" in item.relevance
        ):
            waivers.append(
                api.WaiverCandidate(
                    player=p(item.subject_player),
                    rank=len(waivers) + 1,
                    reasons=list(item.explanation_context),
                    category="WATCHLIST",
                )
            )
            seen.add(item.subject_player.player_id)
    history = [
        api.JournalEntry(
            id=item.event_key,
            player_name=item.subject_name,
            type=item.opportunity_type,
            action=item.action,
            lifecycle=item.lifecycle,
            week=item.week,
            last_seen=item.last_seen,
            feedback=item.feedback,
            outcome=item.outcome,
            recommended_points=item.recommended_points,
            alternative_points=item.alternative_points,
            evidence=list(item.evidence),
        )
        for item in repository.journal(snapshot.scope)
    ]
    result = api.Snapshot(
        meta=api.SnapshotMeta(
            id=snapshot.id,
            built_at=snapshot.built_at,
            week=snapshot.scope.week or None,
            data_fresh=snapshot.data_fresh,
            warnings=list(snapshot.warnings),
        ),
        league=league(state.league, snapshot.team_name),
        starters=[
            api.LineupSlot(
                id=slot.slot_id, label=slot.slot_type, player=p(slot.current_player)
            )
            for slot in state.lineup_slots
        ],
        bench=[p(value) for value in state.roster.bench],
        recommendations=recommendations,
        waivers=waivers,
        events=events,
        history=history,
        suggestions=list(contextual_suggestions(state)),
    )
    snapshot.product = result
    return result
