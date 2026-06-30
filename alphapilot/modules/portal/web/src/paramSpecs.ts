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

// Assign a value into the params object. Keys starting with "_" are UI-only controls (e.g. a
// "show overrides" toggle) and are never sent to the backend. Dotted keys ("yaml_params.account")
// are expanded into nested objects so friendly widgets can populate a single nested patch.
function assignParam(params: Record<string, unknown>, key: string, value: unknown): void {
  if (key.startsWith("_")) return;
  if (!key.includes(".")) {
    params[key] = value;
    return;
  }
  const parts = key.split(".");
  let node = params;
  for (let i = 0; i < parts.length - 1; i++) {
    const part = parts[i];
    if (typeof node[part] !== "object" || node[part] === null) node[part] = {};
    node = node[part] as Record<string, unknown>;
  }
  node[parts[parts.length - 1]] = value;
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
      assignParam(params, field.key, Boolean(raw));
      continue;
    }
    if (field.parse) {
      const parsed = field.parse(raw, values);
      if (parsed !== undefined) assignParam(params, field.key, parsed);
      continue;
    }
    if (field.type === "number") {
      const n = Number(raw);
      if (!Number.isFinite(n)) throw new Error(`${field.label} must be a number`);
      assignParam(params, field.key, n);
      continue;
    }
    assignParam(params, field.key, raw);
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
    label: "数据动作 Action",
    type: "select",
    defaultValue: "pipeline",
    options: [
      { label: "pipeline", value: "pipeline" },
      { label: "download", value: "download" },
      { label: "apply_adjust", value: "apply_adjust" },
      { label: "convert", value: "convert" },
    ],
  },
  {
    key: "source",
    label: "数据源 Data Source",
    type: "select",
    defaultValue: "baostock_cn",
    options: [
      { label: "baostock_cn", value: "baostock_cn" },
      { label: "tushare_cn", value: "tushare_cn" },
    ],
    // ``apply_adjust`` is source-aware too: the data system maps ``source`` to that source's
    // raw / factor / output dirs (see DataSystem.apply_adjust) and never forwards it to the CLI.
    visibleWhen: (v) => ["pipeline", "download", "apply_adjust"].includes(String(v.action)),
  },
  { key: "start_date", label: "开始日期 Start Date", type: "date", defaultValue: "2005-01-01", visibleWhen: (v) => ["pipeline", "download"].includes(String(v.action)) },
  { key: "end_date", label: "结束日期 End Date", type: "date", visibleWhen: (v) => ["pipeline", "download"].includes(String(v.action)) },
  {
    key: "stock_csv",
    label: "股票池 CSV Stock CSV",
    type: "text",
    defaultValue: "important_data/stock_lists/main_stock_2026_4_27.csv",
    helpText: "股票池 CSV 路径，通常位于 important_data/stock_lists/ 下，每行一个代码。",
    visibleWhen: (v) => ["pipeline", "download", "convert"].includes(String(v.action)),
  },
  {
    key: "adjust_mode",
    label: "复权模式 Adjust Mode",
    type: "select",
    defaultValue: "backward",
    options: adjustModeOptions,
    parse: (value, values) => values.source === "tushare_cn" && values.action === "pipeline" ? "none" : value,
    visibleWhen: (v) => ["pipeline", "download", "convert"].includes(String(v.action)),
  },
  {
    key: "target_mode",
    label: "目标复权 Target Mode",
    type: "select",
    defaultValue: "forward",
    options: [
      { label: "forward", value: "forward" },
      { label: "backward", value: "backward" },
    ],
    visibleWhen: (v) => v.action === "apply_adjust" || (v.action === "pipeline" && v.adjust_mode === "none"),
  },
  { key: "token", label: "Tushare Token", type: "password", visibleWhen: (v) => v.source === "tushare_cn" && ["pipeline", "download"].includes(String(v.action)) },
  { key: "include_daily_basic", label: "包含 daily_basic", type: "checkbox", defaultValue: false, visibleWhen: (v) => v.source === "tushare_cn" && ["pipeline", "download"].includes(String(v.action)) },
];

// Strategy / money / cost overrides shared by mining, backtest and daily-trade forms. Fields use
// dotted keys so they collect into a single nested ``yaml_params`` patch; they stay hidden behind a
// UI-only ``_show_overrides`` toggle and are only sent when filled (empty = use template defaults).
const strategyClassOptions: FieldOption[] = [
  { label: "默认（按策略/模板）", value: "" },
  { label: "TopkDropoutStrategy", value: "TopkDropoutStrategy" },
  { label: "EnhancedIndexingStrategy", value: "EnhancedIndexingStrategy" },
];

export function strategyParamFields(opts: { showAccount?: boolean } = {}): FieldSpec[] {
  const { showAccount = true } = opts;
  const gate = (v: Record<string, FieldValue>) => Boolean(v._show_overrides);
  const fields: FieldSpec[] = [
    {
      key: "_show_overrides",
      label: "自定义资金 / 调仓 / 成本参数",
      type: "checkbox",
      defaultValue: false,
      helpText: "打开后可覆盖资金、调仓策略、交易成本与日期；留空的字段沿用策略 / 模板默认值。",
    },
  ];
  if (showAccount) {
    fields.push({ key: "yaml_params.account", label: "初始资金", type: "number", placeholder: "50000", helpText: "回测账户初始现金", visibleWhen: gate });
  }
  fields.push(
    { key: "yaml_params.strategy_class", label: "调仓策略", type: "select", defaultValue: "", options: strategyClassOptions, visibleWhen: gate },
    { key: "yaml_params.topk", label: "持仓数 Top-k", type: "number", placeholder: "15", visibleWhen: gate },
    { key: "yaml_params.n_drop", label: "每日剔除数", type: "number", placeholder: "5", visibleWhen: gate },
    { key: "yaml_params.hold_thresh", label: "最短持有天数", type: "number", placeholder: "1", visibleWhen: gate },
    { key: "yaml_params.risk_degree", label: "仓位比例 (0-1)", type: "number", placeholder: "0.9", visibleWhen: gate },
    { key: "yaml_params.open_cost", label: "买入成本", type: "number", placeholder: "0.0002", visibleWhen: gate },
    { key: "yaml_params.close_cost", label: "卖出成本", type: "number", placeholder: "0.0008", visibleWhen: gate },
    { key: "yaml_params.min_cost", label: "单笔最低成本", type: "number", placeholder: "5", visibleWhen: gate },
    { key: "yaml_params.limit_threshold", label: "涨跌停阈值", type: "number", placeholder: "0.095", visibleWhen: gate },
    { key: "yaml_params.benchmark", label: "基准", type: "text", placeholder: "SH000905", visibleWhen: gate },
    { key: "yaml_params.test_start", label: "测试开始", type: "date", visibleWhen: gate },
    { key: "yaml_params.test_end", label: "测试结束", type: "date", visibleWhen: gate },
    { key: "yaml_params.backtest_start", label: "回测开始", type: "date", visibleWhen: gate },
    { key: "yaml_params.backtest_end", label: "回测结束", type: "date", helpText: "回测区间须落在测试区间内", visibleWhen: gate },
  );
  return fields;
}

export const llmMiningSpecs: FieldSpec[] = [
  // One full mining round = 5 steps (假说生成 → 因子构造 → 因子计算 → 回测 → 反馈).
  // Use a multiple of 5 to finish whole rounds; other values stop mid-round.
  { key: "step_n", label: "迭代步数 Step N", type: "number", defaultValue: 5, required: true, helpText: "一整轮挖掘 = 5 步（假说生成 → 因子构造 → 因子计算 → 回测 → 反馈）。建议填 5 的整数倍，才能跑完整轮；非整数倍会停在半途。" },
  { key: "scenario", label: "场景 Scenario", type: "text", defaultValue: "alpha_factor_mining" },
  { key: "direction", label: "方向 Direction", type: "textarea", placeholder: "挖掘方向或假说" },
  // Auto-add each round's mined factors to the factor library (zoo) under a "mined" category.
  { key: "save_factors_to_library", label: "自动加入因子库", type: "checkbox", defaultValue: false, helpText: "每轮挖出的因子表达式会校验去重后存入因子库（mined 分类）。" },
  // Mining drives its data universe by the top-level ``market`` kwarg (run dir + factor h5 spec).
  { key: "market", label: "市场 / 股票池", type: "text", placeholder: "optional", visibleWhen: (v) => Boolean(v._show_overrides) },
  ...strategyParamFields(),
];

export const alphaForgeSpecs: FieldSpec[] = [
  {
    key: "method",
    label: "方法 Method",
    type: "select",
    defaultValue: "mine_aff",
    options: [
      { label: "AFF", value: "mine_aff" },
      { label: "GP", value: "mine_gp" },
      { label: "RL", value: "mine_rl" },
    ],
  },
  { key: "instruments", label: "股票池 Instruments", type: "text", defaultValue: "test_stock_pool_80" },
  { key: "train_end_year", label: "训练截止年 Train End Year", type: "number", defaultValue: 2020 },
  { key: "seed", label: "随机种子 Seed", type: "number", defaultValue: 0 },
  { key: "top_n", label: "候选数 Top N", type: "number", defaultValue: 50, helpText: "保留得分最高的前 N 个候选因子，数值越大搜索/回测耗时越长。", visibleWhen: (v) => ["mine_aff", "mine_gp"].includes(String(v.method)) },
  { key: "raw", label: "原始输出 Raw output", type: "checkbox", defaultValue: false, helpText: "仅当 qlib 数据带 $factor 复权因子字段时勾选；baostock 数据无此字段，勾选会导致取数为空。" },
  { key: "backtest", label: "挖掘后回测 Run backtest", type: "checkbox", defaultValue: false },
  { key: "save", label: "保存到因子库 Save to zoo", type: "checkbox", defaultValue: true },
  { key: "tournament_size", label: "锦标赛规模 Tournament Size", type: "number", defaultValue: 20, visibleWhen: (v) => v.method === "mine_gp" },
  { key: "num_epochs_g", label: "生成器轮数 Generator Epochs", type: "number", defaultValue: 50, visibleWhen: (v) => v.method === "mine_aff" },
  { key: "max_loops", label: "最大循环数 Max Loops", type: "number", defaultValue: 10, visibleWhen: (v) => v.method === "mine_aff" },
];

// Model presets offered when creating a strategy from selected factors. The actual model is
// determined by the qlib template at backtest time; this is stored as the strategy's model
// label / intent (and reused for reuse_model mode later).
const strategyModelOptions: FieldOption[] = [
  { label: "默认（按模板，多因子 LGBM）", value: "" },
  { label: "LGBModel（多因子）", value: "LGBModel" },
  { label: "LinearModel（线性）", value: "LinearModel" },
  { label: "无 / 单因子直接作为信号", value: "none" },
];

// "Create strategy from selected factors" form. ``yaml_params.*`` fields collect into a single
// nested patch (rebalance / cost / dates) saved into the strategy's metadata.
export const createStrategyFromFactorsSpecs: FieldSpec[] = [
  { key: "strategy_name", label: "策略名称", type: "text", required: true, placeholder: "例如 my_multi_factor_v1" },
  { key: "model_name", label: "模型", type: "select", defaultValue: "", options: strategyModelOptions },
  { key: "market", label: "股票池 / market", type: "text", placeholder: "可选，留空用默认" },
  ...strategyParamFields(),
];

// Optional stock-pool picker for backtest forms; sent as part of the nested ``yaml_params`` patch
// (same channel the strategy/template market override uses). Options are filled by
// ``withInstrumentSetOptions`` at render time.
const backtestMarketField: FieldSpec = {
  key: "yaml_params.market",
  label: "股票池 / market",
  type: "select",
  defaultValue: "",
  // Always offers the "use default" choice even before instrument sets load (or on forms that
  // don't apply ``withInstrumentSetOptions``), so the select is never empty.
  options: [{ label: "（默认 / 留空）", value: "" }],
  helpText: "可选，留空用默认股票池",
};

export const factorBacktestSpecs: FieldSpec[] = [
  { key: "factor_path", label: "因子 CSV Factor CSV", type: "text", required: true, helpText: "因子 CSV 路径或因子库导出文件，如 important_data/factor_zoo/xxx.csv。" },
  {
    key: "mode",
    label: "模式 Mode",
    type: "select",
    defaultValue: "multi_combined",
    options: [
      { label: "multi_combined", value: "multi_combined" },
      { label: "single_ic", value: "single_ic" },
      { label: "multi_sequential", value: "multi_sequential" },
    ],
  },
  { key: "scenario", label: "场景 Scenario", type: "text", defaultValue: "factor_backtest" },
  backtestMarketField,
  ...strategyParamFields(),
];

// Backtest options for the factor library's "backtest selected / category" actions. Same shape
// as ``factorBacktestSpecs`` but without ``factor_path`` — the backend writes the factor CSV from
// the selected factors / category. Replaces the previous raw-JSON-only options box.
export const factorLibraryBacktestSpecs: FieldSpec[] = [
  {
    key: "mode",
    label: "回测模式",
    type: "select",
    defaultValue: "multi_combined",
    options: [
      { label: "multi_combined（多因子合成）", value: "multi_combined" },
      { label: "single_ic（逐因子 IC 快筛）", value: "single_ic" },
      { label: "multi_sequential（多因子序贯）", value: "multi_sequential" },
    ],
  },
  { key: "scenario", label: "场景 Scenario", type: "text", defaultValue: "factor_backtest" },
  backtestMarketField,
  ...strategyParamFields(),
];

export const strategyBacktestSpecs: FieldSpec[] = [
  { key: "strategy_name", label: "策略资产 Strategy Asset", type: "select", required: true, options: [] },
  {
    key: "mode",
    label: "模式 Mode",
    type: "select",
    defaultValue: "retrain",
    options: [
      { label: "retrain", value: "retrain" },
      { label: "reuse_model", value: "reuse_model" },
    ],
  },
  { key: "scenario", label: "场景 Scenario", type: "text", defaultValue: "factor_backtest" },
  backtestMarketField,
  ...strategyParamFields(),
];

export function withStrategyOptions(specs: FieldSpec[], names: string[] = []): FieldSpec[] {
  return specs.map((field) => field.key === "strategy_name"
    ? { ...field, options: [{ label: "请选择策略", value: "" }, ...names.map((name) => ({ label: name, value: name }))] }
    : field);
}

export function withSessionOptions(specs: FieldSpec[], names: string[] = []): FieldSpec[] {
  return specs.map((field) => field.key === "session"
    ? { ...field, options: [{ label: "(不使用会话)", value: "" }, ...names.map((name) => ({ label: name, value: name }))] }
    : field);
}

// Turn the stock-pool fields (``market`` / ``yaml_params.market`` / ``instruments``) into
// dropdowns backed by the Qlib instrument sets on disk (``GET /api/data/instrument-sets``).
// ``market`` fields are optional (a blank "use default" choice is offered); ``instruments`` is
// required, so no blank option. The field's own default is kept as an option even when the set
// is not (yet) on disk, so the current value always stays selectable.
export function withInstrumentSetOptions(specs: FieldSpec[], names: string[] = []): FieldSpec[] {
  const optionalKeys = new Set(["market", "yaml_params.market"]);
  const requiredKeys = new Set(["instruments"]);
  return specs.map((field) => {
    const optional = optionalKeys.has(field.key);
    if (!optional && !requiredKeys.has(field.key)) return field;
    const def = typeof field.defaultValue === "string" ? field.defaultValue : "";
    const extra = def && !names.includes(def) ? [{ label: def, value: def }] : [];
    const base = names.map((name) => ({ label: name, value: name }));
    const options: FieldOption[] = optional
      ? [{ label: "（默认 / 留空）", value: "" }, ...extra, ...base]
      : [...extra, ...base];
    return { ...field, type: "select", options };
  });
}

export const dailyTradeSpecs: FieldSpec[] = [
  // Pick a trade session to resume its rolling state + append to its daily history; leave empty
  // to run a one-off against the strategy asset below.
  { key: "session", label: "交易会话 Session", type: "select", options: [], helpText: "选择会话则续跑其滚动持仓并把每日调仓写入会话历史;留空则用下方策略单次运行。" },
  { key: "strategy_name", label: "策略资产 Strategy Asset", type: "select", options: [] },
  // 当天(自动): 不写死日期, 让每次触发解析当日最新交易日; 指定日期: 显示日期选择器写死.
  // 前缀 "_" => UI-only, 不下发后端; "today" 时 date 隐藏且为空 => 调度 kwargs 无 date => 后端解析最新交易日.
  { key: "_date_mode", label: "日期模式 Date mode", type: "select", defaultValue: "today",
    options: [
      { label: "当天(自动·最新交易日)", value: "today" },
      { label: "指定日期", value: "fixed" },
    ],
    helpText: "当天=每次按运行当日的最新交易日自动更新(周末/节假日回退到最近交易日);指定日期=固定跑某一天。" },
  { key: "date", label: "日期 Date", type: "date", visibleWhen: (v) => v._date_mode === "fixed" },
  { key: "init_cash", label: "初始资金 Initial Cash", type: "number", defaultValue: 1000000 },
  // Board-lot size: buy/sell amounts are rounded to whole multiples of this (A-shares = 100).
  { key: "trade_unit", label: "每手股数 Lot size", type: "number", defaultValue: 100, helpText: "买卖按整手撮合并取整为该数的倍数(A股=100);填 0 关闭整手约束。" },
  { key: "state_path", label: "状态文件 State Path", type: "text" },
  { key: "factor_path", label: "因子文件 Factor Path", type: "text" },
  { key: "model_pickle_path", label: "模型文件 Model Pickle Path", type: "text" },
  { key: "refresh_data", label: "运行前刷新数据 Refresh data", type: "checkbox", defaultValue: false },
  { key: "notify", label: "推送通知 Push notification", type: "checkbox", defaultValue: false },
  // Money is set above via ``init_cash``; only expose rebalance / cost / date overrides here.
  ...strategyParamFields({ showAccount: false }),
];

// Lot-size field shared by both run modes below.
const lotField: FieldSpec = { key: "trade_unit", label: "每手股数 Lot size", type: "number", defaultValue: 100, helpText: "买卖按整手撮合并取整为该数的倍数(A股=100);填 0 关闭整手约束。" };

// Resume an existing trade session: strategy + cash are fixed by the snapshot, so the run form
// only needs the per-run knobs (the DailyTradePage shows the session's strategy/cash read-only).
export const sessionRunSpecs: FieldSpec[] = [
  { key: "date", label: "日期 Date", type: "date" },
  lotField,
  { key: "refresh_data", label: "运行前刷新数据 Refresh data", type: "checkbox", defaultValue: false },
  { key: "notify", label: "推送通知 Push notification", type: "checkbox", defaultValue: false },
];

// Ad-hoc one-off run (no session): pick the strategy + seed cash here.
export const oneOffRunSpecs: FieldSpec[] = [
  { key: "strategy_name", label: "策略资产 Strategy Asset", type: "select", options: [] },
  { key: "init_cash", label: "初始资金 Initial Cash", type: "number", defaultValue: 1000000 },
  { key: "date", label: "日期 Date", type: "date" },
  lotField,
  { key: "refresh_data", label: "运行前刷新数据 Refresh data", type: "checkbox", defaultValue: false },
  { key: "notify", label: "推送通知 Push notification", type: "checkbox", defaultValue: false },
  { key: "state_path", label: "状态文件 State Path", type: "text" },
  { key: "factor_path", label: "因子文件 Factor Path", type: "text" },
  { key: "model_pickle_path", label: "模型文件 Model Pickle Path", type: "text" },
  ...strategyParamFields({ showAccount: false }),
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
