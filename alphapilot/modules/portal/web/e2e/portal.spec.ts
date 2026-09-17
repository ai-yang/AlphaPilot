import { expect, test } from "@playwright/test";
import { connectResearch } from "./research";

const routes = ["/", "/mining", "/backtest", "/timing", "/library", "/market", "/daily-trade", "/live", "/scheduler", "/notifications", "/advanced"];

test.describe("Portal interaction contract", () => {
  test("all routes render without unhandled errors or API 500", async ({ page }) => {
    const consoleErrors: string[] = [];
    const apiFailures: string[] = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 500) apiFailures.push(`${response.status()} ${response.url()}`);
    });
    for (const route of routes) {
      await page.goto(route);
      await connectResearch(page);
      await expect(page.locator(".shell")).toBeVisible();
      await expect(page.locator(".route-skeleton")).toHaveCount(0);
      await expect(page.locator("body")).toContainText("AlphaPilot");
    }
    expect(apiFailures).toEqual([]);
    expect(consoleErrors.filter((message) => !message.includes("favicon.ico"))).toEqual([]);
  });

  test("all routes keep a stable shell through network failure and browser retry", async ({ page }) => {
    for (const route of routes) {
      await page.route("**/api/**", (request) => request.abort("failed"));
      await page.goto(route);
      await expect(page.locator(".shell")).toBeVisible();
      await expect(page.locator("main")).not.toBeEmpty();
      await page.unroute("**/api/**");
      await page.reload();
      await expect(page.locator(".shell")).toBeVisible();
      await expect(page.locator(".route-skeleton")).toHaveCount(0);
    }
  });

  test("backtest artifact opens a real chart", async ({ page }) => {
    await page.goto("/backtest");
    await connectResearch(page);
    await page.getByRole("button", { name: /^legacy_backtest-/ }).first().click();
    await page.getByRole("button", { name: /^cumulative ·/ }).click();
    await expect(page.locator(".js-plotly-plot").first()).toBeVisible({ timeout: 20_000 });
  });

  test("external client and GUI share one durable inline backtest and cancellation", async ({ page }) => {
    await page.goto("/backtest");
    const credentials = await connectResearch(page);
    const headers = { Authorization: `Bearer ${credentials.external}`, "Idempotency-Key": "browser-inline-intent" };
    const data = { kind: "factor_backtest", input: { dataset_id: "baostock_cn:day:backward", mode: "single_ic", factor_source: { type: "inline", factors: [{ name: "price", expression: "$close" }] } } };
    const response = await page.request.post("/api/v1/jobs", { headers, data });
    expect(response.status()).toBe(202);
    const job = await response.json();
    const repeated = await page.request.post("/api/v1/jobs", { headers, data });
    expect((await repeated.json()).job_id).toBe(job.job_id);
    const panel = page.locator("section", { has: page.getByRole("heading", { name: "共享任务队列", exact: true }) }).first();
    const row = panel.locator("tbody tr", { hasText: job.job_id });
    await expect(row).toContainText("排队中");
    await row.getByRole("button", { name: "取消", exact: true }).click();
    await expect(row).toContainText("已取消");
    const result = await page.request.get(`/api/v1/jobs/${job.job_id}`, { headers });
    expect((await result.json()).status).toBe("cancelled");
  });

  test("Paper daemon follows the browser safety workflow", async ({ page }) => {
    const externalRequests: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (!["127.0.0.1", "localhost"].includes(url.hostname)) externalRequests.push(request.url());
    });
    await page.goto("/live");
    await expect(page.getByRole("tab", { name: /Paper/i })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByLabel("初始资金")).toBeVisible();
    await page.getByLabel("初始资金").fill("250000");
    await page.getByRole("button", { name: "启动 daemon" }).click();
    await expect(page.locator(".live-workspace-status .pill.running")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("tab", { name: /Paper/i })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tab", { name: /Live/i })).toBeEnabled();
    await page.getByRole("button", { name: "停止 daemon" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "确认" }).click();
    await expect(page.getByRole("button", { name: "启动 daemon" })).toBeVisible({ timeout: 15_000 });
    expect(externalRequests).toEqual([]);
  });

  test("live account metrics stay visible without overlap at desktop widths", async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.goto("/live");

    const strip = page.locator(".live-account-strip");
    await expect(strip).toBeVisible();
    await expect(strip.locator(":scope > span")).toHaveCount(7);

    const layout = await strip.evaluate((element) => {
      const container = element.getBoundingClientRect();
      const items = Array.from(element.children).map((child) => child.getBoundingClientRect());
      const outside = items.some((item) => (
        item.left < container.left - 0.5 || item.right > container.right + 0.5
      ));
      const overlaps = items.some((item, index) => items.slice(index + 1).some((other) => (
        item.left < other.right - 0.5
        && item.right > other.left + 0.5
        && item.top < other.bottom - 0.5
        && item.bottom > other.top + 0.5
      )));
      return {
        display: getComputedStyle(element).display,
        horizontalOverflow: element.scrollWidth > element.clientWidth + 1,
        outside,
        overlaps,
      };
    });

    expect(layout).toEqual({
      display: "grid",
      horizontalOverflow: false,
      outside: false,
      overlaps: false,
    });
  });

  test("@mobile live safety controls and business tabs stay visible", async ({ page }) => {
    await page.goto("/live");
    await expect(page.locator(".live-workspace-status")).toBeVisible();
    await expect(page.locator(".live-status-actions .danger")).toBeVisible();
    await expect(page.locator(".live-business-tabs")).toBeVisible();
    const columns = await page.locator(".live-workbench-grid").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
    expect(columns).toBe(1);
  });

  test("@cross-browser core navigation and factor form are operable", async ({ page }) => {
    await page.goto("/library");
    await connectResearch(page);
    await expect(page.getByRole("heading", { name: /研究资产库|因子.*策略库|Factor/ }).first()).toBeVisible();
    await page.goto("/live");
    await expect(page.getByRole("tab", { name: /Paper/i })).toBeVisible();
  });
});
