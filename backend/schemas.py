"""Versioned product contracts. No provider payloads cross the API boundary."""

from typing import Literal
from pydantic import BaseModel, Field


class League(BaseModel):
    id: str
    name: str
    season: int
    scoring: str
    team_name: str


class Connection(BaseModel):
    username: str
    leagues: list[League]


class Team(BaseModel):
    abbreviation: str
    display_name: str
    logo_url: str | None = None
    color: str = "#64748b"


class Matchup(BaseModel):
    opponent: Team | None = None
    venue: str | None = None
    kickoff: str | None = None
    schedule_status: str = "UNKNOWN"
    difficulty: str | None = None
    evidence_basis: str | None = None


class Metric(BaseModel):
    label: str
    value: float | None
    unit: str = ""


class NewsEvidence(BaseModel):
    player_id: str
    headline: str
    detail: str
    source: str
    url: str | None = None
    published_at: str
    freshness: str


class Evidence(BaseModel):
    label: str
    detail: str
    source: str
    url: str | None = None


class Player(BaseModel):
    id: str
    name: str
    position: str
    team: Team
    image_url: str | None = None
    status: str = "UNKNOWN"
    matchup: Matchup
    role: str = "UNKNOWN"
    trend: str = "INSUFFICIENT DATA"
    confidence: str = "LOW"
    metrics: list[Metric] = Field(default_factory=list)
    news: list[NewsEvidence] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class LineupSlot(BaseModel):
    id: str
    label: str
    player: Player | None


class Recommendation(BaseModel):
    slot: str
    player: Player
    alternative: Player | None
    action: str
    confidence: str
    reasons: list[str]
    evidence: list[Evidence]


class WaiverCandidate(BaseModel):
    player: Player
    rank: int
    available: bool = True
    reasons: list[str]
    category: Literal["WAIVERS", "WATCHLIST"]


class OpportunityEvent(BaseModel):
    id: str
    type: str
    priority: str
    player: Player | None
    related_player: Player | None
    action: str
    confidence: str
    reasons: list[str]
    evidence: list[Evidence]
    news: list[NewsEvidence]
    lifecycle: str
    freshness: str
    feedback: str | None = None


class JournalEntry(BaseModel):
    id: str
    player_name: str | None
    type: str
    action: str
    lifecycle: str
    week: int
    last_seen: str
    feedback: str | None
    outcome: str | None
    recommended_points: float | None = None
    alternative_points: float | None = None
    evidence: list[str]


class SnapshotMeta(BaseModel):
    id: str
    built_at: str
    week: int | None
    data_fresh: bool
    warnings: list[str]
    refreshing: bool = False
    stale: bool = False
    refresh_error: str | None = None


class Snapshot(BaseModel):
    meta: SnapshotMeta
    league: League
    starters: list[LineupSlot]
    bench: list[Player]
    recommendations: list[Recommendation]
    waivers: list[WaiverCandidate]
    events: list[OpportunityEvent]
    history: list[JournalEntry]
    suggestions: list[str]


class Overview(BaseModel):
    meta: SnapshotMeta
    league: League
    events: list[OpportunityEvent]


class RosterResponse(BaseModel):
    starters: list[LineupSlot]
    bench: list[Player]


class CopilotRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    conversation_id: str | None = Field(default=None, max_length=64)
    suggested: bool = False


class CopilotResponse(BaseModel):
    conversation_id: str
    model_text: str | None = None
    answer: str
    why: list[str]
    action: str | None
    watch_for: str | None
    confidence: str
    hypothetical: bool
    unsupported: bool
    provider_fallback: bool
    evidence: list[Evidence]
    players: list[Player]
    intent: str


class FeedbackRequest(BaseModel):
    status: Literal["SAVED", "DONE", "DISMISSED"]


class AnalyticsRequest(BaseModel):
    event: Literal[
        "ask_fanedge_opened", "copilot_evidence_opened", "recommendation_viewed"
    ]
