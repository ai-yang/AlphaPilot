import { vi } from "vitest";
import type { Asset } from "./research.generated";

export const fixtureDataset = { dataset_id: "fixture", label: "Fixture dataset", source: "test", freq: "day", adjust_mode: "none", ready: true, unavailable_reason: null, revision: "1" };
export function fixtureAsset(name: string, kind: Asset["kind"] = "factor"): Asset {
  return { id: name, name, kind, revision: 2, metadata: { expression: "$close", categories: [], symbols: ["600000.SH"] } };
}
export function researchFallback(path: string) {
  const base = path.split("?")[0];
  if (base === "/api/v1/datasets") return Response.json({ items: [fixtureDataset], next_cursor: null });
  if (base === "/api/v1/templates") return Response.json({ items: [{ template_id: "combined", label: "Combined", ready: true, parameters: {} }], next_cursor: null });
  if (base === "/api/v1/models") return Response.json({ items: [{ model_id: "lgbm", label: "LightGBM" }], next_cursor: null });
  if (base === "/api/v1/factors/categories") return Response.json({ categories: [], items: [], supports_categories: true });
  if (base === "/api/v1/report-factors/ocr-providers") return Response.json({ modes: ["auto"], providers: [] });
  if (["factors", "strategies", "stock-pools", "signal-sessions", "runs", "jobs", "schedules"].some(p => base === `/api/v1/${p}`)) return Response.json({ items: [], next_cursor: null, total: 0 });
  if (base === "/api/v1/schedules/runtime/status") return Response.json({ running: true, paused: false });
  return Response.json({ code: "NOT_FOUND", message: path }, { status: 404 });
}
export function mockResearchFetch(handler?: (path: string, init?: RequestInit) => Response | Promise<Response> | undefined) {
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => handler?.(String(input), init) ?? Promise.resolve(researchFallback(String(input))));
  vi.stubGlobal("fetch", mock);
  return mock;
}
