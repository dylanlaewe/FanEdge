"""Compare the committed M11 reference with M12 using identical live provider data."""

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
from backend.services import IntelligenceService
from football_data import NflverseClient
from news import ESPNNewsClient
from sleeper_api import SleeperClient
from storage import SQLiteRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="TKelceLoveMachine")
    parser.add_argument("--reference", default="ee071e2")
    args = parser.parse_args()
    source = subprocess.check_output(
        ["git", "show", f"{args.reference}:app.py"], cwd=ROOT, text=True
    )
    anchor = "    view = st.session_state.application_nav"
    assert source.count(anchor) == 1
    source = source.replace(
        anchor, "    st.session_state.parity_state = copilot_state\n" + anchor
    )
    captured = {}

    def freeze(cls, method):
        original = getattr(cls, method)

        def call(instance, *values, **kwargs):
            # The two UIs normalize username casing differently; Sleeper does not.
            normalized = tuple(
                v.lower() if method == "get_user" and isinstance(v, str) else v
                for v in values
            )
            key = (cls.__name__, method, normalized, tuple(sorted(kwargs.items())))
            if key not in captured:
                captured[key] = original(instance, *values, **kwargs)
            return copy.deepcopy(captured[key])

        return call

    with (
        tempfile.TemporaryDirectory(prefix="fanedge-parity-") as directory,
        ExitStack() as stack,
    ):
        stack.enter_context(
            patch.dict(
                os.environ,
                {"FANEDGE_DB_PATH": f"{directory}/legacy.db", "OPENAI_API_KEY": ""},
            )
        )
        for cls, methods in [
            (
                SleeperClient,
                [
                    "get_user",
                    "get_leagues",
                    "get_rosters",
                    "get_players",
                    "get_nfl_state",
                ],
            ),
            (
                NflverseClient,
                [
                    "get_schedule_rows",
                    "get_stat_rows",
                    "get_snap_rows",
                    "get_injury_rows",
                    "get_player_rows",
                ],
            ),
            (ESPNNewsClient, ["fetch"]),
        ]:
            for method in methods:
                stack.enter_context(patch.object(cls, method, freeze(cls, method)))
        app = AppTest.from_string(source, default_timeout=180).run()
        app.text_input[0].set_value(args.username)
        app.button[0].click().run()
        assert not app.exception, [e.message for e in app.exception]
        old = app.session_state.parity_state
        service = IntelligenceService(
            repository=SQLiteRepository(f"{directory}/migrated.db")
        )
        try:
            snapshot, _ = service.get_snapshot(
                args.username, str(old.league["league_id"])
            )
            new = snapshot.state
            results = {}
            for field in (
                "roster",
                "lineup_slots",
                "lineup_decisions",
                "waiver_candidates",
                "drop_candidates",
                "roster_needs",
                "opportunity_feed",
                "news_facts",
                "matchup_index",
                "identities",
            ):
                results[field] = getattr(old, field) == getattr(new, field)
            # M12 also builds context for other league-rostered players for the drawer.
            for field in ("contexts", "opportunities", "profiles"):
                results[field] = all(
                    value == getattr(new, field).get(key)
                    for key, value in getattr(old, field).items()
                )
            print(
                json.dumps(
                    {
                        "equal": results,
                        "timings_ms": snapshot.timings,
                        "frozen_provider_calls": len(captured),
                    },
                    indent=2,
                )
            )
            assert all(results.values()), "Parity mismatch; inspect compared fields"
        finally:
            service.close()


if __name__ == "__main__":
    main()
