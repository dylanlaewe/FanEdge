"""Read-only beta funnel report; no user identifiers, feedback text or questions printed."""
import argparse
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def report(path):
    db = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = [dict(r) for r in db.execute("SELECT * FROM beta_events")] if "beta_events" in tables else []
        legacy = [dict(r) for r in db.execute("SELECT event_name,metadata_json FROM analytics_events")] if "analytics_events" in tables else []
    finally:
        db.close()
    events = Counter(r["event"] for r in rows)
    users = {r["user_id"] for r in rows if r["user_id"]}
    sessions = {r["session_id"] for r in rows if r["session_id"]}
    feedback = Counter(r["category"] for r in rows if r["event"] == "feedback")
    intents, unsupported, errors, perf = Counter(), Counter(), Counter(), defaultdict(list)
    for row in legacy:
        meta = json.loads(row["metadata_json"])
        if row["event_name"] == "copilot_question_submitted":
            if meta.get("ai_fallback"):
                errors["AI_FALLBACK"] += 1
            intents[meta.get("intent", "UNKNOWN")] += 1
            if meta.get("supported") is False:
                unsupported[meta.get("intent", "UNKNOWN")] += 1
    for row in rows:
        if row["event"] != "request":
            continue
        context = json.loads(row["context_json"])
        perf[context["route"]].append(context["duration_ms"])
        if row["category"] != "OK":
            errors[row["category"]] += 1
    return {"users": len(users), "sessions": len(sessions), "funnel_events": dict(events),
            "activation_sessions": len({r["session_id"] for r in rows if r["event"] == "intelligence_ready" and r["session_id"]}),
            "feature_adoption_users": {f: len({r["user_id"] for r in rows if r["event"] == f and r["user_id"]}) for f in ("home", "team", "market", "waivers", "trades", "ask")},
            "recommendation_feedback": {k: feedback[k] for k in ("HELPFUL", "NOT_HELPFUL")},
            "product_feedback": dict(feedback),
            "actions": {action: sum(r["event_name"] == f"recommendation_{action}" for r in legacy) for action in ("saved", "done", "dismissed")},
            "ask_intents": dict(intents), "unsupported_demand": dict(unsupported), "errors": dict(errors),
            "performance": {route: {"samples": len(v), "median_ms": statistics.median(v), "max_ms": max(v)} for route, v in perf.items()},
            "quality_labels": "Not stored with production data. Run calibration_report.py.",
            "limitations": "Session IDs identify browser tabs, not verified people; mount impressions are not proof of reading. No raw question/text exports. Counts include only retained rows."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".fanedge/fanedge.db")
    parser.add_argument("--audit", action="append", default=[], help="Optional audit JSON; matching .labels.json stays separate from production")
    args = parser.parse_args()
    value = report(args.db)
    if args.audit:
        from calibration_report import aggregate
        value["quality_labels"] = aggregate([(json.loads(Path(p).read_text()), json.loads(Path(p).with_suffix(".labels.json").read_text())) for p in args.audit])
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
