import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nProvider } from "./i18n";
import { klineAxisType, klineCategoryTicks, klineIsIntraday, klineTimeLabel, LibraryPage, TimingPage } from "./pages";
import { ToastProvider } from "./toast";

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

function mockTimingFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/timing/strategies") {
      return Response.json({
        names: ["boll_mean_reversion", "dual_ma"],
        strategies: [
          {
            name: "boll_mean_reversion",
            description: "BOLL mean reversion",
            defaults: { window: 20, num_std: 2 },
          },
          {
            name: "dual_ma",
            description: "Dual moving average",
            defaults: { short_window: 5, long_window: 20 },
          },
        ],
      });
    }
    if (path === "/api/timing/signal" && init?.method === "POST") {
      return Response.json({
        strategy_name: "boll_mean_reversion",
        signals: {
          columns: ["datetime", "instrument", "signal", "target_percent", "reason"],
          rows: [{ datetime: "2026-01-01", instrument: "SZ000001", signal: 1, target_percent: 1, reason: "test" }],
          row_count: 1,
          truncated: false,
        },
      });
    }
    if (path === "/api/timing/backtest" && init?.method === "POST") {
      return Response.json({
        job_id: "timing-job",
        kind: "timing_backtest",
        status: "running",
        progress: { percent: 0, stage: "queued" },
      });
    }
    if (path === "/api/jobs/timing-job/progress") {
      return Response.json({ job_id: "timing-job", status: "running", percent: 10, stage: "running" });
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
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("LibraryPage factor add", () => {
  it("keeps the form and shows an error when the API rejects a duplicate factor", async () => {
    const fetchMock = mockPortalFetch();
    renderLibraryPage();

    const nameInput = await screen.findByPlaceholderText("factor_name");
    const expressionInput = screen.getByPlaceholderText("factor_expression");

    fireEvent.change(nameInput, { target: { value: "new_factor" } });
    fireEvent.change(expressionInput, { target: { value: "$close / $open" } });

    const addPanel = nameInput.closest("aside");
    expect(addPanel).not.toBeNull();
    fireEvent.click(within(addPanel as HTMLElement).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(screen.getByText("An identical factor expression already exists in the zoo.")).toBeInTheDocument();
    });
    expect(nameInput).toHaveValue("new_factor");
    expect(expressionInput).toHaveValue("$close / $open");
    expect(fetchMock.mock.calls.filter(([path, init]) => String(path) === "/api/factors" && init?.method === "POST")).toHaveLength(1);
  });
});

describe("LibraryPage delete confirmations", () => {
  it("does not delete a factor when the confirmation is cancelled", async () => {
    const fetchMock = mockPortalFetch({
      factors: [{ factor_name: "factor_to_delete", factor_expression: "$close" }],
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderLibraryPage();

    const row = (await screen.findByText("factor_to_delete")).closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "删除" }));

    expect(confirmSpy).toHaveBeenCalledWith("删除 factor_to_delete?");
    expect(hasDeleteCall(fetchMock, "/api/factors/factor_to_delete")).toBe(false);
  });

  it("deletes a factor only after confirmation", async () => {
    const fetchMock = mockPortalFetch({
      factors: [{ factor_name: "confirmed_factor", factor_expression: "$open" }],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderLibraryPage();

    const row = (await screen.findByText("confirmed_factor")).closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(hasDeleteCall(fetchMock, "/api/factors/confirmed_factor")).toBe(true);
    });
  });

  it("does not delete a strategy when the confirmation is cancelled", async () => {
    const fetchMock = mockPortalFetch({
      strategies: [{ strategy_name: "strategy_to_delete", metrics: {} }],
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderLibraryPage();

    fireEvent.click(await screen.findByRole("button", { name: "策略" }));
    const row = (await screen.findByText("strategy_to_delete")).closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "删除" }));

    expect(confirmSpy).toHaveBeenCalledWith("删除 strategy_to_delete?");
    expect(hasDeleteCall(fetchMock, "/api/strategies/strategy_to_delete")).toBe(false);
  });

  it("deletes a strategy only after confirmation", async () => {
    const fetchMock = mockPortalFetch({
      strategies: [{ strategy_name: "confirmed_strategy", metrics: {} }],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderLibraryPage();

    fireEvent.click(await screen.findByRole("button", { name: "策略" }));
    const row = (await screen.findByText("confirmed_strategy")).closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(hasDeleteCall(fetchMock, "/api/strategies/confirmed_strategy")).toBe(true);
    });
  });
});

describe("TimingPage", () => {
  it("previews signals and starts a timing backtest job", async () => {
    const fetchMock = mockTimingFetch();
    renderTimingPage();

    expect(await screen.findByText("BOLL mean reversion")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "预览信号" }));
    await waitFor(() => {
      expect(postedJson(fetchMock, "/api/timing/signal")).not.toBeNull();
    });
    expect(await screen.findByText("SZ000001")).toBeInTheDocument();
    expect(postedJson(fetchMock, "/api/timing/signal")?.strategy_name).toBe("boll_mean_reversion");

    fireEvent.click(screen.getByRole("button", { name: "运行择时回测" }));
    await waitFor(() => {
      expect(postedJson(fetchMock, "/api/timing/backtest")).not.toBeNull();
    });
    expect(postedJson(fetchMock, "/api/timing/backtest")?.strategy_name).toBe("boll_mean_reversion");
    expect(await screen.findByText("timing-job")).toBeInTheDocument();
  });
});
