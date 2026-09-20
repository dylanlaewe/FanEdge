"""Shared application services used by FastAPI and the Streamlit reference UI."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from time import perf_counter
from typing import TYPE_CHECKING
from uuid import uuid4

from backend.cache import TTLCache
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


class IntelligenceService:
    """One refresh creates one snapshot; page reads never run domain calculations."""

    def __init__(self, repository=None, sleeper=None, nflverse=None, news=None):
        self.repository = repository or SQLiteRepository(
            os.getenv("FANEDGE_DB_PATH", ".fanedge/fanedge.db")
        )
        self.sleeper = sleeper or SleeperClient(timeout=20)
        self.nflverse = nflverse or NflverseClient()
        self.news = news or ESPNNewsClient()
        self.providers = TTLCache(64)
        self.snapshots = TTLCache(32)
        self.conversations = TTLCache(256)
        self.build_count = 0

    def close(self):
        for cache in (self.providers, self.snapshots, self.conversations):
            cache.close()

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
                "players", 3600, self.sleeper.get_players, force=refresh
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
                    rows = self.providers.get(
                        "schedule_rows",
                        21600,
                        self.nflverse.get_schedule_rows,
                        force=refresh,
                    )
                    schedule = build_weekly_schedule(rows, nfl_state)

                    def indexes():
                        season = nfl_state.season
                        current = self.providers.get(
                            ("stats", season),
                            21600,
                            lambda: self.nflverse.get_stat_rows(season),
                            force=refresh,
                        )
                        prior = self.providers.get(
                            ("stats", season - 1),
                            86400,
                            lambda: self.nflverse.get_stat_rows(season - 1),
                        )
                        current_snaps = self.providers.get(
                            ("snaps", season),
                            21600,
                            lambda: self.nflverse.get_snap_rows(season),
                            force=refresh,
                        )
                        prior_snaps = self.providers.get(
                            ("snaps", season - 1),
                            86400,
                            lambda: self.nflverse.get_snap_rows(season - 1),
                        )
                        reports = self.providers.get(
                            ("injuries", season),
                            3600,
                            lambda: self.nflverse.get_injury_rows(season),
                            force=refresh,
                        )
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
                    ) = self.providers.get(index_key, 21600, indexes, force=refresh)
                    fresh = schedule.complete
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
            if not any("News refresh" in warning for warning in warnings):
                self.repository.save_news_facts(scope, news_result.relevant_facts)
            memory = self.repository.reconcile(
                scope, news_result.feed, data_fresh=fresh
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
            )
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
        )

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

    def ask(self, snapshot, question, conversation_id=None, suggested=False):
        state, scope = snapshot.state, snapshot.scope
        conversation_id = conversation_id or str(uuid4())
        key = (scope.sleeper_user_id, scope.league_id, scope.season, conversation_id)
        previous = self.conversations.get(key, 3600, lambda: (None, None))
        resolver = CopilotEntityResolver(
            state.roster,
            (candidate.player for candidate in state.waiver_candidates),
            state.league_players,
            state.active_players,
        )
        intent = classify_query(question, resolver, previous_intent=previous[0])
        answer, _ = answer_query(question, intent, state, previous_answer=previous[1])
        self.conversations.put(key, (intent, answer), 3600)
        self.repository.record_analytics(
            scope,
            "copilot_question_submitted",
            metadata={
                "intent": intent.primary_intent,
                "follow_up": intent.follow_up,
                "hypothetical": intent.hypothetical,
                "supported": not answer.unsupported,
            },
        )
        if intent.follow_up:
            self.repository.record_analytics(scope, "copilot_followup_used")
        if suggested:
            self.repository.record_analytics(scope, "copilot_suggested_prompt_clicked")
        return conversation_id, intent, answer
