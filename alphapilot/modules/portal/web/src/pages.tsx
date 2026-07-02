import Plot from "react-plotly.js";
import { Link } from "react-router-dom";
import { api, Factor, Job, JobProgress, qs, Schedule } from "./api";
import { Alert, AsyncButton, chartHeight, DataTable, DynamicForm, HybridJsonEditor, InfoDot, JobsPanel, JsonTextArea, PageTitle, PanelHelp, ProgressBar, RefreshButton, Spinner, StatusPill, Tabs, Tooltip, useConfirm } from "./components";
import { BacktestDetail, BacktestDetailData, LeaderboardPanel } from "./backtestDetail";
import { useAsync, useJsonInput, useParamForm } from "./hooks";
import { useI18n } from "./i18n";
import {
  alphaForgeSpecs,
  createStrategyFromFactorsSpecs,
  dataActionSpecs,
  factorBacktestSpecs,
  factorLibraryBacktestSpecs,
  llmMiningSpecs,
  oneOffRunSpecs,
  scheduleSpecsFor,
  sessionRunSpecs,
  strategyBacktestSpecs,
  timingBacktestSpecs,
  withStrategyOptions,
  withInstrumentSetOptions,
} from "./paramSpecs";
import { computeSessionPnl } from "./sessionPnl";
import { useAction, useToast } from "./toast";
import React, { useEffect, useMemo, useState } from "react";

type Status = {
  metrics: Record<string, string | number>;
  recent_jobs: Job[];
  recent_mining: string[];
  systems: string[];
  modules: Record<string, string[]>;
  config: Record<string, unknown>;
};

type TablePreview = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  row_count?: number;
  truncated?: boolean;
  missing?: boolean;
};

type TimingStrategySpec = {
  name: string;
  description: string;
  defaults: Record<string, unknown>;
};

type TimingStrategiesPayload = {
  strategies: TimingStrategySpec[];
  names: string[];
};

type TimingSignalPayload = {
  strategy_name: string;
  signals: TablePreview;
};

type TimingDetailPayload = {
  job: Job;
  summary: Record<string, unknown>;
  artifact_dir: string;
  signals: TablePreview;
  trades: TablePreview;
  equity_curve: TablePreview;
  positions: TablePreview;
};

type PortalSettings = {
  settings: { host: string; port: number; timezone: string };
  current: { host?: string; port?: number; timezone?: string };
  config_path: string;
  host_options: Array<{ value: string; label: string }>;
  timezone_options: string[];
  restart_required: boolean;
  runtime?: {
    pid?: number;
    running?: boolean;
    path?: string;
    argv?: string[];
  };
};

type PortalEnvField = {
  key: string;
  label: string;
  group: string;
  kind: "text" | "password" | "number" | "boolean";
  secret: boolean;
  help_text?: string;
  requires_restart: boolean;
};

type PortalEnvSettings = {
  fields: PortalEnvField[];
  values: Record<string, string>;
  current: Record<string, string>;
  config_path: string;
  restart_required: boolean;
  restart_required_keys: string[];
  masked_secret: string;
};

type LogCleanupResult = {
  log_root: string;
  execute: boolean;
  removed: number;
  paths: string[];
};

type NotifyCommandsStatus = {
  daemon: {
    running?: boolean;
    pid?: number | null;
    channel?: string | null;
    root?: string;
    log_path?: string;
  };
  payload?: Record<string, unknown>;
  events: NotifyEvent[];
};

type NotifyEvent = Record<string, unknown> & {
  created_at?: string;
  channel?: string;
  user_id?: string;
  text?: string;
  ok?: boolean;
  action?: Record<string, unknown>;
  reply?: string;
  error?: string;
};

type KlineMetric = "amount" | "volume" | "turn" | "pctChg";
type KlineRange = "1M" | "3M" | "6M" | "1Y" | "ALL";

type KlineRow = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  amount?: number;
  turn?: number;
  pctChg?: number;
};

type KlinePayload = {
  symbol?: string;
  label?: string;
  date_range?: unknown[];
  rows?: Array<Record<string, unknown>>;
};

const KLINE_RANGES: KlineRange[] = ["1M", "3M", "6M", "1Y", "ALL"];
const KLINE_METRICS: KlineMetric[] = ["amount", "volume", "turn", "pctChg"];

function toFiniteNumber(value: unknown): number | undefined {
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

function normalizeKlineRows(rows: Array<Record<string, unknown>>): KlineRow[] {
  return rows.flatMap((row) => {
    const open = toFiniteNumber(row.open);
    const high = toFiniteNumber(row.high);
    const low = toFiniteNumber(row.low);
    const close = toFiniteNumber(row.close);
    const date = row.date ? String(row.date) : "";
    if (!date || open === undefined || high === undefined || low === undefined || close === undefined) return [];
    return [{
      date,
      open,
      high,
      low,
      close,
      volume: toFiniteNumber(row.volume),
      amount: toFiniteNumber(row.amount),
      turn: toFiniteNumber(row.turn),
      pctChg: toFiniteNumber(row.pctChg)
    }];
  });
}

function metricValue(row: KlineRow | undefined, metric: KlineMetric, prev?: KlineRow): number | undefined {
  if (!row) return undefined;
  if (metric === "pctChg") {
    if (row.pctChg !== undefined) return row.pctChg;
    if (prev?.close) return ((row.close - prev.close) / prev.close) * 100;
    return undefined;
  }
  return row[metric];
}

function hasMetric(rows: KlineRow[], metric: KlineMetric): boolean {
  return rows.some((row, index) => metricValue(row, metric, rows[index - 1]) !== undefined);
}

function resolveKlineMetric(rows: KlineRow[], metric: KlineMetric): KlineMetric {
  if (hasMetric(rows, metric)) return metric;
  if (hasMetric(rows, "volume")) return "volume";
  return metric;
}

function klineRangeValue(rows: KlineRow[], range: KlineRange): [string, string] | undefined {
  if (range === "ALL" || rows.length < 2) return undefined;
  const lastDate = new Date(rows[rows.length - 1].date);
  if (Number.isNaN(lastDate.getTime())) return undefined;
  const startDate = new Date(lastDate);
  if (range === "1M") startDate.setMonth(startDate.getMonth() - 1);
  if (range === "3M") startDate.setMonth(startDate.getMonth() - 3);
  if (range === "6M") startDate.setMonth(startDate.getMonth() - 6);
  if (range === "1Y") startDate.setFullYear(startDate.getFullYear() - 1);
  return [startDate.toISOString().slice(0, 10), rows[rows.length - 1].date];
}

// Intraday bars carry a non-midnight time component (e.g. "2026-06-23T09:35:00"); daily bars
// are date-only / midnight. Used to pick a continuous (category) x-axis for minute K-lines so
// the lunch break and overnight gaps don't render as empty spans.
export function klineIsIntraday(rows: KlineRow[]): boolean {
  return rows.some((row) => {
    const m = String(row.date).match(/[ T](\d{2}):(\d{2})/);
    return m ? m[1] !== "00" || m[2] !== "00" : false;
  });
}

export function klineAxisType(rows: KlineRow[]): "date" | "category" {
  return klineIsIntraday(rows) ? "category" : "date";
}

// On a category x-axis the range is expressed as bar indices, not dates. Translate the
// selected window (1M/3M/...) into ``[startIndex, lastIndex]`` so the range buttons still work.
function klineCategoryRange(rows: KlineRow[], range: KlineRange): [number, number] | undefined {
  const win = klineRangeValue(rows, range);
  if (!win) return undefined;
  const startTs = new Date(win[0]).getTime();
  const startIdx = rows.findIndex((row) => new Date(row.date).getTime() >= startTs);
  if (startIdx <= 0) return undefined;
  return [startIdx - 0.5, rows.length - 0.5];
}

// 24h time-of-day label ("2026-06-23T09:35:00" -> "09:35"); falls back to the date.
export function klineTimeLabel(date: unknown): string {
  const m = String(date).match(/[ T](\d{2}:\d{2})/);
  return m ? m[1] : String(date).slice(0, 10);
}

// Sparse HH:MM ticks for the intraday category axis: a handful of evenly-spaced bars
// (always including the first and last of the visible window), labelled time-only so
// the axis reads like the daily chart instead of cramming every timestamp.
export function klineCategoryTicks(
  rows: KlineRow[],
  range: [number, number] | undefined,
  maxTicks = 7,
): { tickvals: number[]; ticktext: string[] } {
  const lo = range ? Math.max(0, Math.ceil(range[0])) : 0;
  const hi = range ? Math.min(rows.length - 1, Math.floor(range[1])) : rows.length - 1;
  const span = hi - lo;
  if (span < 0) return { tickvals: [], ticktext: [] };
  const count = Math.min(maxTicks, span + 1);
  const idxs = count <= 1
    ? [lo]
    : Array.from({ length: count }, (_, i) => Math.round(lo + (span * i) / (count - 1)));
  const tickvals = Array.from(new Set(idxs));
  return { tickvals, ticktext: tickvals.map((i) => klineTimeLabel(rows[i].date)) };
}

function formatDateLabel(value: unknown): string {
  return value ? String(value).slice(0, 10) : "-";
}

function formatTimestamp(value: unknown): string {
  if (!value) return "—";
  const d = new Date(String(value));
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}

function formatPrice(value?: number): string {
  return value === undefined ? "-" : value.toFixed(2);
}

function formatCompactNumber(value?: number): string {
  if (value === undefined) return "-";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function formatPercent(value?: number): string {
  return value === undefined ? "-" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatRatioPercent(value: unknown): string {
  const n = toFiniteNumber(value);
  return n === undefined ? "-" : `${n >= 0 ? "+" : ""}${(n * 100).toFixed(2)}%`;
}

function formatMoney(value: unknown): string {
  const n = toFiniteNumber(value);
  if (n === undefined) return "-";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(n);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function mergeTimingAdvanced(base: Record<string, unknown>, advanced: Record<string, unknown>): Record<string, unknown> {
  const out = { ...base };
  if (isRecord(base.strategy_params) || isRecord(advanced.strategy_params)) {
    out.strategy_params = {
      ...(isRecord(base.strategy_params) ? base.strategy_params : {}),
      ...(isRecord(advanced.strategy_params) ? advanced.strategy_params : {}),
    };
  }
  for (const [key, value] of Object.entries(advanced)) {
    if (key !== "strategy_params") out[key] = value;
  }
  return out;
}

function previewColumns(table: TablePreview | undefined, fallback: string[] = []): Array<{ key: string; label: string; ellipsis?: boolean; align?: "left" | "right" | "center" }> {
  const keys = (table?.columns?.length ? table.columns : fallback).slice(0, 10);
  return keys.map((key) => ({
    key,
    label: key,
    ellipsis: ["datetime", "signal_datetime", "instrument", "reason"].includes(key) ? undefined : true,
    align: ["signal", "target_percent", "score", "amount", "price", "fee", "equity", "cash"].includes(key) ? "right" : undefined,
  }));
}

function timingEquitySeries(rows: Array<Record<string, unknown>>): Array<{ datetime: string; equity: number }> {
  const byTime = new Map<string, number>();
  rows.forEach((row) => {
    const dt = row.datetime ? String(row.datetime) : "";
    const equity = toFiniteNumber(row.equity);
    if (dt && equity !== undefined && !byTime.has(dt)) byTime.set(dt, equity);
  });
  return [...byTime.entries()]
    .map(([datetime, equity]) => ({ datetime, equity }))
    .sort((a, b) => a.datetime.localeCompare(b.datetime));
}

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function HomePage() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<Status>("/api/status"), []);
  const metrics = state.data?.metrics || {};
  return (
    <>
      <PageTitle title="AlphaPilot" subtitle={t("homeSubtitle")} />
      {state.error ? <Alert tone="error">{state.error}</Alert> : null}
      <div className="metric-grid">
        {([
          [t("symbols"), metrics.symbols, t("tipSymbols")],
          [t("factors"), metrics.factors, t("tipFactors")],
          [t("strategies"), metrics.strategies, t("tipStrategies")],
          [t("backtests"), metrics.backtests, t("tipBacktests")]
        ] as Array<[string, string | number | undefined, string]>).map(([label, value, tip]) => (
          <div className="metric" key={label}>
            <span className="metric-label">{label}<InfoDot tip={tip} /></span>
            <strong>{state.loading && value === undefined ? "…" : String(value ?? "-")}</strong>
          </div>
        ))}
      </div>
      <div className="grid two">
        <section className="panel">
          <h2>{t("quickActions")}</h2>
          <div className="action-grid">
            <Link className="action" to="/mining">{t("actionMine")}</Link>
            <Link className="action" to="/market">{t("actionMarket")}</Link>
            <Link className="action" to="/backtest">{t("actionBacktest")}</Link>
            <Link className="action" to="/library">{t("actionLibrary")}</Link>
          </div>
        </section>
        <section className="panel">
          <h2>{t("recentMining")}</h2>
          {(state.data?.recent_mining || []).length ? (
            <ul className="plain-list">{state.data?.recent_mining.map((name) => <li key={name}>{name}</li>)}</ul>
          ) : (
            <div className="empty">{t("empty")}</div>
          )}
        </section>
      </div>
      <JobsPanel compact />
    </>
  );
}

export function MiningPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const instrumentSets = useAsync(() => api.get<{ sets: string[] }>("/api/data/instrument-sets"), []);
  const poolNames = instrumentSets.data?.sets || [];
  const llmSpecs = useMemo(() => withInstrumentSetOptions(llmMiningSpecs, poolNames), [instrumentSets.data]);
  const afSpecs = useMemo(() => withInstrumentSetOptions(alphaForgeSpecs, poolNames), [instrumentSets.data]);
  const llmAdvanced = useJsonInput("{}");
  const llmForm = useParamForm(llmSpecs, llmAdvanced.raw);
  const afAdvanced = useJsonInput("{}");
  const afForm = useParamForm(afSpecs, afAdvanced.raw);
  const sessions = useAsync(() => api.get<Array<Record<string, unknown>>>("/api/mining/sessions"), []);
  const { busy, run } = useAction();
  const [sessionDetail, setSessionDetail] = useState<Record<string, unknown> | null>(null);
  const [sessionFile, setSessionFile] = useState<Record<string, unknown> | null>(null);

  function startLlmMining() {
    void run(async () => {
      const kwargs = llmForm.parse();
      await api.post<Job>("/api/jobs", { kind: "mine", kwargs });
    }, t("started"));
  }

  function startAlphaForge() {
    void run(async () => {
      const kwargs = afForm.parse();
      const method = String(kwargs.method || "mine_aff");
      delete kwargs.method;
      await api.post<Job>("/api/jobs", { kind: method, kwargs });
    }, t("started"));
  }

  async function openSession(name: string) {
    setSessionDetail(await api.get(`/api/mining/sessions/${encodeURIComponent(name)}`));
    setSessionFile(null);
  }

  async function openSessionFile(path: string) {
    if (!sessionDetail?.name) return;
    setSessionFile(await api.get(`/api/mining/sessions/${encodeURIComponent(String(sessionDetail.name))}/files/${encodeURIComponent(path)}`));
  }

  async function deleteSession(name: string) {
    if (!(await confirm({ message: `${t("delete")} ${name}?`, danger: true }))) return;
    void run(async () => {
      await api.delete(`/api/mining/sessions/${encodeURIComponent(name)}`);
      setSessionDetail(null);
      await sessions.refresh();
    });
  }

  return (
    <>
      <PageTitle title={t("mining")} subtitle={t("miningSubtitle")} />
      <div className="grid two">
        <section className="panel">
          <div className="panel-head compact">
            <h2>{t("llmMining")}</h2>
            <PanelHelp
              label={t("llmMiningHelp")}
              title={t("llmMiningHelpTitle")}
              intro={t("llmMiningHelpIntro")}
              items={[
                t("llmMiningHelpStep"),
                t("llmMiningHelpDirection"),
                t("llmMiningHelpMarket"),
                t("llmMiningHelpSave"),
                t("llmMiningHelpOverrides"),
                t("llmMiningHelpAdvanced")
              ]}
              footer={t("llmMiningHelpFlow")}
            />
          </div>
          <DynamicForm specs={llmSpecs} values={llmForm.values} onChange={llmForm.setValue} errors={llmForm.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={llmAdvanced.raw} onChange={llmAdvanced.setRaw} rows={5} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => startLlmMining()}>{busy ? <Spinner /> : null}{t("run")}</button>
        </section>
        <section className="panel">
          <div className="panel-head compact">
            <h2>{t("formulaMining")}</h2>
            <PanelHelp
              label={t("formulaMiningHelp")}
              title={t("formulaMiningHelpTitle")}
              intro={t("formulaMiningHelpIntro")}
              items={[
                t("formulaMiningHelpMethod"),
                t("formulaMiningHelpUniverse"),
                t("formulaMiningHelpSeed"),
                t("formulaMiningHelpTop"),
                t("formulaMiningHelpBacktest")
              ]}
              footer={t("formulaMiningHelpFlow")}
            />
          </div>
          <DynamicForm specs={afSpecs} values={afForm.values} onChange={afForm.setValue} errors={afForm.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={afAdvanced.raw} onChange={afAdvanced.setRaw} rows={5} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => startAlphaForge()}>{busy ? <Spinner /> : null}{t("run")}</button>
        </section>
      </div>
      <section className="panel">
        <div className="panel-head">
          <h2>{t("miningSessions")}</h2>
          <RefreshButton className="button small" onClick={() => sessions.refresh()} />
        </div>
        {sessions.error ? <Alert tone="error">{sessions.error}</Alert> : null}
        <DataTable
          rows={(sessions.data || []) as Record<string, unknown>[]}
          empty={t("empty")}
          loading={sessions.loading}
          columns={[
            { key: "name", label: t("colSession") },
            { key: "mtime", label: t("colUpdated") },
            { key: "path", label: t("colPath"), ellipsis: true },
            {
              key: "name",
              label: t("colActions"),
              align: "right",
              render: (row) => (
                <div className="row-actions">
                  <button className="button small" onClick={() => void openSession(String(row.name))}>{t("open")}</button>
                  <button className="button small danger" disabled={busy} onClick={() => void deleteSession(String(row.name))}>{t("delete")}</button>
                </div>
              )
            }
          ]}
        />
        {sessionDetail ? (
          <div className="split">
            <pre className="json">{JSON.stringify({ name: sessionDetail.name, path: sessionDetail.path }, null, 2)}</pre>
            <DataTable
              rows={((sessionDetail.files as Array<Record<string, unknown>>) || []).slice(0, 80)}
              columns={[
                { key: "path", label: t("colFile"), ellipsis: true },
                { key: "size", label: t("colSize"), align: "right" },
                { key: "mtime", label: t("colUpdated") },
                { key: "path", label: t("colActions"), align: "right", render: (row) => <button className="button small" onClick={() => void openSessionFile(String(row.path))}>{t("view")}</button> }
              ]}
            />
          </div>
        ) : null}
        {sessionFile ? (
          <details open>
            <summary>{String(sessionFile.path)}</summary>
            <pre className="log">{String(sessionFile.content || "")}</pre>
          </details>
        ) : null}
      </section>
      <JobsPanel />
    </>
  );
}

export function BacktestPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const instrumentSets = useAsync(() => api.get<{ sets: string[] }>("/api/data/instrument-sets"), []);
  const poolNames = instrumentSets.data?.sets || [];
  const factorAdvanced = useJsonInput("{}");
  const factorSpecs = useMemo(() => withInstrumentSetOptions(factorBacktestSpecs, poolNames), [instrumentSets.data]);
  const factorForm = useParamForm(factorSpecs, factorAdvanced.raw);
  const strategies = useAsync(() => api.get<{ names: string[] }>("/api/strategies"), []);
  const strategySpecs = useMemo(
    () => withInstrumentSetOptions(withStrategyOptions(strategyBacktestSpecs, strategies.data?.names || []), poolNames),
    [strategies.data, instrumentSets.data],
  );
  const strategyAdvanced = useJsonInput("{}");
  const strategyForm = useParamForm(strategySpecs, strategyAdvanced.raw);
  const list = useAsync(() => api.get<Array<Record<string, unknown>>>("/api/backtests"), []);
  const [detail, setDetail] = useState<BacktestDetailData | null>(null);
  const { busy, run } = useAction();

  function startFactorBacktest() {
    void run(async () => {
      const kwargs = factorForm.parse();
      await api.post<Job>("/api/jobs", { kind: "factor_backtest", kwargs });
    }, t("started"));
  }

  function startStrategyBacktest() {
    void run(async () => {
      const kwargs = strategyForm.parse();
      await api.post<Job>("/api/jobs", { kind: "strategy_backtest", kwargs });
    }, t("started"));
  }

  async function open(workspaceId: string) {
    setDetail(await api.get<BacktestDetailData>(`/api/backtests/${encodeURIComponent(workspaceId)}`));
  }

  async function deleteWorkspace(workspaceId: string) {
    if (!(await confirm({ message: `${t("delete")} ${workspaceId}?`, danger: true }))) return;
    void run(async () => {
      await api.delete(`/api/backtests/${encodeURIComponent(workspaceId)}`);
      if (detail?.workspace_id === workspaceId) setDetail(null);
      await list.refresh();
    });
  }

  return (
    <>
      <PageTitle title={t("backtest")} subtitle={t("backtestSubtitle")} />
      {list.error ? <Alert tone="error">{list.error}</Alert> : null}
      <div className="grid two">
        <section className="panel">
          <div className="panel-head compact">
            <h2>{t("factorBacktest")}</h2>
            <PanelHelp
              label={t("factorBacktestHelp")}
              title={t("factorBacktestHelpTitle")}
              intro={t("factorBacktestHelpIntro")}
              items={[
                t("factorBacktestHelpPath"),
                t("factorBacktestHelpMode"),
                t("factorBacktestHelpMarket"),
                t("factorBacktestHelpOverrides"),
                t("factorBacktestHelpAdvanced")
              ]}
              footer={t("factorBacktestHelpFlow")}
            />
          </div>
          <DynamicForm specs={factorSpecs} values={factorForm.values} onChange={factorForm.setValue} errors={factorForm.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={factorAdvanced.raw} onChange={factorAdvanced.setRaw} rows={5} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => startFactorBacktest()}>{busy ? <Spinner /> : null}{t("run")}</button>
        </section>
        <section className="panel">
          <div className="panel-head compact">
            <h2>{t("strategyBacktest")}</h2>
            <PanelHelp
              label={t("strategyBacktestHelp")}
              title={t("strategyBacktestHelpTitle")}
              intro={t("strategyBacktestHelpIntro")}
              items={[
                t("strategyBacktestHelpAsset"),
                t("strategyBacktestHelpMode"),
                t("strategyBacktestHelpReuse"),
                t("strategyBacktestHelpDates"),
                t("strategyBacktestHelpAdvanced")
              ]}
              footer={t("strategyBacktestHelpFlow")}
            />
          </div>
          {strategies.error ? <Alert tone="error">{strategies.error}</Alert> : null}
          <DynamicForm specs={strategySpecs} values={strategyForm.values} onChange={strategyForm.setValue} errors={strategyForm.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={strategyAdvanced.raw} onChange={strategyAdvanced.setRaw} rows={5} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => startStrategyBacktest()}>{busy ? <Spinner /> : null}{t("run")}</button>
        </section>
      </div>
      <section className="panel">
        <h2>{t("workspace")}</h2>
        <DataTable
          rows={(list.data || []) as Record<string, unknown>[]}
          loading={list.loading}
          columns={[
            { key: "label", label: t("colLabel"), ellipsis: true },
            { key: "mtime", label: t("colUpdated") },
            {
              key: "workspace_id",
              label: t("colActions"),
              align: "right",
              render: (row) => (
                <div className="row-actions">
                  <button className="button small" onClick={() => void open(String(row.workspace_id))}>{t("open")}</button>
                  <button className="button small danger" disabled={busy} onClick={() => void deleteWorkspace(String(row.workspace_id))}>{t("delete")}</button>
                </div>
              )
            }
          ]}
        />
      </section>
      {detail ? <BacktestDetail detail={detail} workspaces={(list.data || []) as Record<string, unknown>[]} /> : null}
      <LeaderboardPanel />
      <JobsPanel compact />
    </>
  );
}

export function TimingPage() {
  const { t } = useI18n();
  const strategies = useAsync(() => api.get<TimingStrategiesPayload>("/api/timing/strategies"), []);
  const specs = useMemo(() => timingBacktestSpecs(strategies.data?.names || []), [strategies.data]);
  const advanced = useJsonInput("{}");
  const form = useParamForm(specs);
  const { busy, run } = useAction();
  const [signalPreview, setSignalPreview] = useState<TimingSignalPayload | null>(null);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [detail, setDetail] = useState<TimingDetailPayload | null>(null);

  const selectedStrategy = useMemo(() => {
    const name = String(form.values.strategy_name || "boll_mean_reversion");
    return strategies.data?.strategies.find((item) => item.name === name) || null;
  }, [form.values.strategy_name, strategies.data]);

  const equity = useMemo(() => timingEquitySeries(detail?.equity_curve.rows || []), [detail]);

  function parseTimingPayload() {
    const base = form.parse();
    const extra = advanced.parse();
    return mergeTimingAdvanced(base, extra);
  }

  function previewSignals() {
    void run(async () => {
      const payload = parseTimingPayload();
      const result = await api.post<TimingSignalPayload>("/api/timing/signal", payload);
      setSignalPreview(result);
    }, t("timingSignalReady"));
  }

  function startBacktest() {
    void run(async () => {
      const payload = parseTimingPayload();
      const job = await api.post<Job>("/api/timing/backtest", payload);
      setActiveJob(job);
      setProgress(job.progress || null);
      setDetail(null);
    }, t("started"));
  }

  useEffect(() => {
    if (!activeJob?.job_id || activeJob.status !== "running") return;
    const jobId = activeJob.job_id;
    let alive = true;
    async function poll() {
      try {
        const next = await api.get<JobProgress>(`/api/jobs/${jobId}/progress`);
        if (!alive) return;
        setProgress(next);
        if (next.status === "succeeded") {
          const loaded = await api.get<TimingDetailPayload>(`/api/timing/jobs/${jobId}/detail`);
          if (alive) setDetail(loaded);
        }
        if (!alive) return;
        setActiveJob((current) => current && current.job_id === jobId
          ? { ...current, status: String(next.status || current.status), progress: next }
          : current);
      } catch (err) {
        if (!alive) return;
        setProgress({
          job_id: jobId,
          status: "failed",
          percent: 100,
          stage: "failed",
          message: err instanceof Error ? err.message : String(err),
        });
        setActiveJob((current) => current && current.job_id === jobId ? { ...current, status: "failed" } : current);
      }
    }
    void poll();
    const id = window.setInterval(poll, 3000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [activeJob?.job_id, activeJob?.status]);

  const summary = detail?.summary || {};
  const metricRows = [
    [t("timingFinalEquity"), formatMoney(summary.final_equity)],
    [t("timingTotalReturn"), formatRatioPercent(summary.total_return)],
    [t("timingAnnualReturn"), formatRatioPercent(summary.annual_return)],
    [t("timingMaxDrawdown"), formatRatioPercent(summary.max_drawdown)],
    [t("timingTrades"), String(summary.n_trades ?? "-")],
    [t("timingTotalFee"), formatMoney(summary.total_fee)],
  ];

  return (
    <>
      <PageTitle title={t("timing")} subtitle={t("timingSubtitle")} />
      <div className="grid side">
        <section className="panel">
          <div className="panel-head compact">
            <h2>{t("timingParams")}</h2>
            <PanelHelp
              label={t("timingHelp")}
              title={t("timingHelpTitle")}
              intro={t("timingHelpIntro")}
              items={[
                t("timingHelpData"),
                t("timingHelpStrategy"),
                t("timingHelpExecution"),
                t("timingHelpAdvanced")
              ]}
              footer={t("timingHelpFlow")}
            />
          </div>
          {strategies.error ? <Alert tone="error">{strategies.error}</Alert> : null}
          <DynamicForm specs={specs} values={form.values} onChange={form.setValue} errors={form.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={advanced.raw} onChange={advanced.setRaw} rows={5} />
          </details>
          <div className="toolbar below">
            <button className="button" disabled={busy} onClick={previewSignals}>{busy ? <Spinner /> : null}{t("timingPreviewSignal")}</button>
            <button className="button primary" disabled={busy} onClick={startBacktest}>{busy ? <Spinner /> : null}{t("timingRunBacktest")}</button>
          </div>
        </section>
        <aside className="panel">
          <h2>{t("timingStrategyInfo")}</h2>
          {selectedStrategy ? (
            <>
              <p><strong>{selectedStrategy.name}</strong></p>
              <p className="muted">{selectedStrategy.description}</p>
              <pre className="inline-json">{JSON.stringify(selectedStrategy.defaults, null, 2)}</pre>
            </>
          ) : strategies.loading ? (
            <div className="empty loading-row"><Spinner /> {t("loading")}</div>
          ) : (
            <div className="empty">{t("empty")}</div>
          )}
          {activeJob ? (
            <section className="panel inset">
              <h3>{t("runStatus")}</h3>
              <p className="muted">{activeJob.job_id}</p>
              <StatusPill status={progress?.status || activeJob.status} />
              {progress ? <ProgressBar percent={progress.percent || 0} label={progress.message || progress.stage} active={progress.status === "running"} /> : null}
            </section>
          ) : null}
        </aside>
      </div>

      {signalPreview ? (
        <section className="panel">
          <div className="panel-head">
            <h2>{t("timingSignalPreview")}</h2>
            <span className="muted">
              {signalPreview.signals.row_count ?? signalPreview.signals.rows.length} rows
              {signalPreview.signals.truncated ? " · truncated" : ""}
            </span>
          </div>
          <DataTable
            rows={signalPreview.signals.rows}
            empty={t("empty")}
            columns={previewColumns(signalPreview.signals, ["datetime", "instrument", "signal", "target_percent", "score", "reason"])}
          />
        </section>
      ) : null}

      {detail ? (
        <>
          <section className="panel">
            <div className="panel-head">
              <h2>{t("timingBacktestResult")}</h2>
              <span className="muted">{detail.artifact_dir}</span>
            </div>
            <div className="metric-grid">
              {metricRows.map(([label, value]) => (
                <div className="metric" key={label}>
                  <span className="metric-label">{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
            {equity.length ? (
              <Plot
                data={[
                  {
                    x: equity.map((row) => row.datetime),
                    y: equity.map((row) => row.equity),
                    type: "scatter",
                    mode: "lines",
                    name: t("equityCurve"),
                    line: { color: cssVar("--accent-600", "#2563eb"), width: 2 },
                  },
                ]}
                layout={{
                  autosize: true,
                  height: chartHeight(),
                  margin: { l: 50, r: 20, t: 20, b: 45 },
                  hovermode: "x unified",
                  paper_bgcolor: "rgba(0,0,0,0)",
                  plot_bgcolor: "rgba(0,0,0,0)",
                }}
                config={{ responsive: true, displayModeBar: false }}
                style={{ width: "100%" }}
              />
            ) : (
              <div className="empty">{t("empty")}</div>
            )}
          </section>
          <section className="panel">
            <h2>{t("timingTrades")}</h2>
            <DataTable
              rows={detail.trades.rows}
              empty={t("empty")}
              columns={previewColumns(detail.trades, ["datetime", "instrument", "side", "amount", "price", "fee", "reason"])}
            />
          </section>
          <div className="grid two">
            <section className="panel">
              <h2>{t("timingPositions")}</h2>
              <DataTable
                rows={detail.positions.rows}
                empty={t("empty")}
                columns={previewColumns(detail.positions, ["datetime", "instrument", "amount", "market_value"])}
              />
            </section>
            <section className="panel">
              <h2>{t("timingSignals")}</h2>
              <DataTable
                rows={detail.signals.rows}
                empty={t("empty")}
                columns={previewColumns(detail.signals, ["datetime", "instrument", "signal", "target_percent", "score", "reason"])}
              />
            </section>
          </div>
        </>
      ) : null}
      <JobsPanel compact />
    </>
  );
}

type DuplicateGroup = {
  members: Array<{ factor_name: string; factor_expression: string; categories?: string[] }>;
  canonical: string;
  suggested_keep: string;
  suggested_delete: string[];
};
type SimilarPair = { factor_a: string; factor_b: string; similarity: number; shared: string };
type DuplicatesResult = {
  groups: DuplicateGroup[];
  similar_pairs: SimilarPair[];
  n_factors: number;
  n_duplicate_groups: number;
  n_redundant_factors: number;
};
type FactorValidationResponse = {
  acceptable?: boolean;
  code?: string;
  message?: string;
  details?: Record<string, unknown> | null;
};

function factorValidationMessage(result: FactorValidationResponse): string {
  const message = typeof result.message === "string" && result.message.trim() ? result.message.trim() : "";
  const code = typeof result.code === "string" && result.code.trim() ? result.code.trim() : "";
  return message || code || "Factor was not saved.";
}

export function LibraryPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const factors = useAsync(() => api.get<{ factors: Factor[]; categories: string[]; supports_categories: boolean }>("/api/factors"), []);
  const strategies = useAsync(() => api.get<{ strategies: Array<Record<string, unknown>>; names: string[] }>("/api/strategies"), []);
  const instrumentSets = useAsync(() => api.get<{ sets: string[] }>("/api/data/instrument-sets"), []);
  const poolNames = instrumentSets.data?.sets || [];
  const libraryBtSpecs = useMemo(() => withInstrumentSetOptions(factorLibraryBacktestSpecs, poolNames), [instrumentSets.data]);
  const createStrategySpecs = useMemo(() => withInstrumentSetOptions(createStrategyFromFactorsSpecs, poolNames), [instrumentSets.data]);
  const [tab, setTab] = useState<"factors" | "strategies">("factors");
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selectedFactors, setSelectedFactors] = useState<string[]>([]);
  const [expr, setExpr] = useState("");
  const [name, setName] = useState("");
  const [newFactorCategories, setNewFactorCategories] = useState("");
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);
  const [categoryName, setCategoryName] = useState("");
  const [renameFrom, setRenameFrom] = useState("");
  const [renameTo, setRenameTo] = useState("");
  const [bulkCategory, setBulkCategory] = useState("");
  const [categoryExportPath, setCategoryExportPath] = useState("important_data/factor_zoo/category.csv");
  const [exportPath, setExportPath] = useState("important_data/factor_zoo/factor_zoo.csv");
  const [importKind, setImportKind] = useState("csv");
  const [importSource, setImportSource] = useState("");
  const factorBacktestAdvanced = useJsonInput("{}");
  const factorBacktestForm = useParamForm(libraryBtSpecs, factorBacktestAdvanced.raw);
  const [strategyName, setStrategyName] = useState("");
  const [strategyExportName, setStrategyExportName] = useState("");
  const [strategyExportPath, setStrategyExportPath] = useState("");
  const [strategyImportPath, setStrategyImportPath] = useState("");
  const { busy, run } = useAction();
  const strategyParams = useJsonInput("{}");
  const [showCreateStrategy, setShowCreateStrategy] = useState(false);
  const createStrategyForm = useParamForm(createStrategySpecs);
  const [dupResult, setDupResult] = useState<DuplicatesResult | null>(null);
  const [dupDelete, setDupDelete] = useState<Record<string, boolean>>({});
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return (factors.data?.factors || []).filter((f) => {
      const cats = f.categories || [];
      if (categoryFilter && !cats.includes(categoryFilter)) return false;
      return `${f.factor_name} ${f.factor_expression} ${cats.join(" ")}`.toLowerCase().includes(q);
    });
  }, [factors.data, search, categoryFilter]);
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    (factors.data?.categories || []).forEach((cat) => { counts[cat] = 0; });
    (factors.data?.factors || []).forEach((factor) => (factor.categories || []).forEach((cat) => { counts[cat] = (counts[cat] || 0) + 1; }));
    return counts;
  }, [factors.data]);

  function toggleFactor(factorName: string) {
    setSelectedFactors((current) => current.includes(factorName) ? current.filter((name) => name !== factorName) : [...current, factorName]);
  }

  function addFactor() {
    void run(async () => {
      const categories = newFactorCategories.split(",").map((item) => item.trim()).filter(Boolean);
      const result = await api.post<FactorValidationResponse>("/api/factors", { factor_name: name, factor_expression: expr, categories });
      setValidation(result);
      if (result.acceptable === false) {
        throw new Error(factorValidationMessage(result));
      }
      setName("");
      setExpr("");
      setNewFactorCategories("");
      await factors.refresh();
    }, t("save"));
  }

  function validateFactor() {
    void run(async () => {
      setValidation(await api.post<Record<string, unknown>>("/api/factors/validate", { expression: expr }));
    });
  }

  async function deleteFactor(factorName: string) {
    const target = factorName.trim();
    if (!target || !(await confirm({ message: `${t("delete")} ${target}?`, danger: true }))) return;
    void run(async () => {
      await api.delete(`/api/factors/${encodeURIComponent(target)}`);
      setSelectedFactors((current) => current.filter((name) => name !== target));
      await factors.refresh();
    }, t("delete"));
  }

  function applyBulkCategory(op: "add" | "remove") {
    const category = bulkCategory.trim();
    if (!category || !selectedFactors.length) return;
    void run(async () => {
      await api.post<Record<string, unknown>>(`/api/factors/categories/bulk?op=${op}`, { factor_names: selectedFactors, category });
      await factors.refresh();
    }, op === "add" ? t("bulkAddCategory") : t("bulkRemoveCategory"));
  }

  function backtestSelected() {
    void run(async () => {
      await api.post<Job>("/api/factors/backtest", { factor_names: selectedFactors, options: factorBacktestForm.parse() });
    }, t("started"));
  }

  function backtestCategory(category: string) {
    void run(async () => {
      await api.post<Job>("/api/factors/backtest", { category, options: factorBacktestForm.parse() });
    }, `${t("started")} · ${category}`);
  }

  function exportCategory(category: string) {
    void run(async () => {
      const result = await api.post<Record<string, unknown>>("/api/factors/categories/bulk?op=export", { category, output_path: categoryExportPath });
      void result;
    }, `${t("exportedTo")} ${categoryExportPath}`);
  }

  function saveStrategy() {
    void run(async () => {
      await api.post("/api/strategies", { strategy_name: strategyName, params: strategyParams.parse() });
      setStrategyName("");
      await strategies.refresh();
    }, t("save"));
  }

  async function deleteStrategy(strategyName: string) {
    const target = strategyName.trim();
    if (!target || !(await confirm({ message: `${t("delete")} ${target}?`, danger: true }))) return;
    void run(async () => {
      await api.delete(`/api/strategies/${encodeURIComponent(target)}`);
      await strategies.refresh();
    }, t("delete"));
  }

  function createStrategyFromFactors() {
    void run(async () => {
      const params = createStrategyForm.parse();
      await api.post("/api/strategies/from-factors", { factor_names: selectedFactors, ...params });
      setShowCreateStrategy(false);
      await strategies.refresh();
      setTab("strategies");
    }, t("createdStrategy"));
  }

  function checkDuplicates() {
    void run(async () => {
      const res = await api.get<DuplicatesResult>("/api/factors/duplicates");
      const preset: Record<string, boolean> = {};
      res.groups.forEach((group) => group.suggested_delete.forEach((nm) => { preset[nm] = true; }));
      setDupDelete(preset);
      setDupResult(res);
    }, t("checkDuplicates"));
  }

  function toggleDup(factorName: string) {
    setDupDelete((current) => ({ ...current, [factorName]: !current[factorName] }));
  }

  async function deleteDuplicates() {
    const names = Object.keys(dupDelete).filter((nm) => dupDelete[nm]);
    if (!names.length) return;
    if (!(await confirm({ message: `${t("deleteSelected")} ${names.length} ${t("factorsUnit")}?`, danger: true }))) return;
    void run(async () => {
      await api.post("/api/factors/bulk-delete", { factor_names: names });
      setDupResult(null);
      setDupDelete({});
      setSelectedFactors((current) => current.filter((name) => !names.includes(name)));
      await factors.refresh();
    }, t("deleteSelected"));
  }

  return (
    <>
      <PageTitle title={t("library")} subtitle={t("librarySubtitle")} />
      <div className="tabs">
        <button className={tab === "factors" ? "active" : ""} onClick={() => setTab("factors")}>{t("factors")}</button>
        <button className={tab === "strategies" ? "active" : ""} onClick={() => setTab("strategies")}>{t("strategies")}</button>
      </div>
      {tab === "factors" ? (
        <div className="grid side">
          <section className="panel">
            <div className="panel-head">
              <div className="panel-title-inline">
                <h2>{t("factors")}</h2>
                <PanelHelp
                  label={t("factorLibraryHelp")}
                  title={t("factorLibraryHelpTitle")}
                  intro={t("factorLibraryHelpIntro")}
                  items={[
                    t("factorLibraryHelpFilter"),
                    t("factorLibraryHelpBulk"),
                    t("factorLibraryHelpDuplicates"),
                    t("factorLibraryHelpBacktest"),
                    t("factorLibraryHelpStrategy")
                  ]}
                  footer={t("factorLibraryHelpFlow")}
                />
              </div>
              <input placeholder={t("search")} value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <div className="toolbar">
              <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                <option value="">{t("allCategories")}</option>
                {(factors.data?.categories || []).map((cat) => <option key={cat} value={cat}>{cat}</option>)}
              </select>
              <button className="button small" onClick={() => setSelectedFactors(filtered.map((factor) => factor.factor_name))}>{t("selectAllList")}</button>
              <button className="button small" onClick={() => setSelectedFactors([])}>{t("clearSelection")}</button>
              <button className="button small" disabled={busy} onClick={() => checkDuplicates()}>{t("checkDuplicates")}</button>
            </div>
            {factors.error ? <Alert tone="error">{factors.error}</Alert> : null}
            <DataTable
              rows={filtered as unknown as Record<string, unknown>[]}
              empty={t("empty")}
              loading={factors.loading}
              columns={[
                {
                  key: "select",
                  label: "",
                  render: (row) => <input className="row-check" type="checkbox" checked={selectedFactors.includes(String(row.factor_name))} onChange={() => toggleFactor(String(row.factor_name))} />
                },
                { key: "factor_name", label: t("colName") },
                { key: "factor_expression", label: t("colExpression"), ellipsis: true },
                { key: "categories", label: t("colCategories"), render: (row) => ((row.categories as string[]) || []).join(", ") },
                {
                  key: "factor_name",
                  label: t("colActions"),
                  align: "right",
                  render: (row) => (
                    <div className="row-actions">
                      <button className="button small" disabled={busy} onClick={() => { const name = String(row.factor_name); const next = window.prompt(t("renameFactorPrompt"), name); if (next && next.trim() && next.trim() !== name) void run(async () => { await api.patch(`/api/factors/${encodeURIComponent(name)}`, { new_name: next.trim() }); await factors.refresh(); }, t("renameFactor")); }}>{t("rename")}</button>
                      <button className="button small danger" disabled={busy} onClick={() => deleteFactor(String(row.factor_name))}>{t("delete")}</button>
                    </div>
                  )
                }
              ]}
            />
            <div className="toolbar below">
              <span className="muted">{t("selected")} {selectedFactors.length} {t("factorsUnit")}</span>
              <input placeholder={t("categoryNamePh")} value={bulkCategory} onChange={(e) => setBulkCategory(e.target.value)} />
              <button className="button small" disabled={busy || !selectedFactors.length || !bulkCategory.trim()} onClick={() => applyBulkCategory("add")}>{t("bulkAddCategory")}</button>
              <button className="button small" disabled={busy || !selectedFactors.length || !bulkCategory.trim()} onClick={() => applyBulkCategory("remove")}>{t("bulkRemoveCategory")}</button>
              <button className="button small primary" disabled={busy || !selectedFactors.length} onClick={() => backtestSelected()}>{t("backtestSelected")}</button>
              <button className="button small" disabled={busy || !selectedFactors.length} onClick={() => setShowCreateStrategy((v) => !v)}>{t("createStrategy")}</button>
            </div>
            {showCreateStrategy ? (
              <section className="panel inset">
                <h3>{t("createStrategy")}</h3>
                <p className="muted">{t("selected")} {selectedFactors.length} {t("factorsUnit")}</p>
                <DynamicForm specs={createStrategySpecs} values={createStrategyForm.values} onChange={createStrategyForm.setValue} errors={createStrategyForm.errors} />
                <button className="button primary" disabled={busy || !selectedFactors.length} onClick={() => createStrategyFromFactors()}>{busy ? <Spinner /> : null}{t("save")}</button>
              </section>
            ) : null}
            {dupResult ? (
              <section className="panel inset">
                <div className="panel-head">
                  <h3>{t("duplicateGroups")} ({dupResult.n_duplicate_groups})</h3>
                  <button className="button small" onClick={() => setDupResult(null)}>{t("cancel")}</button>
                </div>
                {dupResult.groups.length === 0 ? (
                  <p className="muted">{t("noDuplicates")}</p>
                ) : (
                  <>
                    {dupResult.groups.map((group, gi) => (
                      <div key={gi} className="dup-group">
                        <p className="muted">{t("sharedExpression")}: <code>{group.canonical}</code></p>
                        {group.members.map((member) => (
                          <label key={member.factor_name} className="inline-check">
                            <input
                              className="row-check"
                              type="checkbox"
                              checked={Boolean(dupDelete[member.factor_name])}
                              onChange={() => toggleDup(member.factor_name)}
                            />
                            <span>
                              {member.factor_name}
                              {member.factor_name === group.suggested_keep ? ` (${t("suggestedKeep")})` : ""}
                              : <code>{member.factor_expression}</code>
                            </span>
                          </label>
                        ))}
                      </div>
                    ))}
                    <button
                      className="button small danger"
                      disabled={busy || !Object.values(dupDelete).some(Boolean)}
                      onClick={() => deleteDuplicates()}
                    >
                      {busy ? <Spinner /> : null}{t("deleteSelected")}
                    </button>
                  </>
                )}
                {dupResult.similar_pairs.length ? (
                  <div className="dup-similar">
                    <h4>{t("similarPairs")}</h4>
                    {dupResult.similar_pairs.map((pair, pi) => (
                      <p key={pi} className="muted">
                        {pair.factor_a} ~ {pair.factor_b} · {Math.round(pair.similarity * 100)}% · <code>{pair.shared}</code>
                      </p>
                    ))}
                  </div>
                ) : null}
              </section>
            ) : null}
            <details>
              <summary>{t("backtestParams")}</summary>
              <DynamicForm specs={libraryBtSpecs} values={factorBacktestForm.values} onChange={factorBacktestForm.setValue} errors={factorBacktestForm.errors} />
              <details>
                <summary>{t("advancedJson")}</summary>
                <JsonTextArea value={factorBacktestAdvanced.raw} onChange={factorBacktestAdvanced.setRaw} rows={5} />
              </details>
            </details>
          </section>
          <aside className="panel">
            <div className="panel-head compact">
              <h2>{t("addFactor")}</h2>
              <PanelHelp
                label={t("factorManageHelp")}
                title={t("factorManageHelpTitle")}
                intro={t("factorManageHelpIntro")}
                items={[
                  t("factorManageHelpAdd"),
                  t("factorManageHelpValidate"),
                  t("factorManageHelpCategories"),
                  t("factorManageHelpImport"),
                  t("factorManageHelpExport")
                ]}
                footer={t("factorManageHelpFlow")}
              />
            </div>
            <input placeholder="factor_name" value={name} onChange={(e) => setName(e.target.value)} />
            <textarea rows={7} placeholder="factor_expression" value={expr} onChange={(e) => setExpr(e.target.value)} />
            <input placeholder={t("categoriesCommaPh")} value={newFactorCategories} onChange={(e) => setNewFactorCategories(e.target.value)} />
            <button className="button" disabled={busy} onClick={() => validateFactor()}>{t("validate")}</button>
            <button className="button primary" disabled={busy} onClick={() => addFactor()}>{busy ? <Spinner /> : null}{t("save")}</button>
            {validation ? <pre className="inline-json">{JSON.stringify(validation, null, 2)}</pre> : null}
            <h3>{t("colCategories")}</h3>
            <DataTable
              rows={Object.entries(categoryCounts).map(([category, count]) => ({ category, count }))}
              columns={[
                { key: "category", label: t("colCategory") },
                { key: "count", label: t("colFactors"), align: "right" },
                {
                  key: "category",
                  label: t("colActions"),
                  align: "right",
                  render: (row) => (
                    <div className="row-actions">
                      <button className="button small" disabled={busy} onClick={() => backtestCategory(String(row.category))}>{t("backtestShort")}</button>
                      <button className="button small" disabled={busy} onClick={() => exportCategory(String(row.category))}>{t("exportShort")}</button>
                    </div>
                  )
                }
              ]}
            />
            <input placeholder={t("categoryExportPathPh")} value={categoryExportPath} onChange={(e) => setCategoryExportPath(e.target.value)} />
            <input placeholder={t("newCategoryPh")} value={categoryName} onChange={(e) => setCategoryName(e.target.value)} />
            <button className="button" disabled={busy || !categoryName.trim()} onClick={() => void run(async () => { await api.post("/api/factors/categories", { name: categoryName }); setCategoryName(""); await factors.refresh(); }, t("createCategory"))}>{t("createCategory")}</button>
            <select value={renameFrom} onChange={(e) => setRenameFrom(e.target.value)}>
              <option value="">{t("selectCategoryToRename")}</option>
              {(factors.data?.categories || []).map((cat) => <option key={cat} value={cat}>{cat}</option>)}
            </select>
            <input placeholder={t("newCategoryNamePh")} value={renameTo} onChange={(e) => setRenameTo(e.target.value)} />
            <button className="button" disabled={busy || !renameFrom || !renameTo.trim()} onClick={() => void run(async () => { await api.patch(`/api/factors/categories/${encodeURIComponent(renameFrom)}`, { new_name: renameTo }); setRenameFrom(""); setRenameTo(""); await factors.refresh(); }, t("renameCategory"))}>{t("renameCategory")}</button>
            <button className="button danger" disabled={busy || !renameFrom} onClick={async () => { if (!(await confirm({ message: `${t("deleteCategory")} ${renameFrom}?`, danger: true }))) return; void run(async () => { await api.delete(`/api/factors/categories/${encodeURIComponent(renameFrom)}`); setRenameFrom(""); await factors.refresh(); }, t("deleteCategory")); }}>{t("deleteCategory")}</button>
            <h3>{t("importExport")}</h3>
            <select value={importKind} onChange={(e) => setImportKind(e.target.value)}>
              <option value="csv">CSV</option>
              <option value="json">JSON</option>
              <option value="pdf">PDF</option>
            </select>
            <input placeholder={t("importSourcePh")} value={importSource} onChange={(e) => setImportSource(e.target.value)} />
            <button className="button" disabled={busy} onClick={() => void run(async () => { await api.post("/api/factors/import", { kind: importKind, source: importSource }); await factors.refresh(); }, t("importFactors"))}>{t("importFactors")}</button>
            <input placeholder={t("exportPathPh")} value={exportPath} onChange={(e) => setExportPath(e.target.value)} />
            <button className="button" disabled={busy} onClick={() => void run(async () => { await api.post("/api/factors/export", { output_path: exportPath }); }, `${t("exportedTo")} ${exportPath}`)}>{t("exportLibrary")}</button>
          </aside>
        </div>
      ) : (
        <div className="grid side">
          <section className="panel">
            <h2>{t("strategies")}</h2>
            <DataTable
              rows={(strategies.data?.strategies || []) as Record<string, unknown>[]}
              empty={t("empty")}
              loading={strategies.loading}
              columns={[
                { key: "strategy_name", label: t("colName") },
                { key: "metrics", label: t("colMetrics"), ellipsis: true, render: (row) => <code>{JSON.stringify(row.metrics || {})}</code> },
                {
                  key: "strategy_name",
                  label: t("colActions"),
                  align: "right",
                  render: (row) => (
                    <div className="row-actions">
                      <button className="button small" onClick={() => { setStrategyExportName(String(row.strategy_name)); setStrategyExportPath(`important_data/strategy_zoo/${String(row.strategy_name)}.json`); }}>{t("exportShort")}</button>
                      <button className="button small danger" disabled={busy} onClick={() => deleteStrategy(String(row.strategy_name))}>{t("delete")}</button>
                    </div>
                  )
                }
              ]}
            />
          </section>
          <aside className="panel">
            <div className="panel-head compact">
              <h2>{t("saveStrategyParams")}</h2>
              <PanelHelp
                label={t("strategyParamsHelp")}
                title={t("strategyParamsHelpTitle")}
                intro={t("strategyParamsHelpIntro")}
                items={[
                  t("strategyParamsHelpName"),
                  t("strategyParamsHelpJson"),
                  t("strategyParamsHelpExport"),
                  t("strategyParamsHelpImport")
                ]}
                footer={t("strategyParamsHelpRisk")}
              />
            </div>
            <input placeholder="strategy_name" value={strategyName} onChange={(e) => setStrategyName(e.target.value)} />
            <HybridJsonEditor value={strategyParams.raw} onChange={strategyParams.setRaw} rows={8} />
            <button className="button primary" disabled={busy} onClick={() => saveStrategy()}>{busy ? <Spinner /> : null}{t("save")}</button>
            <h3>{t("exportStrategyParams")}</h3>
            <input placeholder="strategy_name" value={strategyExportName} onChange={(e) => setStrategyExportName(e.target.value)} />
            <input placeholder="export_file_path" value={strategyExportPath} onChange={(e) => setStrategyExportPath(e.target.value)} />
            <button className="button" disabled={busy} onClick={() => void run(async () => { await api.post("/api/strategies/export", { strategy_name: strategyExportName, output_path: strategyExportPath }); }, `${t("exportedTo")} ${strategyExportPath}`)}>{t("exportShort")}</button>
            <h3>{t("importFromPdf")}</h3>
            <input placeholder="pdf_path" value={strategyImportPath} onChange={(e) => setStrategyImportPath(e.target.value)} />
            <button className="button" disabled={busy} onClick={() => void run(async () => { await api.post("/api/strategies/import", { kind: "pdf", source: strategyImportPath }); await strategies.refresh(); }, t("importPdf"))}>{t("importPdf")}</button>
          </aside>
        </div>
      )}
    </>
  );
}

type PoolSummary = { name: string; description: string; count: number; updated_at: string };
type PoolDetail = { name: string; description: string; symbols: string[]; created_at?: string; updated_at?: string };
type PoolReport = { name: string; valid_count?: number; invalid?: string[]; missing_data?: string[]; instruments_path?: string | null };

function callPool<T>(command: string, kwargs: Record<string, unknown>): Promise<T> {
  return api.post<T>("/api/modules/run", { module: "stock_pool", command, kwargs });
}

// Split a free-text symbol field into a normalized code list (accepts comma / whitespace / newline).
function parseSymbolText(text: string): string[] {
  return text.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
}

// Merge picked codes into an existing symbol field, de-duplicated and order-preserving.
function mergeSymbolText(current: string, additions: string[]): string {
  const seen = new Set<string>();
  const merged: string[] = [];
  for (const code of [...parseSymbolText(current), ...additions]) {
    if (!seen.has(code)) {
      seen.add(code);
      merged.push(code);
    }
  }
  return merged.join(", ");
}

// Picker over already-downloaded symbols (GET /api/data/symbols), with source switch, search,
// select-all / clear and batch add. ``onAdd`` receives the checked codes; ``selectedText`` is the
// caller's current symbol field so codes already queued there are shown as added.
function SymbolPicker({ onAdd, selectedText }: { onAdd: (symbols: string[]) => void; selectedText: string }) {
  const { t } = useI18n();
  const [source, setSource] = useState("baostock_cn");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());

  async function load(src = source) {
    setLoading(true);
    try {
      const result = await api.get<Record<string, string[]>>(`/api/data/symbols${qs({ source: src })}`);
      setSymbols(Array.from(new Set(Object.values(result).flat())).sort());
    } catch {
      setSymbols([]);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const already = useMemo(() => new Set(parseSymbolText(selectedText)), [selectedText]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? symbols.filter((s) => s.toLowerCase().includes(q)) : symbols;
  }, [symbols, search]);

  function toggle(sym: string) {
    setChecked((cur) => {
      const next = new Set(cur);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
  }
  function commit() {
    if (!checked.size) return;
    onAdd([...checked]);
    setChecked(new Set());
  }

  return (
    <div className="symbol-picker">
      <div className="picker-toolbar">
        <select value={source} onChange={(e) => { setSource(e.target.value); void load(e.target.value); }}>
          <option value="baostock_cn">baostock_cn</option>
          <option value="tushare_cn">tushare_cn</option>
        </select>
        <input placeholder={t("search")} value={search} onChange={(e) => setSearch(e.target.value)} />
        <RefreshButton iconOnly onClick={() => load()} />
      </div>
      <div className="picker-actions">
        <button type="button" className="button small" disabled={!filtered.length} onClick={() => setChecked((cur) => new Set([...cur, ...filtered]))}>{t("selectAllList")}</button>
        <button type="button" className="button small" disabled={!checked.size} onClick={() => setChecked(new Set())}>{t("clearSelection")}</button>
        <span className="muted small-text">{t("selected")} {checked.size} / {symbols.length}</span>
      </div>
      {loading ? (
        <div className="empty loading-row"><Spinner /> {t("loading")}</div>
      ) : symbols.length === 0 ? (
        <div className="empty">{t("spNoDownloaded")}</div>
      ) : (
        <div className="symbol-list">
          {filtered.map((sym) => (
            <label key={sym} className={`symbol-item${already.has(sym) ? " added" : ""}`}>
              <input type="checkbox" checked={checked.has(sym)} onChange={() => toggle(sym)} />
              <span>{sym}</span>
            </label>
          ))}
          {filtered.length === 0 ? <span className="muted small-text">{t("empty")}</span> : null}
        </div>
      )}
      <button type="button" className="button small primary" disabled={!checked.size} onClick={commit}>{t("spAddSelected")} ({checked.size})</button>
    </div>
  );
}

// Stock pool (股票池) CRUD: batch-create pools, edit members, rename, delete. Reuses the generic
// /api/modules/run dispatch to call the stock_pool module's pool_* commands. Rendered inside the
// Market Data page.
function StockPoolManager() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const { busy, run } = useAction();
  const toast = useToast();
  const pools = useAsync(() => callPool<PoolSummary[]>("pool_list", {}), []);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<PoolDetail | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [symbols, setSymbols] = useState("");
  const [csv, setCsv] = useState("");
  const [addText, setAddText] = useState("");
  const [renameTo, setRenameTo] = useState("");

  async function loadDetail(poolName: string) {
    setSelected(poolName);
    if (!poolName) {
      setDetail(null);
      return;
    }
    try {
      setDetail(await callPool<PoolDetail>("pool_show", { name: poolName }));
    } catch {
      setDetail(null);
    }
  }

  function reportExtra(r: PoolReport): string {
    const parts: string[] = [];
    if (r.invalid?.length) parts.push(`${t("spInvalid")}: ${r.invalid.join(", ")}`);
    if (r.missing_data?.length) parts.push(`${t("spMissing")}: ${r.missing_data.join(", ")}`);
    return parts.length ? ` · ${parts.join(" | ")}` : "";
  }

  function createPool() {
    void run(async () => {
      const report = await callPool<PoolReport>("pool_create", {
        name,
        description,
        symbols: symbols || null,
        stock_csv: csv.trim() || null,
      });
      setName("");
      setDescription("");
      setSymbols("");
      setCsv("");
      await pools.refresh();
      await loadDetail(report.name);
      toast.success(`${t("spCreated")} ${report.name}${reportExtra(report)}`);
    });
  }

  function addSymbols() {
    if (!selected) return;
    void run(async () => {
      const report = await callPool<PoolReport>("pool_add", { name: selected, symbols: addText || null });
      setAddText("");
      await pools.refresh();
      await loadDetail(selected);
      toast.success(`${t("spUpdated")}${reportExtra(report)}`);
    });
  }

  function removeSymbol(sym: string) {
    if (!selected) return;
    void run(async () => {
      await callPool("pool_remove", { name: selected, symbols: sym });
      await pools.refresh();
      await loadDetail(selected);
    });
  }

  function renamePool() {
    const next = renameTo.trim();
    if (!selected || !next) return;
    void run(async () => {
      await callPool("pool_rename", { name: selected, new_name: next });
      setRenameTo("");
      await pools.refresh();
      await loadDetail(next);
    }, t("spUpdated"));
  }

  async function deletePool(poolName: string) {
    if (!(await confirm({ message: `${t("delete")} ${poolName}?`, danger: true }))) return;
    void run(async () => {
      await callPool("pool_delete", { name: poolName });
      if (selected === poolName) {
        setSelected("");
        setDetail(null);
      }
      await pools.refresh();
    }, t("spDeleted"));
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{t("spManageTitle")}</h2>
        <RefreshButton className="button small" onClick={() => pools.refresh()} />
      </div>
      <p className="muted">{t("spManageSubtitle")}</p>
      {pools.error ? <Alert tone="error">{pools.error}</Alert> : null}
      <div className="grid two">
        <div>
          <h3>{t("spCreate")}</h3>
          <div className="dynamic-form cols-1">
            <label>{t("spName")}<input value={name} onChange={(e) => setName(e.target.value)} placeholder="my_pool" /></label>
            <label>{t("spDescription")}<input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
            <label>{t("spSymbols")}<textarea rows={4} value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="600519.SH, 000001.SZ" /><small>{t("spSymbolsHelp")}</small></label>
            <label>{t("spImportCsv")}<input value={csv} onChange={(e) => setCsv(e.target.value)} placeholder="important_data/stock_lists/xxx.csv" /></label>
          </div>
          <details className="symbol-picker-wrap" open>
            <summary>{t("spPickFromDownloaded")}</summary>
            <SymbolPicker selectedText={symbols} onAdd={(picked) => setSymbols((cur) => mergeSymbolText(cur, picked))} />
          </details>
          <button className="button primary" disabled={busy} onClick={createPool}>{busy ? <Spinner /> : null}{t("spCreateBtn")}</button>
        </div>
        <div>
          <h3>{t("spPools")}</h3>
          <DataTable
            rows={(pools.data || []) as unknown as Record<string, unknown>[]}
            empty={t("spNoPools")}
            loading={pools.loading}
            columns={[
              { key: "name", label: t("spName") },
              { key: "count", label: t("spMembers"), align: "right" },
              { key: "description", label: t("spDescription"), ellipsis: true },
              {
                key: "name",
                label: t("colActions"),
                align: "right",
                render: (row) => (
                  <div className="row-actions">
                    <button className="button small" onClick={() => void loadDetail(String(row.name))}>{t("preview")}</button>
                    <button className="button small danger" disabled={busy} onClick={() => void deletePool(String(row.name))}>{t("delete")}</button>
                  </div>
                )
              }
            ]}
          />
        </div>
      </div>
      {detail ? (
        <div className="pool-detail">
          <h3>{detail.name} · {t("spMembers")} ({detail.symbols.length})</h3>
          <div className="tag-list">
            {detail.symbols.map((sym) => (
              <span key={sym} className="tag removable">
                {sym}
                <button disabled={busy} title={t("delete")} aria-label={`${t("delete")} ${sym}`} onClick={() => removeSymbol(sym)}>×</button>
              </span>
            ))}
            {detail.symbols.length === 0 ? <span className="muted">{t("empty")}</span> : null}
          </div>
          <div className="grid two">
            <div>
              <label>{t("spAdd")}<textarea rows={2} value={addText} onChange={(e) => setAddText(e.target.value)} placeholder="600519.SH, 000001.SZ" /></label>
              <details className="symbol-picker-wrap">
                <summary>{t("spPickFromDownloaded")}</summary>
                <SymbolPicker selectedText={addText} onAdd={(picked) => setAddText((cur) => mergeSymbolText(cur, picked))} />
              </details>
              <button className="button small" disabled={busy} onClick={addSymbols}>{t("spAddBtn")}</button>
            </div>
            <div>
              <label>{t("spRename")}<input value={renameTo} onChange={(e) => setRenameTo(e.target.value)} placeholder="new_name" /></label>
              <button className="button small" disabled={busy} onClick={renamePool}>{t("spRenameBtn")}</button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function MarketPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const sources = useAsync(() => api.get<Array<Record<string, unknown>>>("/api/market/sources"), []);
  const dataJobs = useAsync(() => api.get<Job[]>("/api/jobs"), []);
  const dataAdvanced = useJsonInput("{}");
  const dataForm = useParamForm(dataActionSpecs, dataAdvanced.raw);
  const [universe, setUniverse] = useState<string[]>([]);
  const [dataMessage, setDataMessage] = useState<string | null>(null);
  const [activeDataJob, setActiveDataJob] = useState<Job | null>(null);
  const [dataProgress, setDataProgress] = useState<JobProgress | null>(null);
  const [dataDir, setDataDir] = useState("");
  const [symbol, setSymbol] = useState("");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [kline, setKline] = useState<Record<string, unknown> | null>(null);
  const [klineRange, setKlineRange] = useState<KlineRange>("ALL");
  const [klineSubMetric, setKlineSubMetric] = useState<KlineMetric>("amount");
  const [manageSource, setManageSource] = useState("baostock_cn");
  const [manageSymbols, setManageSymbols] = useState<string[]>([]);
  const [manageSymbol, setManageSymbol] = useState("");
  const [manageMode, setManageMode] = useState("backward");
  const [refreshStart, setRefreshStart] = useState("2016-12-31");
  const [refreshEnd, setRefreshEnd] = useState("");
  const [trimStart, setTrimStart] = useState("");
  const [trimEnd, setTrimEnd] = useState("");
  const [dropDates, setDropDates] = useState("");
  const [applyTarget, setApplyTarget] = useState("forward");
  const { busy, run } = useAction();

  React.useEffect(() => {
    if (!activeDataJob?.job_id) return;
    let alive = true;
    const poll = async () => {
      try {
        const progress = await api.get<JobProgress>(`/api/jobs/${activeDataJob.job_id}/progress`);
        if (!alive) return;
        setDataProgress(progress);
        if (progress.status && ["succeeded", "failed", "cancelled", "lost"].includes(progress.status)) {
          await dataJobs.refresh();
        }
      } catch (err) {
        if (alive) setDataMessage(err instanceof Error ? err.message : String(err));
      }
    };
    void poll();
    const id = window.setInterval(poll, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [activeDataJob?.job_id]);

  async function loadSymbols(path: string) {
    setDataDir(path);
    setKline(null);
    setSymbols(await api.get<string[]>(`/api/market/symbols${qs({ data_dir: path })}`));
  }

  function loadKline() {
    void run(async () => {
      setKline(await api.get(`/api/market/kline${qs({ data_dir: dataDir, symbol })}`));
    });
  }

  async function runDataActionImpl() {
    const kwargs = dataForm.parse();
    const job = await api.post<Job>("/api/jobs", { kind: "data", kwargs });
    setActiveDataJob(job);
    setDataProgress(job.progress || { job_id: job.job_id, status: job.status, percent: 0, stage: "queued", message: "queued" });
    setDataMessage(`已启动数据任务：${job.job_id}`);
    await dataJobs.refresh();
  }

  function runDataAction() {
    void run(() => runDataActionImpl());
  }

  function loadUniverse() {
    void run(async () => {
      const result = await api.get<{ count: number; symbols: string[] }>(`/api/data/universe${qs({ stock_csv: dataForm.values.stock_csv })}`);
      setUniverse(result.symbols || []);
    });
  }

  async function loadManageSymbols(source = manageSource) {
    const result = await api.get<Record<string, string[]>>(`/api/data/symbols${qs({ source })}`);
    const all = Array.from(new Set(Object.values(result).flat())).sort();
    setManageSymbols(all);
    if (!all.includes(manageSymbol)) setManageSymbol(all[0] || "");
  }

  function symbolAction(path: string, options: Record<string, unknown>) {
    if (!manageSymbol) return;
    void run(async () => {
      const result = await api.post(path, { symbol: manageSymbol, options: { source: manageSource, ...options } });
      setDataMessage(JSON.stringify(result, null, 2));
      await loadManageSymbols();
    });
  }

  const klinePayload = kline as KlinePayload | null;
  const rows = useMemo(() => normalizeKlineRows(klinePayload?.rows || []), [klinePayload]);
  const chartMetric = resolveKlineMetric(rows, klineSubMetric);
  const latestRow = rows[rows.length - 1];
  const previousRow = rows[rows.length - 2];
  const latestPct = latestRow ? metricValue(latestRow, "pctChg", previousRow) : undefined;
  const subMetricValues = rows.map((row, index) => metricValue(row, chartMetric, rows[index - 1]) ?? null);
  const volumeColors = rows.map((row) => (row.close >= row.open ? "rgba(239, 83, 80, 0.72)" : "rgba(38, 166, 154, 0.72)"));
  const klineLabel = String(klinePayload?.label || klinePayload?.symbol || symbol || t("kline"));
  const klineDateRange = Array.isArray(klinePayload?.date_range)
    ? `${formatDateLabel(klinePayload?.date_range[0])} - ${formatDateLabel(klinePayload?.date_range[1])}`
    : rows.length
      ? `${formatDateLabel(rows[0].date)} - ${formatDateLabel(rows[rows.length - 1].date)}`
      : "-";
  const metricLabels: Record<KlineMetric, string> = {
    amount: t("klineMetricAmount"),
    volume: t("klineMetricVolume"),
    turn: t("klineMetricTurn"),
    pctChg: t("klineMetricPct")
  };
  // Minute K-lines use a category x-axis (continuous bars, no lunch/overnight gaps); daily keeps
  // the proportional date axis. The range window maps to bar indices in the intraday case.
  const klineXAxisType = klineAxisType(rows);
  const chartRange = klineXAxisType === "category"
    ? klineCategoryRange(rows, klineRange)
    : klineRangeValue(rows, klineRange);
  // Intraday: replace the crammed per-bar timestamps with a few time-only ticks.
  const intradayTickProps = klineXAxisType === "category"
    ? (() => {
        const { tickvals, ticktext } = klineCategoryTicks(rows, chartRange as [number, number] | undefined);
        return { tickmode: "array" as const, tickvals, ticktext };
      })()
    : {};
  const chartColors = {
    surface: cssVar("--surface", "#ffffff"),
    surface2: cssVar("--surface-2", "#f7f8fc"),
    border: cssVar("--border", "#e3e6ef"),
    text: cssVar("--text", "#1a2233"),
    muted: cssVar("--text-muted", "#667085"),
    up: "#ef5350",
    down: "#26a69a"
  };
  const klineHoverText = rows.map((row, index) => {
    const pct = metricValue(row, "pctChg", rows[index - 1]);
    return [
      `<b>${formatDateLabel(row.date)}</b>`,
      `${t("klineOpen")}: ${formatPrice(row.open)}`,
      `${t("klineHigh")}: ${formatPrice(row.high)}`,
      `${t("klineLow")}: ${formatPrice(row.low)}`,
      `${t("klineClose")}: ${formatPrice(row.close)}`,
      `${t("klineMetricPct")}: ${formatPercent(pct)}`,
      `${t("klineMetricAmount")}: ${formatCompactNumber(row.amount)}`,
      `${t("klineMetricVolume")}: ${formatCompactNumber(row.volume)}`,
      `${t("klineMetricTurn")}: ${formatPercent(row.turn)}`
    ].join("<br>");
  });
  const recentDataJobs = (dataJobs.data || []).filter((job) => job.kind === "data").slice(0, 5);
  return (
    <>
      <PageTitle title={t("market")} subtitle={t("marketSubtitle")} />
      <StockPoolManager />
      {dataMessage ? <pre className="inline-json">{dataMessage}</pre> : null}
      <div className="grid side">
        <section className="panel">
          <div className="panel-head compact">
            <h2>{t("dataActions")}</h2>
            <PanelHelp
              label={t("dataActionsHelp")}
              title={t("dataActionsHelpTitle")}
              intro={t("dataActionsHelpIntro")}
              items={[
                t("dataActionsHelpAction"),
                t("dataActionsHelpSource"),
                t("dataActionsHelpDates"),
                t("dataActionsHelpStockCsv"),
                t("dataActionsHelpAdjust"),
                t("dataActionsHelpTarget"),
                t("dataActionsHelpTushare"),
                t("dataActionsHelpAdvanced")
              ]}
              footer={t("dataActionsHelpFlow")}
            />
          </div>
          <DynamicForm specs={dataActionSpecs} values={dataForm.values} onChange={dataForm.setValue} errors={dataForm.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={dataAdvanced.raw} onChange={dataAdvanced.setRaw} rows={5} />
          </details>
          <div className="row-actions left">
            <button className="button primary" disabled={busy} onClick={() => runDataAction()}>{busy ? <Spinner /> : null}{t("run")}</button>
            <button className="button" disabled={busy} onClick={() => loadUniverse()}>{t("loadUniverse")}</button>
          </div>
          {dataProgress ? (
            <div className="progress-card">
              <div className="panel-head compact">
                <h3>{t("currentDataTask")}</h3>
                <StatusPill status={dataProgress.status || activeDataJob?.status} />
              </div>
              <ProgressBar
                percent={dataProgress.percent}
                label={dataProgress.message || dataProgress.stage}
                active={dataProgress.status === "running"}
              />
              <code>{activeDataJob?.job_id}</code>
              <div className="progress-meta">
                {typeof dataProgress.completed === "number" && typeof dataProgress.total === "number" ? <span>{t("progDone")} {dataProgress.completed}/{dataProgress.total}</span> : null}
                {typeof dataProgress.pending === "number" ? <span>{t("progPending")} {dataProgress.pending}</span> : null}
                {dataProgress.current_symbol ? <span>{t("progSymbol")} {dataProgress.current_symbol}</span> : null}
                {dataProgress.current_file ? <span>{t("progFile")} {dataProgress.current_file}</span> : null}
                {dataProgress.updated_at ? <span>{t("progUpdated")} {new Date(dataProgress.updated_at).toLocaleTimeString()}</span> : null}
                {dataProgress.latest_data_date ? <span>{t("progLatestDate")} {dataProgress.latest_data_date}</span> : null}
                {dataProgress.progress_source ? <span>{dataProgress.progress_source}</span> : null}
              </div>
            </div>
          ) : null}
          {universe.length ? <div className="tag-list">{universe.slice(0, 80).map((s) => <span className="tag" key={s}>{s}</span>)}{universe.length > 80 ? <span className="tag">+{universe.length - 80}</span> : null}</div> : null}
        </section>
        <aside className="panel">
          <div className="panel-head compact">
            <h2>{t("symbolManage")}</h2>
            <PanelHelp
              label={t("symbolManageHelp")}
              title={t("symbolManageHelpTitle")}
              intro={t("symbolManageHelpIntro")}
              items={[
                t("symbolManageHelpRefresh"),
                t("symbolManageHelpAdjust"),
                t("symbolManageHelpTrim")
              ]}
              footer={t("symbolManageHelpRisk")}
            />
          </div>
          <select value={manageSource} onChange={(e) => { setManageSource(e.target.value); void loadManageSymbols(e.target.value); }}>
            <option value="baostock_cn">baostock_cn</option>
            <option value="tushare_cn">tushare_cn</option>
          </select>
          <RefreshButton className="button" onClick={() => loadManageSymbols()} />
          <select value={manageSymbol} onChange={(e) => setManageSymbol(e.target.value)}>
            <option value="">{t("selectSymbol")}</option>
            {manageSymbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={manageMode} onChange={(e) => setManageMode(e.target.value)}>
            <option value="backward">backward</option>
            <option value="forward">forward</option>
            <option value="none">none</option>
          </select>
          <button className="button danger" disabled={busy || !manageSymbol} onClick={async () => { if (!(await confirm({ message: `${t("delete")} ${manageSymbol}?`, danger: true }))) return; symbolAction("/api/data/symbols/delete", { adjust_mode: manageMode }); }}>{t("deleteSymbol")}</button>
          <h3>{t("refreshRedownload")}</h3>
          <input placeholder="start_date" value={refreshStart} onChange={(e) => setRefreshStart(e.target.value)} />
          <input placeholder="end_date" value={refreshEnd} onChange={(e) => setRefreshEnd(e.target.value)} />
          <button className="button" disabled={busy || !manageSymbol} onClick={() => symbolAction("/api/data/symbols/refresh", { adjust_mode: manageMode, start_date: refreshStart, end_date: refreshEnd || null, qlib_adjust_mode: manageMode })}>{t("refreshSymbol")}</button>
          <h3>{t("localAdjust")}</h3>
          <select value={applyTarget} onChange={(e) => setApplyTarget(e.target.value)}>
            <option value="forward">forward</option>
            <option value="backward">backward</option>
          </select>
          <button className="button" disabled={busy || !manageSymbol} onClick={() => symbolAction("/api/data/symbols/apply-adjust", { target_mode: applyTarget })}>{t("genAdjustedCsv")}</button>
          <h3>{t("trimDates")}</h3>
          <input placeholder="keep from YYYY-MM-DD" value={trimStart} onChange={(e) => setTrimStart(e.target.value)} />
          <input placeholder="keep until YYYY-MM-DD" value={trimEnd} onChange={(e) => setTrimEnd(e.target.value)} />
          <input placeholder="drop dates, comma separated" value={dropDates} onChange={(e) => setDropDates(e.target.value)} />
          <button className="button" disabled={busy || !manageSymbol} onClick={() => symbolAction("/api/data/symbols/trim", { adjust_mode: manageMode, start: trimStart || null, end: trimEnd || null, drop_dates: dropDates || null, qlib_adjust_mode: manageMode })}>{t("trimSymbol")}</button>
        </aside>
      </div>
      <section className="panel">
        <div className="panel-head">
          <h2>{t("recentDataTasks")}</h2>
          <RefreshButton className="button small" onClick={() => dataJobs.refresh()} />
        </div>
        <DataTable
          rows={recentDataJobs as unknown as Record<string, unknown>[]}
          loading={dataJobs.loading}
          columns={[
            { key: "job_id", label: t("colJobId"), ellipsis: true },
            { key: "status", label: t("status"), render: (row) => <StatusPill status={String(row.status)} /> },
            { key: "params", label: t("colDataAction"), render: (row) => <code>{String((row.params as Record<string, unknown> | undefined)?.action || "")}</code> },
            {
              key: "progress",
              label: t("progress"),
              render: (row) => {
                const progress = row.progress as JobProgress | undefined;
                return progress ? <ProgressBar percent={progress.percent} label={progress.message || progress.stage} /> : "";
              }
            }
          ]}
        />
      </section>
      <section className="panel">
        <h2>{t("kline")}</h2>
        {sources.error ? <Alert tone="error">{sources.error}</Alert> : null}
        <div className="toolbar kline-toolbar">
          <select value={dataDir} onChange={(e) => void loadSymbols(e.target.value)}>
            <option value="">{t("selectDataDir")}</option>
            {(sources.data || []).map((s) => <option key={String(s.path)} value={String(s.path)}>{String(s.label)}</option>)}
          </select>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            <option value="">{t("selectSymbol")}</option>
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="button" disabled={busy || !dataDir || !symbol} onClick={() => loadKline()}>{busy ? <Spinner /> : null}{t("refresh")}</button>
        </div>
      </section>
      {rows.length ? (
        <section className="panel kline-panel">
          <div className="kline-chart-head">
            <div>
              <h2>{klineLabel}</h2>
              <p>{klineDateRange}</p>
            </div>
            <div className="kline-controls">
              <div className="kline-range-buttons" aria-label={t("klineRange")}>
                {KLINE_RANGES.map((range) => (
                  <button
                    key={range}
                    className={range === klineRange ? "active" : ""}
                    onClick={() => setKlineRange(range)}
                    type="button"
                  >
                    {range === "ALL" ? t("klineRangeAll") : range}
                  </button>
                ))}
              </div>
              <select value={klineSubMetric} onChange={(e) => setKlineSubMetric(e.target.value as KlineMetric)} aria-label={t("klineSubMetric")}>
                {KLINE_METRICS.map((metric) => <option key={metric} value={metric}>{metricLabels[metric]}</option>)}
              </select>
            </div>
          </div>
          <div className="kline-stats">
            <div>
              <span>{t("klineClose")}</span>
              <strong>{formatPrice(latestRow?.close)}</strong>
            </div>
            <div className={latestPct !== undefined && latestPct >= 0 ? "up" : "down"}>
              <span>{t("klineMetricPct")}</span>
              <strong>{formatPercent(latestPct)}</strong>
            </div>
            <div>
              <span>{t("klineHigh")}</span>
              <strong>{formatPrice(latestRow?.high)}</strong>
            </div>
            <div>
              <span>{t("klineLow")}</span>
              <strong>{formatPrice(latestRow?.low)}</strong>
            </div>
            <div>
              <span>{metricLabels[chartMetric]}</span>
              <strong>{chartMetric === "pctChg" || chartMetric === "turn" ? formatPercent(metricValue(latestRow, chartMetric, previousRow)) : formatCompactNumber(metricValue(latestRow, chartMetric, previousRow))}</strong>
            </div>
          </div>
          {chartMetric !== klineSubMetric ? <p className="kline-note">{t("klineMetricFallback")}</p> : null}
          <Plot
            data={[
              {
                x: rows.map((row) => row.date),
                open: rows.map((row) => row.open),
                high: rows.map((row) => row.high),
                low: rows.map((row) => row.low),
                close: rows.map((row) => row.close),
                type: "candlestick",
                name: klineLabel,
                text: klineHoverText,
                hovertemplate: "%{text}<extra></extra>",
                increasing: { line: { color: chartColors.up, width: 1.1 }, fillcolor: chartColors.up },
                decreasing: { line: { color: chartColors.down, width: 1.1 }, fillcolor: chartColors.down },
                xaxis: "x",
                yaxis: "y"
              },
              {
                x: rows.map((row) => row.date),
                y: subMetricValues,
                type: "bar",
                name: metricLabels[chartMetric],
                marker: { color: chartMetric === "pctChg" ? volumeColors : volumeColors },
                hovertemplate: `<b>%{x}</b><br>${metricLabels[chartMetric]}: %{y:.2f}<extra></extra>`,
                xaxis: "x2",
                yaxis: "y2"
              }
            ]}
            layout={{
              autosize: true,
              height: Math.max(560, Math.min(780, chartHeight() + 180)),
              margin: { l: 18, r: 64, t: 10, b: 34 },
              paper_bgcolor: chartColors.surface,
              plot_bgcolor: chartColors.surface,
              font: { color: chartColors.text, size: 12 },
              dragmode: "pan",
              hovermode: "x unified",
              showlegend: false,
              bargap: 0,
              xaxis: {
                domain: [0, 1],
                anchor: "y",
                type: klineXAxisType,
                range: chartRange,
                rangeslider: { visible: false },
                showgrid: true,
                gridcolor: chartColors.border,
                showline: true,
                linecolor: chartColors.border,
                tickfont: { color: chartColors.muted },
                showspikes: true,
                spikemode: "across",
                spikesnap: "cursor",
                spikecolor: chartColors.muted,
                spikethickness: 1,
                ...intradayTickProps
              },
              xaxis2: {
                domain: [0, 1],
                anchor: "y2",
                matches: "x",
                type: klineXAxisType,
                showgrid: true,
                gridcolor: chartColors.border,
                showline: true,
                linecolor: chartColors.border,
                tickfont: { color: chartColors.muted },
                showspikes: true,
                spikemode: "across",
                spikesnap: "cursor",
                spikecolor: chartColors.muted,
                spikethickness: 1,
                ...intradayTickProps
              },
              yaxis: {
                domain: [0.28, 1],
                side: "right",
                fixedrange: false,
                showgrid: true,
                gridcolor: chartColors.border,
                zeroline: false,
                tickfont: { color: chartColors.muted }
              },
              yaxis2: {
                domain: [0, 0.22],
                side: "right",
                fixedrange: false,
                showgrid: true,
                gridcolor: chartColors.border,
                zeroline: false,
                title: { text: metricLabels[chartMetric], font: { color: chartColors.muted, size: 11 } },
                tickfont: { color: chartColors.muted }
              },
              hoverlabel: {
                bgcolor: chartColors.surface2,
                bordercolor: chartColors.border,
                font: { color: chartColors.text }
              }
            }}
            config={{
              responsive: true,
              displaylogo: false,
              modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d"]
            }}
            useResizeHandler
            style={{ width: "100%" }}
          />
        </section>
      ) : <div className="empty">{t("empty")}</div>}
    </>
  );
}

type TradeSessionManifest = {
  name: string;
  source_strategy?: string;
  current_date?: string | null;
  status?: string;
  init_cash?: number | null;
  market?: string | null;
  n_factors?: number;
};
type SessionLogRow = { date: string; n_buy?: number; n_sell?: number; cash?: number; n_positions?: number; nav?: number; ret?: number; cost?: number; turnover?: number };
type CashflowRow = { ts?: string; date?: string; delta?: number; balance_after?: number; note?: string };
type TradeSessionDetail = {
  manifest: TradeSessionManifest;
  state?: { date?: string; cash?: number; positions?: Record<string, number> } | null;
  history?: SessionLogRow[];
  cashflows?: CashflowRow[];
};

function fmtNum(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString();
}
function fmtSigned(v: unknown): string {
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  return (n > 0 ? "+" : "") + n.toLocaleString();
}
function cashflowColumns(t: (k: string) => string) {
  return [
    { key: "date", label: t("dateLabel") },
    { key: "delta", label: t("amount"), render: (r: Record<string, unknown>) => <>{fmtSigned(r.delta)}</> },
    { key: "balance_after", label: t("balance"), render: (r: Record<string, unknown>) => <>{fmtNum(r.balance_after)}</> },
    { key: "note", label: t("note") },
  ];
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

const PNL_MARGIN = { l: 56, r: 48, t: 28, b: 40 };
const fmtMoney = (v: number | null): string => (v === null ? "—" : (v > 0 ? "+" : "") + Math.round(v).toLocaleString());
const fmtPts = (v: number): string => (v > 0 ? "+" : "") + v.toFixed(2);

/** "概览" tab: KPI strip + P&L charts (NAV curve, cumulative return, turnover & fee) for a session. */
function SessionOverview({ detail }: { detail: TradeSessionDetail }) {
  const { t } = useI18n();
  const pnl = useMemo(
    () => computeSessionPnl(detail.history || [], detail.manifest?.init_cash ?? 0, detail.cashflows || []),
    [detail],
  );
  const nPositions = detail.state?.positions ? Object.keys(detail.state.positions).length : 0;
  if (!pnl.hasData) return <p className="empty">{t("pnlNoData")}</p>;
  return (
    <>
      <div className="metric-grid compact">
        <Metric label={t("pnlMoney")} value={fmtMoney(pnl.totals.pnlMoney)} />
        <Metric label={t("cumReturnPts")} value={fmtPts(pnl.totals.cumReturnPts)} />
        <Metric label={t("totalFees")} value={fmtNum(Math.round(pnl.totals.totalFees))} />
        <Metric label={t("navLabel")} value={fmtNum(pnl.totals.latestNav)} />
        <Metric label={t("currentCash")} value={fmtNum(detail.state?.cash)} />
        <Metric label={t("positions")} value={String(nPositions)} />
      </div>
      <h4 className="muted compact">{t("equityCurve")}</h4>
      <Plot
        data={[
          { x: pnl.dates, y: pnl.nav, type: "scatter", mode: "lines", name: t("navLabel"), line: { color: "#2563eb", width: 2 } },
          { x: pnl.dates, y: pnl.cash, type: "scatter", mode: "lines", name: t("currentCash"), line: { color: "#94a3b8", width: 1.5 } },
        ]}
        layout={{ autosize: true, height: chartHeight(), margin: PNL_MARGIN, hovermode: "x unified", legend: { orientation: "h" } }}
        useResizeHandler
        style={{ width: "100%" }}
      />
      <h4 className="muted compact">{t("cumReturnChart")}</h4>
      <Plot
        data={[{ x: pnl.dates, y: pnl.cumReturnPct, type: "scatter", mode: "lines", name: t("cumReturnPts"), line: { color: "#16a34a", width: 2 } }]}
        layout={{
          autosize: true,
          height: 320,
          margin: PNL_MARGIN,
          hovermode: "x unified",
          shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { dash: "dot", color: "#94a3b8" } }],
        }}
        useResizeHandler
        style={{ width: "100%" }}
      />
      <h4 className="muted compact">{t("turnoverFee")}</h4>
      <Plot
        data={[
          { x: pnl.dates, y: pnl.turnover, type: "bar", name: t("turnoverLabel"), marker: { color: "#60a5fa" }, opacity: 0.7 },
          { x: pnl.dates, y: pnl.feeMoney, type: "scatter", mode: "lines", name: t("feeMoney"), line: { color: "#ef4444", width: 1.5 }, yaxis: "y2" },
        ]}
        layout={{
          autosize: true,
          height: 320,
          margin: PNL_MARGIN,
          hovermode: "x unified",
          yaxis: { title: t("turnoverLabel") },
          yaxis2: { title: t("feeMoney"), overlaying: "y", side: "right" },
        }}
        useResizeHandler
        style={{ width: "100%" }}
      />
    </>
  );
}

export function DailyTradePage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const strategies = useAsync(() => api.get<{ strategies: Array<Record<string, unknown>>; names: string[] }>("/api/strategies"), []);
  const sessions = useAsync(() => api.get<TradeSessionManifest[]>("/api/trade-sessions"), []);
  const strategyNames = strategies.data?.names || [];
  const sessionNames = (sessions.data || []).map((s) => s.name);

  // The run mode is driven by a session dropdown: a session -> resume it (strategy + cash fixed by
  // the snapshot); empty -> an ad-hoc one-off run (pick strategy + seed cash).
  const [runSessionName, setRunSessionName] = useState("");
  const [runSession, setRunSession] = useState<TradeSessionDetail | null>(null);
  const runSpecs = useMemo(
    () => (runSessionName ? sessionRunSpecs : withStrategyOptions(oneOffRunSpecs, strategyNames)),
    [runSessionName, strategies.data],
  );
  const params = useJsonInput("{}");
  const runForm = useParamForm(runSpecs, params.raw);
  const [result, setResult] = useState<unknown>(null);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [cashAmount, setCashAmount] = useState("");
  const [cashNote, setCashNote] = useState("");
  const { busy, run } = useAction();

  async function refreshRunSession(name: string) {
    if (!name) { setRunSession(null); return; }
    try {
      setRunSession(await api.get<TradeSessionDetail>(`/api/trade-sessions/${encodeURIComponent(name)}`));
    } catch { setRunSession(null); }
  }
  function selectRunSession(name: string) {
    setRunSessionName(name);
    void refreshRunSession(name);
  }
  function adjustCash(sign: 1 | -1) {
    void run(async () => {
      const amt = Number(cashAmount);
      if (!cashAmount.trim() || Number.isNaN(amt) || amt <= 0) throw new Error(t("invalidAmount"));
      await api.post(`/api/trade-sessions/${encodeURIComponent(runSessionName)}/cash`, { delta: sign * amt, note: cashNote || undefined });
      setCashAmount("");
      setCashNote("");
      await refreshRunSession(runSessionName);
      await sessions.refresh();
    }, sign > 0 ? t("depositDone") : t("withdrawDone"));
  }

  // Trade-session create form + detail view.
  const [sessName, setSessName] = useState("");
  const [sessStrategy, setSessStrategy] = useState("");
  const [sessInitCash, setSessInitCash] = useState("1000000");
  const [sessOverwrite, setSessOverwrite] = useState(false);
  const [detail, setDetail] = useState<TradeSessionDetail | null>(null);
  const [detailTab, setDetailTab] = useState("overview");

  function createSession() {
    void run(async () => {
      const payload: Record<string, unknown> = { name: sessName || undefined, strategy_name: sessStrategy, overwrite: sessOverwrite };
      const cash = Number(sessInitCash);
      if (sessInitCash.trim() && !Number.isNaN(cash)) payload.init_cash = cash;
      await api.post("/api/trade-sessions", payload);
      setSessName("");
      await sessions.refresh();
    }, t("sessionCreated"));
  }

  function viewSession(name: string) {
    void run(async () => {
      setDetail(await api.get<TradeSessionDetail>(`/api/trade-sessions/${encodeURIComponent(name)}`));
      setDetailTab("overview");
    });
  }

  async function removeSession(name: string) {
    if (!(await confirm({ message: `${t("delete")} ${name}?`, danger: true }))) return;
    void run(async () => {
      await api.delete(`/api/trade-sessions/${encodeURIComponent(name)}`);
      if (detail?.manifest?.name === name) setDetail(null);
      if (runSessionName === name) {
        setRunSessionName("");
        setRunSession(null);
      }
      await sessions.refresh();
    }, t("sessionDeleted"));
  }

  // Poll the running daily-trade job for live status; on completion fetch its result. Mirrors
  // the MarketPage data-job pattern so the page shows a run-status card instead of nothing.
  useEffect(() => {
    if (!activeJob?.job_id) return;
    let alive = true;
    const poll = async () => {
      try {
        const p = await api.get<JobProgress>(`/api/jobs/${activeJob.job_id}/progress`);
        if (!alive) return;
        setProgress(p);
        if (p.status && ["succeeded", "failed", "cancelled", "lost"].includes(p.status)) {
          if (p.status === "succeeded") {
            try { setResult(await api.get(`/api/jobs/${activeJob.job_id}/result`)); } catch { /* result may be empty */ }
            if (runSessionName) void refreshRunSession(runSessionName);
            void sessions.refresh();
          }
          setActiveJob(null);
        }
      } catch (err) {
        if (alive) setMessage(err instanceof Error ? err.message : String(err));
      }
    };
    void poll();
    const id = window.setInterval(poll, 2000);
    return () => { alive = false; window.clearInterval(id); };
  }, [activeJob?.job_id]);

  function runDailyTrade() {
    void run(async () => {
      const payload = runForm.parse();
      if (runSessionName) payload.session = runSessionName;
      const job = await api.post<Job>("/api/daily-trade", payload);
      setResult(null);
      setActiveJob(job);
      setProgress(job.progress || { job_id: job.job_id, status: job.status, percent: 0, stage: "queued", message: "queued" });
      setMessage(`${t("started")}: ${job.job_id}`);
    }, t("started"));
  }

  return (
    <>
      <PageTitle title={t("daily")} subtitle={t("dailySubtitle")} />
      <section className="panel">
        <div className="panel-head compact">
          <h2>{t("tradeSessions")}</h2>
          <PanelHelp label={t("tradeSessions")} title={t("tradeSessions")} intro={t("tradeSessionsSubtitle")} items={[]} />
          <RefreshButton onClick={() => void sessions.refresh()} />
        </div>
        {sessions.error ? <Alert tone="error">{sessions.error}</Alert> : null}
        <div className="dynamic-form cols-2">
          <label>
            {t("sessionName")}
            <input value={sessName} onChange={(e) => setSessName(e.target.value)} placeholder={t("sessionNamePlaceholder")} />
          </label>
          <label>
            {t("sourceStrategy")}
            <select value={sessStrategy} onChange={(e) => setSessStrategy(e.target.value)}>
              <option value="">—</option>
              {strategyNames.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label>
            {t("initCash")}
            <input type="number" value={sessInitCash} onChange={(e) => setSessInitCash(e.target.value)} />
          </label>
          <label className="inline-check dynamic-check">
            <input type="checkbox" checked={sessOverwrite} onChange={(e) => setSessOverwrite(e.target.checked)} />
            <span>{t("overwriteSession")}</span>
          </label>
        </div>
        <div className="toolbar below">
          <button className="button primary" disabled={busy || !sessStrategy} onClick={() => createSession()}>
            {busy ? <Spinner /> : null}{t("createSession")}
          </button>
        </div>
        <DataTable
          rows={(sessions.data || []) as unknown as Record<string, unknown>[]}
          empty={t("noSessions")}
          loading={sessions.loading}
          columns={[
            { key: "name", label: t("sessionName") },
            { key: "source_strategy", label: t("sourceStrategy") },
            { key: "current_date", label: t("currentDate"), render: (row) => <>{(row.current_date as string) || "—"}</> },
            { key: "status", label: t("sessionStatus"), render: (row) => <StatusPill status={row.status as string} /> },
            {
              key: "name",
              label: "",
              render: (row) => (
                <div className="row-actions">
                  <button className="button small" onClick={() => viewSession(row.name as string)}>{t("viewSession")}</button>
                  <button className="button small danger" disabled={busy} onClick={() => removeSession(row.name as string)}>{t("deleteSession")}</button>
                </div>
              )
            }
          ]}
        />
        {detail ? (
          <section className="panel inset">
            <div className="panel-head compact">
              <h3>{detail.manifest?.name} — {t("sessionHistory")}</h3>
              <button className="button ghost small" onClick={() => setDetail(null)}>×</button>
            </div>
            {detail.state ? (
              <p className="muted">
                {t("currentDate")}: {detail.state.date || "—"} · {t("initCash")}: {detail.state.cash ?? "—"} · {t("positions")}: {detail.state.positions ? Object.keys(detail.state.positions).length : 0}
              </p>
            ) : null}
            <Tabs
              active={detailTab}
              onChange={setDetailTab}
              tabs={[
                { key: "overview", label: t("tabOverview") },
                { key: "history", label: t("sessionHistory") },
                { key: "cashflows", label: t("cashflows") },
              ]}
            />
            {detailTab === "overview" ? <SessionOverview detail={detail} /> : null}
            {detailTab === "history" ? (
              <DataTable
                rows={(detail.history || []) as unknown as Record<string, unknown>[]}
                empty={t("empty")}
                columns={[
                  { key: "date", label: t("dateLabel") },
                  { key: "n_buy", label: t("buys") },
                  { key: "n_sell", label: t("sells") },
                  { key: "cash", label: t("initCash") },
                  { key: "n_positions", label: t("positions") }
                ]}
              />
            ) : null}
            {detailTab === "cashflows" ? (
              <DataTable rows={(detail.cashflows || []) as unknown as Record<string, unknown>[]} empty={t("empty")} columns={cashflowColumns(t)} />
            ) : null}
          </section>
        ) : null}
      </section>
      <div className="grid side">
        <section className="panel">
          <div className="panel-head compact">
            <h2>{t("dailyTradeParams")}</h2>
            <PanelHelp
              label={t("dailyTradeHelp")}
              title={t("dailyTradeHelpTitle")}
              intro={t("dailyTradeHelpIntro")}
              items={[
                t("dailyTradeHelpStrategy"),
                t("dailyTradeHelpDate"),
                t("dailyTradeHelpState"),
                t("dailyTradeHelpAssets"),
                t("dailyTradeHelpRefresh"),
                t("dailyTradeHelpNotify"),
                t("dailyTradeHelpAdvanced")
              ]}
              footer={t("dailyTradeHelpFlow")}
            />
          </div>
          {strategies.error ? <Alert tone="error">{strategies.error}</Alert> : null}

          {/* Run mode = session dropdown: a session resumes its rolling state; empty = one-off. */}
          <div className="dynamic-form cols-1">
            <label>
              {t("runMode")}
              <select value={runSessionName} onChange={(e) => selectRunSession(e.target.value)}>
                <option value="">{t("oneOffRun")}</option>
                {sessionNames.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
          </div>

          {runSessionName ? (
            <div className="panel inset">
              <p className="muted compact">
                {t("sourceStrategy")}: {runSession?.manifest?.source_strategy || "—"} · {t("currentDate")}: {runSession?.state?.date || runSession?.manifest?.current_date || "—"} · {t("currentCash")}: {fmtNum(runSession?.state?.cash ?? runSession?.manifest?.init_cash)} · {t("positions")}: {runSession?.state?.positions ? Object.keys(runSession.state.positions).length : 0}
              </p>
              <div className="panel-head compact"><h3>{t("adjustCash")}</h3></div>
              <div className="toolbar">
                <input type="number" placeholder={t("amount")} value={cashAmount} onChange={(e) => setCashAmount(e.target.value)} />
                <input placeholder={t("note")} value={cashNote} onChange={(e) => setCashNote(e.target.value)} />
                <button className="button small" disabled={busy || !cashAmount} onClick={() => adjustCash(1)}>{t("depositIn")}</button>
                <button className="button small danger" disabled={busy || !cashAmount} onClick={() => adjustCash(-1)}>{t("withdrawOut")}</button>
              </div>
              {(runSession?.cashflows || []).length ? (
                <>
                  <h4 className="muted compact">{t("cashflows")}</h4>
                  <DataTable rows={(runSession?.cashflows || []) as unknown as Record<string, unknown>[]} empty={t("empty")} columns={cashflowColumns(t)} />
                </>
              ) : null}
            </div>
          ) : null}

          <DynamicForm specs={runSpecs} values={runForm.values} onChange={runForm.setValue} errors={runForm.errors} />
          <details>
            <summary>{t("advancedParams")}</summary>
            <JsonTextArea value={params.raw} onChange={params.setRaw} rows={7} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => runDailyTrade()}>{busy ? <Spinner /> : null}{runSessionName ? t("runSession") : t("run")}</button>
          {message ? <p className="muted">{message}</p> : null}
        </section>
        <aside className="panel">
          <h2>{t("runStatus")}</h2>
          {progress ? (
            <div className="progress-card">
              <div className="panel-head compact">
                <h3>{t("currentDailyJob")}</h3>
                <StatusPill status={progress.status || activeJob?.status} />
              </div>
              <ProgressBar percent={progress.percent} label={progress.message || progress.stage} active={progress.status === "running"} />
              <code>{progress.job_id || activeJob?.job_id}</code>
            </div>
          ) : null}
          <h3>{t("runResult")}</h3>
          {result ? <pre className="json">{JSON.stringify(result, null, 2)}</pre> : <div className="empty">{t("empty")}</div>}
        </aside>
      </div>
      <JobsPanel compact />
    </>
  );
}

export function SchedulerPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const schedules = useAsync(() => api.get<Schedule[]>("/api/schedules"), []);
  const strategies = useAsync(() => api.get<{ names: string[] }>("/api/strategies"), []);
  const instrumentSets = useAsync(() => api.get<{ sets: string[] }>("/api/data/instrument-sets"), []);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("data");
  const [time, setTime] = useState("18:00");
  const [enabled, setEnabled] = useState(true);
  const [notify, setNotify] = useState(false);
  const scheduleAdvanced = useJsonInput("{}");
  const scheduleFields = useMemo(
    () => withInstrumentSetOptions(scheduleSpecsFor(kind, strategies.data?.names || []), instrumentSets.data?.sets || []),
    [kind, strategies.data, instrumentSets.data],
  );
  const scheduleForm = useParamForm(scheduleFields, scheduleAdvanced.raw);

  function changeKind(next: string) {
    setKind(next);
    scheduleAdvanced.setRaw("{}");
  }
  const daemon = useAsync(() => api.get<Record<string, unknown>>("/api/schedules/daemon"), []);
  const { busy, run } = useAction();

  function create() {
    void run(async () => {
      const kwargs = scheduleForm.parse();
      if (notify) kwargs.notify = true;
      await api.post("/api/schedules", {
        name: name || `${kind}-${time}`,
        kind,
        time,
        enabled,
        kwargs
      });
      setName("");
      await schedules.refresh();
    }, t("save"));
  }

  async function deleteSchedule(scheduleId: string) {
    const target = scheduleId.trim();
    if (!target || !(await confirm({ message: `${t("delete")} ${target}?`, danger: true }))) return;
    void run(async () => {
      await api.delete(`/api/schedules/${encodeURIComponent(target)}`);
      await schedules.refresh();
    }, t("delete"));
  }

  return (
    <>
      <PageTitle title={t("scheduler")} subtitle={t("schedulerSubtitle")} />
      <section className="panel">
        <div className="panel-head">
          <div className="panel-title-inline">
            <h2>{t("daemon")}</h2>
            <InfoDot tip={daemon.data?.running ? t("daemonTipOn") : t("daemonTipOff")} />
          </div>
          <StatusPill status={daemon.data?.running ? "running" : "stopped"} />
        </div>
        <div className="row-actions left">
          <button className="button" disabled={busy} onClick={() => void run(async () => { await api.post("/api/schedules/daemon/start"); await daemon.refresh(); }, t("daemonOn"))}>{t("start")}</button>
          <button className="button danger" disabled={busy} onClick={async () => { if (!(await confirm({ message: t("daemonStopConfirm"), danger: true }))) return; void run(async () => { await api.post("/api/schedules/daemon/stop"); await daemon.refresh(); }, t("daemonOff")); }}>{t("stop")}</button>
        </div>
      </section>
      <div className="grid side">
        <section className="panel">
          <h2>{t("schedules")}</h2>
          <DataTable
            rows={(schedules.data || []) as unknown as Record<string, unknown>[]}
            loading={schedules.loading}
            columns={[
              { key: "name", label: t("colName") },
              { key: "kind", label: t("colKind") },
              { key: "time", label: t("colTime") },
              { key: "enabled", label: t("colEnabled"), align: "center", render: (row) => <input className="row-check" type="checkbox" checked={Boolean(row.enabled)} readOnly aria-label={t("colEnabled")} /> },
              { key: "last_run_at", label: t("scheduleLastRun"), render: (row) => <span title={String(row.last_job_id || "")}>{formatTimestamp(row.last_run_at)}</span> },
              { key: "next_run_at", label: t("scheduleNextRun"), render: (row) => <>{row.enabled ? formatTimestamp(row.next_run_at) : "—"}</> },
              {
                key: "schedule_id",
                label: t("colActions"),
                align: "right",
                render: (row) => (
                  <div className="row-actions">
                    <button className="button small" disabled={busy} onClick={() => void run(async () => { await api.post(`/api/schedules/${row.schedule_id}/run`); await schedules.refresh(); }, t("started"))}>{t("run")}</button>
                    <button className="button small danger" disabled={busy} onClick={() => deleteSchedule(String(row.schedule_id))}>{t("delete")}</button>
                  </div>
                )
              }
            ]}
          />
        </section>
        <aside className="panel">
          <div className="panel-head compact">
            <h2>{t("createSchedule")}</h2>
            <PanelHelp
              label={t("schedulerCreateHelp")}
              title={t("schedulerCreateHelpTitle")}
              intro={t("schedulerCreateHelpIntro")}
              items={[
                t("schedulerCreateHelpKind"),
                t("schedulerCreateHelpTime"),
                t("schedulerCreateHelpEnabled"),
                t("schedulerCreateHelpNotify"),
                t("schedulerCreateHelpAdvanced")
              ]}
              footer={t("schedulerCreateHelpFlow")}
            />
          </div>
          <label>
            {t("nameLabel")}
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={`${kind}-${time}`} />
          </label>
          <div className="form-grid">
            <label>
              {t("typeLabel")}
              <select value={kind} onChange={(e) => changeKind(e.target.value)}>
                <option value="data">{t("kindData")}</option>
                <option value="mine">{t("kindMine")}</option>
                <option value="mine_aff">{t("kindAff")}</option>
                <option value="mine_gp">{t("kindGp")}</option>
                <option value="mine_rl">AlphaForge RL</option>
                <option value="factor_backtest">{t("factorBacktest")}</option>
                <option value="strategy_backtest">{t("strategyBacktest")}</option>
                <option value="daily_signals">{t("kindDaily")}</option>
              </select>
            </label>
            <label>
              {t("timeLabel")}
              <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
            </label>
          </div>
          <label className="inline-check">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            {t("enabledLabel")}
          </label>
          <label className="inline-check">
            <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
            {t("notifyOnComplete")}
          </label>
          <DynamicForm specs={scheduleFields} values={scheduleForm.values} onChange={scheduleForm.setValue} errors={scheduleForm.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={scheduleAdvanced.raw} onChange={scheduleAdvanced.setRaw} rows={5} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => create()}>{busy ? <Spinner /> : null}{t("save")}</button>
        </aside>
      </div>
    </>
  );
}

export function NotificationsPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const cfg = useAsync(() => api.get<Record<string, unknown>>("/api/notify"), []);
  const commands = useAsync(() => api.get<NotifyCommandsStatus>("/api/notify/commands/status"), []);
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [commandText, setCommandText] = useState("/jobs");
  const [commandResult, setCommandResult] = useState<Record<string, unknown> | null>(null);
  const [daemonChannel, setDaemonChannel] = useState("telegram");
  const [pairCode, setPairCode] = useState<{ code: string; expires_at: string } | null>(null);
  const toast = useToast();
  const { busy, run } = useAction();
  React.useEffect(() => {
    if (cfg.data) setConfig((cfg.data.config || {}) as Record<string, unknown>);
  }, [cfg.data]);

  const fields = (cfg.data?.fields || {}) as Record<string, Array<string | [string, string]>>;
  const maskedSecret = String(cfg.data?.masked_secret || "********");

  function fieldName(field: string | [string, string]) {
    return Array.isArray(field) ? field[0] : field;
  }

  function fieldKind(field: string | [string, string]) {
    return Array.isArray(field) ? field[1] : "str";
  }

  function updateChannel(channel: string, field: string, value: unknown) {
    const next = { ...config };
    const channelConfig = { ...((next[channel] as Record<string, unknown>) || {}) };
    channelConfig[field] = value;
    next[channel] = channelConfig;
    setConfig(next);
  }

  function updateOption(key: string, value: unknown) {
    const next = { ...config };
    next.options = { ...((next.options as Record<string, unknown>) || {}), [key]: value };
    setConfig(next);
  }

  function saveNotify() {
    void run(async () => {
      await api.patch("/api/notify", { config });
      await cfg.refresh();
    }, t("notifySaved"));
  }

  function testChannel(channel?: string) {
    void run(async () => {
      const r = await api.post(`/api/notify/test${channel ? qs({ channel }) : ""}`);
      toast.info(JSON.stringify(r));
    });
  }

  function dispatchCommand(planOnly = false) {
    void run(async () => {
      const path = planOnly ? "/api/notify/commands/plan" : "/api/notify/commands/dispatch";
      const r = await api.post<Record<string, unknown>>(path, {
        text: commandText,
        channel: "portal",
        user_id: "portal",
        chat_id: "portal",
        enforce_auth: false
      });
      setCommandResult(r);
      await commands.refresh();
    });
  }

  function startCommands() {
    void run(async () => {
      await api.post("/api/notify/commands/start", { channel: daemonChannel });
      await commands.refresh();
    }, t("commandReceiverStarted"));
  }

  async function stopCommands() {
    if (!(await confirm({ message: t("cmdStopConfirm"), danger: true }))) return;
    void run(async () => {
      await api.post("/api/notify/commands/stop");
      await commands.refresh();
    }, t("commandReceiverStopped"));
  }

  function generatePairCode() {
    void run(async () => {
      const channel = daemonChannel === "feishu" ? "feishu" : "telegram";
      const r = await api.post<{ code: string; expires_at: string }>("/api/notify/commands/pair-code", { channel });
      setPairCode({ code: r.code, expires_at: r.expires_at });
    });
  }

  function registerMenu() {
    void run(async () => {
      await api.post("/api/notify/commands/register-menu");
    }, t("menuRegistered"));
  }

  return (
    <>
      <PageTitle title={t("notify")} subtitle={t("notifySubtitle")} />
      <div className="grid two">
      <section className="panel">
          <div className="panel-head">
            <div>
              <h2>{t("notifyChannelsTitle")}</h2>
              <p className="muted">{t("notifyChannelsSubtitle")}</p>
            </div>
            <PanelHelp
              label={t("notifyChannelsHelp")}
              title={t("notifyChannelsHelpTitle")}
              intro={t("notifyChannelsHelpIntro")}
              items={[
                t("notifyChannelsHelpCredentials"),
                t("notifyChannelsHelpAllJobs"),
                t("notifyChannelsHelpFileBrowse"),
                t("notifyChannelsHelpSecrets")
              ]}
              footer={t("notifyChannelsHelpFlow")}
            />
          </div>
          {cfg.error ? <Alert tone="error">{cfg.error}</Alert> : null}
          <p className="muted">{t("credentialsPath")}：{String(cfg.data?.credentials_path || "")}</p>
          <p className="muted">{t("configuredChannels")}：{((cfg.data?.configured_channels as string[]) || []).join(", ") || t("none")}</p>
          <label className="inline-check">
            <input
              type="checkbox"
              checked={Boolean(((config.options as Record<string, unknown>) || {}).notify_on_all_jobs)}
              onChange={(e) => updateOption("notify_on_all_jobs", e.target.checked)}
            />
            {t("notifyAllJobs")}
          </label>
          <details>
            <summary>{t("fileBrowseTitle")}</summary>
            <p className="muted small-text">{t("fileBrowseHint")}</p>
            <div className="form-grid">
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={Boolean(((config.options as Record<string, unknown>) || {}).file_browse_enabled)}
                  onChange={(e) => updateOption("file_browse_enabled", e.target.checked)}
                />
                {t("fileBrowseEnabled")}
              </label>
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={Boolean(((config.options as Record<string, unknown>) || {}).file_browse_allow_download)}
                  onChange={(e) => updateOption("file_browse_allow_download", e.target.checked)}
                />
                {t("fileBrowseAllowDownload")}
              </label>
              <label>
                {t("fileBrowseRoot")}
                <input
                  type="text"
                  placeholder={t("fileBrowseRootPh")}
                  value={String(((config.options as Record<string, unknown>) || {}).file_browse_root || "")}
                  onChange={(e) => updateOption("file_browse_root", e.target.value)}
                />
              </label>
              <label>
                {t("fileBrowseMaxKb")}
                <input
                  type="number"
                  value={String(((config.options as Record<string, unknown>) || {}).file_browse_max_kb ?? 256)}
                  onChange={(e) => updateOption("file_browse_max_kb", e.target.value ? Number(e.target.value) : 256)}
                />
              </label>
            </div>
          </details>
          {Object.entries(fields).map(([channel, names]) => (
            <details key={channel}>
              <summary>{channel}</summary>
              <div className="form-grid">
                {names.map((field) => {
                  const name = fieldName(field);
                  const kind = fieldKind(field);
                  const value = ((config[channel] as Record<string, unknown>) || {})[name];
                  if (kind === "bool") {
                    return (
                      <label className="inline-check" key={name}>
                        <input type="checkbox" checked={Boolean(value)} onChange={(e) => updateChannel(channel, name, e.target.checked)} />
                        {name}
                      </label>
                    );
                  }
                  return (
                    <label key={name}>
                      {name}
                      <input
                        type={kind === "secret" ? "password" : kind === "int" ? "number" : "text"}
                        placeholder={kind === "secret" && value === maskedSecret ? t("configuredKeepPlaceholder") : undefined}
                        value={kind === "secret" && value === maskedSecret ? "" : Array.isArray(value) ? value.join(",") : String(value || "")}
                        onChange={(e) => {
                          const rawValue = e.target.value;
                          if (kind === "int") updateChannel(channel, name, rawValue ? Number(rawValue) : "");
                          else if (kind === "list") updateChannel(channel, name, rawValue.split(",").map((item) => item.trim()).filter(Boolean));
                          else updateChannel(channel, name, rawValue);
                        }}
                      />
                    </label>
                  );
                })}
              </div>
              <button className="button small" disabled={busy} onClick={() => testChannel(channel)}>{t("test")} {channel}</button>
            </details>
        ))}
        <div className="row-actions left">
          <button className="button primary" disabled={busy} onClick={() => saveNotify()}>{busy ? <Spinner /> : null}{t("save")}</button>
          <button className="button" disabled={busy} onClick={() => testChannel()}>{t("testAll")}</button>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t("commandReceiverTitle")}</h2>
            <p className="muted">{t("commandReceiverSubtitle")}</p>
          </div>
          <div className="row-actions">
            <PanelHelp
              label={t("commandReceiverHelp")}
              title={t("commandReceiverHelpTitle")}
              intro={t("commandReceiverHelpIntro")}
              items={[
                t("commandReceiverHelpChannel"),
                t("commandReceiverHelpPairing"),
                t("commandReceiverHelpAllowlist"),
                t("commandReceiverHelpMenu")
              ]}
              footer={t("commandReceiverHelpFlow")}
            />
            <StatusPill status={commands.data?.daemon?.running ? "running" : "stopped"} />
          </div>
        </div>
        {commands.error ? <Alert tone="error">{commands.error}</Alert> : null}
        <div className="metric-grid compact">
          <div className="metric"><span>{t("status")}</span><strong>{commands.data?.daemon?.running ? t("daemonOn") : t("daemonOff")}</strong></div>
          <div className="metric"><span>{t("pidLabel")}</span><strong>{String(commands.data?.daemon?.pid || "-")}</strong></div>
          <div className="metric"><span>{t("commandChannel")}</span><strong>{String(commands.data?.daemon?.channel || "-")}</strong></div>
        </div>
        <div className="form-grid">
          <label>
            {t("commandChannel")}
            <select value={daemonChannel} onChange={(e) => setDaemonChannel(e.target.value)}>
              <option value="telegram">Telegram</option>
              <option value="all">Telegram + Feishu</option>
              <option value="feishu">Feishu callback only</option>
            </select>
          </label>
          <label>
            {t("savedFileLabel")}
            <input readOnly value={String(commands.data?.daemon?.root || "")} />
          </label>
        </div>
        <div className="row-actions left">
          <button className="button primary" disabled={busy || Boolean(commands.data?.daemon?.running)} onClick={() => startCommands()}>{t("startCommandReceiver")}</button>
          <button className="button" disabled={busy || !commands.data?.daemon?.running} onClick={() => stopCommands()}>{t("stopCommandReceiver")}</button>
          <RefreshButton className="button ghost" onClick={() => commands.refresh()} />
        </div>
        <div className="panel-head">
          <div>
            <h3>{t("pairingTitle")}</h3>
            <p className="muted">{t("pairingSubtitle")}</p>
          </div>
        </div>
        <div className="row-actions left">
          <button className="button" disabled={busy} onClick={() => generatePairCode()}>{t("generatePairCode")}</button>
          <button className="button ghost" disabled={busy} onClick={() => registerMenu()}>{t("registerMenu")}</button>
        </div>
        {pairCode ? (
          <Alert tone="info">
            <strong className="mono">{pairCode.code}</strong> — {t("pairingInstruction").replace("{code}", pairCode.code)}
            <span className="muted small-text"> （{t("expiresAt")}: {pairCode.expires_at}）</span>
          </Alert>
        ) : null}
      </section>
      </div>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t("commandTestTitle")}</h2>
            <p className="muted">{t("commandTestSubtitle")}</p>
          </div>
          <PanelHelp
            label={t("commandTestHelp")}
            title={t("commandTestHelpTitle")}
            intro={t("commandTestHelpIntro")}
            items={[
              t("commandTestHelpRun"),
              t("commandTestHelpPlan"),
              t("commandTestHelpAuth")
            ]}
            footer={t("commandTestHelpFlow")}
          />
        </div>
        <textarea className="mono" rows={4} value={commandText} onChange={(e) => setCommandText(e.target.value)} />
        <div className="row-actions left">
          <button className="button primary" disabled={busy || !commandText.trim()} onClick={() => dispatchCommand(false)}>{t("runCommandTest")}</button>
          <button className="button" disabled={busy || !commandText.trim()} onClick={() => dispatchCommand(true)}>{t("planCommandTest")}</button>
        </div>
        {commandResult ? <pre className="result-box">{JSON.stringify(commandResult, null, 2)}</pre> : null}
      </section>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t("commandEventsTitle")}</h2>
            <p className="muted">{t("commandEventsSubtitle")}</p>
          </div>
          <RefreshButton className="button ghost small" onClick={() => commands.refresh()} />
        </div>
        <DataTable
          rows={commands.data?.events || []}
          loading={commands.loading}
          empty={t("empty")}
          columns={[
            { key: "created_at", label: t("dateLabel") },
            { key: "channel", label: t("commandChannel") },
            { key: "user_id", label: t("colUser") },
            { key: "text", label: t("commandText"), ellipsis: true, render: (row) => <span className="mono small-text">{String(row.text || "")}</span> },
            { key: "ok", label: t("status"), render: (row) => <StatusPill status={row.ok ? "succeeded" : "failed"} /> },
            { key: "reply", label: t("commandReply"), render: (row) => <span className="small-text">{String(row.reply || row.error || "")}</span> }
          ]}
        />
      </section>
    </>
  );
}

export function AdvancedPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const portalSettings = useAsync(() => api.get<PortalSettings>("/api/portal/settings"), []);
  const envSettings = useAsync(() => api.get<PortalEnvSettings>("/api/portal/env"), []);
  const [portalHost, setPortalHost] = useState("127.0.0.1");
  const [portalPort, setPortalPort] = useState("19901");
  const [portalTz, setPortalTz] = useState("Asia/Shanghai");
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const modules = useAsync(() => api.get<Record<string, { commands: Array<Record<string, string>> }>>("/api/modules"), []);
  const [runModule, setRunModule] = useState("portal");
  const [runCommand, setRunCommand] = useState("scheduler");
  const runKwargs = useJsonInput(JSON.stringify({ interval: 30 }, null, 2));
  const runRaw = useJsonInput(JSON.stringify({ module: "portal", command: "scheduler", kwargs: { interval: 30 } }, null, 2));
  const [runRawError, setRunRawError] = useState<string | null>(null);
  const [result, setResult] = useState<unknown>(null);
  const [restartMessage, setRestartMessage] = useState<string | null>(null);
  const [logDir, setLogDir] = useState("");
  const [logCleanupResult, setLogCleanupResult] = useState<LogCleanupResult | null>(null);
  const { busy, run: runAction } = useAction();
  const { busy: savingPortal, run: savePortal } = useAction();
  const { busy: savingEnv, run: saveEnv } = useAction();
  const { busy: restartingPortal, run: restartPortal } = useAction();
  const { busy: cleaningLogs, run: runLogCleanup } = useAction();
  const moduleNames = useMemo(() => Object.keys(modules.data || {}).sort(), [modules.data]);
  const commandNames = useMemo(
    () => ((modules.data?.[runModule]?.commands || []).map((cmd) => String(cmd.name))),
    [modules.data, runModule],
  );
  const hostOptions = useMemo(
    () => (portalSettings.data?.host_options || [
      { value: "127.0.0.1", label: "127.0.0.1" },
      { value: "0.0.0.0", label: "0.0.0.0" },
    ]).map((option) => ({
      value: option.value,
      label:
        option.value === "127.0.0.1"
          ? t("hostLocalOnly")
          : option.value === "0.0.0.0"
            ? t("hostLanAll")
            : option.label,
    })),
    [portalSettings.data, t],
  );

  const tzOptions = useMemo(() => {
    const opts = portalSettings.data?.timezone_options || ["Asia/Shanghai", "UTC"];
    return opts.includes(portalTz) ? opts : [portalTz, ...opts];
  }, [portalSettings.data, portalTz]);

  useEffect(() => {
    if (!portalSettings.data) return;
    setPortalHost(portalSettings.data.settings.host);
    setPortalPort(String(portalSettings.data.settings.port));
    setPortalTz(portalSettings.data.settings.timezone);
  }, [portalSettings.data]);

  useEffect(() => {
    if (!envSettings.data) return;
    const next: Record<string, string> = {};
    envSettings.data.fields.forEach((field) => {
      const value = envSettings.data?.values[field.key] || "";
      next[field.key] = field.secret && value === envSettings.data?.masked_secret ? "" : value;
    });
    setEnvValues(next);
  }, [envSettings.data]);

  const envGroups = useMemo(() => {
    const groups: Record<string, PortalEnvField[]> = {};
    (envSettings.data?.fields || []).forEach((field) => {
      groups[field.group] = [...(groups[field.group] || []), field];
    });
    return groups;
  }, [envSettings.data]);

  useEffect(() => {
    if (!moduleNames.length) return;
    if (!moduleNames.includes(runModule)) {
      setRunModule(moduleNames[0]);
    }
  }, [moduleNames, runModule]);

  useEffect(() => {
    if (!commandNames.length) {
      if (runCommand) setRunCommand("");
      return;
    }
    if (!commandNames.includes(runCommand)) {
      setRunCommand(commandNames[0]);
    }
  }, [commandNames, runCommand]);

  useEffect(() => {
    let kwargs: Record<string, unknown> = {};
    try {
      kwargs = runKwargs.parse();
    } catch {
      kwargs = {};
    }
    runRaw.setRaw(JSON.stringify({ module: runModule, command: runCommand, kwargs }, null, 2));
  }, [runModule, runCommand, runKwargs.raw]);

  function applyRawToStructured() {
    try {
      const parsed = runRaw.parse();
      if (typeof parsed.module === "string") setRunModule(parsed.module);
      if (typeof parsed.command === "string") setRunCommand(parsed.command);
      if (parsed.kwargs && typeof parsed.kwargs === "object" && !Array.isArray(parsed.kwargs)) {
        runKwargs.setRaw(JSON.stringify(parsed.kwargs, null, 2));
      }
      setRunRawError(null);
    } catch (err) {
      setRunRawError(err instanceof Error ? err.message : String(err));
    }
  }

  function parseRunPayload(): { module: string; command: string; kwargs: Record<string, unknown> } {
    let fallbackKwargs: Record<string, unknown> = {};
    try {
      fallbackKwargs = runKwargs.parse();
    } catch {
      fallbackKwargs = {};
    }
    const fallback = {
      module: runModule,
      command: runCommand,
      kwargs: fallbackKwargs,
    };
    try {
      const parsed = runRaw.parse();
      if (typeof parsed.module !== "string" || typeof parsed.command !== "string") {
        throw new Error(t("runPayloadInvalid"));
      }
      const kwargs = parsed.kwargs;
      if (kwargs !== undefined && (kwargs === null || Array.isArray(kwargs) || typeof kwargs !== "object")) {
        throw new Error(t("runPayloadInvalid"));
      }
      setRunRawError(null);
      return {
        module: parsed.module,
        command: parsed.command,
        kwargs: (kwargs as Record<string, unknown> | undefined) || {},
      };
    } catch (err) {
      setRunRawError(err instanceof Error ? err.message : String(err));
      return fallback;
    }
  }

  return (
    <>
      <PageTitle title={t("advanced")} subtitle={t("advancedSubtitle")} />
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t("portalSettingsTitle")}</h2>
            <p className="muted no-margin">{t("portalSettingsSubtitle")}</p>
          </div>
          <PanelHelp
            label={t("portalSettingsHelp")}
            title={t("portalSettingsHelpTitle")}
            intro={t("portalSettingsHelpIntro")}
            items={[
              t("portalSettingsHelpHost"),
              t("portalSettingsHelpPort"),
              t("portalSettingsHelpTimezone"),
              t("portalSettingsHelpRestart")
            ]}
            footer={t("portalSettingsHelpFlow")}
          />
        </div>
        {portalSettings.error ? <Alert tone="error">{portalSettings.error}</Alert> : null}
        {portalSettings.data?.restart_required ? (
          <Alert>{t("portalSettingsRestartRequired")}</Alert>
        ) : null}
        {restartMessage ? <Alert tone="success">{restartMessage}</Alert> : null}
        <div className="dynamic-form cols-2">
          <label>
            {t("bindHostLabel")}
            <select value={portalHost} onChange={(e) => setPortalHost(e.target.value)}>
              {hostOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <small>{t("bindHostHelp")}</small>
          </label>
          <label>
            {t("portLabel")}
            <input type="number" min={1} max={65535} value={portalPort} onChange={(e) => setPortalPort(e.target.value)} />
            <small>{t("portHelp")}</small>
          </label>
          <label>
            {t("timezoneLabel")}
            <select value={portalTz} onChange={(e) => setPortalTz(e.target.value)}>
              {tzOptions.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
            <small>{t("timezoneHelp")}</small>
          </label>
        </div>
        <div className="settings-summary">
          <span>{t("currentAddressLabel")}: {portalSettings.data?.current.host || window.location.hostname}:{portalSettings.data?.current.port || window.location.port || "80"}</span>
          <span>{t("pidLabel")}: {portalSettings.data?.runtime?.pid || "-"}</span>
          <span>{t("savedFileLabel")}: {portalSettings.data?.config_path || "-"}</span>
        </div>
        <div className="row-actions left">
          <button
            className="button primary"
            disabled={savingPortal}
            onClick={() => void savePortal(async () => {
              const next = await api.patch<PortalSettings>("/api/portal/settings", { host: portalHost, port: Number(portalPort), timezone: portalTz });
              portalSettings.setData?.(next);
            }, t("portalSettingsSaved"))}
          >
            {savingPortal ? <Spinner /> : null}{t("savePortalSettings")}
          </button>
          <button
            className="button"
            disabled={restartingPortal}
            onClick={async () => {
              if (!(await confirm({ message: t("restartPortalConfirm"), danger: true }))) return;
              void restartPortal(async () => {
                await api.post("/api/portal/restart");
                setRestartMessage(t("restartPortalRequestedMessage"));
              }, t("restartPortalRequestedToast"));
            }}
          >
            {restartingPortal ? <Spinner /> : null}{t("restartPortalButton")}
          </button>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t("envSettingsTitle")}</h2>
            <p className="muted no-margin">{t("envSettingsSubtitle")}</p>
          </div>
          <PanelHelp
            label={t("envSettingsHelp")}
            title={t("envSettingsHelpTitle")}
            intro={t("envSettingsHelpIntro")}
            items={[
              t("envSettingsHelpPriority"),
              t("envSettingsHelpSecrets"),
              t("envSettingsHelpRestart"),
              t("envSettingsHelpCurrent")
            ]}
            footer={t("envSettingsHelpFlow")}
          />
        </div>
        {envSettings.error ? <Alert tone="error">{envSettings.error}</Alert> : null}
        {envSettings.data?.restart_required ? (
          <Alert>{t("envSettingsRestartRequired")}</Alert>
        ) : null}
        <div className="settings-summary">
          <span>{t("savedFileLabel")}: {envSettings.data?.config_path || "-"}</span>
          <span>{t("restartKeysLabel")}: {(envSettings.data?.restart_required_keys || []).join(", ") || "-"}</span>
        </div>
        {Object.entries(envGroups).map(([group, fields]) => (
          <details key={group} open>
            <summary>{group}</summary>
            <div className="dynamic-form cols-2 env-form">
              {fields.map((field) => {
                const savedMasked = Boolean(field.secret && envSettings.data?.values[field.key] === envSettings.data?.masked_secret);
                return (
                  <label key={field.key}>
                    {field.label}
                    {field.kind === "boolean" ? (
                      <select
                        value={envValues[field.key] || ""}
                        onChange={(e) => setEnvValues((current) => ({ ...current, [field.key]: e.target.value }))}
                      >
                        <option value="">{t("unsetOption")}</option>
                        <option value="true">{t("trueOption")}</option>
                        <option value="false">{t("falseOption")}</option>
                      </select>
                    ) : (
                      <input
                        type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"}
                        value={envValues[field.key] || ""}
                        placeholder={savedMasked ? t("configuredKeepPlaceholder") : field.key}
                        onChange={(e) => setEnvValues((current) => ({ ...current, [field.key]: e.target.value }))}
                      />
                    )}
                    <small>
                      {field.key}
                      {envSettings.data?.current[field.key] ? ` · ${t("currentValueLabel")}: ${field.secret ? envSettings.data.masked_secret : envSettings.data.current[field.key]}` : ""}
                      {field.help_text ? ` · ${field.help_text}` : ""}
                    </small>
                  </label>
                );
              })}
            </div>
          </details>
        ))}
        <div className="row-actions left">
          <button
            className="button primary"
            disabled={savingEnv}
            onClick={() => void saveEnv(async () => {
              const next = await api.patch<PortalEnvSettings>("/api/portal/env", { values: envValues });
              envSettings.setData?.(next);
            }, t("envSettingsSaved"))}
          >
            {savingEnv ? <Spinner /> : null}{t("saveEnvSettings")}
          </button>
          <button
            className="button"
            disabled={restartingPortal}
            onClick={async () => {
              if (!(await confirm({ message: t("restartPortalConfirm"), danger: true }))) return;
              void restartPortal(async () => {
                await api.post("/api/portal/restart");
                setRestartMessage(t("restartPortalRequestedMessage"));
              }, t("restartPortalRequestedToast"));
            }}
          >
            {restartingPortal ? <Spinner /> : null}{t("restartPortalButton")}
          </button>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t("logCleanupTitle")}</h2>
            <p className="muted no-margin">{t("logCleanupSubtitle")}</p>
          </div>
          <PanelHelp
            label={t("logCleanupHelp")}
            title={t("logCleanupHelpTitle")}
            intro={t("logCleanupHelpIntro")}
            items={[
              t("logCleanupHelpPreview"),
              t("logCleanupHelpExecute"),
              t("logCleanupHelpRoot")
            ]}
            footer={t("logCleanupHelpRisk")}
          />
        </div>
        <div className="dynamic-form cols-2">
          <label>
            {t("logDirLabel")}
            <input
              value={logDir}
              placeholder={portalSettings.data?.settings ? t("logDirDefaultPlaceholder") : "log"}
              onChange={(e) => setLogDir(e.target.value)}
            />
            <small>{t("logDirHelp")}</small>
          </label>
        </div>
        <div className="row-actions left">
          <button
            className="button"
            disabled={cleaningLogs}
            onClick={() => void runLogCleanup(async () => {
              setLogCleanupResult(await api.post<LogCleanupResult>("/api/logs/cleanup", { log_dir: logDir || undefined, execute: false }));
            }, t("logCleanupPreviewed"))}
          >
            {cleaningLogs ? <Spinner /> : null}{t("preview")}
          </button>
          <button
            className="button danger"
            disabled={cleaningLogs}
            onClick={async () => {
              if (!(await confirm({ message: t("logCleanupExecuteConfirm"), danger: true }))) return;
              void runLogCleanup(async () => {
                setLogCleanupResult(await api.post<LogCleanupResult>("/api/logs/cleanup", { log_dir: logDir || undefined, execute: true }));
              }, t("logCleanupDeleted"));
            }}
          >
            {cleaningLogs ? <Spinner /> : null}{t("delete")}
          </button>
        </div>
        {logCleanupResult ? (
          <>
            <div className="settings-summary">
              <span>{t("logRootLabel")}: {logCleanupResult.log_root}</span>
              <span>{t("logCleanupMatched")}: {logCleanupResult.removed}</span>
              <span>{t("modeLabel")}: {logCleanupResult.execute ? t("delete") : t("preview")}</span>
            </div>
            <DataTable
              rows={logCleanupResult.paths.map((path) => ({ path }))}
              empty={t("empty")}
              columns={[{ key: "path", label: t("pathLabel"), render: (row) => <span className="mono small-text">{String(row.path || "")}</span> }]}
            />
          </>
        ) : null}
      </section>
      {modules.error ? <Alert tone="error">{modules.error}</Alert> : null}
      <div className="grid side">
        <section className="panel">
          <h2>{t("modulesTitle")}</h2>
          {Object.entries(modules.data || {}).map(([name, info]) => (
            <details key={name}>
              <summary>{name}</summary>
              <DataTable
                rows={info.commands as Record<string, unknown>[]}
                columns={[
                  { key: "name", label: t("commandLabel") },
                  { key: "signature", label: t("signatureLabel") },
                  { key: "doc", label: t("docLabel") },
                ]}
              />
            </details>
          ))}
        </section>
        <aside className="panel">
          <div className="panel-head compact">
            <h2>{t("runCommandTitle")}</h2>
            <PanelHelp
              label={t("runCommandHelp")}
              title={t("runCommandHelpTitle")}
              intro={t("runCommandHelpIntro")}
              items={[
                t("runCommandHelpModule"),
                t("runCommandHelpKwargs"),
                t("runCommandHelpRaw"),
                t("runCommandHelpRisk")
              ]}
              footer={t("runCommandHelpFlow")}
            />
          </div>
          <div className="form-grid">
            <label>
              {t("moduleLabel")}
              <select value={runModule} onChange={(e) => setRunModule(e.target.value)}>
                {!moduleNames.length ? <option value="">{t("empty")}</option> : null}
                {moduleNames.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
            <label>
              {t("commandLabel")}
              <select value={runCommand} onChange={(e) => setRunCommand(e.target.value)}>
                {!commandNames.length ? <option value="">{t("empty")}</option> : null}
                {commandNames.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
          </div>
          <HybridJsonEditor value={runKwargs.raw} onChange={runKwargs.setRaw} rows={6} />
          <details>
            <summary>{t("advancedJson")}</summary>
            {runRawError ? <Alert tone="error">{runRawError}</Alert> : null}
            <JsonTextArea value={runRaw.raw} onChange={runRaw.setRaw} rows={10} />
            <div className="row-actions left">
              <button className="button small" onClick={() => applyRawToStructured()}>{t("applyJsonToForm")}</button>
            </div>
          </details>
          <button
            className="button primary"
            disabled={busy}
            onClick={() => void runAction(async () => {
              setResult(await api.post("/api/modules/run", parseRunPayload()));
            }, t("run"))}
          >
            {busy ? <Spinner /> : null}{t("run")}
          </button>
        </aside>
      </div>
      {result ? <pre className="json">{JSON.stringify(result, null, 2)}</pre> : null}
    </>
  );
}

// ---- Live trading (paper sandbox) ------------------------------------------
type LiveConfigSnapshot = {
  mode: string;
  broker: string;
  timezone: string;
  ledger_dir: string;
  state_dir: string;
  risk: Record<string, number>;
};
type LivePosition = { code: string; exchange: string; volume: number; available: number; yd_volume: number; frozen: number; price: number };
type LiveOrder = { order_id: string; code: string; side: string; price: number; volume: number; traded: number; status: string; active: boolean };
type LiveTrade = { trade_id: string; code: string; side: string; price: number; volume: number };
type LiveEngineSnapshot = { mode: string; halted: boolean; connection: string; session: string; buying_power: number; active_orders: number; positions: number };
type LiveState = {
  snapshot: LiveEngineSnapshot;
  account: { buying_power: number; balance: number };
  positions: LivePosition[];
  orders: LiveOrder[];
  trades: LiveTrade[];
  ledger: Array<{ ts: string; kind: string }>;
};
type LiveStatus = { config: LiveConfigSnapshot; modes: string[]; running: boolean; state?: LiveState };

export function LivePage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const fmtMoney = (n: number) => (Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—");
  const status = useAsync(() => api.get<LiveStatus>("/api/live/status"), []);
  const { run } = useAction();
  const [cash, setCash] = useState("1000000");
  const [orderCode, setOrderCode] = useState("");
  const [orderSide, setOrderSide] = useState("buy");
  const [orderVol, setOrderVol] = useState("100");
  const [orderPrice, setOrderPrice] = useState("");
  const [targetJson, setTargetJson] = useState(
    '{\n  "holdings": { "SH600000": 1000 },\n  "prices": { "SH600000": 10.0 }\n}',
  );

  const cfg = status.data?.config;
  const running = Boolean(status.data?.running);
  const state = status.data?.state;

  const connect = () =>
    run(async () => {
      await api.post("/api/live/paper/connect", { cash: Number(cash) || undefined });
      await status.refresh();
    }, t("liveConnected"));
  const submitOrder = () =>
    run(async () => {
      if (!orderCode.trim()) throw new Error(t("liveCode"));
      await api.post("/api/live/paper/order", {
        code: orderCode.trim(),
        side: orderSide,
        volume: Number(orderVol),
        price: Number(orderPrice) || undefined,
      });
      await status.refresh();
    }, t("liveOrderDone"));
  const submitTarget = () =>
    run(async () => {
      await api.post("/api/live/paper/submit-target", JSON.parse(targetJson));
      await status.refresh();
    }, t("liveTargetDone"));
  const halt = async () => {
    if (!(await confirm({ message: t("liveHaltConfirm"), danger: true }))) return;
    await run(async () => {
      await api.post("/api/live/paper/halt", {});
      await status.refresh();
    }, t("liveHaltedDone"));
  };
  const resume = () =>
    run(async () => {
      await api.post("/api/live/paper/resume", {});
      await status.refresh();
    }, t("liveResumedDone"));
  const reset = async () => {
    if (!(await confirm({ message: t("liveResetConfirm"), danger: true }))) return;
    await run(async () => {
      await api.post("/api/live/paper/reset", {});
      await status.refresh();
    }, t("liveResetDone"));
  };

  const riskRows: Array<[string, string]> = cfg
    ? [
        [t("liveRiskMaxOrder"), fmtMoney(cfg.risk.max_order_value)],
        [t("liveRiskMaxDaily"), fmtMoney(cfg.risk.max_daily_value)],
        [t("liveRiskMaxPos"), `${Math.round((cfg.risk.max_position_pct || 0) * 100)}%`],
        [t("liveRiskPriceGuard"), `${Math.round((cfg.risk.price_guard_pct || 0) * 100)}%`],
        [t("liveRiskLot"), String(cfg.risk.lot_size)],
        [t("liveRiskMaxOrders"), String(cfg.risk.max_orders_per_day)],
      ]
    : [];

  return (
    <div className="stack">
      <PageTitle title={t("navLive")} subtitle={t("liveIntro")} />
      <Alert tone="info">{t("livePaperNote")}</Alert>

      <section className="panel">
        <div className="panel-head">
          <div className="panel-title-inline">
            <h2>{t("liveConfig")}</h2>
            <PanelHelp label={t("help")} title={t("liveConfig")} intro={t("liveConfigHelp")} items={[t("liveConfigHelp1"), t("liveConfigHelp2")]} />
          </div>
          <RefreshButton onClick={status.refresh} />
        </div>
        {cfg ? (
          <div className="metric-grid compact">
            <div className="metric"><span className="metric-label">{t("liveMode")}</span><StatusPill status={cfg.mode} /></div>
            <div className="metric"><span className="metric-label">{t("liveBroker")}</span><strong>{cfg.broker}</strong></div>
            {riskRows.map(([label, value]) => (
              <div className="metric" key={label}><span className="metric-label">{label}</span><strong>{value}</strong></div>
            ))}
          </div>
        ) : (
          <Spinner />
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <div className="panel-title-inline">
            <h2>{t("livePaper")}</h2>
            <InfoDot tip={t("livePaperNote")} />
          </div>
        </div>

        {!running || !state ? (
          <div className="toolbar">
            <label className="field">
              <span>{t("liveInitCash")}</span>
              <input value={cash} onChange={(e) => setCash(e.target.value)} inputMode="decimal" />
            </label>
            <AsyncButton onClick={connect}>{t("liveConnect")}</AsyncButton>
          </div>
        ) : (
          <div className="stack">
            <div className="toolbar live-status-bar">
              <span className="metric"><span className="metric-label">{t("liveModeState")}</span><StatusPill status={state.snapshot.mode} /></span>
              <span className="metric"><span className="metric-label">{t("liveKillState")}</span><StatusPill status={state.snapshot.halted ? "halted" : "running"} /></span>
              <span className="metric"><span className="metric-label">{t("liveSession")}</span><StatusPill status={state.snapshot.session} /></span>
              <span className="metric"><span className="metric-label">{t("liveConnection")}</span><StatusPill status={state.snapshot.connection} /></span>
              <span className="metric"><span className="metric-label">{t("liveBuyingPower")}</span><strong>{fmtMoney(state.account.buying_power)}</strong></span>
              <div className="row-actions">
                {state.snapshot.halted ? (
                  <AsyncButton onClick={resume}>{t("liveResume")}</AsyncButton>
                ) : (
                  <AsyncButton className="button danger" onClick={halt}>{t("liveHalt")}</AsyncButton>
                )}
                <AsyncButton className="button ghost" onClick={reset}>{t("liveReset")}</AsyncButton>
              </div>
            </div>

            <div className="toolbar">
              <input placeholder={t("liveCode")} value={orderCode} onChange={(e) => setOrderCode(e.target.value)} />
              <select value={orderSide} onChange={(e) => setOrderSide(e.target.value)}>
                <option value="buy">{t("liveBuy")}</option>
                <option value="sell">{t("liveSell")}</option>
              </select>
              <input placeholder={t("liveVolume")} value={orderVol} onChange={(e) => setOrderVol(e.target.value)} inputMode="numeric" />
              <input placeholder={t("livePrice")} value={orderPrice} onChange={(e) => setOrderPrice(e.target.value)} inputMode="decimal" />
              <AsyncButton onClick={submitOrder}>{t("liveSubmitOrder")}</AsyncButton>
            </div>

            <div className="field">
              <span>{t("liveSubmitTarget")}</span>
              <textarea rows={5} value={targetJson} onChange={(e) => setTargetJson(e.target.value)} spellCheck={false} />
              <small className="field-hint">{t("liveTargetHint")}</small>
              <div className="row-actions"><AsyncButton onClick={submitTarget}>{t("liveSubmit")}</AsyncButton></div>
            </div>

            <h3>{t("livePositions")}</h3>
            <DataTable<LivePosition>
              rows={state.positions}
              empty={t("empty")}
              columns={[
                { key: "code", label: t("liveCode") },
                { key: "volume", label: t("liveVolume"), align: "right" },
                { key: "available", label: t("liveAvailable"), align: "right" },
                { key: "price", label: t("liveAvgPrice"), align: "right", render: (r) => fmtMoney(r.price) },
              ]}
            />

            <h3>{t("liveOrders")}</h3>
            <DataTable<LiveOrder>
              rows={state.orders}
              empty={t("empty")}
              columns={[
                { key: "order_id", label: t("liveOrderId"), ellipsis: true },
                { key: "code", label: t("liveCode") },
                { key: "side", label: t("liveSideCol"), render: (r) => t(r.side === "buy" ? "liveBuy" : "liveSell") },
                { key: "price", label: t("livePrice"), align: "right", render: (r) => fmtMoney(r.price) },
                { key: "volume", label: t("liveVolume"), align: "right" },
                { key: "traded", label: t("liveTraded"), align: "right" },
                { key: "status", label: t("status"), render: (r) => <StatusPill status={r.status} /> },
              ]}
            />

            <h3>{t("liveTrades")}</h3>
            <DataTable<LiveTrade>
              rows={state.trades}
              empty={t("empty")}
              columns={[
                { key: "code", label: t("liveCode") },
                { key: "side", label: t("liveSideCol"), render: (r) => t(r.side === "buy" ? "liveBuy" : "liveSell") },
                { key: "price", label: t("livePrice"), align: "right", render: (r) => fmtMoney(r.price) },
                { key: "volume", label: t("liveVolume"), align: "right" },
              ]}
            />
          </div>
        )}
      </section>
    </div>
  );
}
