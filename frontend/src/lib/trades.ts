import type { Player } from "./types";
export type TradePreferences = {
  protected: string[];
  trade_block: string[];
  protect_core: boolean;
};
export type PositionProfile = {
  position: string;
  status: string;
  required: number;
  depth: number;
  usable_depth: number;
  starter_quality: number;
  bench_quality: number;
  injury_pressure: number;
  bye_pressure: number;
  reason: string;
};
export type TradeTeam = {
  roster_id: string;
  team_name: string;
  player_ids: string[];
  positions: Record<string, PositionProfile>;
  valid: boolean;
};
export type TradePartner = {
  roster_id: string;
  team_name: string;
  score: number;
  needs: string[];
  surplus: string[];
  reasons: string[];
};
export type TradeOverview = {
  teams: TradeTeam[];
  partners: TradePartner[];
  user_team_id: string;
  default_protected: string[];
  players: Record<string, Player>;
  snapshot_id: string;
  warnings: string[];
  values: Record<
    string,
    {
      relative_value: number;
      quality: number;
      waiver_replacement: number | null;
      typical_starter: number | null;
      available: boolean;
      supported: boolean;
      confidence: string;
      tier?: string;
      market_evidence?: {
        source: string;
        url: string;
        as_of: string;
        kind: string;
        adp: number;
        samples: number;
      } | null;
      reasons: string[];
    }
  >;
};
export type TradeImpact = {
  lineup_delta: number;
  depth_delta: number;
  label: string;
  changes: { slot: string; before: string | null; after: string | null }[];
  before: Record<string, PositionProfile>;
  after: Record<string, PositionProfile>;
  required_drops: string[];
};
export type TradeIdea = {
  id: string;
  partner_id: string;
  partner_name: string;
  outgoing: string[];
  incoming: string[];
  user_impact: TradeImpact;
  partner_impact: TradeImpact;
  fit: string;
  confidence: string;
  why_you: string[];
  why_them: string[];
  give_up: string[];
  risks: string[];
  value_ratio: number;
};
export type TradeSearch = {
  ideas: TradeIdea[];
  partners: TradePartner[];
  players: Record<string, Player>;
  elapsed_ms: number;
  tested: number;
  warnings: string[];
  protected: string[];
  model_version: string;
};
export type TradeAnalysis = {
  codes?: string[];
  accepted: boolean;
  rejections: string[];
  idea: TradeIdea | null;
  players: Record<string, Player>;
};
