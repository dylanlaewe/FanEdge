"""Bounded, single-flight TTL caches with optional stale-while-revalidate."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any, Callable


@dataclass
class Entry:
    value: Any
    expires: float


class TTLCache:
    def __init__(self, max_entries=64, clock=monotonic):
        self.entries = OrderedDict()
        self.lock = RLock()
        self.key_locks = [RLock() for _ in range(32)]
        self.pending = set()
        self.errors = {}
        self.retry_after = {}
        self.pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="fanedge-refresh"
        )
        self.max_entries, self.clock = max_entries, clock

    def get(self, key, ttl: float, factory: Callable, *, background=False, force=False):
        with self.lock:
            entry = self.entries.get(key)
            if entry and not force and entry.expires > self.clock():
                self.entries.move_to_end(key)
                return entry.value
            if entry and background:
                if key not in self.pending and (
                    force or self.retry_after.get(key, 0) <= self.clock()
                ):
                    self.pending.add(key)
                    self.pool.submit(self._refresh, key, ttl, factory)
                return entry.value
        with self.key_locks[hash(key) % len(self.key_locks)]:
            with self.lock:
                entry = self.entries.get(key)
                if entry and not force and entry.expires > self.clock():
                    return entry.value
            value = factory()
            self.put(key, value, ttl)
            return value

    def put(self, key, value, ttl):
        with self.lock:
            self.entries[key] = Entry(value, self.clock() + ttl)
            self.entries.move_to_end(key)
            self.errors.pop(key, None)
            self.retry_after.pop(key, None)
            while len(self.entries) > self.max_entries:
                removed, _ = self.entries.popitem(last=False)
                self.errors.pop(removed, None)
                self.retry_after.pop(removed, None)

    def _refresh(self, key, ttl, factory):
        try:
            self.put(key, factory(), ttl)
        except Exception:
            with self.lock:
                self.errors[key] = (
                    "Refresh failed; showing the last successful snapshot."
                )
                self.retry_after[key] = self.clock() + 30
        finally:
            with self.lock:
                self.pending.discard(key)

    def status(self, key):
        with self.lock:
            entry = self.entries.get(key)
            return {
                "refreshing": key in self.pending,
                "stale": bool(entry and entry.expires <= self.clock()),
                "refresh_error": self.errors.get(key),
            }

    def close(self):
        self.pool.shutdown(wait=True)
