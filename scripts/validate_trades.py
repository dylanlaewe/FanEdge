"""Real-provider trade validation. Writes reports only to an explicit local path."""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services import IntelligenceService
from storage import SQLiteRepository
from trades import TradeEngine, TradeOptions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="TKelceLoveMachine")
    parser.add_argument("--output", default="/tmp/fanedge-trades-validation.json")
    parser.add_argument(
        "--all-rosters",
        action="store_true",
        help="Also audit hypothetical viewpoints of the same league, not additional leagues/accounts",
    )
    parser.add_argument(
        "--recheck",
        nargs="*",
        default=[],
        help="Prior reports to re-analyze, including rejected examples",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="fanedge-trades-") as directory:
        service = IntelligenceService(
            SQLiteRepository(Path(directory) / "validation.db")
        )
        try:
            _, leagues = service.connect(args.username)
            reports = []
            for league in leagues[:2]:
                snap, _ = service.get_snapshot(args.username, str(league["league_id"]))
                start = perf_counter()
                engine = service.trade_engine(snap)
                build_ms = (perf_counter() - start) * 1000
                overview = engine.overview()
                searches = {}
                for goal in ("RB", "WR", "TE", "BEST_UPGRADE", "DEPTH"):
                    searches[goal] = engine.search(TradeOptions(goal=goal, limit=30))
                for goal in ("RB", "WR", "BEST_UPGRADE"):
                    searches[f"explicitly_unlocked_{goal}"] = engine.search(
                        TradeOptions(goal=goal, protect_core=False, limit=30)
                    )
                protected = engine.default_protected[:1]
                if not protected:
                    protected = tuple(
                        sorted(
                            engine.teams[engine.user_team_id]["player_ids"],
                            key=lambda p: -engine.values[p].relative_value,
                        )[:1]
                    )
                searches["protected_star"] = engine.search(
                    TradeOptions(goal="RB", protected=protected, limit=30)
                )
                targets = [
                    pid
                    for pid, owner in engine.owners.items()
                    if owner != engine.user_team_id
                    and engine.players[pid].position == "RB"
                    and engine.values[pid].supported
                    and engine.values[pid].available
                ]
                target = max(
                    targets,
                    key=lambda pid: engine.values[pid].relative_value,
                    default=None,
                )
                if target:
                    searches["specific_target"] = engine.search(
                        TradeOptions(goal="RB", target_id=target, limit=30)
                    )
                for target_id in targets:
                    searches[f"target_{target_id}"] = engine.search(
                        TradeOptions(goal="RB", target_id=target_id, limit=30)
                    )
                for target_id in [
                    pid
                    for pid, owner in engine.owners.items()
                    if owner != engine.user_team_id
                    and engine.players[pid].position in {"WR", "TE"}
                    and engine.values[pid].supported
                    and engine.values[pid].available
                ]:
                    searches[f"target_{target_id}"] = engine.search(
                        TradeOptions(
                            goal=engine.players[target_id].position,
                            target_id=target_id,
                            protect_core=False,
                            limit=30,
                        )
                    )
                ideas = {
                    idea["id"]: idea
                    for result in searches.values()
                    for idea in result["ideas"]
                }
                rechecks = {}
                for report_path in args.recheck:
                    for prior in json.loads(Path(report_path).read_text()):
                        if (
                            prior["league"] != league["name"]
                            or prior["team"]
                            != engine.teams[engine.user_team_id]["team_name"]
                        ):
                            continue
                        for result in prior["searches"].values():
                            for idea in result["ideas"]:
                                options = TradeOptions(
                                    goal="DEPTH"
                                    if idea["user_impact"]["lineup_delta"] < 1
                                    else "BEST_UPGRADE",
                                    protect_core=False,
                                )
                                rechecks[idea["id"]] = engine.analyze(
                                    idea["outgoing"], idea["incoming"], options
                                )
                perspectives = {}
                if args.all_rosters:
                    for team in engine.teams.values():
                        if team["roster_id"] == engine.user_team_id:
                            continue
                        other = TradeEngine(
                            snap.state, snap.rosters, snap.metadata, team["owner_id"]
                        )
                        perspectives[team["roster_id"]] = {
                            "team_name": team["team_name"],
                            "result": other.search(TradeOptions(limit=30)),
                        }
                reports.append(
                    {
                        "league": league["name"],
                        "team": engine.teams[engine.user_team_id]["team_name"],
                        "profile_ms": round(build_ms, 2),
                        "overview": overview,
                        "searches": searches,
                        "target": engine.players[target].name if target else None,
                        "protected": [engine.players[p].name for p in protected],
                        "players": {
                            pid: {
                                "name": engine.players[pid].name,
                                "position": engine.players[pid].position,
                            }
                            for pid in engine.owners
                        },
                        "unique_ideas": len(ideas),
                        "rechecked_previous_ideas": rechecks,
                        "additional_viewpoints_same_league": perspectives,
                    }
                )
                print(
                    json.dumps(
                        {
                            "league": league["name"],
                            "teams": len(engine.teams),
                            "profile_ms": round(build_ms, 2),
                            "searches": {
                                key: {
                                    "ideas": len(value["ideas"]),
                                    "ms": value["elapsed_ms"],
                                    "tested": value["tested"],
                                }
                                for key, value in searches.items()
                                if not key.startswith("target_")
                            },
                            "unique": len(ideas),
                            "additional_viewpoint_ideas": sum(
                                len(p["result"]["ideas"]) for p in perspectives.values()
                            ),
                        },
                        indent=2,
                    ),
                    flush=True,
                )
            Path(args.output).write_text(json.dumps(reports, indent=2))
        finally:
            service.close()


if __name__ == "__main__":
    main()
