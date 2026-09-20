"""Bounded, deterministic current-season trade discovery. Not market valuation.

No network, persistence, LLM calls, or mutation of league/lineup state lives here.
The assignment objective is evidence quality, not projected fantasy points.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from itertools import combinations
from statistics import median
from time import perf_counter

from lineup_optimizer import comparison_score, normalize_lineup_slots
from sleeper_api import build_roster
from waiver_engine import build_rostered_player_ids
from calibration import TIERS, evidence_tier

POSITIONS = ("QB", "RB", "WR", "TE")
GOALS = (*POSITIONS, "BEST_UPGRADE", "DEPTH")
UNAVAILABLE = {"out", "ir", "pup", "doubtful", "suspended"}
MODEL_VERSION = "trade-evidence-v2"


@dataclass(frozen=True)
class TradeOptions:
    goal: str = "BEST_UPGRADE"
    protected: tuple[str, ...] = ()
    trade_block: tuple[str, ...] = ()
    partner_id: str | None = None
    target_id: str | None = None
    protect_core: bool = True
    limit: int = 12
    exclude_ids: tuple[str, ...] = ()


DEFAULT_OPTIONS = TradeOptions()


@dataclass(frozen=True)
class PlayerValue:
    player_id: str
    quality: float
    relative_value: float
    waiver_replacement: float | None
    typical_starter: float | None
    confidence: str
    supported: bool
    available: bool
    reasons: tuple[str, ...]
    tier: str = "SPECULATIVE"
    market_evidence: dict | None = None


def rejection_codes(reasons):
    mappings = (
        ("protected", "PROTECTED_PLAYER"),
        ("Duplicate", "DUPLICATE_PLAYER"),
        ("belong", "INVALID_OWNERSHIP"),
        ("unavailable", "UNSUPPORTED_ASSET"),
        ("Only 1", "PACKAGE_SHAPE"),
        ("capacity", "INVALID_ROSTER"),
        ("starting requirements", "UNSUPPORTED_FORMAT"),
        ("Relative evidence", "VALUE_GAP"),
        ("two starters", "QUANTITY_FOR_QUALITY"),
        ("stronger evidence", "INSUFFICIENT_EVIDENCE"),
        ("deteriorates", "STARTER_DOWNGRADE"),
        ("Their roster receives no", "NO_PARTNER_INCENTIVE"),
        ("Your roster receives no", "REDUNDANT_INCOMING_POSITION"),
        ("does not", "POSITIONAL_NON_FIT"),
        ("requested player", "TARGET_MISMATCH"),
        ("different partner", "PARTNER_MISMATCH"),
        ("tier gap", "STAR_FOR_DEPTH"),
        ("uncovered", "DEPTH_DAMAGE"),
    )
    return list(
        dict.fromkeys(
            next((code for fragment, code in mappings if fragment in reason), "OTHER")
            for reason in reasons
        )
    )


def assign_lineup(slots, players, scores):
    """Exact maximum-weight rectangular assignment (Hungarian, O(slots²*players)).

    Empty dummy columns permit explicit holes; eligible real players are preferred.
    Reuses the existing league-slot eligibility definitions, not fixed fantasy slots.
    """
    n, m = len(slots), len(players) + len(slots)
    if not n:
        return (), 0.0
    costs = [
        [
            -(10000 + scores.get(p.player_id, 0))
            if p.position in eligible and p.player_id in scores
            else 1e6
            for p in players
        ]
        + [0.0] * n
        for _, eligible in slots
    ]
    u, v, matching, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        matching[0], j0 = i, 0
        minimum, used = [float("inf")] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = matching[j0], float("inf"), 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = costs[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minimum[j]:
                        minimum[j], way[j] = cur, j0
                    if minimum[j] < delta:
                        delta, j1 = minimum[j], j
            for j in range(m + 1):
                if used[j]:
                    u[matching[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if not matching[j0]:
                break
        while j0:
            j1 = way[j0]
            matching[j0] = matching[j1]
            j0 = j1
    assigned = [None] * n
    for j in range(1, m + 1):
        if matching[j] and j <= len(players) and costs[matching[j] - 1][j - 1] < 0:
            assigned[matching[j] - 1] = players[j - 1].player_id
    return tuple(assigned), round(sum(scores.get(pid, 0) for pid in assigned), 3)


class TradeEngine:
    def __init__(
        self,
        state,
        raw_rosters,
        metadata,
        user_id,
        names=None,
        *,
        market=None,
        market_status=None,
    ):
        self.state, self.players = state, {p.player_id: p for p in state.active_players}
        self.market_status = market_status or {"status": "NOT_CONFIGURED"}
        market = market or {}
        self.slots = normalize_lineup_slots(state.league.get("roster_positions") or [])
        self.capacity = sum(
            str(s).upper() not in {"IR", "TAXI"}
            for s in state.league.get("roster_positions") or []
        )
        unsupported_slots = (
            set(state.league.get("roster_positions") or [])
            - {s[0] for s in self.slots}
            - {"BN", "IR", "TAXI"}
        )
        self.warnings = [
            "Current-season roster fit only; relative evidence value is not trade market value or an acceptance probability."
        ]
        if unsupported_slots:
            self.warnings.append(
                "Unsupported starting slots prevent reliable trade simulation."
            )
        self.enabled = (
            bool(self.slots) and not unsupported_slots and len(self.slots) <= 20
        )
        self.teams, self.owners, self.restricted, self.values = {}, {}, set(), {}
        self.user_team_id = ""
        self.owned = build_rostered_player_ids(raw_rosters)
        for index, raw in enumerate(raw_rosters):
            tid = str(raw.get("roster_id", index + 1))
            roster = build_roster(raw, metadata)
            self.players.update(
                (p.player_id, p) for p in (*roster.starters, *roster.bench)
            )
            restricted = {
                str(pid)
                for key in ("reserve", "taxi", "practice_squad")
                for pid in raw.get(key) or []
            }
            self.restricted.update(restricted)
            ids = tuple(
                sorted(
                    {p.player_id for p in (*roster.starters, *roster.bench)}
                    - restricted
                )
            )
            name = str(
                (raw.get("metadata") or {}).get("team_name")
                or (names or {}).get(str(raw.get("owner_id")))
                or f"Roster {tid}"
            )
            self.teams[tid] = {
                "roster_id": tid,
                "owner_id": str(raw.get("owner_id") or ""),
                "team_name": name,
                "player_ids": ids,
            }
            for pid in ids:
                if pid in self.owners:
                    self.restricted.add(pid)  # ambiguous ownership is never tradable
                self.owners[pid] = tid
            if str(raw.get("owner_id")) == str(user_id):
                self.user_team_id = tid
        quality = {}
        for pid, p in self.players.items():
            context, role = state.contexts.get(pid), state.profiles.get(pid)
            summary = context.season_stats if context else None
            history = role.historical if role else None
            supported = p.position in POSITIONS and bool(
                context and (summary or history and history.points_per_game is not None)
            )
            neutral = replace(context, status=None, is_bye=False) if context else None
            score = (
                comparison_score(p, neutral, state.opportunities.get(pid), profile=role)
                if supported
                else 0
            )
            if supported and not summary:
                score += history.points_per_game
            if summary and not history and summary.games_played < 4:
                score *= 0.55 + 0.45 * min(1, summary.games_played / 4)
            quality[pid] = max(0.0, score)
        self.replacement, self.typical = {}, {}
        # Fractional flex demand is used only for a league-wide positional baseline.
        demand = Counter()
        for _, eligible in self.slots:
            for pos in eligible:
                if pos in POSITIONS:
                    demand[pos] += 1 / len(eligible)
        for pos in POSITIONS:
            free = sorted(
                (
                    q
                    for pid, q in quality.items()
                    if self.players[pid].position == pos
                    and pid not in self.owned
                    and q > 0
                    and state.contexts.get(pid)
                    and not state.contexts[pid].is_bye
                    and str(state.contexts[pid].status or "").lower() not in UNAVAILABLE
                ),
                reverse=True,
            )
            owned = sorted(
                (
                    q
                    for pid, q in quality.items()
                    if self.players[pid].position == pos and pid in self.owned and q > 0
                ),
                reverse=True,
            )
            self.replacement[pos] = median(free[:3]) if free else None
            count = max(1, round(demand[pos] * len(self.teams)))
            self.typical[pos] = median(owned[:count]) if owned else None
        for pid, p in self.players.items():
            context, role = state.contexts.get(pid), state.profiles.get(pid)
            games = (
                context.season_stats.games_played
                if context and context.season_stats
                else 0
            )
            supported = p.position in POSITIONS and quality[pid] > 0
            available = bool(
                context
                and not context.is_bye
                and str(context.status or "").lower() not in UNAVAILABLE
            )
            baseline, typical = (
                self.replacement.get(p.position),
                self.typical.get(p.position),
            )
            confidence = (
                "HIGH"
                if games >= 4 and role and role.evidence_quality == "HIGH"
                else "MODERATE"
                if games >= 2 or role and role.historical
                else "LOW"
            )
            value = (
                (
                    6
                    + 0.35 * quality[pid]
                    + max(0, quality[pid] - (baseline or quality[pid]))
                    + 0.3 * max(0, quality[pid] - (typical or quality[pid]))
                )
                if supported
                else 0
            )
            reasons = (
                f"{games} completed current-season games",
                f"{role.role.title()} role" if role else "Role unknown",
                "Waiver baseline unavailable"
                if baseline is None
                else "Compared with the top three unowned positional alternatives",
            )
            self.values[pid] = PlayerValue(
                pid,
                round(quality[pid], 3),
                round(value, 3),
                baseline,
                typical,
                confidence,
                supported,
                available,
                reasons,
                evidence_tier(
                    quality[pid],
                    typical,
                    games=games,
                    historical_games=role.historical.games
                    if role and role.historical
                    else 0,
                    confidence=confidence,
                    market=market.get(pid),
                    league_size=len(self.teams),
                ),
                asdict(market[pid]) if pid in market else None,
            )
        self._profiles = {}
        self.profiles = {
            tid: self.profile(team["player_ids"]) for tid, team in self.teams.items()
        }
        self.default_protected = tuple(
            sorted(
                pid
                for pid in self.teams.get(self.user_team_id, {}).get("player_ids", ())
                if pid in self.profiles.get(self.user_team_id, {}).get("lineup", ())
                and self.values[pid].supported
                and self.values[pid].quality
                >= (self.typical.get(self.players[pid].position) or float("inf")) * 1.15
            )
        )
        core = sorted(
            (
                pid
                for pid in self.profiles.get(self.user_team_id, {}).get("lineup", ())
                if pid
                and self.players[pid].position in {"RB", "WR", "TE"}
                and self.values[pid].supported
            ),
            key=lambda pid: (-self.values[pid].relative_value, pid),
        )[:3]
        self.default_protected = tuple(sorted(set(self.default_protected) | set(core)))

    def profile(self, ids):
        key = tuple(sorted(ids))
        if key in self._profiles:
            return self._profiles[key]
        players = [self.players[pid] for pid in key]
        scores = {
            p.player_id: self.values[p.player_id].quality
            for p in players
            if self.values[p.player_id].available or p.position in {"K", "DEF"}
        }
        lineup, quality = assign_lineup(self.slots, players, scores)
        positions, depth_score = {}, 0.0
        for pos in POSITIONS:
            members = [p.player_id for p in players if p.position == pos]
            starters = [pid for pid in lineup if pid in members]
            required = max(
                sum(eligible == (pos,) for _, eligible in self.slots), len(starters)
            )
            usable = [
                pid
                for pid in members
                if self.values[pid].available and self.values[pid].supported
            ]
            backups = [pid for pid in usable if pid not in starters]
            typical = self.typical[pos]
            replacement = self.replacement[pos]
            useful_backups = [
                pid
                for pid in backups
                if self.values[pid].quality
                >= max((replacement or 0) + 1, (typical or 0) * 0.65)
            ]
            starter_quality = sum(self.values[pid].quality for pid in starters)
            bench_quality = sum(
                sorted(
                    (self.values[pid].quality for pid in useful_backups), reverse=True
                )[:2]
            )
            weak = sum(
                self.values[pid].quality < (typical or 0) * 0.75 for pid in starters
            )
            missing = max(0, required - len(usable))
            injury = sum(
                str(self.state.contexts[pid].status or "").lower()
                in UNAVAILABLE | {"questionable"}
                for pid in members
                if pid in self.state.contexts
            )
            bye = sum(
                self.state.contexts[pid].is_bye
                for pid in members
                if pid in self.state.contexts
            )
            label = (
                "STRONG_NEED"
                if missing
                else "NEED"
                if weak
                else "STRONG_SURPLUS"
                if len(useful_backups) >= 2
                else "SURPLUS"
                if useful_backups
                else "BALANCED"
            )
            if typical is None:
                label = "UNKNOWN"
            positions[pos] = {
                "position": pos,
                "status": label,
                "required": required,
                "depth": len(members),
                "usable_depth": len(usable),
                "starter_quality": round(starter_quality, 2),
                "bench_quality": round(bench_quality, 2),
                "injury_pressure": injury,
                "bye_pressure": bye,
                "role_quality": sum(
                    self.state.profiles[pid].role in {"FEATURED", "STARTER"}
                    for pid in members
                    if pid in self.state.profiles
                ),
                "reason": f"{len(usable)} evidence-supported available options for {required} occupied/required slots; {len(useful_backups)} useful backups; {weak} below-baseline starters.",
            }
            # A third QB in a one-QB league is not a meaningful depth upgrade.
            backup_cap = 1 if pos in {"QB", "TE"} and required <= 1 else 2
            depth_score += min(backup_cap, len(useful_backups)) * 2
        result = {
            "lineup": lineup,
            "lineup_quality": quality,
            "depth_quality": depth_score,
            "positions": positions,
            "valid": bool(self.slots) and all(lineup),
        }
        # Per-search bounded memoization; never accumulate arbitrary packages forever.
        if len(self._profiles) < 4096:
            self._profiles[key] = result
        return result

    def partners(self):
        mine = self.profiles.get(self.user_team_id)
        if not mine:
            return []
        fits = []
        for tid, team in self.teams.items():
            if tid == self.user_team_id:
                continue
            other, reasons, score = self.profiles[tid], [], 0
            relative_edges = {"you": [], "them": []}
            for pos in POSITIONS:
                us, them = mine["positions"][pos], other["positions"][pos]
                if "NEED" in us["status"] and "SURPLUS" in them["status"]:
                    score += 3
                    reasons.append(f"Their {pos} surplus aligns with your {pos} need.")
                if "SURPLUS" in us["status"] and "NEED" in them["status"]:
                    score += 3
                    reasons.append(
                        f"Your {pos} surplus could address their {pos} need."
                    )
                # Deep flex leagues can deploy all good assets. Complementarity can
                # still exist between unequal starting units, not just bench surplus.
                your_average = us["starter_quality"] / max(1, us["required"])
                their_average = them["starter_quality"] / max(1, them["required"])
                margin = max(2.0, (self.typical[pos] or 0) * 0.15)
                if your_average - their_average >= margin:
                    relative_edges["you"].append(pos)
                if their_average - your_average >= margin:
                    relative_edges["them"].append(pos)
            if relative_edges["you"] and relative_edges["them"]:
                score += 4
                reasons.append(
                    f"Your stronger {'/'.join(relative_edges['you'])} unit and their stronger {'/'.join(relative_edges['them'])} unit create a possible two-way fit; package simulation must confirm it."
                )
            fits.append(
                {
                    "roster_id": tid,
                    "team_name": team["team_name"],
                    "score": score,
                    "reasons": reasons
                    or [
                        "No strong complementary position signal; a specific target may still merit analysis."
                    ],
                    "needs": [
                        p
                        for p in POSITIONS
                        if "NEED" in other["positions"][p]["status"]
                    ],
                    "surplus": [
                        p
                        for p in POSITIONS
                        if "SURPLUS" in other["positions"][p]["status"]
                    ],
                }
            )
        return sorted(fits, key=lambda x: (-x["score"], x["roster_id"]))

    def protections(self, options):
        return set(options.protected) | (
            set(self.default_protected) - set(options.trade_block)
            if options.protect_core
            else set()
        )

    def _post(self, tid, outgoing, incoming, protected):
        ids = (set(self.teams[tid]["player_ids"]) - set(outgoing)) | set(incoming)
        drops = []
        excess = len(ids) - self.capacity
        if excess > 0:
            # Never silently assume unlimited roster space. Only conditional low-value bench cuts.
            before = self.profiles[tid]
            options = sorted(
                (
                    pid
                    for pid in ids
                    if pid not in incoming
                    and pid not in protected
                    and pid not in before["lineup"]
                    and self.values[pid].supported
                    and self.values[pid].available
                ),
                key=lambda pid: (self.values[pid].relative_value, pid),
            )
            for pid in options[:excess]:
                if (
                    self.values[pid].relative_value
                    >= min(self.values[p].relative_value for p in incoming) * 0.7
                ):
                    return None, (), ()
                drops.append(pid)
                ids.remove(pid)
            if len(ids) > self.capacity:
                return None, (), ()
        return self.profile(ids), tuple(sorted(ids)), tuple(drops)

    def analyze(self, outgoing, incoming, options=DEFAULT_OPTIONS):
        outgoing, incoming = tuple(outgoing), tuple(incoming)
        reject = []
        if (len(outgoing), len(incoming)) not in {(1, 1), (2, 1), (1, 2)}:
            reject.append("Only 1-for-1, 2-for-1, and 1-for-2 packages are supported.")
        if len({*outgoing, *incoming}) != len(outgoing) + len(incoming):
            reject.append("Duplicate players are not valid trade assets.")
        if any(self.owners.get(pid) != self.user_team_id for pid in outgoing):
            reject.append("Outgoing players must belong to your active roster.")
        owners = {self.owners.get(pid) for pid in incoming}
        partner = next(iter(owners)) if len(owners) == 1 else None
        if not partner or partner == self.user_team_id:
            reject.append("Incoming players must belong to one other league roster.")
        if any(
            pid not in self.values
            or not self.values[pid].supported
            or not self.values[pid].available
            or pid in self.restricted
            for pid in (*outgoing, *incoming)
        ):
            reject.append(
                "A player is unavailable, reserved, ambiguously owned, or lacks supported value evidence."
            )
        if set(outgoing) & self.protections(options):
            reject.append("A protected player is included.")
        if not self.enabled:
            reject.append("League starting requirements cannot be fully simulated.")
        if reject:
            return {
                "accepted": False,
                "rejections": reject,
                "codes": rejection_codes(reject),
                "idea": None,
            }
        before_us, before_them = (
            self.profiles[self.user_team_id],
            self.profiles[partner],
        )
        after_us, _, drops_us = self._post(
            self.user_team_id, outgoing, incoming, self.protections(options)
        )
        after_them, _, drops_them = self._post(partner, incoming, outgoing, set())
        if (
            not after_us
            or not after_them
            or not after_us["valid"]
            or not after_them["valid"]
        ):
            return {
                "accepted": False,
                "rejections": [
                    "The trade cannot produce two valid, capacity-compliant starting lineups."
                ],
                "idea": None,
                "codes": ["INVALID_ROSTER"],
            }
        sent = sum(self.values[p].relative_value for p in outgoing)
        received = sum(self.values[p].relative_value for p in incoming)
        if min(sent, received) / max(sent, received) < 0.72:
            reject.append(
                "Relative evidence value is too uneven for a plausible package."
            )
        for assets, return_assets in ((outgoing, incoming), (incoming, outgoing)):
            best_sent = max(TIERS.index(self.values[p].tier) for p in assets)
            best_received = max(TIERS.index(self.values[p].tier) for p in return_assets)
            if best_sent >= TIERS.index("HIGH_END") and best_sent - best_received >= 2:
                reject.append(
                    "A major evidence tier gap is not compensated by comparable starting quality."
                )

        def impact(before, after, drops):
            delta = after["lineup_quality"] - before["lineup_quality"]
            depth_delta = after["depth_quality"] - before["depth_quality"]
            changes = []
            counts = Counter()
            for i, (slot, _) in enumerate(self.slots):
                counts[slot] += 1
                if before["lineup"][i] != after["lineup"][i]:
                    changes.append(
                        {
                            "slot": f"{slot}{counts[slot]}",
                            "before": before["lineup"][i],
                            "after": after["lineup"][i],
                        }
                    )
            return {
                "lineup_delta": round(delta, 2),
                "depth_delta": depth_delta,
                "label": "STARTER_UPGRADE"
                if delta >= 1
                else "DEPTH_IMPROVEMENT"
                if depth_delta >= 2
                else "LITTLE_CHANGE",
                "changes": changes,
                "before": before["positions"],
                "after": after["positions"],
                "required_drops": list(drops),
            }

        us, them = (
            impact(before_us, after_us, drops_us),
            impact(before_them, after_them, drops_them),
        )
        for impact_value in (us, them):
            if any(
                impact_value["after"][pos]["status"] == "STRONG_NEED"
                and impact_value["before"][pos]["status"] != "STRONG_NEED"
                for pos in POSITIONS
            ):
                reject.append(
                    "The trade leaves a previously covered starting position uncovered."
                )
        for label, value in (("Your", us), ("Their", them)):
            if value["lineup_delta"] < -1:
                reject.append(
                    f"{label} best available starting lineup deteriorates materially."
                )
            if value["lineup_delta"] < 1 and value["depth_delta"] < 2:
                reject.append(
                    f"{label} roster receives no meaningful starter or depth benefit."
                )
        # Consolidating two actual starters needs more than a marginal weekly
        # score gain. Apply symmetrically, even when core protections are disabled.
        for label, sent_ids, before, change in (
            ("Your", outgoing, before_us, us),
            ("Their", incoming, before_them, them),
        ):
            if len(sent_ids) == 2 and all(pid in before["lineup"] for pid in sent_ids):
                hurdle = max(
                    3.0, 0.10 * sum(self.values[pid].quality for pid in sent_ids)
                )
                if change["lineup_delta"] < hurdle:
                    reject.append(
                        f"{label} roster gives up two starters for too little consolidation benefit."
                    )
                if any(
                    self.values[pid].confidence != "HIGH"
                    for pid in (*outgoing, *incoming)
                ):
                    reject.append(
                        f"{label} two-starter consolidation needs stronger evidence than the current sample supports."
                    )
        goal = options.goal
        if goal in POSITIONS:
            gained = (
                after_us["positions"][goal]["starter_quality"]
                - before_us["positions"][goal]["starter_quality"]
            )
            depth_gain = (
                after_us["positions"][goal]["bench_quality"]
                - before_us["positions"][goal]["bench_quality"]
            )
            if (
                gained < 1
                and depth_gain < 2
                or not any(self.players[p].position == goal for p in incoming)
            ):
                reject.append(
                    f"The incoming package does not meaningfully improve {goal}."
                )
        elif goal == "DEPTH" and us["depth_delta"] < 2:
            reject.append("The package does not add useful depth.")
        elif goal == "BEST_UPGRADE" and us["lineup_delta"] < 1:
            reject.append("The package does not improve your best starting lineup.")
        if options.target_id and options.target_id not in incoming:
            reject.append("The requested player is not included.")
        if options.partner_id and partner != options.partner_id:
            reject.append("The package uses a different partner.")
        confidence = (
            "LOW"
            if any(self.values[p].confidence == "LOW" for p in (*outgoing, *incoming))
            else "HIGH"
            if all(self.values[p].confidence == "HIGH" for p in (*outgoing, *incoming))
            else "MODERATE"
        )
        risks = [
            "Evidence utility is not projected points, market price, or an acceptance probability."
        ]
        if confidence == "LOW":
            risks.append("Limited current-season evidence; this idea is tentative.")
        for tid, drops in ((self.user_team_id, drops_us), (partner, drops_them)):
            if drops:
                risks.append(
                    f"{self.teams[tid]['team_name']} must make roster space: consider releasing {', '.join(self.players[p].name for p in drops)}. No transaction is performed."
                )
        for pid in (*outgoing, *incoming):
            context = self.state.contexts.get(pid)
            if context and context.status:
                risks.append(
                    f"{self.players[pid].name}: {context.status}; recheck availability."
                )
        for fact in getattr(self.state, "news_facts", ()):
            if (
                fact.subject_player_id in (*outgoing, *incoming)
                and fact.provider_fresh
                and fact.freshness != "STALE"
            ):
                risks.append(
                    f"Reported context — {fact.subject_name}: {fact.evidence_text} ({', '.join(fact.sources)}). Recheck in the player drawer."
                )
        # M13's start-now and trade-away advice can be alternatives, not both actions.
        if set(outgoing) & {
            d.challenger.player_id for d in getattr(self.state, "lineup_decisions", ())
        }:
            risks.append(
                "Starting this player now and exploring a trade are alternatives, not cumulative actions; re-run the lineup after a trade."
            )
        relative = (
            "USER_FAVORED"
            if received > sent * 1.15
            else "OTHER_TEAM_FAVORED"
            if sent > received * 1.15
            else "HELPS_BOTH"
        )
        idea = {
            "id": sha256(
                (
                    MODEL_VERSION
                    + partner
                    + ",".join(sorted(outgoing))
                    + ":"
                    + ",".join(sorted(incoming))
                ).encode()
            ).hexdigest()[:20],
            "partner_id": partner,
            "partner_name": self.teams[partner]["team_name"],
            "outgoing": list(outgoing),
            "incoming": list(incoming),
            "user_impact": us,
            "partner_impact": them,
            "fit": relative if not reject else "QUESTIONABLE_FIT",
            "confidence": confidence,
            "why_you": self._reasons(us),
            "why_them": [
                "They may have a reason to consider this because "
                + reason[0].lower()
                + reason[1:]
                for reason in self._reasons(them)
            ],
            "give_up": [
                f"{self.players[p].name}: {self.players[p].position} · {self.values[p].reasons[1]}"
                for p in outgoing
            ],
            "risks": risks,
            "value_ratio": round(min(sent, received) / max(sent, received), 3),
            "rank_score": round(
                min(
                    us["lineup_delta"] + us["depth_delta"],
                    them["lineup_delta"] + them["depth_delta"],
                )
                * 2
                + us["lineup_delta"]
                + them["lineup_delta"]
                + 2 * bool(set(outgoing) & set(options.trade_block)),
                3,
            ),
        }
        return {
            "accepted": not reject,
            "rejections": reject,
            "codes": rejection_codes(reject),
            "idea": idea,
        }

    def _reasons(self, impact):
        reasons = []
        for pos in POSITIONS:
            before, after = impact["before"][pos], impact["after"][pos]
            if after["starter_quality"] >= before["starter_quality"] + 1:
                reasons.append(
                    f"{pos} starting options improve against the current league baseline."
                )
            if after["bench_quality"] >= before["bench_quality"] + 2:
                reasons.append(f"{pos} has stronger evidence-supported bench cover.")
        return reasons or ["The simulated slot assignment becomes more useful."]

    def search(self, options=DEFAULT_OPTIONS):
        start, tested, ideas, seen = perf_counter(), 0, [], set()
        considered, rejected, primary, all_reasons = 0, 0, Counter(), Counter()

        def reject_codes(codes):
            nonlocal rejected
            rejected += 1
            primary[codes[0] if codes else "OTHER"] += 1
            all_reasons.update(set(codes or ["OTHER"]))

        if options.goal not in GOALS or not self.user_team_id:
            raise ValueError("Unsupported trade goal or missing user roster.")
        if any(
            self.owners.get(pid) != self.user_team_id
            for pid in (*options.protected, *options.trade_block)
        ):
            raise ValueError("Trade preferences must name players on your roster.")
        if options.target_id and self.owners.get(options.target_id) in {
            None,
            self.user_team_id,
        }:
            raise ValueError("Choose a target from another fantasy roster.")
        if options.partner_id and options.partner_id not in self.teams:
            raise ValueError("Unknown trade partner.")
        protected = self.protections(options)

        def pool(tid):
            return sorted(
                (
                    pid
                    for pid in self.teams[tid]["player_ids"]
                    if self.values[pid].supported
                    and self.values[pid].available
                    and pid not in self.restricted
                    and (tid != self.user_team_id or pid not in protected)
                ),
                key=lambda pid: (
                    pid not in options.trade_block,
                    -self.values[pid].relative_value,
                    pid,
                ),
            )[:10]

        mine = pool(self.user_team_id)
        for partner in self.partners():
            tid = partner["roster_id"]
            if (
                options.partner_id
                and tid != options.partner_id
                or options.target_id
                and self.owners.get(options.target_id) != tid
            ):
                continue
            if not options.target_id and partner["score"] < 3:
                continue
            theirs = pool(tid)
            if (
                options.target_id
                and self.values.get(options.target_id)
                and self.values[options.target_id].available
            ):
                theirs = [
                    options.target_id,
                    *[pid for pid in theirs if pid != options.target_id][:9],
                ]
            packages = [((a,), (b,)) for a in mine for b in theirs]
            packages += [(a, (b,)) for a in combinations(mine[:7], 2) for b in theirs]
            packages += [((a,), b) for a in mine for b in combinations(theirs[:7], 2)]
            for outgoing, incoming in packages:
                considered += 1
                if (
                    options.target_id
                    and options.target_id not in incoming
                    or options.goal in POSITIONS
                    and not any(
                        self.players[p].position == options.goal for p in incoming
                    )
                ):
                    reject_codes(
                        [
                            "TARGET_MISMATCH"
                            if options.target_id and options.target_id not in incoming
                            else "POSITIONAL_NON_FIT"
                        ]
                    )
                    continue
                a, b = (
                    sum(self.values[p].relative_value for p in outgoing),
                    sum(self.values[p].relative_value for p in incoming),
                )
                if not max(a, b) or min(a, b) / max(a, b) < 0.72:
                    reject_codes(["VALUE_GAP"])
                    continue
                tested += 1
                result = self.analyze(outgoing, incoming, options)
                if not result["accepted"]:
                    reject_codes(result["codes"])
                if (
                    result["accepted"]
                    and result["idea"]["id"] not in seen
                    and result["idea"]["id"] not in options.exclude_ids
                ):
                    ideas.append(result["idea"])
                    seen.add(result["idea"]["id"])
        ideas.sort(key=lambda i: (-i["rank_score"], i["id"]))
        # Avoid a result list consisting only of permutations around the same target.
        diversified, counts = [], Counter()
        for idea in ideas:
            key = (idea["partner_id"], tuple(idea["incoming"]))
            if counts[key] < 2:
                diversified.append(idea)
                counts[key] += 1
            if len(diversified) >= options.limit:
                break
        return {
            "ideas": diversified,
            "partners": self.partners(),
            "tested": tested,
            "elapsed_ms": round((perf_counter() - start) * 1000, 2),
            "warnings": self.warnings,
            "protected": sorted(protected),
            "model_version": MODEL_VERSION,
            "diagnostics": {
                "considered": considered,
                "rejected": rejected,
                "surviving": considered - rejected,
                "surfaced": len(diversified),
                "primary_reasons": dict(primary),
                "all_reasons": dict(all_reasons),
                "analyzer_entries": tested,
                "protected_assets": len(protected),
                "model_version": MODEL_VERSION,
                "calibration": self.market_status,
            },
        }

    def overview(self):
        return {
            "teams": [
                {**team, **self.profiles[tid]} for tid, team in self.teams.items()
            ],
            "partners": self.partners(),
            "user_team_id": self.user_team_id,
            "default_protected": self.default_protected,
            "values": {
                pid: asdict(value)
                for pid, value in self.values.items()
                if pid in self.owners
            },
            "warnings": self.warnings,
        }
