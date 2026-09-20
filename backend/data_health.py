"""Fetch freshness is not content freshness. Bounded, secret-free provider telemetry."""

from collections import OrderedDict
from datetime import UTC, datetime
from threading import RLock
from time import time

from backend.cache import TTLCache

DATASETS = {
    "players": "Sleeper players",
    "rosters": "Sleeper rosters",
    "connection": "Sleeper connection",
    "nfl_state": "Sleeper NFL state",
    "schedule_rows": "Schedule",
    "stats": "Stats",
    "snaps": "Snap counts",
    "injuries": "Injury reports",
    "identity_rows": "Player identities",
    "news_facts": "News",
    "calibration": "Market calibration",
    "memory": "Memory",
}


class DataHealth:
    def __init__(self, clock=time):
        self.clock, self.entries, self.lock = clock, OrderedDict(), RLock()

    def observe(self, key, ttl, value=None, *, failed=False, warning=None):
        base = key[0] if isinstance(key, tuple) else key
        if base not in DATASETS:
            return
        with self.lock:
            old = self.entries.get(key, {})
            record = {
                **old,
                "provider": DATASETS[base],
                "dataset": base,
                "last_attempt": self.clock(),
                "stale_threshold_seconds": ttl,
                "failed": failed,
                "warnings": [warning] if warning else [],
            }
            if not failed:
                record.update(
                    last_success=self.clock(),
                    records=len(value.get("players", []))
                    if base == "calibration" and isinstance(value, dict)
                    else len(value)
                    if isinstance(value, (dict, list, tuple))
                    else 1,
                )
                if base in {"stats", "snaps", "injuries"} and isinstance(value, list):
                    weeks = [
                        int(row["week"])
                        for row in value
                        if str(row.get("week", "")).isdigit()
                        and row.get("season_type", "REG") == "REG"
                    ]
                    record["latest_content_week"] = max(weeks, default=None)
                    record["season"] = key[1]
                if base == "news_facts" and isinstance(value, (list, tuple)):
                    dates = [str(getattr(item, "published_at", "")) for item in value]
                    record["latest_content_at"] = max(dates, default=None)
            self.entries[key] = record
            self.entries.move_to_end(key)
            while len(self.entries) > 128:
                self.entries.popitem(last=False)

    def report(self, keys=None, *, expected_week=None, season=None):
        with self.lock:
            rows = [
                dict(value)
                for key, value in self.entries.items()
                if (
                    keys is None
                    and value["dataset"] not in {"rosters", "connection", "memory"}
                )
                or (keys is not None and key in keys)
            ]
        for row in rows:
            row["warnings"] = list(row["warnings"])
            last = row.get("last_success")
            age = max(0, self.clock() - last) if last is not None else None
            row["age_seconds"] = round(age, 1) if age is not None else None
            row["status"] = (
                "UNAVAILABLE"
                if row.pop("failed")
                else "STALE"
                if age is not None and age > row["stale_threshold_seconds"]
                else "EMPTY"
                if row.get("records") == 0
                else "OK"
            )
            if (
                row["status"] == "OK"
                and season == row.get("season")
                and expected_week
                and (row.get("latest_content_week") or 0) < expected_week
            ):
                row["status"] = "DELAYED"
                row["warnings"].append(
                    "Fetched successfully, but completed-week content is behind the expected week."
                )
            for field in ("last_success", "last_attempt"):
                row[field] = (
                    datetime.fromtimestamp(row[field], UTC).isoformat()
                    if row.get(field) is not None
                    else None
                )
        if keys is None:
            observed = {row["dataset"] for row in rows}
            for dataset, threshold in {
                "players": 86400,
                "nfl_state": 300,
                "schedule_rows": 21600,
                "stats": 21600,
                "snaps": 21600,
                "injuries": 3600,
                "news_facts": 900,
            }.items():
                if dataset not in observed:
                    rows.append(
                        {
                            "provider": DATASETS[dataset],
                            "dataset": dataset,
                            "status": "NOT_FETCHED",
                            "last_success": None,
                            "age_seconds": None,
                            "records": None,
                            "stale_threshold_seconds": threshold,
                            "warnings": ["No successful observation in this process."],
                        }
                    )
        return rows


class ProviderCache(TTLCache):
    def __init__(self, health):
        super().__init__(64)
        self.health = health

    def get(self, key, ttl, factory, **kwargs):
        def tracked():
            try:
                value = factory()
            except Exception:
                from backend.beta import log_request, correlation_id
                log_request("provider", "PROVIDER_UNAVAILABLE", correlation_id.get(), 0,
                            stage="fetch", provider=DATASETS.get(key[0] if isinstance(key, tuple) else key, "unknown"))
                self.health.observe(
                    key,
                    ttl,
                    failed=True,
                    warning="Provider refresh failed; absence of new data is not evidence of no change.",
                )
                raise
            self.health.observe(key, ttl, value)
            return value

        return super().get(key, ttl, tracked, **kwargs)
