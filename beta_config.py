"""Explicit, fail-closed optional capabilities. Restart after changing flags."""
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path


def enabled(name):
    return os.getenv(f"FANEDGE_{name}_ENABLED", "0") == "1"


def capabilities():
    return {
        "news_enabled": enabled("NEWS"),
        "player_images_enabled": enabled("PLAYER_IMAGES"),
        "team_logos_enabled": enabled("TEAM_LOGOS"),
        "market_calibration_enabled": enabled("MARKET_ADP"),
        "ai_enabled": enabled("AI") and bool(os.getenv("OPENAI_API_KEY")),
        "trade_discovery": "EXPERIMENTAL",
    }


@lru_cache(maxsize=1)
def build_version():
    supplied = os.getenv("FANEDGE_BUILD_ID", "")
    if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied):
        return supplied
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=Path(__file__).resolve().parent, stderr=subprocess.DEVNULL,
            timeout=1, text=True,
        ).strip()
        return f"m15-{sha}"
    except (OSError, subprocess.SubprocessError):
        return "m15-unknown"
