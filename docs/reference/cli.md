# CLI 完整参考

> 本文件由 `scripts/generate_docs_reference.py` 生成，请勿手工编辑。

当前内置公共命令共 **120** 个。第三方模块命令不计入此清单。

通用帮助：`alphapilot <command> -- --help`。参数由 Python Fire 解析，布尔值建议显式写成 `--flag=True|False`。

## LLM 因子挖掘（`alpha_mining`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `backtest` | Run a single-shot factor backtest from a factor CSV. | `(path: 'str \| None' = None, step_n: 'int \| None' = None, factor_path: 'str \| None' = None, scenario: 'str' = 'factor_backtest', qlib_config_name: 'str \| None' = None, qlib_template_dir: 'str \| None' = None, mode: 'str' = 'multi_combined', yaml_params: 'str \| None' = None, market: 'str \| None' = None, freq: 'str' = 'day') -> 'None'` | `None` | 计算并写入产物 | 正式 | 回测 | `/api/jobs、/api/backtests` |
| `delete_mine_log` | Delete a mining log session directory under the configured log root. | `(session: 'str') -> 'bool'` | `bool` | 破坏性/清理操作 | 正式 | 因子挖掘 | `/api/jobs、/api/mining` |
| `delete_run` | Delete a per-task run directory (shared cache symlink targets are preserved). | `(run_id: 'str') -> 'bool'` | `bool` | 破坏性/清理操作 | 正式 | 因子挖掘 | `/api/jobs、/api/mining` |
| `list_mine_logs` | Return mining log session folder names under the configured log root. | `() -> 'list[str]'` | `list[str]` | 只读、诊断或本地计算 | 正式 | 因子挖掘 | `/api/jobs、/api/mining` |
| `list_runs` | List per-task run directories (newest first) with their manifest summary. | `() -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 因子挖掘 | `/api/jobs、/api/mining` |
| `mine` | Run the autonomous factor-mining loop. | `(path: 'str \| None' = None, step_n: 'int \| None' = None, direction: 'str \| None' = None, stop_event: 'Any' = None, scenario: 'str' = 'alpha_factor_mining', qlib_config_name: 'str \| None' = None, qlib_template_dir: 'str \| None' = None, qlib_dir: 'str \| None' = None, market: 'str \| None' = None, yaml_params: 'str \| None' = None, save_factors_to_library: 'bool' = False, random_seed: 'int \| None' = None, campaign_id: 'str \| None' = None, freq: 'str' = 'day') -> 'dict[str, Any]'` | `dict[str, Any]` | 计算并写入产物 | 正式 | 因子挖掘 | `/api/jobs、/api/mining` |

## 平台运维（`platform`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `clean_logs` | Clean empty/stub AlphaPilot log directories. | `(log_dir: 'str \| None' = None, execute: 'bool' = False) -> 'dict[str, object]'` | `dict[str, object]` | 破坏性/清理操作 | 正式 | 首页/高级设置 | `/api/portal、/api/modules、/api/logs` |
| `delete_stock` | Delete one stock across raw CSVs, factor, Qlib features and instruments. | `(symbol: 'str', adjust_mode: 'str' = 'all', source: 'str' = 'baostock_cn', dry_run: 'bool' = False) -> 'Any'` | `Any` | 破坏性/清理操作 | 正式 | 行情数据 | `/api/data、/api/market` |
| `list_stocks` | List local stock symbols (optionally for one adjust mode). | `(adjust_mode: 'str \| None' = None, source: 'str' = 'baostock_cn') -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 行情数据 | `/api/data、/api/market` |
| `modules` | List loaded modules with their command names. | `() -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 首页/高级设置 | `/api/portal、/api/modules、/api/logs` |
| `prepare_data` | Run prepare-data actions through the data system entrypoint. | `(action: 'str' = 'pipeline', start_date: 'str' = '2015-01-01', end_date: 'str \| None' = None, stock_csv: 'str \| None' = None, adjust_mode: 'str' = 'backward', market: 'str \| None' = None, qlib_dir: 'str \| None' = None, output_dir: 'str \| None' = None, **options: 'Any') -> 'Any'` | `Any` | 数据下载/转换写操作 | 正式 | 行情数据 | `/api/data、/api/market` |
| `refresh_stock` | Re-download one stock (incremental) and re-sync its Qlib binary. | `(symbol: 'str', adjust_mode: 'str' = 'backward', source: 'str' = 'baostock_cn', start_date: 'str' = '2016-12-31', end_date: 'str \| None' = None, qlib_adjust_mode: 'str' = 'backward', resync_qlib: 'bool' = True) -> 'Any'` | `Any` | 数据下载/转换写操作 | 正式 | 行情数据 | `/api/data、/api/market` |
| `trim_stock` | Trim one stock's CSV to ``[start_date, end_date]`` / drop ``drop_dates``. | `(symbol: 'str', adjust_mode: 'str' = 'all', source: 'str' = 'baostock_cn', start_date: 'str \| None' = None, end_date: 'str \| None' = None, drop_dates: 'str \| None' = None, qlib_adjust_mode: 'str' = 'backward', resync_qlib: 'bool' = True, dry_run: 'bool' = False) -> 'Any'` | `Any` | 破坏性/清理操作 | 正式 | 行情数据 | `/api/data、/api/market` |

## 独立行情可视化（`data_viz`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `data_viz` | Launch Streamlit K-line viewer for downloaded stock CSV data. | `(port: 'int' = 19902, host: 'str' = '0.0.0.0') -> 'None'` | `None` | 长运行进程 | 回退工具 | 行情数据 | `/api/data、/api/market` |

## Portal、调度与通知入口（`portal`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `notify_commands` | Run the inbound notification command receiver. | `(channel: 'str' = 'telegram', poll_interval: 'float \| None' = None) -> 'None'` | `None` | 长运行进程 | 正式 | 通知 | `/api/notify` |
| `portal` | Launch the React/FastAPI unified web portal. | `(port: 'int \| None' = None, host: 'str \| None' = None, reload: 'bool' = False) -> 'None'` | `None` | 长运行进程 | 正式 | 首页/高级设置 | `/api/portal、/api/modules、/api/logs` |
| `portal_operator_auth` | Show or change Portal operator authentication. | `(required: 'bool \| None' = None, operator_id: 'str' = '', reason: 'str' = '', acknowledge_network_risk: 'bool' = False, restart: 'bool' = False) -> 'dict[str, Any]'` | `dict[str, Any]` | 配置或进程控制 | 正式 | 首页/高级设置 | `GET /api/portal/security（只读）` |
| `portal_restart` | Restart a running `alphapilot portal` process. | `() -> 'dict[str, Any]'` | `dict[str, Any]` | 配置或进程控制 | 正式 | 首页/高级设置 | `/api/portal、/api/modules、/api/logs` |
| `scheduler` | Run the daily task scheduler daemon (auto-fires saved data/mine/backtest schedules). | `(interval: 'int' = 30) -> 'None'` | `None` | 长运行进程 | 正式 | 调度 | `/api/schedules` |
| `timezone` | Show or set the AlphaPilot timezone (default Asia/Shanghai). | `(tz: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 配置或进程控制 | 正式 | 首页/高级设置 | `/api/portal、/api/modules、/api/logs` |

## 独立回测可视化（`backtest_viz`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `backtest_viz` | Launch Streamlit backtest artifact viewer. | `(port: 'int' = 19903, host: 'str' = '0.0.0.0') -> 'None'` | `None` | 长运行进程 | 回退工具 | 回测 | `/api/backtests` |

## Qlib YAML（`qlib_yaml`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `qlib_yaml_generate` | Generate a qlib qrun YAML from structured params and optional LLM prompt. | `(output: 'str', template: 'str' = 'baseline', prompt: 'str \| None' = None, params_file: 'str \| None' = None, market: 'str \| None' = None, benchmark: 'str \| None' = None, topk: 'int \| None' = None, backtest_start: 'str \| None' = None, backtest_end: 'str \| None' = None, test_start: 'str \| None' = None, test_end: 'str \| None' = None, learning_rate: 'float \| None' = None, provider_uri: 'str \| None' = None, workspace: 'str \| None' = None, skip_smoke: 'bool' = False, smoke_timeout: 'int' = 120, copy_helpers: 'bool' = False) -> 'dict[str, Any]'` | `dict[str, Any]` | 计算并写入产物 | 正式 | CLI 专用 | `—` |
| `qlib_yaml_validate` | Validate an existing qlib qrun YAML. | `(config: 'str', workspace: 'str \| None' = None, skip_smoke: 'bool' = False, smoke_timeout: 'int' = 120) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | CLI 专用 | `—` |

## 每日交易会话（`daily_trade`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `daily_signals` | Generate today's trade plan. | `(strategy_name: 'str \| None' = None, session: 'str \| None' = None, factor_path: 'str \| None' = None, model_pickle_path: 'str \| None' = None, yaml_params: 'str \| None' = None, date: 'str \| None' = None, state_path: 'str \| None' = None, init_cash: 'float \| None' = None, refresh_data: 'bool' = False, qlib_template_dir: 'str \| None' = None, market: 'str \| None' = None, factor_data_dir: 'str \| None' = None, trade_unit: 'int \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 计算并写入产物 | 正式 | 每日交易 | `/api/daily-trade、/api/trade-sessions` |
| `daily_state` | Show the current saved portfolio state for a strategy. | `(strategy_name: 'str \| None' = None, state_path: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 每日交易 | `/api/daily-trade、/api/trade-sessions` |
| `trade_session_cash` | Simulate a cash deposit / withdrawal on a session's rolling balance. | `(name: 'str', amount: 'float', note: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 每日交易 | `/api/daily-trade、/api/trade-sessions` |
| `trade_session_create` | Snapshot an existing strategy into a new trade session. | `(name: 'str \| None' = None, strategy_name: 'str \| None' = None, init_cash: 'float \| None' = None, overwrite: 'bool' = False) -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 每日交易 | `/api/daily-trade、/api/trade-sessions` |
| `trade_session_delete` | Delete a trade session and all its data (strategy snapshot + state + history). | `(name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 破坏性/清理操作 | 正式 | 每日交易 | `/api/daily-trade、/api/trade-sessions` |
| `trade_session_history` | Show a session's per-day rebalance log. | `(name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 每日交易 | `/api/daily-trade、/api/trade-sessions` |
| `trade_session_list` | List all trade sessions (manifests). | `() -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 每日交易 | `/api/daily-trade、/api/trade-sessions` |
| `trade_session_show` | Show a session: manifest + current portfolio state + recent history. | `(name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 每日交易 | `/api/daily-trade、/api/trade-sessions` |

## 因子库 CLI（`factor`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `category_create` | Create an (initially empty) category. | `(name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 因子与策略库 | `/api/factors` |
| `category_delete` | Delete a category (factors are kept; only the assignments are removed). | `(name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 破坏性/清理操作 | 正式 | 因子与策略库 | `/api/factors` |
| `category_list` | List all categories in the registry. | `() -> 'list[str]'` | `list[str]` | 只读、诊断或本地计算 | 正式 | 因子与策略库 | `/api/factors` |
| `category_rename` | Rename a category. | `(old_name: 'str', new_name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 因子与策略库 | `/api/factors` |
| `factor_add` | Validate then add a factor; ``--categories=a,b`` assigns categories. | `(factor_name: 'str', expression: 'str', categories: 'Any' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 因子与策略库 | `/api/factors` |
| `factor_categorize` | Replace a factor's categories with ``--categories=a,b`` (creates missing ones). | `(factor_name: 'str', categories: 'Any' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 因子与策略库 | `/api/factors` |
| `factor_category_add` | Add one category to multiple factors without replacing existing categories. | `(factor_names: 'Any', category: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 因子与策略库 | `/api/factors` |
| `factor_category_remove` | Remove one category from multiple factors while preserving other categories. | `(factor_names: 'Any', category: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 破坏性/清理操作 | 正式 | 因子与策略库 | `/api/factors` |
| `factor_duplicates` | Report duplicate / near-duplicate factors in the zoo. | `(similarity_threshold: 'float' = 0.8) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 因子与策略库 | `/api/factors` |
| `factor_list` | List factors in the zoo, optionally filtered to a single ``--category``. | `(category: 'str \| None' = None) -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 因子与策略库 | `/api/factors` |
| `factor_rename` | Rename a factor in the zoo (expression and categories are preserved). | `(factor_name: 'str', new_name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 因子与策略库 | `/api/factors` |
| `factor_validate` | Validate a factor expression and print the rejection reason if any. | `(expression: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 因子与策略库 | `/api/factors` |

## AlphaForge AFF（`alphaforge_aff`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `mine_aff` | Mine a zoo of alpha factors with the AFF generator-predictor loop. | `(instruments: 'str' = 'csi300', train_end_year: 'int' = 2020, train_start_date: 'str \| None' = None, train_end_date: 'str \| None' = None, freq: 'str' = 'day', seed: 'int' = 0, zoo_size: 'int' = 100, corr_thresh: 'float' = 0.7, ic_thresh: 'float' = 0.03, icir_thresh: 'float' = 0.1, max_len: 'int' = 20, target_horizon: 'int' = 20, target_price: 'str' = 'vwap', vwap_mode: 'str' = 'amount_volume', device: 'str \| None' = None, qlib_dir: 'str \| None' = None, backtest: 'bool' = False, save: 'bool' = True, **kwargs: 'Any') -> 'dict[str, Any]'` | `dict[str, Any]` | 计算并写入产物 | 正式 | 因子挖掘 | `/api/jobs、/api/mining` |

## AlphaForge GP/RL（`alphaforge_search`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `mine_gp` | Mine factors via genetic programming (gplearn). | `(instruments: 'str' = 'csi300', train_end_year: 'int' = 2020, train_start_date: 'str \| None' = None, train_end_date: 'str \| None' = None, freq: 'str' = 'day', seed: 'int' = 0, population_size: 'int' = 1000, generations: 'int' = 40, target_horizon: 'int' = 20, target_price: 'str' = 'vwap', vwap_mode: 'str' = 'amount_volume', device: 'str \| None' = None, qlib_dir: 'str \| None' = None, backtest: 'bool' = False, save: 'bool' = True, **kwargs: 'Any') -> 'dict[str, Any]'` | `dict[str, Any]` | 计算并写入产物 | 正式 | 因子挖掘 | `/api/jobs、/api/mining` |
| `mine_rl` | Mine factors via PPO RL search (stable-baselines3 + sb3-contrib). | `(instruments: 'str' = 'csi300', train_end_year: 'int' = 2020, train_start_date: 'str \| None' = None, train_end_date: 'str \| None' = None, freq: 'str' = 'day', seed: 'int' = 0, steps: 'int' = 200000, pool_capacity: 'int' = 10, target_horizon: 'int' = 20, target_price: 'str' = 'vwap', vwap_mode: 'str' = 'amount_volume', campaign_id: 'str \| None' = None, research_hypothesis: 'str' = 'rl_symbolic_factor_search', device: 'str \| None' = None, qlib_dir: 'str \| None' = None, backtest: 'bool' = False, save: 'bool' = True, **kwargs: 'Any') -> 'dict[str, Any]'` | `dict[str, Any]` | 计算并写入产物 | 正式 | 因子挖掘 | `/api/jobs、/api/mining` |

## 股票池（`stock_pool`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `pool_add` | Batch-add stocks to an existing pool (deduped against current members). | `(name: 'str', symbols: 'Any' = None, stock_csv: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_create` | Create a stock pool from a CSV/TXT file and/or inline ``symbols``. | `(name: 'str', stock_csv: 'str \| None' = None, symbols: 'Any' = None, description: 'str' = '') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_delete` | Delete a pool (JSON + Qlib instruments). Use ``dry_run`` to preview. | `(name: 'str', dry_run: 'bool' = False) -> 'dict[str, Any]'` | `dict[str, Any]` | 破坏性/清理操作 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_export` | Export a pool's members to a CSV file at ``output``. | `(name: 'str', output: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_list` | List all stock pools with their member counts. | `() -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_remove` | Remove one or more stocks from a pool. | `(name: 'str', symbols: 'Any') -> 'dict[str, Any]'` | `dict[str, Any]` | 破坏性/清理操作 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_rename` | Rename a pool (moves both the JSON and the Qlib instruments file). | `(name: 'str', new_name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_save` | Create or overwrite a stock pool with the given members. | `(name: 'str', stock_csv: 'str \| None' = None, symbols: 'Any' = None, description: 'str' = '') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_set_description` | Update a pool's description without touching its members. | `(name: 'str', description: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 资源写操作 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |
| `pool_show` | Show a single pool's metadata and full member list. | `(name: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 行情数据 | `/api/modules/run (stock_pool)` |

## 策略资产复测（`strategy_backtest`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `strategy_backtest` | Retrain or evaluate a saved research strategy asset through Qlib. | `(strategy_name: 'str', qlib_data_dir: 'str \| None' = None, qlib_config_name: 'str \| None' = None, qlib_template_dir: 'str \| None' = None, mode: 'str' = 'retrain', scenario: 'str' = 'factor_backtest', use_local: 'bool \| None' = None, run_tag: 'str \| None' = None, save_as: 'str \| None' = None, **options: 'Any') -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 计算并写入产物 | 正式 | 回测 | `/api/jobs、/api/backtests` |
| `strategy_backtest_list` | List saved research strategy assets with compact model and metric status. | `() -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 回测 | `/api/jobs、/api/backtests` |
| `strategy_create` | Create a strategy asset from factor-zoo factors. | `(strategy_name: 'str', factor_names: 'Any', model_name: 'str \| None' = None, market: 'str \| None' = None, yaml_params: 'Any' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 研究资产写操作 | 正式 | 因子与策略库/回测 | `/api/strategies` |

## 交易运行时 CLI（`live`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `live_brokers` | List registered brokers: gateway, env fields for credentials, availability. | `(account_kind: 'str \| None' = None) -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_cancel` | Connect once and cancel one order. | `(order_id: 'str', symbol: 'str \| None' = None, force: 'bool' = False, mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, cash: 'float \| None' = None, timeout: 'float' = 20.0, event_timeout: 'float' = 3.0, ledger_dir: 'str \| None' = None, state_dir: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_connect` | Connect once, wait for readiness, persist state, then close. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, cash: 'float \| None' = None, timeout: 'float' = 20.0, ledger_dir: 'str \| None' = None, state_dir: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_cancel` | Ask the running daemon to cancel one active order. | `(order_id: 'str', symbol: 'str \| None' = None, force: 'bool' = False, mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, wait: 'bool' = False, timeout: 'float' = 5.0, event_timeout: 'float' = 3.0) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_halt` | Ask the running daemon to engage the in-process kill-switch. | `(reason: 'str' = 'manual', mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, wait: 'bool' = False, timeout: 'float' = 5.0) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_order` | Ask the running daemon to submit one manual/debug order. | `(symbol: 'str', side: 'str', volume: 'float', price: 'float' = 0.0, order_type: 'str' = 'limit', exchange: 'str \| None' = None, offset: 'str' = 'none', product: 'str' = 'equity', mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, wait: 'bool' = False, timeout: 'float' = 5.0, event_timeout: 'float' = 3.0, confirm_live: 'bool' = False, reference: 'str' = 'daemon_manual') -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_reconnect` | Ask the running daemon to reconnect and reconcile broker state. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, wait: 'bool' = False, timeout: 'float' = 20.0, auto_resume: 'bool' = False, confirm_live: 'bool' = False) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_refresh` | Ask the running daemon to re-query broker account and positions. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, wait: 'bool' = False, timeout: 'float' = 5.0) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_resume` | Ask the running daemon to resume after a kill-switch halt. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, wait: 'bool' = False, timeout: 'float' = 5.0) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_start` | Start a detached runtime without attaching an automated strategy. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, symbols: 'str \| list[str] \| None' = None, cash: 'float \| None' = None, interval: 'float' = 1.0, timeout: 'float' = 20.0, ledger_dir: 'str \| None' = None, state_dir: 'str \| None' = None, duration: 'float \| None' = None, record_market_data: 'bool \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_status` | Show the long-lived live runtime daemon status and latest state. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_stop` | Stop the detached live runtime daemon if one is running. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, timeout: 'float' = 5.0) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_submit_target` | Ask the running daemon to plan or route a target portfolio. | `(target_path: 'str \| None' = None, holdings: 'str \| dict \| None' = None, prices: 'str \| dict \| None' = None, positions: 'list[dict[str, Any]] \| None' = None, date: 'str \| None' = None, source: 'str \| None' = None, session: 'str \| None' = None, strategy_name: 'str \| None' = None, factor_path: 'str \| None' = None, model_pickle_path: 'str \| None' = None, yaml_params: 'str \| None' = None, refresh_data: 'bool' = False, route: 'bool' = False, mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, wait: 'bool' = False, timeout: 'float' = 5.0, confirm_live: 'bool' = False) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_daemon_subscribe` | Add display-only symbols to a running standalone daemon. | `(symbols: 'str \| list[str]', mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, wait: 'bool' = False, timeout: 'float' = 5.0) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_ledger_events` | Query live audit ledger events by common correlation fields. | `(kind: 'str \| None' = None, command_id: 'str \| None' = None, order_id: 'str \| None' = None, reference: 'str \| None' = None, day: 'str \| None' = None, limit: 'int' = 50, mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, ledger_dir: 'str \| None' = None, state_dir: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_market_bars` | Read recent persisted and current live bars for one subscribed symbol. | `(symbol: 'str', interval: 'int' = 60, limit: 'int' = 300, mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_market_snapshot` | Read the daemon's latest quote projection without touching a gateway. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, symbols: 'str \| list[str] \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_modes` | List modes (SHADOW uses real data/account but cannot route). | `() -> 'list[str]'` | `list[str]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_order` | Submit one manual/debug order through LiveEngine and RiskGate. | `(symbol: 'str', side: 'str', volume: 'float', price: 'float' = 0.0, order_type: 'str' = 'limit', exchange: 'str \| None' = None, offset: 'str' = 'none', product: 'str' = 'equity', mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, cash: 'float \| None' = None, timeout: 'float' = 20.0, event_timeout: 'float' = 3.0, ledger_dir: 'str \| None' = None, state_dir: 'str \| None' = None, confirm_live: 'bool' = False, reference: 'str' = 'manual') -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |
| `live_plugins` | Show installed live plugin versions and isolated discovery failures. | `() -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_preflight` | Check broker registry, env fields and optional TCP endpoint reachability. | `(broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, network: 'bool' = False, timeout: 'float' = 3.0) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_quote_providers` | List registered quote providers without exposing secret values. | `(data_kind: 'str \| None' = None) -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_risk_status` | Show persisted risk/recovery status without connecting to a broker. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None, ledger_dir: 'str \| None' = None, tail: 'int' = 20) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_run` | Run a connected live runtime loop and keep writing state snapshots. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, symbols: 'str \| list[str] \| None' = None, cash: 'float \| None' = None, interval: 'float' = 2.0, duration: 'float \| None' = None, timeout: 'float' = 20.0, ledger_dir: 'str \| None' = None, state_dir: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 长运行进程 | 正式 | 模拟与实盘 | `/api/live` |
| `live_state` | Read the last persisted live runtime state without connecting. | `(mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, state_dir: 'str \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_status` | Show the resolved live config (mode, broker, risk limits) — no secrets. | `() -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 模拟与实盘 | `/api/live` |
| `live_submit_target` | Plan or route a target portfolio through the live executor. | `(target_path: 'str \| None' = None, holdings: 'str \| dict \| None' = None, prices: 'str \| dict \| None' = None, positions: 'list[dict[str, Any]] \| None' = None, date: 'str \| None' = None, source: 'str \| None' = None, session: 'str \| None' = None, strategy_name: 'str \| None' = None, factor_path: 'str \| None' = None, model_pickle_path: 'str \| None' = None, yaml_params: 'str \| None' = None, refresh_data: 'bool' = False, route: 'bool' = False, mode: 'str \| None' = None, broker: 'str \| None' = None, trade_broker: 'str \| None' = None, quote_provider: 'str \| None' = None, cash: 'float \| None' = None, timeout: 'float' = 20.0, ledger_dir: 'str \| None' = None, state_dir: 'str \| None' = None, confirm_live: 'bool' = False) -> 'dict[str, Any]'` | `dict[str, Any]` | 交易/运行时写操作 | 正式 | 模拟与实盘 | `/api/live` |

## 策略实例与部署 CLI（`trading_cli`）

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `trading_audit` | List recent operator audit events with sensitive account data redacted. | `(limit: 'int' = 200) -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_backtest` | Start an asynchronous unified replay, optionally waiting for completion. | `(instance_id: 'str', options: 'Any' = None, wait: 'bool' = False, output_dir: 'str' = '') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_backtest_cancel` | Request cancellation of a queued or running unified replay. | `(run_id: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_backtest_status` | Read a unified replay run, optionally including full artifacts. | `(run_id: 'str', detail: 'bool' = False) -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_broker_uat_abort` | Abort a broker UAT while preserving callback and cleanup evidence. | `(run_id: 'str', confirmation: 'str', reason: 'str', operator_id: 'str' = 'local-cli') -> 'dict[str, Any]'` | `dict[str, Any]` | 本地受控券商 UAT | 仅本地 UAT | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_broker_uat_preflight` | Run the local, query-only broker readiness and candidate scan. | `(broker: 'str', symbols: 'str \| list[str] \| None' = None, max_notional: 'float' = 20000.0, timeout: 'float' = 30.0) -> 'dict[str, Any]'` | `dict[str, Any]` | 本地受控券商 UAT | 仅本地 UAT | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_broker_uat_resume` | Resume an interrupted broker UAT after local diagnosis and confirmation. | `(run_id: 'str', confirmation: 'str', timeout: 'float' = 30.0, operator_id: 'str' = 'local-cli', reason: 'str' = 'resume broker UAT after diagnosed failure') -> 'dict[str, Any]'` | `dict[str, Any]` | 本地受控券商 UAT | 仅本地 UAT | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_broker_uat_start` | Start a bounded, callback-derived real-broker UAT scenario. | `(broker: 'str', symbol: 'str', side: 'str', volume: 'float', price: 'float', max_notional: 'float', confirmation: 'str', timeout: 'float' = 30.0, operator_id: 'str' = 'local-cli', reason: 'str' = 'bounded real-broker UAT') -> 'dict[str, Any]'` | `dict[str, Any]` | 本地受控券商 UAT | 仅本地 UAT | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_broker_uat_status` | Show one broker UAT run or list runs, optionally filtered by broker. | `(run_id: 'str' = '', broker: 'str' = '') -> 'Any'` | `Any` | 本地受控券商 UAT | 仅本地 UAT | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_compatibility` | Inspect, set or exchange legacy-entrypoint migration cutoff reports. | `(set_cutoff: 'bool' = False, export_path: 'str' = '', import_path: 'str' = '') -> 'dict[str, Any]'` | `dict[str, Any]` | 兼容审计（可选写入 cutoff/报告） | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_decision_compare` | Compare persisted decisions from any two replay/deployment runs. | `(instance_id: 'str', left_mode: 'str', left_run_id: 'str', right_mode: 'str', right_run_id: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 诊断写入 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_decision_comparisons` | Read one decision comparison or list comparisons for an instance. | `(instance_id: 'str', comparison_id: 'str' = '') -> 'Any'` | `Any` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_definitions` | List installed strategy definitions and their parameter contracts. | `() -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_deploy` | Configure or replace an independent deployment while its daemon is stopped. | `(instance_id: 'str', run_mode: 'str', trade_provider: 'str' = '', quote_provider: 'str' = '', account_profile: 'str' = '', account_id: 'str' = '', reason: 'str' = '') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_deployment_subscribe` | Add display-only symbols to a running isolated deployment daemon. | `(instance_id: 'str', symbols: 'Any') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_deployments` | List independent strategy deployment configurations and runtime state. | `() -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_diagnostics` | Read neutral runtime diagnostics; results never change deployment authority. | `(instance_id: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_instance_create` | Create a strategy instance from a registered definition. | `(instance_id: 'str', strategy_id: 'str', universe: 'Any', params: 'Any' = None, frequency: 'str' = 'day', data_policy: 'Any' = None, portfolio_policy: 'Any' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_instance_from_research` | Snapshot a saved research asset into a deployable selection instance. | `(instance_id: 'str', strategy_name: 'str', universe: 'Any' = None, portfolio_policy: 'Any' = None, risk_policy: 'Any' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_instance_validate` | Validate one strategy instance, artifact, data policy and parameters. | `(instance_id: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_instances` | List persisted strategy instances and their lifecycle state. | `() -> 'list[dict[str, Any]]'` | `list[dict[str, Any]]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_kill_switch` | Engage or release an instance, account or global kill switch. | `(scope_type: 'str', scope_id: 'str', active: 'bool', reason: 'str', operator_id: 'str' = 'local-cli') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_operator_token` | Create a local operator token; its plaintext is returned only once. | `(operator_id: 'str', label: 'str' = '', expires_in_days: 'int \| None' = None) -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_pause` | Pause new decisions and request cancellation of instance orders. | `(instance_id: 'str', operator_id: 'str' = 'local-cli', reason: 'str' = 'CLI pause') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_policies` | List installed portfolio-policy definitions and parameter contracts. | `() -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_preview` | Evaluate one instance and optionally export its signal as JSON or CSV. | `(instance_id: 'str', options: 'Any' = None, output_path: 'str' = '', output_format: 'str' = 'json') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_reconcile` | Reconcile runtime state with broker account, orders and fills. | `(instance_id: 'str', operator_id: 'str' = 'local-cli', reason: 'str' = 'CLI reconcile') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_removal_check` | Evaluate the auditable legacy-entrypoint removal qualification report. | `(acceptance_instance_id: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_resume` | Resume a reconciled deployment after an explicit operator action. | `(instance_id: 'str', operator_id: 'str' = 'local-cli', reason: 'str' = 'CLI resume') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_start` | Start the deployment runtime for a persisted strategy instance. | `(instance_id: 'str', operator_id: 'str' = 'local-cli', reason: 'str' = 'CLI start') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_status` | Show desired/observed deployment, heartbeat and reconciliation status. | `(instance_id: 'str') -> 'dict[str, Any]'` | `dict[str, Any]` | 只读、诊断或本地计算 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |
| `trading_stop` | Stop a deployment and revoke its automated routing authority. | `(instance_id: 'str', operator_id: 'str' = 'local-cli', reason: 'str' = 'CLI stop') -> 'dict[str, Any]'` | `dict[str, Any]` | 策略或部署写操作 | 正式 | 策略实例/模拟与实盘 | `/api/trading` |

## 已弃用命令附录

这些命令仍计入 120 个公共命令，但只输出迁移提示，不应由新脚本继续采用。

| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |
|---|---|---|---|---|---|---|---|
| `ui` | Deprecated: use ``alphapilot portal`` → Mining Log tab. | `(port: 'int' = 19899, log_dir: 'str' = './log', debug: 'bool' = False) -> 'None'` | `None` | 仅输出迁移提示 | 已弃用 | 首页/高级设置 | `/api/portal、/api/modules、/api/logs` |
| `backtest_ui` | Deprecated: use ``alphapilot portal`` → Backtest → Backtest Detail tab. | `(port: 'int' = 19900, workspace_root: 'str \| None' = None, log_dir: 'str' = './log') -> 'None'` | `None` | 仅输出迁移提示 | 已弃用 | 首页/高级设置 | `/api/portal、/api/modules、/api/logs` |

## 已移除命令（不可用）

以下命令不再注册，也不应由脚本或自动化调用：

- `trading_stage_start`
- `trading_stage_finish`
- `trading_stage_evaluate`
- `trading_promote`
- `trading_authorize_live`
- `trading_qualification`
- `trading_parity_start`
- `trading_parity_status`
- `trading_bind_execution`
- `trading_execution_binding`
- `timing_strategies`
- `timing_signal`
- `timing_backtest`
- `live_daemon_strategy_status`
- `live_daemon_strategy_start`
- `live_daemon_strategy_pause`
- `live_daemon_strategy_resume`
- `live_daemon_strategy_stop`
