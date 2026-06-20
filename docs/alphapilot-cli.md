# AlphaPilot CLI 命令参考

本文档列出 **AlphaPilot 项目**（`alphapilot/` 包）的全部命令行入口与用法。项目根目录下的 `AlphaForge/`、`openclawa/` **不属于**本仓库代码，不在本文档范围内。

---

## 目录

- [概述](#概述)
- [命令速查表](#命令速查表)
- [通用约定](#通用约定)
- [因子挖掘（LLM）](#因子挖掘llm)
- [数据准备与单股维护](#数据准备与单股维护)
- [Web 界面与调度](#web-界面与调度)
- [Qlib YAML](#qlib-yaml)
- [回测系统设计文档](alphapilot-backtest.md)（`backtest` / 组合 vs 单因子语义）
- [因子库管理](#因子库管理)
- [日频交易信号](#日频交易信号)
- [策略复测](#策略复测)
- [AlphaForge 非 LLM 挖掘](#alphaforge-非-llm-挖掘)
- [可选依赖与弃用命令](#可选依赖与弃用命令)
- [附录：内部脚本](#附录内部脚本)

---

## 概述

### 安装与入口

安装本项目后，命令行入口为：

```bash
alphapilot <command> [flags]
```

- 注册位置：[`pyproject.toml`](../pyproject.toml) → `alphapilot = "alphapilot.app.cli:app"`
- 实现：[`alphapilot/app/cli.py`](../alphapilot/app/cli.py)
- 启动时自动加载**当前工作目录**下的 `.env`（需 `python-dotenv`）

### 架构

CLI 使用 **Google Fire** 框架。各可插拔模块通过 `commands()` 向内核注册命令，`MainEngine.collect_commands()` 合并为**扁平**顶层命令（无 `alphapilot portal start` 这类嵌套子命令）。

```
pyproject.toml → app/cli.py → build_engine() → Module.commands() → fire.Fire(commands)
```

- **Systems 层**（`data` / `factor` / `strategy` / `backtest` / `notify`）不直接暴露 CLI，由 modules 调用
- **Modules 层**通过 `pyproject.toml` 的 `[project.entry-points."alphapilot.modules"]` 或内核内置注册贡献命令
- 第三方包可注册新 module，其 `commands()` 会自动出现在 CLI 中

### 发现已加载命令

```bash
alphapilot modules
```

输出示例（模块名 → 命令列表）：

```
alpha_mining:      ["backtest", "delete_mine_log", "list_mine_logs", "mine"]
platform:          ["backtest_ui", "delete_stock", "list_stocks", "modules", "prepare_data", ...]
portal:            ["portal", "scheduler"]
daily_trade:     ["daily_signals", "daily_state"]
factor:            ["category_create", "category_delete", "category_list", "factor_add", "factor_list", ...]
...
```

---

## 命令速查表

共 **36** 条顶层命令（含 2 条已弃用）：

| # | 命令 | 模块 | 用途 |
|---|------|------|------|
| 1 | `mine` | alpha_mining | LLM 自动因子挖掘主流程 |
| 2 | `backtest` | alpha_mining | 因子 CSV 回测（默认 combined + LGBM，见 [alphapilot-backtest.md](alphapilot-backtest.md)） |
| 3 | `list_mine_logs` | alpha_mining | 列出挖掘日志会话 |
| 4 | `delete_mine_log` | alpha_mining | 删除挖掘日志会话 |
| 5 | `prepare_data` | platform | 数据下载 / 复权 / Qlib 转换 / h5 |
| 6 | `list_stocks` | platform | 列出本地已下载股票 |
| 7 | `delete_stock` | platform | 删除单只股票数据 |
| 8 | `trim_stock` | platform | 裁剪单股 CSV 日期范围 |
| 9 | `refresh_stock` | platform | 增量重下并同步 Qlib |
| 10 | `ui` | platform | **已弃用** → 用 `portal` |
| 11 | `backtest_ui` | platform | **已弃用** → 用 `portal` |
| 12 | `modules` | platform | 列出已加载模块与命令 |
| 13 | `portal` | portal | 统一 Streamlit Web 门户 |
| 14 | `scheduler` | portal | 定时任务守护进程 |
| 15 | `data_viz` | data_viz | K 线 Streamlit 查看器 |
| 16 | `backtest_viz` | backtest_viz | 回测结果 Streamlit 查看器 |
| 17 | `qlib_yaml_generate` | qlib_yaml | 生成 qlib qrun YAML |
| 18 | `qlib_yaml_validate` | qlib_yaml | 校验 qlib qrun YAML |
| 19 | `factor_validate` | factor | 校验因子表达式 |
| 20 | `factor_add` | factor | 校验并添加因子到 zoo |
| 21 | `factor_list` | factor | 列出 factor zoo 中的因子 |
| 22 | `factor_categorize` | factor | 设置因子的分类标签 |
| 23 | `factor_category_add` | factor | 为多个因子追加同一分类 |
| 24 | `factor_category_remove` | factor | 从多个因子移除某一分类 |
| 25 | `category_list` | factor | 列出所有分类名 |
| 26 | `category_create` | factor | 创建空分类 |
| 27 | `category_rename` | factor | 重命名分类 |
| 28 | `category_delete` | factor | 删除分类（因子保留） |
| 29 | `daily_signals` | daily_trade | 生成单日调仓/持仓信号 |
| 30 | `daily_state` | daily_trade | 查看滚动持仓状态 JSON |
| 31 | `mine_aff` | alphaforge_aff | GAN 式公式化因子挖掘 |
| 32 | `mine_gp` | alphaforge_search | 遗传编程因子挖掘 |
| 33 | `mine_rl` | alphaforge_search | PPO RL 因子挖掘 |
| 34 | `mine_dso` | alphaforge_search | 深度符号优化因子挖掘 |
| 35 | `strategy_backtest` | strategy_backtest | 从 strategy_zoo 复测策略 |
| 36 | `strategy_backtest_list` | strategy_backtest | 列出已保存策略资产 |

> **模块名说明**：`alphapilot modules` 输出中的模块名来自各类的 `name` 属性（如 `factor`），与 `pyproject.toml` entry-point 键名（如 `factor_cli`）可能不同，但 CLI 顶层命令名一致。

---

## 通用约定

### 查看帮助

Fire 对带默认参数的命令，`--help` 可能触发实际执行。推荐写法：

```bash
alphapilot <command> -- --help
```

示例：

```bash
alphapilot mine -- --help
alphapilot prepare_data -- --help
```

### 参数风格

- 布尔：`--backtest=True` / `--dry_run=True`
- 位置参数可用 flags：`alphapilot delete_stock --symbol=sz.300001`
- `prepare_data` 接受额外 `**options`，会透传给底层 `PrepareDataCLI`（如 `--source=tushare_cn`、`--max_workers=4`）

### 运行目录

请在 **项目根目录** 执行命令，确保 `.env` 与相对路径（股票列表、日志目录等）正确解析。

---

## 因子挖掘（LLM）

源文件：[`alphapilot/modules/alpha_mining/module.py`](../alphapilot/modules/alpha_mining/module.py)

### `alphapilot mine`

运行 LLM 驱动的自动因子挖掘循环（Idea → Factor → Eval）。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--path` | str | None | 从已有会话路径恢复（不传则新建） |
| `--step_n` | int | None | 限制迭代步数 |
| `--direction` | str | None | 初始挖掘方向 |
| `--scenario` | str | `alpha_factor_mining` | 场景名（决定 loop 类与 prop setting） |
| `--qlib_config_name` | str | None | Qlib 配置 yaml 名 |
| `--qlib_template_dir` | str | None | Qlib 模板目录 |

```bash
# 新建会话，跑 3 轮
alphapilot mine --step_n=3

# 从已有日志恢复
alphapilot mine --path=./log/20260101_120000

# 指定 Qlib 配置
alphapilot mine --qlib_config_name=conf_cn_combined_kdd_ver.yaml
```

Qlib 配置优先级见 [README.md](../README.md)：`mine` 默认读取 `.env` 中 `QLIB_FACTOR_QLIB_CONFIG_NAME`。

### `alphapilot backtest`

对已有因子 CSV 做单次 Qlib 回测（默认 **多因子合并 + LGBM 组合回测**，非逐因子独立回测；详见 [回测系统设计文档](alphapilot-backtest.md)）。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--factor_path` | str | **必填** | 因子 CSV 路径 |
| `--scenario` | str | `factor_backtest` | 回测场景 |
| `--qlib_config_name` | str | None | Qlib 配置 yaml 名 |
| `--qlib_template_dir` | str | None | Qlib 模板目录 |
| `--path` | str | — | **已不支持**（会抛 `NotImplementedError`） |

```bash
alphapilot backtest --factor_path=./path/to/factor.csv
```

### `alphapilot list_mine_logs`

列出配置日志根目录（`.env` / `AppConfig` 中的 `log_dir`）下的挖掘会话文件夹名。无参数。

```bash
alphapilot list_mine_logs
```

### `alphapilot delete_mine_log`

删除指定挖掘日志会话目录。

| 参数 | 类型 | 说明 |
|------|------|------|
| `session` | str | 会话文件夹名（相对 log 根目录） |

```bash
alphapilot delete_mine_log --session=20260101_120000
```

---

## 数据准备与单股维护

源文件：[`alphapilot/modules/platform/module.py`](../alphapilot/modules/platform/module.py)  
底层实现：[`alphapilot/systems/data/`](../alphapilot/systems/data/)

### `alphapilot prepare_data`

通过 data system 执行数据准备 action。两种等价调用风格：

```bash
# 风格 A：显式 action 参数
alphapilot prepare_data --action=download --stock_csv=important_data/stock_lists/main_stock_2026_4_27.csv

# 风格 B：Fire 子命令风格（action 作为第一个 positional）
alphapilot prepare_data download --stock_csv=important_data/stock_lists/main_stock_2026_4_27.csv
```

#### 通用参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--action` | `pipeline` | 见下表 |
| `--start_date` | `2015-01-01` | 下载/回测起始日期 |
| `--end_date` | None | 结束日期（默认今天） |
| `--stock_csv` | None | 股票池 CSV 路径 |
| `--adjust_mode` | `backward` | 复权模式：`none` / `forward` / `backward` |
| `--parallel_price_factor` | `False` | 仅 `adjust_mode=none` 时生效；将除权行情和复权因子分独立进程并行下载，默认关闭以避免限流 |
| `--market` | None | 市场/股票池名 |
| `--qlib_dir` | None | Qlib 二进制目录 |
| `--output_dir` | None | 输出目录 |

#### action 一览

| action | 作用 |
|--------|------|
| `pipeline` | 下载 → 复权 → 转 Qlib（**默认**） |
| `download` | 仅下载行情 CSV（支持 baostock / tushare 等，通过 `--source` 指定） |
| `convert` | CSV → Qlib 二进制 + 日历 + 基准 + h5 |
| `build_h5` | 构建 `daily_pv.h5` |
| `refresh_factors` | 刷新复权因子 |
| `apply_adjust` | 对本地 CSV 应用复权 |
| `dump` | 仅 CSV → Qlib dump |
| `calendar` | 扩展 Qlib 交易日历 |
| `h5` | 从 Qlib 导出因子代码用的 h5 |

#### 常用示例

```bash
# 完整流水线（默认股票列表）
alphapilot prepare_data

# baostock 下载
alphapilot prepare_data download \
  --stock_csv=important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode=backward

# 除权行情 + 复权因子并行下载（实验性，默认关闭）
alphapilot prepare_data download \
  --stock_csv=important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode=none \
  --parallel_price_factor=True

# Tushare 数据源
TUSHARE_TOKEN=你的token alphapilot prepare_data --action=download \
  --source=tushare_cn \
  --stock_csv=important_data/stock_lists/main_stock_2026_4_27.csv

# 仅转 Qlib + 生成 h5
alphapilot prepare_data convert --adjust_mode=forward

# 重建因子 h5
alphapilot prepare_data h5 --market=main_stock_2026_4_27
```

各 action 的额外参数（如 `--max_workers`、`--source`、`--all_market`）见 [`systems/data/prepare_data.py`](../alphapilot/systems/data/prepare_data.py) 中 `PrepareDataCLI` 方法签名；通过 `prepare_data` 的 `**options` 透传。

### `alphapilot list_stocks`

列出本地已下载的股票代码。

| 参数 | 默认 | 说明 |
|------|------|------|
| `--adjust_mode` | None | 可选，按复权模式过滤 |

```bash
alphapilot list_stocks
alphapilot list_stocks --adjust_mode=backward
```

### `alphapilot delete_stock`

删除单只股票在各处的数据（原始 CSV、复权因子、Qlib features、instruments）。

| 参数 | 默认 | 说明 |
|------|------|------|
| `symbol` | **必填** | 股票代码，如 `sz.300001` |
| `--adjust_mode` | `all` | `all` 或具体复权模式 |
| `--dry_run` | False | 仅预览，不实际删除 |

```bash
alphapilot delete_stock --symbol=sz.300001
alphapilot delete_stock --symbol=sz.300001 --dry_run=True
```

删除后如需 h5，请运行 `alphapilot prepare_data h5`。

### `alphapilot trim_stock`

裁剪单股 CSV 到指定日期范围，并可选重 dump Qlib。

| 参数 | 默认 | 说明 |
|------|------|------|
| `symbol` | **必填** | 股票代码 |
| `--adjust_mode` | `all` | 复权模式 |
| `--start_date` | None | 保留区间起点 |
| `--end_date` | None | 保留区间终点 |
| `--drop_dates` | None | 要删除的日期列表 |
| `--qlib_adjust_mode` | `backward` | Qlib 同步使用的复权模式 |
| `--resync_qlib` | True | 是否重 dump 该 symbol 的 Qlib 二进制 |
| `--rebuild_h5` | False | 是否重建 daily_pv h5 |
| `--market` | None | h5 重建时的 market |
| `--dry_run` | False | 预览模式 |

```bash
alphapilot trim_stock --symbol=sz.300001 --start_date=2020-01-01 --end_date=2025-12-31
```

### `alphapilot refresh_stock`

增量重下载单股并同步 Qlib 二进制。

| 参数 | 默认 | 说明 |
|------|------|------|
| `symbol` | **必填** | 股票代码 |
| `--adjust_mode` | `backward` | 下载复权模式 |
| `--start_date` | `2016-12-31` | 增量起点 |
| `--end_date` | None | 结束日期 |
| `--qlib_adjust_mode` | `backward` | Qlib 同步复权模式 |
| `--resync_qlib` | True | 是否重 dump Qlib |
| `--rebuild_h5` | False | 是否重建 h5 |
| `--market` | None | h5 重建 market |

```bash
alphapilot refresh_stock --symbol=sz.300001
```

### `alphapilot modules`

列出当前引擎已加载的模块及其 CLI 命令名。无参数。

```bash
alphapilot modules
```

---

## Web 界面与调度

### `alphapilot portal`

启动统一 Streamlit Web 门户（数据、因子、策略、回测、挖掘日志、K 线等）。

| 参数 | 默认 | 说明 |
|------|------|------|
| `--port` | `19901` | 监听端口 |
| `--host` | `0.0.0.0` | 监听地址 |

```bash
alphapilot portal
alphapilot portal --port=19901 --host=127.0.0.1
# 浏览器打开 http://localhost:19901
```

源文件：[`alphapilot/modules/portal/app.py`](../alphapilot/modules/portal/app.py)

### `alphapilot scheduler`

运行定时任务守护进程，自动触发 portal 中保存的数据/挖掘/回测调度。

| 参数 | 默认 | 说明 |
|------|------|------|
| `--interval` | `30` | 轮询间隔（秒） |

```bash
alphapilot scheduler --interval=30
```

### `alphapilot data_viz`

独立 K 线 Streamlit 查看器（portal 中亦可用）。

| 参数 | 默认 |
|------|------|
| `--port` | `19902` |
| `--host` | `0.0.0.0` |

```bash
alphapilot data_viz --port=19902
```

### `alphapilot backtest_viz`

独立回测结果 Streamlit 查看器（portal「回测详情」亦可用）。

| 参数 | 默认 |
|------|------|
| `--port` | `19903` |
| `--host` | `0.0.0.0` |

```bash
alphapilot backtest_viz --port=19903
```

---

## Qlib YAML

源文件：[`alphapilot/modules/qlib_yaml/module.py`](../alphapilot/modules/qlib_yaml/module.py)  
实现：[`alphapilot/systems/backtest/qlib_yaml/`](../alphapilot/systems/backtest/qlib_yaml/)

### `alphapilot qlib_yaml_generate`

从结构化参数（+ 可选 LLM 自然语言）生成 qlib qrun YAML。

| 参数 | 默认 | 说明 |
|------|------|------|
| `output` | **必填** | 输出 yaml 路径 |
| `--template` | `baseline` | `baseline` 或 `combined` |
| `--prompt` | None | LLM 自然语言补丁 |
| `--params_file` | None | JSON 参数补丁文件 |
| `--market` | None | 股票池 |
| `--benchmark` | None | 基准指数 |
| `--topk` | None | 持仓数量 |
| `--backtest_start/end` | None | 回测区间 |
| `--test_start/end` | None | 测试区间 |
| `--learning_rate` | None | 模型学习率 |
| `--provider_uri` | None | Qlib 数据目录 |
| `--workspace` | None | 冒烟测试 workspace |
| `--skip_smoke` | False | 跳过 Qlib handler 冒烟 |
| `--smoke_timeout` | `120` | 冒烟超时（秒） |
| `--copy_helpers` | False | 复制 combined 模板辅助文件 |

```bash
alphapilot qlib_yaml_generate \
  --output=important_data/factor_qlib_templates/my_conf.yaml \
  --template=baseline \
  --topk=20

alphapilot qlib_yaml_generate \
  --output=important_data/factor_qlib_templates/my_conf.yaml \
  --template=combined \
  --params_file=my_params.json \
  --prompt="回测区间改到2025年底，topk改为20" \
  --copy_helpers=True
```

校验失败时 exit code 为 1。

### `alphapilot qlib_yaml_validate`

校验已有 qlib qrun YAML。

| 参数 | 默认 | 说明 |
|------|------|------|
| `config` | **必填** | yaml 路径 |
| `--workspace` | None | combined 模板 workspace |
| `--skip_smoke` | False | 跳过冒烟 |
| `--smoke_timeout` | `120` | 冒烟超时 |

```bash
alphapilot qlib_yaml_validate \
  --config=important_data/factor_qlib_templates/conf.yaml \
  --skip_smoke=True
```

---

## 因子库管理

源文件：[`alphapilot/modules/factor/module.py`](../alphapilot/modules/factor/module.py)
底层实现：[`alphapilot/systems/factor/`](../alphapilot/systems/factor/)

### `alphapilot factor_validate`

校验因子表达式是否符合 DSL 与 zoo 规则。校验失败 exit code 为 1。

| 参数 | 说明 |
|------|------|
| `expression` | **必填**，因子表达式字符串 |

```bash
alphapilot factor_validate --expression="Rank(Close, 20)"
```

### `alphapilot factor_add`

校验通过后，将因子添加到 factor zoo。可选同时指定分类。

| 参数 | 说明 |
|------|------|
| `factor_name` | **必填**，因子名 |
| `expression` | **必填**，因子表达式 |
| `--categories` | 可选，逗号分隔的分类名（如 `momentum,value`）；不存在的分类会自动创建 |

```bash
alphapilot factor_add --factor_name=my_factor --expression="Rank(Close, 20)"
alphapilot factor_add --factor_name=my_factor --expression="Rank(Close, 20)" --categories=momentum,alpha158
```

### `alphapilot factor_list`

列出 factor zoo 中的因子；可按分类过滤。

| 参数 | 说明 |
|------|------|
| `--category` | 可选，只显示属于该分类的因子 |

```bash
alphapilot factor_list
alphapilot factor_list --category=momentum
```

### `alphapilot factor_categorize`

**替换**指定因子的全部分类（不会保留旧分类）。

| 参数 | 说明 |
|------|------|
| `factor_name` | **必填** |
| `--categories` | 逗号分隔的新分类列表；传空则清空分类 |

```bash
alphapilot factor_categorize --factor_name=my_factor --categories=momentum,short_term
```

### `alphapilot factor_category_add`

为多个因子**追加**同一分类（保留原有分类）。

| 参数 | 说明 |
|------|------|
| `factor_names` | **必填**，逗号分隔的因子名 |
| `category` | **必填**，要追加的分类名 |

```bash
alphapilot factor_category_add --factor_names=f1,f2 --category=value
```

### `alphapilot factor_category_remove`

从多个因子中**移除**某一分类（其它分类保留）。

| 参数 | 说明 |
|------|------|
| `factor_names` | **必填**，逗号分隔的因子名 |
| `category` | **必填**，要移除的分类名 |

```bash
alphapilot factor_category_remove --factor_names=f1,f2 --category=value
```

### `alphapilot category_list`

列出因子库中已注册的全部分类名。无参数。

```bash
alphapilot category_list
```

### `alphapilot category_create`

创建空分类（尚无因子归属也可先建）。

| 参数 | 说明 |
|------|------|
| `name` | **必填**，分类名 |

```bash
alphapilot category_create --name=momentum
```

### `alphapilot category_rename`

重命名分类；已归属该分类的因子会自动更新。

| 参数 | 说明 |
|------|------|
| `old_name` | **必填** |
| `new_name` | **必填** |

```bash
alphapilot category_rename --old_name=mom --new_name=momentum
```

### `alphapilot category_delete`

删除分类；**因子本身保留**，仅移除分类归属。

| 参数 | 说明 |
|------|------|
| `name` | **必填**，分类名 |

```bash
alphapilot category_delete --name=deprecated_cat
```

---

## 日频交易信号

源文件：[`alphapilot/modules/daily_trade/module.py`](../alphapilot/modules/daily_trade/module.py)
底层实现：[`alphapilot/systems/backtest/live/`](../alphapilot/systems/backtest/live/)

在已有策略资产（或手动指定因子 CSV + 模型 pkl）的前提下，根据**上一日收盘后的现金与持仓**，生成**指定交易日**的目标调仓与持仓，并自动滚动 JSON 状态文件。走 qlib **单日** `backtest` + 静态模型打分，**不是**整段历史 `qrun` 重跑。

状态文件默认路径：`git_ignore_folder/portfolio_state/<策略名>.json`

Portal 等价入口：**自动化 → 每日交易**（后台 job 类型 `daily_signals`）。

### `alphapilot daily_state`

查看当前保存的持仓状态。

| 参数 | 说明 |
|------|------|
| `--strategy_name` | 策略名（用于推导默认 state 路径） |
| `--state_path` | 可选，直接指定 state JSON 路径 |

```bash
alphapilot daily_state --strategy_name='mine_round_01_...'
alphapilot daily_state --state_path=git_ignore_folder/portfolio_state/my_run.json
```

### `alphapilot daily_signals`

生成指定交易日的买卖计划与目标持仓。

| 参数 | 默认 | 说明 |
|------|------|------|
| `--strategy_name` | None | strategy_zoo 中的策略名（与手动参数二选一或组合） |
| `--factor_path` | None | 因子 CSV 路径 |
| `--model_pickle_path` | None | 已训练模型 `fitted_model.pkl` |
| `--yaml_params` | None | 回测 yaml 补丁：JSON 字符串、`.json`/`.yaml` 文件路径或 dict |
| `--date` | None | 目标交易日（默认最近交易日） |
| `--state_path` | None | 持仓状态 JSON（默认按策略名推导） |
| `--init_cash` | None | 首次运行、无状态文件时的初始资金 |
| `--refresh_data` | False | 生成信号前是否增量刷新行情 |
| `--qlib_template_dir` | None | Qlib 模板目录 |

```bash
# 从 strategy_zoo 资产（推荐）
alphapilot daily_signals --strategy_name='mine_round_01_...'

# 首次运行指定初始资金
alphapilot daily_signals --strategy_name='mine_round_01_...' --init_cash=500000

# 指定日期并先刷新行情
alphapilot daily_signals \
  --strategy_name='mine_round_01_...' \
  --date=2026-06-18 \
  --refresh_data=True

# 手动指定模型与 yaml 补丁（不依赖 strategy_zoo）
alphapilot daily_signals \
  --factor_path=./factors.csv \
  --model_pickle_path=important_data/strategy_zoo/.../artifacts/fitted_model.pkl \
  --yaml_params='{"topk": 15, "n_drop": 5}'
```

输出包含：当日买卖列表、目标持仓、Top 模型打分摘要；状态 JSON 含 `date`、`cash`、`positions`。

---

## 策略复测

源文件：[`alphapilot/modules/strategy_backtest/module.py`](../alphapilot/modules/strategy_backtest/module.py)  
策略资产目录：`important_data/strategy_zoo/`

### `alphapilot strategy_backtest`

从已保存的策略资产运行 Qlib 回测。

| 参数 | 默认 | 说明 |
|------|------|------|
| `strategy_name` | **必填** | strategy_zoo 中的策略名 |
| `--mode` | `retrain` | `retrain` 或 `reuse_model` |
| `--qlib_config_name` | None | Qlib 配置 yaml |
| `--qlib_template_dir` | None | Qlib 模板目录 |
| `--qlib_data_dir` | None | Qlib 数据目录 |
| `--scenario` | `factor_backtest` | 回测场景 |
| `--use_local` | None | 是否本地 pickle 缓存 |
| `--run_tag` | None | 运行标签 |

```bash
alphapilot strategy_backtest --strategy_name=my_strategy --mode=retrain
alphapilot strategy_backtest --strategy_name=my_strategy --mode=reuse_model
```

### `alphapilot strategy_backtest_list`

列出 strategy_zoo 中已保存策略及 IC/ICIR 等指标摘要。无参数。

```bash
alphapilot strategy_backtest_list
```

---

## AlphaForge 非 LLM 挖掘

这些命令使用 vendored AlphaForge 引擎（[`alphapilot/modules/alphaforge/`](../alphapilot/modules/alphaforge/)），**不依赖 LLM**。挖掘结果会翻译为 alphapilot DSL，校验后可入库并可选回测。

### `alphapilot mine_aff`

GAN 式（AFF）公式化因子挖掘。

源文件：[`alphapilot/modules/alphaforge_aff/module.py`](../alphapilot/modules/alphaforge_aff/module.py)

| 参数 | 默认 | 说明 |
|------|------|------|
| `--instruments` | `csi300` | 股票池 |
| `--train_end_year` | `2020` | 训练截止年 |
| `--freq` | `day` | 频率 |
| `--seed` | `0` | 随机种子 |
| `--zoo_size` | `100` | 因子池大小 |
| `--corr_thresh` | `0.7` | 相关性阈值 |
| `--ic_thresh` | `0.03` | IC 阈值 |
| `--icir_thresh` | `0.1` | ICIR 阈值 |
| `--max_len` | `20` | 表达式最大长度 |
| `--device` | None | `cpu` / `cuda` 等 |
| `--qlib_dir` | None | Qlib 数据目录 |
| `--backtest` | False | 挖掘后是否回测 |
| `--save` | True | 是否写入 factor zoo |

额外训练参数（`batch_size`、`num_epochs_g`、`num_epochs_p`、`init_collect`、`iter_collect`、`max_loops`、`raw` 等）可通过 `**kwargs` 透传。

```bash
alphapilot mine_aff --instruments=test_stock_pool_80 --zoo_size=20 --device=cpu --backtest=True
```

### `alphapilot mine_gp`

遗传编程（GP）因子挖掘。依赖较轻。

源文件：[`alphapilot/modules/alphaforge_search/module.py`](../alphapilot/modules/alphaforge_search/module.py)

| 参数 | 默认 |
|------|------|
| `--instruments` | `csi300` |
| `--train_end_year` | `2020` |
| `--population_size` | `1000` |
| `--generations` | `40` |
| `--backtest` | False |
| `--save` | True |

```bash
alphapilot mine_gp --instruments=test_stock_pool_80 --population_size=200 --generations=10
```

### `alphapilot mine_rl`

PPO 强化学习因子挖掘。需要 `stable-baselines3`、`sb3-contrib`。

| 参数 | 默认 |
|------|------|
| `--steps` | `200000` |
| `--pool_capacity` | `10` |
| `--backtest` | False |
| `--save` | True |

```bash
alphapilot mine_rl --instruments=test_stock_pool_80 --steps=50000 --pool_capacity=10
```

### `alphapilot mine_dso`

深度符号优化（DSO）。需要可选依赖 `alphaforge-dso`（TensorFlow + Cython `cyfunc`）。

| 参数 | 默认 |
|------|------|
| `--n_samples` | `5000` |
| `--pool_capacity` | `10` |
| `--backtest` | False |
| `--save` | True |

```bash
alphapilot mine_dso --instruments=test_stock_pool_80
```

更多细节见 [`alphapilot/modules/alphaforge/README.md`](../alphapilot/modules/alphaforge/README.md)。

---

## 可选依赖与弃用命令

### 可选依赖

安装 extras（见 `pyproject.toml` `[project.optional-dependencies]`）：

```bash
# AFF + GP + RL
pip install -e ".[alphaforge]"

# DSO（TensorFlow + Cython，较重）
pip install -e ".[alphaforge-dso]"
```

| 命令 | 所需依赖 |
|------|----------|
| `mine_aff` | `torch` 等（`alphaforge` extra） |
| `mine_gp` | 较轻，基本随主依赖 |
| `mine_rl` | `stable-baselines3`, `sb3-contrib`（`alphaforge` extra） |
| `mine_dso` | `tensorflow`, `cython`（`alphaforge-dso` extra） |

### 已弃用命令

| 命令 | 替代 |
|------|------|
| `alphapilot ui` | `alphapilot portal` →「挖掘日志」标签页 |
| `alphapilot backtest_ui` | `alphapilot portal` →「回测 → 回测详情」 |

调用弃用命令只会打印提示，不会启动 Streamlit。

---

## 附录：内部脚本

以下脚本**不**通过 `alphapilot` 主入口暴露，供开发或间接调用：

| 路径 | 说明 |
|------|------|
| [`systems/data/prepare_data.py`](../alphapilot/systems/data/prepare_data.py) | `PrepareDataCLI`，被 `prepare_data` 间接调用 |
| [`systems/data/qlib_dump/dump_bin.py`](../alphapilot/systems/data/qlib_dump/dump_bin.py) | Qlib CSV → 二进制 dump 工具 |
| [`systems/data/qlib_dump/future_calendar_collector.py`](../alphapilot/systems/data/qlib_dump/future_calendar_collector.py) | 扩展 Qlib 交易日历 |
| [`log/ui/app.py`](../alphapilot/log/ui/app.py) | 独立挖掘日志 Streamlit（已整合进 portal） |
| [`modules/portal/schedules.py`](../alphapilot/modules/portal/schedules.py) | scheduler 底层；`python -m` 可调试 |
| [`modules/portal/jobs.py`](../alphapilot/modules/portal/jobs.py) | portal 后台 job worker 调试入口 |
| [`modules/alphaforge/vendor/dso/run.py`](../alphapilot/modules/alphaforge/vendor/dso/run.py) | vendored DSO Click CLI，未接入 `alphapilot` |
| [`modules/alphaforge/vendor/dso/logeval.py`](../alphapilot/modules/alphaforge/vendor/dso/logeval.py) | DSO 实验日志分析 |
| [`modules/alphaforge/vendor/dso/task/regression/dataset.py`](../alphapilot/modules/alphaforge/vendor/dso/task/regression/dataset.py) | DSO 基准数据集可视化 |

---

## 相关文档

- [项目结构说明](alphapilot-structure.md)
- [README](../README.md)
- [因子 Qlib 模板](../important_data/factor_qlib_templates/README.md)
- [用户数据目录](../important_data/README.md)
