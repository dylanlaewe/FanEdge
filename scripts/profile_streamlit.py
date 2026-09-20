"""Reproducible real-provider Streamlit profiling; run from the repository root."""

import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="TKelceLoveMachine")
    parser.add_argument("--output", default="/tmp/fanedge-streamlit-before.json")
    parser.add_argument("--no-profile", action="store_true")
    args = parser.parse_args()
    calls = defaultdict(lambda: {"calls": 0, "ms": 0.0})
    started = {}

    def profile(frame, event, arg):
        filename = frame.f_code.co_filename
        name = frame.f_code.co_name
        local = filename.startswith(str(ROOT)) and "/.venv/" not in filename
        network = filename.endswith("requests/sessions.py") and name == "send"
        if not (local or network):
            return
        key = f"{Path(filename).name}:{name}"
        if event == "call":
            started[id(frame)] = time.perf_counter()
        elif event == "return" and id(frame) in started:
            calls[key]["calls"] += 1
            calls[key]["ms"] += (time.perf_counter() - started.pop(id(frame))) * 1000

    if not args.no_profile:
        threading.setprofile(profile)
    results = []
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)

    def measure(label, action):
        calls.clear()
        begin = time.perf_counter()
        action()
        result = {
            "interaction": label,
            "wall_ms": round((time.perf_counter() - begin) * 1000, 2),
            "functions": {
                key: {"calls": value["calls"], "ms": round(value["ms"], 2)}
                for key, value in calls.items()
                if not key.endswith(":<genexpr>") and not key.endswith(":<listcomp>")
            },
            "errors": [str(item.message) for item in app.exception],
        }
        results.append(result)
        print(label, result["wall_ms"], result["errors"], flush=True)
        Path(args.output).write_text(json.dumps(results, indent=2))

    measure("startup", lambda: app.run())
    app.text_input[0].set_value(args.username)
    measure("connection_and_initial_league", lambda: app.button[0].click().run())
    for view in ["My Team", "Waivers", "Ask FanEdge", "Overview"] * 2:
        measure(
            f"navigate:{view}",
            lambda view=view: app.radio(key="application_nav").set_value(view).run(),
        )
    threading.setprofile(None)


if __name__ == "__main__":
    main()
