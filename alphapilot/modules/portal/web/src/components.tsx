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
          <span className="brand-mark">A</span>
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

  async function refresh() {
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
        <h2>{t("jobs")}</h2>
        <div className="row-actions">
          {!compact && hasFinished ? (
            <button className="button small ghost" onClick={() => void clearFinished()}>{t("clearFinished")}</button>
          ) : null}
          <button className="icon-button" onClick={refresh} title={t("refresh")}><RefreshCw size={16} /></button>
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
