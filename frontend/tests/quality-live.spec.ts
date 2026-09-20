import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

test.skip(!process.env.FANEDGE_LIVE, "Opt-in real league quality journeys");
test("M14 Ask goals, unsupported grounding, news evidence and refresh journal", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const folder =
    process.env.FANEDGE_SCREENSHOTS || "/tmp/fanedge-quality-screens";
  await mkdir(folder, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Sleeper username").fill("TKelceLoveMachine");
  await page.getByRole("button", { name: "Connect my team" }).click();
  await expect(
    page.getByRole("heading", { name: "Your edge", exact: true }),
  ).toBeVisible({ timeout: 60_000 });
  const snapshotResponse = await page.request.get(
    "http://127.0.0.1:8000/api/users/TKelceLoveMachine/leagues",
  );
  const league = (await snapshotResponse.json()).leagues[0].id;
  const snapshotUrl = `http://127.0.0.1:8000/api/leagues/${league}/snapshot?username=TKelceLoveMachine`;
  const initial = await (await page.request.get(snapshotUrl)).json();
  await page.getByRole("button", { name: "Refresh league data" }).click();
  await expect
    .poll(
      async () => (await (await page.request.get(snapshotUrl)).json()).meta.id,
      { timeout: 60_000 },
    )
    .not.toBe(initial.meta.id);
  await page.getByRole("button", { name: "Decision journal" }).click();
  await expect(
    page.getByText("Decision journal", { exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({ path: `${folder}/1440-journal.png`, fullPage: true });
  await page.getByRole("link", { name: "Ask FanEdge AI" }).click();
  const measures = [];
  for (const question of [
    "What should I do this week?",
    "I need an RB.",
    "Tell me about Jaxson Dart",
    "Will rain affect my lineup?",
    "What changed since my last check?",
  ]) {
    const start = performance.now();
    const response = page.waitForResponse(
      (r) => r.url().includes("/copilot") && r.request().method() === "POST",
    );
    await page.getByLabel("Ask about your team").fill(question);
    await page.getByRole("button", { name: "Send message" }).click();
    const answer = await (await response).json();
    await expect(page.locator(".assistant-message").last()).toContainText(
      answer.answer,
    );
    measures.push({
      question,
      response_ms: Math.round(performance.now() - start),
      action: answer.action,
    });
    if (question === "I need an RB.") {
      expect(answer.intent).toBe("ACTION_PLAN");
      expect(answer.plan.considered).toEqual([
        "LINEUP_SWAP",
        "WAIVER",
        "TRADE",
        "MONITOR",
        "HOLD",
      ]);
    }
    if (question.includes("rain")) expect(answer.unsupported).toBe(true);
  }
  await page.screenshot({
    path: `${folder}/1440-quality-ask.png`,
    fullPage: true,
  });
  await writeFile(
    `${folder}/quality-journeys.json`,
    JSON.stringify(measures, null, 2),
  );
  expect(errors).toEqual([]);
});
