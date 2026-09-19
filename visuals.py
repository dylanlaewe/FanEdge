"""Centralized, lightweight visual identity helpers for FanEdge."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

from player_identity import PlayerIdentity
from team_identity import normalize_team_id


ESPN_HEADSHOT_URL = "https://a.espncdn.com/i/headshots/nfl/players/full/{espn_id}.png"
ESPN_TEAM_LOGO_URL = "https://a.espncdn.com/i/teamlogos/nfl/500/{team}.png"

TEAM_NAMES = {
    "ARI":"Arizona Cardinals","ATL":"Atlanta Falcons","BAL":"Baltimore Ravens","BUF":"Buffalo Bills","CAR":"Carolina Panthers","CHI":"Chicago Bears","CIN":"Cincinnati Bengals","CLE":"Cleveland Browns","DAL":"Dallas Cowboys","DEN":"Denver Broncos","DET":"Detroit Lions","GB":"Green Bay Packers","HOU":"Houston Texans","IND":"Indianapolis Colts","JAX":"Jacksonville Jaguars","KC":"Kansas City Chiefs","LAC":"Los Angeles Chargers","LAR":"Los Angeles Rams","LV":"Las Vegas Raiders","MIA":"Miami Dolphins","MIN":"Minnesota Vikings","NE":"New England Patriots","NO":"New Orleans Saints","NYG":"New York Giants","NYJ":"New York Jets","PHI":"Philadelphia Eagles","PIT":"Pittsburgh Steelers","SEA":"Seattle Seahawks","SF":"San Francisco 49ers","TB":"Tampa Bay Buccaneers","TEN":"Tennessee Titans","WAS":"Washington Commanders",
}
TEAM_COLORS = {
    "ARI":"#97233F","ATL":"#A71930","BAL":"#241773","BUF":"#00338D","CAR":"#0085CA","CHI":"#0B162A","CIN":"#FB4F14","CLE":"#311D00","DAL":"#041E42","DEN":"#FB4F14","DET":"#0076B6","GB":"#203731","HOU":"#03202F","IND":"#002C5F","JAX":"#006778","KC":"#E31837","LAC":"#0080C6","LAR":"#003594","LV":"#000000","MIA":"#008E97","MIN":"#4F2683","NE":"#002244","NO":"#D3BC8D","NYG":"#0B2265","NYJ":"#125740","PHI":"#004C54","PIT":"#FFB612","SEA":"#69BE28","SF":"#AA0000","TB":"#D50A0A","TEN":"#4B92DB","WAS":"#5A1414",
}


@dataclass(frozen=True)
class TeamVisual:
    canonical_team: str
    display_name: str
    abbreviation: str
    logo_url: str | None
    color: str


def team_visual(raw_team: Any) -> TeamVisual | None:
    team = normalize_team_id("sleeper", raw_team)
    if not team or team not in TEAM_NAMES:
        return None
    return TeamVisual(team, TEAM_NAMES[team], team, ESPN_TEAM_LOGO_URL.format(team=team.lower()), TEAM_COLORS.get(team, "#52606d"))


def resolve_player_image(identity: PlayerIdentity | None) -> str | None:
    """Return a deterministic public ESPN CDN URL when an ESPN identity exists."""
    if identity and identity.espn_id:
        return ESPN_HEADSHOT_URL.format(espn_id=identity.espn_id)
    return None


def initials(name: str) -> str:
    words = [word for word in name.split() if word]
    return "".join(word[0] for word in words[:2]).upper() or "?"


def player_visual(identity: PlayerIdentity | None, name: str, position: str, team: str, *, size: str = "large") -> str:
    visual = team_visual(team)
    image = resolve_player_image(identity)
    team_code = visual.abbreviation if visual else (team or "FA")
    fallback = f'<span class="fe-player-fallback" style="--team-color:{escape(visual.color if visual else "#52606d")}"><b>{escape(initials(name))}</b><small>{escape(position)}</small></span>'
    media = f'<img class="fe-player-image {size}" src="{escape(image)}" alt="" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'grid\'">{fallback}' if image else fallback
    return f'<span class="fe-player-visual {size}" title="{escape(name)}">{media}</span>'


def team_mark(team: str) -> str:
    visual = team_visual(team)
    if not visual:
        return f'<span class="fe-team-mark unknown">{escape(team or "—")}</span>'
    return f'<span class="fe-team-mark" style="--team-color:{visual.color}"><img src="{visual.logo_url}" alt="" loading="lazy" onerror="this.style.display=\'none\'">{visual.abbreviation}</span>'
