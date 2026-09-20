"""Normalized, source-bounded NFL news ingestion and deterministic fact extraction."""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, Iterable

import requests

from player_identity import PlayerIdentity, normalize_name
from sleeper_api import Player
from team_identity import normalize_team_id


ESPN_NFL_RSS_URL = "https://www.espn.com/espn/rss/nfl/news"
USER_AGENT = "FanEdge/1.0 (+https://github.com/dylanlaewe/FanEdge)"
MAX_FEED_BYTES = 1_500_000


class NewsError(RuntimeError):
    """Raised when a provider cannot return a safe, usable feed batch."""


class NewsCategory(StrEnum):
    INJURY = "INJURY"
    AVAILABILITY = "AVAILABILITY"
    ROLE = "ROLE"
    DEPTH_CHART = "DEPTH_CHART"
    TRANSACTION = "TRANSACTION"
    COACH_COMMENT = "COACH_COMMENT"
    PRACTICE = "PRACTICE"
    SUSPENSION = "SUSPENSION"
    OTHER = "OTHER"


class NewsFactType(StrEnum):
    PLAYER_STATUS_CHANGE = "PLAYER_STATUS_CHANGE"
    PRACTICE_STATUS = "PRACTICE_STATUS"
    ROLE_COMMENT = "ROLE_COMMENT"
    DEPTH_CHART_CHANGE = "DEPTH_CHART_CHANGE"
    TRANSACTION = "TRANSACTION"
    TEAMMATE_AVAILABILITY = "TEAMMATE_AVAILABILITY"


class Freshness(StrEnum):
    BREAKING = "BREAKING"
    RECENT = "RECENT"
    STALE = "STALE"


@dataclass(frozen=True)
class NewsEntity:
    player_id: str
    name: str
    position: str
    team: str
    resolution: str


@dataclass(frozen=True)
class NewsItem:
    id: str
    source: str
    published_at: str
    headline: str
    summary: str
    url: str
    teams: tuple[str, ...] = ()
    player_entities: tuple[NewsEntity, ...] = ()
    category: str = NewsCategory.OTHER.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NewsFact:
    fact_id: str
    subject_player_id: str
    subject_name: str
    subject_position: str
    team: str
    fact_type: str
    old_state: str | None
    new_state: str
    related_player_id: str | None
    confidence: str
    source_item_ids: tuple[str, ...]
    sources: tuple[str, ...]
    urls: tuple[str, ...]
    published_at: str
    evidence_text: str
    freshness: str
    authority: str
    explicit: bool = True
    superseded_fact_ids: tuple[str, ...] = ()
    provider_fresh: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NewsFact":
        values = dict(value)
        for key in ("source_item_ids", "sources", "urls", "superseded_fact_ids"):
            values[key] = tuple(values.get(key) or ())
        return cls(**values)


@dataclass(frozen=True)
class NewsAudit:
    fetched: int
    player_resolved: int
    actionable_facts: int
    unresolved: int
    rejected: int
    rejection_reasons: tuple[tuple[str, int], ...]


TEAM_ALIASES = {
    "ARI": ("Arizona Cardinals", "Cardinals"), "ATL": ("Atlanta Falcons", "Falcons"),
    "BAL": ("Baltimore Ravens", "Ravens"), "BUF": ("Buffalo Bills", "Bills"),
    "CAR": ("Carolina Panthers", "Panthers"), "CHI": ("Chicago Bears", "Bears"),
    "CIN": ("Cincinnati Bengals", "Bengals"), "CLE": ("Cleveland Browns", "Browns"),
    "DAL": ("Dallas Cowboys", "Cowboys"), "DEN": ("Denver Broncos", "Broncos"),
    "DET": ("Detroit Lions", "Lions"), "GB": ("Green Bay Packers", "Packers"),
    "HOU": ("Houston Texans", "Texans"), "IND": ("Indianapolis Colts", "Colts"),
    "JAX": ("Jacksonville Jaguars", "Jaguars", "Jags"), "KC": ("Kansas City Chiefs", "Chiefs"),
    "LAC": ("Los Angeles Chargers", "Chargers"), "LAR": ("Los Angeles Rams", "Rams"),
    "LV": ("Las Vegas Raiders", "Raiders"), "MIA": ("Miami Dolphins", "Dolphins"),
    "MIN": ("Minnesota Vikings", "Vikings"), "NE": ("New England Patriots", "Patriots"),
    "NO": ("New Orleans Saints", "Saints"), "NYG": ("New York Giants", "Giants"),
    "NYJ": ("New York Jets", "Jets"), "PHI": ("Philadelphia Eagles", "Eagles"),
    "PIT": ("Pittsburgh Steelers", "Steelers"), "SEA": ("Seattle Seahawks", "Seahawks"),
    "SF": ("San Francisco 49ers", "49ers", "Niners"), "TB": ("Tampa Bay Buccaneers", "Buccaneers", "Bucs"),
    "TEN": ("Tennessee Titans", "Titans"), "WAS": ("Washington Commanders", "Commanders"),
}


def _utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(UTC)
    return result.astimezone(UTC) if result.tzinfo else result.replace(tzinfo=UTC)


def freshness_bucket(published_at: str, *, now: datetime | None = None) -> str:
    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    age_hours = max(0.0, (_utc(now) - _utc(published)).total_seconds() / 3600)
    return Freshness.BREAKING.value if age_hours <= 2 else Freshness.RECENT.value if age_hours <= 48 else Freshness.STALE.value


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _category(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("practice", "participant", "dnp")):
        return NewsCategory.PRACTICE.value
    if any(term in lowered for term in ("injur", "questionable", "doubtful", "ruled out")):
        return NewsCategory.INJURY.value
    if "suspend" in lowered:
        return NewsCategory.SUSPENSION.value
    if any(term in lowered for term in ("signed", "released", "waived", "activated", "injured reserve", "traded")):
        return NewsCategory.TRANSACTION.value
    if any(term in lowered for term in ("depth chart", "named starter")):
        return NewsCategory.DEPTH_CHART.value
    if any(term in lowered for term in ("touches", "workload", "role", "snaps")):
        return NewsCategory.ROLE.value
    return NewsCategory.OTHER.value


def detect_teams(text: str) -> tuple[str, ...]:
    found = []
    for team, aliases in TEAM_ALIASES.items():
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?:'s|’s)?(?!\w)", text, re.I) for alias in aliases):
            found.append(team)
    return tuple(found)


class ESPNNewsClient:
    """Fetch ESPN's explicitly published NFL RSS feed as one bounded batch."""

    def __init__(self, timeout: float = 10.0, session: requests.Session | None = None) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch(self, *, now: datetime | None = None) -> list[NewsItem]:
        try:
            response = self.session.get(ESPN_NFL_RSS_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9"}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise NewsError("Current NFL reporting could not be refreshed.") from exc
        content = response.content
        if len(content) > MAX_FEED_BYTES:
            raise NewsError("The NFL news feed exceeded the safe batch size.")
        return parse_espn_rss(content, now=now)


def parse_espn_rss(content: bytes | str, *, now: datetime | None = None) -> list[NewsItem]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise NewsError("The NFL news feed returned unreadable XML.") from exc
    items: list[NewsItem] = []
    for element in root.findall(".//item"):
        headline = _clean_text(element.findtext("title") or "")
        summary = _clean_text(element.findtext("description") or "")
        url = (element.findtext("link") or "").strip()
        raw_date = (element.findtext("pubDate") or "").strip()
        if not headline or not url or not raw_date or not url.startswith("https://"):
            continue
        try:
            published = parsedate_to_datetime(raw_date)
            published = _utc(published).isoformat(timespec="seconds")
        except (TypeError, ValueError, OverflowError):
            continue
        guid = _clean_text(element.findtext("guid") or "")
        item_id = hashlib.sha256((guid or url).encode()).hexdigest()[:24]
        text = f"{headline} {summary}"
        items.append(NewsItem(item_id, "ESPN", published, headline, summary, url, detect_teams(text), (), _category(text)))
    if not items:
        raise NewsError("The NFL news feed contained no usable stories.")
    items.sort(key=lambda item: item.published_at, reverse=True)
    return items


class NewsEntityResolver:
    """Resolve full names exactly; permit last names only with unique team context."""

    def __init__(self, players: Iterable[Player], identities: dict[str, PlayerIdentity] | None = None) -> None:
        self.players = tuple(player for player in players if player.position in {"QB", "RB", "WR", "TE", "K"})
        self.identities = identities or {}

    @staticmethod
    def _name_pattern(name: str) -> re.Pattern[str]:
        tokens = re.findall(r"[A-Za-z0-9]+", name)
        return re.compile(r"(?<!\w)" + r"[\s.'’-]+".join(re.escape(token) for token in tokens) + r"(?!\w)", re.I)

    def resolve_item(self, item: NewsItem) -> NewsItem:
        text = f"{item.headline} {item.summary}"
        resolved: dict[str, NewsEntity] = {}
        by_normalized: dict[str, list[Player]] = {}
        for player in self.players:
            by_normalized.setdefault(normalize_name(player.name), []).append(player)
        for player in sorted(self.players, key=lambda value: len(value.name), reverse=True):
            if len(by_normalized.get(normalize_name(player.name), ())) != 1:
                continue
            if self._name_pattern(player.name).search(text):
                identity = self.identities.get(player.player_id)
                method = "provider_identity_exact_name" if identity and identity.resolution != "unresolved" else "exact_normalized_name"
                resolved[player.player_id] = NewsEntity(player.player_id, player.name, player.position, player.team, method)
        # A short last-name mention is accepted only inside one explicit team and
        # only when that team has exactly one matching active player.
        if len(item.teams) == 1:
            team = item.teams[0]
            team_players = [player for player in self.players if normalize_team_id("sleeper", player.team) == team]
            by_last: dict[str, list[Player]] = {}
            for player in team_players:
                last = re.findall(r"[A-Za-z0-9]+", player.name)
                if last:
                    by_last.setdefault(normalize_name(last[-1]), []).append(player)
            for last, candidates in by_last.items():
                if len(candidates) != 1 or candidates[0].player_id in resolved:
                    continue
                raw_last = re.findall(r"[A-Za-z0-9]+", candidates[0].name)[-1]
                if re.search(rf"(?<!\w){re.escape(raw_last)}(?:'s|’s)?(?!\w)", text, re.I):
                    player = candidates[0]
                    resolved[player.player_id] = NewsEntity(player.player_id, player.name, player.position, player.team, "team_assisted_unique_last_name")
        return replace(item, player_entities=tuple(sorted(resolved.values(), key=lambda value: value.player_id)))

    def resolve_all(self, items: Iterable[NewsItem]) -> list[NewsItem]:
        return [self.resolve_item(item) for item in items]


def _excerpt(item: NewsItem, entity: NewsEntity) -> str:
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", f"{item.headline}. {item.summary}".strip())
    full_name = NewsEntityResolver._name_pattern(entity.name)
    for sentence in sentences:
        if full_name.search(sentence):
            return sentence[:240]
    last = re.findall(r"[A-Za-z0-9]+", entity.name)[-1]
    for sentence in sentences:
        if re.search(rf"(?<!\w){re.escape(last)}(?!\w)", sentence, re.I):
            return sentence[:240]
    return item.headline[:240]


def _local_evidence(item: NewsItem, entity: NewsEntity) -> str:
    """Return the clause nearest the entity to avoid cross-player attribution."""
    evidence = _excerpt(item, entity)
    name_pattern = NewsEntityResolver._name_pattern(entity.name)
    match = name_pattern.search(evidence)
    if not match:
        last = re.findall(r"[A-Za-z0-9]+", entity.name)[-1]
        match = re.search(rf"(?<!\w){re.escape(last)}(?:'s|’s)?(?!\w)", evidence, re.I)
    if not match:
        return ""
    return evidence[max(0, match.start() - 24):min(len(evidence), match.end() + 100)]


def _fact_id(entity: NewsEntity, fact_type: str, state: str, published_at: str, item_id: str) -> str:
    raw = f"{entity.player_id}|{fact_type}|{state}|{published_at}|{item_id}"
    return "nf1:" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def _make_fact(item: NewsItem, entity: NewsEntity, fact_type: NewsFactType, state: str, *, confidence: str = "HIGH", explicit: bool = True) -> NewsFact:
    authority = "REPUTABLE_REPORTING" if item.source == "ESPN" else "OFFICIAL" if item.source in {"NFL", "NFL TEAM"} else "OTHER"
    return NewsFact(
        _fact_id(entity, fact_type.value, state, item.published_at, item.id),
        entity.player_id, entity.name, entity.position, entity.team, fact_type.value,
        None, state, None, confidence, (item.id,), (item.source,), (item.url,),
        item.published_at, _excerpt(item, entity), freshness_bucket(item.published_at), authority, explicit,
    )


STATUS_PATTERNS = (
    (r"\b(?:rule(?:d|s)?|is|listed|downgraded to) out\b|\bto out\b|\bout (?:vs\.?|for)\b|\bwill not play\b|\binactive\b", "OUT"),
    (r"\bdoubtful\b", "DOUBTFUL"),
    (r"\bquestionable\b", "QUESTIONABLE"),
    (r"\bactivated from (?:injured reserve|ir)\b|\bactivated\b", "ACTIVE"),
    (r"\bplaced on (?:injured reserve|ir)\b|\bto injured reserve\b", "IR"),
    (r"\bsuspended\b", "SUSPENDED"),
)
PRACTICE_PATTERNS = (
    (r"\b(?:did|will) not practice\b|\bmiss(?:ed|es|ing) practice\b|\bDNP\b", "DID_NOT_PRACTICE"),
    (r"\blimited(?: in practice| participant| participation)?\b", "LIMITED"),
    (r"\bfull participant\b|\bpracticed in full\b", "FULL"),
)
TRANSACTION_PATTERNS = (
    (r"\breleased\b", "RELEASED"), (r"\bwaived\b", "WAIVED"),
    (r"\bsigned\b", "SIGNED"), (r"\btraded\b", "TRADED"),
)


def extract_facts(items: Iterable[NewsItem], *, now: datetime | None = None) -> list[NewsFact]:
    """Extract only explicit, attributable states; implication stays downstream."""
    facts: list[NewsFact] = []
    for item in items:
        item = replace(item, published_at=_utc(datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))).isoformat(timespec="seconds"))
        text = f"{item.headline}. {item.summary}"
        for entity in item.player_entities:
            # Use the sentence/excerpt containing the entity, preventing one
            # player's status from being attached to every name in an article.
            relevant = _local_evidence(item, entity)
            for pattern, state in STATUS_PATTERNS:
                if re.search(pattern, relevant, re.I):
                    facts.append(_make_fact(item, entity, NewsFactType.PLAYER_STATUS_CHANGE, state))
                    break
            for pattern, state in PRACTICE_PATTERNS:
                if re.search(pattern, relevant, re.I):
                    facts.append(_make_fact(item, entity, NewsFactType.PRACTICE_STATUS, state, confidence="MODERATE"))
                    break
            for pattern, state in TRANSACTION_PATTERNS:
                if re.search(pattern, relevant, re.I):
                    facts.append(_make_fact(item, entity, NewsFactType.TRANSACTION, state))
                    break
            # Attribute the statement—not an invented carry/target outcome.
            last = re.escape(entity.name.split()[-1])
            role_patterns = (
                rf"(?:coach|coordinator).{{0,80}}expect(?:s|ed)?.{{0,40}}{last}.{{0,60}}(?:more|increased|larger).{{0,20}}(?:touches|workload|role|snaps)",
                rf"{last}.{{0,50}}(?:coach|coordinator).{{0,50}}(?:more|increased|larger).{{0,20}}(?:touches|workload|role|snaps)",
            )
            if any(re.search(pattern, relevant, re.I) for pattern in role_patterns) and not re.search(r"\b(?:could|may|might)\b", relevant, re.I):
                facts.append(_make_fact(item, entity, NewsFactType.ROLE_COMMENT, "EXPECTED_INCREASED_ROLE", confidence="MODERATE"))
    # Recompute freshness against the caller's clock without altering source time.
    return [replace(fact, freshness=freshness_bucket(fact.published_at, now=now)) for fact in facts]


def _family(fact: NewsFact) -> str:
    return fact.fact_type


def reconcile_facts(facts: Iterable[NewsFact], *, now: datetime | None = None) -> list[NewsFact]:
    """Deduplicate equivalent facts and retain losing contradictions as superseded IDs."""
    grouped: dict[tuple[str, str], list[NewsFact]] = {}
    for fact in facts:
        refreshed = replace(fact, freshness=freshness_bucket(fact.published_at, now=now))
        grouped.setdefault((fact.subject_player_id, _family(fact)), []).append(refreshed)
    result: list[NewsFact] = []
    authority = {"OFFICIAL": 3, "REPUTABLE_REPORTING": 2, "OTHER": 1}
    fresh_rank = {Freshness.STALE.value: 0, Freshness.RECENT.value: 1, Freshness.BREAKING.value: 2}
    for values in grouped.values():
        by_state: dict[tuple[str, str], list[NewsFact]] = {}
        for value in values:
            by_state.setdefault((value.fact_type, value.new_state), []).append(value)
        merged: list[NewsFact] = []
        for equivalents in by_state.values():
            winner = max(equivalents, key=lambda value: (value.published_at, authority.get(value.authority, 0)))
            merged.append(replace(
                winner,
                source_item_ids=tuple(dict.fromkeys(item for value in equivalents for item in value.source_item_ids)),
                sources=tuple(dict.fromkeys(item for value in equivalents for item in value.sources)),
                urls=tuple(dict.fromkeys(item for value in equivalents for item in value.urls)),
                confidence="HIGH" if len({source for value in equivalents for source in value.sources}) >= 2 or winner.confidence == "HIGH" else winner.confidence,
            ))
        winner = max(merged, key=lambda value: (fresh_rank.get(value.freshness, 0), 1 if value.explicit else 0, authority.get(value.authority, 0), value.published_at))
        contradicted = sorted((value for value in merged if value.fact_id != winner.fact_id), key=lambda value: value.published_at, reverse=True)
        losers = tuple(value.fact_id for value in contradicted)
        result.append(replace(winner, old_state=contradicted[0].new_state if contradicted else winner.old_state, superseded_fact_ids=losers))
    return sorted(result, key=lambda value: value.published_at, reverse=True)


def audit_news(items: Iterable[NewsItem], facts: Iterable[NewsFact]) -> NewsAudit:
    item_list, fact_list = list(items), list(facts)
    resolved_ids = {item.id for item in item_list if item.player_entities}
    fact_item_ids = {item_id for fact in fact_list for item_id in fact.source_item_ids}
    reasons: dict[str, int] = {}
    for item in item_list:
        reason = None if item.id in fact_item_ids else "NO_PLAYER_RESOLUTION" if item.id not in resolved_ids else "NO_SUPPORTED_ACTIONABLE_FACT"
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    return NewsAudit(len(item_list), len(resolved_ids), len(fact_list), len(item_list) - len(resolved_ids), len(item_list) - len(fact_item_ids), tuple(sorted(reasons.items())))
