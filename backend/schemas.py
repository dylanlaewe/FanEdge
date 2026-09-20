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
    roster_id: str | None = None
    is_opponent: bool = False


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
    trade_preferences: "TradeRequest | None" = None


class CopilotResponse(BaseModel):
    plan: dict | None = None
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
    trades: "TradeSearch | None" = None


class FeedbackRequest(BaseModel):
    status: Literal["SAVED", "DONE", "DISMISSED"]


class AnalyticsRequest(BaseModel):
    event: Literal[
        "ask_fanedge_opened",
        "copilot_evidence_opened",
        "recommendation_viewed",
        "TRADE_FINDER_OPENED",
        "TRADE_GOAL_SELECTED",
        "TRADE_VIEWED",
        "TRADE_VARIATION_REQUESTED",
        "TRADE_PLAYER_PROTECTED",
    ]


class PositionProfile(BaseModel):
    position: str
    status: str
    required: int
    depth: int
    usable_depth: int
    starter_quality: float
    bench_quality: float
    injury_pressure: int
    bye_pressure: int
    role_quality: int
    reason: str


class TeamProfile(BaseModel):
    roster_id: str
    owner_id: str
    team_name: str
    player_ids: list[str]
    lineup: list[str | None]
    lineup_quality: float
    depth_quality: float
    positions: dict[str, PositionProfile]
    valid: bool


class TradePartnerFit(BaseModel):
    roster_id: str
    team_name: str
    score: int
    reasons: list[str]
    needs: list[str]
    surplus: list[str]


class RelativePlayerValue(BaseModel):
    player_id: str
    quality: float
    relative_value: float
    waiver_replacement: float | None
    typical_starter: float | None
    confidence: str
    supported: bool
    available: bool
    reasons: list[str]
    tier: str = "SPECULATIVE"
    market_evidence: dict | None = None


class TradeOverview(BaseModel):
    teams: list[TeamProfile]
    partners: list[TradePartnerFit]
    user_team_id: str
    default_protected: list[str]
    values: dict[str, RelativePlayerValue]
    players: dict[str, Player]
    warnings: list[str]
    snapshot_id: str


class LineupChange(BaseModel):
    slot: str
    before: str | None
    after: str | None


class TradeImpact(BaseModel):
    lineup_delta: float
    depth_delta: float
    label: str
    changes: list[LineupChange]
    before: dict[str, PositionProfile]
    after: dict[str, PositionProfile]
    required_drops: list[str]


class TradeIdea(BaseModel):
    id: str
    partner_id: str
    partner_name: str
    outgoing: list[str]
    incoming: list[str]
    user_impact: TradeImpact
    partner_impact: TradeImpact
    fit: str
    confidence: str
    why_you: list[str]
    why_them: list[str]
    give_up: list[str]
    risks: list[str]
    value_ratio: float


class TradeSearch(BaseModel):
    ideas: list[TradeIdea]
    partners: list[TradePartnerFit]
    tested: int
    elapsed_ms: float
    warnings: list[str]
    protected: list[str]
    model_version: str
    players: dict[str, Player] = Field(default_factory=dict)


class TradeRequest(BaseModel):
    goal: Literal["QB", "RB", "WR", "TE", "BEST_UPGRADE", "DEPTH"] = "BEST_UPGRADE"
    protected: list[str] = Field(default_factory=list, max_length=64)
    trade_block: list[str] = Field(default_factory=list, max_length=64)
    partner_id: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=64)
    protect_core: bool = True
    limit: int = Field(default=12, ge=1, le=30)
    exclude_ids: list[str] = Field(default_factory=list, max_length=30)

    def options(self):
        from trades import TradeOptions

        values = self.model_dump()
        for key in ("protected", "trade_block", "exclude_ids"):
            values[key] = tuple(sorted(set(values[key])))
        return TradeOptions(**values)


class TradeAnalyzeRequest(TradeRequest):
    outgoing: list[str] = Field(min_length=1, max_length=2)
    incoming: list[str] = Field(min_length=1, max_length=2)

    def options(self):
        return TradeRequest(**self.model_dump()).options()


class TradeAnalysis(BaseModel):
    accepted: bool
    rejections: list[str]
    idea: TradeIdea | None
    players: dict[str, Player] = Field(default_factory=dict)
    codes: list[str] = Field(default_factory=list)


CopilotRequest.model_rebuild()
CopilotResponse.model_rebuild()
