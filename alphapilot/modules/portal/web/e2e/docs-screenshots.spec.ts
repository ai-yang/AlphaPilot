import { expect, test } from "@playwright/test";
import { connectResearch } from "./research";
import fs from "node:fs";
import path from "node:path";

const enabled = process.env.ALPHAPILOT_GENERATE_DOC_SCREENSHOTS === "1";
const outputDir = path.resolve(process.cwd(), "../../../../docs/assets/portal");
const pages = [
  ["/", "home.png"],
  ["/mining", "mining.png"],
  ["/backtest", "backtest.png"],
  ["/timing", "strategy-instances.png"],
  ["/library", "library.png"],
  ["/market", "market.png"],
  ["/daily-trade", "daily-trade.png"],
  ["/live", "live.png"],
  ["/scheduler", "scheduler.png"],
  ["/notifications", "notifications.png"],
  ["/advanced", "advanced.png"],
] as const;

test.describe("documentation screenshots", () => {
  test.skip(!enabled, "run npm run docs:screenshots to refresh checked-in documentation images");

  test("capture every Portal route from isolated deterministic fixtures", async ({ page }) => {
    const externalRequests: string[] = [];
    const serverErrors: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (!["127.0.0.1", "localhost"].includes(url.hostname)) externalRequests.push(request.url());
    });
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 500) {
        serverErrors.push(`${response.status()} ${response.url()}`);
      }
    });

    fs.mkdirSync(outputDir, { recursive: true });
    for (const [route, filename] of pages) {
      await page.goto(route);
      await connectResearch(page);
      await expect(page.locator(".shell")).toBeVisible();
      await expect(page.locator(".route-skeleton")).toHaveCount(0);
      await page.evaluate(() => document.fonts.ready);
      await expect(page.locator("body")).not.toContainText(/\/home\/|[A-Za-z]:\\Users\\/);
      const passwords = page.locator('input[type="password"]');
      for (let index = 0; index < await passwords.count(); index += 1) {
        await expect(passwords.nth(index)).toHaveValue("");
      }
      await page.screenshot({ path: path.join(outputDir, filename), fullPage: true });
    }

    expect(externalRequests).toEqual([]);
    expect(serverErrors).toEqual([]);
  });
});
