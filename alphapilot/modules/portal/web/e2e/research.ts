import { expect, type Page } from "@playwright/test";

export async function connectResearch(page: Page) {
  const credentials = await (await page.request.get("/__test__/credentials")).json();
  await page.getByLabel("研究服务 Token").fill(credentials.gui);
  await page.getByRole("button", { name: "连接研究服务", exact: true }).click();
  await expect(page.getByRole("button", { name: "断开研究服务" })).toBeVisible();
  return credentials as { gui: string; external: string };
}
