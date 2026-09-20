"""Opt-in real-league audit with separate human labels; never tunes production."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.presenter import present
from backend.services import IntelligenceService
from beta_config import build_version, capabilities
from quality import audit_state
from storage import SQLiteRepository
from trades import TradeOptions


def review_items(report):
    items = []
    def add(feature, value, position="TEAM", kind="", evidence="UNKNOWN"):
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]
        items.append(dict(id=f"{feature}:{digest}", feature=feature, position=position,
                          recommendation_type=kind or feature, evidence_quality=evidence,
                          recommendation=value))
    snap = report["snapshot"]
    for row in snap["recommendations"]:
        add("lineup", row, row["player"]["position"], row["action"], row["confidence"])
    for row in snap["waivers"]:
        add(row["category"].lower(), row, row["player"]["position"], row["category"], row["player"]["confidence"])
    for row in snap["events"]:
        add("events", row, (row.get("player") or {}).get("position", "TEAM"), row["type"], row["confidence"])
    for name, row in report["answers"].items():
        add("ask", row, kind=name, evidence=row.get("confidence", "UNKNOWN"))
    for goal, result in report["searches"].items():
        for row in result["ideas"]:
            add("trades", row, goal if goal in {"QB", "RB", "WR", "TE"} else "TEAM", goal, row.get("confidence", "UNKNOWN"))
    for row in report["profiles"].get("partners", []):
        add("partners", row)
    return items


def run(username, league_id, position="RB"):
    os.environ["FANEDGE_AI_ENABLED"] = "0"
    with tempfile.TemporaryDirectory(prefix="fanedge-audit-") as folder:
        service = IntelligenceService(SQLiteRepository(Path(folder) / "audit.db"))
        try:
            snap, _ = service.get_snapshot(username, league_id)
            engine = service.trade_engine(snap)
            started = perf_counter()
            product = present(snap, service.repository)
            presentation_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            encoded = product.model_dump_json()
            serialization_ms = (perf_counter() - started) * 1000
            league = snap.state.league
            questions = {"weekly_plan": "What should I do this week?",
                         "weakness": "What's my biggest roster weakness?",
                         "position_plan": f"I need a {position}. What should I do?"}
            report = dict(schema_version=1, build=build_version(), capabilities=capabilities(),
                audit_id=snap.id, captured_at=snap.built_at,
                league={"id": league_id, "user_id": snap.scope.sleeper_user_id,
                        "name": league.get("name"), "teams": len(snap.rosters),
                        "scoring": league.get("scoring_settings", {}),
                        "roster_positions": league.get("roster_positions", []),
                        "format": {"type": (league.get("settings") or {}).get("type"),
                                   "scoring": product.league.scoring}},
                snapshot=product.model_dump(mode="json"),
                timings={**snap.timings, "presentation_ms": round(presentation_ms, 3), "serialization_ms": round(serialization_ms, 3), "snapshot_bytes": len(encoded.encode())}, profiles=engine.overview(),
                searches={goal: engine.search(TradeOptions(goal=goal)) for goal in ("RB", "WR", "BEST_UPGRADE", "DEPTH")},
                answers={key: service.ask(snap, question)[2].to_dict() for key, question in questions.items()},
                data_quality={"issues": [v.to_dict() for v in audit_state(snap.state)],
                              "providers": service.data_health(snap),
                              "identities_total": len(snap.state.identities),
                              "missing_gsis": sum(not i.gsis_id for i in snap.state.identities.values()),
                              "warnings": list(snap.warnings)})
            report["review_items"] = review_items(report)
            return report
        finally:
            service.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--league", required=True)
    parser.add_argument("--position", choices=["QB", "RB", "WR", "TE"], default="RB")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    labels = output.with_suffix(".labels.json")
    if output.exists() or labels.exists():
        parser.error("Choose a new output path; existing audits/labels are never overwritten.")
    report = run(args.username, args.league, args.position)
    output.write_text(json.dumps(report, indent=2, default=str))
    labels.write_text(json.dumps({"audit_id": report["audit_id"], "reviewer": "", "items": [
        {"id": item["id"], "label": None, "reason": ""} for item in report["review_items"]]}, indent=2))
    print(json.dumps({"audit": str(output), "labels": str(labels), "review_items": len(report["review_items"])}))


if __name__ == "__main__":
    main()
