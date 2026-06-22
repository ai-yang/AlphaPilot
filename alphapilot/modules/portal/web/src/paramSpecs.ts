export type FieldValue = string | number | boolean | string[] | null | undefined;

export type FieldOption = {
  label: string;
  value: string | number | boolean;
};

export type FieldSpec = {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "checkbox" | "date" | "textarea" | "password";
  defaultValue?: FieldValue;
  placeholder?: string;
  options?: FieldOption[];
  visibleWhen?: (values: Record<string, FieldValue>) => boolean;
  helpText?: string;
  required?: boolean;
  parse?: (value: FieldValue, values: Record<string, FieldValue>) => unknown;
  serialize?: (value: unknown) => FieldValue;
};

export function defaultValuesFor(specs: FieldSpec[]): Record<string, FieldValue> {
  const values: Record<string, FieldValue> = {};
  specs.forEach((field) => {
    if (field.defaultValue !== undefined) values[field.key] = field.defaultValue;
    else values[field.key] = field.type === "checkbox" ? false : "";
  });
  return values;
}

export function visibleFields(specs: FieldSpec[], values: Record<string, FieldValue>): FieldSpec[] {
  return specs.filter((field) => !field.visibleWhen || field.visibleWhen(values));
}

export function buildParams(
  specs: FieldSpec[],
  values: Record<string, FieldValue>,
  advancedJson?: string,
): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const field of visibleFields(specs, values)) {
    const raw = values[field.key];
    if (field.required && (raw === "" || raw === null || raw === undefined)) {
      throw new Error(`${field.label} is required`);
    }
    if (raw === "" || raw === null || raw === undefined) continue;
    if (field.type === "checkbox") {
      params[field.key] = Boolean(raw);
      continue;
    }
    if (field.parse) {
      const parsed = field.parse(raw, values);
      if (parsed !== undefined) params[field.key] = parsed;
      continue;
    }
    if (field.type === "number") {
      const n = Number(raw);
      if (!Number.isFinite(n)) throw new Error(`${field.label} must be a number`);
      params[field.key] = n;
      continue;
    }
    params[field.key] = raw;
  }

  if (advancedJson?.trim()) {
    const advanced = JSON.parse(advancedJson);
    if (advanced === null || Array.isArray(advanced) || typeof advanced !== "object") {
      throw new Error("Advanced JSON must be an object");
    }
    Object.assign(params, advanced as Record<string, unknown>);
  }
  return params;
}

export const adjustModeOptions: FieldOption[] = [
  { label: "none", value: "none" },
  { label: "forward", value: "forward" },
  { label: "backward", value: "backward" },
];

export const dataActionSpecs: FieldSpec[] = [
  {
    key: "action",
    label: "Action",
    type: "select",
    defaultValue: "pipeline",
    options: [
      { label: "pipeline", value: "pipeline" },
      { label: "download", value: "download" },
      { label: "apply_adjust", value: "apply_adjust" },
      { label: "convert", value: "convert" },
      { label: "build_h5", value: "build_h5" },
    ],
  },
  {
    key: "source",
    label: "Data Source",
    type: "select",
    defaultValue: "baostock_cn",
    options: [
      { label: "baostock_cn", value: "baostock_cn" },
      { label: "tushare_cn", value: "tushare_cn" },
    ],
    visibleWhen: (v) => ["pipeline", "download", "apply_adjust"].includes(String(v.action)),
  },
  { key: "start_date", label: "Start Date", type: "date", defaultValue: "2005-01-01", visibleWhen: (v) => ["pipeline", "download"].includes(String(v.action)) },
  { key: "end_date", label: "End Date", type: "date", visibleWhen: (v) => ["pipeline", "download"].includes(String(v.action)) },
  {
    key: "stock_csv",
    label: "Stock CSV",
    type: "text",
    defaultValue: "important_data/stock_lists/main_stock_2026_4_27.csv",
    visibleWhen: (v) => ["pipeline", "download", "convert"].includes(String(v.action)),
  },
  {
    key: "adjust_mode",
    label: "Adjust Mode",
    type: "select",
    defaultValue: "backward",
    options: adjustModeOptions,
    parse: (value, values) => values.source === "tushare_cn" && values.action === "pipeline" ? "none" : value,
    visibleWhen: (v) => ["pipeline", "download", "convert"].includes(String(v.action)),
  },
  {
    key: "target_mode",
    label: "Target Mode",
    type: "select",
    defaultValue: "forward",
    options: [
      { label: "forward", value: "forward" },
      { label: "backward", value: "backward" },
    ],
    visibleWhen: (v) => v.action === "apply_adjust" || (v.action === "pipeline" && v.adjust_mode === "none"),
  },
  { key: "token", label: "Tushare Token", type: "password", visibleWhen: (v) => v.source === "tushare_cn" && ["pipeline", "download"].includes(String(v.action)) },
  { key: "include_daily_basic", label: "Include daily_basic", type: "checkbox", defaultValue: false, visibleWhen: (v) => v.source === "tushare_cn" && ["pipeline", "download"].includes(String(v.action)) },
  { key: "market", label: "Market", type: "text", placeholder: "optional", visibleWhen: (v) => v.action === "build_h5" },
];

export const llmMiningSpecs: FieldSpec[] = [
  { key: "step_n", label: "Step N", type: "number", defaultValue: 5, required: true },
  { key: "scenario", label: "Scenario", type: "text", defaultValue: "alpha_factor_mining" },
  { key: "direction", label: "Direction", type: "textarea", placeholder: "挖掘方向或假说" },
];

export const alphaForgeSpecs: FieldSpec[] = [
  {
    key: "method",
    label: "Method",
    type: "select",
    defaultValue: "mine_aff",
    options: [
      { label: "AFF", value: "mine_aff" },
      { label: "GP", value: "mine_gp" },
      { label: "RL", value: "mine_rl" },
    ],
  },
  { key: "instruments", label: "Instruments", type: "text", defaultValue: "test_stock_pool_80" },
  { key: "train_end_year", label: "Train End Year", type: "number", defaultValue: 2020 },
  { key: "seed", label: "Seed", type: "number", defaultValue: 0 },
  { key: "top_n", label: "Top N", type: "number", defaultValue: 50, visibleWhen: (v) => ["mine_aff", "mine_gp"].includes(String(v.method)) },
  { key: "raw", label: "Raw output", type: "checkbox", defaultValue: true },
  { key: "backtest", label: "Run backtest after mining", type: "checkbox", defaultValue: false },
  { key: "save", label: "Save to factor zoo", type: "checkbox", defaultValue: true },
  { key: "tournament_size", label: "Tournament Size", type: "number", defaultValue: 20, visibleWhen: (v) => v.method === "mine_gp" },
  { key: "num_epochs_g", label: "Generator Epochs", type: "number", defaultValue: 50, visibleWhen: (v) => v.method === "mine_aff" },
  { key: "max_loops", label: "Max Loops", type: "number", defaultValue: 10, visibleWhen: (v) => v.method === "mine_aff" },
];

export const factorBacktestSpecs: FieldSpec[] = [
  { key: "factor_path", label: "Factor CSV", type: "text", required: true },
  {
    key: "mode",
    label: "Mode",
    type: "select",
    defaultValue: "multi_combined",
    options: [
      { label: "multi_combined", value: "multi_combined" },
      { label: "single_ic", value: "single_ic" },
      { label: "multi_sequential", value: "multi_sequential" },
    ],
  },
  { key: "scenario", label: "Scenario", type: "text", defaultValue: "factor_backtest" },
];

export const strategyBacktestSpecs: FieldSpec[] = [
  { key: "strategy_name", label: "Strategy Asset", type: "select", required: true, options: [] },
  {
    key: "mode",
    label: "Mode",
    type: "select",
    defaultValue: "retrain",
    options: [
      { label: "retrain", value: "retrain" },
      { label: "reuse_model", value: "reuse_model" },
    ],
  },
  { key: "scenario", label: "Scenario", type: "text", defaultValue: "factor_backtest" },
];

export function withStrategyOptions(specs: FieldSpec[], names: string[] = []): FieldSpec[] {
  return specs.map((field) => field.key === "strategy_name"
    ? { ...field, options: [{ label: "请选择策略", value: "" }, ...names.map((name) => ({ label: name, value: name }))] }
    : field);
}

export const dailyTradeSpecs: FieldSpec[] = [
  { key: "strategy_name", label: "Strategy Asset", type: "select", options: [] },
  { key: "date", label: "Date", type: "date" },
  { key: "init_cash", label: "Initial Cash", type: "number", defaultValue: 1000000 },
  { key: "state_path", label: "State Path", type: "text" },
  { key: "factor_path", label: "Factor Path", type: "text" },
  { key: "model_pickle_path", label: "Model Pickle Path", type: "text" },
  { key: "refresh_data", label: "Refresh data before run", type: "checkbox", defaultValue: false },
  { key: "notify", label: "Push notification", type: "checkbox", defaultValue: false },
];

export function scheduleSpecsFor(kind: string, strategyNames: string[] = []): FieldSpec[] {
  if (kind === "data") return dataActionSpecs;
  if (kind === "mine") return llmMiningSpecs;
  if (["mine_aff", "mine_gp", "mine_rl"].includes(kind)) {
    return alphaForgeSpecs
      .filter((field) => field.key !== "method")
      .map((field) => {
        if (field.key === "top_n" && ["mine_aff", "mine_gp"].includes(kind)) return { ...field, visibleWhen: undefined };
        if (field.key === "tournament_size" && kind === "mine_gp") return { ...field, visibleWhen: undefined };
        if (["num_epochs_g", "max_loops"].includes(field.key) && kind === "mine_aff") return { ...field, visibleWhen: undefined };
        if (["top_n", "tournament_size", "num_epochs_g", "max_loops"].includes(field.key)) return { ...field, visibleWhen: () => false };
        return field;
      });
  }
  if (kind === "factor_backtest") return factorBacktestSpecs;
  if (kind === "strategy_backtest") return withStrategyOptions(strategyBacktestSpecs, strategyNames);
  if (kind === "daily_signals") return withStrategyOptions(dailyTradeSpecs, strategyNames);
  return [];
}
