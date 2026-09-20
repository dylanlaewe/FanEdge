import { expect, test, type Page } from "@playwright/test";
import type { Player, Snapshot } from "../src/lib/types";

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
  await page.locator(".sidebar").getByLabel("Select league").selectOption("other");
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
