import Plot from "react-plotly.js";
import { Link } from "react-router-dom";
import { api, Factor, Job, JobProgress, qs, Schedule } from "./api";
import { Alert, DataTable, DynamicForm, JobsPanel, JsonTextArea, PageTitle, ProgressBar, Spinner, StatusPill } from "./components";
import { useAsync, useJsonInput, useParamForm } from "./hooks";
import { useI18n } from "./i18n";
import {
  alphaForgeSpecs,
  dailyTradeSpecs,
  dataActionSpecs,
  factorBacktestSpecs,
  llmMiningSpecs,
  scheduleSpecsFor,
  strategyBacktestSpecs,
  withStrategyOptions,
} from "./paramSpecs";
import { useAction, useToast } from "./toast";
import React, { useEffect, useMemo, useState } from "react";

/** Responsive Plotly height: ~half the viewport, clamped to a sensible range. */
function chartHeight(): number {
  if (typeof window === "undefined") return 420;
  return Math.max(360, Math.min(640, Math.round(window.innerHeight * 0.5)));
}

type Status = {
  metrics: Record<string, string | number>;
  recent_jobs: Job[];
  recent_mining: string[];
  systems: string[];
  modules: Record<string, string[]>;
  config: Record<string, unknown>;
};

type PortalSettings = {
  settings: { host: string; port: number };
  current: { host?: string; port?: number };
  config_path: string;
  host_options: Array<{ value: string; label: string }>;
  restart_required: boolean;
};

export function HomePage() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<Status>("/api/status"), []);
  const metrics = state.data?.metrics || {};
  return (
    <>
      <PageTitle title="AlphaPilot" subtitle={t("homeSubtitle")} />
      {state.error ? <Alert tone="error">{state.error}</Alert> : null}
      <div className="metric-grid">
        {[
          [t("symbols"), metrics.symbols],
          [t("factors"), metrics.factors],
          [t("strategies"), metrics.strategies],
          [t("backtests"), metrics.backtests]
        ].map(([label, value]) => (
          <div className="metric" key={label}>
            <span>{label}</span>
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
  const llmAdvanced = useJsonInput("{}");
  const llmForm = useParamForm(llmMiningSpecs, llmAdvanced.raw);
  const afAdvanced = useJsonInput("{}");
  const afForm = useParamForm(alphaForgeSpecs, afAdvanced.raw);
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

  function deleteSession(name: string) {
    if (!window.confirm(`${t("delete")} ${name}?`)) return;
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
          <h2>{t("llmMining")}</h2>
          <DynamicForm specs={llmMiningSpecs} values={llmForm.values} onChange={llmForm.setValue} errors={llmForm.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={llmAdvanced.raw} onChange={llmAdvanced.setRaw} rows={5} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => startLlmMining()}>{busy ? <Spinner /> : null}{t("run")}</button>
        </section>
        <section className="panel">
          <h2>AlphaForge</h2>
          <DynamicForm specs={alphaForgeSpecs} values={afForm.values} onChange={afForm.setValue} errors={afForm.errors} />
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
          <button className="button small" onClick={() => void sessions.refresh()}>{t("refresh")}</button>
        </div>
        {sessions.error ? <Alert tone="error">{sessions.error}</Alert> : null}
        <DataTable
          rows={(sessions.data || []) as Record<string, unknown>[]}
          empty={t("empty")}
          loading={sessions.loading}
          columns={[
            { key: "name", label: "Session" },
            { key: "mtime", label: "Updated" },
            { key: "path", label: "Path" },
            {
              key: "name",
              label: "",
              render: (row) => (
                <div className="row-actions">
                  <button className="button small" onClick={() => void openSession(String(row.name))}>Open</button>
                  <button className="button small danger" onClick={() => void deleteSession(String(row.name))}>{t("delete")}</button>
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
              empty={t("empty")}
              columns={[
                { key: "path", label: "File" },
                { key: "size", label: "Size" },
                { key: "mtime", label: "Updated" },
                { key: "path", label: "", render: (row) => <button className="button small" onClick={() => void openSessionFile(String(row.path))}>View</button> }
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
  const factorAdvanced = useJsonInput("{}");
  const factorForm = useParamForm(factorBacktestSpecs, factorAdvanced.raw);
  const strategies = useAsync(() => api.get<{ names: string[] }>("/api/strategies"), []);
  const strategySpecs = useMemo(() => withStrategyOptions(strategyBacktestSpecs, strategies.data?.names || []), [strategies.data]);
  const strategyAdvanced = useJsonInput("{}");
  const strategyForm = useParamForm(strategySpecs, strategyAdvanced.raw);
  const list = useAsync(() => api.get<Array<Record<string, unknown>>>("/api/backtests"), []);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
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
    setDetail(await api.get(`/api/backtests/${encodeURIComponent(workspaceId)}`));
  }

  function deleteWorkspace(workspaceId: string) {
    if (!window.confirm(`${t("delete")} ${workspaceId}?`)) return;
    void run(async () => {
      await api.delete(`/api/backtests/${encodeURIComponent(workspaceId)}`);
      if (detail?.workspace_id === workspaceId) setDetail(null);
      await list.refresh();
    });
  }

  const cumulative = (detail?.cumulative as Array<Record<string, unknown>> | undefined) || [];
  const report = (detail?.report as Array<Record<string, unknown>> | undefined) || [];
  const trades = (detail?.trades as Array<Record<string, unknown>> | undefined) || [];
  const holdings = (detail?.holdings as Array<Record<string, unknown>> | undefined) || [];
  const metrics = (detail?.metrics as Record<string, unknown> | undefined) || {};
  const x = cumulative.map((r) => String(r.date));
  return (
    <>
      <PageTitle title={t("backtest")} subtitle={t("backtestSubtitle")} />
      {list.error ? <Alert tone="error">{list.error}</Alert> : null}
      <div className="grid two">
        <section className="panel">
          <h2>{t("factorBacktest")}</h2>
          <DynamicForm specs={factorBacktestSpecs} values={factorForm.values} onChange={factorForm.setValue} errors={factorForm.errors} />
          <details>
            <summary>{t("advancedJson")}</summary>
            <JsonTextArea value={factorAdvanced.raw} onChange={factorAdvanced.setRaw} rows={5} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => startFactorBacktest()}>{busy ? <Spinner /> : null}{t("run")}</button>
        </section>
        <section className="panel">
          <h2>{t("strategyBacktest")}</h2>
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
        <h2>Workspace</h2>
        <DataTable
          rows={(list.data || []) as Record<string, unknown>[]}
          empty={t("empty")}
          loading={list.loading}
          columns={[
            { key: "label", label: "Label" },
            { key: "mtime", label: "Updated" },
            {
              key: "workspace_id",
              label: "",
              render: (row) => (
                <div className="row-actions">
                  <button className="button small" onClick={() => void open(String(row.workspace_id))}>Open</button>
                  <button className="button small danger" onClick={() => void deleteWorkspace(String(row.workspace_id))}>{t("delete")}</button>
                </div>
              )
            }
          ]}
        />
      </section>
      {detail ? (
        <section className="panel">
          <h2>{String(detail.workspace_id)}</h2>
          <div className="metric-grid compact">
            {Object.entries((detail.summary as Record<string, unknown>) || {}).map(([key, value]) => (
              <div className="metric" key={key}><span>{key}</span><strong>{Number(value).toFixed(4)}</strong></div>
            ))}
          </div>
          <Plot
            data={[
              { x, y: cumulative.map((r) => r["策略(含成本)"]), type: "scatter", mode: "lines", name: "策略(含成本)" },
              { x, y: cumulative.map((r) => r["基准"]), type: "scatter", mode: "lines", name: "基准" },
              { x, y: cumulative.map((r) => r["超额(含成本)"]), type: "scatter", mode: "lines", name: "超额(含成本)" }
            ]}
            layout={{ autosize: true, height: chartHeight(), margin: { l: 48, r: 24, t: 24, b: 40 }, hovermode: "x unified" }}
            useResizeHandler
            style={{ width: "100%" }}
          />
          <div className="tabs">
            <button className="active">Summary</button>
          </div>
          <div className="split">
            <DataTable
              rows={Object.entries(metrics).map(([key, value]) => ({ key, value: typeof value === "number" ? value.toFixed(6) : String(value) }))}
              empty={t("empty")}
              columns={[
                { key: "key", label: "Metric" },
                { key: "value", label: "Value" }
              ]}
            />
            <DataTable
              rows={report.slice(-30).reverse()}
              empty={t("empty")}
              columns={Object.keys(report[0] || {}).slice(0, 8).map((key) => ({ key, label: key }))}
            />
          </div>
          <details>
            <summary>Trades</summary>
            <DataTable
              rows={trades.slice(0, 80)}
              empty={t("empty")}
              columns={Object.keys(trades[0] || {}).slice(0, 10).map((key) => ({ key, label: key }))}
            />
          </details>
          <details>
            <summary>Holdings</summary>
            <DataTable
              rows={holdings.slice(0, 80)}
              empty={t("empty")}
              columns={Object.keys(holdings[0] || {}).slice(0, 10).map((key) => ({ key, label: key }))}
            />
          </details>
        </section>
      ) : null}
      <JobsPanel compact />
    </>
  );
}

export function LibraryPage() {
  const { t } = useI18n();
  const factors = useAsync(() => api.get<{ factors: Factor[]; categories: string[]; supports_categories: boolean }>("/api/factors"), []);
  const strategies = useAsync(() => api.get<{ strategies: Array<Record<string, unknown>>; names: string[] }>("/api/strategies"), []);
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
  const factorBacktestOptions = useJsonInput(JSON.stringify({ mode: "multi_combined", scenario: "factor_backtest" }, null, 2));
  const [strategyName, setStrategyName] = useState("");
  const [strategyExportName, setStrategyExportName] = useState("");
  const [strategyExportPath, setStrategyExportPath] = useState("");
  const [strategyImportPath, setStrategyImportPath] = useState("");
  const { busy, run } = useAction();
  const strategyParams = useJsonInput("{}");
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
      const result = await api.post<Record<string, unknown>>("/api/factors", { factor_name: name, factor_expression: expr, categories });
      setValidation(result);
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
      await api.post<Job>("/api/factors/backtest", { factor_names: selectedFactors, options: factorBacktestOptions.parse() });
    }, t("started"));
  }

  function backtestCategory(category: string) {
    void run(async () => {
      await api.post<Job>("/api/factors/backtest", { category, options: factorBacktestOptions.parse() });
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
              <h2>{t("factors")}</h2>
              <input placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <div className="toolbar">
              <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                <option value="">{t("allCategories")}</option>
                {(factors.data?.categories || []).map((cat) => <option key={cat} value={cat}>{cat}</option>)}
              </select>
              <button className="button small" onClick={() => setSelectedFactors(filtered.map((factor) => factor.factor_name))}>{t("selectAllList")}</button>
              <button className="button small" onClick={() => setSelectedFactors([])}>{t("clearSelection")}</button>
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
                { key: "factor_name", label: "Name" },
                { key: "factor_expression", label: "Expression" },
                { key: "categories", label: "Categories", render: (row) => ((row.categories as string[]) || []).join(", ") },
                {
                  key: "factor_name",
                  label: "",
                  render: (row) => <button className="button small danger" onClick={() => void run(async () => { await api.delete(`/api/factors/${encodeURIComponent(String(row.factor_name))}`); await factors.refresh(); })}>{t("delete")}</button>
                }
              ]}
            />
            <div className="toolbar below">
              <span className="muted">{t("selected")} {selectedFactors.length} {t("factorsUnit")}</span>
              <input placeholder={t("categoryNamePh")} value={bulkCategory} onChange={(e) => setBulkCategory(e.target.value)} />
              <button className="button small" disabled={busy || !selectedFactors.length || !bulkCategory.trim()} onClick={() => applyBulkCategory("add")}>{t("bulkAddCategory")}</button>
              <button className="button small" disabled={busy || !selectedFactors.length || !bulkCategory.trim()} onClick={() => applyBulkCategory("remove")}>{t("bulkRemoveCategory")}</button>
              <button className="button small primary" disabled={busy || !selectedFactors.length} onClick={() => backtestSelected()}>{t("backtestSelected")}</button>
            </div>
            <details>
              <summary>{t("backtestParams")}</summary>
              <JsonTextArea value={factorBacktestOptions.raw} onChange={factorBacktestOptions.setRaw} rows={5} />
            </details>
          </section>
          <aside className="panel">
            <h2>{t("addFactor")}</h2>
            <input placeholder="factor_name" value={name} onChange={(e) => setName(e.target.value)} />
            <textarea rows={7} placeholder="factor_expression" value={expr} onChange={(e) => setExpr(e.target.value)} />
            <input placeholder={t("categoriesCommaPh")} value={newFactorCategories} onChange={(e) => setNewFactorCategories(e.target.value)} />
            <button className="button" disabled={busy} onClick={() => validateFactor()}>{t("validate")}</button>
            <button className="button primary" disabled={busy} onClick={() => addFactor()}>{busy ? <Spinner /> : null}{t("save")}</button>
            {validation ? <pre className="inline-json">{JSON.stringify(validation, null, 2)}</pre> : null}
            <h3>Categories</h3>
            <DataTable
              rows={Object.entries(categoryCounts).map(([category, count]) => ({ category, count }))}
              empty={t("empty")}
              columns={[
                { key: "category", label: "Category" },
                { key: "count", label: "Factors" },
                {
                  key: "category",
                  label: "",
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
            <button className="button danger" disabled={busy || !renameFrom} onClick={() => { if (window.confirm(`${t("deleteCategory")} ${renameFrom}?`)) void run(async () => { await api.delete(`/api/factors/categories/${encodeURIComponent(renameFrom)}`); setRenameFrom(""); await factors.refresh(); }, t("deleteCategory")); }}>{t("deleteCategory")}</button>
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
                { key: "strategy_name", label: "Name" },
                { key: "metrics", label: "Metrics", render: (row) => <code>{JSON.stringify(row.metrics || {})}</code> },
                {
                  key: "strategy_name",
                  label: "",
                  render: (row) => (
                    <div className="row-actions">
                      <button className="button small" onClick={() => { setStrategyExportName(String(row.strategy_name)); setStrategyExportPath(`important_data/strategy_zoo/${String(row.strategy_name)}.json`); }}>{t("exportShort")}</button>
                      <button className="button small danger" disabled={busy} onClick={() => void run(async () => { await api.delete(`/api/strategies/${encodeURIComponent(String(row.strategy_name))}`); await strategies.refresh(); })}>{t("delete")}</button>
                    </div>
                  )
                }
              ]}
            />
          </section>
          <aside className="panel">
            <h2>{t("saveStrategyParams")}</h2>
            <input placeholder="strategy_name" value={strategyName} onChange={(e) => setStrategyName(e.target.value)} />
            <JsonTextArea value={strategyParams.raw} onChange={strategyParams.setRaw} />
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

export function MarketPage() {
  const { t } = useI18n();
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
  const [h5Market, setH5Market] = useState("");
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

  async function startBuildH5Job() {
    const kwargs: Record<string, unknown> = { action: "build_h5" };
    if (h5Market) kwargs.market = h5Market;
    const job = await api.post<Job>("/api/jobs", { kind: "data", kwargs });
    setActiveDataJob(job);
    setDataProgress(job.progress || { job_id: job.job_id, status: job.status, percent: 0, stage: "queued", message: "queued" });
    setDataMessage(`已启动 H5 重建任务：${job.job_id}`);
    await dataJobs.refresh();
  }

  const rows = (kline?.rows as Array<Record<string, unknown>> | undefined) || [];
  const recentDataJobs = (dataJobs.data || []).filter((job) => job.kind === "data").slice(0, 5);
  return (
    <>
      <PageTitle title={t("market")} subtitle={t("marketSubtitle")} />
      {dataMessage ? <pre className="inline-json">{dataMessage}</pre> : null}
      <div className="grid side">
        <section className="panel">
          <h2>{t("dataActions")}</h2>
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
                <h3>当前数据任务</h3>
                <StatusPill status={dataProgress.status || activeDataJob?.status} />
              </div>
              <ProgressBar
                percent={dataProgress.percent}
                label={dataProgress.message || dataProgress.stage}
                active={dataProgress.status === "running"}
              />
              <code>{activeDataJob?.job_id}</code>
              <div className="progress-meta">
                {typeof dataProgress.completed === "number" && typeof dataProgress.total === "number" ? <span>完成 {dataProgress.completed}/{dataProgress.total}</span> : null}
                {typeof dataProgress.pending === "number" ? <span>等待 {dataProgress.pending}</span> : null}
                {dataProgress.current_symbol ? <span>股票 {dataProgress.current_symbol}</span> : null}
                {dataProgress.current_file ? <span>文件 {dataProgress.current_file}</span> : null}
                {dataProgress.updated_at ? <span>更新 {new Date(dataProgress.updated_at).toLocaleTimeString()}</span> : null}
                {dataProgress.latest_data_date ? <span>最新日期 {dataProgress.latest_data_date}</span> : null}
                {dataProgress.progress_source ? <span>{dataProgress.progress_source}</span> : null}
              </div>
            </div>
          ) : null}
          {universe.length ? <div className="tag-list">{universe.slice(0, 80).map((s) => <span className="tag" key={s}>{s}</span>)}{universe.length > 80 ? <span className="tag">+{universe.length - 80}</span> : null}</div> : null}
        </section>
        <aside className="panel">
          <h2>{t("symbolManage")}</h2>
          <select value={manageSource} onChange={(e) => { setManageSource(e.target.value); void loadManageSymbols(e.target.value); }}>
            <option value="baostock_cn">baostock_cn</option>
            <option value="tushare_cn">tushare_cn</option>
          </select>
          <button className="button" onClick={() => void loadManageSymbols()}>{t("refresh")}</button>
          <select value={manageSymbol} onChange={(e) => setManageSymbol(e.target.value)}>
            <option value="">{t("selectSymbol")}</option>
            {manageSymbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={manageMode} onChange={(e) => setManageMode(e.target.value)}>
            <option value="backward">backward</option>
            <option value="forward">forward</option>
            <option value="none">none</option>
          </select>
          <button className="button danger" disabled={busy || !manageSymbol} onClick={() => { if (window.confirm(`${t("delete")} ${manageSymbol}?`)) symbolAction("/api/data/symbols/delete", { adjust_mode: manageMode }); }}>{t("deleteSymbol")}</button>
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
          <h3>daily_pv h5</h3>
          <input placeholder="market optional" value={h5Market} onChange={(e) => setH5Market(e.target.value)} />
          <button className="button" disabled={busy} onClick={() => void run(startBuildH5Job)}>{t("rebuildH5")}</button>
        </aside>
      </div>
      <section className="panel">
        <div className="panel-head">
          <h2>最近数据任务</h2>
          <button className="button small" onClick={() => void dataJobs.refresh()}>{t("refresh")}</button>
        </div>
        <DataTable
          rows={recentDataJobs as unknown as Record<string, unknown>[]}
          empty={t("empty")}
          loading={dataJobs.loading}
          columns={[
            { key: "job_id", label: "Job" },
            { key: "status", label: "Status", render: (row) => <StatusPill status={String(row.status)} /> },
            { key: "params", label: "Action", render: (row) => <code>{String((row.params as Record<string, unknown> | undefined)?.action || "")}</code> },
            {
              key: "progress",
              label: "Progress",
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
          <select value={dataDir} onChange={(e) => void loadSymbols(e.target.value)}>
            <option value="">{t("selectDataDir")}</option>
            {(sources.data || []).map((s) => <option key={String(s.path)} value={String(s.path)}>{String(s.label)}</option>)}
          </select>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            <option value="">{t("selectSymbol")}</option>
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="button" disabled={busy || !dataDir || !symbol} onClick={() => loadKline()}>{t("refresh")}</button>
      </section>
      {rows.length ? (
        <section className="panel">
          <Plot
            data={[
              {
                x: rows.map((r) => r.date),
                open: rows.map((r) => r.open),
                high: rows.map((r) => r.high),
                low: rows.map((r) => r.low),
                close: rows.map((r) => r.close),
                type: "candlestick",
                name: symbol
              }
            ]}
            layout={{ autosize: true, height: chartHeight(), margin: { l: 48, r: 24, t: 24, b: 40 }, xaxis: { rangeslider: { visible: false } } }}
            useResizeHandler
            style={{ width: "100%" }}
          />
        </section>
      ) : <div className="empty">{t("empty")}</div>}
    </>
  );
}

export function DailyTradePage() {
  const { t } = useI18n();
  const strategies = useAsync(() => api.get<{ strategies: Array<Record<string, unknown>>; names: string[] }>("/api/strategies"), []);
  const dailySpecs = useMemo(() => withStrategyOptions(dailyTradeSpecs, strategies.data?.names || []), [strategies.data]);
  const params = useJsonInput("{}");
  const dailyForm = useParamForm(dailySpecs, params.raw);
  const [result, setResult] = useState<unknown>(null);
  const { busy, run } = useAction();

  function runDailyTrade() {
    void run(async () => {
      const payload = dailyForm.parse();
      setResult(await api.post("/api/daily-trade", payload));
    }, t("started"));
  }

  return (
    <>
      <PageTitle title={t("daily")} subtitle={t("dailySubtitle")} />
      <div className="grid side">
        <section className="panel">
          {strategies.error ? <Alert tone="error">{strategies.error}</Alert> : null}
          <DynamicForm specs={dailySpecs} values={dailyForm.values} onChange={dailyForm.setValue} errors={dailyForm.errors} />
          <details>
            <summary>{t("advancedParams")}</summary>
            <JsonTextArea value={params.raw} onChange={params.setRaw} rows={7} />
          </details>
          <button className="button primary" disabled={busy} onClick={() => runDailyTrade()}>{busy ? <Spinner /> : null}{t("run")}</button>
        </section>
        <aside className="panel">
          <h2>{t("runResult")}</h2>
          {result ? <pre className="json">{JSON.stringify(result, null, 2)}</pre> : <div className="empty">{t("empty")}</div>}
        </aside>
      </div>
    </>
  );
}

export function SchedulerPage() {
  const { t } = useI18n();
  const schedules = useAsync(() => api.get<Schedule[]>("/api/schedules"), []);
  const strategies = useAsync(() => api.get<{ names: string[] }>("/api/strategies"), []);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("data");
  const [time, setTime] = useState("18:00");
  const [enabled, setEnabled] = useState(true);
  const [notify, setNotify] = useState(false);
  const scheduleAdvanced = useJsonInput("{}");
  const scheduleFields = useMemo(() => scheduleSpecsFor(kind, strategies.data?.names || []), [kind, strategies.data]);
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

  return (
    <>
      <PageTitle title={t("scheduler")} subtitle={t("schedulerSubtitle")} />
      <section className="panel">
        <div className="panel-head">
          <h2>Daemon</h2>
          <StatusPill status={daemon.data?.running ? "running" : "stopped"} />
        </div>
        <div className="row-actions left">
          <button className="button" disabled={busy} onClick={() => void run(async () => { await api.post("/api/schedules/daemon/start"); await daemon.refresh(); }, t("daemonOn"))}>Start</button>
          <button className="button" disabled={busy} onClick={() => void run(async () => { await api.post("/api/schedules/daemon/stop"); await daemon.refresh(); }, t("daemonOff"))}>Stop</button>
        </div>
      </section>
      <div className="grid side">
        <section className="panel">
          <h2>Schedules</h2>
          <DataTable
            rows={(schedules.data || []) as unknown as Record<string, unknown>[]}
            empty={t("empty")}
            loading={schedules.loading}
            columns={[
              { key: "name", label: "Name" },
              { key: "kind", label: "Kind" },
              { key: "time", label: "Time" },
              { key: "enabled", label: "Enabled" },
              {
                key: "schedule_id",
                label: "",
                render: (row) => (
                  <div className="row-actions">
                    <button className="button small" disabled={busy} onClick={() => void run(async () => { await api.post(`/api/schedules/${row.schedule_id}/run`); }, t("started"))}>{t("run")}</button>
                    <button className="button small danger" disabled={busy} onClick={() => void run(async () => { await api.delete(`/api/schedules/${row.schedule_id}`); await schedules.refresh(); })}>{t("delete")}</button>
                  </div>
                )
              }
            ]}
          />
        </section>
        <aside className="panel">
          <h2>{t("createSchedule")}</h2>
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
                <option value="mine_dso">AlphaForge DSO</option>
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
  const cfg = useAsync(() => api.get<Record<string, unknown>>("/api/notify"), []);
  const [raw, setRaw] = useState("");
  const toast = useToast();
  const { busy, run } = useAction();
  React.useEffect(() => {
    if (cfg.data && !raw) setRaw(JSON.stringify(cfg.data.config || {}, null, 2));
  }, [cfg.data]);

  const config = useMemo(() => {
    try {
      return raw ? JSON.parse(raw) as Record<string, unknown> : {};
    } catch {
      return {};
    }
  }, [raw]);
  const fields = (cfg.data?.fields || {}) as Record<string, Array<string | [string, string]>>;

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
    setRaw(JSON.stringify(next, null, 2));
  }

  function updateNotifyAll(value: boolean) {
    const next = { ...config };
    next.options = { ...((next.options as Record<string, unknown>) || {}), notify_on_all_jobs: value };
    setRaw(JSON.stringify(next, null, 2));
  }

  function saveNotify() {
    void run(async () => {
      await api.patch("/api/notify", { config: JSON.parse(raw || "{}") });
      await cfg.refresh();
    }, t("notifySaved"));
  }

  function testChannel(channel?: string) {
    void run(async () => {
      const r = await api.post(`/api/notify/test${channel ? qs({ channel }) : ""}`);
      toast.info(JSON.stringify(r));
    });
  }

  return (
    <>
      <PageTitle title={t("notify")} subtitle={t("notifySubtitle")} />
      <div className="grid side">
        <section className="panel">
          {cfg.error ? <Alert tone="error">{cfg.error}</Alert> : null}
          <p className="muted">{t("credentialsPath")}：{String(cfg.data?.credentials_path || "")}</p>
          <p className="muted">{t("configuredChannels")}：{((cfg.data?.configured_channels as string[]) || []).join(", ") || t("none")}</p>
          <label className="inline-check">
            <input
              type="checkbox"
              checked={Boolean(((config.options as Record<string, unknown>) || {}).notify_on_all_jobs)}
              onChange={(e) => updateNotifyAll(e.target.checked)}
            />
            {t("notifyAllJobs")}
          </label>
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
                        value={Array.isArray(value) ? value.join(",") : String(value || "")}
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
          <button className="button primary" disabled={busy} onClick={() => saveNotify()}>{busy ? <Spinner /> : null}{t("save")}</button>
          <button className="button" disabled={busy} onClick={() => testChannel()}>{t("testAll")}</button>
        </section>
        <aside className="panel">
          <h2>{t("advancedJson")}</h2>
          <JsonTextArea value={raw} onChange={setRaw} rows={18} />
        </aside>
      </div>
    </>
  );
}

export function AdvancedPage() {
  const { t } = useI18n();
  const portalSettings = useAsync(() => api.get<PortalSettings>("/api/portal/settings"), []);
  const [portalHost, setPortalHost] = useState("127.0.0.1");
  const [portalPort, setPortalPort] = useState("19901");
  const modules = useAsync(() => api.get<Record<string, { commands: Array<Record<string, string>> }>>("/api/modules"), []);
  const run = useJsonInput(JSON.stringify({ module: "portal", command: "scheduler", kwargs: { interval: 30 } }, null, 2));
  const [result, setResult] = useState<unknown>(null);
  const { busy, run: runAction } = useAction();
  const { busy: savingPortal, run: savePortal } = useAction();
  useEffect(() => {
    if (!portalSettings.data) return;
    setPortalHost(portalSettings.data.settings.host);
    setPortalPort(String(portalSettings.data.settings.port));
  }, [portalSettings.data]);
  return (
    <>
      <PageTitle title={t("advanced")} subtitle={t("advancedSubtitle")} />
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Portal Settings</h2>
            <p className="muted no-margin">Configure the default host and port used the next time `alphapilot portal` starts.</p>
          </div>
        </div>
        {portalSettings.error ? <Alert tone="error">{portalSettings.error}</Alert> : null}
        {portalSettings.data?.restart_required ? (
          <Alert>Saved settings differ from the current running address. Restart `alphapilot portal` to apply them.</Alert>
        ) : null}
        <div className="dynamic-form cols-2">
          <label>
            Bind host
            <select value={portalHost} onChange={(e) => setPortalHost(e.target.value)}>
              {(portalSettings.data?.host_options || [
                { value: "127.0.0.1", label: "127.0.0.1 (local only)" },
                { value: "0.0.0.0", label: "0.0.0.0 (LAN / all interfaces)" }
              ]).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <small>Default is local-only. Choose 0.0.0.0 only when this machine should accept LAN connections.</small>
          </label>
          <label>
            Port
            <input type="number" min={1} max={65535} value={portalPort} onChange={(e) => setPortalPort(e.target.value)} />
            <small>CLI arguments still override saved settings, e.g. `alphapilot portal --port 19902`.</small>
          </label>
        </div>
        <div className="settings-summary">
          <span>Current: {portalSettings.data?.current.host || window.location.hostname}:{portalSettings.data?.current.port || window.location.port || "80"}</span>
          <span>Saved file: {portalSettings.data?.config_path || "-"}</span>
        </div>
        <button
          className="button primary"
          disabled={savingPortal}
          onClick={() => void savePortal(async () => {
            const next = await api.patch<PortalSettings>("/api/portal/settings", { host: portalHost, port: Number(portalPort) });
            portalSettings.setData?.(next);
          }, "Portal settings saved")}
        >
          {savingPortal ? <Spinner /> : null}Save Portal Settings
        </button>
      </section>
      {modules.error ? <Alert tone="error">{modules.error}</Alert> : null}
      <div className="grid side">
        <section className="panel">
          <h2>Modules</h2>
          {Object.entries(modules.data || {}).map(([name, info]) => (
            <details key={name}>
              <summary>{name}</summary>
              <DataTable rows={info.commands as Record<string, unknown>[]} columns={[{ key: "name", label: "Command" }, { key: "signature", label: "Signature" }, { key: "doc", label: "Doc" }]} />
            </details>
          ))}
        </section>
        <aside className="panel">
          <h2>Run Command</h2>
          <JsonTextArea value={run.raw} onChange={run.setRaw} />
          <button className="button primary" disabled={busy} onClick={() => void runAction(async () => { setResult(await api.post("/api/modules/run", run.parse())); }, t("run"))}>{busy ? <Spinner /> : null}{t("run")}</button>
        </aside>
      </div>
      {result ? <pre className="json">{JSON.stringify(result, null, 2)}</pre> : null}
    </>
  );
}
