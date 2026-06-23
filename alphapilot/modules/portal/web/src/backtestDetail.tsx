import React, { useEffect, useMemo, useState } from "react";
import Plot from "react-plotly.js";
import { api } from "./api";
import { Alert, chartHeight, DataTable, Spinner, Tabs } from "./components";
import { useAsync } from "./hooks";
import { useI18n } from "./i18n";

type Row = Record<string, unknown>;

export type BacktestDetailData = {
  workspace_id?: string;
  summary?: Record<string, number>;
  report?: Row[];
  cumulative?: Row[];
  trades?: Row[];
  holdings?: Row[];
  metrics?: Record<string, unknown> | null;
};

// --- formatting + small numeric helpers ------------------------------------
const numv = (v: unknown): number => {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : 0;
};
const dayKey = (v: unknown): string => String(v ?? "").slice(0, 10);
// report rows are named `date` (api renames the index), but fall back to
// `datetime` in case the source index kept that name.
const repDay = (r: Row): string => dayKey(r.date ?? r.datetime);
const pct = (v: number): string => `${(v * 100).toFixed(2)}%`;
const pct4 = (v: number): string => `${(v * 100).toFixed(4)}%`;
const money = (v: number): string => v.toLocaleString("en-US", { maximumFractionDigits: 0 });

const CHART_MARGIN = { l: 56, r: 48, t: 28, b: 40 };

/** Mirror of `backtest_viz.charts.cum_series` (cumulative sums over the slice). */
function cumSeries(rows: Row[]) {
  const date: string[] = [];
  const stratNoCost: number[] = [];
  const stratCost: number[] = [];
  const bench: number[] = [];
  const excessNoCost: number[] = [];
  const excessCost: number[] = [];
  let a = 0;
  let b = 0;
  let c = 0;
  let d = 0;
  let e = 0;
  for (const r of rows) {
    const ret = numv(r["return"]);
    const cost = numv(r.cost);
    const bch = numv(r.bench);
    a += ret;
    b += ret - cost;
    c += bch;
    d += ret - bch;
    e += ret - bch - cost;
    date.push(repDay(r));
    stratNoCost.push(a);
    stratCost.push(b);
    bench.push(c);
    excessNoCost.push(d);
    excessCost.push(e);
  }
  return { date, stratNoCost, stratCost, bench, excessNoCost, excessCost };
}

/** Mirror of `artifacts.build_summary` for the six displayed KPIs. */
function summarize(rows: Row[]) {
  let cumRet = 0;
  let cumRetCost = 0;
  let cumBench = 0;
  let cumExcess = 0;
  let peak = -Infinity;
  let maxDD = 0;
  let turnoverSum = 0;
  let costSum = 0;
  let lastAccount = 0;
  let n = 0;
  for (const r of rows) {
    const ret = numv(r["return"]);
    const cost = numv(r.cost);
    const bch = numv(r.bench);
    cumRet += ret;
    cumRetCost += ret - cost;
    cumBench += bch;
    cumExcess += ret - bch;
    peak = Math.max(peak, cumRet);
    maxDD = Math.min(maxDD, cumRet - peak);
    turnoverSum += numv(r.turnover);
    costSum += cost;
    if (r.account != null) lastAccount = numv(r.account);
    n += 1;
  }
  return {
    cumReturnCost: cumRetCost,
    benchCum: cumBench,
    excessNoCost: cumExcess,
    maxDD,
    meanTurnover: n ? turnoverSum / n : 0,
    totalCost: costSum,
    finalAccount: lastAccount
  };
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function BacktestDetail({ detail, workspaces }: { detail: BacktestDetailData; workspaces: Row[] }) {
  const { t } = useI18n();
  const wsId = String(detail.workspace_id ?? "");
  const report = detail.report || [];
  const trades = detail.trades || [];
  const holdings = detail.holdings || [];
  const metrics = (detail.metrics as Record<string, unknown> | null) || {};

  const minDay = report.length ? repDay(report[0]) : "";
  const maxDay = report.length ? repDay(report[report.length - 1]) : "";

  const [start, setStart] = useState(minDay);
  const [end, setEnd] = useState(maxDay);
  const [selectedDay, setSelectedDay] = useState("");
  const [dayTab, setDayTab] = useState("trades");
  const [compareId, setCompareId] = useState("");
  const [compareRows, setCompareRows] = useState<Row[] | null>(null);
  const [compareErr, setCompareErr] = useState<string | null>(null);

  // Reset range + compare whenever a different workspace is opened.
  useEffect(() => {
    setStart(minDay);
    setEnd(maxDay);
    setSelectedDay("");
    setCompareId("");
    setCompareRows(null);
    setCompareErr(null);
  }, [wsId]); // eslint-disable-line react-hooks/exhaustive-deps

  const inRange = (v: unknown): boolean => {
    const d = dayKey(v);
    return (!start || d >= start) && (!end || d <= end);
  };

  const reportSlice = useMemo(() => report.filter((r) => inRange(r.date ?? r.datetime)), [report, start, end]);
  const cum = useMemo(() => cumSeries(reportSlice), [reportSlice]);
  const summary = useMemo(() => summarize(reportSlice), [reportSlice]);

  const days = useMemo(() => reportSlice.map((r) => repDay(r)), [reportSlice]);
  const effectiveDay = days.includes(selectedDay) ? selectedDay : days[days.length - 1] || "";

  const compareCum = useMemo(() => {
    if (!compareRows) return null;
    return cumSeries(compareRows.filter((r) => inRange(r.date ?? r.datetime)));
  }, [compareRows, start, end]);

  async function pickCompare(id: string) {
    setCompareId(id);
    setCompareRows(null);
    setCompareErr(null);
    if (!id) return;
    try {
      const d = await api.get<BacktestDetailData>(`/api/backtests/${encodeURIComponent(id)}`);
      setCompareRows(d.report || []);
    } catch (err) {
      setCompareErr(err instanceof Error ? err.message : String(err));
    }
  }

  const x = cum.date;
  const accX = reportSlice.map((r) => repDay(r));

  const cumData: Row[] = [
    { x, y: cum.stratNoCost, type: "scatter", mode: "lines", name: t("btStratNoCost"), line: { color: "#2563eb", width: 2 } },
    { x, y: cum.stratCost, type: "scatter", mode: "lines", name: t("btStratCost"), line: { color: "#16a34a", width: 2 } },
    { x, y: cum.bench, type: "scatter", mode: "lines", name: t("btBench"), line: { color: "#f97316", width: 2 } }
  ];
  if (compareCum) {
    cumData.push({
      x: compareCum.date,
      y: compareCum.stratCost,
      type: "scatter",
      mode: "lines",
      name: `${t("btCompareTrace")}: ${compareId.slice(0, 8)}…`,
      line: { color: "#dc2626", width: 2, dash: "dash" }
    });
  }

  const dayRow = reportSlice.find((r) => repDay(r) === effectiveDay);
  const dayTrades = trades.filter((r) => dayKey(r.datetime) === effectiveDay);
  const dayHoldings = holdings.filter((r) => dayKey(r.datetime) === effectiveDay);
  const rangeTrades = trades.filter((r) => inRange(r.datetime));
  const buyN = dayTrades.filter((r) => numv(r.status) === 1).length;
  const sellN = dayTrades.filter((r) => numv(r.status) === -1).length;

  const tradeCols = [
    { key: "datetime", label: t("colDate"), render: (r: Row) => dayKey(r.datetime) },
    { key: "instrument", label: t("colInstrument") },
    { key: "status_label", label: t("colDirection") },
    { key: "amount", label: t("colAmount") },
    { key: "price", label: t("colPrice") },
    { key: "weight", label: t("colWeight") }
  ];
  const holdCols = [
    { key: "datetime", label: t("colDate"), render: (r: Row) => dayKey(r.datetime) },
    { key: "instrument", label: t("colInstrument") },
    { key: "amount", label: t("colHoldAmount") },
    { key: "price", label: t("colPrice") },
    { key: "weight", label: t("colWeight") },
    { key: "cash", label: t("colCash") }
  ];

  return (
    <section className="panel">
      <h2>{wsId}</h2>

      {/* date range + compare controls */}
      <div className="form-grid">
        <label>
          {t("btDateRange")}
          <input type="date" value={start} min={minDay} max={end || maxDay} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          &nbsp;
          <input type="date" value={end} min={start || minDay} max={maxDay} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label>
          {t("btCompare")}
          <select value={compareId} onChange={(e) => void pickCompare(e.target.value)}>
            <option value="">{t("btNoCompare")}</option>
            {workspaces
              .filter((w) => String(w.workspace_id) !== wsId)
              .map((w) => (
                <option key={String(w.workspace_id)} value={String(w.workspace_id)}>
                  {String(w.label || w.workspace_id)}
                </option>
              ))}
          </select>
        </label>
      </div>
      {compareErr ? <Alert tone="error">{compareErr}</Alert> : null}

      {/* KPI grid */}
      <div className="metric-grid compact">
        <Metric label={t("kpiCumReturnCost")} value={pct(summary.cumReturnCost)} />
        <Metric label={t("kpiBenchCum")} value={pct(summary.benchCum)} />
        <Metric label={t("kpiExcess")} value={pct(summary.excessNoCost)} />
        <Metric label={t("kpiMaxDD")} value={pct(summary.maxDD)} />
        <Metric label={t("kpiTurnover")} value={pct(summary.meanTurnover)} />
        <Metric label={t("kpiCost")} value={summary.totalCost.toFixed(4)} />
      </div>

      {/* cumulative return */}
      <h3>{t("btCumulative")}</h3>
      <Plot
        data={cumData}
        layout={{ autosize: true, height: chartHeight(), margin: CHART_MARGIN, hovermode: "x unified", legend: { orientation: "h" } }}
        useResizeHandler
        style={{ width: "100%" }}
      />

      {/* excess + account side by side */}
      <div className="split">
        <div>
          <h3>{t("btExcess")}</h3>
          <Plot
            data={[
              { x, y: cum.excessNoCost, type: "scatter", mode: "lines", name: t("btExcessNoCost"), line: { color: "#7c3aed" } },
              { x, y: cum.excessCost, type: "scatter", mode: "lines", name: t("btExcessCost"), line: { color: "#0891b2" } }
            ]}
            layout={{
              autosize: true,
              height: 320,
              margin: CHART_MARGIN,
              hovermode: "x unified",
              shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { dash: "dot", color: "#94a3b8" } }]
            }}
            useResizeHandler
            style={{ width: "100%" }}
          />
        </div>
        <div>
          <h3>{t("btAccount")}</h3>
          <Plot
            data={[
              { x: accX, y: reportSlice.map((r) => numv(r.account)), type: "scatter", mode: "lines", name: t("btTotalAssets"), line: { color: "#2563eb", width: 2 } },
              { x: accX, y: reportSlice.map((r) => numv(r.value)), type: "scatter", mode: "lines", name: t("btPositionValue"), line: { color: "#16a34a", width: 1.5 } },
              { x: accX, y: reportSlice.map((r) => numv(r.cash)), type: "scatter", mode: "lines", name: t("btCash"), line: { color: "#94a3b8", width: 1.5 } }
            ]}
            layout={{ autosize: true, height: 320, margin: CHART_MARGIN, hovermode: "x unified" }}
            useResizeHandler
            style={{ width: "100%" }}
          />
        </div>
      </div>

      {/* turnover & cost (dual axis) */}
      <h3>{t("btTurnoverCost")}</h3>
      <Plot
        data={[
          { x: accX, y: reportSlice.map((r) => numv(r.turnover)), type: "bar", name: t("btTurnover"), marker: { color: "#60a5fa" }, opacity: 0.7 },
          { x: accX, y: reportSlice.map((r) => numv(r.cost)), type: "scatter", mode: "lines", name: t("btFee"), line: { color: "#ef4444", width: 1.5 }, yaxis: "y2" }
        ]}
        layout={{
          autosize: true,
          height: 320,
          margin: CHART_MARGIN,
          hovermode: "x unified",
          yaxis: { title: t("btTurnover") },
          yaxis2: { title: t("btFee"), overlaying: "y", side: "right" }
        }}
        useResizeHandler
        style={{ width: "100%" }}
      />

      {/* daily detail */}
      <h3>{t("btDailyDetail")}</h3>
      <div className="form-grid">
        <label>
          {t("btSelectDay")}
          <select value={effectiveDay} onChange={(e) => setSelectedDay(e.target.value)}>
            {days
              .slice()
              .reverse()
              .map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
          </select>
        </label>
      </div>
      {dayRow ? (
        <div className="metric-grid compact">
          <Metric label={t("dayReturn")} value={pct4(numv(dayRow["return"]))} />
          <Metric label={t("dayBench")} value={pct4(numv(dayRow.bench))} />
          <Metric label={t("dayTurnover")} value={pct4(numv(dayRow.turnover))} />
          <Metric label={t("dayCost")} value={numv(dayRow.cost).toFixed(4)} />
          <Metric label={t("dayAccount")} value={money(numv(dayRow.account))} />
        </div>
      ) : null}

      <Tabs
        tabs={[
          { key: "trades", label: t("btTabTrades") },
          { key: "holdings", label: t("btTabHoldings") },
          { key: "allTrades", label: t("btTabAllTrades") },
          { key: "metrics", label: t("btTabMetrics") }
        ]}
        active={dayTab}
        onChange={setDayTab}
      />
      {dayTab === "trades" ? (
        <>
          <Alert tone="info">{`${effectiveDay} — ${t("btBuy")} ${buyN} / ${t("btSell")} ${sellN}`}</Alert>
          <DataTable rows={dayTrades} empty={t("btNoTradesDay")} columns={tradeCols} />
        </>
      ) : null}
      {dayTab === "holdings" ? <DataTable rows={dayHoldings} empty={t("btNoHoldingsDay")} columns={holdCols} /> : null}
      {dayTab === "allTrades" ? <DataTable rows={rangeTrades} empty={t("btNoTradesDay")} columns={tradeCols} /> : null}
      {dayTab === "metrics" ? (
        <DataTable
          rows={Object.entries(metrics).map(([key, value]) => ({
            key,
            value: typeof value === "number" ? value.toFixed(6) : String(value)
          }))}
          empty={t("btNoMetrics")}
          columns={[
            { key: "key", label: t("colMetric") },
            { key: "value", label: t("colValue") }
          ]}
        />
      ) : null}
    </section>
  );
}

type LeaderboardFile = { file: string; label: string; mtime: string };
type LeaderboardData = { columns: string[]; numeric_columns: string[]; rows: Row[] };

export function LeaderboardPanel() {
  const { t } = useI18n();
  const files = useAsync(() => api.get<LeaderboardFile[]>("/api/backtests/leaderboards"), []);
  const [file, setFile] = useState("");
  const [data, setData] = useState<LeaderboardData | null>(null);
  const [sortCol, setSortCol] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(f: string) {
    setFile(f);
    setData(null);
    setError(null);
    if (!f) return;
    setLoading(true);
    try {
      const d = await api.get<LeaderboardData>(`/api/backtests/leaderboard?file=${encodeURIComponent(f)}`);
      setData(d);
      setSortCol(d.numeric_columns[0] || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const sortedRows = useMemo(() => {
    if (!data) return [];
    if (!sortCol) return data.rows;
    return [...data.rows].sort((a, b) => Math.abs(numv(b[sortCol])) - Math.abs(numv(a[sortCol])));
  }, [data, sortCol]);

  const available = files.data || [];

  return (
    <section className="panel">
      <h2>{t("btLeaderboard")}</h2>
      {files.error ? <Alert tone="error">{files.error}</Alert> : null}
      {!available.length ? (
        <div className="empty">{t("btNoLeaderboard")}</div>
      ) : (
        <div className="form-grid">
          <label>
            {t("btLeaderboardFile")}
            <select value={file} onChange={(e) => void load(e.target.value)}>
              <option value="">{t("none")}</option>
              {available.map((f) => (
                <option key={f.file} value={f.file}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          {data && data.numeric_columns.length ? (
            <label>
              {t("btSortMetric")}
              <select value={sortCol} onChange={(e) => setSortCol(e.target.value)}>
                {data.numeric_columns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      )}
      {error ? <Alert tone="error">{error}</Alert> : null}
      {loading ? (
        <div className="empty">
          <Spinner /> {t("loading")}
        </div>
      ) : null}
      {data ? (
        <>
          {sortCol && data.columns.includes("factor_name") ? (
            <Plot
              data={[
                {
                  x: sortedRows.map((r) => String(r.factor_name)),
                  y: sortedRows.map((r) => numv(r[sortCol])),
                  type: "bar",
                  marker: { color: "#2563eb" }
                }
              ]}
              layout={{ autosize: true, height: 320, margin: { l: 56, r: 24, t: 28, b: 80 }, title: sortCol }}
              useResizeHandler
              style={{ width: "100%" }}
            />
          ) : null}
          <DataTable
            rows={sortedRows}
            empty={t("empty")}
            columns={data.columns.map((c) => ({ key: c, label: c }))}
          />
        </>
      ) : null}
    </section>
  );
}
