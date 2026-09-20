"""Opt-in real-provider quality artifact. No raw provider dumps or persistent user DB."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.presenter import present
from backend.services import IntelligenceService
from storage import SQLiteRepository
from trades import TradeOptions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="TKelceLoveMachine")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    os.environ["OPENAI_API_KEY"] = (
        ""  # Audit deterministic grounding, not optional prose.
    )
    with tempfile.TemporaryDirectory(prefix="fanedge-quality-") as folder:
        service = IntelligenceService(SQLiteRepository(Path(folder) / "audit.db"))
        try:
            _, leagues = service.connect(args.username)
            snapshot, _ = service.get_snapshot(
                args.username, str(leagues[0]["league_id"])
            )
            engine = service.trade_engine(snapshot)
            questions = [
                "What should I do this week?",
                "I need an RB. What should I do?",
                "Who should I shop?",
                "Find me an RB trade",
                "What changed since my last check?",
                "Will rain affect my lineup?",
            ]
            if snapshot.state.roster.starters:
                questions += [f"Tell me about {snapshot.state.roster.starters[0].name}"]
            answers = {q: service.ask(snapshot, q)[2].to_dict() for q in questions}
            report = {
                "league": snapshot.state.league["name"],
                "snapshot": present(snapshot, service.repository).model_dump(
                    mode="json"
                ),
                "timings": snapshot.timings,
                "answers": answers,
                "profiles": engine.overview(),
                "searches": {
                    goal: engine.search(TradeOptions(goal=goal))
                    for goal in ("RB", "WR", "BEST_UPGRADE", "DEPTH")
                },
                "targeted": engine.search(TradeOptions(target_id="12481", goal="RB"))
                if "12481" in engine.owners
                else None,
            }
            if hasattr(service, "data_health"):
                report["data_health"] = service.data_health(snapshot)
            Path(args.output).write_text(json.dumps(report, indent=2, default=str))
            print(
                json.dumps(
                    {
                        "league": report["league"],
                        "timings": report["timings"],
                        "lineup": len(report["snapshot"]["recommendations"]),
                        "waivers": len(report["snapshot"]["waivers"]),
                        "events": len(report["snapshot"]["events"]),
                        "trades": {
                            key: len(value["ideas"])
                            for key, value in report["searches"].items()
                        },
                    },
                    indent=2,
                )
            )
        finally:
            service.close()


if __name__ == "__main__":
    main()
