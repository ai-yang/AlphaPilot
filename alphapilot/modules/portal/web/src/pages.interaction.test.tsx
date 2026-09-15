import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { I18nProvider } from "./i18n";
import { AdvancedPage, BacktestPage, DailyTradePage, MarketPage, MiningPage, NotificationsPage, SchedulerPage, TimingPage } from "./pages";
import { ToastProvider } from "./toast";
import { setResearchToken } from "./researchClient";
import { mockResearchFetch, fixtureAsset } from "./testResearch";
import { JobDetail } from "./ResearchJobs";
import { LibraryPage } from "./ResearchPages";
beforeEach(() => setResearchToken("apr_fixture"));

vi.mock("react-plotly.js", () => ({ default: () => null }));

function renderPage(page: ReactNode) {
  return render(<I18nProvider><ToastProvider>{page}</ToastProvider></I18nProvider>);
}

function bodyOf(call: [RequestInfo | URL, RequestInit?]) {
  return JSON.parse(String(call[1]?.body || "{}")) as Record<string, unknown>;
}

afterEach(() => {
  cleanup();
  setResearchToken("");
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Research workbench v1 interactions", () => {
  it("stops detail polling once the result and incremental log are terminal", async () => {
    vi.useFakeTimers();
    const fetch = mockResearchFetch(path => {
      if (path.endsWith("/result")) return Response.json({ availability: "complete", summary: {} });
      if (path.includes("/logs?")) return Response.json({ text: "done", next_cursor: 4, complete: true });
      if (path === "/api/v1/jobs/data-job") return Response.json({ status: "succeeded", progress: {}, run_ids: [] });
    });
    renderPage(<JobDetail jobId="data-job" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(fetch.mock.calls.filter(([p]) => p === "/api/v1/jobs/data-job")).toHaveLength(1);
    expect(screen.getByText("done")).toBeInTheDocument();
  });

  it("creates and edits pool members through versioned assets", async () => {
    let pool: ReturnType<typeof fixtureAsset> | undefined;
    const fetch = mockResearchFetch((path, init) => {
      if (path.startsWith("/api/v1/stock-pools?") && !init?.method) return Response.json({ items: pool ? [pool] : [], next_cursor: null });
      if (path === "/api/v1/stock-pools" && init?.method === "POST") {
        const body = JSON.parse(String(init.body)); pool = { ...fixtureAsset(body.name, "stock_pool"), metadata: body }; return Response.json(pool);
      }
      if (path === "/api/v1/stock-pools/qa_pool" && init?.method === "PATCH") return Response.json({ updated: true });
    });
    renderPage(<LibraryPage />); fireEvent.click(screen.getByText("股票池"));
    const form = screen.getByRole("heading", { name: "创建资产" }).closest("form")!;
    fireEvent.change(within(form).getByLabelText("名称"), { target: { value: "qa_pool" } });
    fireEvent.change(within(form).getByLabelText("股票代码列表"), { target: { value: '["600000.SH"]' } });
    await within(form).findByRole("option", { name: "Fixture dataset" });
    fireEvent.change(within(form).getByLabelText("数据集"), { target: { value: "fixture" } });
    fireEvent.submit(form);
    const row = (await screen.findByText("qa_pool")).closest("tr")!; fireEvent.click(within(row).getByText("编辑"));
    const edit = screen.getByRole("heading", { name: /编辑 qa_pool/ }).closest("form")!;
    fireEvent.change(within(edit).getByLabelText("股票代码列表"), { target: { value: '["600000.SH","600085.SH"]' } });
    fireEvent.submit(edit);
    await waitFor(() => expect(fetch.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true));
    const call = fetch.mock.calls.find(([, init]) => init?.method === "PATCH")!;
    expect(JSON.parse(String(call[1]?.body)).symbols).toEqual(["600000.SH", "600085.SH"]);
    expect(new Headers(call[1]?.headers).get("If-Match")).toBe("2");
  });

  it("preserves a mining direction while resource catalogs load", async () => {
    let resolve: ((r: Response) => void) | undefined;
    mockResearchFetch(path => path.startsWith("/api/v1/stock-pools?") ? new Promise<Response>(r => { resolve = r; }) : undefined);
    renderPage(<MiningPage />);
    const direction = screen.getByLabelText("挖掘方向"); fireEvent.change(direction, { target: { value: "量价方向" } });
    await act(async () => { resolve?.(Response.json({ items: [fixtureAsset("late_pool", "stock_pool")], next_cursor: null })); });
    expect((await screen.findAllByRole("option", { name: "late_pool" })).length).toBeGreaterThan(0);
    expect(direction).toHaveValue("量价方向");
  });

  it.each([MiningPage, BacktestPage])("keeps the latest run selection when an older detail resolves last", async Page => {
    const pending = new Map<string, (r: Response) => void>();
    const run = (id: string) => ({ run_id: id, job_id: null, artifacts: [], metadata: { command: "mine", status: "succeeded", marker: `detail-${id}` } });
    mockResearchFetch(path => {
      if (path.startsWith("/api/v1/runs?")) return Response.json({ items: [run("old"), run("new")], next_cursor: null });
      if (path.startsWith("/api/v1/runs/")) return new Promise<Response>(r => pending.set(path, r));
    });
    renderPage(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: "old" }));
    fireEvent.click(screen.getByRole("button", { name: "new" }));
    await act(async () => { pending.get("/api/v1/runs/new")?.(Response.json(run("new"))); });
    expect(await screen.findByText(/detail-new/)).toBeInTheDocument();
    await act(async () => { pending.get("/api/v1/runs/old")?.(Response.json(run("old"))); });
    expect(screen.queryByText(/detail-old/)).not.toBeInTheDocument();
  });

  it("clears one-off strategy and cash when switching to a session", async () => {
    const fetch = mockResearchFetch((path, init) => {
      if (path.startsWith("/api/v1/signal-sessions?")) return Response.json({ items: [fixtureAsset("session", "signal_session")], next_cursor: null });
      if (path.startsWith("/api/v1/strategies?")) return Response.json({ items: [fixtureAsset("strategy", "strategy")], next_cursor: null });
      if (path === "/api/v1/jobs" && init?.method === "POST") return Response.json({ job_id: "daily" });
    });
    renderPage(<DailyTradePage />);
    const form = screen.getByLabelText("信号来源").closest("form")!;
    await screen.findAllByRole("option", { name: "strategy" });
    fireEvent.change(within(form).getByLabelText("策略资产"), { target: { value: "strategy" } });
    fireEvent.change(within(form).getByLabelText("初始资金"), { target: { value: "300000" } });
    fireEvent.change(within(form).getByLabelText("信号来源"), { target: { value: "session" } });
    fireEvent.change(within(form).getByLabelText("模拟会话"), { target: { value: "session" } });
    fireEvent.change(within(form).getByLabelText("执行模式"), { target: { value: "advance" } });
    fireEvent.submit(form);
    await waitFor(() => expect(fetch.mock.calls.some(([p]) => p === "/api/v1/jobs")).toBe(true));
    const call = fetch.mock.calls.find(([p]) => p === "/api/v1/jobs")!;
    expect(JSON.parse(String(call[1]?.body)).input).toMatchObject({ session_id: "session", mode: "advance" });
    expect(JSON.parse(String(call[1]?.body)).input).not.toHaveProperty("strategy_id");
    expect(JSON.parse(String(call[1]?.body)).input).not.toHaveProperty("init_cash");
  });

  it("drops data fields when changing a schedule to mining", async () => {
    const fetch = mockResearchFetch((path, init) => path === "/api/v1/schedules" && init?.method === "POST" ? Response.json({ schedule_id: "new" }) : undefined);
    renderPage(<SchedulerPage />);
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "mining schedule" } });
    fireEvent.change(screen.getByLabelText("任务类型"), { target: { value: "data" } });
    fireEvent.change(screen.getByText("数据操作").querySelector("select")!, { target: { value: "download" } });
    fireEvent.change(screen.getByLabelText("任务类型"), { target: { value: "mine" } });
    fireEvent.change(screen.getByLabelText("最大步数"), { target: { value: "2" } });
    fireEvent.submit(screen.getByText("保存调度").closest("form")!);
    await waitFor(() => expect(fetch.mock.calls.some(([p]) => p === "/api/v1/schedules")).toBe(true));
    const call = fetch.mock.calls.find(([p]) => p === "/api/v1/schedules")!;
    const job = JSON.parse(String(call[1]?.body)).job;
    expect(job.kind).toBe("mine"); expect(job.input).not.toHaveProperty("action"); expect(job.input).not.toHaveProperty("start_date");
  });
});

describe("NotificationsPage secret handling", () => {
  it("keeps a configured secret masked and submits the preservation marker", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/notify" && init?.method === "PATCH") return Response.json({ saved: true });
      if (path === "/api/notify") return Response.json({
        config: { telegram: { bot_token: "********" }, options: { notify_on_all_jobs: false } },
        fields: { telegram: [["bot_token", "secret"]] },
        configured_channels: ["telegram"],
        credentials_path: "/isolated/notify.json",
        masked_secret: "********",
      });
      if (path === "/api/notify/commands/status") return Response.json({ daemon: { running: false }, events: [] });
      if (path.startsWith("/api/notify/test") && init?.method === "POST") return Response.json({ ok: true });
      if (path === "/api/v1/commands/plan" && init?.method === "POST") return Response.json({ action: "jobs" });
      if (path === "/api/notify/commands/start" && init?.method === "POST") return Response.json({ started: true });
      if (path === "/api/notify/commands/pair-code" && init?.method === "POST") return Response.json({ code: "123456", expires_at: "2026-07-11T13:00:00" });
      if (path === "/api/notify/commands/register-menu" && init?.method === "POST") return Response.json({ registered: true });
      return Response.json({}, { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPage(<NotificationsPage />);

    await user.click(await screen.findByText("telegram"));
    const token = screen.getByLabelText("bot_token");
    expect(token).toHaveValue("");
    expect(token).toHaveAttribute("placeholder", "已配置 - 留空表示保持不变");
    const section = screen.getByRole("heading", { name: "发送渠道" }).closest("section") as HTMLElement;
    await user.click(within(section).getByRole("button", { name: "保存" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) => String(path) === "/api/notify" && init?.method === "PATCH")).toBe(true));
    const call = fetchMock.mock.calls.find(([path, init]) => String(path) === "/api/notify" && init?.method === "PATCH") as [RequestInfo | URL, RequestInit?];
    expect((((bodyOf(call).config as Record<string, unknown>).telegram as Record<string, unknown>).bot_token)).toBe("********");
    await user.click(screen.getByLabelText("所有后台任务完成后通知"));
    await user.click(within(section).getByRole("button", { name: "测试 telegram" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "仅规划" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "仅规划" }));
    await screen.findByText(/"action": "jobs"/);
    await user.click(screen.getByRole("button", { name: "生成配对码" }));
    await screen.findByText("123456");
    await user.click(screen.getByRole("button", { name: "注册命令菜单" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "启动接收器" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "启动接收器" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/notify/commands/start")).toBe(true));
  });
});

describe("AdvancedPage destructive action separation", () => {
  it("sends preview with execute=false and cancellation never sends execute=true", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/portal/settings") return Response.json({
        settings: { host: "127.0.0.1", port: 19901, timezone: "Asia/Shanghai" },
        current: { host: "127.0.0.1", port: 19901, timezone: "Asia/Shanghai" },
        config_path: "/isolated/portal.json", host_options: [{ value: "127.0.0.1", label: "local" }],
        timezone_options: ["Asia/Shanghai"], restart_required: false,
      });
      if (path === "/api/portal/security") return Response.json({
        operator_auth_required: false, operator_auth_mode: "optional", source: "settings",
        pending_required: false, pending_mode: "optional", pending_source: "settings",
        restart_required: false, bind_host: "0.0.0.0", bind_port: 19901,
        bind_address: "0.0.0.0:19901", network_exposed: true,
        automated_live_enabled: true, cors_policy: "wildcard", warning: "high risk",
      });
      if (path === "/api/portal/env") return Response.json({
        fields: [{ key: "OPENAI_API_KEY", label: "LLM key", group: "LLM", kind: "password", secret: true, requires_restart: true }],
        values: { OPENAI_API_KEY: "********" }, current: { OPENAI_API_KEY: "********" },
        config_path: "/isolated/.env", restart_required: false, restart_required_keys: [], masked_secret: "********",
      });
      if (path === "/api/modules") return Response.json({ portal: { commands: [{ name: "scheduler" }] } });
      if (path === "/api/logs/cleanup" && init?.method === "POST") return Response.json({ log_root: "/isolated/log", execute: bodyOf([input, init]).execute, removed: 0, paths: ["/isolated/log/stub"] });
      return Response.json({}, { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderPage(<AdvancedPage />);

    expect(await screen.findByRole("heading", { name: "操作员鉴权状态" })).toBeInTheDocument();
    expect(screen.getByText(/Portal 操作员鉴权为 optional/)).toBeInTheDocument();
    const section = (await screen.findByRole("heading", { name: "日志清理" })).closest("section") as HTMLElement;
    expect(screen.getByPlaceholderText("已配置 - 留空表示保持不变")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "保存环境设置" }));
    await user.click(screen.getByRole("button", { name: "保存门户设置" }));
    await user.click(within(section).getByRole("button", { name: "预览" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) => String(path) === "/api/logs/cleanup" && init?.method === "POST")).toBe(true));
    await user.click(within(section).getByRole("button", { name: "删除" }));
    const calls = fetchMock.mock.calls.filter(([path, init]) => String(path) === "/api/logs/cleanup" && init?.method === "POST");
    expect(calls).toHaveLength(1);
    expect(bodyOf(calls[0] as [RequestInfo | URL, RequestInit?]).execute).toBe(false);
    const envCall = fetchMock.mock.calls.find(([path, init]) => String(path) === "/api/portal/env" && init?.method === "PATCH") as [RequestInfo | URL, RequestInit?];
    expect((bodyOf(envCall).values as Record<string, unknown>).OPENAI_API_KEY).toBe("");
  });
});
