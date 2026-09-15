import { ResearchConnection, ResearchGate } from "./ResearchConnection";
import { ResearchJobs } from "./ResearchJobs";
import { research } from "./researchClient";
import { AlertTriangle, HelpCircle, Info, Loader2, Moon, RefreshCw, Sun, Trash2, XCircle } from "lucide-react";
import React, { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api, Job } from "./api";
import { useI18n } from "./i18n";
import { FieldSpec, FieldValue, visibleFields } from "./paramSpecs";
import { useToast } from "./toast";

const NAV: [string, string][] = [
  ["home", "/"],
  ["mining", "/mining"],
  ["backtest", "/backtest"],
  ["timing", "/timing"],
  ["library", "/library"],
  ["market", "/market"],
  ["daily", "/daily-trade"],
  ["live", "/live"],
  ["scheduler", "/scheduler"],
  ["notify", "/notifications"],
  ["advanced", "/advanced"]
];

function activeNavKey(pathname: string): string {
  const match = NAV.filter(([, href]) => href !== "/").find(([, href]) => pathname.startsWith(href));
  return match ? match[0] : "home";
}

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => (localStorage.getItem("portal_theme") === "dark" ? "dark" : "light"));
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("portal_theme", theme);
  }, [theme]);
  return [theme, () => setTheme((cur) => (cur === "dark" ? "light" : "dark"))];
}

export function Layout() {
  const { lang, setLang, t } = useI18n();
  const [theme, toggleTheme] = useTheme();
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
          <div className="topbar-actions"><ResearchConnection />
            <span className="daemon-chip" title={daemon ? t("daemonTipOn") : t("daemonTipOff")}>
              <span className={`dot ${daemon ? "on" : "off"}`} />
              {daemon ? t("daemonOn") : t("daemonOff")}
            </span>
            <button
              className="button ghost small icon-only"
              onClick={toggleTheme}
              title={theme === "dark" ? t("themeLight") : t("themeDark")}
              aria-label={theme === "dark" ? t("themeLight") : t("themeDark")}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button className="button ghost small" onClick={() => setLang(lang === "zh" ? "en" : "zh")}>
              {lang === "zh" ? "English" : "中文"}
            </button>
          </div>
        </header>
        <section className="content">
          {["home", "mining", "backtest", "library", "market", "daily", "scheduler"].includes(current) ? <ResearchGate><Outlet /></ResearchGate> : <Outlet />}
        </section>
      </main>
    </div>
  );
}

function useDaemonStatus(): boolean {
  const [running, setRunning] = useState(false);
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const data = await research.get<{ running?: boolean }>("/schedules/runtime/status");
        if (alive) setRunning(Boolean(data.running));
      } catch {
        /* ignore */
      }
      if (alive) timer = window.setTimeout(poll, 15000);
    };
    void poll();
    return () => {
      alive = false;
      if (timer !== undefined) window.clearTimeout(timer);
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

/** Hover/focus tooltip bubble. Pure CSS positioning (see `.tooltip` in styles.css). */
export function Tooltip({ tip, children, className }: { tip: string; children: React.ReactNode; className?: string }) {
  return (
    <span className={`tooltip${className ? ` ${className}` : ""}`} tabIndex={0}>
      {children}
      <span className="tooltip-bubble" role="tooltip">{tip}</span>
    </span>
  );
}

/** Small info icon that reveals an explanatory tooltip — use beside labels/metrics. */
export function InfoDot({ tip }: { tip: string }) {
  return (
    <Tooltip tip={tip} className="info-dot">
      <Info size={14} aria-hidden="true" />
    </Tooltip>
  );
}

/**
 * Button whose `onClick` may be async: shows a spinner and disables itself while the click is in
 * flight, so primary actions get a consistent loading state and are guarded against double-clicks.
 */
export function AsyncButton({
  onClick,
  children,
  className = "button",
  disabled = false,
  title,
  type = "button"
}: {
  onClick: () => void | Promise<unknown>;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
  title?: string;
  type?: "button" | "submit";
}) {
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  async function handle() {
    if (inFlight.current || disabled) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await onClick();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <button type={type} className={className} disabled={busy || disabled} title={title} onClick={() => void handle()}>
      {busy ? <Loader2 className="spin" size={15} /> : null}
      {children}
    </button>
  );
}

export function PanelHelp({
  label,
  title,
  intro,
  items,
  footer
}: {
  label: string;
  title: string;
  intro?: string;
  items: string[];
  footer?: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [offsetX, setOffsetX] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open) return;

    const keepInsideViewport = () => {
      const trigger = triggerRef.current;
      const popover = popoverRef.current;
      if (!trigger || !popover) return;

      const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
      const viewportPadding = 16;
      const triggerRect = trigger.getBoundingClientRect();
      const popoverWidth = popover.getBoundingClientRect().width;
      const naturalLeft = triggerRect.right - popoverWidth;
      const minLeft = viewportPadding;
      const maxLeft = Math.max(minLeft, viewportWidth - viewportPadding - popoverWidth);
      const clampedLeft = Math.min(maxLeft, Math.max(minLeft, naturalLeft));
      setOffsetX(clampedLeft - naturalLeft);
    };

    keepInsideViewport();
    window.addEventListener("resize", keepInsideViewport);
    window.addEventListener("scroll", keepInsideViewport, true);
    return () => {
      window.removeEventListener("resize", keepInsideViewport);
      window.removeEventListener("scroll", keepInsideViewport, true);
    };
  }, [open]);

  return (
    <div className="panel-help">
      <button
        ref={triggerRef}
        type="button"
        className="icon-button"
        aria-label={label}
        title={label}
        aria-expanded={open}
        onClick={() => setOpen((cur) => !cur)}
      >
        <HelpCircle size={16} />
      </button>
      {open ? (
        <div
          ref={popoverRef}
          className="help-popover"
          role="dialog"
          aria-label={label}
          style={{ transform: `translateX(${offsetX}px)` }}
        >
          <div className="help-popover-head">
            <strong>{title}</strong>
            <button type="button" className="button ghost small icon-only" aria-label={t("cancel")} onClick={() => setOpen(false)}>×</button>
          </div>
          {intro ? <p>{intro}</p> : null}
          <ul>
            {items.map((item) => <li key={item}>{item}</li>)}
          </ul>
          {footer ? <p className="muted compact">{footer}</p> : null}
        </div>
      ) : null}
    </div>
  );
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

/** Responsive Plotly height: ~half the viewport, clamped to a sensible range. */
export function chartHeight(): number {
  if (typeof window === "undefined") return 420;
  return Math.max(360, Math.min(640, Math.round(window.innerHeight * 0.5)));
}

/** Simple tab bar reusing the `.tabs` styling. Caller owns the active state. */
export function Tabs({
  tabs,
  active,
  onChange
}: {
  tabs: { key: string; label: string }[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="tabs">
      {tabs.map((tb) => (
        <button key={tb.key} className={tb.key === active ? "active" : ""} onClick={() => onChange(tb.key)}>
          {tb.label}
        </button>
      ))}
    </div>
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

const STATUS_LABEL_KEY: Record<string, string> = {
  running: "stRunning",
  succeeded: "stSucceeded",
  failed: "stFailed",
  cancelled: "stCancelled",
  lost: "stLost",
  pending: "stPending",
  stopped: "stStopped",
  unknown: "stUnknown",
};

export function StatusPill({ status }: { status?: string }) {
  const { t } = useI18n();
  const s = status || "unknown";
  const label = STATUS_LABEL_KEY[s] ? t(STATUS_LABEL_KEY[s]) : s;
  return (
    <span className={`pill ${s}`} title={t("statusTip")}>
      <span className="pill-dot" />
      {label}
    </span>
  );
}

export function ProgressBar({ percent, label, active = false }: { percent: number; label?: string; active?: boolean }) {
  const { t } = useI18n();
  const value = Math.max(0, Math.min(100, Math.round(percent || 0)));
  return (
    <div className={`progress-block ${active ? "active" : ""}`}>
      <div className="progress-head">
        <span>{label || t("progress")}</span>
        <strong>{value}%</strong>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export type Column<T> = {
  key: keyof T | string;
  label: string;
  render?: (row: T) => React.ReactNode;
  /** Horizontal alignment of header + cell (numbers read better right-aligned). */
  align?: "left" | "right" | "center";
  /** Render long values on a single line with an ellipsis; hover shows the full text. */
  ellipsis?: boolean;
};

export function DataTable<T extends Record<string, unknown>>({
  rows,
  columns,
  empty,
  loading = false
}: {
  rows: T[];
  columns: Column<T>[];
  empty?: string;
  loading?: boolean;
}) {
  const { t } = useI18n();
  const emptyText = empty ?? t("empty");
  if (loading && !rows.length) {
    return (
      <div className="empty loading-row">
        <Spinner /> {t("loading")}
      </div>
    );
  }
  if (!rows.length) return <div className="empty">{emptyText}</div>;
  const cellClass = (col: Column<T>) =>
    [col.align ? `col-${col.align}` : "", col.ellipsis ? "cell-ellipsis" : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((col, idx) => (
              <th key={`${String(col.key)}-${idx}`} className={col.align ? `col-${col.align}` : undefined}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map((col, colIdx) => {
                const raw = String(row[col.key as keyof T] ?? "");
                const content = col.render ? col.render(row) : raw;
                return (
                  <td
                    key={`${String(col.key)}-${colIdx}`}
                    className={cellClass(col)}
                    title={col.ellipsis && !col.render ? raw : undefined}
                  >
                    {content}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JobsPanel({ compact = false }: { compact?: boolean }) {
  return <ResearchGate><ResearchJobs compact={compact} /></ResearchGate>;
}


type ConfirmOptions = {
  message: string;
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

type ConfirmState = ConfirmOptions & { resolve: (ok: boolean) => void };

const ConfirmContext = createContext<((opts: ConfirmOptions) => Promise<boolean>) | null>(null);

/**
 * Themed replacement for `window.confirm`. Wrap the app in `ConfirmProvider`, then call
 * `const confirm = useConfirm()` and `if (!(await confirm({ message, danger: true }))) return;`
 * in any handler. The dialog matches the portal theme (incl. dark mode).
 */
export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const [state, setState] = useState<ConfirmState | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  const confirm = useCallback(
    (opts: ConfirmOptions) => new Promise<boolean>((resolve) => {
      previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setState((current) => {
        current?.resolve(false);
        return { ...opts, resolve };
      });
    }),
    [],
  );

  function close(ok: boolean) {
    setState((cur) => {
      cur?.resolve(ok);
      window.setTimeout(() => previousFocus.current?.focus(), 0);
      return null;
    });
  }

  useEffect(() => {
    if (!state) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state ? (
        <div className="modal-overlay" onClick={() => close(false)}>
          <div
            ref={dialogRef}
            className="modal-card"
            role={state.danger ? "alertdialog" : "dialog"}
            aria-modal="true"
            aria-labelledby="portal-confirm-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-head">
              {state.danger ? <AlertTriangle size={18} className="modal-danger-icon" /> : <Info size={18} className="modal-info-icon" />}
              <strong id="portal-confirm-title">{state.title || t("confirmTitle")}</strong>
            </div>
            <p className="modal-body">{state.message}</p>
            <div className="modal-actions">
              <button className="button" onClick={() => close(false)}>{state.cancelLabel || t("cancel")}</button>
              <button className={`button ${state.danger ? "danger" : "primary"}`} autoFocus onClick={() => close(true)}>
                {state.confirmLabel || t("confirm")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  // Progressive enhancement: when a ConfirmProvider is mounted (the real app) use the themed
  // dialog; otherwise (e.g. unit tests rendering a page in isolation) fall back to the native
  // confirm so callers can stay agnostic.
  if (ctx) return ctx;
  return (opts: ConfirmOptions) => Promise.resolve(window.confirm(opts.message));
}
