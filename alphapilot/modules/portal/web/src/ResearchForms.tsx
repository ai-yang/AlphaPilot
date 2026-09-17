import React, { useEffect, useState } from "react";
import schemas from "./research.schema.json";
import { Catalogs, loadCatalogs, research } from "./researchClient";
import type { Job, JobSpec } from "./research.generated";

type Schema = { $ref?: string; type?: string; title?: string; properties?: Record<string, Schema>; required?: string[]; default?: unknown; enum?: unknown[]; const?: unknown; anyOf?: Schema[]; oneOf?: Schema[]; items?: Schema; minimum?: number; maximum?: number; minLength?: number; maxLength?: number; format?: string; discriminator?: { propertyName: string } };
const registry = schemas as Record<string, Schema>;
export const inputSchemas: Record<JobSpec["kind"], string> = { mine: "MiningInput", mine_aff: "AFFInput", mine_gp: "GPInput", mine_rl: "RLInput", factor_backtest: "FactorBacktestInput", strategy_backtest: "StrategyBacktestInput", data: "DataDownload", daily_signals: "DailyInput", report_factor_extract: "ReportInput" };
export const kindLabels: Record<JobSpec["kind"], string> = { mine: "自主因子挖掘", mine_aff: "AFF 挖掘", mine_gp: "GP 挖掘", mine_rl: "RL 挖掘", factor_backtest: "因子回测", strategy_backtest: "策略复测", data: "数据维护", daily_signals: "日频模拟信号", report_factor_extract: "报告因子提取" };
const labels: Record<string, string> = { dataset_id: "数据集", stock_pool_id: "股票池（留空使用全部）", template_id: "模板", model_id: "模型", strategy_id: "策略资产", session_id: "模拟会话", factor_source: "因子来源", factor_ids: "库内因子", factors: "内联因子表达式", expression: "表达式", name: "名称", parameters: "覆盖模板参数", max_steps: "最大步数", mode: "执行模式", action: "数据操作", date: "交易日期", refresh_data: "执行前更新行情", timeout_seconds: "超时（秒）", init_cash: "初始资金", save_factors_to_library: "保存合格因子到库", save: "保存合格因子到库", symbols: "股票代码列表", categories: "分类列表", time: "每日触发时间", timezone: "时区", direction: "挖掘方向", budget: "执行预算" };
function resolve(schema: Schema): Schema { return schema.$ref ? registry[schema.$ref.split("/").pop()!] : schema; }
export function schemaDefaults(name: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(registry[name]?.properties || {}).filter(([, s]) => s.default !== undefined && s.default !== null).map(([k, s]) => [k, s.default]));
}
export function useCatalogs() {
  const [catalogs, setCatalogs] = useState<Catalogs>(); const [error, setError] = useState("");
  const refresh = async () => { try { setCatalogs(await loadCatalogs()); setError(""); } catch (e) { setError(String(e)); } };
  useEffect(() => { void refresh(); }, []);
  return { catalogs, error, refresh };
}
function optionsFor(key: string, catalogs?: Catalogs) {
  if (!catalogs) return undefined;
  if (key === "dataset_id") return catalogs.datasets.map(r => ({ value: r.dataset_id, label: `${r.label}${r.ready ? "" : "（待准备）"}` }));
  if (key === "template_id") return catalogs.templates.filter(r => r.ready).map(r => ({ value: r.template_id, label: r.label }));
  if (key === "model_id") return catalogs.models.map(r => ({ value: r.model_id, label: r.label }));
  const rows = key === "stock_pool_id" ? catalogs.pools : key === "strategy_id" ? catalogs.strategies : key === "session_id" ? catalogs.sessions : key === "factor_ids" ? catalogs.factors : undefined;
  return rows?.map(r => ({ value: r.id, label: r.name }));
}
function JsonField({ value, onChange, required, label }: { value: unknown; onChange: (value: unknown) => void; required?: boolean; label: string }) {
  const [raw, setRaw] = useState(JSON.stringify(value ?? [], null, 2));
  return <textarea aria-label={label} rows={5} required={required} value={raw} onChange={e => {
    setRaw(e.target.value);
    try { const parsed = JSON.parse(e.target.value); onChange(parsed); e.target.setCustomValidity(""); }
    catch { e.target.setCustomValidity("请输入有效的 JSON"); }
  }} />;
}
function Field({ field, schema, value, set, catalogs, required }: { field: string; schema: Schema; value: unknown; set: (v: unknown) => void; catalogs?: Catalogs; required: boolean }) {
  schema = resolve(schema);
  const choices = schema.oneOf || schema.anyOf;
  if (choices) {
    const possible = choices.map(resolve).filter(s => s.type !== "null");
    if (possible.length === 1) return <Field {...{ field, value, set, catalogs, required }} schema={possible[0]} />;
    const discriminator = schema.discriminator?.propertyName;
    if (discriminator) {
      const selected = possible.find(s => s.properties?.[discriminator]?.const === (value as Record<string, unknown>)?.[discriminator]) || possible[0];
      return <fieldset><legend>{labels[field] || field}</legend><select aria-label={`${field} type`} value={String(selected.properties?.[discriminator]?.const)} onChange={e => set({ [discriminator]: e.target.value })}>
        {possible.map(s => <option key={String(s.properties?.[discriminator]?.const)}>{String(s.properties?.[discriminator]?.const)}</option>)}
      </select><Fields schema={selected} value={(value || {}) as Record<string, unknown>} set={v => set({ [discriminator]: selected.properties?.[discriminator]?.const, ...v })} catalogs={catalogs} /></fieldset>;
    }
  }
  if (schema.const !== undefined) return null;
  const label = labels[field] || schema.title || field;
  const options = optionsFor(field, catalogs);
  if (schema.type === "object") return <details><summary>{label}</summary><Fields schema={schema} value={(value || {}) as Record<string, unknown>} set={set} catalogs={catalogs} /></details>;
  if (schema.type === "boolean") return <label className="inline-check"><input aria-label={label} type="checkbox" checked={Boolean(value)} onChange={e => set(e.target.checked)} /><span>{label}{required ? " *" : ""}</span></label>;
  return <label className={`field${schema.type === "array" ? " field-wide" : ""}`}><span>{label}{required ? " *" : ""}</span>
    {options ? <select aria-label={label} required={required} multiple={schema.type === "array"} value={schema.type === "array" ? (value || []) as string[] : String(value ?? "")} onChange={e => set(schema.type === "array" ? [...e.target.selectedOptions].map(o => o.value) : e.target.value || undefined)}>
      {schema.type !== "array" && <option value="">选择资源</option>}{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select> : schema.enum ? <select aria-label={label} value={String(value ?? schema.default ?? "")} required={required} onChange={e => set(e.target.value || undefined)}><option value="">选择</option>{schema.enum.map(v => <option key={String(v)} value={String(v)}>{String(v)}</option>)}</select>
    : schema.type === "array" ? <JsonField value={value} onChange={set} required={required} label={label} />
    : <input aria-label={label} type={schema.type === "number" || schema.type === "integer" ? "number" : schema.format === "date" ? "date" : "text"} value={value === undefined || value === null ? "" : String(value)} required={required} min={schema.minimum} max={schema.maximum} minLength={schema.minLength} maxLength={schema.maxLength} step={schema.type === "integer" ? 1 : "any"} onChange={e => set(e.target.value === "" ? undefined : schema.type === "number" || schema.type === "integer" ? Number(e.target.value) : e.target.value)} />}
  </label>;
}
function Fields({ schema, value, set, catalogs }: { schema: Schema; value: Record<string, unknown>; set: (v: Record<string, unknown>) => void; catalogs?: Catalogs }) {
  return <div className="form-grid schema-fields">{Object.entries(resolve(schema).properties || {}).map(([key, spec]) => <Field key={key} field={key} schema={spec} value={value[key]} required={Boolean(schema.required?.includes(key))} catalogs={catalogs} set={v => set({ ...value, [key]: v })} />)}</div>;
}
export function SchemaFields({ name, value, onChange, catalogs, omit = [] }: { name: string; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; catalogs?: Catalogs; omit?: string[] }) {
  return <Fields schema={{ ...registry[name], properties: Object.fromEntries(Object.entries(registry[name].properties || {}).filter(([key]) => !omit.includes(key))) }} value={value} set={onChange} catalogs={catalogs} />;
}
export function JobEditor({ kinds, catalogs, onSubmit, initial, label = "提交任务" }: { kinds: JobSpec["kind"][]; catalogs?: Catalogs; onSubmit?: (spec: JobSpec, key: string) => Promise<unknown>; initial?: JobSpec; label?: string }) {
  const [kind, setKind] = useState<JobSpec["kind"]>(initial?.kind || kinds[0]);
  const [value, setValue] = useState<Record<string, unknown>>({ ...schemaDefaults(inputSchemas[kind]), ...initial?.input });
  const [budget, setBudget] = useState<Record<string, unknown>>({ ...schemaDefaults("Budget"), ...initial?.budget });
  const [dailySource, setDailySource] = useState(initial?.kind === "daily_signals" && initial.input.session_id ? "session" : "strategy");
  const [notify, setNotify] = useState(initial?.notify ?? false); const [error, setError] = useState(""); const [result, setResult] = useState<unknown>(); const [busy, setBusy] = useState(false);
  // Preserve the key across transport failures. A deliberate input edit starts a new intent.
  const [key, setKey] = useState(crypto.randomUUID());
  const dataSchemas: Record<string, string> = { convert: "DataConvert", apply_adjust: "DataAdjust", delete_symbol: "DataDelete", refresh_symbol: "DataRefresh", trim_symbol: "DataTrim", apply_adjust_symbol: "DataAdjustSymbol" };
  const schema = kind === "data" ? dataSchemas[String(value.action)] || "DataDownload" : inputSchemas[kind];
  return <form onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError("");
    const spec = { kind, input: value, budget, notify } as JobSpec;
    try { setResult(await (onSubmit ? onSubmit(spec, key) : research.submit(spec, key))); setKey(crypto.randomUUID()); window.dispatchEvent(new Event("research-jobs")); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }}>
    <select aria-label="任务类型" value={kind} onChange={e => { const next = e.target.value as JobSpec["kind"]; setKind(next); setValue(schemaDefaults(inputSchemas[next])); setKey(crypto.randomUUID()); setResult(undefined); }}>
      {kinds.map(k => <option value={k} key={k}>{kindLabels[k]}</option>)}
    </select>
    {kind === "data" && <label>数据操作<select value={String(value.action || "")} required onChange={e => { setValue({ ...schemaDefaults(dataSchemas[e.target.value] || "DataDownload"), dataset_id: value.dataset_id, action: e.target.value }); setKey(crypto.randomUUID()); }}>{["", "download", "update", "pipeline", "convert", "apply_adjust", "delete_symbol", "refresh_symbol", "trim_symbol", "apply_adjust_symbol"].map(a => <option key={a}>{a}</option>)}</select></label>}
    {kind === "daily_signals" && <label>信号来源<select aria-label="信号来源" value={dailySource} onChange={e => { setDailySource(e.target.value); setValue(v => { const { strategy_id, session_id, init_cash, ...rest } = v; return { ...rest, mode: e.target.value === "strategy" ? "preview" : rest.mode }; }); setKey(crypto.randomUUID()); }}><option value="strategy">策略预览</option><option value="session">模拟会话</option></select></label>}
    <SchemaFields key={`${kind}:${schema}`} name={schema} omit={kind === "data" ? ["action"] : kind === "daily_signals" ? dailySource === "session" ? ["strategy_id", "init_cash"] : ["session_id"] : []} value={value} onChange={v => { setValue(v); setKey(crypto.randomUUID()); }} catalogs={catalogs} />
    <details><summary>预算与通知</summary><SchemaFields name="Budget" value={budget} onChange={v => { setBudget(v); setKey(crypto.randomUUID()); }} /><label className="inline-check"><input type="checkbox" checked={notify} onChange={e => { setNotify(e.target.checked); setKey(crypto.randomUUID()); }} />通过已配置渠道通知结果</label></details>
    {error && <p role="alert" className="alert error">{error}</p>}
    <button className="button primary" disabled={busy}>{busy ? "提交中…" : label}</button>
    {result !== undefined && <pre className="json">{JSON.stringify(result, null, 2)}</pre>}
  </form>;
}
