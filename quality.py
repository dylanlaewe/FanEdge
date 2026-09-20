"""Deterministic recommendation integrity and coherence checks, without network calls."""

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    player_ids: tuple[str, ...]
    detail: str

    def to_dict(self):
        return asdict(self)


def audit_state(state, trade_ideas=()):
    issues = []
    own = {p.player_id for p in (*state.roster.starters, *state.roster.bench)}
    bench = {p.player_id for p in state.roster.bench}
    available = getattr(state, "available_ids", None)
    ownership = state.ownership

    def add(code, ids, detail, severity="ERROR"):
        issues.append(QualityIssue(code, severity, tuple(sorted(set(ids))), detail))

    if available is not None:
        for pid in sorted(set(available) & (set(ownership) | own)):
            add(
                "AVAILABILITY_COLLISION",
                [pid],
                "Owned player was also marked available; affected advice is withheld.",
            )
    for candidate in state.waiver_candidates:
        pid = candidate.player.player_id
        if (
            pid in own
            or pid in ownership
            or available is not None
            and pid not in available
        ):
            add(
                "WAIVER_UNCONFIRMED",
                [pid],
                "Waiver advice lacks confirmed league availability.",
            )
    for event in state.opportunity_feed:
        if event.subject_player and "AVAILABLE_IN_LEAGUE" in event.relevance:
            pid = event.subject_player.player_id
            if (
                pid in ownership
                or pid in own
                or available is not None
                and pid not in available
            ):
                add(
                    "WAIVER_UNCONFIRMED",
                    [pid],
                    "Available-player event conflicts with confirmed league ownership.",
                )
    for pid, context in state.contexts.items():
        if (
            context.is_bye
            and (context.opponent or context.schedule_status == "SCHEDULED")
            or context.schedule_status == "BYE"
            and (not context.is_bye or context.opponent)
        ):
            add("SCHEDULE_CONFLICT", [pid], "Bye and scheduled-game evidence conflict.")
    slots = {s.slot_id: s for s in state.lineup_slots}
    challengers, selected_slots = set(), set()
    for decision in state.lineup_decisions:
        pid, slot = decision.challenger.player_id, slots.get(decision.slot_id)
        context = state.contexts.get(pid)
        if (
            not slot
            or decision.challenger.position not in slot.eligible_positions
            or pid not in bench
            or pid in challengers
            or decision.slot_id in selected_slots
            or context
            and (
                context.is_bye
                or str(context.status or "").lower()
                in {"out", "ir", "pup", "doubtful", "suspended"}
            )
        ):
            add(
                "ILLEGAL_LINEUP",
                [pid],
                "Recommended player cannot occupy the requested slot in this lineup.",
            )
        challengers.add(pid)
        selected_slots.add(decision.slot_id)
    for fact in state.news_facts:
        if (
            not fact.sources
            or not fact.urls
            or not fact.evidence_text
            or not fact.published_at
        ):
            add(
                "NEWS_WITHOUT_PROVENANCE",
                [fact.subject_player_id],
                "News fact has no complete source attribution.",
            )
    for item in state.memory.current if state.memory else ():
        if item.lifecycle == "RESOLVED":
            add(
                "RESOLVED_ACTIONABLE",
                [item.opportunity.subject_player.player_id]
                if item.opportunity.subject_player
                else [],
                "Resolved event cannot be in the active feed without reopening.",
            )
    drops = {d.player.player_id for d in state.drop_candidates}
    for pid in sorted(drops & challengers):
        add(
            "START_DROP_CONFLICT",
            [pid],
            "A proposed starter is also a drop candidate; retain the player while the lineup recommendation is active.",
            "WARNING",
        )
    for pid in sorted(drops & {w.player.player_id for w in state.waiver_candidates}):
        add(
            "ADD_DROP_CONFLICT",
            [pid],
            "The same player cannot be the add and the release.",
        )
    for idea in trade_ideas:
        for pid in idea["outgoing"]:
            if ownership.get(pid) != state.user_roster_id:
                add(
                    "TRADE_OWNERSHIP",
                    [pid],
                    "Outgoing trade asset is not owned by the sending team.",
                )
            if pid in challengers:
                add(
                    "START_TRADE_CONFLICT",
                    [pid],
                    "Starting this player now and exploring a trade are alternatives, not cumulative actions; re-run the lineup after a trade.",
                    "WARNING",
                )
        for pid in idea["incoming"]:
            if ownership.get(pid) != idea["partner_id"]:
                add(
                    "TRADE_OWNERSHIP",
                    [pid],
                    "Incoming trade asset is not owned by the stated counterpart.",
                )
    return tuple(issues)


def enforce_state(state):
    issues = audit_state(state)
    blocked = {
        pid for issue in issues if issue.severity == "ERROR" for pid in issue.player_ids
    }
    protected = {d.challenger.player_id for d in state.lineup_decisions}
    memory = state.memory
    if memory:
        memory = replace(
            memory,
            current=tuple(
                item
                for item in memory.current
                if item.lifecycle != "RESOLVED"
                and (
                    not item.opportunity.subject_player
                    or item.opportunity.subject_player.player_id not in blocked
                )
            ),
            changes=tuple(
                item
                for item in memory.changes
                if item.lifecycle == "RESOLVED"
                or not item.opportunity.subject_player
                or item.opportunity.subject_player.player_id not in blocked
            ),
        )
    return replace(
        state,
        memory=memory,
        lineup_decisions=tuple(
            d for d in state.lineup_decisions if d.challenger.player_id not in blocked
        ),
        waiver_candidates=tuple(
            w for w in state.waiver_candidates if w.player.player_id not in blocked
        ),
        drop_candidates=tuple(
            d
            for d in state.drop_candidates
            if d.player.player_id not in blocked | protected
        ),
        news_facts=tuple(
            f for f in state.news_facts if f.subject_player_id not in blocked
        ),
        opportunity_feed=tuple(
            e
            for e in state.opportunity_feed
            if not e.subject_player or e.subject_player.player_id not in blocked
        ),
        quality_issues=tuple(i.to_dict() for i in issues),
    )


def waiver_is_actionable(candidate, state):
    """One shared definition for Market and Ask; rank/role alone is not a call to add."""
    pid, context, role = (
        candidate.player.player_id,
        candidate.context,
        candidate.intelligence,
    )
    available = getattr(state, "available_ids", None)
    if available is not None and pid not in available or pid in state.ownership:
        return False
    if context.is_bye or str(context.status or "").lower() in {
        "out",
        "ir",
        "pup",
        "doubtful",
        "suspended",
    }:
        return False
    fit = (
        candidate.player.position in state.roster_needs.shallow_depth_positions
        or bool(state.roster_needs.injury_pressure.get(candidate.player.position))
        or bool(state.roster_needs.bye_pressure.get(candidate.player.position))
    )
    evidence = (
        role
        and role.evidence_quality != "LOW"
        and role.role in {"FEATURED", "STARTER", "EMERGING"}
    )
    return bool(fit and evidence)
