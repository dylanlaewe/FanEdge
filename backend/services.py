"""Shared application services used by FastAPI and the Streamlit reference UI."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace, field
from datetime import datetime, timezone
from time import perf_counter
from typing import TYPE_CHECKING
from uuid import uuid4

from backend.cache import TTLCache
from beta_config import capabilities
from backend.data_health import DataHealth, ProviderCache
from copilot import CopilotEntityResolver, CopilotState, answer_query, classify_query
from football_data import (
    FootballDataError,
    NFLState,
    NflverseClient,
    WeeklySchedule,
    build_performance_index,
    build_player_weekly_contexts,
    build_weekly_schedule,
    normalize_nfl_state,
)
from intelligence import (
    build_availability_changes,
    build_historical_index,
    build_participation_index,
    build_role_profiles,
)
from lineup_optimizer import build_current_lineup, optimize_lineup
from matchup import build_defense_vs_position
from memory import LeagueScope
from news import (
    ESPNNewsClient,
    NewsError,
    NewsEntityResolver,
    extract_facts,
    freshness_bucket,
    reconcile_facts,
)
from news_intelligence import NewsIntelligenceResult, integrate_news_intelligence
from opportunity import build_opportunity_index, build_player_opportunities
from opportunity_engine import build_opportunity_feed
from outcomes import evaluate_pending_lineup_decisions
from player_identity import PlayerIdentityResolver
from sleeper_api import (
    Roster,
    SleeperAPIError,
    SleeperClient,
    build_roster,
    find_user_roster,
)
from storage import SQLiteRepository
from waiver_engine import (
    analyze_roster_needs,
    build_available_players,
    build_rostered_player_ids,
    find_drop_candidates,
    rank_waiver_candidates,
)

if TYPE_CHECKING:
    from backend.schemas import Snapshot


def current_season():
    today = datetime.now()
    return today.year - 1 if today.month <= 2 else today.year


def scoring_label(league):
    rec = (league.get("scoring_settings") or {}).get("rec", 0)
    return {0: "Standard", 0.5: "Half PPR", 1: "PPR"}.get(rec, f"{rec} PPR")


class LeagueNotFound(ValueError):
    pass


@dataclass
class LeagueIntelligenceSnapshot:
    id: str
    built_at: str
    state: CopilotState
    scope: LeagueScope
    nfl_state: NFLState | None
    news_result: NewsIntelligenceResult
    warnings: tuple[str, ...]
    data_fresh: bool
    timings: dict[str, float]
    team_name: str
    product: Snapshot | None = None
    rosters: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class IntelligenceService:
    """One refresh creates one snapshot; page reads never run domain calculations."""

    def __init__(self, repository=None, sleeper=None, nflverse=None, news=None):
        self.repository = repository or SQLiteRepository(
            os.getenv("FANEDGE_DB_PATH", ".fanedge/fanedge.db")
        )
        self.sleeper = sleeper or SleeperClient(timeout=10)
        self.nflverse = nflverse or NflverseClient(timeout=8)
        self.news = news or ESPNNewsClient()
        self.news_enabled = news is not None or capabilities()["news_enabled"]
        self.health = DataHealth()
        self.providers = ProviderCache(self.health)
        self.snapshots = TTLCache(32)
        self.conversations = TTLCache(256)
        self.trade_engines = TTLCache(8)
        self.trade_results = TTLCache(64)
        self.ask_results = TTLCache(128)
        self.dataset_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="fanedge-datasets")
        self.build_count = 0

    def close(self):
        for cache in (
            self.providers,
            self.snapshots,
            self.conversations,
            self.trade_engines,
            self.trade_results,
            self.ask_results,
        ):
            cache.close()
        self.dataset_pool.shutdown(wait=True)

    def connect(self, username, *, refresh=False):
        normalized = username.strip().lower()
        if not normalized or len(normalized) > 100:
            raise LeagueNotFound("Enter a valid Sleeper username.")

        def fetch():
            user = self.sleeper.get_user(normalized)
            leagues = self.sleeper.get_leagues(str(user["user_id"]), current_season())
            return user, leagues

        return self.providers.get(
            ("connection", normalized, current_season()), 900, fetch, force=refresh
        )

    def resolve(self, username, league_id, *, refresh=False):
        user, leagues = self.connect(username, refresh=refresh)
        league = next(
            (item for item in leagues if str(item["league_id"]) == league_id), None
        )
        if league is None:
            raise LeagueNotFound(
                "This league is not connected to the supplied Sleeper user."
            )
        return user, league

    def get_snapshot(self, username, league_id, *, refresh=False):
        user, league = self.resolve(username, league_id, refresh=refresh)
        key = (
            str(user["user_id"]),
            league_id,
            str(league.get("season")),
            json.dumps(league.get("scoring_settings") or {}, sort_keys=True),
            tuple(league.get("roster_positions") or []),
        )
        result = self.snapshots.get(
            key,
            300,
            lambda: self.build(user, league, refresh=refresh),
            background=True,
            force=refresh,
        )
        return result, self.snapshots.status(key)

    def build(self, user, league, *, refresh=False):
        start = perf_counter()
        timings, warnings = {}, []

        def dataset(key, ttl, fetch, **kwargs):
            try:
                return self.providers.get(key, ttl, fetch, **kwargs)
            except FootballDataError:
                warnings.append(
                    f"{key[0] if isinstance(key, tuple) else key} unavailable; other datasets remain usable."
                )
                return []

        @contextmanager
        def timed(name):
            begin = perf_counter()
            yield
            timings[name] = round((perf_counter() - begin) * 1000, 3)

        league_id = str(league["league_id"])
        with timed("sleeper"):
            rosters = self.providers.get(
                ("rosters", league_id),
                300,
                lambda: self.sleeper.get_rosters(league_id),
                force=refresh,
            )
            metadata = self.providers.get(
                "players", 86400, self.sleeper.get_players
            )
            raw = find_user_roster(rosters, str(user["user_id"]))
            roster = build_roster(raw, metadata)
            try:
                nfl_state = self.providers.get(
                    "nfl_state",
                    300,
                    lambda: normalize_nfl_state(self.sleeper.get_nfl_state()),
                    force=refresh,
                )
            except (SleeperAPIError, FootballDataError):
                nfl_state = None
                warnings.append(
                    "NFL week unavailable; schedule and stats are incomplete."
                )
        schedule = WeeklySchedule({}, False, ("schedule unavailable",))
        performances, usage, matchups, historical, snaps, old_snaps, injuries, depth = (
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
        )
        fresh = False
        with timed("football_datasets_and_indexes"):
            if nfl_state:
                try:
                    rows = dataset(
                        "schedule_rows",
                        21600,
                        self.nflverse.get_schedule_rows,
                        force=refresh,
                    )
                    schedule = build_weekly_schedule(rows, nfl_state)

                    season = nfl_state.season
                    # Fetch independent datasets in a bounded shared pool, outside
                    # the indexes cache's single-flight lock (avoid nested-lock deadlock).
                    jobs = [
                        ("stats", season, 21600, self.nflverse.get_stat_rows, refresh),
                        ("stats", season - 1, 86400, self.nflverse.get_stat_rows, False),
                        ("snaps", season, 21600, self.nflverse.get_snap_rows, refresh),
                        ("snaps", season - 1, 86400, self.nflverse.get_snap_rows, False),
                        ("injuries", season, 3600, self.nflverse.get_injury_rows, refresh),
                    ]
                    futures = [self.dataset_pool.submit(copy_context().run, dataset, (kind, year), ttl,
                        lambda fetch=fetch, year=year: fetch(year), force=force)
                        for kind, year, ttl, fetch, force in jobs]
                    current, prior, current_snaps, prior_snaps, reports = [f.result() for f in futures]

                    def indexes():
                        scoring = league.get("scoring_settings") or {}
                        return (
                            build_performance_index(current, nfl_state, scoring),
                            build_opportunity_index(current, nfl_state),
                            build_defense_vs_position(
                                current, nfl_state, scoring, prior
                            ),
                            build_historical_index(prior, season - 1, scoring),
                            build_participation_index(current_snaps, nfl_state),
                            build_participation_index(
                                prior_snaps, NFLState(season - 1, 99, "regular")
                            ),
                            build_availability_changes(reports, nfl_state),
                            {},
                        )

                    index_key = (
                        "indexes",
                        nfl_state,
                        json.dumps(
                            league.get("scoring_settings") or {}, sort_keys=True
                        ),
                    )
                    (
                        performances,
                        usage,
                        matchups,
                        historical,
                        snaps,
                        old_snaps,
                        injuries,
                        depth,
                    ) = self.providers.get(index_key, 300, indexes, force=refresh)
                    datasets = self.health.report(
                        expected_week=max(0, nfl_state.week - 1),
                        season=nfl_state.season,
                    )
                    fresh = (
                        schedule.complete
                        and bool(performances)
                        and not any(
                            d["status"] in {"UNAVAILABLE", "STALE", "DELAYED"}
                            for d in datasets
                            if d["dataset"] in {"stats", "snaps", "injuries"}
                        )
                    )
                except FootballDataError:
                    warnings.append(
                        "Some football datasets are unavailable. Missing evidence stays unknown."
                    )
        with timed("identity"):
            try:

                def identities_factory():
                    rows = self.providers.get(
                        "identity_rows", 86400, self.nflverse.get_player_rows
                    )
                    return PlayerIdentityResolver(rows).resolve_all(metadata)

                identities = self.providers.get(
                    "identities", 3600, identities_factory, force=refresh
                )
            except FootballDataError:
                identities, fresh = {}, False
                warnings.append("Player identity evidence is incomplete.")
        with timed("player_context_roles"):
            owned_ids = build_rostered_player_ids(rosters)
            available = build_available_players(metadata, owned_ids)
            active = build_available_players(metadata, set())
            combined = {
                player.player_id: player
                for player in (*active, *roster.starters, *roster.bench)
            }
            contexts = build_player_weekly_contexts(
                Roster(list(combined.values()), []),
                metadata,
                schedule,
                performances,
                identities=identities,
            )
            opportunities = build_player_opportunities(
                combined.values(), usage, identities
            )
            profiles = build_role_profiles(
                combined.values(),
                opportunities,
                identities,
                historical,
                snaps,
                injuries,
                depth,
                old_snaps,
            )
            needs = analyze_roster_needs(roster, contexts)
        with timed("lineup_optimizer"):
            slots = build_current_lineup(
                raw, metadata, league.get("roster_positions") or []
            )
            decisions, _ = optimize_lineup(
                slots,
                roster,
                contexts,
                opportunities,
                matchups,
                {pid: bool(identity.gsis_id) for pid, identity in identities.items()},
                profiles,
            )
        with timed("waiver_engine"):
            waivers = rank_waiver_candidates(
                available,
                contexts,
                needs,
                opportunities=opportunities,
                profiles=profiles,
            )
            drops = find_drop_candidates(roster, contexts, needs)
        with timed("opportunity_engine"):
            feed = build_opportunity_feed(
                roster,
                contexts,
                opportunities,
                profiles,
                slots,
                decisions,
                waivers,
                opportunities,
                needs,
                matchups,
                week=nfl_state.week if nfl_state else None,
            )
        scope = LeagueScope(
            str(user["user_id"]),
            league_id,
            nfl_state.season
            if nfl_state
            else int(league.get("season") or current_season()),
            nfl_state.week if nfl_state else 0,
        )
        with timed("news"):
            try:

                def facts_factory():
                    if not self.news_enabled:
                        return ()
                    items = self.news.fetch()
                    return tuple(
                        reconcile_facts(
                            extract_facts(
                                NewsEntityResolver(active, identities).resolve_all(
                                    items
                                )
                            )
                        )
                    )

                facts = self.providers.get(
                    "news_facts", 900, facts_factory, force=refresh
                )
            except NewsError:
                fresh = False
                warnings.append(
                    "News refresh unavailable; last verified reports may be stale."
                )
                facts = tuple(
                    replace(
                        fact,
                        freshness=freshness_bucket(fact.published_at),
                        provider_fresh=False,
                    )
                    for fact in self.repository.load_news_facts(scope)
                )
            facts = tuple(
                replace(fact, freshness=freshness_bucket(fact.published_at))
                for fact in facts
            )
            news_result = integrate_news_intelligence(
                feed,
                facts,
                roster,
                contexts,
                available,
                opportunities,
                profiles,
                profiles,
                needs,
                week=scope.week or None,
            )
        with timed("sqlite_memory"):
            if self.news_enabled and not any("News refresh" in warning for warning in warnings):
                self.repository.save_news_facts(scope, news_result.relevant_facts)
            memory_fresh = fresh and (self.news_enabled or not self.repository.load_news_facts(scope))
            if not memory_fresh and fresh:
                warnings.append("News is disabled; historical news-supported signals cannot be confirmed resolved.")
            memory = self.repository.reconcile(
                scope, news_result.feed, data_fresh=memory_fresh
            )
            self.health.observe(
                ("memory", scope.sleeper_user_id, league_id),
                300,
                memory.current,
                # A deliberate optional-provider policy is not a failure of
                # the current core datasets or the memory write itself.
                failed=not fresh,
                warning="Lifecycle resolution is paused while required evidence is incomplete."
                if not memory_fresh
                else None,
            )
            if fresh:
                evaluate_pending_lineup_decisions(
                    self.repository, scope, scope.week, performances
                )
            self.repository.record_analytics(
                scope,
                "league_connected",
                idempotency_key=f"league-connected:{scope.sleeper_user_id}:{scope.league_id}:{scope.season}",
            )
        with timed("copilot_preparation"):
            state = CopilotState(
                roster,
                league,
                contexts,
                opportunities,
                profiles,
                tuple(slots),
                tuple(decisions),
                tuple(waivers),
                tuple(drops),
                needs,
                tuple(news_result.feed),
                memory,
                tuple(news_result.relevant_facts),
                matchups,
                identities,
                tuple(player for player in active if player.player_id in owned_ids),
                tuple(combined.values()),
                scoring_label(league),
                {
                    str(pid): str(team.get("roster_id", index + 1))
                    for index, team in enumerate(rosters)
                    for pid in build_rostered_player_ids([team])
                },
                str(
                    raw.get(
                        "roster_id",
                        next(
                            index + 1
                            for index, team in enumerate(rosters)
                            if team is raw
                        ),
                    )
                ),
                available_ids=frozenset(p.player_id for p in available),
            )
            from quality import enforce_state

            state = enforce_state(state)
            warnings.extend(issue["detail"] for issue in state.quality_issues)
        self.build_count += 1
        timings["total"] = round((perf_counter() - start) * 1000, 3)
        # Sleeper roster metadata may carry a manager-provided team name; never invent a logo.
        team_name = str(
            (raw.get("metadata") or {}).get("team_name")
            or user.get("display_name")
            or user.get("username")
            or "My team"
        )
        return LeagueIntelligenceSnapshot(
            str(uuid4()),
            datetime.now(timezone.utc).isoformat(),
            state,
            scope,
            nfl_state,
            news_result,
            tuple(warnings),
            fresh,
            timings,
            team_name,
            rosters=rosters,
            metadata=metadata,
        )

    def trade_engine(self, snapshot):
        from trades import TradeEngine

        def build():
            names = {}
            try:
                users = self.providers.get(
                    ("league_users", snapshot.scope.league_id),
                    900,
                    lambda: self.sleeper.get_league_users(snapshot.scope.league_id),
                )
                names = {
                    str(user["user_id"]): str(
                        (user.get("metadata") or {}).get("team_name")
                        or user.get("display_name")
                        or user.get("username")
                        or ""
                    )
                    for user in users
                }
            except (SleeperAPIError, AttributeError):
                pass  # Stable roster-ID labels are explicit fallbacks, never invented names.
            market, market_status = (
                {},
                {
                    "status": "DISABLED",
                    "reason": "Optional ADP calibration is disabled; draft sentiment is not in-season market value.",
                },
            )
            if os.getenv("FANEDGE_MARKET_ADP_ENABLED") == "1":
                from calibration import ADPClient, CalibrationError, resolve_adp

                positions = snapshot.state.league.get("roster_positions") or []
                scoring = {0: "standard", 0.5: "half-ppr", 1: "ppr"}.get(
                    (snapshot.state.league.get("scoring_settings") or {}).get("rec", 0)
                )
                custom_receiving = any(
                    key.startswith("bonus_rec") or key in {"rec_te", "rec_rb", "rec_wr"}
                    for key in snapshot.state.league.get("scoring_settings", {})
                )
                if (
                    scoring
                    and not custom_receiving
                    and positions.count("QB") == 1
                    and "SUPER_FLEX" not in positions
                    and "OP" not in positions
                ):
                    key = (
                        "calibration",
                        snapshot.scope.season,
                        scoring,
                        len(snapshot.rosters),
                    )
                    try:
                        payload = self.providers.get(
                            key,
                            86400,
                            lambda: ADPClient().fetch(
                                scoring, len(snapshot.rosters), snapshot.scope.season
                            ),
                        )
                        market, market_status = resolve_adp(
                            payload,
                            snapshot.state.active_players,
                            season=snapshot.scope.season,
                            week=snapshot.scope.week,
                            teams=len(snapshot.rosters),
                            scoring=scoring,
                        )
                    except CalibrationError:
                        market_status = {"status": "UNAVAILABLE"}
                else:
                    market_status = {"status": "UNSUPPORTED_FORMAT"}
            return TradeEngine(
                snapshot.state,
                snapshot.rosters,
                snapshot.metadata,
                snapshot.scope.sleeper_user_id,
                names,
                market=market,
                market_status=market_status,
            )

        return self.trade_engines.get(snapshot.id, 300, build)

    def find_trades(self, snapshot, options):
        engine = self.trade_engine(snapshot)
        result = self.trade_results.get(
            (snapshot.id, options), 300, lambda: engine.search(options)
        )
        self.repository.record_analytics(
            snapshot.scope,
            "TRADE_RESULTS_GENERATED",
            metadata={
                "goal": options.goal,
                "count": len(result["ideas"]),
                "tested": result["tested"],
                "diagnostics": result.get("diagnostics", {}),
            },
        )
        return result

    def data_health(self, snapshot=None):
        rows = self.health.report(
            expected_week=max(0, snapshot.scope.week - 1) if snapshot else None,
            season=snapshot.scope.season if snapshot else None,
        )
        if snapshot:
            keys = {
                ("rosters", snapshot.scope.league_id),
                ("memory", snapshot.scope.sleeper_user_id, snapshot.scope.league_id),
            }
            rows += self.health.report(keys)
        if not self.news_enabled:
            for row in rows:
                if row["dataset"] == "news_facts":
                    row["status"] = "DISABLED"
                    row["warnings"] = ["Optional news disabled by beta provider policy."]
        if not any(row["dataset"] == "calibration" for row in rows):
            rows.append(
                {
                    "provider": "Market calibration",
                    "dataset": "calibration",
                    "status": "NOT_FETCHED"
                    if os.getenv("FANEDGE_MARKET_ADP_ENABLED") == "1"
                    else "DISABLED",
                    "last_success": None,
                    "age_seconds": None,
                    "records": 0,
                    "stale_threshold_seconds": 86400,
                    "warnings": [
                        "No live market price is used. Optional, sample-gated ADP only."
                    ],
                }
            )
        return {
            "providers": rows,
            "quality_issues": list(snapshot.state.quality_issues) if snapshot else [],
            "fetch_freshness_is_not_content_freshness": True,
        }

    def record_feedback(self, scope, event_id, status):
        self.repository.record_feedback(scope, event_id, status)
        self.repository.record_analytics(
            scope, f"recommendation_{status.lower()}", event_key=event_id
        )
        # Both UIs update presentation without a new football/memory observation.
        with self.snapshots.lock:
            for entry in self.snapshots.entries.values():
                snapshot = entry.value
                if snapshot.scope != scope or snapshot.state.memory is None:
                    continue
                snapshot.state = replace(
                    snapshot.state,
                    memory=replace(
                        snapshot.state.memory,
                        current=tuple(
                            replace(item, feedback=status)
                            if item.event_key == event_id
                            else item
                            for item in snapshot.state.memory.current
                        ),
                    ),
                )
                snapshot.product = None

    def ask(
        self, snapshot, question, conversation_id=None, suggested=False,
        trade_preferences=None,
    ):
        # Identical in-flight/double-click requests share work, scoped to snapshot,
        # conversation state and protections. Question text stays in bounded RAM only.
        scope = snapshot.scope
        with self.conversations.lock:
            previous = self.conversations.entries.get(
                (scope.sleeper_user_id, scope.league_id, scope.season, conversation_id)
            ) if conversation_id else None
        key = (snapshot.id, scope.sleeper_user_id, scope.league_id, conversation_id,
               question, json.dumps(trade_preferences or {}, sort_keys=True))
        base_key = key
        # Do not reuse follow-up answers after a different preceding question.
        if previous and previous.value[2] != question:
            key += (previous.value[2],)
        result = self.ask_results.get(key, 30, lambda: self._ask(
            snapshot, question, conversation_id, suggested, trade_preferences
        ))
        # Once the conversation advances to this question, a repeated click no
        # longer has the prior-question suffix. Reuse that exact completed answer.
        if key != base_key:
            self.ask_results.put(base_key, result, 30)
        return result

    def _ask(
        self,
        snapshot,
        question,
        conversation_id=None,
        suggested=False,
        trade_preferences=None,
    ):
        state, scope = snapshot.state, snapshot.scope
        conversation_id = conversation_id or str(uuid4())
        key = (scope.sleeper_user_id, scope.league_id, scope.season, conversation_id)
        previous = self.conversations.get(key, 3600, lambda: (None, None, None))
        resolver = CopilotEntityResolver(
            state.roster,
            (candidate.player for candidate in state.waiver_candidates),
            state.league_players,
            state.active_players,
        )
        intent = classify_query(question, resolver, previous_intent=previous[0])
        if intent.follow_up and previous[1] and previous[1].plan:
            return self.ask(
                snapshot, previous[2], conversation_id, suggested, trade_preferences
            )
        if intent.primary_intent in {"ACTION_PLAN", "WEEKLY_PLAN"}:
            from action_planner import plan_actions
            from backend.trade_copilot import answer_trade
            from trades import TradeOptions

            preferences = trade_preferences or {}
            goal_question = re.split(
                r"\b(?:without giving up|without trading|do not trade|don't trade|protect|keep)\b",
                question,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            planning_intent = classify_query(goal_question, resolver)
            locks = self.trade_engine(snapshot).protections(
                TradeOptions(
                    protected=tuple(preferences.get("protected", ())),
                    trade_block=tuple(preferences.get("trade_block", ())),
                    protect_core=preferences.get("protect_core", True),
                )
            )
            trade_intent = replace(
                planning_intent,
                position=planning_intent.position
                or (
                    planning_intent.player_entities[0].position
                    if planning_intent.player_entities and "replace" in question.lower()
                    else None
                ),
                primary_intent="TRADE_TARGET"
                if any(
                    p.source_tier == "LEAGUE_ROSTERED"
                    for p in planning_intent.player_entities
                )
                else "TRADE_FIND",
            )
            trade_answer = answer_trade(
                self, snapshot, question, trade_intent, preferences
            )
            if trade_answer.trades:
                locks = set(locks) | set(trade_answer.trades.get("protected", ()))
            live_fresh = (
                snapshot.data_fresh
                and (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(snapshot.built_at)
                ).total_seconds()
                < 300
                and not any(
                    row["status"] in {"UNAVAILABLE", "STALE", "DELAYED"}
                    for row in self.data_health(snapshot)["providers"]
                    if row["dataset"] != "calibration"
                )
            )
            answer = plan_actions(
                state,
                question,
                planning_intent,
                trade_answer=trade_answer,
                protected=locks,
                fresh=live_fresh,
            )
        elif intent.primary_intent.startswith("TRADE_"):
            from backend.trade_copilot import answer_trade

            answer = answer_trade(self, snapshot, question, intent, trade_preferences)
        elif intent.follow_up and previous[1] and previous[1].trades:
            from trades import TradeOptions

            preferences = trade_preferences or {}
            locks = self.trade_engine(snapshot).protections(
                TradeOptions(
                    protected=tuple(preferences.get("protected", ())),
                    trade_block=tuple(preferences.get("trade_block", ())),
                    protect_core=preferences.get("protect_core", True),
                )
            )
            ideas = [
                idea
                for idea in previous[1].trades["ideas"]
                if not set(idea["outgoing"]) & locks
            ]
            answer = replace(
                previous[1],
                answer="Here is the same trade evidence for both rosters; no new package has been invented."
                if ideas
                else "No previous trade remains under your current protections. Ask for a new search when ready.",
                trades={
                    **previous[1].trades,
                    "ideas": ideas,
                    "protected": sorted(locks),
                },
                player_ids=tuple(
                    pid
                    for idea in ideas
                    for pid in (*idea["outgoing"], *idea["incoming"])
                ),
                why=previous[1].why if ideas else (),
            )
        else:
            answer, _ = answer_query(
                question, intent, state, previous_answer=previous[1],
                api_key=None if capabilities()["ai_enabled"] else "",
            )
        self.conversations.put(key, (intent, answer, question), 3600)
        self.repository.record_analytics(
            scope,
            "copilot_question_submitted",
            metadata={
                "intent": intent.primary_intent,
                "follow_up": intent.follow_up,
                "hypothetical": intent.hypothetical,
                "supported": not answer.unsupported,
                "ai_fallback": answer.provider_fallback,
            },
        )
        if intent.follow_up:
            self.repository.record_analytics(scope, "copilot_followup_used")
        if suggested:
            self.repository.record_analytics(scope, "copilot_suggested_prompt_clicked")
        return conversation_id, intent, answer
