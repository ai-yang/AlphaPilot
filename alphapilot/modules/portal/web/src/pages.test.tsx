import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nProvider } from "./i18n";
import { LibraryPage } from "./pages";
import { ToastProvider } from "./toast";

vi.mock("react-plotly.js", () => ({ default: () => null }));

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

function hasDeleteCall(fetchMock: ReturnType<typeof mockPortalFetch>, path: string) {
  return fetchMock.mock.calls.some(([input, init]) => String(input) === path && init?.method === "DELETE");
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
