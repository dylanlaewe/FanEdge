"""Measure real HTTP wall time against a running backend; no profiler overhead."""

import argparse
import json
import statistics
from time import perf_counter
from urllib.parse import quote
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="TKelceLoveMachine")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--trades", action="store_true")
    parser.add_argument("--copilot", action="store_true")
    args = parser.parse_args()

    def fetch(path, body=None):
        start = perf_counter()
        request = Request(
            args.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=90) as response:
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
    if args.trades:
        overview, overview_ms = fetch(path("trades"))
        search, first_ms = fetch(path("trades/search"), {"goal": "BEST_UPGRADE"})
        samples = sorted(
            fetch(path("trades/search"), {"goal": "BEST_UPGRADE"})[1]
            for _ in range(args.samples)
        )
        results["trades"] = {
            "overview_http_ms": overview_ms,
            "rosters": len(overview["teams"]),
            "first_search_http_ms": first_ms,
            "engine_ms": search["elapsed_ms"],
            "candidates_checked": search["tested"],
            "cached_search_median_ms": round(statistics.median(samples), 3),
            "cached_search_p95_ms": samples[max(0, int(len(samples) * 0.95) - 1)],
        }
    if args.copilot:
        values = [
            fetch(path("copilot"), {"question": "I need an RB."})[1]
            for _ in range(min(args.samples, 5))
        ]
        results["copilot"] = {
            "first_ms": values[0],
            "warm_median_ms": round(statistics.median(values[1:] or values), 3),
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
