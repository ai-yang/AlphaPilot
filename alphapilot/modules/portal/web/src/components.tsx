import { Loader2, RefreshCw, Trash2, XCircle } from "lucide-react";
import React, { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api, Job } from "./api";
import { useI18n } from "./i18n";
import { FieldSpec, FieldValue, visibleFields } from "./paramSpecs";
import { useToast } from "./toast";

const NAV: [string, string][] = [
  ["home", "/"],
  ["mining", "/mining"],
  ["backtest", "/backtest"],
  ["library", "/library"],
  ["market", "/market"],
  ["daily", "/daily-trade"],
  ["scheduler", "/scheduler"],
  ["notify", "/notifications"],
  ["advanced", "/advanced"]
];

function activeNavKey(pathname: string): string {
  const match = NAV.filter(([, href]) => href !== "/").find(([, href]) => pathname.startsWith(href));
  return match ? match[0] : "home";
}

export function Layout() {
  const { lang, setLang, t } = useI18n();
  const location = useLocation();
  const daemon = useDaemonStatus();
  const current = activeNavKey(location.pathname);
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <span className="brand-mark" aria-hidden="true">
            <img src="/branding/logo.svg" alt="" />
          </span>
          <span>
            <strong>AlphaPilot</strong>
            <small>Portal</small>
          </span>
        </Link>
        <nav>
          {NAV.map(([key, href]) => (
            <NavLink key={key} to={href} end={href === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              {t(key)}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="topbar-title">
            <strong>{t(current)}</strong>
            <span className="muted">AlphaPilot Portal</span>
          </div>
          <div className="topbar-actions">
            <span className="daemon-chip" title={t("scheduler")}>
              <span className={`dot ${daemon ? "on" : "off"}`} />
              {daemon ? t("daemonOn") : t("daemonOff")}
            </span>
            <button className="button ghost small" onClick={() => setLang(lang === "zh" ? "en" : "zh")}>
              {lang === "zh" ? "English" : "中文"}
            </button>
          </div>
        </header>
        <section className="content">
          <Outlet />
        </section>
      </main>
    </div>
  );
}

function useDaemonStatus(): boolean {
  const [running, setRunning] = useState(false);
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const data = await api.get<{ running?: boolean }>("/api/schedules/daemon");
        if (alive) setRunning(Boolean(data.running));
      } catch {
        /* ignore */
      }
    };
    void poll();
    const id = window.setInterval(poll, 15000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);
  return running;
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="page-title">
      <h1>{title}</h1>
      {subtitle ? <p>{subtitle}</p> : null}
    </div>
  );
}

export function Alert({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "error" | "success" }) {
  return <div className={`alert ${tone}`}>{children}</div>;
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="spin" />;
}

/**
 * Refresh control that shows a spinning icon while its click is in flight.
 * Promise-aware: it awaits `onClick`, so it works for a `useAsync.refresh`, a
 * manual async loader, or any handler that returns a promise. Self-guards
 * against double-clicks (and the always-present icon improves affordance).
 */
export function RefreshButton({
  onClick,
  className = "button ghost small",
  iconOnly = false,
  label,
  title,
  size = 14,
  disabled = false
}: {
  onClick: () => void | Promise<unknown>;
  className?: string;
  iconOnly?: boolean;
  label?: string;
  title?: string;
  size?: number;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const text = label ?? t("refresh");
  async function handle() {
    if (busy || disabled) return;
    setBusy(true);
    try {
      await onClick();
    } finally {
      setBusy(false);
    }
  }
  return (
    <button
      type="button"
      className={iconOnly ? "icon-button" : className}
      disabled={busy || disabled}
      onClick={() => void handle()}
      title={title ?? (iconOnly ? text : undefined)}
    >
      {busy ? <Loader2 className="spin" size={iconOnly ? 16 : size} /> : <RefreshCw size={iconOnly ? 16 : size} />}
      {iconOnly ? null : <span>{text}</span>}
    </button>
  );
}

export function JsonTextArea({
  value,
  onChange,
  rows = 8,
  placeholder = "{}"
}: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  return <textarea className="mono" rows={rows} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />;
}

type JsonPrimitiveType = "string" | "number" | "boolean" | "null";
type JsonPrimitive = string | number | boolean | null;
type PrimitiveRow = { key: string; type: JsonPrimitiveType; value: string | boolean };

function isPrimitiveValue(value: unknown): value is JsonPrimitive {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function primitiveTypeOf(value: JsonPrimitive): JsonPrimitiveType {
  if (value === null) return "null";
  if (typeof value === "number") return "number";
  if (typeof value === "boolean") return "boolean";
  return "string";
}

function primitiveEntriesFromObject(data: Record<string, unknown>): Array<[string, JsonPrimitive]> {
  return Object.entries(data).filter((entry): entry is [string, JsonPrimitive] => isPrimitiveValue(entry[1]));
}

function primitiveRowsFromObject(data: Record<string, unknown>): PrimitiveRow[] {
  return primitiveEntriesFromObject(data)
    .map(([key, value]) => ({
      key,
      type: primitiveTypeOf(value),
      value: typeof value === "boolean" ? value : value === null ? "" : String(value),
    }));
}

function coercePrimitive(row: PrimitiveRow): string | number | boolean | null {
  if (row.type === "null") return null;
  if (row.type === "boolean") return Boolean(row.value);
  if (row.type === "number") {
    const n = Number(row.value);
    return Number.isFinite(n) ? n : 0;
  }
  return String(row.value ?? "");
}

export function HybridJsonEditor({
  value,
  onChange,
  rows = 8,
  placeholder = "{}",
}: {
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  const { t } = useI18n();
  const [fields, setFields] = useState<PrimitiveRow[]>([]);
  const [parseError, setParseError] = useState<string | null>(null);
  const [complexKeys, setComplexKeys] = useState<string[]>([]);

  useEffect(() => {
    if (!value.trim()) {
      setFields([]);
      setComplexKeys([]);
      setParseError(null);
      return;
    }
    try {
      const parsed = JSON.parse(value);
      if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("JSON must be an object");
      }
      const parsedObject = parsed as Record<string, unknown>;
      setFields(primitiveRowsFromObject(parsedObject));
      setComplexKeys(
        Object.entries(parsedObject)
          .filter(([, fieldValue]) => !isPrimitiveValue(fieldValue))
          .map(([key]) => key),
      );
      setParseError(null);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : String(err));
    }
  }, [value]);

  function commitFields(nextFields: PrimitiveRow[]) {
    setFields(nextFields);
    let source: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(value || "{}");
      if (parsed && !Array.isArray(parsed) && typeof parsed === "object") {
        source = parsed as Record<string, unknown>;
      }
    } catch {
      source = {};
    }

    const output: Record<string, unknown> = {};
    Object.entries(source)
      .filter(([, currentValue]) => !isPrimitiveValue(currentValue))
      .forEach(([key, currentValue]) => {
        output[key] = currentValue;
      });

    nextFields.forEach((field) => {
      const key = field.key.trim();
      if (!key) return;
      output[key] = coercePrimitive(field);
    });

    onChange(JSON.stringify(output, null, 2));
  }

  function updateField(index: number, patch: Partial<PrimitiveRow>) {
    const next = [...fields];
    const current = next[index];
    if (!current) return;
    next[index] = { ...current, ...patch };
    if (patch.type && patch.type !== current.type) {
      if (patch.type === "boolean") next[index].value = false;
      else next[index].value = "";
    }
    commitFields(next);
  }

  return (
    <div className="hybrid-json-editor">
      <div className="hybrid-json-header">
        <strong>{t("structuredParams")}</strong>
        <button
          type="button"
          className="button small ghost"
          onClick={() => commitFields([...fields, { key: "", type: "string", value: "" }])}
        >
          {t("addField")}
        </button>
      </div>
      {fields.length ? (
        <div className="hybrid-json-fields">
          {fields.map((field, index) => (
            <div className="hybrid-json-row" key={`${field.key}-${index}`}>
              <input
                placeholder={t("fieldKey")}
                value={field.key}
                onChange={(e) => updateField(index, { key: e.target.value })}
              />
              <select value={field.type} onChange={(e) => updateField(index, { type: e.target.value as JsonPrimitiveType })}>
                <option value="string">{t("fieldTypeString")}</option>
                <option value="number">{t("fieldTypeNumber")}</option>
                <option value="boolean">{t("fieldTypeBoolean")}</option>
                <option value="null">{t("fieldTypeNull")}</option>
              </select>
              {field.type === "boolean" ? (
                <label className="inline-check compact">
                  <input
                    type="checkbox"
                    checked={Boolean(field.value)}
                    onChange={(e) => updateField(index, { value: e.target.checked })}
                  />
                  <span>{String(Boolean(field.value))}</span>
                </label>
              ) : (
                <input
                  placeholder={field.type === "null" ? "null" : t("fieldValue")}
                  value={field.type === "null" ? "null" : String(field.value ?? "")}
                  disabled={field.type === "null"}
                  onChange={(e) => updateField(index, { value: e.target.value })}
                />
              )}
              <button type="button" className="icon-button danger" onClick={() => commitFields(fields.filter((_, i) => i !== index))}>
                ×
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty">{t("structuredParamsEmpty")}</div>
      )}
      {complexKeys.length ? <p className="muted compact">{t("structuredComplexHint")} {complexKeys.join(", ")}</p> : null}
      {parseError ? <Alert tone="error">{t("jsonSyntaxError")}: {parseError}</Alert> : null}
      <JsonTextArea value={value} onChange={onChange} rows={rows} placeholder={placeholder} />
    </div>
  );
}

export function DynamicForm({
  specs,
  values,
  onChange,
  errors = {},
  columns = 2
}: {
  specs: FieldSpec[];
  values: Record<string, FieldValue>;
  onChange: (key: string, value: FieldValue) => void;
  errors?: Record<string, string>;
  columns?: 1 | 2;
}) {
  const visible = visibleFields(specs, values);
  return (
    <div className={`dynamic-form cols-${columns}`}>
      {errors._form ? <Alert tone="error">{errors._form}</Alert> : null}
      {visible.map((field) => {
        const value = values[field.key];
        const error = errors[field.key];
        const inputId = `field-${field.key}`;
        if (field.type === "checkbox") {
          return (
            <label className="inline-check dynamic-check" key={field.key} htmlFor={inputId}>
              <input id={inputId} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(field.key, e.target.checked)} />
              <span>{field.label}</span>
              {field.helpText ? <small>{field.helpText}</small> : null}
              {error ? <small className="field-error">{error}</small> : null}
            </label>
          );
        }
        return (
          <label key={field.key} htmlFor={inputId}>
            {field.label}
            {field.type === "select" ? (
              <select id={inputId} value={String(value ?? "")} onChange={(e) => onChange(field.key, e.target.value)}>
                {(field.options || []).map((option) => <option key={String(option.value)} value={String(option.value)}>{option.label}</option>)}
              </select>
            ) : field.type === "textarea" ? (
              <textarea id={inputId} rows={4} value={String(value ?? "")} placeholder={field.placeholder} onChange={(e) => onChange(field.key, e.target.value)} />
            ) : (
              <input
                id={inputId}
                type={field.type === "password" ? "password" : field.type === "date" ? "date" : field.type === "number" ? "number" : "text"}
                value={String(value ?? "")}
                placeholder={field.placeholder}
                onChange={(e) => onChange(field.key, e.target.value)}
              />
            )}
            {field.helpText ? <small>{field.helpText}</small> : null}
            {error ? <small className="field-error">{error}</small> : null}
          </label>
        );
      })}
    </div>
  );
}

export function StatusPill({ status }: { status?: string }) {
  const s = status || "unknown";
  return (
    <span className={`pill ${s}`}>
      <span className="pill-dot" />
      {s}
    </span>
  );
}

export function ProgressBar({ percent, label, active = false }: { percent: number; label?: string; active?: boolean }) {
  const value = Math.max(0, Math.min(100, Math.round(percent || 0)));
  return (
    <div className={`progress-block ${active ? "active" : ""}`}>
      <div className="progress-head">
        <span>{label || "Progress"}</span>
        <strong>{value}%</strong>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export function DataTable<T extends Record<string, unknown>>({
  rows,
  columns,
  empty = "No data",
  loading = false
}: {
  rows: T[];
  columns: { key: keyof T | string; label: string; render?: (row: T) => React.ReactNode }[];
  empty?: string;
  loading?: boolean;
}) {
  const { t } = useI18n();
  if (loading && !rows.length) {
    return (
      <div className="empty loading-row">
        <Spinner /> {t("loading")}
      </div>
    );
  }
  if (!rows.length) return <div className="empty">{empty}</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((col, idx) => (
              <th key={`${String(col.key)}-${idx}`}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map((col, colIdx) => (
                <td key={`${String(col.key)}-${colIdx}`}>{col.render ? col.render(row) : String(row[col.key as keyof T] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JobsPanel({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  const toast = useToast();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<Job | null>(null);
  const [log, setLog] = useState("");
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  async function refresh() {
    setSyncing(true);
    try {
      const data = await api.get<Job[]>("/api/jobs");
      setJobs(data);
      setError(null);
      if (selected) {
        const next = data.find((j) => j.job_id === selected.job_id);
        if (next) setSelected(next);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setSyncing(false);
    }
  }

  useEffect(() => {
    void refresh();
    const id = window.setInterval(refresh, 5000);
    return () => window.clearInterval(id);
  }, []);

  async function loadJob(job: Job) {
    setSelected(job);
    setLog("");
    setResult(null);
    const [logRes, resultRes] = await Promise.allSettled([
      api.get<{ log: string }>(`/api/jobs/${job.job_id}/log`),
      api.get<unknown>(`/api/jobs/${job.job_id}/result`)
    ]);
    if (logRes.status === "fulfilled") setLog(logRes.value.log);
    if (resultRes.status === "fulfilled") setResult(resultRes.value);
  }

  async function cancel(job: Job) {
    try {
      await api.post(`/api/jobs/${job.job_id}/cancel`);
      await refresh();
      toast.info(`${t("cancel")} ${job.job_id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function remove(job: Job) {
    if (!window.confirm(`${t("delete")} ${job.job_id}?`)) return;
    try {
      await api.delete(`/api/jobs/${job.job_id}`);
      setSelected(null);
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function clearFinished() {
    if (!window.confirm(t("clearFinishedConfirm"))) return;
    try {
      const res = await api.post<{ deleted: number }>("/api/jobs/clear");
      setSelected(null);
      await refresh();
      toast.success(`${t("clearFinished")}: ${res.deleted}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const visible = compact ? jobs.slice(0, 5) : jobs;
  const hasFinished = jobs.some((j) => j.status !== "running");
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          {t("jobs")}
          <span className={`live-dot${syncing ? " on" : ""}`} title={t("autoRefreshing")} />
        </h2>
        <div className="row-actions">
          {!compact && hasFinished ? (
            <button className="button small ghost" onClick={() => void clearFinished()}>{t("clearFinished")}</button>
          ) : null}
          <RefreshButton iconOnly onClick={refresh} />
        </div>
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <DataTable
        rows={visible as unknown as Record<string, unknown>[]}
        empty={t("empty")}
        loading={loading}
        columns={[
          { key: "kind", label: "Kind" },
          { key: "status", label: "Status", render: (row) => <StatusPill status={String(row.status)} /> },
          {
            key: "progress",
            label: "Progress",
            render: (row) => {
              const progress = row.progress as { percent?: number; stage?: string; message?: string } | undefined;
              return progress ? <ProgressBar percent={progress.percent || 0} label={progress.message || progress.stage} /> : "";
            }
          },
          { key: "result_summary", label: "Summary" },
          {
            key: "job_id",
            label: "",
            render: (row) => {
              const job = row as unknown as Job;
              return (
                <div className="row-actions">
                  <button className="button small" onClick={() => void loadJob(job)}>Open</button>
                  {job.status === "running" ? <button className="icon-button" onClick={() => void cancel(job)} title={t("cancel")}><XCircle size={15} /></button> : null}
                  {job.status !== "running" ? <button className="icon-button danger" onClick={() => void remove(job)} title={t("delete")}><Trash2 size={15} /></button> : null}
                </div>
              );
            }
          }
        ]}
      />
      {selected && !compact ? (
        <div className="split">
          <pre className="log">{log || "No log"}</pre>
          <pre className="json">{JSON.stringify(result ?? selected, null, 2)}</pre>
        </div>
      ) : null}
    </section>
  );
}
