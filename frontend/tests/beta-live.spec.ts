import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
test.skip(!process.env.FANEDGE_LIVE, "Opt-in real beta validation");
test("beta cold routes, capability fallbacks and feedback", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const output = process.env.FANEDGE_SCREENSHOTS || "/tmp/fanedge-m15";
  await mkdir(output, { recursive: true });
  const reports = [];
  for (const width of [1440, 390]) {
    const context = await browser.newContext({
      viewport: { width, height: 950 },
    });
    const page = await context.newPage();
    await page.goto("/");
    await page.screenshot({ path: `${output}/beta-landing-${width}.png` });
    await page.getByLabel("Sleeper username").fill("TKelceLoveMachine");
    await page.getByRole("button", { name: "Connect my team" }).click();
    await expect(
      page.getByRole("heading", { name: "Your edge", exact: true }),
    ).toBeVisible({ timeout: 60_000 });
    for (const [route, heading] of [
      ["home", "Your edge"],
      ["team", "Your team"],
      ["market", "The market"],
      ["ask", "Ask FanEdge"],
    ]) {
      // New document: cold React Query state; warmed backend after first connection.
      await page.goto(`/${route}`);
      await expect(
        page.getByRole("heading", { name: heading, exact: true }),
      ).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText(/AI phrasing off/)).toBeVisible();
      reports.push(
        await page.evaluate(
          ({ width, route }) => ({
            width,
            route,
            ready_ms: performance
              .getEntriesByName(`fanedge:ready:${route}`)
              .at(-1)?.startTime,
            navigation: performance
              .getEntriesByType("navigation")
              .map((x) => x.toJSON()),
            resources: performance
              .getEntriesByType("resource")
              .map((x) => x.toJSON()),
            overflow: document.documentElement.scrollWidth > innerWidth,
          }),
          { width, route },
        ),
      );
      await page.screenshot({
        path: `${output}/beta-${route}-${width}.png`,
        fullPage: true,
      });
      if (route === "team") {
        const start = Date.now();
        await page
          .getByRole("button", { name: /^View / })
          .first()
          .click();
        await expect(page.getByRole("dialog")).toBeVisible();
        reports.push({
          width,
          route: "first_drawer",
          ready_ms: Date.now() - start,
          overflow: false,
        });
        await page.keyboard.press("Escape");
      }
      if (route === "market") {
        const start = Date.now();
        await page.getByRole("tab", { name: "Trades", exact: true }).click();
        await expect(
          page.getByRole("heading", { name: "Trade discovery Experimental" }),
        ).toBeVisible();
        reports.push({
          width,
          route: "first_trades",
          ready_ms: Date.now() - start,
          overflow: false,
          resources: await page.evaluate(() =>
            performance.getEntriesByType("resource").map((x) => x.toJSON()),
          ),
        });
      }
    }
    await page.getByText("Beta · Send feedback", { exact: true }).click();
    await page.getByLabel("What happened?").selectOption("OTHER");
    await page
      .getByLabel("Anything else? (optional)")
      .fill("M15 validation: test feedback, not tester adoption.");
    await page
      .getByRole("button", { name: "Send feedback", exact: true })
      .click();
    await expect(page.getByText("Thanks — feedback saved.")).toBeVisible();
    await page.goto("/home");
    const helpful = page
      .getByRole("button", { name: "Helpful", exact: true })
      .first();
    await helpful.click();
    await expect(helpful).toHaveAttribute("aria-pressed", "true");
    await context.close();
  }
  expect(reports.every((r) => !r.overflow)).toBeTruthy();
  await writeFile(
    `${output}/cold-routes.json`,
    JSON.stringify(reports, null, 2),
  );
});
