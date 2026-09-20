export type Team = {
  abbreviation: string;
  display_name: string;
  logo_url: string | null;
  color: string;
};
export type Evidence = {
  label: string;
  detail: string;
  source: string;
  url?: string | null;
};
export type NewsEvidence = {
  player_id: string;
  headline: string;
  detail: string;
  source: string;
  url: string | null;
  published_at: string;
  freshness: string;
};
export type Player = {
  roster_id?: string | null;
  is_opponent?: boolean;
  id: string;
  name: string;
  position: string;
  team: Team;
  image_url: string | null;
  status: string;
  matchup: {
    opponent: Team | null;
    venue: string | null;
    kickoff: string | null;
    schedule_status: string;
    difficulty: string | null;
    evidence_basis: string | null;
  };
  role: string;
  trend: string;
  confidence: string;
  metrics: { label: string; value: number | null; unit: string }[];
  news: NewsEvidence[];
  evidence: Evidence[];
};
export type League = {
  id: string;
  name: string;
  season: number;
  scoring: string;
  team_name: string;
};
export type Connection = { username: string; leagues: League[] };
export type Recommendation = {
  slot: string;
  player: Player;
  alternative: Player | null;
  action: string;
  confidence: string;
  reasons: string[];
  evidence: Evidence[];
};
export type Waiver = {
  player: Player;
  rank: number;
  available: boolean;
  reasons: string[];
  category: "WAIVERS" | "WATCHLIST";
};
export type Insight = {
  id: string;
  type: string;
  priority: string;
  player: Player | null;
  related_player: Player | null;
  action: string;
  confidence: string;
  reasons: string[];
  evidence: Evidence[];
  news: NewsEvidence[];
  lifecycle: string;
  freshness: string;
  feedback: string | null;
};
export type Journal = {
  id: string;
  player_name: string | null;
  type: string;
  action: string;
  lifecycle: string;
  week: number;
  last_seen: string;
  feedback: string | null;
  outcome: string | null;
  recommended_points: number | null;
  alternative_points: number | null;
  evidence: string[];
};
export type Snapshot = {
  meta: {
    id: string;
    built_at: string;
    week: number | null;
    data_fresh: boolean;
    warnings: string[];
    refreshing: boolean;
    stale: boolean;
    refresh_error: string | null;
  };
  league: League;
  starters: { id: string; label: string; player: Player | null }[];
  bench: Player[];
  recommendations: Recommendation[];
  waivers: Waiver[];
  events: Insight[];
  history: Journal[];
  suggestions: string[];
};
export type Answer = {
  plan?: {
    goal: string;
    considered: string[];
    limitations: string[];
    actions: {
      kind: string;
      summary: string;
      cost: string;
      improvement: string;
      reversibility: string;
      confidence: string;
      player_ids: string[];
      evidence: string[];
    }[];
  } | null;
  trades?: import("./trades").TradeSearch | null;
  conversation_id: string;
  model_text?: string | null;
  answer: string;
  why: string[];
  action: string | null;
  watch_for: string | null;
  confidence: string;
  hypothetical: boolean;
  unsupported: boolean;
  provider_fallback: boolean;
  evidence: Evidence[];
  players: Player[];
  intent: string;
};
export type Message =
  { role: "user"; text: string } | { role: "assistant"; answer: Answer };
