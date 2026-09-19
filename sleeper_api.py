"""Small, defensive client for Sleeper's public fantasy football API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests


BASE_URL = "https://api.sleeper.app/v1"


class SleeperAPIError(RuntimeError):
    """Raised when Sleeper cannot provide a usable response."""


@dataclass(frozen=True)
class Player:
    player_id: str
    name: str
    position: str
    team: str


@dataclass(frozen=True)
class Roster:
    starters: list[Player]
    bench: list[Player]


class SleeperClient:
    """HTTP client with predictable errors and response validation."""

    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, path: str) -> Any:
        try:
            response = self.session.get(f"{BASE_URL}{path}", timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.Timeout as exc:
            raise SleeperAPIError("Sleeper took too long to respond. Please try again.") from exc
        except requests.RequestException as exc:
            raise SleeperAPIError("Could not connect to Sleeper. Please try again shortly.") from exc
        except ValueError as exc:
            raise SleeperAPIError("Sleeper returned an unreadable response.") from exc

    def get_user(self, username: str) -> dict[str, Any]:
        data = self._get(f"/user/{quote(username.strip(), safe='')}")
        if not isinstance(data, dict) or not data.get("user_id"):
            raise SleeperAPIError(f'No Sleeper user was found for "{username}".')
        return data

    def get_leagues(self, user_id: str, season: int) -> list[dict[str, Any]]:
        data = self._get(f"/user/{user_id}/leagues/nfl/{season}")
        if not isinstance(data, list):
            raise SleeperAPIError("Sleeper returned malformed league data.")
        return [league for league in data if isinstance(league, dict) and league.get("league_id")]

    def get_rosters(self, league_id: str) -> list[dict[str, Any]]:
        data = self._get(f"/league/{league_id}/rosters")
        if not isinstance(data, list):
            raise SleeperAPIError("Sleeper returned malformed roster data.")
        return [roster for roster in data if isinstance(roster, dict)]

    def get_players(self) -> dict[str, dict[str, Any]]:
        data = self._get("/players/nfl")
        if not isinstance(data, dict):
            raise SleeperAPIError("Sleeper returned malformed player data.")
        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def get_nfl_state(self) -> dict[str, Any]:
        data = self._get("/state/nfl")
        if not isinstance(data, dict):
            raise SleeperAPIError("Sleeper could not provide the current NFL week.")
        return data


def find_user_roster(rosters: list[dict[str, Any]], user_id: str) -> dict[str, Any]:
    """Find a user's roster while tolerating numeric/string owner IDs."""
    for roster in rosters:
        if str(roster.get("owner_id", "")) == str(user_id):
            return roster
    raise SleeperAPIError("Your roster could not be found in this league.")


def _player_from_metadata(player_id: str, players: dict[str, dict[str, Any]]) -> Player:
    metadata = players.get(str(player_id), {})
    full_name = metadata.get("full_name")
    if not full_name:
        full_name = " ".join(
            part for part in (metadata.get("first_name"), metadata.get("last_name")) if part
        )
    return Player(
        player_id=str(player_id),
        name=full_name or f"Unknown player ({player_id})",
        position=metadata.get("position") or "—",
        team=metadata.get("team") or "FA",
    )


def build_roster(roster: dict[str, Any], players: dict[str, dict[str, Any]]) -> Roster:
    """Convert Sleeper IDs into display-ready starters and bench players."""
    raw_players = roster.get("players") or []
    raw_starters = roster.get("starters") or []
    if not isinstance(raw_players, list) or not isinstance(raw_starters, list):
        raise SleeperAPIError("Sleeper returned malformed player information for this roster.")

    player_ids = [str(player_id) for player_id in raw_players if player_id is not None]
    starter_ids = [str(player_id) for player_id in raw_starters if player_id not in (None, "0")]
    starter_set = set(starter_ids)
    starters = [_player_from_metadata(player_id, players) for player_id in starter_ids]
    bench = [_player_from_metadata(player_id, players) for player_id in player_ids if player_id not in starter_set]
    return Roster(starters=starters, bench=bench)
