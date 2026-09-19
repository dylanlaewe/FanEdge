"""Provider-neutral weekly football context for FanEdge."""

from __future__ import annotations

import csv
import gzip
import io
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

from sleeper_api import Player, Roster
from player_identity import PlayerIdentity, normalize_name
from team_identity import NFL_TEAMS, normalize_team_id


SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv.gz"
PLAYERS_URL = "https://github.com/nflverse/nflverse-data/releases/download/players/players.csv"
EASTERN = ZoneInfo("America/New_York")
SEASON_TYPES = {"pre": "PRE", "regular": "REG", "post": "POST"}
STAT_SCORING_KEYS = {
    "pass_yd": "passing_yards",
    "pass_td": "passing_tds",
    "pass_int": "passing_interceptions",
    "pass_2pt": "passing_2pt_conversions",
    "rush_yd": "rushing_yards",
    "rush_td": "rushing_tds",
    "rush_2pt": "rushing_2pt_conversions",
    "rec": "receptions",
    "rec_yd": "receiving_yards",
    "rec_td": "receiving_tds",
    "rec_2pt": "receiving_2pt_conversions",
}


class FootballDataError(RuntimeError):
    """Raised when a football data provider cannot return usable data."""


@dataclass(frozen=True)
class NFLState:
    season: int
    week: int
    season_type: str


@dataclass(frozen=True)
class WeeklyGame:
    team: str
    opponent: str
    is_home: bool
    kickoff: datetime | None


class ScheduleStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    BYE = "BYE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class WeeklySchedule:
    games: dict[str, WeeklyGame]
    complete: bool
    issues: tuple[str, ...] = ()

    def get(self, team: str, default: Any = None) -> WeeklyGame | Any:
        canonical = normalize_team_id("sleeper", team)
        return self.games.get(canonical, default) if canonical else default

    def __getitem__(self, team: str) -> WeeklyGame:
        canonical = normalize_team_id("sleeper", team)
        if not canonical:
            raise KeyError(team)
        return self.games[canonical]

    def status_for(self, team: str) -> ScheduleStatus:
        canonical = normalize_team_id("sleeper", team)
        if not canonical or not self.complete:
            return ScheduleStatus.UNKNOWN
        return ScheduleStatus.SCHEDULED if canonical in self.games else ScheduleStatus.BYE

    def __bool__(self) -> bool:
        return bool(self.games)


@dataclass(frozen=True)
class GamePerformance:
    week: int
    fantasy_points: float


@dataclass(frozen=True)
class PerformanceSummary:
    games_played: int
    season_average: float
    recent_average: float
    trend: str


@dataclass(frozen=True)
class PlayerWeeklyContext:
    player_id: str
    name: str
    position: str
    team: str
    opponent: str | None
    home_away: str | None
    kickoff: datetime | None
    is_bye: bool | None
    status: str | None
    injury_body_part: str | None
    recent_stats: tuple[GamePerformance, ...]
    season_stats: PerformanceSummary | None
    schedule_status: str = ScheduleStatus.UNKNOWN.value

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kickoff"] = self.kickoff.isoformat() if self.kickoff else None
        return value


class NflverseClient:
    """Read schedule and completed-game statistics from nflverse releases."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def _get(self, url: str) -> bytes:
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            raise FootballDataError("Weekly NFL data is temporarily unavailable.") from exc

    def get_schedule_rows(self) -> list[dict[str, str]]:
        content = self._get(SCHEDULE_URL).decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(content)))

    def get_stat_rows(self, season: int) -> list[dict[str, str]]:
        try:
            content = gzip.decompress(self._get(STATS_URL.format(season=season))).decode("utf-8-sig")
        except (gzip.BadGzipFile, UnicodeDecodeError) as exc:
            raise FootballDataError("Weekly player data was unreadable.") from exc
        return list(csv.DictReader(io.StringIO(content)))

    def get_player_rows(self) -> list[dict[str, str]]:
        content = self._get(PLAYERS_URL).decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(content)))


def normalize_nfl_state(raw: Any) -> NFLState:
    if not isinstance(raw, dict):
        raise FootballDataError("NFL state data was malformed.")
    try:
        season = int(raw["season"])
        week = int(raw["week"])
        season_type = str(raw["season_type"]).lower()
    except (KeyError, TypeError, ValueError) as exc:
        raise FootballDataError("NFL state data was incomplete.") from exc
    if season < 2000 or week < 0 or season_type not in SEASON_TYPES:
        raise FootballDataError("NFL state data contained unsupported values.")
    return NFLState(season=season, week=week, season_type=season_type)


def _kickoff(row: dict[str, str]) -> datetime | None:
    gameday, gametime = row.get("gameday"), row.get("gametime")
    if not gameday or not gametime:
        return None
    try:
        return datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M").replace(tzinfo=EASTERN)
    except ValueError:
        return None


def build_weekly_schedule(rows: Iterable[dict[str, str]], state: NFLState) -> WeeklySchedule:
    games: dict[str, WeeklyGame] = {}
    issues: list[str] = []
    matched_rows = 0
    expected_type = SEASON_TYPES[state.season_type]
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            matches = int(row.get("season", "")) == state.season and int(row.get("week", "")) == state.week
        except (TypeError, ValueError):
            continue
        if not matches or row.get("game_type") != expected_type:
            continue
        matched_rows += 1
        away = normalize_team_id("nflverse", row.get("away_team"))
        home = normalize_team_id("nflverse", row.get("home_team"))
        if not away or not home:
            issues.append("unrecognized team identity")
            continue
        if away == home or away in games or home in games:
            issues.append("duplicate or impossible team assignment")
            continue
        kickoff = _kickoff(row)
        games[away] = WeeklyGame(away, home, False, kickoff)
        games[home] = WeeklyGame(home, away, True, kickoff)
    game_count = len(games) // 2
    represented = set(games)
    complete = (
        matched_rows == game_count
        and 12 <= game_count <= 16
        and len(games) % 2 == 0
        and represented <= NFL_TEAMS
        and not issues
    )
    if not complete and not issues:
        issues.append("weekly schedule is incomplete")
    return WeeklySchedule(games, complete, tuple(issues))


def normalize_player_status(metadata: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(metadata, dict):
        return None, None
    injury = metadata.get("injury_status")
    roster_status = metadata.get("status")
    status = str(injury).strip() if injury else None
    if not status and roster_status and str(roster_status).lower() != "active":
        status = str(roster_status).strip()
    body_part = metadata.get("injury_body_part")
    return status or None, str(body_part).strip() if body_part else None


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fantasy_points(row: dict[str, Any], scoring: dict[str, Any], position: str) -> float | None:
    """Calculate points only when all non-zero offensive scoring keys are supported."""
    offensive_keys = {
        key for key, value in scoring.items()
        if _number(value)
        and (
            key.startswith(("pass_", "rush_", "rec_", "bonus_pass_", "bonus_rush_", "bonus_rec_"))
            or key in {"fum", "fum_lost"}
        )
    }
    supported = set(STAT_SCORING_KEYS) | {"fum_lost"}
    if offensive_keys - supported:
        return None
    total = sum(_number(scoring.get(key)) * _number(row.get(column)) for key, column in STAT_SCORING_KEYS.items())
    fumbles_lost = sum(_number(row.get(key)) for key in ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"))
    total += _number(scoring.get("fum_lost")) * fumbles_lost
    return round(total, 2)


def _identity(name: str, team: str, position: str) -> tuple[str, str, str]:
    return normalize_name(name), team.upper(), position.upper()


def build_performance_index(
    rows: Iterable[dict[str, str]], state: NFLState, scoring: dict[str, Any]
) -> dict[Any, list[GamePerformance]]:
    index: dict[Any, list[GamePerformance]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            season = int(row.get("season", ""))
            week = int(row.get("week", ""))
        except (TypeError, ValueError):
            continue
        if season != state.season or week >= state.week or row.get("season_type") != SEASON_TYPES[state.season_type]:
            continue
        name = row.get("player_display_name") or row.get("player_name")
        team, position = row.get("team") or row.get("recent_team"), row.get("position")
        if not name or not team or not position:
            continue
        points = fantasy_points(row, scoring, position)
        if points is None:
            continue
        performance = GamePerformance(week, points)
        index.setdefault(_identity(name, team, position), []).append(performance)
        if row.get("player_id"):
            index.setdefault(("gsis", str(row["player_id"])), []).append(performance)
    for values in index.values():
        values.sort(key=lambda item: item.week)
    return index


def summarize_performance(games: Iterable[GamePerformance]) -> PerformanceSummary | None:
    values = list(games)
    if not values:
        return None
    season_average = sum(item.fantasy_points for item in values) / len(values)
    recent = values[-3:]
    recent_average = sum(item.fantasy_points for item in recent) / len(recent)
    difference = recent_average - season_average
    trend = "up" if difference >= 2 else "down" if difference <= -2 else "steady"
    return PerformanceSummary(len(values), round(season_average, 1), round(recent_average, 1), trend)


def build_player_weekly_contexts(
    roster: Roster,
    metadata: dict[str, dict[str, Any]],
    schedule: WeeklySchedule | dict[str, WeeklyGame],
    performances: dict[Any, list[GamePerformance]],
    *,
    identities: dict[str, PlayerIdentity] | None = None,
) -> dict[str, PlayerWeeklyContext]:
    contexts: dict[str, PlayerWeeklyContext] = {}
    for player in (*roster.starters, *roster.bench):
        game = schedule.get(player.team)
        schedule_status = schedule.status_for(player.team) if isinstance(schedule, WeeklySchedule) else (ScheduleStatus.SCHEDULED if game else ScheduleStatus.UNKNOWN)
        player_metadata = metadata.get(player.player_id)
        status, body_part = normalize_player_status(player_metadata)
        identity = (identities or {}).get(player.player_id)
        games = tuple(
            performances.get(("gsis", identity.gsis_id), [])
            if identity and identity.gsis_id
            else performances.get(_identity(player.name, player.team, player.position), [])
        )
        contexts[player.player_id] = PlayerWeeklyContext(
            player_id=player.player_id,
            name=player.name,
            position=player.position,
            team=player.team,
            opponent=game.opponent if game else None,
            home_away="home" if game and game.is_home else "away" if game else None,
            kickoff=game.kickoff if game else None,
            is_bye=schedule_status == ScheduleStatus.BYE,
            status=status,
            injury_body_part=body_part,
            recent_stats=games[-3:],
            season_stats=summarize_performance(games),
            schedule_status=schedule_status.value,
        )
    return contexts
