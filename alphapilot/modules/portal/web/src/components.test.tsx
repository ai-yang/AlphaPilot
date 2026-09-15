import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { AsyncButton, ConfirmProvider, JobsPanel, PanelHelp, useConfirm } from "./components";
import { I18nProvider } from "./i18n";
import { ToastProvider } from "./toast";
import { setResearchToken } from "./researchClient";
beforeEach(() => setResearchToken("apr_fixture"));

afterEach(() => {
  cleanup();
  setResearchToken("");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("JobsPanel", () => {
  it("does not let an older job detail response overwrite the latest selection", async () => {
    let resolveOldLog: ((response: Response) => void) | undefined;
    let resolveOldResult: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.startsWith("/api/v1/jobs?")) return Promise.resolve(Response.json({ items: [
        { job_id: "old-job", kind: "mine", status: "running", progress: {}, run_ids: [] },
        { job_id: "new-job", kind: "data", status: "succeeded", progress: {}, run_ids: [] },
      ], next_cursor: null }));
      if (path === "/api/v1/jobs/old-job/logs?cursor=0") return new Promise<Response>((resolve) => { resolveOldLog = resolve; });
      if (path === "/api/v1/jobs/old-job/result") return new Promise<Response>((resolve) => { resolveOldResult = resolve; });
      if (path === "/api/v1/jobs/new-job/logs?cursor=0") return Promise.resolve(Response.json({ text: "new-log", next_cursor: 7, complete: true }));
      if (path === "/api/v1/jobs/new-job/result") return Promise.resolve(Response.json({ value: "new-result" }));
      if (path === "/api/v1/jobs/old-job" || path === "/api/v1/jobs/new-job") return Promise.resolve(Response.json({ job_id: path.split("/").pop(), status: "succeeded", progress: {}, run_ids: [] }));
      return Promise.resolve(Response.json({}, { status: 404 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<I18nProvider><ToastProvider><JobsPanel /></ToastProvider></I18nProvider>);

    const oldRow = (await screen.findByText("mine")).closest("tr") as HTMLElement;
    const newRow = screen.getByText("data").closest("tr") as HTMLElement;
    await user.click(within(oldRow).getByRole("button", { name: "old-job" }));
    await user.click(within(newRow).getByRole("button", { name: "new-job" }));
    expect(await screen.findByText("new-log")).toBeInTheDocument();
    await act(async () => {
      resolveOldLog?.(Response.json({ text: "old-log", next_cursor: 7, complete: true }));
      resolveOldResult?.(Response.json({ value: "old-result" }));
      await Promise.resolve();
    });
    expect(screen.queryByText("old-log")).not.toBeInTheDocument();
    expect(screen.getByText(/new-result/)).toBeInTheDocument();
  });

  it("does not overlap automatic job-list refreshes", async () => {
    vi.useFakeTimers();
    const resolvers: Array<(response: Response) => void> = [];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).startsWith("/api/v1/jobs?")) return new Promise<Response>((resolve) => resolvers.push(resolve));
      return Promise.resolve(Response.json({}, { status: 404 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<I18nProvider><ToastProvider><JobsPanel /></ToastProvider></I18nProvider>);
    await act(async () => {});
    await act(async () => { vi.advanceTimersByTime(15000); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolvers[0](Response.json({ items: [], next_cursor: null }));
      await Promise.resolve();
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("AsyncButton", () => {
  it("uses a synchronous guard so two clicks in the same render submit once", async () => {
    let resolve: (() => void) | undefined;
    const action = vi.fn(() => new Promise<void>((done) => { resolve = done; }));
    render(<AsyncButton onClick={action}>submit</AsyncButton>);
    const button = screen.getByRole("button", { name: "submit" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(action).toHaveBeenCalledTimes(1);
    await act(async () => { resolve?.(); await Promise.resolve(); });
  });
});

function ConfirmProbe({ onResult }: { onResult: (value: boolean) => void }) {
  const confirm = useConfirm();
  return <button onClick={() => void confirm({ message: "Delete portfolio?", danger: true }).then(onResult)}>delete</button>;
}

describe("ConfirmProvider", () => {
  it("does not globally confirm when Enter activates Cancel and restores focus", async () => {
    const onResult = vi.fn();
    const user = userEvent.setup();
    render(<I18nProvider><ConfirmProvider><ConfirmProbe onResult={onResult} /></ConfirmProvider></I18nProvider>);
    const trigger = screen.getByRole("button", { name: "delete" });
    await user.click(trigger);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    screen.getByRole("button", { name: "取消" }).focus();
    await user.keyboard("{Enter}");
    expect(onResult).toHaveBeenCalledWith(false);
    expect(onResult).not.toHaveBeenCalledWith(true);
    await vi.waitFor(() => expect(trigger).toHaveFocus());
  });

  it("cancels on Escape", async () => {
    const onResult = vi.fn();
    const user = userEvent.setup();
    render(<I18nProvider><ConfirmProvider><ConfirmProbe onResult={onResult} /></ConfirmProvider></I18nProvider>);
    await user.click(screen.getByRole("button", { name: "delete" }));
    await user.keyboard("{Escape}");
    expect(onResult).toHaveBeenCalledWith(false);
  });

  it("keeps Tab focus within the modal", async () => {
    const user = userEvent.setup();
    render(<I18nProvider><ConfirmProvider><ConfirmProbe onResult={() => undefined} /></ConfirmProvider></I18nProvider>);
    await user.click(screen.getByRole("button", { name: "delete" }));
    const cancel = screen.getByRole("button", { name: "取消" });
    const confirm = screen.getByRole("button", { name: "确认" });
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();
  });
});

describe("PanelHelp", () => {
  it("shifts a help popover into the viewport when its trigger is near the left edge", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains("help-popover")) {
        return { left: -480, right: 40, top: 40, bottom: 240, width: 520, height: 200, x: -480, y: 40, toJSON: () => ({}) };
      }
      if (this.getAttribute("aria-label") === "Help") {
        return { left: 20, right: 40, top: 12, bottom: 32, width: 20, height: 20, x: 20, y: 12, toJSON: () => ({}) };
      }
      return { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}) };
    });
    vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(800);

    render(
      <I18nProvider>
        <PanelHelp label="Help" title="Parameters" items={["First item"]} />
      </I18nProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Help" }));

    expect(screen.getByRole("dialog", { name: "Help" })).toHaveStyle({ transform: "translateX(496px)" });
  });
});
