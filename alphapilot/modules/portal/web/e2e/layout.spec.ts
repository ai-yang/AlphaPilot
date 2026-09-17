import { expect, test, type Page } from "@playwright/test";
import { connectResearch } from "./research";

const routes = ["/", "/mining", "/backtest", "/library", "/market", "/daily-trade", "/scheduler", "/timing", "/live", "/notifications", "/advanced"];
const schemaRoutes = new Set(["/mining", "/backtest", "/market", "/daily-trade", "/scheduler", "/advanced"]);

async function expectContainedLayout(page: Page) {
  const issues = await page.evaluate(() => {
    const problems: string[] = [];
    const width = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > width + 1) problems.push("page scrolls horizontally");
    const visible = (el: Element) => el.getClientRects().length > 0;
    for (const el of document.querySelectorAll('.content input[type="checkbox"]')) {
      if (!visible(el)) continue;
      const box = el.getBoundingClientRect();
      if (box.width !== 16 || box.height !== 16) problems.push(`checkbox ${el.getAttribute("aria-label")}: ${box.width} × ${box.height}`);
    }
    for (const el of document.querySelectorAll(".content .panel, .content .form-grid > *, .topbar > *")) {
      if (!visible(el)) continue;
      const box = el.getBoundingClientRect();
      if (box.left < -1 || box.right > width + 1 || el.scrollWidth > el.clientWidth + 1) {
        problems.push(`overflow: ${el.tagName}.${el.className} ${el.textContent?.trim().slice(0, 50)}`);
      }
    }
    // Input bounds catch fields painting across adjacent columns even when the page fits.
    for (const el of document.querySelectorAll(".form-grid label > input, .form-grid label > select, .form-grid label > textarea")) {
      if (!visible(el)) continue;
      const box = el.getBoundingClientRect();
      const parent = el.parentElement!.getBoundingClientRect();
      if (box.left < parent.left - 1 || box.right > parent.right + 1) problems.push(`field overlaps its column: ${el.getAttribute("aria-label")}`);
    }
    return problems;
  });
  expect(issues).toEqual([]);
}

for (const width of [1440, 1024, 768, 390, 320]) {
  test(`${width <= 390 ? "@mobile " : ""}controls and expanded forms fit at ${width}px`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByLabel("研究服务 Token")).toBeVisible();
    await expectContainedLayout(page);
    const credentials = await connectResearch(page);
    const headers = { Authorization: `Bearer ${credentials.gui}` };
    const factors = await (await page.request.get("/api/v1/factors", { headers })).json();
    const factorName = "layout_fixture";
    if (!factors.items.some((factor: { name: string }) => factor.name === factorName)) {
      const response = await page.request.post("/api/v1/factors", {
        headers,
        data: { name: factorName, expression: "$close/(TS_MEAN($close,20)+1e-8)-1", categories: [] },
      });
      expect(response.ok()).toBeTruthy();
    }

    for (const route of routes) {
      await test.step(route, async () => {
        await page.locator(`nav a[href="${route}"]`).click();
        await expect(page.locator(".route-skeleton")).toHaveCount(0);
        await expect(page.locator(".content .panel").first()).toBeVisible();
        if (schemaRoutes.has(route)) await expect(page.locator('select[aria-label="数据集"]').first()).toBeVisible();
        // Inspect expanded parameter groups as well as the initial collapsed view.
        await page.locator(".content details").evaluateAll(elements => elements.forEach(el => { (el as HTMLDetailsElement).open = true; }));
        await expectContainedLayout(page);

        if (route === "/library") {
          const checkbox = page.getByRole("checkbox", { name: `选择 ${factorName}`, exact: true });
          await checkbox.check();
          await expect(checkbox).toBeChecked();
          await expect(page.locator("aside.panel select[aria-label='数据集']")).toBeVisible();
          await page.locator("aside.panel details").evaluateAll(elements => elements.forEach(el => { (el as HTMLDetailsElement).open = true; }));
          await expectContainedLayout(page);
        }
        if (route === "/mining") {
          const checkbox = page.getByRole("checkbox", { name: "保存合格因子到库", exact: true }).first();
          await checkbox.uncheck();
          await checkbox.focus();
          await page.keyboard.press("Space");
          await expect(checkbox).toBeChecked();
        }
      });
    }
    await page.locator('nav a[href="/mining"]').click();
    await expect(page.locator('select[aria-label="数据集"]').first()).toBeVisible();
    await page.getByRole("button", { name: "深色模式", exact: true }).click();
    await page.locator(".content details").evaluateAll(elements => elements.forEach(el => { (el as HTMLDetailsElement).open = true; }));
    await expectContainedLayout(page);
  });
}
