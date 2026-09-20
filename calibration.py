"""Optional, attributed draft-sentiment evidence; never an in-season market oracle."""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

import requests

from player_identity import normalize_name
from team_identity import normalize_team_id

SOURCE_URL = "https://help.fantasyfootballcalculator.com/article/42-adp-rest-api"


@dataclass(frozen=True)
class MarketEvidence:
    player_id: str
    adp: float
    samples: int
    as_of: str
    source: str = "Fantasy Football Calculator"
    url: str = SOURCE_URL
    kind: str = "DRAFT_SENTIMENT"


class CalibrationError(ValueError):
    pass


class ADPClient:
    def fetch(self, scoring, teams, season):
        try:
            response = requests.get(
                f"https://fantasyfootballcalculator.com/api/v1/adp/{scoring}",
                params={"teams": teams, "year": season},
                timeout=5,
            )
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict) or not isinstance(
                value.get("players"), list
            ):
                raise TypeError("Malformed ADP response")
            return value
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise CalibrationError("Draft-sentiment data unavailable.") from exc


def resolve_adp(payload, players, *, season, week, teams, scoring, today=None):
    """Exact name/position/canonical-team join; missing/ambiguous identities stay unknown."""
    today = today or datetime.now(UTC).date()
    meta = payload.get("meta", {})
    try:
        end = date.fromisoformat(meta["end_date"])
        valid = (
            end.year == season
            and 0 <= (today - end).days <= 7
            and int(meta["teams"]) == teams
            and int(meta["total_drafts"]) >= 50
            and week <= 4
            and str(meta["type"]).lower().replace(" ", "-") == scoring
        )
    except (KeyError, ValueError, TypeError):
        valid = False
    if not valid:
        return {}, {
            "status": "REJECTED",
            "reason": "ADP date, format, sample, or seasonal applicability gate failed.",
            "matched": 0,
        }
    index = {}
    for player in players:
        key = (
            normalize_name(player.name),
            player.position,
            normalize_team_id("sleeper", player.team),
        )
        index.setdefault(key, []).append(player.player_id)
    found, duplicates, skipped = {}, set(), 0
    for row in payload["players"]:
        try:
            key = (
                normalize_name(row["name"]),
                row["position"],
                normalize_team_id("sleeper", row["team"]),
            )
            ids = index.get(key, [])
            adp, samples = float(row["adp"]), int(row["times_drafted"])
            if (
                len(ids) != 1
                or key[2] is None
                or samples < 20
                or not math.isfinite(adp)
                or adp <= 0
            ):
                skipped += 1
                continue
            pid = ids[0]
            if pid in found:
                duplicates.add(pid)
            found[pid] = MarketEvidence(pid, adp, samples, end.isoformat())
        except (KeyError, ValueError, TypeError):
            skipped += 1
    for pid in duplicates:
        found.pop(pid, None)
    return found, {
        "status": "USABLE" if found else "INSUFFICIENT_SAMPLE",
        "matched": len(found),
        "skipped": skipped,
        "as_of": end.isoformat(),
        "source": SOURCE_URL,
        "kind": "DRAFT_SENTIMENT",
    }


TIERS = ("SPECULATIVE", "BENCH", "DEPTH", "STARTER", "HIGH_END", "FOUNDATION")


def evidence_tier(
    quality,
    typical,
    *,
    games,
    historical_games=0,
    confidence="LOW",
    market=None,
    league_size=12,
):
    if not typical or confidence == "LOW" or (games < 4 and historical_games < 8):
        return "SPECULATIVE"
    ratio = quality / typical
    tier = (
        "FOUNDATION"
        if ratio >= 1.35
        else "HIGH_END"
        if ratio >= 1.10
        else "STARTER"
        if ratio >= 0.85
        else "DEPTH"
        if ratio >= 0.60
        else "BENCH"
    )
    # Corroborated early draft demand can protect importance, never manufacture it.
    if (
        market
        and market.adp <= league_size * 2
        and ratio >= 0.85
        and historical_games >= 8
        and TIERS.index(tier) < TIERS.index("HIGH_END")
    ):
        tier = "HIGH_END"
    return tier
