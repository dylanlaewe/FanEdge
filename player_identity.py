"""Deterministic cross-provider player identity resolution."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str) -> str:
    """Normalize punctuation, accents, spacing, and common suffix differences."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", ascii_name.lower())
    while tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    return "".join(tokens)


@dataclass(frozen=True)
class PlayerIdentity:
    sleeper_id: str
    gsis_id: str | None
    pfr_id: str | None
    full_name: str
    normalized_name: str
    position: str
    nfl_team: str
    resolution: str


class PlayerIdentityResolver:
    """Resolve Sleeper metadata to nflverse without broad fuzzy matching."""

    def __init__(self, nflverse_players: Iterable[dict[str, Any]]) -> None:
        self._by_gsis: dict[str, list[dict[str, Any]]] = {}
        self._by_espn: dict[str, list[dict[str, Any]]] = {}
        self._by_exact: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._by_name_position: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in nflverse_players:
            if not isinstance(row, dict):
                continue
            name = str(row.get("display_name") or "").strip()
            position = str(row.get("position") or "").upper()
            team = str(row.get("latest_team") or "").upper()
            normalized = normalize_name(name)
            if not normalized or not position:
                continue
            if row.get("gsis_id"):
                self._by_gsis.setdefault(str(row["gsis_id"]), []).append(row)
            if row.get("espn_id"):
                self._by_espn.setdefault(str(row["espn_id"]), []).append(row)
            self._by_exact.setdefault((normalized, position, team), []).append(row)
            self._by_name_position.setdefault((normalized, position), []).append(row)

    @staticmethod
    def _unique(index: dict[Any, list[dict[str, Any]]], key: Any) -> dict[str, Any] | None:
        matches = index.get(key, [])
        return matches[0] if len(matches) == 1 else None

    def resolve(self, sleeper_id: str, metadata: dict[str, Any]) -> PlayerIdentity:
        name = str(metadata.get("full_name") or " ".join(
            str(metadata.get(key) or "") for key in ("first_name", "last_name")
        )).strip()
        position = str(metadata.get("position") or "").upper()
        team = str(metadata.get("team") or "").upper()
        normalized = normalize_name(name)

        if position == "DEF" and team:
            return PlayerIdentity(
                str(sleeper_id), None, None, name or team, normalized,
                position, team, "team_defense",
            )

        match: dict[str, Any] | None = None
        method = "unresolved"
        for field, index, label in (
            ("gsis_id", self._by_gsis, "gsis_id"),
            ("espn_id", self._by_espn, "espn_id"),
        ):
            value = metadata.get(field)
            if value not in (None, ""):
                match = self._unique(index, str(value))
                if match:
                    method = label
                    break
        if not match and normalized and position:
            match = self._unique(self._by_exact, (normalized, position, team))
            method = "name_position_team" if match else method
        if not match and normalized and position:
            match = self._unique(self._by_name_position, (normalized, position))
            method = "name_position" if match else method

        return PlayerIdentity(
            sleeper_id=str(sleeper_id),
            gsis_id=str(match.get("gsis_id")) if match and match.get("gsis_id") else None,
            pfr_id=str(match.get("pfr_id")) if match and match.get("pfr_id") else None,
            full_name=name,
            normalized_name=normalized,
            position=position,
            nfl_team=team,
            resolution=method,
        )

    def resolve_all(self, players: dict[str, dict[str, Any]]) -> dict[str, PlayerIdentity]:
        return {str(player_id): self.resolve(str(player_id), metadata) for player_id, metadata in players.items()}
