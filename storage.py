"""Replaceable SQLite persistence for FanEdge snapshots and decision history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from memory import (
    FeedbackStatus, JournalEntry, LeagueScope, Lifecycle, ReconciliationResult,
    TemporalOpportunity, TemporalSummary, classify_lifecycle, evidence_fingerprint,
    evidence_strength, feed_fingerprint, stable_event_key,
)
from news import NewsFact
from opportunity_engine import FantasyOpportunity, Signal
from sleeper_api import Player


SCHEMA_VERSION = 2
RESOLUTION_FRESH_MISSES = 2
SENSITIVE_KEYS = {"secret", "token", "password", "api_key", "provider_payload", "authorization"}


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS league_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_key TEXT NOT NULL UNIQUE,
    sleeper_user_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    data_fresh INTEGER NOT NULL,
    feed_fingerprint TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_scope
ON league_snapshots(sleeper_user_id, league_id, season, captured_at DESC);

CREATE TABLE IF NOT EXISTS event_states (
    event_key TEXT PRIMARY KEY,
    sleeper_user_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    subject_player_id TEXT,
    subject_name TEXT,
    related_player_id TEXT,
    related_name TEXT,
    priority TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    opportunity_json TEXT NOT NULL,
    strength INTEGER NOT NULL,
    lifecycle TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    current INTEGER NOT NULL DEFAULT 1,
    missing_count INTEGER NOT NULL DEFAULT 0,
    freshness TEXT NOT NULL DEFAULT 'FRESH'
);
CREATE INDEX IF NOT EXISTS idx_events_scope
ON event_states(sleeper_user_id, league_id, season, current, last_seen DESC);

CREATE TABLE IF NOT EXISTS event_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES league_snapshots(snapshot_id),
    event_key TEXT NOT NULL REFERENCES event_states(event_key),
    lifecycle TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    priority TEXT NOT NULL,
    action TEXT NOT NULL,
    current INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(snapshot_id, event_key, lifecycle)
);

CREATE TABLE IF NOT EXISTS decision_records (
    decision_key TEXT PRIMARY KEY,
    event_key TEXT NOT NULL REFERENCES event_states(event_key),
    sleeper_user_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    decision_type TEXT NOT NULL,
    subject_json TEXT,
    related_json TEXT,
    recommendation TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    outcome TEXT,
    recommended_points REAL,
    alternative_points REAL,
    evaluated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_scope
ON decision_records(sleeper_user_id, league_id, season, week DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS user_feedback (
    event_key TEXT PRIMARY KEY REFERENCES event_states(event_key),
    sleeper_user_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_events (
    analytics_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE,
    sleeper_user_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    event_key TEXT,
    metadata_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_fact_cache (
    sleeper_user_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    fact_id TEXT NOT NULL,
    fact_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    current INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (sleeper_user_id, league_id, season, fact_id)
);
CREATE INDEX IF NOT EXISTS idx_news_fact_scope
ON news_fact_cache(sleeper_user_id, league_id, season, current, fetched_at DESC);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _observation_bucket(captured_at: str) -> str:
    observed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    return f"{observed.date().isoformat()}:{observed.hour // 6}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _player(value: dict[str, Any] | None) -> Player | None:
    return Player(**value) if value else None


def deserialize_opportunity(raw: str) -> FantasyOpportunity:
    value = json.loads(raw)
    return FantasyOpportunity(
        value["opportunity_id"], value["opportunity_type"], value["priority"],
        _player(value.get("subject_player")), _player(value.get("related_player")),
        tuple(Signal(**signal) for signal in value.get("signals", [])),
        tuple(value.get("relevance", [])), value["recommended_action"], value["confidence"],
        tuple(value.get("explanation_context", [])), value.get("first_seen_week"),
        value.get("last_seen_week"), value.get("resolved"), value.get("action_taken"),
    )


class SQLiteRepository:
    """Small repository boundary; callers do not depend on SQLite queries."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_meta(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )

    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT MAX(version) AS version FROM schema_meta").fetchone()
        return int(row["version"] or 0)

    def snapshot_count(self, scope: LeagueScope) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) FROM league_snapshots WHERE sleeper_user_id=?
                AND league_id=? AND season=?""",
                (scope.sleeper_user_id, scope.league_id, scope.season),
            ).fetchone()
        return int(row[0])

    def save_news_facts(
        self, scope: LeagueScope, facts: Iterable[NewsFact], *, fetched_at: str | None = None,
    ) -> None:
        """Persist normalized facts only; source article bodies are never stored."""
        captured = fetched_at or utc_now()
        values = tuple(facts)
        with self._connect() as connection:
            connection.execute(
                """UPDATE news_fact_cache SET current=0 WHERE sleeper_user_id=?
                AND league_id=? AND season=?""",
                (scope.sleeper_user_id, scope.league_id, scope.season),
            )
            for fact in values:
                connection.execute(
                    """INSERT INTO news_fact_cache
                    (sleeper_user_id, league_id, season, fact_id, fact_json, fetched_at, current)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(sleeper_user_id, league_id, season, fact_id) DO UPDATE SET
                    fact_json=excluded.fact_json, fetched_at=excluded.fetched_at, current=1""",
                    (scope.sleeper_user_id, scope.league_id, scope.season, fact.fact_id, _json(fact.to_dict()), captured),
                )

    def load_news_facts(self, scope: LeagueScope) -> tuple[NewsFact, ...]:
        """Return the last verified current fact set for provider-failure continuity."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT fact_json FROM news_fact_cache WHERE sleeper_user_id=?
                AND league_id=? AND season=? AND current=1 ORDER BY fetched_at DESC, fact_id""",
                (scope.sleeper_user_id, scope.league_id, scope.season),
            ).fetchall()
        return tuple(NewsFact.from_dict(json.loads(row["fact_json"])) for row in rows)

    def reconcile(
        self,
        scope: LeagueScope,
        opportunities: Iterable[FantasyOpportunity],
        *,
        data_fresh: bool,
        captured_at: str | None = None,
        observation_id: str | None = None,
    ) -> ReconciliationResult:
        captured_at = captured_at or utc_now()
        items = tuple(opportunities)
        feed_hash = feed_fingerprint(items)
        snapshot_key = hashlib.sha256(_json({
            "user": scope.sleeper_user_id, "league": scope.league_id,
            "season": scope.season, "week": scope.week, "feed": feed_hash,
            "fresh": data_fresh, "observation": observation_id or _observation_bucket(captured_at),
        }).encode()).hexdigest()
        temporal: list[TemporalOpportunity] = []
        resolved: list[TemporalOpportunity] = []
        with self._connect() as connection:
            previous_count = int(connection.execute(
                "SELECT COUNT(*) FROM league_snapshots WHERE sleeper_user_id=? AND league_id=? AND season=?",
                (scope.sleeper_user_id, scope.league_id, scope.season),
            ).fetchone()[0])
            inserted = connection.execute(
                """INSERT OR IGNORE INTO league_snapshots
                (snapshot_key, sleeper_user_id, league_id, season, week, captured_at, data_fresh, feed_fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot_key, scope.sleeper_user_id, scope.league_id, scope.season, scope.week, captured_at, int(data_fresh), feed_hash),
            )
            is_new_snapshot = inserted.rowcount == 1
            snapshot = connection.execute("SELECT snapshot_id FROM league_snapshots WHERE snapshot_key=?", (snapshot_key,)).fetchone()
            snapshot_id = int(snapshot["snapshot_id"])
            if not data_fresh:
                active_uncertain = connection.execute(
                    """SELECT e.*, f.status AS feedback FROM event_states e
                    LEFT JOIN user_feedback f ON f.event_key=e.event_key
                    WHERE e.sleeper_user_id=? AND e.league_id=? AND e.season=? AND e.current=1""",
                    (scope.sleeper_user_id, scope.league_id, scope.season),
                ).fetchall()
                for old in active_uncertain:
                    connection.execute("UPDATE event_states SET freshness='UNCERTAIN' WHERE event_key=?", (old["event_key"],))
                    temporal.append(TemporalOpportunity(
                        deserialize_opportunity(str(old["opportunity_json"])),
                        str(old["event_key"]), Lifecycle.ACTIVE.value,
                        str(old["first_seen"]), str(old["last_seen"]), "UNCERTAIN",
                        str(old["feedback"]) if old["feedback"] else None,
                    ))
                return ReconciliationResult(
                    snapshot_id, previous_count > 0, tuple(temporal), (), TemporalSummary(),
                )
            seen: set[str] = set()
            for item in items:
                event_key = stable_event_key(scope, item)
                seen.add(event_key)
                fingerprint = evidence_fingerprint(item)
                strength = evidence_strength(item)
                old = connection.execute("SELECT * FROM event_states WHERE event_key=?", (event_key,)).fetchone()
                lifecycle = classify_lifecycle(
                    previous_fingerprint=old["evidence_fingerprint"] if old else None,
                    current_fingerprint=fingerprint,
                    previous_strength=int(old["strength"]) if old else None,
                    current_strength=strength,
                    was_current=bool(old["current"]) if old else False,
                )
                first_seen = str(old["first_seen"]) if old else captured_at
                subject, related = item.subject_player, item.related_player
                connection.execute(
                    """INSERT INTO event_states
                    (event_key, sleeper_user_id, league_id, season, week, event_type,
                     subject_player_id, subject_name, related_player_id, related_name,
                     priority, action, confidence, evidence_fingerprint, evidence_json,
                     opportunity_json, strength, lifecycle, first_seen, last_seen, current,
                     missing_count, freshness)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 'FRESH')
                    ON CONFLICT(event_key) DO UPDATE SET
                     week=excluded.week, priority=excluded.priority, action=excluded.action,
                     confidence=excluded.confidence, evidence_fingerprint=excluded.evidence_fingerprint,
                     evidence_json=excluded.evidence_json, opportunity_json=excluded.opportunity_json,
                     strength=excluded.strength, lifecycle=excluded.lifecycle, last_seen=excluded.last_seen,
                     current=1, missing_count=0, freshness='FRESH'""",
                    (
                        event_key, scope.sleeper_user_id, scope.league_id, scope.season, scope.week,
                        item.opportunity_type, subject.player_id if subject else None,
                        subject.name if subject else None, related.player_id if related else None,
                        related.name if related else None, item.priority, item.recommended_action,
                        item.confidence, fingerprint, _json(item.explanation_context),
                        _json(item.to_dict()), strength, lifecycle.value, first_seen, captured_at,
                    ),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO event_history
                    (snapshot_id, event_key, lifecycle, evidence_fingerprint, priority, action, current, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                    (snapshot_id, event_key, lifecycle.value, fingerprint, item.priority, item.recommended_action, captured_at),
                )
                decision_key = hashlib.sha256(f"{event_key}|{scope.week}|{fingerprint}".encode()).hexdigest()
                connection.execute(
                    """INSERT INTO decision_records
                    (decision_key, event_key, sleeper_user_id, league_id, season, week,
                     decision_type, subject_json, related_json, recommendation, confidence,
                     evidence_fingerprint, evidence_json, created_at, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(decision_key) DO UPDATE SET last_seen=excluded.last_seen""",
                    (
                        decision_key, event_key, scope.sleeper_user_id, scope.league_id,
                        scope.season, scope.week, item.opportunity_type,
                        _json(asdict(subject)) if subject else None,
                        _json(asdict(related)) if related else None,
                        item.recommended_action, item.confidence, fingerprint,
                        _json(item.explanation_context), captured_at, captured_at,
                    ),
                )
                feedback = connection.execute("SELECT status FROM user_feedback WHERE event_key=?", (event_key,)).fetchone()
                temporal.append(TemporalOpportunity(
                    item, event_key, lifecycle.value, first_seen, captured_at,
                    "FRESH", str(feedback["status"]) if feedback else None,
                ))

            active = connection.execute(
                """SELECT * FROM event_states
                WHERE sleeper_user_id=? AND league_id=? AND season=? AND current=1""",
                (scope.sleeper_user_id, scope.league_id, scope.season),
            ).fetchall()
            for old in active:
                if old["event_key"] in seen:
                    continue
                if not is_new_snapshot:
                    continue
                misses = int(old["missing_count"]) + 1
                if misses < RESOLUTION_FRESH_MISSES:
                    connection.execute(
                        "UPDATE event_states SET missing_count=?, freshness='STALE' WHERE event_key=?",
                        (misses, old["event_key"]),
                    )
                    continue
                connection.execute(
                    """UPDATE event_states SET current=0, missing_count=?, freshness='FRESH',
                    lifecycle=?, week=? WHERE event_key=?""",
                    (misses, Lifecycle.RESOLVED.value, scope.week, old["event_key"]),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO event_history
                    (snapshot_id, event_key, lifecycle, evidence_fingerprint, priority, action, current, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
                    (snapshot_id, old["event_key"], Lifecycle.RESOLVED.value, old["evidence_fingerprint"], old["priority"], old["action"], captured_at),
                )
                item = deserialize_opportunity(str(old["opportunity_json"]))
                feedback = connection.execute("SELECT status FROM user_feedback WHERE event_key=?", (old["event_key"],)).fetchone()
                resolved.append(TemporalOpportunity(
                    item, str(old["event_key"]), Lifecycle.RESOLVED.value,
                    str(old["first_seen"]), captured_at, "FRESH",
                    str(feedback["status"]) if feedback else None,
                ))

        changes = tuple(item for item in temporal if item.lifecycle != Lifecycle.ACTIVE.value) + tuple(resolved)
        counts = {lifecycle.value: 0 for lifecycle in Lifecycle}
        for item in changes:
            counts[item.lifecycle] += 1
        summary = TemporalSummary(
            counts[Lifecycle.NEW.value], counts[Lifecycle.STRENGTHENED.value],
            counts[Lifecycle.WEAKENED.value], counts[Lifecycle.CHANGED.value],
            counts[Lifecycle.RESOLVED.value], counts[Lifecycle.REOPENED.value],
        )
        order = {
            Lifecycle.NEW.value: 0, Lifecycle.REOPENED.value: 1,
            Lifecycle.STRENGTHENED.value: 2, Lifecycle.WEAKENED.value: 3,
            Lifecycle.CHANGED.value: 4, Lifecycle.ACTIVE.value: 5,
        }
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        temporal.sort(key=lambda value: (order[value.lifecycle], priority_order.get(value.opportunity.priority, 4), value.event_key))
        return ReconciliationResult(snapshot_id, previous_count > 0, tuple(temporal), changes, summary)

    def record_feedback(self, scope: LeagueScope, event_key: str, status: str, *, recorded_at: str | None = None) -> None:
        normalized = FeedbackStatus(status).value
        with self._connect() as connection:
            event = connection.execute(
                """SELECT event_key FROM event_states WHERE event_key=? AND sleeper_user_id=?
                AND league_id=? AND season=?""",
                (event_key, scope.sleeper_user_id, scope.league_id, scope.season),
            ).fetchone()
            if not event:
                raise KeyError("Unknown event for this league scope")
            connection.execute(
                """INSERT INTO user_feedback(event_key, sleeper_user_id, league_id, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at""",
                (event_key, scope.sleeper_user_id, scope.league_id, normalized, recorded_at or utc_now()),
            )

    def feedback_for(self, event_key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM user_feedback WHERE event_key=?", (event_key,)).fetchone()
        return str(row["status"]) if row else None

    def journal(self, scope: LeagueScope, *, limit: int = 30) -> list[JournalEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT e.*, f.status AS feedback,
                d.outcome, d.recommended_points, d.alternative_points
                FROM event_states e
                LEFT JOIN user_feedback f ON f.event_key=e.event_key
                LEFT JOIN decision_records d ON d.decision_key=(
                    SELECT d2.decision_key FROM decision_records d2
                    WHERE d2.event_key=e.event_key
                    ORDER BY d2.week DESC, d2.last_seen DESC, d2.decision_key DESC LIMIT 1
                )
                WHERE e.sleeper_user_id=? AND e.league_id=? AND e.season=?
                ORDER BY e.week DESC, e.last_seen DESC LIMIT ?""",
                (scope.sleeper_user_id, scope.league_id, scope.season, limit),
            ).fetchall()
        return [JournalEntry(
            str(row["event_key"]), str(row["event_type"]), row["subject_name"],
            row["related_name"], str(row["priority"]), str(row["action"]),
            str(row["confidence"]), str(row["lifecycle"]), int(row["week"]),
            str(row["first_seen"]), str(row["last_seen"]), row["feedback"], row["outcome"],
            row["recommended_points"], row["alternative_points"],
            tuple(json.loads(row["evidence_json"])),
        ) for row in rows]

    def pending_lineup_decisions(self, scope: LeagueScope, *, before_week: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM decision_records WHERE sleeper_user_id=? AND league_id=?
                AND season=? AND decision_type='LINEUP_OPPORTUNITY' AND week<? AND outcome IS NULL""",
                (scope.sleeper_user_id, scope.league_id, scope.season, before_week),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_outcome(
        self, decision_key: str, outcome: str, recommended_points: float | None,
        alternative_points: float | None, *, evaluated_at: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE decision_records SET outcome=?, recommended_points=?,
                alternative_points=?, evaluated_at=?, status='EVALUATED' WHERE decision_key=?""",
                (outcome, recommended_points, alternative_points, evaluated_at or utc_now(), decision_key),
            )

    def record_analytics(
        self, scope: LeagueScope, event_name: str, *, event_key: str | None = None,
        metadata: dict[str, Any] | None = None, idempotency_key: str | None = None,
        occurred_at: str | None = None,
    ) -> None:
        metadata = metadata or {}
        if any(any(term in str(key).lower() for term in SENSITIVE_KEYS) for key in metadata):
            raise ValueError("Sensitive analytics metadata is not allowed")
        safe = {str(key): value for key, value in metadata.items() if isinstance(value, (str, int, float, bool)) or value is None}
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO analytics_events
                (idempotency_key, sleeper_user_id, league_id, season, week, event_name,
                 event_key, metadata_json, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (idempotency_key, scope.sleeper_user_id, scope.league_id, scope.season,
                 scope.week, event_name, event_key, _json(safe), occurred_at or utc_now()),
            )

    def analytics_count(self, event_name: str | None = None) -> int:
        with self._connect() as connection:
            if event_name:
                row = connection.execute("SELECT COUNT(*) FROM analytics_events WHERE event_name=?", (event_name,)).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) FROM analytics_events").fetchone()
        return int(row[0])
