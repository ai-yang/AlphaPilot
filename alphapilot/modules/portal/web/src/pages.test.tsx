import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nProvider } from "./i18n";
import { klineAxisType, klineCategoryTicks, klineIsIntraday, klineTimeLabel, LibraryPage, TimingPage } from "./pages";
import { ToastProvider } from "./toast";
import { setResearchToken } from "./researchClient";
import { fixtureAsset, mockResearchFetch } from "./testResearch";
beforeEach(() => setResearchToken("apr_fixture"));

vi.mock("react-plotly.js", () => ({ default: () => null }));

const klineRow = (date: string) => ({
  date, open: 1, high: 1, low: 1, close: 1, volume: 1, amount: 1, turn: 1, pctChg: 0,
});

describe("kline axis selection", () => {
  it("treats date-only / midnight bars as daily (date axis)", () => {
    const daily = [klineRow("2026-06-23"), klineRow("2026-06-24T00:00:00")];
    expect(klineIsIntraday(daily)).toBe(false);
    expect(klineAxisType(daily)).toBe("date");
  });

  it("treats intraday timestamps as minute (category axis, no gaps)", () => {
    const intraday = [klineRow("2026-06-23T09:35:00"), klineRow("2026-06-23 09:40:00")];
    expect(klineIsIntraday(intraday)).toBe(true);
    expect(klineAxisType(intraday)).toBe("category");
  });
});

describe("intraday axis tick labels", () => {
  it("formats time-of-day as 24h HH:MM without date", () => {
    expect(klineTimeLabel("2026-06-23T09:35:00")).toBe("09:35");
    expect(klineTimeLabel("2026-06-23 13:00:00")).toBe("13:00");
  });

  it("returns sparse evenly-spaced ticks including the first and last bar, time-only", () => {
    const rows = Array.from({ length: 48 }, (_, i) => {
      const hh = String(9 + Math.floor(i / 12)).padStart(2, "0");
      const mm = String((i % 12) * 5).padStart(2, "0");
      return klineRow(`2026-06-23T${hh}:${mm}:00`);
    });
    const { tickvals, ticktext } = klineCategoryTicks(rows, undefined, 7);
    expect(tickvals.length).toBeGreaterThan(1);
    expect(tickvals.length).toBeLessThanOrEqual(7);
    expect(tickvals[0]).toBe(0);
    expect(tickvals[tickvals.length - 1]).toBe(47);
    expect(ticktext.every((s) => /^\d{2}:\d{2}$/.test(s))).toBe(true);
  });

  it("restricts ticks to the visible (zoomed) index window", () => {
    const rows = Array.from({ length: 48 }, (_, i) => klineRow(`2026-06-23T10:${String(i).padStart(2, "0")}:00`));
    const { tickvals } = klineCategoryTicks(rows, [23.5, 47.5], 5);
    expect(tickvals[0]).toBe(24);
    expect(tickvals[tickvals.length - 1]).toBe(47);
  });
});

type MockFactor = {
  factor_name: string;
  factor_expression: string;
  categories?: string[];
};

type MockStrategy = {
  strategy_name: string;
  metrics?: Record<string, unknown>;
};

function renderLibraryPage() {
  return render(
    <I18nProvider>
      <ToastProvider>
        <LibraryPage />
      </ToastProvider>
    </I18nProvider>,
  );
}

function renderTimingPage() {
  return render(
    <I18nProvider>
      <ToastProvider>
        <TimingPage />
      </ToastProvider>
    </I18nProvider>,
  );
}

function mockPortalFetch({
  factors = [],
  strategies = [],
}: {
  factors?: MockFactor[];
  strategies?: MockStrategy[];
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/factors" && (!init || init.method === undefined)) {
      return Response.json({ factors, categories: [], supports_categories: true });
    }
    if (path === "/api/strategies" && (!init || init.method === undefined)) {
      return Response.json({ strategies, names: strategies.map((strategy) => strategy.strategy_name) });
    }
    if (path === "/api/report-factors/ocr-providers") {
      return Response.json({
        default_provider: "azure",
        modes: ["auto", "local", "azure"],
        providers: [{ provider_id: "azure", display_name: "Azure Document Intelligence", source: "built_in" }],
      });
    }
    if (path === "/api/factors" && init?.method === "POST") {
      return Response.json({
        acceptable: false,
        code: "duplicate_expression",
        message: "An identical factor expression already exists in the zoo.",
        details: { factor_name: "existing_factor" },
      });
    }
    if (path.startsWith("/api/factors/") && init?.method === "DELETE") {
      return Response.json({ deleted: true });
    }
    if (path.startsWith("/api/strategies/") && init?.method === "DELETE") {
      return Response.json({ deleted: true });
    }
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockTimingFetch(optionalAuth = false) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/portal/security") {
      return Response.json({
        operator_auth_required: !optionalAuth,
        operator_auth_mode: optionalAuth ? "optional" : "required",
        source: "settings",
        pending_required: !optionalAuth,
        pending_mode: optionalAuth ? "optional" : "required",
        pending_source: "settings",
        restart_required: false,
        bind_host: "0.0.0.0",
        bind_port: 19901,
        bind_address: "0.0.0.0:19901",
        network_exposed: true,
        automated_live_enabled: true,
        cors_policy: "wildcard",
        warning: optionalAuth ? "high risk" : "",
      });
    }
    if (path === "/api/trading/strategy-definitions") {
      return Response.json({
        definitions: [
          {
            strategy_id: "boll_mean_reversion",
            version: "1.0.0",
            signal_kind: "instrument_timing",
            description: "BOLL mean reversion",
            parameter_schema: { properties: { window: { default: 20 }, num_std: { default: 2 } } },
          },
          {
            strategy_id: "dual_ma",
            version: "1.0.0",
            signal_kind: "instrument_timing",
            description: "Dual moving average",
            parameter_schema: { properties: { short_window: { default: 5 }, long_window: { default: 20 } } },
          },
        ],
      });
    }
    if (path === "/api/trading/strategy-instances") {
      return Response.json({ instances: [{
        instance_id: "boll_demo", strategy_id: "boll_mean_reversion",
        validation_state: "validated", config_hash: "abc1234567890",
      }] });
    }
    if (path === "/api/trading/strategy-instances/boll_demo/preview" && init?.method === "POST") {
      return Response.json({
        signal: { as_of: "2026-01-01", payload: { scores: { "000001.SZSE": 1 }, states: { "000001.SZSE": "long" } } },
      });
    }
    if (path === "/api/trading/strategy-instances/boll_demo/backtest-runs" && init?.method === "POST") {
      return Response.json({ run_id: "timing-job", status: "running" });
    }
    if (path === "/api/trading/backtest-runs/timing-job") {
      return Response.json({ run_id: "timing-job", status: "running" });
    }
    if (path === "/api/jobs") {
      return Response.json([]);
    }
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function hasDeleteCall(fetchMock: ReturnType<typeof mockPortalFetch>, path: string) {
  return fetchMock.mock.calls.some(([input, init]) => String(input) === path && init?.method === "DELETE");
}

function postedJson(fetchMock: ReturnType<typeof mockTimingFetch>, path: string) {
  const call = fetchMock.mock.calls.find(([input, init]) => String(input) === path && init?.method === "POST");
  if (!call) return null;
  return JSON.parse(String(call[1]?.body || "{}")) as Record<string, unknown>;
}

afterEach(() => {
  cleanup();
  setResearchToken("");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("LibraryPage v1 assets", () => {
  it("keeps the form when expression admission rejects a duplicate", async () => {
    const fetch = mockResearchFetch((path, init) => {
      if (path === "/api/v1/factors" && init?.method === "POST") return Response.json({ code: "duplicate_expression", message: "Expression already exists" }, { status: 422 });
    });
    renderLibraryPage();
    const aside = screen.getByRole("heading", { name: "创建资产" }).closest("aside")!;
    const name = within(aside).getByLabelText("名称");
    const expression = within(aside).getByLabelText("表达式");
    fireEvent.change(name, { target: { value: "new_factor" } });
    fireEvent.change(expression, { target: { value: "$close/$open" } });
    fireEvent.submit(name.closest("form")!);
    expect(await screen.findByText(/Expression already exists/)).toBeInTheDocument();
    expect(name).toHaveValue("new_factor"); expect(expression).toHaveValue("$close/$open");
    expect(fetch.mock.calls.filter(([p, init]) => p === "/api/v1/factors" && init?.method === "POST")).toHaveLength(1);
  });

  it("reviews extracted drafts before explicitly committing them", async () => {
    const draft = { draft_id: "draft-1", factor_name: "momentum", factor_expression: "$close/$open", categories: [] };
    const fetch = mockResearchFetch((path, init) => {
      if (path === "/api/v1/jobs/report-job/result") return Response.json({ availability: "complete", summary: { factors: [draft] } });
      if (path === "/api/v1/jobs/report-job") return Response.json({ status: "succeeded", progress: {}, run_ids: [] });
      if (path.startsWith("/api/v1/jobs/report-job/logs")) return Response.json({ text: "", next_cursor: 0, complete: true });
      if (path === "/api/v1/report-factors/commit") return Response.json({ imported: 1 });
    });
    renderLibraryPage();
    fireEvent.change(screen.getByLabelText("提取任务 ID"), { target: { value: "report-job" } });
    fireEvent.click(screen.getByText("读取提取结果"));
    await screen.findByDisplayValue("momentum");
    expect(fetch.mock.calls.some(([p]) => p === "/api/v1/report-factors/commit")).toBe(false);
    fireEvent.change(screen.getByLabelText("因子名称"), { target: { value: "reviewed" } });
    fireEvent.click(screen.getByLabelText("选择入库"));
    fireEvent.click(screen.getByText("保存选中因子"));
    await waitFor(() => expect(fetch.mock.calls.some(([p]) => p === "/api/v1/report-factors/commit")).toBe(true));
    const call = fetch.mock.calls.find(([p]) => p === "/api/v1/report-factors/commit")!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({ job_id: "report-job", factors: [{ ...draft, factor_name: "reviewed" }] });
  });

  it.each(["factor", "strategy"] as const)("requires confirmation and an observed version to delete a %s", async kind => {
    const row = fixtureAsset("confirmed_asset", kind);
    const collection = kind === "factor" ? "factors" : "strategies";
    const fetch = mockResearchFetch((path, init) => {
      if (path.startsWith(`/api/v1/${collection}?`)) return Response.json({ items: [row], next_cursor: null });
      if (init?.method === "DELETE") return Response.json({ deleted: true });
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderLibraryPage();
    if (kind === "strategy") fireEvent.click(screen.getByText("策略库"));
    const element = (await screen.findByText("confirmed_asset")).closest("tr")!;
    fireEvent.click(within(element).getByText("删除"));
    expect(fetch.mock.calls.some(([,init]) => init?.method === "DELETE")).toBe(false);
    confirm.mockReturnValue(true); fireEvent.click(within(element).getByText("删除"));
    await waitFor(() => expect(fetch.mock.calls.some(([,init]) => init?.method === "DELETE")).toBe(true));
    const call = fetch.mock.calls.find(([,init]) => init?.method === "DELETE")!;
    expect(call[0]).toBe(`/api/v1/${collection}/${row.id}`);
    expect(new Headers(call[1]?.headers).get("If-Match")).toBe("2");
  });
});

describe("TimingPage", () => {
  it("hides the token field and warns on optional operator authentication", async () => {
    mockTimingFetch(true);
    renderTimingPage();

    expect(await screen.findByText(/Portal 操作员鉴权为 optional/)).toBeInTheDocument();
    expect(screen.getByText(/0\.0\.0\.0:19901/)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("apop_…")).not.toBeInTheDocument();
  });

  it("previews signals and starts a timing backtest job", async () => {
    const fetchMock = mockTimingFetch();
    renderTimingPage();

    expect(await screen.findByText("BOLL mean reversion")).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("运行实例"), { target: { value: "boll_demo" } });

    fireEvent.click(screen.getByRole("button", { name: "预览信号" }));
    await waitFor(() => {
      expect(postedJson(fetchMock, "/api/trading/strategy-instances/boll_demo/preview")).not.toBeNull();
    });
    expect(await screen.findByText("000001.SZSE")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "运行择时回测" }));
    await waitFor(() => {
      expect(postedJson(fetchMock, "/api/trading/strategy-instances/boll_demo/backtest-runs")).not.toBeNull();
    });
    expect(await screen.findByText("timing-job")).toBeInTheDocument();
  });
});
