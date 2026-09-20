"""Deterministic trade retrieval for Ask; never lets a model invent a package."""

import re
from dataclasses import replace

from backend import presenter
from copilot import CopilotAnswer, CopilotEntityResolver, EvidenceReference
from trades import TradeOptions


def answer_trade(service, snapshot, question, intent, preferences=None):
    engine = service.trade_engine(snapshot)
    if intent.ambiguous_players:
        return CopilotAnswer(
            "Which player do you mean? Please use their full name.", confidence="LOW"
        )
    if re.search(r"\b(dynasty|draft picks?|future upside)\b", question, re.IGNORECASE):
        return CopilotAnswer(
            "I can assess current-season roster fit, but not dynasty or draft-pick value.",
            unsupported=True,
            confidence="LOW",
        )
    mine = engine.teams.get(engine.user_team_id, {}).get("player_ids", ())
    matched = [p.player_id for p in intent.player_entities]
    protected = list((preferences or {}).get("protected", ()))
    exclusions = re.search(
        r"(?:without (?:giving up|trading)|do not trade|don't trade|protect|keep)\s+(.+)",
        question,
        re.IGNORECASE,
    )
    if exclusions:
        resolver = CopilotEntityResolver(snapshot.state.roster, (), (), ())
        resolved, ambiguous = resolver.resolve(exclusions.group(1))
        if ambiguous or not resolved:
            return CopilotAnswer(
                "Which player should I protect? Use their full roster name.",
                confidence="LOW",
            )
        protected.extend(p.player_id for p in resolved)
    opponents = [
        pid
        for pid in matched
        if engine.owners.get(pid) not in {None, engine.user_team_id}
    ]
    if intent.primary_intent == "TRADE_TARGET" and len(opponents) != 1:
        return CopilotAnswer(
            "Choose one player who belongs to another roster in this league. An unowned player is a waiver target, not a trade target.",
            confidence="LOW",
        )
    team_matches = [
        team["roster_id"]
        for team in engine.teams.values()
        if team["roster_id"] != engine.user_team_id
        and team["team_name"].casefold() in question.casefold()
    ]
    options = TradeOptions(
        goal=intent.position
        or ("DEPTH" if "depth" in question.lower() else "BEST_UPGRADE"),
        protected=tuple(sorted(set(protected))),
        trade_block=tuple((preferences or {}).get("trade_block", ())),
        protect_core=(preferences or {}).get("protect_core", True),
        target_id=opponents[0] if len(opponents) == 1 else None,
        partner_id=team_matches[0] if len(team_matches) == 1 else None,
        limit=6,
    )
    if intent.primary_intent == "TRADE_PARTNER":
        partners = [p for p in engine.partners() if p["score"] > 0]
        if team_matches:
            partners = [p for p in partners if p["roster_id"] in team_matches]
        return CopilotAnswer(
            "These rosters have the strongest complementary fit."
            if partners
            else "No strong complementary roster fit clears the current evidence threshold.",
            tuple(f"{p['team_name']}: {' '.join(p['reasons'])}" for p in partners[:3]),
            action="EXPLORE",
            evidence=(
                EvidenceReference(
                    "Partner fit",
                    "Ranked deterministically from position needs and usable surplus, not manager psychology.",
                    "FanEdge team profiles",
                ),
            ),
        )
    if intent.primary_intent == "TRADE_AWAY":
        shop = [pid for pid in matched if pid in mine and pid not in options.protected]
        if not shop:
            shop = [
                pid
                for pid in mine
                if pid not in engine.protections(options)
                and "SURPLUS"
                in engine.profiles[engine.user_team_id]["positions"]
                .get(engine.players[pid].position, {})
                .get("status", "")
                and engine.values[pid].supported
                and engine.values[pid].available
            ]
        if not shop:
            return CopilotAnswer(
                "I don't see an unprotected, evidence-supported surplus player to shop.",
                confidence="LOW",
            )
        options = replace(options, trade_block=tuple(shop))
    if intent.primary_intent == "TRADE_ANALYZE":
        send_clause = re.search(
            r"\bi send\s+(.+?)(?:\s+(?:for|and i receive|i receive|receive)\s+|$)",
            question,
            re.IGNORECASE,
        )
        if send_clause:
            resolver = CopilotEntityResolver(
                snapshot.state.roster,
                (),
                snapshot.state.league_players,
                snapshot.state.active_players,
            )
            named, ambiguous = resolver.resolve(send_clause.group(1))
            if ambiguous or not named or any(p.player_id not in mine for p in named):
                return CopilotAnswer(
                    "The players you send must belong to your roster. Please clarify the direction, or use Market → Trades to select each side.",
                    confidence="LOW",
                )
        outgoing = [pid for pid in matched if pid in mine]
        if not outgoing or not opponents:
            return CopilotAnswer(
                "Name the players you send and receive, or use the manual analyzer in Market → Trades. I won't invent a package.",
                confidence="LOW",
            )
        result = engine.analyze(outgoing, opponents, options)
        service.repository.record_analytics(
            snapshot.scope, "TRADE_ANALYZED", metadata={"accepted": result["accepted"]}
        )
        data = {
            "ideas": [result["idea"]] if result["idea"] else [],
            "partners": [],
            "tested": 1,
            "elapsed_ms": 0,
            "warnings": result["rejections"] or engine.warnings,
            "protected": sorted(engine.protections(options)),
            "model_version": "trade-evidence-v1",
        }
        summary = (
            "This package is worth discussing based on both rosters."
            if result["accepted"]
            else "I would not recommend this package under the current evidence and protections."
        )
    else:
        try:
            data = service.find_trades(snapshot, options)
        except ValueError as exc:
            return CopilotAnswer(str(exc), confidence="LOW")
        if intent.primary_intent == "TRADE_AWAY":
            data = {
                **data,
                "ideas": [
                    idea for idea in data["ideas"] if set(idea["outgoing"]) & set(shop)
                ],
            }
        summary = (
            f"I found {len(data['ideas'])} roster-backed trade ideas to explore."
            if data["ideas"]
            else "No package clears the two-sided benefit and evidence filters with these protections. I won't manufacture a trade to fill the list."
        )
    data = {
        **data,
        "players": {
            pid: presenter.player(engine.players[pid], snapshot.state).model_dump()
            for pid in engine.owners
        },
    }
    first = data["ideas"][0] if data["ideas"] else None
    why = (
        tuple(first["why_you"] + first["why_them"])
        if first
        else tuple(data["warnings"][:2])
    )
    if intent.primary_intent == "TRADE_AWAY":
        why = (
            tuple(
                f"Consider shopping {engine.players[pid].name}: {engine.profiles[engine.user_team_id]['positions'][engine.players[pid].position]['reason']}"
                for pid in shop[:4]
            )
            + why
        )
    return CopilotAnswer(
        summary,
        why,
        "EXPLORE" if first else "HOLD",
        "Discuss only after rechecking injuries, roster space, and manager preferences.",
        first["confidence"] if first else "LOW",
        (
            EvidenceReference(
                "Trade model",
                "Both rosters are reassigned after the exchange. Value is a package-plausibility heuristic, not a market price or acceptance probability.",
                "FanEdge deterministic trade engine",
            ),
        ),
        tuple(first["outgoing"] + first["incoming"]) if first else (),
        hypothetical=True,
        trades=data,
    )
