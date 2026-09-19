"""Explicit NFL team identity normalization across FanEdge providers."""

from __future__ import annotations


NFL_TEAMS = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO",
    "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
})

PROVIDER_ALIASES = {
    "nflverse": {"LA": "LAR", "LAR": "LAR", "JAC": "JAX", "WSH": "WAS", "LVR": "LV"},
    "sleeper": {"LA": "LAR", "JAC": "JAX", "WSH": "WAS", "LVR": "LV"},
    "historical": {"STL": "LAR", "OAK": "LV", "SD": "LAC"},
}


def normalize_team_id(provider: str, raw_team: object) -> str | None:
    """Return one of 32 canonical current-team IDs; never fuzzy match."""
    value = str(raw_team or "").strip().upper()
    if not value:
        return None
    value = PROVIDER_ALIASES.get(provider.lower(), {}).get(value, value)
    return value if value in NFL_TEAMS else None
