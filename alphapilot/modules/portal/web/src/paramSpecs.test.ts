import { describe, expect, it } from "vitest";
import {
  buildParams,
  dailyTradeSpecs,
  dataActionSpecs,
  defaultValuesFor,
  factorBacktestSpecs,
  factorLibraryBacktestSpecs,
  freqOptions,
  llmMiningSpecs,
  oneOffRunSpecs,
  sessionRunSpecs,
  visibleFields,
  withSessionOptions,
  type FieldSpec,
} from "./paramSpecs";

const dailyTradeKeys = (values: Record<string, string>) =>
  visibleFields(dailyTradeSpecs, values).map((f) => f.key);

const specs: FieldSpec[] = [
  { key: "name", label: "Name", type: "text", required: true },
  { key: "count", label: "Count", type: "number", defaultValue: 5 },
  { key: "flag", label: "Flag", type: "checkbox", defaultValue: false },
  { key: "mode", label: "Mode", type: "select", defaultValue: "a" },
  {
    key: "extra",
    label: "Extra",
    type: "text",
    visibleWhen: (v) => v.mode === "b",
  },
  { key: "_uiOnly", label: "UI", type: "text", defaultValue: "ignored" },
  { key: "yaml_params.topk", label: "TopK", type: "number" },
];

describe("defaultValuesFor", () => {
  it("uses declared defaults and sensible empties", () => {
    const v = defaultValuesFor(specs);
    expect(v.count).toBe(5);
    expect(v.flag).toBe(false);
    expect(v.name).toBe("");
  });
});

describe("visibleFields", () => {
  it("hides fields whose visibleWhen is false", () => {
    const keys = visibleFields(specs, { mode: "a" }).map((f) => f.key);
    expect(keys).not.toContain("extra");
  });

  it("shows conditional fields when the predicate passes", () => {
    const keys = visibleFields(specs, { mode: "b" }).map((f) => f.key);
    expect(keys).toContain("extra");
  });
});

describe("buildParams", () => {
  it("coerces numbers, booleans and drops empties + UI-only keys", () => {
    const params = buildParams(specs, {
      name: "hi",
      count: "7",
      flag: true,
      mode: "a",
      _uiOnly: "x",
      "yaml_params.topk": "30",
    });
    expect(params).toEqual({ name: "hi", count: 7, flag: true, mode: "a", yaml_params: { topk: 30 } });
    expect(params).not.toHaveProperty("_uiOnly");
  });

  it("throws when a required field is missing", () => {
    expect(() => buildParams(specs, { name: "" })).toThrow(/required/i);
  });

  it("merges valid advanced JSON overrides", () => {
    const params = buildParams(specs, { name: "hi", mode: "a" }, '{"seed": 1}');
    expect(params.seed).toBe(1);
  });

  it("rejects advanced JSON that is not an object", () => {
    expect(() => buildParams(specs, { name: "hi", mode: "a" }, "[1,2,3]")).toThrow(/object/i);
  });
});

describe("real spec catalogs", () => {
  it("dataActionSpecs default to the pipeline action", () => {
    const v = defaultValuesFor(dataActionSpecs);
    expect(v.action).toBe("pipeline");
  });

  it("dailyTradeSpecs expose a session field", () => {
    expect(dailyTradeSpecs.some((f) => f.key === "session")).toBe(true);
  });

  it("dailyTradeSpecs default the date mode to today (auto latest trading day)", () => {
    const v = defaultValuesFor(dailyTradeSpecs);
    expect(v._date_mode).toBe("today");
    // In "today" mode the date picker is hidden; in "fixed" mode it shows.
    expect(dailyTradeKeys({ _date_mode: "today" })).not.toContain("date");
    expect(dailyTradeKeys({ _date_mode: "fixed" })).toContain("date");
  });

  it("dailyTradeSpecs omit the date kwarg in today mode and keep it when fixed", () => {
    // "today" => no frozen date in the schedule (backend resolves the latest trading day each run).
    const auto = buildParams(dailyTradeSpecs, { _date_mode: "today", date: "2026-01-01", strategy_name: "x" });
    expect(auto).not.toHaveProperty("date");
    expect(auto).not.toHaveProperty("_date_mode");
    // "fixed" => the chosen date is sent through.
    const fixed = buildParams(dailyTradeSpecs, { _date_mode: "fixed", date: "2026-01-01", strategy_name: "x" });
    expect(fixed.date).toBe("2026-01-01");
  });

  it("withSessionOptions injects session names plus a blank option", () => {
    const injected = withSessionOptions(dailyTradeSpecs, ["live_a", "live_b"]);
    const sessionField = injected.find((f) => f.key === "session");
    expect(sessionField?.options?.map((o) => o.value)).toEqual(["", "live_a", "live_b"]);
  });

  it("sessionRunSpecs omit strategy + cash (driven by the session snapshot)", () => {
    const keys = sessionRunSpecs.map((f) => f.key);
    expect(keys).not.toContain("strategy_name");
    expect(keys).not.toContain("init_cash");
    expect(keys).not.toContain("session");
    expect(keys).toContain("trade_unit");
  });

  it("oneOffRunSpecs include strategy + cash but no session field", () => {
    const keys = oneOffRunSpecs.map((f) => f.key);
    expect(keys).toContain("strategy_name");
    expect(keys).toContain("init_cash");
    expect(keys).not.toContain("session");
  });
});

describe("freq (minute K-line) entry points", () => {
  it("freqOptions cover day + baostock intraday frequencies", () => {
    expect(freqOptions.map((o) => o.value)).toEqual(["day", "5min", "15min", "30min", "60min"]);
  });

  it("data / backtest / mining specs all expose a freq field defaulting to day", () => {
    for (const specs of [dataActionSpecs, factorBacktestSpecs, factorLibraryBacktestSpecs, llmMiningSpecs]) {
      const freq = specs.find((f) => f.key === "freq");
      expect(freq, "freq field present").toBeTruthy();
      expect(freq?.defaultValue).toBe("day");
    }
  });

  it("data action freq is baostock-only and hidden for tushare", () => {
    const keys = (v: Record<string, string>) => visibleFields(dataActionSpecs, v).map((f) => f.key);
    expect(keys({ action: "pipeline", source: "baostock_cn" })).toContain("freq");
    expect(keys({ action: "download", source: "baostock_cn" })).toContain("freq");
    expect(keys({ action: "convert", source: "baostock_cn" })).toContain("freq");
    expect(keys({ action: "pipeline", source: "tushare_cn" })).not.toContain("freq");
    // apply_adjust has no freq concept.
    expect(keys({ action: "apply_adjust", source: "baostock_cn" })).not.toContain("freq");
  });

  it("a 5min selection is sent through to the backend kwargs", () => {
    const params = buildParams(dataActionSpecs, { action: "pipeline", source: "baostock_cn", freq: "5min" });
    expect(params.freq).toBe("5min");
    // backtest form sends freq as a top-level kwarg (not nested under yaml_params).
    const bt = buildParams(factorBacktestSpecs, { factor_path: "x.csv", mode: "single_ic", freq: "5min" });
    expect(bt.freq).toBe("5min");
    expect(bt).not.toHaveProperty("yaml_params.freq");
  });
});
