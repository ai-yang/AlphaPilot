// Pure P&L math for a trade session, derived from its compact daily log + cash-flow ledger.
// Kept framework-free so it is unit-testable (see sessionPnl.test.ts); the chart component in
// pages.tsx binds straight to the arrays/totals returned here. Mirrors the backtest page's
// cumulative-return convention (arithmetic sum of daily returns) so the two pages read alike.

export type PnlRow = {
  date?: string;
  cash?: number | null;
  nav?: number | null; // account NAV captured from qlib's report_normal
  ret?: number | null; // daily return rate
  cost?: number | null; // daily trade cost as a fraction of account value
  turnover?: number | null;
};

export type PnlCashflow = { delta?: number | null };

export type SessionPnl = {
  dates: string[];
  nav: number[];
  cash: (number | null)[];
  cumReturnPct: number[]; // cumulative return in percentage points (Σ ret × 100)
  feeMoney: number[]; // per-day fee in money ≈ cost × nav
  cumFee: number[];
  turnover: (number | null)[];
  hasData: boolean;
  totals: {
    latestNav: number | null;
    cumReturnPts: number; // total cumulative return in points
    totalFees: number; // total fees in money
    netContributed: number; // init cash ± simulated deposits/withdrawals
    pnlMoney: number | null; // latestNav − netContributed (trading P&L, cash-flow neutral)
  };
};

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

export function computeSessionPnl(
  rows: PnlRow[] = [],
  initCash: number | null | undefined = 0,
  cashflows: PnlCashflow[] = [],
): SessionPnl {
  // Only rows that carry a NAV metric can be charted (older sessions predate the capture).
  const series = (rows || []).filter((r) => num(r.nav) !== null);

  const dates: string[] = [];
  const nav: number[] = [];
  const cash: (number | null)[] = [];
  const cumReturnPct: number[] = [];
  const feeMoney: number[] = [];
  const cumFee: number[] = [];
  const turnover: (number | null)[] = [];

  let retAcc = 0;
  let feeAcc = 0;
  for (const r of series) {
    const navV = num(r.nav) as number;
    const ret = num(r.ret) ?? 0;
    const fee = (num(r.cost) ?? 0) * navV;
    retAcc += ret * 100;
    feeAcc += fee;
    dates.push(String(r.date ?? ""));
    nav.push(navV);
    cash.push(num(r.cash));
    cumReturnPct.push(retAcc);
    feeMoney.push(fee);
    cumFee.push(feeAcc);
    turnover.push(num(r.turnover));
  }

  const netContributed =
    (num(initCash) ?? 0) + (cashflows || []).reduce((s, c) => s + (num(c.delta) ?? 0), 0);
  const latestNav = nav.length ? nav[nav.length - 1] : null;

  return {
    dates,
    nav,
    cash,
    cumReturnPct,
    feeMoney,
    cumFee,
    turnover,
    hasData: series.length > 0,
    totals: {
      latestNav,
      cumReturnPts: cumReturnPct.length ? cumReturnPct[cumReturnPct.length - 1] : 0,
      totalFees: feeAcc,
      netContributed,
      pnlMoney: latestNav === null ? null : latestNav - netContributed,
    },
  };
}
