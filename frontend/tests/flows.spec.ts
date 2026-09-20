import { expect, test, type Page } from "@playwright/test";
import type { Player, Snapshot } from "../src/lib/types";
import type {
  TradeIdea,
  TradeOverview,
  TradeSearch,
  PositionProfile,
} from "../src/lib/trades";

const player: Player = {
  id: "p1",
  name: "Fixture Receiver With A Long Name",
  position: "WR",
  team: {
    abbreviation: "LAR",
    display_name: "Los Angeles Rams",
    logo_url: null,
    color: "#003594",
  },
  image_url: "/missing-image.png",
  status: "QUESTIONABLE",
  matchup: {
    opponent: {
      abbreviation: "NYG",
      display_name: "New York Giants",
      logo_url: null,
      color: "#003594",
    },
    venue: "home",
    kickoff: "2026-09-22T00:15:00Z",
    schedule_status: "SCHEDULED",
    difficulty: "NEUTRAL",
    evidence_basis: "MIXED",
  },
  role: "FEATURED",
  trend: "INSUFFICIENT DATA",
  confidence: "MODERATE",
  metrics: [{ label: "Fantasy / G", value: 12.2, unit: "" }],
  news: [],
  evidence: [{ label: "Role", detail: "Featured", source: "Fixture" }],
};
const snapshot: Snapshot = {
  meta: {
    id: "one",
    built_at: "2026-09-19T12:00:00Z",
    week: 2,
    data_fresh: true,
    warnings: [],
    refreshing: false,
    stale: false,
    refresh_error: null,
  },
  league: {
    id: "league",
    name: "Test League",
    season: 2026,
    scoring: "Half PPR",
    team_name: "My Team",
  },
  starters: [{ id: "WR1", label: "WR", player }],
  bench: [],
  recommendations: [],
  waivers: [
    {
      player: { ...player, id: "p2", name: "Available Receiver" },
      rank: 1,
      available: true,
      reasons: ["Usage rising"],
      category: "WAIVERS",
    },
    {
      player: { ...player, id: "p3", name: "Watch Receiver" },
      rank: 2,
      available: true,
      reasons: ["Small sample"],
      category: "WATCHLIST",
    },
  ],
  events: [],
  history: [],
  suggestions: ["What should I do this week?"],
};
async function fixtures(page: Page) {
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const response = url.includes("/users/")
      ? { username: "manager", leagues: [snapshot.league] }
      : url.includes("/copilot")
        ? {
            conversation_id: "conversation",
            answer: "Your plan holds.",
            why: ["No material change cleared the threshold."],
            action: "HOLD",
            watch_for: null,
            confidence: "HIGH",
            hypothetical: false,
            unsupported: false,
            provider_fallback: false,
            evidence: player.evidence,
            players: [player],
            intent: "WEEKLY_PLAN",
          }
        : snapshot;
    await route.fulfill({ json: response });
  });
}
async function connect(page: Page) {
  await page.goto("/");
  await page.getByLabel("Sleeper username").fill("manager");
  await page.getByRole("button", { name: "Connect my team" }).click();
  await expect(
    page.getByRole("heading", { name: "Your edge", exact: true }),
  ).toBeVisible();
}

const opponent = {
  ...player,
  id: "p2",
  name: "Opponent Runner",
  position: "RB",
  roster_id: "other",
  is_opponent: true,
};
const positionProfile: PositionProfile = {
  position: "RB",
  status: "NEED",
  required: 1,
  depth: 1,
  usable_depth: 1,
  starter_quality: 5,
  bench_quality: 0,
  injury_pressure: 0,
  bye_pressure: 0,
  reason: "One weak starter; no usable backup.",
};
const impact = {
  lineup_delta: 3,
  depth_delta: 0,
  label: "STARTER_UPGRADE",
  changes: [{ slot: "RB1", before: null, after: "p2" }],
  before: { RB: positionProfile },
  after: { RB: { ...positionProfile, status: "BALANCED", starter_quality: 8 } },
  required_drops: [],
};
const tradeIdea: TradeIdea = {
  id: "idea",
  partner_id: "other",
  partner_name: "Other Team",
  outgoing: ["p1"],
  incoming: ["p2"],
  user_impact: impact,
  partner_impact: { ...impact, changes: [] },
  fit: "HELPS_BOTH",
  confidence: "MODERATE",
  why_you: ["RB starter quality improves."],
  why_them: ["They may consider improved WR cover."],
  give_up: ["One WR option."],
  risks: ["Not projected points or acceptance probability."],
  value_ratio: 0.9,
};
const tradeOverview: TradeOverview = {
  teams: [
    {
      roster_id: "mine",
      team_name: "My Team",
      player_ids: ["p1"],
      positions: { RB: positionProfile },
      valid: true,
    },
    {
      roster_id: "other",
      team_name: "Other Team",
      player_ids: ["p2"],
      positions: { RB: { ...positionProfile, status: "SURPLUS" } },
      valid: true,
    },
  ],
  partners: [
    {
      roster_id: "other",
      team_name: "Other Team",
      score: 6,
      needs: ["WR"],
      surplus: ["RB"],
      reasons: ["Complementary WR and RB evidence."],
    },
  ],
  user_team_id: "mine",
  default_protected: [],
  players: { p1: player, p2: opponent },
  snapshot_id: "one",
  warnings: [],
  values: {},
};
const tradeSearch: TradeSearch = {
  ideas: [tradeIdea],
  partners: tradeOverview.partners,
  players: tradeOverview.players,
  elapsed_ms: 12,
  tested: 20,
  warnings: [],
  protected: [],
  model_version: "trade-evidence-v1",
};
async function tradeFixtures(page: Page) {
  await fixtures(page);
  await page.route("**/trades?**", (route) =>
    route.fulfill({ json: tradeOverview }),
  );
  await page.route("**/trades/search?**", (route) =>
    route.fulfill({
      json: {
        ...tradeSearch,
        ideas: route.request().postDataJSON().protected?.includes("p1")
          ? []
          : tradeSearch.ideas,
      },
    }),
  );
  await page.route("**/trades/analyze?**", (route) =>
    route.fulfill({
      json: {
        accepted: true,
        rejections: [],
        idea: tradeIdea,
        players: tradeOverview.players,
      },
    }),
  );
}
test("trade discovery, player protection, manual analysis and targeted drawer", async ({
  page,
}) => {
  await tradeFixtures(page);
  await connect(page);
  await page.getByRole("link", { name: "Market", exact: true }).click();
  await page.getByRole("tab", { name: "Trades", exact: true }).click();
  await page.getByRole("button", { name: "Find trades", exact: true }).click();
  await expect(page.locator(".trade-idea")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Analyze trade", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Package clears the two-sided filters" }),
  ).toBeVisible();
  await page
    .locator(".trade-results")
    .getByRole("button", { name: `Protect ${player.name}`, exact: true })
    .click();
  await expect(page.locator(".trade-results .trade-idea")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Browse all roster profiles" })
    .click();
  await page
    .locator(".trade-team-list summary")
    .filter({ hasText: "Other Team" })
    .click();
  await page
    .locator(".trade-team-list")
    .getByRole("button", { name: "Opponent Runner RB · LAR" })
    .click();
  await page
    .getByRole("button", { name: "Explore trade for Opponent Runner" })
    .click();
  await expect(page.getByLabel("Trade target")).toHaveValue("p2");
  await page.locator(".trade-manual summary").click();
  await page.getByLabel("Players I send").selectOption("p1");
  await page.getByLabel("Manual trade partner").selectOption("other");
  await page.getByLabel("Players I receive").selectOption("p2");
  await expect(
    page.getByRole("button", { name: "Analyze selected package" }),
  ).toBeEnabled();
});
test("mobile trade search and structured trade answer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await tradeFixtures(page);
  await connect(page);
  await page
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("link", { name: "Market", exact: true })
    .click();
  await page.getByRole("tab", { name: "Trades", exact: true }).click();
  await page.getByRole("button", { name: "Find trades", exact: true }).click();
  await expect(page.locator(".trade-idea")).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.route("**/copilot?**", (route) =>
    route.fulfill({
      json: {
        conversation_id: "trade",
        answer: "One trade idea",
        why: [],
        action: "EXPLORE",
        watch_for: null,
        confidence: "MODERATE",
        hypothetical: true,
        unsupported: false,
        provider_fallback: false,
        evidence: [],
        players: [],
        intent: "TRADE_FIND",
        trades: tradeSearch,
      },
    }),
  );
  await page
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("link", { name: "AI", exact: true })
    .click();
  await page.getByLabel("Ask about your team").fill("Find an RB trade");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.locator(".assistant-message .trade-idea")).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("changing league discards a delayed answer from the previous league", async ({
  page,
}) => {
  await fixtures(page);
  const other = { ...snapshot.league, id: "other", name: "Other League" };
  await page.route("**/api/users/**", (route) =>
    route.fulfill({
      json: { username: "manager", leagues: [snapshot.league, other] },
    }),
  );
  await page.route("**/api/leagues/other/snapshot?**", (route) =>
    route.fulfill({ json: { ...snapshot, league: other } }),
  );
  let release!: () => void;
  const blocked = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/copilot?**", async (route) => {
    await blocked;
    await route.fulfill({
      json: {
        conversation_id: "old",
        answer: "Old league response",
        why: [],
        players: [],
        evidence: [],
      },
    });
  });
  await connect(page);
  await page.getByRole("link", { name: "Ask FanEdge" }).click();
  const pending = page.waitForRequest("**/copilot?**");
  await page
    .getByRole("button", { name: "What should I do this week?" })
    .click();
  await pending;
  await page
    .locator(".sidebar")
    .getByLabel("Select league")
    .selectOption("other");
  await expect(
    page.getByRole("heading", { name: "What’s the move?" }),
  ).toBeVisible();
  const received = page.waitForResponse("**/copilot?**");
  release();
  await received;
  await expect(page.getByText("Old league response")).toHaveCount(0);
  await expect(page.locator(".user-message")).toHaveCount(0);
});
test("connect, cached navigation, team, market and player drawer", async ({
  page,
}) => {
  await fixtures(page);
  let reads = 0;
  page.on("request", (r) => {
    if (r.url().includes("/snapshot")) reads++;
  });
  await connect(page);
  await page
    .getByRole("navigation", { name: "Primary navigation" })
    .getByRole("link", { name: "Team", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your team", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: `View ${player.name}` }).click();
  await expect(
    page.getByRole("dialog", { name: "Player details" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: player.name })).toBeVisible();
  await expect(page.getByText("Questionable").last()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("link", { name: "Market", exact: true }).click();
  await expect(
    page.getByText("Available Receiver", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Watchlist" }).click();
  await expect(page.getByText("Watch Receiver", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "QB", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No players match this view" }),
  ).toBeVisible();
  expect(reads).toBe(1);
});
test("copilot sends question, renders structured response and evidence", async ({
  page,
}) => {
  await fixtures(page);
  await connect(page);
  await page
    .getByRole("navigation", { name: "Primary navigation" })
    .getByRole("link", { name: "Ask FanEdge" })
    .click();
  await expect(
    page.getByRole("heading", { name: "What’s the move?" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "What should I do this week?" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your plan holds." }),
  ).toBeVisible();
  await page.locator(".assistant-message summary").click();
  await expect(
    page.locator(".evidence-item").getByText("Featured", { exact: true }),
  ).toBeVisible();
});
test("loading and provider error have usable recovery", async ({ page }) => {
  await fixtures(page);
  await page.route("**/snapshot?**", async (route) => {
    await new Promise((r) => setTimeout(r, 1000));
    await route.fulfill({
      status: 502,
      json: { detail: "Provider unavailable" },
    });
  });
  await page.goto("/");
  await page.getByLabel("Sleeper username").fill("manager");
  await page.getByRole("button", { name: "Connect my team" }).click();
  await expect(
    page.getByRole("status", { name: "Loading league intelligence" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Your league could not load" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
});
test("mobile long names, failed headshots, drawer and bottom navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixtures(page);
  await connect(page);
  await page
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("link", { name: "Team", exact: true })
    .click();
  await page.getByRole("button", { name: `View ${player.name}` }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "Close player details" }).click();
  await expect(
    page.getByRole("navigation", { name: "Mobile navigation" }),
  ).toBeVisible();
});
