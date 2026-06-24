import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, fireEvent, cleanup } from "@testing-library/react";
import { I18nProvider, useI18n } from "./i18n";

function Probe() {
  const { lang, setLang, t } = useI18n();
  return (
    <div>
      <span data-testid="lang">{lang}</span>
      <span data-testid="home">{t("home")}</span>
      <span data-testid="unknown">{t("__no_such_key__")}</span>
      <button onClick={() => setLang("en")}>en</button>
    </div>
  );
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("i18n", () => {
  it("defaults to Chinese and translates a known key", () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang").textContent).toBe("zh");
    expect(screen.getByTestId("home").textContent).toBe("首页");
  });

  it("returns the key itself for unknown keys", () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("unknown").textContent).toBe("__no_such_key__");
  });

  it("switches language and persists the choice", () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    act(() => {
      fireEvent.click(screen.getByText("en"));
    });
    expect(screen.getByTestId("lang").textContent).toBe("en");
    // English dictionary returns something other than the Chinese label.
    expect(screen.getByTestId("home").textContent).not.toBe("首页");
    expect(localStorage.getItem("portal_lang")).toBe("en");
  });

  it("throws when useI18n is used without a provider", () => {
    // Suppress the expected React error boundary noise.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/I18nProvider missing/);
    spy.mockRestore();
  });
});
