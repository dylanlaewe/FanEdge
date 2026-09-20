"""Measure real HTTP wall time against a running backend; no profiler overhead."""

import argparse
import json
import statistics
from time import perf_counter
from urllib.parse import quote
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="TKelceLoveMachine")
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()

    def fetch(path):
        start = perf_counter()
        with urlopen(args.url + path, timeout=90) as response:
            value = json.load(response)
        return value, round((perf_counter() - start) * 1000, 3)

    leagues, connection_ms = fetch(f"/api/users/{quote(args.username)}/leagues")
    league = leagues["leagues"][0]["id"]

    def path(route):
        return f"/api/leagues/{league}/{route}?username={quote(args.username)}"

    snapshot, initial_ms = fetch(path("snapshot"))
    results = {
        "connection_ms": connection_ms,
        "initial_snapshot_ms": initial_ms,
        "snapshot_built_at": snapshot["meta"]["built_at"],
        "reads": {},
    }
    for route in (
        "overview",
        "roster",
        "lineup",
        "waivers",
        "events",
        "history",
        "snapshot",
    ):
        values = sorted(fetch(path(route))[1] for _ in range(args.samples))
        results["reads"][route] = {
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": values[max(0, int(len(values) * 0.95) - 1)],
            "max_ms": max(values),
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
