"""Aggregate audit JSON plus separate human labels. Unreviewed is never PASS."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

LABELS = {"GOOD", "DEFENSIBLE", "QUESTIONABLE", "BAD"}
GATES = ("data_integrity", "recommendation_safety", "ai_grounding", "performance",
         "reliability", "security", "providers", "independent_leagues", "ux", "deployment", "rollback")


def aggregate(pairs):
    groups = {name: defaultdict(Counter) for name in ("feature", "league_type", "position", "recommendation_type", "evidence_quality")}
    totals, rejections, leagues, users, audits = Counter(), Counter(), set(), set(), set()
    integrity = []
    for audit, labels in pairs:
        if labels.get("audit_id") != audit["audit_id"]:
            raise ValueError("Labels belong to a different audit.")
        if audit["audit_id"] in audits:
            raise ValueError("Duplicate audit input.")
        audits.add(audit["audit_id"])
        known = {row["id"] for row in audit["review_items"]}
        ids = [row["id"] for row in labels["items"]]
        if len(ids) != len(set(ids)) or set(ids) - known:
            raise ValueError("Duplicate or unknown labeled recommendation.")
        labeled = {row["id"]: row.get("label") for row in labels["items"]}
        if any(value is not None and value not in LABELS for value in labeled.values()):
            raise ValueError("Invalid human label.")
        if any(labeled.values()) and not labels.get("reviewer", "").strip():
            raise ValueError("Reviewed labels require reviewer attribution.")
        leagues.add(audit["league"]["id"])
        users.add(audit["league"]["user_id"])
        league_type = json.dumps(audit["league"]["format"], sort_keys=True)
        integrity.extend(audit["data_quality"]["issues"])
        for row in audit["review_items"]:
            label = labeled.get(row["id"]) or "UNREVIEWED"
            totals[label] += 1
            for group, values in groups.items():
                values[league_type if group == "league_type" else row[group]][label] += 1
        for result in audit["searches"].values():
            # Counts are per search/goal, not distinct packages across searches.
            rejections.update(result.get("diagnostics", {}).get("primary_reasons", {}))
    return {"audits": len(audits), "leagues": len(leagues), "users": len(users),
            "labels": dict(totals), "groups": groups, "trade_rejections_per_search": dict(rejections),
            "integrity_issues": integrity,
            "recommendation_safety": "PASS" if totals and not totals["BAD"] and not totals["UNREVIEWED"] else "FAIL"}


def release_gates(summary, evidence):
    gates = {}
    for gate in GATES:
        item = evidence.get(gate, {})
        passed = item.get("status") == "PASS" and bool(item.get("evidence"))
        if gate == "recommendation_safety":
            passed = passed and summary["recommendation_safety"] == "PASS"
        if gate == "independent_leagues":
            passed = passed and summary["leagues"] >= 2 and summary["users"] >= 2
        if gate == "data_integrity":
            passed = passed and summary["audits"] > 0 and not any(i["severity"] == "ERROR" for i in summary["integrity_issues"])
        gates[gate] = {"status": "PASS" if passed else "FAIL", "evidence": item.get("evidence") or "Missing reviewed evidence."}
    return {"decision": "GO" if all(g["status"] == "PASS" for g in gates.values()) else "NO-GO", "gates": gates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audits", nargs="+")
    parser.add_argument("--gates", help="Manually reviewed gate evidence JSON")
    args = parser.parse_args()
    pairs = [(json.loads(Path(p).read_text()), json.loads(Path(p).with_suffix(".labels.json").read_text())) for p in args.audits]
    result = aggregate(pairs)
    result["release"] = release_gates(result, json.loads(Path(args.gates).read_text()) if args.gates else {})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
