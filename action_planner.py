"""Evidence-first, deterministic alternatives. These are proposals, never transactions."""

import re
from dataclasses import asdict, dataclass

from copilot import CopilotAnswer, EvidenceReference
from quality import waiver_is_actionable


@dataclass(frozen=True)
class CandidateAction:
    kind: str
    summary: str
    player_ids: tuple[str, ...]
    cost: str
    improvement: str
    reversibility: str
    confidence: str
    evidence: tuple[str, ...]
    priority: int


def goal_for(question, intent):
    text = question.lower()
    if "replace" in text:
        return "REPLACE_INJURED"
    if "depth" in text or "another" in text:
        return "ADD_DEPTH"
    if intent.position:
        return "IMPROVE_POSITION"
    if intent.player_entities:
        return "TARGET_PLAYER"
    if "depth" in text or re.search(r"\b(another|need an?|need another)\b", text):
        return "ADD_DEPTH" if not intent.position else "IMPROVE_POSITION"
    return "FIX_LINEUP"


def plan_actions(
    state, question, intent, *, trade_answer=None, protected=(), fresh=True
):
    goal = goal_for(question, intent)
    target = intent.player_entities[0] if intent.player_entities else None
    position = intent.position or (target.position if target else None)
    targeted_id = target.player_id if target and goal == "TARGET_PLAYER" else None
    actions, limitations = [], []
    if position:
        needs = state.roster_needs
        limitations.append(
            f"Roster context: {needs.positional_counts.get(position, 0)} {position} players; {needs.injury_pressure.get(position, 0)} injury and {needs.bye_pressure.get(position, 0)} bye concerns. A requested upgrade is not automatically a depth emergency."
        )
    if trade_answer and trade_answer.unsupported:
        return trade_answer
    if not fresh:
        return CopilotAnswer(
            "Refresh your league before making a move: some required evidence is unavailable or stale.",
            action="HOLD",
            confidence="LOW",
            plan={
                "goal": goal,
                "actions": [],
                "considered": ["LINEUP_SWAP", "WAIVER", "TRADE", "MONITOR", "HOLD"],
                "limitations": [
                    "A successful fetch does not guarantee current football content."
                ],
            },
        )
    if intent.ambiguous_players:
        return CopilotAnswer(
            "Which player do you mean? Please use their full name.", confidence="LOW"
        )
    for decision in state.lineup_decisions:
        player = decision.challenger
        if (
            position
            and player.position != position
            or targeted_id
            and player.player_id != targeted_id
        ):
            continue
        # A swap fixes a starting slot, but does not add roster depth.
        if goal == "ADD_DEPTH":
            continue
        actions.append(
            CandidateAction(
                "LINEUP_SWAP",
                f"Consider {player.name} over {decision.starter.name if decision.starter else 'the empty slot'} in {decision.slot_id}.",
                (player.player_id,)
                + ((decision.starter.player_id,) if decision.starter else ()),
                "No assets surrendered; check player locks.",
                "Improves the existing slot's evidence profile; does not add roster depth.",
                "Reversible before players lock.",
                decision.confidence,
                decision.reasons,
                0,
            )
        )
    starters = {p.player_id for p in state.roster.starters}
    retained = (
        starters
        | set(protected)
        | {d.challenger.player_id for d in state.lineup_decisions}
    )
    drops = [d for d in state.drop_candidates if d.player.player_id not in retained]
    for candidate in state.waiver_candidates:
        player = candidate.player
        if (
            position
            and player.position != position
            or targeted_id
            and player.player_id != targeted_id
        ):
            continue
        if (
            not position
            and not targeted_id
            and not waiver_is_actionable(candidate, state)
        ):
            continue
        if waiver_is_actionable(candidate, state) and drops:
            drop = drops[0]
            actions.append(
                CandidateAction(
                    "WAIVER",
                    f"Review adding {player.name}; the supported release is {drop.player.name}.",
                    (player.player_id, drop.player.player_id),
                    f"No trade asset required, but releases {drop.player.name}; FAAB/claim priority may apply.",
                    f"Addresses {player.position} depth or availability pressure with a supported role.",
                    "A dropped player may not be recoverable; confirm roster fit first.",
                    candidate.intelligence.evidence_quality,
                    (
                        *candidate.reasons,
                        drop.rationale,
                        "Confirmed available in this league.",
                    ),
                    1,
                )
            )
        else:
            reason = (
                "No supported, unprotected release exists."
                if waiver_is_actionable(candidate, state)
                else "Role, availability or roster-fit evidence does not justify an immediate add."
            )
            actions.append(
                CandidateAction(
                    "MONITOR",
                    f"Watch {player.name}, rather than force an add.",
                    (player.player_id,),
                    "No transaction.",
                    reason,
                    "No roster commitment.",
                    candidate.intelligence.evidence_quality
                    if candidate.intelligence
                    else "LOW",
                    candidate.reasons,
                    3,
                )
            )
    ideas = (
        trade_answer.trades.get("ideas", [])
        if trade_answer and trade_answer.trades
        else []
    )
    for idea in ideas:
        if set(idea["outgoing"]) & set(protected):
            continue
        if targeted_id and targeted_id not in idea["incoming"]:
            continue
        if position and not any(
            p.player_id in idea["incoming"] and p.position == position
            for p in state.active_players
        ):
            continue
        names = {p.player_id: p.name for p in state.active_players}
        incoming = ", ".join(
            names.get(pid, "the incoming player") for pid in idea["incoming"]
        )
        outgoing = ", ".join(
            names.get(pid, "the outgoing player") for pid in idea["outgoing"]
        )
        actions.append(
            CandidateAction(
                "TRADE",
                f"Explore {incoming} for {outgoing}.",
                (*idea["incoming"], *idea["outgoing"]),
                f"Gives up {outgoing}; requires another manager's agreement.",
                "Two-sided roster simulation clears the trade filters; not an acceptance prediction.",
                "High friction; usually not reversible once completed.",
                idea.get("confidence", "MODERATE"),
                (*idea["why_you"], *idea["why_them"]),
                2,
            )
        )
    if not ideas:
        limitations.append(
            "No trade clears the current evidence and protection filters. Complementary partners are exploration paths, not endorsed packages."
        )
    for event in state.opportunity_feed:
        p = event.subject_player
        if (
            not p
            or position
            and p.position != position
            or targeted_id
            and p.player_id != targeted_id
        ):
            continue
        if event.recommended_action in {"MONITOR", "REVIEW"}:
            actions.append(
                CandidateAction(
                    "MONITOR",
                    f"Monitor {p.name}: {event.explanation_context[0] if event.explanation_context else 'recheck current availability'}",
                    (p.player_id,),
                    "No transaction.",
                    "Wait for corroborated role or availability evidence.",
                    "No roster commitment.",
                    event.confidence,
                    event.explanation_context,
                    3,
                )
            )
    # Stable tie-break: confidence then source order. No invented point forecasts.
    actions.sort(
        key=lambda a: (
            a.priority,
            {"HIGH": 0, "MODERATE": 1, "LOW": 2}.get(a.confidence, 2),
            {"HIGH": 0, "MODERATE": 1, "LOW": 2}.get(
                getattr(
                    state.profiles.get(a.player_ids[0]) if a.player_ids else None,
                    "evidence_quality",
                    "LOW",
                ),
                2,
            ),
        )
    )
    unique = []
    seen = set()
    for action in actions:
        key = (action.kind, action.player_ids[0])
        if key not in seen:
            unique.append(action)
            seen.add(key)
    actions = unique[:4]
    if not actions:
        actions = [
            CandidateAction(
                "HOLD",
                "Hold your roster; no supported move improves this goal right now.",
                (),
                "No assets surrendered.",
                "Avoids a low-evidence transaction.",
                "Revisit after fresh usage or injury evidence.",
                "MODERATE",
                (
                    "Lineup, confirmed waivers, trade paths and relevant events were checked.",
                ),
                4,
            )
        ]
    limitations.extend(issue["detail"] for issue in state.quality_issues)
    limitations.append(
        "These are alternatives, not a combined transaction plan. Re-run lineup and roster checks after any move."
    )
    if state.memory and state.memory.changes:
        limitations.append(
            f"{len(state.memory.changes)} journal changes are available in Recent changes; resolved items are not new actions."
        )
    primary = actions[0]
    why = (
        primary.cost,
        primary.improvement,
        *primary.evidence[:3],
        *(f"Alternative — {a.summary} {a.cost}" for a in actions[1:]),
        *limitations,
    )
    return CopilotAnswer(
        primary.summary,
        why,
        primary.kind,
        "Confirm late status, league availability and player locks before acting.",
        primary.confidence,
        tuple(
            EvidenceReference(
                a.kind.replace("_", " ").title(),
                "; ".join(a.evidence),
                "FanEdge deterministic league evidence",
            )
            for a in actions
        ),
        tuple(dict.fromkeys(pid for a in actions for pid in a.player_ids)),
        trades=trade_answer.trades if primary.kind == "TRADE" else None,
        plan={
            "goal": goal,
            "actions": [asdict(a) for a in actions],
            "considered": ["LINEUP_SWAP", "WAIVER", "TRADE", "MONITOR", "HOLD"],
            "limitations": limitations,
        },
    )
