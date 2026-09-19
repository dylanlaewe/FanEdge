"""Deterministic historical, participation, role, and availability intelligence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Iterable

from football_data import NFLState, SEASON_TYPES, _identity, _number, fantasy_points
from opportunity import PlayerOpportunity
from player_identity import PlayerIdentity, normalize_name
from sleeper_api import Player
from team_identity import normalize_team_id


class Role(StrEnum):
    FEATURED = "FEATURED"
    STARTER = "STARTER"
    ROTATIONAL = "ROTATIONAL"
    LIMITED = "LIMITED"
    EMERGING = "EMERGING"
    DECLINING = "DECLINING"
    UNKNOWN = "UNKNOWN"


class RoleTrend(StrEnum):
    EXPANDING = "ROLE EXPANDING"
    STABLE = "ROLE STABLE"
    SHRINKING = "ROLE SHRINKING"
    INSUFFICIENT = "INSUFFICIENT DATA"


@dataclass(frozen=True)
class HistoricalBaseline:
    season: int
    games: int
    points_per_game: float | None
    targets_per_game: float | None
    touches_per_game: float | None
    attempts_per_game: float | None
    snap_share: float | None = None
    team: str | None = None

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class ParticipationSummary:
    games: int
    season_snap_share: float | None
    recent_snap_share: float | None
    season_offensive_snaps: float | None
    recent_offensive_snaps: float | None
    season_routes: int | None
    recent_routes: int | None
    route_participation: float | None
    trend: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class TeammateAvailabilityChange:
    teammate: str
    position: str
    previous_status: str | None
    current_status: str
    source: str = "nflverse weekly injury reports"

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class RoleProfile:
    role: str
    role_trend: str
    evidence_quality: str
    current_games: int
    current_weight: float
    historical: HistoricalBaseline | None
    participation: ParticipationSummary | None
    teammate_changes: tuple[TeammateAvailabilityChange, ...] = ()
    depth_rank: int | None = None
    evidence_dimensions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def current_evidence_weight(games: int, *, team_changed: bool = False) -> float:
    """Current data earns 25% per completed game; a team change weakens the prior."""
    current = min(1.0, max(0, games) / 4)
    if team_changed and games:
        current = min(1.0, current + (1.0 - current) * 0.5)
    return round(current, 2)


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_number(row[key]) for row in rows if row.get(key) not in (None, "")]
    return round(sum(values) / len(values), 1) if values else None


def build_historical_index(rows: Iterable[dict[str, str]], season: int, scoring: dict[str, Any]) -> dict[Any, HistoricalBaseline]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            valid = int(row.get("season", "")) == season and row.get("season_type") == "REG"
        except (TypeError, ValueError):
            continue
        name = row.get("player_display_name") or row.get("player_name")
        team = normalize_team_id("nflverse", row.get("team") or row.get("recent_team"))
        position = str(row.get("position") or "").upper()
        if not valid or not name or not team or position not in {"QB", "RB", "WR", "TE"}:
            continue
        enriched = dict(row)
        enriched["_points"] = fantasy_points(row, scoring, position)
        keys = [_identity(name, team, position)]
        if row.get("player_id"): keys.append(("gsis", str(row["player_id"])))
        for key in keys: grouped.setdefault(key, []).append(enriched)
    result: dict[Any, HistoricalBaseline] = {}
    for key, games in grouped.items():
        points = [row["_points"] for row in games if row["_points"] is not None]
        carries, receptions = _avg(games, "carries"), _avg(games, "receptions")
        result[key] = HistoricalBaseline(
            season, len(games), round(sum(points) / len(points), 1) if points else None,
            _avg(games, "targets"), None if carries is None and receptions is None else round((carries or 0) + (receptions or 0), 1),
            _avg(games, "attempts"), team=normalize_team_id("nflverse", games[-1].get("team") or games[-1].get("recent_team")),
        )
    return result


def add_historical_snap_shares(index: dict[Any, HistoricalBaseline], snap_rows: Iterable[dict[str, str]], season: int) -> dict[Any, HistoricalBaseline]:
    shares: dict[Any, list[float]] = {}
    for row in snap_rows:
        try: valid = int(row.get("season", "")) == season and row.get("game_type") == "REG"
        except (TypeError, ValueError): continue
        if not valid or row.get("offense_pct") in (None, ""): continue
        keys = [("pfr", str(row.get("pfr_player_id"))), _identity(str(row.get("player") or ""), str(row.get("team") or ""), str(row.get("position") or ""))]
        for key in keys: shares.setdefault(key, []).append(_number(row["offense_pct"]))
    # Stats use GSIS IDs, so name/team/position is the safe common key. PFR values
    # remain available for callers that resolve directly by PFR ID.
    result = dict(index)
    for key, values in shares.items():
        baseline = result.get(key)
        if baseline:
            result[key] = HistoricalBaseline(**{**asdict(baseline), "snap_share": round(sum(values)/len(values), 2)})
    return result


def build_participation_index(rows: Iterable[dict[str, str]], state: NFLState) -> dict[Any, ParticipationSummary]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        try: valid = int(row.get("season", "")) == state.season and int(row.get("week", "")) < state.week and row.get("game_type") == "REG"
        except (TypeError, ValueError): continue
        if not valid or not row.get("player") or not row.get("position") or not row.get("team"): continue
        keys = [("pfr", str(row["pfr_player_id"])), _identity(str(row["player"]), str(row["team"]), str(row["position"]))]
        for key in keys: grouped.setdefault(key, []).append(row)
    result: dict[Any, ParticipationSummary] = {}
    for key, games in grouped.items():
        games.sort(key=lambda x: int(x["week"]))
        shares = [_number(x["offense_pct"]) for x in games if x.get("offense_pct") not in (None, "")]
        snaps = [_number(x["offense_snaps"]) for x in games if x.get("offense_snaps") not in (None, "")]
        trend = RoleTrend.INSUFFICIENT.value
        if len(shares) >= 4:
            before, after = sum(shares[:-2]) / len(shares[:-2]), sum(shares[-2:]) / 2
            trend = RoleTrend.EXPANDING.value if after-before >= .12 else RoleTrend.SHRINKING.value if before-after >= .12 else RoleTrend.STABLE.value
        result[key] = ParticipationSummary(len(games), round(sum(shares)/len(shares), 2) if shares else None, round(sum(shares[-3:])/len(shares[-3:]), 2) if shares else None, round(sum(snaps)/len(snaps), 1) if snaps else None, round(sum(snaps[-3:])/len(snaps[-3:]), 1) if snaps else None, None, None, None, trend)
    return result


def build_availability_changes(rows: Iterable[dict[str, str]], state: NFLState) -> dict[tuple[str, str], tuple[TeammateAvailabilityChange, ...]]:
    unavailable = {"out", "doubtful", "injured reserve", "physically unable to perform"}
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        try: week = int(row.get("week", ""))
        except (TypeError, ValueError): continue
        team = normalize_team_id("nflverse", row.get("team")); position = str(row.get("position") or "").upper()
        if row.get("season_type") != "REG" or week > state.week or not team or position not in {"QB","RB","WR","TE"}: continue
        grouped.setdefault((team, position), []).append(row)
    result: dict[tuple[str, str], tuple[TeammateAvailabilityChange, ...]] = {}
    for key, values in grouped.items():
        by_player: dict[str, list[dict[str, str]]] = {}
        for row in values: by_player.setdefault(str(row.get("gsis_id") or row.get("full_name")), []).append(row)
        changes = []
        for player_rows in by_player.values():
            player_rows.sort(key=lambda x: int(x["week"])); current = player_rows[-1]
            current_status = str(current.get("report_status") or "").strip()
            previous_status = str(player_rows[-2].get("report_status") or "").strip() if len(player_rows) > 1 else None
            if current_status.lower() in unavailable and current_status != previous_status:
                changes.append(TeammateAvailabilityChange(str(current.get("full_name") or "Unknown teammate"), key[1], previous_status or None, current_status))
        if changes: result[key] = tuple(changes)
    return result


def build_depth_ranks(rows: Iterable[dict[str, str]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        if row.get("gsis_id") and row.get("pos_rank"):
            try: result[str(row["gsis_id"])] = int(row["pos_rank"])
            except (TypeError, ValueError): pass
    return result


def classify_role(position: str, opportunity: PlayerOpportunity | None, participation: ParticipationSummary | None) -> tuple[str, str]:
    games = max(opportunity.games if opportunity else 0, participation.games if participation else 0)
    trend = RoleTrend.INSUFFICIENT.value
    if games >= 4:
        trend = participation.trend if participation and participation.trend != RoleTrend.INSUFFICIENT.value else ({"RISING": RoleTrend.EXPANDING.value, "FALLING": RoleTrend.SHRINKING.value, "STEADY": RoleTrend.STABLE.value}.get(opportunity.usage_trend) if opportunity else None) or RoleTrend.INSUFFICIENT.value
    snap = participation.recent_snap_share if participation else None
    volume = opportunity.recent_attempts if position == "QB" and opportunity else opportunity.recent_touches if position == "RB" and opportunity else opportunity.recent_targets if opportunity else None
    if volume is None and snap is None: return Role.UNKNOWN.value, trend
    featured, starter, rotational = {"QB": (28,18,8), "RB": (18,11,6), "WR": (8,5,3), "TE": (7,4,2)}.get(position, (999,999,999))
    base = Role.FEATURED if (volume or 0) >= featured or (snap or 0) >= .75 else Role.STARTER if (volume or 0) >= starter or (snap or 0) >= .55 else Role.ROTATIONAL if (volume or 0) >= rotational or (snap or 0) >= .30 else Role.LIMITED
    if games >= 4 and trend == RoleTrend.EXPANDING.value and base not in {Role.FEATURED, Role.STARTER}: base = Role.EMERGING
    elif games >= 4 and trend == RoleTrend.SHRINKING.value and base != Role.LIMITED: base = Role.DECLINING
    return base.value, trend


def build_role_profiles(players: Iterable[Player], opportunities: dict[str, PlayerOpportunity], identities: dict[str, PlayerIdentity], historical_index: dict[Any, HistoricalBaseline], participation_index: dict[Any, ParticipationSummary], availability: dict[tuple[str,str], tuple[TeammateAvailabilityChange,...]], depth_ranks: dict[str,int], historical_participation: dict[Any, ParticipationSummary] | None = None) -> dict[str, RoleProfile]:
    profiles = {}
    for player in players:
        identity = identities.get(player.player_id)
        historical = historical_index.get(("gsis", identity.gsis_id)) if identity and identity.gsis_id else historical_index.get(_identity(player.name, player.team, player.position))
        prior_participation = (historical_participation or {}).get(("pfr", identity.pfr_id)) if identity and identity.pfr_id else None
        if historical and prior_participation and prior_participation.season_snap_share is not None:
            historical = HistoricalBaseline(**{**asdict(historical), "snap_share": prior_participation.season_snap_share})
        participation = participation_index.get(("pfr", identity.pfr_id)) if identity and identity.pfr_id else participation_index.get(_identity(player.name, player.team, player.position))
        opportunity = opportunities.get(player.player_id)
        role, trend = classify_role(player.position, opportunity, participation)
        games = max(opportunity.games if opportunity else 0, participation.games if participation else 0)
        team_changed = bool(historical and historical.team and historical.team != normalize_team_id("sleeper", player.team))
        weight = current_evidence_weight(games, team_changed=team_changed)
        quality = "HIGH" if games >= 4 else "MODERATE" if games >= 2 or (historical and historical.games >= 4) else "LOW"
        teammate = tuple(change for change in availability.get((normalize_team_id("sleeper", player.team) or player.team, player.position), ()) if normalize_name(change.teammate) != normalize_name(player.name))
        dimensions = (
            f"SAMPLE_SIZE:{games}_CURRENT_GAMES",
            "RECENCY:CURRENT_SEASON",
            "SOURCE_RELIABILITY:STRUCTURED_NFLVERSE",
            f"ROLE_RELEVANCE:{'POSITION_SPECIFIC' if player.position in {'QB','RB','WR','TE'} else 'UNKNOWN'}",
            f"BASIS:{'CURRENT' if weight == 1 else 'MIXED' if historical else 'CURRENT_LIMITED'}",
        )
        profiles[player.player_id] = RoleProfile(role, trend, quality, games, weight, historical, participation, teammate, depth_ranks.get(identity.gsis_id) if identity and identity.gsis_id else None, dimensions)
    return profiles
