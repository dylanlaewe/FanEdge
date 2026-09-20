import { test, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
test.skip(!process.env.FANEDGE_LIVE, "Opt-in real trade walkthrough");
test("real trade finder: desktop tablet mobile, protected players, analysis and Ask", async ({
  page,
}) => {
  test.setTimeout(180000);
  const folder =
    process.env.FANEDGE_SCREENSHOTS || "/tmp/fanedge-trade-screens";
  await mkdir(folder, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("Sleeper username").fill("TKelceLoveMachine");
  await page.getByRole("button", { name: "Connect my team" }).click();
  await expect(
    page.getByRole("heading", { name: "Your edge", exact: true }),
  ).toBeVisible({ timeout: 60000 });
  await page.getByRole("link", { name: "Market", exact: true }).click();
  await page.getByRole("tab", { name: "Trades", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Trade discovery Experimental" }),
  ).toBeVisible();
  const times = [];
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const start = performance.now();
    await page
      .getByRole("button", { name: "Find trades", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: /ideas worth exploring/ }),
    ).toBeVisible({ timeout: 30000 });
    await expect(
      page.getByRole("button", { name: "Find trades", exact: true }),
    ).toBeEnabled();
    times.push({
      width,
      search_response_ms: Math.round(performance.now() - start),
    });
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({
      path: `${folder}/${width}-finder.png`,
      fullPage: true,
    });
    await page.getByLabel("Trade target").selectOption("12481");
    await page
      .getByRole("button", { name: "Find trades", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Find trades", exact: true }),
    ).toBeEnabled({ timeout: 30000 });
    // Live evidence changes: a quiet supported result is not a test failure.
    await expect(
      page.getByRole("heading", { name: /ideas worth exploring/ }),
    ).toBeVisible();
    if (await page.locator(".trade-results .trade-idea").count()) {
      await page
        .locator(".trade-results .trade-idea")
        .first()
        .screenshot({ path: `${folder}/${width}-idea.png` });
    }
    await page.getByLabel("Trade target").selectOption("");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  if (await page.locator(".trade-results .trade-idea").count()) {
    await page
      .locator(".trade-results")
      .getByRole("button", { name: "Analyze trade", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Package clears the two-sided filters",
      }),
    ).toBeVisible();
    await page
      .locator(".trade-analysis")
      .screenshot({ path: `${folder}/390-manual-analysis.png` });
  }
  await page.locator(".trade-protections summary").click();
  await page.screenshot({
    path: `${folder}/390-protections.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "RB", exact: true }).click();
  await page.getByRole("button", { name: "Find trades", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Find trades", exact: true }),
  ).toBeEnabled();
  await page.screenshot({
    path: `${folder}/390-rb-results.png`,
    fullPage: true,
  });
  await page
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("link", { name: "AI", exact: true })
    .click();
  await page.getByLabel("Ask about your team").fill("Find me a win-now trade");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.locator(".assistant-message")).toHaveCount(1, {
    timeout: 30000,
  });
  await page.screenshot({
    path: `${folder}/390-ask-trade.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await writeFile(`${folder}/timings.json`, JSON.stringify(times, null, 2));
});
