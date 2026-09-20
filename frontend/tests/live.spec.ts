import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
test.skip(
  !process.env.FANEDGE_LIVE,
  "Opt-in real-provider visual/performance check",
);
test("real connected league: all pages at desktop, tablet, mobile", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const output = process.env.FANEDGE_SCREENSHOTS || "/tmp/fanedge-m12-screens";
  await mkdir(output, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Sleeper username").fill("TKelceLoveMachine");
  await page.getByRole("button", { name: "Connect my team" }).click();
  await expect(
    page.getByRole("heading", { name: "Your edge", exact: true }),
  ).toBeVisible({ timeout: 60_000 });
  const measurements: {
    width: number;
    view: string;
    ms: number;
    requests: number;
  }[] = [];
  let requests = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/")) requests++;
  });
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    for (const [view, heading] of [
      ["home", "Your edge"],
      ["team", "Your team"],
      ["market", "The market"],
      ["ask", "Ask FanEdge"],
    ]) {
      const nav = page.getByRole("navigation", {
        name: width < 768 ? "Mobile navigation" : "Primary navigation",
      });
      const label =
        view === "home"
          ? "Home"
          : view === "team"
            ? "Team"
            : view === "market"
              ? "Market"
              : width < 768
                ? "AI"
                : "Ask FanEdge";
      const before = requests;
      await page.evaluate(() => {
        performance.clearMarks();
        performance.clearMeasures();
      });
      await nav
        .getByRole("link", { name: label, exact: view !== "ask" })
        .evaluate((el) =>
          el.addEventListener("click", () => performance.mark("nav-start"), {
            once: true,
          }),
        );
      await nav
        .getByRole("link", { name: label, exact: view !== "ask" })
        .click();
      await expect(
        page.getByRole("heading", { name: heading, exact: true }),
      ).toBeVisible();
      const ms = await page.evaluate(
        () =>
          new Promise<number>((resolve) =>
            requestAnimationFrame(() => {
              performance.mark("nav-end");
              resolve(
                performance.measure("nav", "nav-start", "nav-end").duration,
              );
            }),
          ),
      );
      measurements.push({
        width,
        view,
        ms: Math.round(ms * 100) / 100,
        requests: requests - before,
      });
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForTimeout(250);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page
        .waitForFunction(
          () => Array.from(document.images).every((img) => img.complete),
          undefined,
          { timeout: 3000 },
        )
        .catch(() => {});
      await page.screenshot({
        path: `${output}/${width}-${view}.png`,
        fullPage: true,
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBeTruthy();
      if (view === "team") {
        const drawerStart = performance.now();
        await page.locator(".roster-section .player-row").first().click();
        await expect(page.getByRole("dialog")).toBeVisible();
        measurements.push({
          width,
          view: "drawer",
          ms: Math.round(performance.now() - drawerStart),
          requests: requests - before,
        });
        await page.screenshot({ path: `${output}/${width}-drawer.png` });
        await page
          .getByRole("button", { name: "Close player details" })
          .click();
      }
      if (view === "market") {
        await page.getByRole("tab", { name: "Watchlist" }).click();
        await page.screenshot({
          path: `${output}/${width}-watchlist.png`,
          fullPage: true,
        });
      }
    }
  }
  await page
    .getByLabel("Ask about your team")
    .fill("What should I do this week?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.locator(".assistant-message")).toHaveCount(1, {
    timeout: 30_000,
  });
  await page.screenshot({
    path: `${output}/390-chat-response.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await writeFile(
    `${output}/navigation.json`,
    JSON.stringify(measurements, null, 2),
  );
});
