"""Small single-worker beta controls; no raw request bodies in telemetry."""
import json
import logging
import sqlite3
from collections import OrderedDict, deque
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from contextvars import ContextVar

from beta_config import build_version
correlation_id = ContextVar("fanedge_correlation", default="internal")
logger = logging.getLogger("fanedge.beta")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False

EVENTS = {
    "landing", "connect_started", "connect_succeeded", "intelligence_ready",
    "home", "team", "market", "waivers", "trades", "ask", "recommendation_viewed",
    "evidence_opened", "trade_search", "helpful", "not_helpful", "feedback",
    "return_session", "player_drawer",
}


class RateLimiter:
    """Bounded sliding window; untrusted forwarding headers are never identity."""
    def __init__(self, clock=monotonic):
        self.clock, self.lock, self.windows = clock, Lock(), OrderedDict()

    def allow(self, key, limit, seconds=60):
        with self.lock:
            now = self.clock()
            window = self.windows.setdefault(key, deque())
            while window and window[0] <= now - seconds:
                window.popleft()
            self.windows.move_to_end(key)
            while len(self.windows) > 4096:
                self.windows.popitem(last=False)
            if len(window) >= limit:
                return False
            window.append(now)
            return True


class BetaStore:
    """Separate instrumentation tables. Explicit 30-day maintenance retention."""
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS beta_events (
                id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL, build TEXT NOT NULL,
                session_id TEXT, user_id TEXT, league_id TEXT, feature TEXT,
                event TEXT NOT NULL, event_id TEXT, category TEXT, text TEXT,
                context_json TEXT NOT NULL DEFAULT '{}')""")
            db.execute("CREATE INDEX IF NOT EXISTS beta_time ON beta_events(occurred_at)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def record(self, event, *, session_id=None, user_id=None, league_id=None,
               feature=None, event_id=None, category=None, text=None, context=None):
        with self.connect() as db:
            db.execute("""INSERT INTO beta_events
                (occurred_at,build,session_id,user_id,league_id,feature,event,event_id,category,text,context_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                datetime.now(timezone.utc).isoformat(), build_version(), session_id,
                user_id, league_id, feature, event, event_id, category, text,
                json.dumps(context or {}, separators=(",", ":")),
            ))

    def prune(self):
        with self.connect() as db:
            return db.execute("DELETE FROM beta_events WHERE julianday(occurred_at) < julianday('now','-30 days')").rowcount


def log_request(route, category, correlation, duration, *, stage="request", provider=None):
    record = dict(timestamp=datetime.now(timezone.utc).isoformat(), build=build_version(),
                  route=route, stage=stage, category=category, provider=provider,
                  correlation_id=correlation, duration_ms=round(duration, 2))
    logger.info(json.dumps(record, separators=(",", ":")))
    return record


ai_budget = RateLimiter()
