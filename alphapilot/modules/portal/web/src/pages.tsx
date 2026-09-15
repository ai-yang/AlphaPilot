import { AdvancedResearch } from "./ResearchPages";
import { ResearchGate } from "./ResearchConnection";
import { research } from "./researchClient";
import type { Asset } from "./research.generated";
import { api, Factor, getOperatorToken, Job, JobProgress, qs, Schedule, setOperatorToken, type PortalSecurityStatus } from "./api";
import { Alert, AsyncButton, DataTable, DynamicForm, HybridJsonEditor, InfoDot, JobsPanel, JsonTextArea, PageTitle, PanelHelp, ProgressBar, RefreshButton, Spinner, StatusPill, Tabs, Tooltip, useConfirm } from "./components";
import { useAsync, useJsonInput, useLatestRequest, useParamForm } from "./hooks";
import { useI18n } from "./i18n";
import type { TradeSessionDetail, TradeSessionManifest } from "./pages/dailyTrade/types";
import { previewColumns, TimingResultPanel } from "./pages/timing/TimingResultPanel";
import type { TimingDetailPayload, TimingSignalPayload, TimingStrategiesPayload } from "./pages/timing/types";
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
  validateParams,
  withStrategyOptions,
  withInstrumentSetOptions,
} from "./paramSpecs";
import { useAction, useToast } from "./toast";
import React, { useEffect, useMemo, useState } from "react";

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

function formatTimestamp(value: unknown): string {
  if (!value) return "—";
  const d = new Date(String(value));
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
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

export { MiningPage, BacktestPage, LibraryPage, MarketPage, DailyTradePage, SchedulerPage } from "./ResearchPages";

export function TimingPage() {
  const { t } = useI18n();
  const portalSecurity = useAsync(
    () => api.get<PortalSecurityStatus>("/api/portal/security"),
    [],
  );
  const strategies = useAsync(async () => {
    const payload = await api.get<{ definitions: Array<Record<string, unknown>> }>("/api/trading/strategy-definitions");
    const rows = payload.definitions
      .filter((item) => item.signal_kind === "instrument_timing")
      .map((item) => {
        const schema = (item.parameter_schema || {}) as { properties?: Record<string, { default?: unknown }> };
        const defaults = Object.fromEntries(Object.entries(schema.properties || {})
          .filter(([, spec]) => spec.default !== undefined)
          .map(([key, spec]) => [key, spec.default]));
        return {
          name: String(item.strategy_id || ""),
          description: String(item.description || ""),
          defaults,
          parameter_schema: item.parameter_schema as TimingStrategiesPayload["strategies"][number]["parameter_schema"],
          required_history: Number(item.required_history || 1),
          version: String(item.version || ""),
          source: String(item.source || ""),
          code_hash: String(item.code_hash || ""),
        };
      });
    return {
      strategies: rows,
      names: rows.map((item) => item.name),
      definitions: payload.definitions,
    } as TimingStrategiesPayload & { definitions: Array<Record<string, unknown>> };
  }, []);
  const policyDefinitions = useAsync(
    () => api.get<{ definitions: Array<Record<string, unknown>> }>("/api/trading/portfolio-policy-definitions"),
    [],
  );
  const researchAssets = useAsync(
    async () => { const rows = await research.all<Asset>("/strategies"); return { strategies: rows.map(r => ({ ...r.metadata, strategy_name: r.name })), names: rows.map(r => r.name) }; },
    [],
  );
  const specs = useMemo(
    () => timingBacktestSpecs(strategies.data?.names || [], strategies.data?.strategies || []),
    [strategies.data],
  );
  const advanced = useJsonInput("{}");
  const form = useParamForm(specs);
  const { busy, run } = useAction();
  const [signalPreview, setSignalPreview] = useState<TimingSignalPayload | null>(null);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [detail, setDetail] = useState<TimingDetailPayload | null>(null);
  const instances = useAsync(
    () => api.get<{ instances: Array<{ instance_id: string; strategy_id: string; validation_state: string; config_hash: string }> }>("/api/trading/strategy-instances"),
    [],
  );
  const [newInstanceId, setNewInstanceId] = useState("");
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const [operatorToken, setOperatorTokenValue] = useState(getOperatorToken());
  const [researchInstanceId, setResearchInstanceId] = useState("");
  const [researchAsset, setResearchAsset] = useState("");
  const [researchUniverse, setResearchUniverse] = useState("");
  // If status cannot be loaded, keep showing the token field (fail closed).
  const operatorAuthRequired = portalSecurity.data?.operator_auth_required !== false;

  const selectedStrategy = useMemo(() => {
    const name = String(form.values.strategy_name || "boll_mean_reversion");
    return strategies.data?.strategies.find((item) => item.name === name) || null;
  }, [form.values.strategy_name, strategies.data]);

  function parseTimingPayload() {
    const base = form.parse();
    const extra = advanced.parse();
    const payload = mergeTimingAdvanced(base, extra);
    validateParams(payload);
    return payload;
  }

  function previewSignals() {
    void run(async () => {
      const payload = parseTimingPayload();
      if (!selectedInstanceId) throw new Error("请先选择策略实例");
      const result = await api.post<{
        signal: { as_of: string; payload: { scores?: Record<string, number>; states?: Record<string, string> } };
      }>(`/api/trading/strategy-instances/${selectedInstanceId}/preview`, payload);
      const scores = result.signal.payload.scores || {};
      const states = result.signal.payload.states || {};
      const rows = Object.keys({ ...scores, ...states }).sort().map((instrument) => ({
        datetime: result.signal.as_of,
        instrument,
        signal: states[instrument] === "long" ? 1 : 0,
        score: scores[instrument] ?? 0,
        state: states[instrument] || "",
      }));
      setSignalPreview({
        strategy_name: selectedStrategy?.name || "",
        signals: { columns: ["datetime", "instrument", "signal", "score", "state"], rows, row_count: rows.length },
      });
    }, t("timingSignalReady"));
  }

  function startBacktest() {
    void run(async () => {
      const payload = parseTimingPayload();
      if (!selectedInstanceId) throw new Error("请先选择策略实例");
      const runRecord = await api.post<{ run_id: string; status: string }>(
        `/api/trading/strategy-instances/${selectedInstanceId}/backtest-runs`, payload,
      );
      const job: Job = { job_id: runRecord.run_id, kind: "trading_replay", status: runRecord.status };
      setActiveJob(job);
      setProgress({ job_id: runRecord.run_id, status: runRecord.status, percent: 0, stage: runRecord.status });
      setDetail(null);
    }, t("started"));
  }

  function createStrategyInstance() {
    void run(async () => {
      if (!newInstanceId.trim()) throw new Error("instance_id is required");
      const payload = parseTimingPayload();
      const strategyParams = { ...((payload.strategy_params || {}) as Record<string, unknown>) };
      if (payload.target_percent !== undefined) strategyParams.target_percent = payload.target_percent;
      await api.post("/api/trading/strategy-instances", {
        instance_id: newInstanceId.trim(),
        strategy_id: payload.strategy_name,
        params: strategyParams,
        universe: payload.symbols || [],
        frequency: payload.freq || "day",
        data_policy: {
          feature_adjustment: payload.adjust_mode || "backward",
        },
      });
      setSelectedInstanceId(newInstanceId.trim());
      setNewInstanceId("");
      await instances.refresh();
    }, "策略实例已保存");
  }

  function validateStrategyInstance(instanceId: string) {
    void run(async () => {
      await api.post(`/api/trading/strategy-instances/${instanceId}/validate`, {});
      await instances.refresh();
    }, "策略实例校验完成");
  }

  function importResearchAsset() {
    void run(async () => {
      if (!researchInstanceId.trim() || !researchAsset.trim()) {
        throw new Error("实例 ID 和研究资产均为必填项");
      }
      await api.post("/api/trading/strategy-instances/from-research-asset", {
        instance_id: researchInstanceId.trim(),
        strategy_name: researchAsset.trim(),
        universe: researchUniverse.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean),
        reason: "Portal research asset snapshot",
      });
      setSelectedInstanceId(researchInstanceId.trim());
      setResearchInstanceId("");
      await instances.refresh();
    }, "研究资产已快照为不可变选股实例");
  }

  useEffect(() => {
    if (!activeJob?.job_id || !["queued", "running"].includes(activeJob.status)) return;
    const jobId = activeJob.job_id;
    let alive = true;
    let timer: number | undefined;
    async function poll() {
      let terminal = false;
      try {
        const runRecord = await api.get<{
          run_id: string; status: string; result?: Record<string, unknown>; artifact_dir?: string;
        }>(`/api/trading/backtest-runs/${jobId}`);
        const next: JobProgress = {
          job_id: jobId,
          status: runRecord.status,
          percent: ["completed", "failed", "cancelled"].includes(runRecord.status) ? 100 : 50,
          stage: runRecord.status,
          message: runRecord.status,
        };
        if (!alive) return;
        setProgress(next);
        if (next.status === "completed") {
          const loaded = await api.get<{
            artifact_dir: string;
            result: Record<string, unknown>;
            detail?: { signals?: Array<Record<string, unknown>>; orders?: Array<Record<string, unknown>>; equity?: Array<Record<string, unknown>>; positions?: Array<Record<string, unknown>> };
          }>(`/api/trading/backtest-runs/${jobId}/detail`);
          const table = (rows: Array<Record<string, unknown>> = []) => ({
            rows,
            columns: [...new Set(rows.flatMap((row) => Object.keys(row)))],
            row_count: rows.length,
          });
          const artifacts = loaded.detail || {};
          const mapped: TimingDetailPayload = {
            job: { job_id: jobId, kind: "trading_replay", status: "completed" },
            summary: { ...loaded.result, total_return: loaded.result.return },
            artifact_dir: loaded.artifact_dir,
            signals: table(artifacts.signals),
            trades: table(artifacts.orders),
            equity_curve: table((artifacts.equity || []).map((row) => ({ ...row, datetime: row.session }))),
            positions: table((artifacts.positions || []).map((row) => ({ ...row, datetime: row.session, amount: row.volume }))),
          };
          if (alive) setDetail(mapped);
        }
        terminal = ["completed", "failed", "cancelled"].includes(String(next.status));
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
        terminal = true;
      }
      if (alive && !terminal) timer = window.setTimeout(poll, 3000);
    }
    void poll();
    return () => {
      alive = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeJob?.job_id, activeJob?.status]);

  return (
    <>
      <PageTitle title={t("timing")} subtitle={t("timingSubtitle")} />
      {operatorAuthRequired ? (
        <section className="panel inset">
          <label className="field"><span>{t("timingOperatorTokenScope")}</span>
            <input type="password" value={operatorToken} onChange={(event) => {
              setOperatorTokenValue(event.target.value);
              setOperatorToken(event.target.value);
            }} placeholder="apop_…" autoComplete="off" />
          </label>
        </section>
      ) : (
        <Alert tone="error">
          <strong>{t("portalOperatorAuthOptionalTitle")}</strong>
          <br />
          {t("portalOperatorAuthOptionalWarning")} {t("portalOperatorAuthBind")}: <code>{portalSecurity.data?.bind_address || portalSecurity.data?.bind_host || "—"}</code>.
          {portalSecurity.data?.restart_required ? ` ${t("portalOperatorAuthRestartPending")}` : ""}
          {operatorToken ? (
            <div className="row-actions left">
              <span>{t("portalOperatorAuthSuppliedToken")}</span>
              <button type="button" className="button small" onClick={() => {
                setOperatorTokenValue("");
                setOperatorToken("");
              }}>{t("portalOperatorAuthClearToken")}</button>
            </div>
          ) : null}
        </Alert>
      )}
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

      <section className="panel">
        <div className="panel-head compact">
          <div><h2>策略实例</h2><span className="muted">实例只保存代码、参数、因子、模型、股票池和政策；部署在实盘工作区独立配置。</span></div>
        </div>
        <div className="row-actions">
          <input value={newInstanceId} onChange={(event) => setNewInstanceId(event.target.value)} placeholder="实例 ID，例如 ma_5_20" />
          <button className="button" disabled={busy} onClick={createStrategyInstance}>保存当前参数为实例</button>
          <label className="field"><span>运行实例</span>
            <select value={selectedInstanceId} onChange={(event) => setSelectedInstanceId(event.target.value)}>
              <option value="">选择用于预览/回测的实例</option>
              {(instances.data?.instances || []).map((item) => <option key={item.instance_id} value={item.instance_id}>{item.instance_id}</option>)}
            </select>
          </label>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>实例</th><th>策略</th><th>校验状态</th><th>配置哈希</th><th>操作</th></tr></thead>
            <tbody>{(instances.data?.instances || []).map((item) => (
              <tr key={item.instance_id}>
                <td>{item.instance_id}</td><td>{item.strategy_id}</td><td>{item.validation_state}</td>
                <td><code>{item.config_hash.slice(0, 12)}</code></td>
                <td><button className="button small" disabled={busy} onClick={() => validateStrategyInstance(item.instance_id)}>校验</button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      <div className="grid two">
        <section className="panel">
          <div className="panel-head compact"><div><h2>策略与政策定义</h2><span className="muted">定义只描述信号；政策负责把信号转换为目标权重。</span></div></div>
          <DataTable
            rows={(strategies.data as (TimingStrategiesPayload & { definitions?: Array<Record<string, unknown>> }) | undefined)?.definitions || []}
            empty="暂无策略定义"
            columns={[
              { key: "strategy_id", label: "策略 ID" },
              { key: "signal_kind", label: "信号类型" },
              { key: "version", label: "版本" },
              { key: "provider_api_version", label: "Provider API" },
              { key: "required_history", label: "预热 Bar", align: "right" },
            ]}
          />
          <DataTable
            rows={policyDefinitions.data?.definitions || []}
            empty="暂无组合政策"
            columns={[
              { key: "policy_id", label: "政策 ID" },
              { key: "version", label: "版本" },
              { key: "description", label: "说明", ellipsis: true },
            ]}
          />
        </section>
        <section className="panel">
          <div className="panel-head compact"><div><h2>研究资产导入</h2><span className="muted">模型和因子会复制到不可变 artifact；不接受任意上传路径。</span></div></div>
          <div className="dynamic-form cols-1">
            <label>实例 ID<input value={researchInstanceId} onChange={(event) => setResearchInstanceId(event.target.value)} placeholder="qlib_topk_demo" /></label>
            <label>研究策略资产<select value={researchAsset} onChange={(event) => setResearchAsset(event.target.value)}>
              <option value="">选择研究资产</option>
              {(researchAssets.data?.names || (researchAssets.data?.strategies || []).map((item) => String(item.strategy_name || ""))).filter(Boolean).map((name) => <option key={name} value={name}>{name}</option>)}
            </select></label>
            <label>股票池（可选覆盖）<textarea value={researchUniverse} onChange={(event) => setResearchUniverse(event.target.value)} rows={3} placeholder="600000.SH, 000001.SZ" /></label>
          </div>
          <button className="button primary" disabled={busy} onClick={importResearchAsset}>创建不可变选股实例</button>
        </section>
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

      {detail ? <TimingResultPanel detail={detail} /> : null}
      <JobsPanel compact />
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
      const path = planOnly ? "/commands/plan" : "/commands/dispatch";
      const r = await research.post<Record<string, unknown>>(path, { text: commandText });
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

const retiredResearchModules = new Set(["alpha_mining", "factor", "stock_pool", "strategy_backtest", "daily_trade", "report_factor", "alphaforge_aff", "alphaforge_search", "qlib_yaml", "data_viz", "backtest_viz"]);
const localResearchCommands = new Set(["prepare_data", "research_token", "research_migrate", "task_runtime", "scheduler"]);

export function AdvancedPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const portalSettings = useAsync(() => api.get<PortalSettings>("/api/portal/settings"), []);
  const portalSecurity = useAsync(
    () => api.get<PortalSecurityStatus>("/api/portal/security"),
    [],
  );
  const envSettings = useAsync(() => api.get<PortalEnvSettings>("/api/portal/env"), []);
  const [portalHost, setPortalHost] = useState("127.0.0.1");
  const [portalPort, setPortalPort] = useState("19901");
  const [portalTz, setPortalTz] = useState("Asia/Shanghai");
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const modules = useAsync(() => api.get<Record<string, { commands: Array<Record<string, string>> }>>("/api/modules"), []);
  const [runModule, setRunModule] = useState("portal");
  const [runCommand, setRunCommand] = useState("timezone");
  const runKwargs = useJsonInput(JSON.stringify({}, null, 2));
  const runRaw = useJsonInput(JSON.stringify({ module: "portal", command: "timezone", kwargs: {} }, null, 2));
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
  const moduleNames = useMemo(() => Object.keys(modules.data || {}).filter(name => !retiredResearchModules.has(name)).sort(), [modules.data]);
  const commandNames = useMemo(
    () => ((modules.data?.[runModule]?.commands || []).map((cmd) => String(cmd.name)).filter(name => !localResearchCommands.has(name))),
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
      <ResearchGate><AdvancedResearch /></ResearchGate>
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
        <section className="panel inset" aria-label={t("portalSecurityTitle")}>
          <div className="panel-head compact">
            <div>
              <h3>{t("portalSecurityTitle")}</h3>
              <p className="muted no-margin">{t("portalSecurityReadOnly")}</p>
            </div>
          </div>
          {portalSecurity.data?.operator_auth_required === false ? (
            <Alert tone="error">
              <strong>{t("portalOperatorAuthOptionalTitle")}</strong>
              <br />
              {t("portalOperatorAuthOptionalWarning")}
            </Alert>
          ) : null}
          <div className="settings-summary">
            <span>{t("portalSecurityMode")}: <strong>{portalSecurity.data?.operator_auth_mode || "required"}</strong></span>
            <span>{t("portalSecuritySource")}: {portalSecurity.data?.source || t("portalSecurityFailClosed")}</span>
            <span>{t("portalOperatorAuthBind")}: {portalSecurity.data?.bind_address || "—"}</span>
            <span>{t("portalSecurityAutomatedLive")}: {portalSecurity.data?.automated_live_enabled ? t("liveYes") : t("liveNo")}</span>
          </div>
          {portalSecurity.data?.restart_required ? <Alert>{t("portalOperatorAuthRestartPending")}</Alert> : null}
          <p className="muted no-margin">{t("portalSecurityCliHint")} <code>alphapilot portal_operator_auth</code></p>
        </section>
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
              const payload = parseRunPayload();
              if (retiredResearchModules.has(payload.module) || localResearchCommands.has(payload.command)) throw new Error("请使用本页研究操作面板；凭据与迁移仅支持本机 CLI。");
              setResult(await api.post("/api/modules/run", payload));
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

export { HomePage } from "./pages/home/HomePage";
export { LivePage } from "./pages/live/LivePage";
export { klineAxisType, klineCategoryTicks, klineIsIntraday, klineTimeLabel } from "./pages/market/kline";
