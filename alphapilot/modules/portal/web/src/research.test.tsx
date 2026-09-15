import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api, setOperatorToken } from "./api";
import { research, setResearchToken, getResearchToken, type Catalogs } from "./researchClient";
import { JobEditor } from "./ResearchForms";
import { ResearchJobs } from "./ResearchJobs";
import { ResearchGate } from "./ResearchConnection";

const catalogs: Catalogs = { datasets: [{ dataset_id: "fixture", label: "Fixture dataset", ready: true, source: "test", freq: "day", adjust_mode: "none", unavailable_reason: null, revision: "1" }], templates: [], models: [], factors: [{ id: "factor-one", revision: 2, kind: "factor", name: "Factor one", metadata: {} }], strategies: [], pools: [], sessions: [] };
beforeEach(() => { setResearchToken("apr_test"); });
afterEach(() => { setResearchToken(""); setOperatorToken(""); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
function mockResponse(body: unknown, status = 200) { return { ok: status < 400, status, json: async () => body }; }

it("uses separate memory-only credentials for research and trading", async () => {
  const fetch = vi.fn().mockResolvedValue(mockResponse({})); vi.stubGlobal("fetch", fetch);
  setOperatorToken("trade_only");
  await research.get("/capabilities"); await api.get("/api/trading/accounts");
  expect(new Headers(fetch.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer apr_test");
  expect(new Headers(fetch.mock.calls[1][1].headers).get("Authorization")).toBe("Bearer trade_only");
  expect(Object.values(localStorage)).not.toContain("apr_test");
});

it("sends observed asset revisions and a stable caller supplied idempotency key", async () => {
  const fetch = vi.fn().mockResolvedValue(mockResponse({})); vi.stubGlobal("fetch", fetch);
  await research.edit("/factors/factor-one", { name: "renamed" }, 2);
  await research.post("/jobs", { kind: "mine", input: { dataset_id: "fixture", max_steps: 1 } }, "intent-one");
  expect(new Headers(fetch.mock.calls[0][1].headers).get("If-Match")).toBe("2");
  expect(new Headers(fetch.mock.calls[1][1].headers).get("Idempotency-Key")).toBe("intent-one");
  expect(fetch.mock.calls.every(c => c[0].startsWith("/api/v1/"))).toBe(true);
});

it("disconnects on revoked credentials and gates subsequent research requests", async () => {
  const fetch = vi.fn().mockResolvedValue(mockResponse({ code: "UNAUTHENTICATED", message: "Revoked" }, 401)); vi.stubGlobal("fetch", fetch);
  render(<ResearchGate><div>Private workspace</div></ResearchGate>);
  await act(async () => { await expect(research.get("/jobs")).rejects.toThrow("Revoked"); });
  await waitFor(() => expect(screen.queryByText("Private workspace")).not.toBeInTheDocument());
  expect(getResearchToken()).toBe("");
  await expect(research.get("/jobs")).rejects.toThrow("请先连接"); expect(fetch).toHaveBeenCalledTimes(1);
});

it("derives the finite mining budget and resource IDs from the published schema", async () => {
  const submit = vi.fn().mockResolvedValue({ job_id: "new" });
  render(<JobEditor kinds={["mine"]} catalogs={catalogs} onSubmit={submit} />);
  fireEvent.change(screen.getByLabelText("数据集"), { target: { value: "fixture" } });
  fireEvent.change(screen.getByLabelText("最大步数"), { target: { value: "3" } });
  fireEvent.submit(screen.getByText("提交任务").closest("form")!);
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0]).toMatchObject({ kind: "mine", input: { dataset_id: "fixture", max_steps: 3 }, budget: { timeout_seconds: 3600 } });
  expect(submit.mock.calls[0][0].input).not.toHaveProperty("qlib_dir");
});

it("preserves the intent key when a transport failure is retried", async () => {
  const submit = vi.fn().mockRejectedValueOnce(new Error("connection lost")).mockResolvedValue({ job_id: "same" });
  render(<JobEditor kinds={["mine"]} catalogs={catalogs} onSubmit={submit} />);
  const form = screen.getByText("提交任务").closest("form")!;
  fireEvent.submit(form); await screen.findByRole("alert"); fireEvent.submit(form);
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
  expect(submit.mock.calls[0][1]).toBe(submit.mock.calls[1][1]);
});

it("submits the explicit inline factor source discriminator", async () => {
  const submit = vi.fn().mockResolvedValue({ job_id: "inline" });
  render(<JobEditor kinds={["factor_backtest"]} catalogs={catalogs} onSubmit={submit} />);
  fireEvent.change(screen.getByLabelText("factor_source type"), { target: { value: "inline" } });
  fireEvent.change(screen.getByLabelText("内联因子表达式"), { target: { value: '[{"name":"test","expression":"$close/(TS_MEAN($close,20)+1e-8)-1"}]' } });
  fireEvent.submit(screen.getByText("提交任务").closest("form")!);
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0].input.factor_source).toEqual({ type: "inline", factors: [{ name: "test", expression: "$close/(TS_MEAN($close,20)+1e-8)-1" }] });
});

it("keeps a selected job visible when paging the queue and cancels queued jobs", async () => {
  const job = { job_id: "queued-one", status: "queued", kind: "mine", client_id: "mcp", progress: { percent: null, stage: "queued" }, run_ids: [] };
  const fetch = vi.fn().mockImplementation(async (url: string) => {
    if (url.includes("/logs")) return mockResponse({ text: "", next_cursor: 0, complete: false });
    if (url.includes("/result")) return mockResponse({ availability: "pending", summary: null });
    if (url.includes("/jobs/queued-one")) return mockResponse(job);
    return mockResponse({ items: url.includes("cursor=next") ? [] : [job], next_cursor: url.includes("cursor=next") ? null : "next" });
  }); vi.stubGlobal("fetch", fetch);
  render(<ResearchJobs />);
  fireEvent.click(await screen.findByText("queued-one"));
  await waitFor(() => expect(fetch.mock.calls.some(c => c[0] === "/api/v1/jobs/queued-one")).toBe(true));
  fireEvent.click(screen.getByText("取消"));
  await waitFor(() => expect(fetch.mock.calls.some(c => c[0] === "/api/v1/jobs/queued-one/cancel")).toBe(true));
  fireEvent.click(screen.getByText("下一页"));
  await waitFor(() => expect(fetch.mock.calls.some(c => c[0].includes("cursor=next"))).toBe(true));
  expect(screen.getByRole("heading", { name: /queued-one/ })).toBeInTheDocument();
});

it("compares full-result metrics and preserves a zero metric when ranking runs", async () => {
  const { ResearchCompare } = await import("./ResearchCompare");
  vi.spyOn(research, "text").mockImplementation(async artifact => JSON.stringify({ metrics: { IC: artifact.artifact_id === "a" ? 0 : -.1 } }));
  const runs: import("./research.generated").Run[] = ["a", "b"].map(id => ({ run_id: id, job_id: null, metadata: { status: "succeeded" }, artifacts: [{ artifact_id: id, run_id: id, job_id: null, kind: "evaluation", schema_version: "1", media_type: "application/json", size: 20, sha256: "a".repeat(64), name: `${id}.json`, created_at: "2026-01-05T00:00:00Z", content_url: `/api/v1/artifacts/${id}/content` }] }));
  const view = render(<ResearchCompare runs={runs} />);
  await waitFor(() => expect(view.container.querySelectorAll("tbody tr")).toHaveLength(2));
  expect(view.container.querySelector("tbody tr td")?.textContent).toBe("a");
  fireEvent.click(screen.getByLabelText("按指标升序"));
  expect(view.container.querySelector("tbody tr td")?.textContent).toBe("b");
});
