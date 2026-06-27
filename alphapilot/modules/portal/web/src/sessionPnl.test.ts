import { describe, expect, it } from "vitest";
import { computeSessionPnl } from "./sessionPnl";

describe("computeSessionPnl", () => {
  it("derives cumulative return, fees and P&L from the daily log", () => {
    const rows = [
      { date: "2026-06-01", cash: 200000, nav: 1_000_000, ret: 0.01, cost: 0.0005, turnover: 0.2 },
      { date: "2026-06-02", cash: 150000, nav: 1_020_000, ret: 0.02, cost: 0.001, turnover: 0.3 },
    ];
    const r = computeSessionPnl(rows, 1_000_000, []);
    expect(r.hasData).toBe(true);
    expect(r.dates).toEqual(["2026-06-01", "2026-06-02"]);
    expect(r.nav).toEqual([1_000_000, 1_020_000]);
    // Cumulative return in points = Σ ret × 100.
    expect(r.cumReturnPct[0]).toBeCloseTo(1);
    expect(r.totals.cumReturnPts).toBeCloseTo(3);
    // Fee money per day ≈ cost × nav.
    expect(r.feeMoney[0]).toBeCloseTo(500);
    expect(r.feeMoney[1]).toBeCloseTo(1020);
    expect(r.totals.totalFees).toBeCloseTo(1520);
    // No cash flows: P&L = latest NAV − initial cash.
    expect(r.totals.netContributed).toBe(1_000_000);
    expect(r.totals.pnlMoney).toBe(20_000);
  });

  it("nets out simulated deposits/withdrawals so P&L stays trading-only", () => {
    const rows = [{ date: "2026-06-02", cash: 700000, nav: 1_400_000, ret: 0.0, cost: 0 }];
    // 1,000,000 initial + 300,000 deposited − 100,000 withdrawn = 1,200,000 contributed.
    const r = computeSessionPnl(rows, 1_000_000, [{ delta: 300000 }, { delta: -100000 }]);
    expect(r.totals.netContributed).toBe(1_200_000);
    expect(r.totals.pnlMoney).toBe(200_000);
  });

  it("skips rows without a NAV metric (older sessions) and is empty when none qualify", () => {
    const mixed = [
      { date: "2026-06-01", cash: 1_000_000 }, // legacy row, no nav
      { date: "2026-06-02", cash: 990000, nav: 1_010_000, ret: 0.01, cost: 0.0002 },
    ];
    const r = computeSessionPnl(mixed, 1_000_000, []);
    expect(r.dates).toEqual(["2026-06-02"]);
    expect(r.hasData).toBe(true);

    const none = computeSessionPnl([{ date: "x", cash: 1 }], 1_000_000, []);
    expect(none.hasData).toBe(false);
    expect(none.totals.latestNav).toBeNull();
    expect(none.totals.pnlMoney).toBeNull();
  });
});
