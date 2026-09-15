import { expect, test } from "@playwright/test";
import { connectResearch } from "./research";

test.skip(process.env.ALPHAPILOT_RUN_REAL_LLM !== "1", "Set ALPHAPILOT_RUN_REAL_LLM=1 for the opt-in external smoke test");

test("real LLM mining creates a three-step observable job", async ({ page }) => {
  test.setTimeout(20 * 60_000);
  await page.goto("/mining");
  const credentials = await connectResearch(page);
  const headers = { Authorization: `Bearer ${credentials.gui}` };
  const datasets = await (await page.request.get("/api/v1/datasets", { headers })).json();
  const dataset = datasets.items.find((row: { dataset_id: string; ready: boolean }) => row.ready && (!process.env.ALPHAPILOT_TEST_DATASET_ID || row.dataset_id === process.env.ALPHAPILOT_TEST_DATASET_ID));
  expect(dataset, "Prepare a versioned research dataset before the opt-in mining test").toBeTruthy();
  const form = page.locator("form", { has: page.getByLabel("最大步数") });
  await form.getByLabel("数据集", { exact: true }).selectOption(dataset.dataset_id);
  await form.getByLabel("最大步数").fill("3");
  await form.getByLabel("挖掘方向").fill("量价反转与短期动量的非线性组合");
  if (process.env.ALPHAPILOT_TEST_POOL_ID) await form.getByLabel("股票池（留空使用全部）").selectOption(process.env.ALPHAPILOT_TEST_POOL_ID);
  await page.request.post("/api/v1/schedules/runtime/start", { headers });
  const accepted = page.waitForResponse(response => response.url().endsWith("/api/v1/jobs") && response.request().method() === "POST");
  await form.getByRole("button", { name: "提交任务", exact: true }).click();
  const response = await accepted;
  expect(response.status()).toBe(202);
  const job = await response.json();
  const row = page.locator("table tbody tr", { hasText: job.job_id });
  await expect(row).toContainText("已完成", { timeout: 18 * 60_000 });
  await row.getByRole("button", { name: job.job_id, exact: true }).click();
  await expect(page.locator("pre.log")).toContainText(/factor|因子|expression|表达式/i);
  await expect(page.locator("pre.log")).not.toContainText(/OPENAI_API_KEY|Bearer\s+[A-Za-z0-9_-]{12,}/i);
  const result = await (await page.request.get(`/api/v1/jobs/${job.job_id}/result`, { headers })).json();
  expect(result.availability).toBe("complete");
  expect(result.run_ids.length).toBeGreaterThan(0);
});
