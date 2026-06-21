# AlphaPilot

基于 [AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent)（KDD 2025）的本地化 fork，面向 A 股因子挖掘与 Qlib 回测。本仓库在保留原项目核心流程（假设生成 → 因子构造 → 回测评估）的基础上，增加了 API 兼容、**多模式回测**、**日频交易信号**、回测可视化等改动，便于在本地环境稳定运行。

---

## 项目简介

AlphaPilot 通过三个 Agent 协作完成因子挖掘：

| Agent | 职责 |
|-------|------|
| **Idea Agent** | 根据市场假说提出可验证的因子方向 |
| **Factor Agent** | 将假说转化为因子表达式并生成代码 |
| **Eval Agent** | 用 Qlib 回测评估因子，并反馈迭代 |

本仓库使用 [Qlib](https://github.com/microsoft/qlib) 作为回测引擎，使用 OpenAI 兼容 API 调用大模型。

> **CLI 完整参考**：所有 `alphapilot` 命令及参数见 [docs/alphapilot-cli.md](docs/alphapilot-cli.md)。

---

## 相对原版的改动说明

### 1. LLM JSON 解析容错（`alphapilot/oai/llm_utils.py`）

适配 MiniMax 等推理模型的非标准 JSON 输出（代码块包裹、尾逗号、推理块等），新增 `extract_and_validate_llm_json()`，降低因子构造阶段 `json.loads` 失败概率。

### 2. 回测结果可视化（`alphapilot/modules/backtest_viz/` + `systems/backtest/artifacts.py`）

在原版 `alphapilot ui`（运行日志总览）之外，新增回测查看器（`backtest_viz` / portal「回测」页），支持：

- 收益曲线、超额收益、回撤
- 日换手与成本
- 当日成交、持仓明细
- **`single_ic` / `multi_sequential` 因子排行榜**（扫描 `*_leaderboard.csv`）

原独立界面 `alphapilot ui` / `alphapilot backtest_ui` 已整合进统一门户 `alphapilot portal`（见下方使用流程）。

### 2.5 多模式回测与日频交易信号（`systems/backtest/`）

回测系统新增 **引擎分层** 与 **三种评估模式**（默认 `multi_combined` 与原版行为一致）：

| 模式 | 行为 |
|------|------|
| `multi_combined` | 多因子合并 → LGBM → `qrun` 组合回测（默认） |
| `single_ic` | 只算 IC/RankIC/ICIR，不训练、不 `qrun`（快筛） |
| `multi_sequential` | 逐因子各跑一次完整 `qrun`（慢，适合少量终选因子） |

- **可配置 yaml**：`--yaml_params`（JSON / 文件）在运行时渲染 `QlibYamlParams` 到 workspace，可改模型、调仓策略、回测区间、TopK 等，无需先改静态模板（亦可用 `qlib_yaml_generate` 落盘到 `factor_qlib_templates/`）。
- **引擎**：`engines/qlib_workflow.py`（全量 `qrun`）、`engines/qlib_signal.py`（IC 快筛）；编排见 `pipelines/factor_evaluation.py`。
- **模型资产**：`qrun` 完成后 workspace 会尝试导出 `fitted_model.pkl`（`scoring_model_export.py`），供 `strategy_backtest --mode=reuse_model` 与下方日频信号复用。
- **日频交易信号**（`systems/backtest/live/` + `alphapilot daily_signals`）：加载已训练模型，在**昨日持仓 + 现金**基础上只推进 **一个交易日**（qlib 底层 `backtest`，非整段 `qrun`）；状态写入 `git_ignore_folder/portfolio_state/<策略>.json` 并自动滚动。Portal：**每日交易**页。

设计细节与路线图见 [docs/alphapilot-backtest.md](docs/alphapilot-backtest.md)。

### 2.6 统一 Web 门户（React/FastAPI）

原 Streamlit 统一门户已重写为 **FastAPI 后端 + React/TypeScript (Vite) 前端**：

| 组件 | 路径 | 说明 |
|------|------|------|
| API | `alphapilot/modules/portal/api.py` | REST 后端，驱动页面与后台 job |
| 前端 | `alphapilot/modules/portal/web/` | React 源码；`npm run build` → `web/dist/` |
| 旧版 | `alphapilot/modules/portal/app.py` | Streamlit 门户，经 `alphapilot portal_legacy` 启动 |

`alphapilot portal` 由 Python 托管 `dist/` 静态文件并暴露 `/api/*`；`ui` / `backtest_ui` 能力已整合进新版各导航页。旧版 Streamlit 保留作回退。

### 3. 数据准备命令（`alphapilot prepare_data`）

- 内置原 qlib `dump_bin.py`、`future_calendar_collector.py`（无需 clone qlib 仓库）
- 通过 baostock 下载行情：支持**直接下载前/后复权**（`--adjust_mode forward|backward`），或下载除权日线 + 复权因子后用 `apply_adjust` 本地合成，再 `convert` 为 Qlib 与 `daily_pv.h5`；CSV 与下载状态默认落在 `~/.qlib/qlib_data/cn_data/baostock/`
- 可选 Tushare 数据源：`--action download --source tushare_cn` 下载除权日线 + `adj_factor`，默认保存到 `~/.qlib/qlib_data/cn_data/tushare/`（与 baostock 目录并列，互不覆盖）
- 默认股票列表：`important_data/stock_lists/main_stock_2026_4_27.csv`（可用 `--stock_csv` 指定任意 CSV/TXT，例如同目录下的 `kechuang_stock.csv`）

> 用户数据目录总览见 [important_data/README.md](important_data/README.md)（策略资产、**因子库**、Qlib 模板、股票池列表）。

> 当前 CLI 已改为 **modules-only** 分发，`prepare_data` 由内置 `platform` 模块提供。  
> 从本地化重构版本起，`prepare_data` 的各 action 统一经由 **data system** 调度（单一入口），避免模块层直接分支调用。  
> 数据下载、复权、Qlib 转换、h5 生成等**核心实现位于** `alphapilot/systems/data/`（`app/data` 兼容层已移除）。  
> 你可以继续使用原有风格：`alphapilot prepare_data download ...`，也可使用显式 action 风格：`alphapilot prepare_data --action download ...`。

示例（两种写法等价）：

```bash
# 旧写法（仍可用）
alphapilot prepare_data download --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv

# 新写法（modules-only 语义更清晰）
alphapilot prepare_data --action download --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv
```

Tushare 数据源需使用显式 action 写法，并设置 `TUSHARE_TOKEN` 或传入 `--token`：

```bash
TUSHARE_TOKEN=你的token alphapilot prepare_data --action download \
  --source tushare_cn \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode none
```

### 4. 回测与因子数据配置

> **回测系统设计与演进规划**（当前实现、组合 vs 单因子语义、目标架构）：见 [docs/alphapilot-backtest.md](docs/alphapilot-backtest.md)。

**Qlib 回测模板（`qrun` 实际加载）**

| 优先级 | 目录 | 说明 |
|--------|------|------|
| 1（推荐） | `important_data/factor_qlib_templates/` | 在 `.env` 中配置 `QLIB_FACTOR_QLIB_TEMPLATE_DIR` 后，`mine` / `backtest` / `strategy_backtest` 默认使用此目录 |
| 2（回退） | `alphapilot/systems/backtest/qlib/templates/factor_template/` | 未配置用户目录且 `important_data/factor_qlib_templates/` 不存在时使用 |

常见文件：

| 文件 | 用途 |
|------|------|
| `conf.yaml` | 基线回测（仅内置价量特征） |
| `conf_cn_combined_kdd_ver.yaml` | 合并 LLM 新因子后的回测（`mine` / `backtest` 常用默认） |
| `back_test.yaml` | 更短回测窗口的变体（手动 `qrun` 或自定义场景时使用，非 mine 默认） |
| `read_exp_res.py` | `qrun` 后导出 IC、收益等到 `qlib_res.csv` / `ret.pkl` |

**默认选用哪个 yaml？**

| 命令 | 默认 yaml | 说明 |
|------|-----------|------|
| `alphapilot mine` | `.env` 中 `QLIB_FACTOR_QLIB_CONFIG_NAME`，未配置时多为 `conf_cn_combined_kdd_ver.yaml` | 通过 `AlphaPilotLoop` 读取 `QLIB_FACTOR_*` |
| `alphapilot backtest` | 未传 `--qlib_config_name` 时，按实验结构自动选：有 `based_experiments` → `conf_cn_combined_kdd_ver.yaml`，否则 `conf.yaml` | 一般 backtest 也会落到 combined；可用 `--mode`（`single_ic` / `multi_sequential`）；`--yaml_params` 可运行时覆盖模型/策略/区间 |
| `alphapilot strategy_backtest` | 策略 `metadata` 中的记录，否则 `.env` 的 `QLIB_FACTOR_*` | 与 mine 保存时写入的 yaml 名一致 |
| `alphapilot daily_signals` | 策略 `metadata` 中的 `yaml_params`，或 `--yaml_params` | 日频一步调仓；不跑整段历史 `qrun` |

模板目录默认优先 `important_data/factor_qlib_templates/`（目录存在时），与是否配置 `.env` 无关；`QLIB_FACTOR_QLIB_TEMPLATE_DIR` 用于显式指定或覆盖。

**二开建议**：将内置模板复制到 `important_data/factor_qlib_templates/` 后只改副本，避免动仓库内置配置。模板说明见 [important_data/factor_qlib_templates/README.md](important_data/factor_qlib_templates/README.md)。

> `alphapilot/modules/alpha_mining/qlib/experiment/factor_template/` 为历史副本，**运行时不会**作为 `qrun` 模板目录；请以 `important_data/factor_qlib_templates/` 或 `systems/backtest/qlib/templates/factor_template/` 为准。

**可选环境变量**（前缀 `QLIB_FACTOR_`，在 `.env` 中配置；CLI 参数优先）：

| 变量 | 含义 |
|------|------|
| `QLIB_FACTOR_QLIB_TEMPLATE_DIR` | 拷入 workspace 的模板目录（相对项目根，如 `important_data/factor_qlib_templates`） |
| `QLIB_FACTOR_QLIB_CONFIG_NAME` | 上述目录中的 yaml 文件名（如 `conf_cn_combined_kdd_ver.yaml`） |

`alphapilot prepare_data h5` 会从 Qlib 导出 `daily_pv.h5` 到 `git_ignore_folder/factor_implementation_source_data*`，供因子 Python 代码使用。

模板 yaml 中的 `provider_uri` 须指向当前使用的 Qlib 二进制目录（baostock 默认 `~/.qlib/qlib_data/cn_data/baostock/qlib`）。若只改 `.env` 的 `ALPHAPILOT_QLIB_DATA_DIR` 而未改 yaml，部分 `qrun` 路径仍可能读到旧目录。

可按需修改股票池（`market` / `instruments`）、训练/验证/测试区间、持仓数量等。

**用 CLI 生成或校验 yaml**（`alphapilot qlib_yaml_*`，实现位于 `systems/backtest/qlib_yaml/`）：

- 不让 LLM 直接写整份带 YAML 锚点的配置，而是：**结构化参数 + 可选自然语言 → LLM 输出 JSON 补丁 → Jinja2 渲染模板**
- 生成后自动做静态校验；默认还会跑 Qlib handler 冒烟（可用 `--skip_smoke` 跳过）

```bash
# 结构化参数生成（baseline = conf.yaml 结构；combined = conf_cn_combined_kdd_ver.yaml 结构）
alphapilot qlib_yaml_generate \
  --output=important_data/factor_qlib_templates/my_conf.yaml \
  --template=baseline \
  --topk=20

# JSON 补丁 + LLM 自然语言
alphapilot qlib_yaml_generate \
  --output=important_data/factor_qlib_templates/my_conf.yaml \
  --template=combined \
  --params_file=my_params.json \
  --prompt="回测区间改到2025年底，topk改为20" \
  --copy_helpers

# 校验已有 yaml（combined 模板可加 --workspace 检查 combined_factors_df.pkl）
alphapilot qlib_yaml_validate \
  --config=important_data/factor_qlib_templates/conf.yaml \
  --skip_smoke
```

生成产物写入 `important_data/factor_qlib_templates/` 后，`mine` / `backtest` 会自动拾取（与手工编辑 yaml 等效）。详见 [important_data/factor_qlib_templates/README.md](important_data/factor_qlib_templates/README.md)。

**一次性调参、不想改模板文件时**：直接在 `backtest` / `daily_signals` 上传 `--yaml_params='{"topk":30,...}'`（或 JSON/YAML 文件路径），由 `factor_runner` / `live/predict.py` 在当次运行渲染进 workspace，与上面「生成 yaml 落盘」二选一或组合使用。

### 5. 运行注意事项

- 请在 **`AlphaPilot` 项目根目录** 下执行命令，确保 `.env` 能被正确加载
- `.env` 已加入 `.gitignore`，勿将 API Key 提交到仓库

### 6. 结构收敛（Big Bang 迁移）

本仓库已完成一次性结构收敛，核心变更如下：

- 因子挖掘业务整体收拢到 `alphapilot/modules/alpha_mining/`
  - `qlib` 场景代码：`alphapilot/modules/alpha_mining/qlib/`
  - 循环编排：`alphapilot/modules/alpha_mining/loops/alphapilot_loop.py`
  - 场景配置：`alphapilot/modules/alpha_mining/conf.py`
  - 场景注册：`alphapilot/modules/alpha_mining/registry.py`
- 历史入口 `alphapilot/app/qlib_rd_loop/*` 已移除，不再保留兼容 shim
- 数据准备逻辑已迁入 `alphapilot/systems/data/`（含 `prepare_cn.py`、`adjust_prices.py`、`qlib_convert.py`、`generate_h5.py`、`qlib_dump/` 等）；`alphapilot/app/data/` 兼容层已删除
- `prepare_data` 统一由 `platform -> context.data() -> systems.data` 链路执行（单一调度入口）
- `mine/backtest/strategy_backtest/qlib_yaml_generate/qlib_yaml_validate/factor_validate/factor_add/prepare_data/portal/data_viz/backtest_viz` 等由内置模块贡献命令（modules-only）；`ui` / `backtest_ui` 仅保留弃用提示
- 回测产物解析收拢到 `alphapilot/systems/backtest/artifacts.py`；可视化 UI 在 `alphapilot/modules/backtest_viz/`（原 `app/backtest_viewer/` 已删除）
- 回测引擎与多模式分派：`systems/backtest/engines/`（`QlibWorkflowEngine` / `QlibSignalEngine`）+ `pipelines/factor_evaluation.py`（`multi_combined` / `single_ic` / `multi_sequential`）
- 日频交易信号：`systems/backtest/live/`（持仓 JSON、`predict`、单日 `rebalance`）+ CLI 模块 `modules/daily_trade/`（`daily_signals` / `daily_state`）
- 策略复测编排收拢到 `alphapilot/systems/strategy/backtest.py`，经 `context.backtest()` 执行，**不再**经 `alpha_mining` 模块中转
- 挖掘日志 UI（`alphapilot/log/ui/`）通过 `core.scenario.Scenario` 的 UI trait 分支渲染，**不再 import** `alpha_mining` 具体场景类
- adapter 层仅保留 **LLM + 数据源** 可插拔边界；已移除未接入主路径的 backtest engine adapter（`get_backtest_engine`），回测统一经 `systems/backtest/` 执行（详见 [alphapilot/adapters/README.md](alphapilot/adapters/README.md)）
- 统一 Web 门户：`modules/portal/api.py`（FastAPI）+ `modules/portal/web/`（React/Vite 前端）；旧 Streamlit 版保留为 `app.py` / `alphapilot portal_legacy`
- 任务完成通知收拢到 `alphapilot/systems/notify/`（Telegram / 飞书 / 邮件）；Portal「通知」页配置凭证，后台 job 结束时由 `modules/portal/jobs.py` 触发推送

**数据系统代码位置（供二开参考）**

| 模块 | 路径 | 职责 |
|------|------|------|
| CLI 编排 | `systems/data/prepare_data.py` | `PrepareDataCLI`，对应 `alphapilot prepare_data` 各子命令 |
| 下载 | `systems/data/prepare_cn.py` | baostock 下载、复权因子刷新 |
| Tushare 下载 | `systems/data/prepare_tushare.py` | Tushare 日线 + `adj_factor` |
| 路径约定 | `systems/data/data_paths.py` | `cn_data/baostock` 与 `cn_data/tushare` 目录布局、旧路径回退 |
| 复权 | `systems/data/adjust_prices.py` | 除权 CSV 本地合成前/后复权 |
| Qlib 转换 | `systems/data/qlib_convert.py` | CSV → Qlib 二进制 |
| h5 导出 | `systems/data/generate_h5.py` | 生成 `daily_pv.h5` |
| dump 工具 | `systems/data/qlib_dump/` | `dump_bin`、交易日历扩展 |
| 单股管理 | `systems/data/manage.py` | 单只股票的删除 / 裁剪 / 单股重 dump（`delete_symbol`、`trim_symbol`、`resync_symbol_to_qlib`、instruments 增删改） |
| 系统 API | `systems/data/service.py` | `QlibDataSystem` 与 typed DTO（`types.py`） |
| 路径约定 | `kernel/paths.py` | `important_data_dir`、`strategy_zoo_dir`、`factor_zoo_dir`、`stock_lists_dir`、默认 `stock_csv` |

程序化调用示例：

```python
from alphapilot.kernel import build_engine
from alphapilot.systems.data.types import DataDownloadCommand

engine = build_engine()
data = engine.get_system("data")
data.run_download(DataDownloadCommand(
    start_date="2005-01-01",
    stock_csv="important_data/stock_lists/main_stock_2026_4_27.csv",
    options={"adjust_mode": "backward"},
))
```

**单只股票数据管理（删除 / 修改）**

一只股票的数据横跨多层：各复权目录 raw CSV、复权因子 CSV、Qlib 二进制 `features/{code}/`、`instruments/{all.txt, market.txt}`、衍生 `daily_pv_*.h5`。CSV 是「源」，Qlib 二进制与 h5 是「派生物」，**改 CSV 后必须同步**否则回测仍读旧数据。新增命令会自动处理这条链路：

| 命令 | 作用 | Qlib/h5 同步 |
|------|------|--------------|
| `alphapilot list_stocks` | 列出本地已下载代码（可加 `--adjust_mode`） | — |
| `alphapilot delete_stock --symbol sz.300001` | 删除该股各复权 CSV、复权因子、`features/{code}/`、`instruments` 行 | 删除天然 per-symbol 安全，无需重 dump；h5 需重建 |
| `alphapilot refresh_stock --symbol sz.300001 --adjust_mode backward` | 增量重下该股（含复权因子） | 自动用 `DumpDataUpdate` 单股重 dump（扩日历 + 追加）；h5 需重建 |
| `alphapilot trim_stock --symbol sz.300001 --start_date 2018-01-01 --drop_dates 2020-02-03,2020-02-04` | 按区间裁剪 / 删除指定异常日期（本地，不联网） | 自动用 `DumpDataFix` 单股重 dump；h5 需重建 |

要点：

- `delete_stock` 的 `--adjust_mode` 默认 `all`（删除全部复权目录的 CSV）；`refresh/trim` 用 `--qlib_adjust_mode`（默认 `backward`）指定**重 dump 读哪个复权目录**，需与你 `convert` 时所用复权类型一致。
- **`daily_pv_*.h5` 无增量模式**，默认**延后重建**：上述命令会提示「h5 已过期」。请在改动完成后运行 `alphapilot prepare_data h5`（或给 `refresh/trim` 加 `--rebuild_h5 True`）让因子数据同步。
- 所有破坏性操作支持 `--dry_run True` 先预览将改动的文件 / instruments 行。
- 单股重 dump 依赖已存在的 `instruments/all.txt` 与 `calendars/day.txt`；若缺失会提示改跑全量 `alphapilot prepare_data convert`。
- Portal「市场数据」页也内嵌了同一套删除 / 刷新 / 裁剪控件与「重建 daily_pv h5」按钮。

### 7. 任务完成通知（`alphapilot/systems/notify/`）

因子挖掘、因子/策略回测、数据任务、AlphaForge 等**后台任务**完成后，可推送摘要到 **Telegram**、**飞书** 或 **邮件 SMTP**。

- **配置入口**：`alphapilot portal` → **通知**
- **凭证文件**：`~/.alphapilot/credentials/notify.json`（仓库外，权限 `0600`；勿提交 git）
- **触发方式**：在「定时任务」创建任务时勾选「完成后通知」；或在通知页开启「所有后台任务完成都通知」
- **环境变量覆盖**（服务器部署）：`ALPHAPILOT_NOTIFY_*`（如 `ALPHAPILOT_NOTIFY_TELEGRAM_BOT_TOKEN`、`ALPHAPILOT_NOTIFY_FEISHU_WEBHOOK`）；**运行时 env 优先于文件**
- **测试**：Portal 中先 **Save**，再点频道 **Test Send**（未保存时测试读的是磁盘上的旧配置）

| 频道 | 必填项 | 说明 |
|------|--------|------|
| Telegram | `bot_token`、`chat_id` | @BotFather 创建 bot；先向 bot 发 `/start`，再填个人或群 `chat_id` |
| 飞书 Feishu | `webhook` | 群 **自定义机器人** Webhook URL；若创建时开启签名校验则同时填 `secret`，否则留空 |
| Email | `host`、`sender`、`recipients` | SMTP（默认 SSL 465；`use_ssl=false` 时用 STARTTLS）；按需填 `username` / `password` |

实现位于 `alphapilot/systems/notify/`（`config.py`、各 channel、`service.py`）；Portal 后台 worker 在 `modules/portal/jobs.py` 中于任务结束时调用。

---

## 环境准备

### 1. 创建 Conda 环境

```bash
conda create -n alphapilot python=3.11
conda activate alphapilot
```

### 2. 安装本仓库

在 **AlphaPilot 根目录** 下安装依赖与可编辑包：

```bash
cd AlphaPilot
pip install -e .
```

**Portal（React/FastAPI）额外说明**

新版 `alphapilot portal` 使用 **FastAPI 后端 + React/TypeScript (Vite) 前端**：

- Python 后端依赖 `fastapi`、`uvicorn`，已写入 `requirements.txt`，执行 `pip install -e .` 时会安装到当前 conda 环境（例如 `conda activate alphapilot` 后的 `alphapilot` 环境）。
- 前端构建需要 **Node.js/npm**。Node 不需要装进 conda 虚拟环境，推荐用 Homebrew 安装系统级 Node：

```bash
brew install node
```

如果 conda 环境里的旧 Node 在 `PATH` 前面，构建时可显式使用 Homebrew Node：

```bash
cd alphapilot/modules/portal/web
PATH=/opt/homebrew/bin:$PATH npm install --registry=https://registry.npmmirror.com
PATH=/opt/homebrew/bin:$PATH npm run build
```

构建完成后会生成 `alphapilot/modules/portal/web/dist/`。运行 `alphapilot portal` 只需要这个 `dist/` 和 Python 后端依赖；不需要每次启动都运行 npm。旧版 Streamlit 门户保留为 `alphapilot portal_legacy`。

本地开发前端时，可在一个终端运行 `alphapilot portal --port 19901`，另一个终端在 `alphapilot/modules/portal/web` 下执行 `npm run dev`（Vite 默认 `http://localhost:5173`，`/api` 代理到后端）。仅改 Python 后端时可用 `alphapilot portal --reload --port 19901`（需配合 `npm run dev` 或已构建的 `dist/`）。

**可选：AlphaForge 公式化挖掘依赖**

AlphaForge（无需 LLM 的公式化因子挖掘，详见 [使用流程 §1.5](#15-alphaforge-公式化因子挖掘无需-llm可选)）的依赖不随基础安装引入，按需选装：

```bash
# AFF（GAN）+ GP + RL：torch / gym / stable-baselines3 / sb3-contrib / shimmy
pip install -e ".[alphaforge]"

# DSO（实验性、较重，可选）：先装 TensorFlow + Cython
pip install -e ".[alphaforge-dso]"
# 再编译 dso 的 Cython 扩展（cyfunc）
cd alphapilot/modules/alphaforge/vendor/dso && python setup.py build_ext --inplace && cd -
```

> GP / RL / AFF 三种方法只需 `.[alphaforge]`；DSO 额外依赖 TensorFlow 与已编译的 `cyfunc` 扩展，缺失时仅 `mine_dso` 会报清晰的安装提示，不影响其它方法。numpy / scipy / pandas / scikit-learn / gymnasium 等已随基础依赖（含 qlib）安装。

### 3. macOS 额外依赖（LightGBM 回测）

在 **macOS** 上跑 `alphapilot mine` 时，Qlib 回测默认使用 **LightGBM**（`LGBModel`）。除 conda 环境内的 Python 包外，还需要本机通过 **Homebrew** 安装 OpenMP 运行时；`brew` 装的是**系统级**库（如 `/opt/homebrew/opt/libomp`），**不会**装进 `alphapilot` 虚拟环境，运行时由 LightGBM 动态加载。

**1）安装 libomp（仅需执行一次）**

```bash
brew install libomp
```

**2）验证 LightGBM 是否可用**

```bash
conda activate alphapilot
python -c "import lightgbm as lgb; print('lightgbm', lgb.__version__)"
```

若仍报 `dlopen` / 找不到 `libomp`，可确认 Homebrew 路径后重装 LightGBM：

```bash
brew --prefix libomp
pip install lightgbm --force-reinstall
```

Apple Silicon 上 `brew --prefix libomp` 一般为 `/opt/homebrew/opt/libomp`；Intel Mac 多为 `/usr/local/opt/libomp`。

### 4. 准备行情数据

在 **AlphaPilot 根目录** 下准备数据有两种常用方式（二选一即可）。

#### 方式 A：直接下载已复权数据（更简单）

`download` 的 `--adjust_mode` 设为 `forward`（前复权）或 `backward`（后复权）时，由 **baostock 直接返回复权后的 OHLC**，写入对应目录，**无需** `apply_adjust`，也**不会**下载复权因子。

```bash
cd AlphaPilot

# 后复权（写入 ~/.qlib/qlib_data/cn_data/baostock/raw_data_back_adjust）
alphapilot prepare_data download \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode backward

# 或前复权（写入 baostock/raw_data_forward_adjust）
# alphapilot prepare_data download \
#   --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
#   --adjust_mode forward

# 转 Qlib + 日历 + h5（adjust_mode 与下载时一致；Qlib 默认写入 baostock/qlib）
alphapilot prepare_data convert \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode backward \
  --market main_stock_2026_4_27
```

同样支持增量：再次执行 `download` 只会补最新交易日。中文别名：`前复权`、`后复权`。

#### 方式 B：除权 + 本地复权（默认，便于核对因子）

先下除权价与复权因子，再在本地合成前/后复权 CSV，适合需要自行核对除权因子、或希望与本地 `apply_adjust` 逻辑一致时使用。

```bash
cd AlphaPilot

# 1) 仅下载：除权行情（增量；已到 end_date 则零网络请求）+ 有缺口时窗口探测除权因子
alphapilot prepare_data download --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv --adjust_mode none

# 可选：除权行情和复权因子分两个独立进程并行下载（默认关闭，可能触发数据源限流）
alphapilot prepare_data download \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode none \
  --parallel_price_factor True

# 2) 合成为前复权或后复权 CSV（供训练 / convert）
alphapilot prepare_data apply_adjust --adjust_mode backward
# alphapilot prepare_data apply_adjust --adjust_mode forward

# 若早期复权价仍等于除权价，先刷新全历史复权因子（自 1990 年起）
alphapilot prepare_data refresh_factors --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv

# 3) 转 Qlib + 日历 + h5（data_path / adjust_mode 与上一步复权类型一致）
alphapilot prepare_data convert \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode backward \
  --market main_stock_2026_4_27
```

一键全流程（方式 B：下载除权 → 本地复权 → convert）：

```bash
alphapilot prepare_data pipeline \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --target_mode forward
```

#### 可选：Tushare 数据源

Tushare 第一版支持 A 股日线 + `adj_factor`，默认落盘到独立目录
`~/.qlib/qlib_data/cn_data/tushare/`，避免覆盖 baostock 数据。Tushare 下载仅支持
`--adjust_mode none`；如需前/后复权，请下载后复用本地 `apply_adjust`。

```bash
# 1) 下载 Tushare 除权日线 + adj_factor
TUSHARE_TOKEN=你的token alphapilot prepare_data --action download \
  --source tushare_cn \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode none

# Tushare 也可显式开启并行行情 + adj_factor 下载；默认关闭以避免积分/限流风险
TUSHARE_TOKEN=你的token alphapilot prepare_data --action download \
  --source tushare_cn \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode none \
  --parallel_price_factor True

# 1b) 会员可选：附带每日指标（daily_basic，需 Tushare 2000 积分）
#     额外填充 turn/peTTM/pbMRQ/psTTM 到同一份行情 CSV
TUSHARE_TOKEN=你的token alphapilot prepare_data --action download \
  --source tushare_cn \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode none \
  --include_daily_basic True

# 2) 用 Tushare 目录合成前复权 CSV
alphapilot prepare_data apply_adjust \
  --adjust_mode forward \
  --raw_dir ~/.qlib/qlib_data/cn_data/tushare/raw_data_no_adjust \
  --factor_dir ~/.qlib/qlib_data/cn_data/tushare/adjust_factors \
  --output_dir ~/.qlib/qlib_data/cn_data/tushare/raw_data_forward_adjust

# 3) 转 Qlib；使用独立 qlib_dir，避免与 baostock 的 Qlib 数据混用
alphapilot prepare_data convert \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --data_path ~/.qlib/qlib_data/cn_data/tushare/raw_data_forward_adjust \
  --qlib_dir ~/.qlib/qlib_data/cn_data/tushare/qlib \
  --market main_stock_2026_4_27 \
  --adjust_mode forward

# 4) 生成 h5（因子挖掘用；切换 Tushare 后须对应当前 qlib_dir）
alphapilot prepare_data h5 \
  --qlib_dir ~/.qlib/qlib_data/cn_data/tushare/qlib \
  --market main_stock_2026_4_27
```

`pipeline` 现已支持数据源参数：传 `--source tushare_cn` 即可一键跑通
Tushare 全流程（下除权 + `adj_factor` → 本地 `apply_adjust` → `convert`，各目录默认落在
`cn_data/tushare/` 下）。Tushare 仅支持除权下载，因此 `source=tushare_cn` 时强制
`adjust_mode=none`，最终复权由 `--target_mode forward|backward` 决定：

```bash
TUSHARE_TOKEN=你的token alphapilot prepare_data --action pipeline \
  --source tushare_cn \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --target_mode forward
```

baostock 流程不变：`--source` 省略即默认 baostock，`adjust_mode=none` 时同样可用
`--target_mode` 选择前/后复权，或直接 `--adjust_mode forward|backward` 下载已复权数据。
Tushare 与 baostock 的 OHLC / 成交量单位不完全一致，**请勿混用同一 `qlib_dir`**。

**`--include_daily_basic`（每日指标，需 2000 积分）**：`pro.daily()` 不返回换手率与估值，
默认这些列留空（`NA`）。开启后会额外调用 `daily_basic` 并按交易日合并进**同一份** Tushare 行情
CSV，填充以下列（与 baostock 同名，下游 `apply_adjust` / `convert` 无需改动）：

| 行情 CSV 列 | Tushare `daily_basic` 字段 |
|-------------|----------------------------|
| `turn`      | `turnover_rate`（换手率） |
| `peTTM`     | `pe_ttm` |
| `pbMRQ`     | `pb` |
| `psTTM`     | `ps_ttm` |

- 积分不足/限流时**优雅降级**：仅打印告警并把该列留空，**不影响**行情与复权因子下载（统计行会显示「每日指标失败」计数）。
- `daily_basic` 按 `[start_date, end_date]` 全窗口拉取，增量补行情时会顺带回填历史行；但若本地行情已是最新（零网络请求被整只跳过），不会单独触发回填——此时请清掉该股 CSV 或 `download_state` 后重下以补齐。
- `pcfNcfTTM` / `isST` 不在 `daily_basic` 中，仍保持 `NA`。
- 仅 Tushare 支持此参数；baostock 的 K 线接口已自带这些字段，传入会被忽略。

**指定股票列表**（路径任意；推荐放在 `important_data/stock_lists/`）

```bash
# 项目内其它列表（market 默认为文件名，如 kechuang_stock）
alphapilot prepare_data download \
  --stock_csv important_data/stock_lists/kechuang_stock.csv

# 自定义路径
alphapilot prepare_data download --stock_csv /path/to/my_stocks.csv --code_column ts_code
alphapilot prepare_data download --stock_csv watchlist.txt --market watchlist
alphapilot prepare_data download --all_market True
```

`--adjust_mode` / `--target_mode` 支持：`none`（除权/不复权）、`forward`（前复权）、`backward`（后复权），以及中文 `除权`、`前复权`、`后复权`。

支持的代码格式：`300001.SZ`、`sz.300001`、`SH600000`、纯 6 位数字。

下载后会写入 `instruments/{market}.txt`，**请在** 你使用的 Qlib 模板 yaml（通常为 `important_data/factor_qlib_templates/conf_cn_combined_kdd_ver.yaml`）**里把** `market` **改成与** `--market` **或** `stock_csv` **文件名一致**。

常用子命令：

```bash
# 直接前复权（跳过 apply_adjust）
alphapilot prepare_data download --stock_csv my_stocks.csv --adjust_mode forward
alphapilot prepare_data convert --stock_csv my_stocks.csv --adjust_mode forward

# 除权 + 本地复权
alphapilot prepare_data download --stock_csv my_stocks.csv --adjust_mode none
alphapilot prepare_data apply_adjust --adjust_mode forward
alphapilot prepare_data convert --stock_csv my_stocks.csv --adjust_mode forward
```

默认路径（`~/.qlib/qlib_data/cn_data/` 下按数据源分目录）：

```
cn_data/
├── baostock/
│   ├── raw_data_no_adjust/       # 除权 CSV
│   ├── raw_data_forward_adjust/  # 前复权 CSV
│   ├── raw_data_back_adjust/     # 后复权 CSV
│   ├── adjust_factors/           # 复权因子
│   ├── download_state.csv        # 下载增量状态
│   └── qlib/                     # convert 后的 Qlib 二进制（features / calendars / instruments）
└── tushare/
    └── （同上结构）
```

| 参数 | 默认值 |
|------|--------|
| `--stock_csv` | `important_data/stock_lists/main_stock_2026_4_27.csv` |
| `--market` | 与 `stock_csv` 文件名相同 |
| `download` 默认 `--adjust_mode` | `none`（除权）；设为 `forward` / `backward` 则直接下载已复权 CSV |
| `--parallel_price_factor` | 默认 `False`；仅 `adjust_mode=none` 时把除权行情和复权因子分独立进程并行下载，可能触发数据源限流 |
| **baostock** CSV 除权 | `cn_data/baostock/raw_data_no_adjust` |
| **baostock** CSV 前/后复权 | `cn_data/baostock/raw_data_forward_adjust` / `raw_data_back_adjust` |
| **baostock** 复权因子 | `cn_data/baostock/adjust_factors` |
| **baostock** 下载状态 | `cn_data/baostock/download_state.csv` |
| **baostock** Qlib 二进制 | `cn_data/baostock/qlib` |
| **tushare** 同上结构 | `cn_data/tushare/raw_data_*`、`adjust_factors`、`download_state.csv`、`qlib/` |

**从旧版目录迁移**（若 CSV / Qlib 仍在 `cn_data/` 根下而非 `baostock/`）：

```bash
BASE=~/.qlib/qlib_data/cn_data
mkdir -p "$BASE/baostock"
for d in raw_data_no_adjust raw_data_forward_adjust raw_data_back_adjust adjust_factors; do
  [ -d "$BASE/$d" ] && mv "$BASE/$d" "$BASE/baostock/"
done
[ -f "$BASE/download_state.csv" ] && mv "$BASE/download_state.csv" "$BASE/baostock/"
if [ -d "$BASE/features" ] || [ -d "$BASE/calendars" ]; then
  mkdir -p "$BASE/baostock/qlib"
  for d in features calendars instruments; do
    [ -d "$BASE/$d" ] && mv "$BASE/$d" "$BASE/baostock/qlib/"
  done
fi
```

**回测用哪套数据？** Qlib 回测读取的是 `qlib/` 二进制目录，不是 CSV。默认（baostock）在 `.env` 中配置：

```env
ALPHAPILOT_QLIB_DATA_DIR=~/.qlib/qlib_data/cn_data/baostock/qlib
```

改用 Tushare 时改为 `.../tushare/qlib`，并重新 `convert` + `h5`。也可在 Qlib 模板 yaml 的 `provider_uri` 或 `strategy_backtest --qlib_data_dir` 中指定。

如需指数成分股文件，仍可在 qlib 源码中运行 `cn_index/collector.py`（可选）；若使用自定义股票池，`convert` 会写入 `baostock/qlib/instruments/{market}.txt`（Tushare 则为 `tushare/qlib/instruments/`），请在 Qlib 模板 yaml 中把 `market` 设为与 `--market` 或 `stock_csv` 文件名一致。

修改股票池或字段后，请按下方 [清理缓存](#5-清理缓存) 删除旧 h5 并重新运行 `alphapilot prepare_data h5`。

---

## 配置说明

复制环境变量模板并填写：

```bash
cp .env.example .env
```

常用配置项：

```env
USE_LOCAL=True
OPENAI_BASE_URL=<你的 API 地址>
OPENAI_API_KEY=<你的 API Key>
REASONING_MODEL=<推理模型，用于假设与因子生成>
CHAT_MODEL=<对话模型，用于调试与反馈>
MAX_RETRY=5
FACTOR_MINING_TIMEOUT=36000  # 因子挖掘最长运行时间（秒），不设 step_n 时生效
EMBEDDING_MAX_STR_NUM=10     # DashScope 等 embedding 接口的单次 batch 上限（按需）

# 可选：用户数据根目录（策略资产、因子库、Qlib 模板、股票池 CSV 均在其下）
# ALPHAPILOT_IMPORTANT_DATA_DIR=important_data
# ALPHAPILOT_STRATEGY_PARAM_DIR=important_data/strategy_zoo
# ALPHAPILOT_FACTOR_ZOO_DIR=important_data/factor_zoo

# 可选：pickle 缓存（mine 与 backtest 分目录，见 §5 清理缓存）
# ALPHAPILOT_PICKLE_CACHE_DIR_MINE=pickle_cache/mine
# ALPHAPILOT_PICKLE_CACHE_DIR_BACKTEST=pickle_cache/backtest

# 可选：行情数据路径（默认解析到 cn_data/baostock/；见 §4 准备行情数据）
# ALPHAPILOT_QLIB_DATA_DIR=~/.qlib/qlib_data/cn_data/baostock/qlib
# ALPHAPILOT_RAW_DATA_DIR=~/.qlib/qlib_data/cn_data/baostock/raw_data_back_adjust
# ALPHAPILOT_ADJUST_FACTOR_DIR=~/.qlib/qlib_data/cn_data/baostock/adjust_factors
# TUSHARE_TOKEN=<your_tushare_pro_token>

# 可选：Qlib 回测模板与 yaml（mine / backtest / strategy_backtest 共用 QLIB_FACTOR_ 前缀）
# 模板内 provider_uri 建议与 ALPHAPILOT_QLIB_DATA_DIR 一致（如 .../baostock/qlib）
# QLIB_FACTOR_QLIB_TEMPLATE_DIR=important_data/factor_qlib_templates
# QLIB_FACTOR_QLIB_CONFIG_NAME=conf_cn_combined_kdd_ver.yaml

# 可选：门户 / 回测可视化默认路径（portal、backtest_viz 共用）
# ALPHAPILOT_LOG_DIR=./log
# ALPHAPILOT_WORKSPACE_ROOT=git_ignore_folder/RD-Agent_workspace
# ALPHAPILOT_BACKTEST_ROOT=git_ignore_folder/RD-Agent_workspace

# 可选：任务完成通知（默认 ~/.alphapilot/credentials/notify.json；Portal「通知」页也可配置）
# ALPHAPILOT_NOTIFY_CREDENTIALS_PATH=~/.alphapilot/credentials/notify.json
# ALPHAPILOT_NOTIFY_ON_ALL_JOBS=false
# ALPHAPILOT_NOTIFY_TELEGRAM_ENABLED=true
# ALPHAPILOT_NOTIFY_TELEGRAM_BOT_TOKEN=...
# ALPHAPILOT_NOTIFY_TELEGRAM_CHAT_ID=...
# ALPHAPILOT_NOTIFY_FEISHU_ENABLED=true
# ALPHAPILOT_NOTIFY_FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/...
# ALPHAPILOT_NOTIFY_FEISHU_SECRET=...
# ALPHAPILOT_NOTIFY_EMAIL_HOST=smtp.example.com
# ALPHAPILOT_NOTIFY_EMAIL_RECIPIENTS=you@example.com,other@example.com

# 可选：因子 factor.py 子进程 Python（默认当前解释器 sys.executable）
# FACTOR_CoSTEER_PYTHON_BIN=/path/to/python
```

---

## 使用流程

### 0. 查看当前可用模块与命令（推荐先执行）

```bash
alphapilot modules
```

输出会列出当前内置模块与通过 `entry_points` 自动发现的第三方模块，以及每个模块暴露的命令（含 `qlib_yaml_generate` / `qlib_yaml_validate`、`factor_validate` / `factor_add`、`daily_signals` / `daily_state`）。新增插件后，这里和 `alphapilot portal` 页面都会自动出现。

### 1. 因子挖掘（主流程）

在 **AlphaPilot 根目录** 下执行：

```bash
conda activate alphapilot
cd /path/to/AlphaPilot

alphapilot mine --direction "你的市场假说，例如：行为金融学假说"
```

指定场景运行（默认 `alpha_factor_mining`，可显式传入）：

```bash
alphapilot mine --scenario alpha_factor_mining --direction "行为金融学假说"
```

只跑有限轮次后自动退出（每轮 5 步：假说 → 构造 → 计算 → 回测 → 反馈）：

```bash
# 跑 1 轮
alphapilot mine --direction "行为金融学假说" --step_n 5

# 跑 2 轮
alphapilot mine --direction "行为金融学假说" --step_n 10
```

不传 `--step_n` 时会持续循环，直到手动中断或 `.env` 中 `FACTOR_MINING_TIMEOUT` 超时。

可选：指定自定义 Qlib 模板目录或 yaml（亦可在 `.env` 中配置 `QLIB_FACTOR_*`）：

```bash
alphapilot mine --direction "行为金融学假说" \
  --qlib_template_dir=important_data/factor_qlib_templates \
  --qlib_config_name=conf_cn_combined_kdd_ver.yaml
```

流程概要：

1. Idea Agent 生成/迭代市场假说  
2. Factor Agent 生成因子表达式与 Python 代码  
3. 在 `daily_pv.h5` 上计算因子值  
4. Qlib + LightGBM 回测，输出 IC、收益等指标  
5. 根据反馈进入下一轮；每轮成功结束后可将因子/模型/指标写入 `important_data/strategy_zoo/`（策略资产）

回测工作区默认在 `git_ignore_folder/RD-Agent_workspace/`；挖掘日志在 `log/`。因子库默认使用 SQLite，路径为 `important_data/factor_zoo/factor_zoo.db`（与策略资产一样长期保留，可用 Portal 或 API 管理）。

**从挖掘日志批量导入因子库**（自动按名称/表达式去重）：

```bash
python import_factors_from_log.py                  # 扫描整个 log/
python import_factors_from_log.py --dry-run      # 仅预览
python import_factors_from_log.py --log-dir log/<会话目录>
python import_factors_from_log.py --validate     # 仅导入通过校验的表达式（跳过时会打印 code 与原因）
```

**校验 / 添加单条因子表达式**（`alphapilot factor_*`，实现位于 `systems/factor/`，失败时返回具体原因而非仅 true/false）：

```bash
# 校验是否可加入因子库（失败时 exit 1，并打印 code / message / details）
alphapilot factor_validate --expression="Ref(\$close, 1) / \$close - 1"

# 示例：常量过多会被拒绝
alphapilot factor_validate --expression="1 + 2 + 3"

# 校验通过后写入 important_data/factor_zoo/factor_zoo.db
alphapilot factor_add --factor_name=my_momentum --expression="Ref(\$close, 1) / \$close - 1"
```

常见拒绝原因（`code`）：

| code | 含义 |
|------|------|
| `parse_error` | 表达式语法无法解析 |
| `too_similar` | 与因子库已有公式重复子树过大（原创性不足） |
| `too_many_literals` | 数值常量占比过高 |
| `insufficient_variables` | 行情变量（`$close` 等）多样性不足 |
| `duplicate_name` / `duplicate_expression` | 添加时名称或公式已存在 |

Portal「因子」标签页的「校验表达式」「添加到因子库」与上述 CLI 共用同一套逻辑；失败时会显示中文原因，并可展开查看 `details`（重复子树大小、匹配因子名等）。

> **注意**：默认 SQLite 因子库不需要手工处理 CSV 引号；只有显式导入/导出 CSV 时，含逗号的表达式才需要正确 CSV 引号（如 `Ref($close, 1)`）。通过 Portal 导出或 `pandas.to_csv` 会自动处理。

**管理挖掘 log 会话（CLI，可选）**：

```bash
alphapilot list_mine_logs
alphapilot delete_mine_log --session=2026-06-04_15-32-47-893456
```

### 1.5 AlphaForge 公式化因子挖掘（无需 LLM，可选）

除 LLM 驱动的 `mine` 外，本仓库还集成了从 [AlphaForge](https://github.com/DulyHao/AlphaForge) / AlphaGen 移植的**公式化**因子挖掘（不调用大模型）。挖到的因子会翻译成 AlphaPilot 因子 DSL，校验后可加入因子库（`--save`，默认开）并可选回测（`--backtest`）。依赖见 [环境准备 §2](#2-安装本仓库)（`pip install -e ".[alphaforge]"`）。

| 命令 | 方法 | 依赖 |
|------|------|------|
| `alphapilot mine_gp` | 遗传规划（gplearn），最轻量 | `.[alphaforge]` |
| `alphapilot mine_rl` | PPO 强化学习（stable-baselines3 + sb3-contrib） | `.[alphaforge]` |
| `alphapilot mine_aff` | AFF（GAN 生成器 + 预测器，论文 stage-1，表达式长度固定 20） | `.[alphaforge]` |
| `alphapilot mine_dso` | 深度符号优化（实验性） | `.[alphaforge-dso]` + 编译 cyfunc |

> **数据注意**：本仓库 baostock qlib 数据**没有 `csi300` / `csi500` 成分股集**（这些是各方法的默认值），请改用 `--instruments=test_stock_pool_80`（或 `all`，即 `<qlib_data_dir>/instruments/` 下实际存在的股票池）。

CLI 示例：

```bash
alphapilot mine_gp  --instruments=test_stock_pool_80 --population_size=200 --generations=10
alphapilot mine_rl  --instruments=test_stock_pool_80 --steps=50000 --pool_capacity=10
alphapilot mine_aff --instruments=test_stock_pool_80 --zoo_size=20 --device=cpu --backtest=True
# DSO 需先装 .[alphaforge-dso] 并编译 cyfunc（见 §2）
alphapilot mine_dso --instruments=test_stock_pool_80
```

常用参数：`--instruments`（股票池）、`--train_end_year`（默认 2020：train=[2010,end]、valid=end+1、test=end+2）、`--device`（`cpu`/`mps`/`cuda`，省略自动探测）、`--save`（加入因子库，默认 True）、`--backtest`（回测通过的因子，默认 False）；其余训练超参经 `**kwargs` 透传（如 `--top_n=50`、`--num_epochs_g=50`）。

也可在 **Portal「因子挖掘」页** 以 JSON kwargs 启动 AlphaForge（GP/RL/AFF/DSO）**后台任务**，并在任务面板查看日志 / 进度 / 取消。

详见模块文档 [alphapilot/modules/alphaforge/README.md](alphapilot/modules/alphaforge/README.md)。

### 2. 多因子回测

默认模式是 `multi_combined`：把 CSV 里的多条因子合并成一套特征，训练模型并跑组合回测，产物可在 portal「回测」页查看。

```bash
alphapilot backtest --factor_path /path/to/factors.csv
```

指定回测场景（默认 `factor_backtest`）：

```bash
alphapilot backtest --scenario factor_backtest --factor_path /path/to/factors.csv
```

CSV 示例：

```csv
factor_name,factor_expression
MACD_Factor,"MACD($close)"
RSI_Factor,"RSI($close)"
```

同样支持 `--qlib_template_dir`、`--qlib_config_name`。未传 `--qlib_config_name` 时按实验结构自动选择 yaml（通常为 `conf_cn_combined_kdd_ver.yaml`）；仅 `mine` 会默认读取 `.env` 中的 `QLIB_FACTOR_QLIB_CONFIG_NAME`。

#### 回测模式

`alphapilot backtest` 现在支持三种模式：

| `--mode` | 用途 | 主要产物 |
|----------|------|----------|
| `multi_combined`（默认） | 多因子合并训练 + 组合回测；适合正式验证一组因子 | qlib workspace、`ret.pkl`、`qlib_res.csv`，可在「回测详情」查看收益/持仓/成交 |
| `single_ic` | 不跑 qrun / 不训练模型，只逐因子计算 IC、RankIC、ICIR；适合快速筛选大量候选因子 | `factor_ic_leaderboard.csv`，可在「回测详情」的“因子排行榜”查看 |
| `multi_sequential` | 对 CSV 中每个因子分别跑一次完整组合回测；适合少量终选因子的横向比较 | `factor_portfolio_leaderboard.csv`，可在“因子排行榜”查看；耗时明显更长 |

示例：

```bash
# 快速逐因子 IC 排行
alphapilot backtest --factor_path /path/to/factors.csv --mode=single_ic

# 对每个因子分别跑完整组合回测（建议只用于少量因子）
alphapilot backtest --factor_path /path/to/factors.csv --mode=multi_sequential
```

#### 覆盖模型、策略和区间参数

`--yaml_params` 可传 JSON 字符串，也可传 `.json` / `.yaml` 文件路径，用于覆盖 `QlibYamlParams` 中的字段（模型、策略、数据区间、TopK、成本等）。未传时沿用静态模板路径，兼容旧行为。

```bash
alphapilot backtest \
  --factor_path /path/to/factors.csv \
  --mode=multi_combined \
  --yaml_params='{"topk": 30, "n_drop": 5, "backtest_start": "2024-01-01", "backtest_end": "2026-05-22"}'
```

自定义模型 / 策略时使用 `model_class`、`model_module`、`model_kwargs`、`strategy_class`、`strategy_module`、`strategy_kwargs`：

```bash
alphapilot backtest \
  --factor_path /path/to/factors.csv \
  --yaml_params='{"model_class": "LGBModel", "model_module": "qlib.contrib.model.gbdt", "strategy_class": "TopkDropoutStrategy", "strategy_module": "qlib.contrib.strategy", "strategy_kwargs": {"topk": 20, "n_drop": 5, "signal": "<PRED>"}}'
```

Portal 中也可以使用：进入「回测」页，在因子回测或策略回测表单的 JSON kwargs 中填写 `factor_path`、`mode`、`yaml_params` 等，提交后会生成后台 job。

> **Portal 入口差异**：因子库页的「回测选中因子」「回测该类别」以及 AlphaForge 的 `--backtest` 仍走默认 `multi_combined`；要选 `single_ic` / `multi_sequential` 或填 `yaml_params`，请用「回测」页的 JSON kwargs，或在「定时任务」高级 kwargs 里传 `{"mode":"single_ic", ...}`。

### 3. 策略资产复测（`strategy_backtest`）

`mine` 每轮结束后会在 `important_data/strategy_zoo/<策略名>/` 落盘策略资产（因子公式、`fitted_model.pkl`、IC 等指标、`metadata.json`）。可用独立命令对**已保存资产**重新回测，无需重跑完整挖掘流程。

**调用链**：`strategy_backtest` 模块 → `StrategySystem.backtest_from_asset` → `systems/strategy/backtest.py` → `context.backtest()`（`retrain` / `reuse_model`）。

**列出已保存策略：**

```bash
alphapilot strategy_backtest_list
```

**从资产复测（推荐在 alphapilot conda 环境下执行）：**

```bash
alphapilot strategy_backtest \
  --strategy_name='mine_round_01_20260602_164008_行为金融学假说' \
  --mode=retrain
```

| 参数 | 说明 |
|------|------|
| `--mode` | `retrain`：按资产内公式重算因子并重新训练回测；`reuse_model`：加载 `artifacts/fitted_model.pkl` 跳过训练，仍跑信号与组合回测 |
| `--qlib_data_dir` | 可选，切换 Qlib 数据目录（默认 `~/.qlib/qlib_data/cn_data/baostock/qlib`，Tushare 用 `.../tushare/qlib`） |
| `--qlib_template_dir` / `--qlib_config_name` | 可选，覆盖模板目录与 yaml；未传时优先读策略 `metadata`，否则用 `.env` 的 `QLIB_FACTOR_*` |
| `--use_local` | 与 `USE_LOCAL` 一致，是否本地执行 `qrun` |

复测结果摘要打印在终端，明细写入该策略目录下 `retests/<时间戳>_<mode>.json`。若回测 workspace 含 `ret.pkl`（及 qlib 导出的仓位文件），会额外写入同名的 `retests/<时间戳>_<mode>/` 目录，包括：

| 文件 | 内容 |
|------|------|
| `daily_report.csv` | 日频账户曲线（收益、换手、成本等） |
| `daily_trades.csv` | 每日调仓买卖明细 |
| `daily_holdings.csv` | 每日持仓明细 |
| `position_*_wide.csv` | 持仓权重/数量/价格宽表（可选） |
| `daily_indicators.csv` | 组合指标（若存在） |
| `portfolio_summary.json` | 累计收益、最大回撤等汇总 |
| `manifest.json` | 导出文件清单与 workspace 路径 |

> **注意**：请在已安装本包且能 `import alphapilot` 的 Python 环境中运行（如 `conda activate alphapilot`）。因子代码默认使用**当前解释器**执行；失败的历史 pickle 缓存不会阻止重试（仅成功结果会被缓存）。

### 3.5 每日交易信号（`daily_signals`）

在已有策略资产（或手动指定因子 CSV + 模型 pkl）的前提下，根据**上一日收盘后的现金与持仓**，生成**指定交易日**的目标调仓与持仓，并自动滚动 JSON 状态文件。适用于「不重跑整段历史回测、只推进一天」的模拟/实盘前演练。

**前提**：策略须含可用的 `fitted_model.pkl`（来自 `mine` 保存、`strategy_backtest` 或某次 `qrun` workspace 导出）；行情数据须已更新到目标日（可先 `prepare_data download`，或在命令/Portal 中勾选刷新数据）。

**查看当前持仓状态：**

```bash
alphapilot daily_state --strategy_name='mine_round_01_...'
```

**生成今日（或指定日）交易计划：**

```bash
# 从 strategy_zoo 资产（推荐）
alphapilot daily_signals --strategy_name='mine_round_01_...'

# 首次运行可指定初始资金（无状态文件时）；之后自动读 git_ignore_folder/portfolio_state/<策略>.json
alphapilot daily_signals --strategy_name='mine_round_01_...' --init_cash=500000

# 指定日期、先增量更新行情、自定义状态文件路径
alphapilot daily_signals \
  --strategy_name='mine_round_01_...' \
  --date=2026-06-18 \
  --refresh_data=True \
  --state_path=git_ignore_folder/portfolio_state/my_run.json

# 手动指定模型与 yaml 补丁（不依赖 strategy_zoo）
alphapilot daily_signals \
  --factor_path=./factors.csv \
  --model_pickle_path=important_data/strategy_zoo/.../artifacts/fitted_model.pkl \
  --yaml_params='{"topk": 15, "n_drop": 5}'
```

终端会打印当日买卖列表、目标持仓、Top 模型打分等摘要；状态 JSON 含 `date`、`cash`、`positions`（instrument → 股数）。

**Portal**：**每日交易**页 — 选择策略资产或手动填写模型 pkl / 因子 CSV / `yaml_params`，提交后作为后台 job 运行（与挖掘/回测 job 共用任务面板）。

> 日频信号走 qlib **单日** `backtest` + 静态模型打分，**不是** `qrun` 全历史重跑；与 `strategy_backtest --mode=reuse_model` 共用同一套模型与 yaml 参数语义。

### 4. 可视化工具

**推荐唯一入口**：`alphapilot portal`（统一门户，已整合原 `ui` 与 `backtest_ui` 的全部功能）。

| 命令 | 状态 | 主要用途 |
|------|------|----------|
| `alphapilot portal` | **推荐** | 新版 FastAPI + React 一站式 Web 门户：数据/因子/策略/回测、K 线、**定时任务 / 通知**、模块命令等 |
| `alphapilot portal_legacy` | 旧版回退 | Streamlit 版旧门户；用于新版前端未构建或需要临时回退时使用 |
| `alphapilot data_viz` | 可选独立 | 查看已下载股票 CSV：**K 线图**（portal「市场数据」页已内嵌，通常无需单独启动） |
| `alphapilot backtest_viz` | 可选独立 | 查看回测 workspace 产物（portal「回测」页已内嵌，通常无需单独启动） |
| `alphapilot ui` | **已弃用** | 打印重定向提示 → 请使用 portal「因子挖掘」页 |
| `alphapilot backtest_ui` | **已弃用** | 打印重定向提示 → 请使用 portal「回测」页或 `backtest_viz` |

> 说明：CLI 入口已改为 **modules-only** 分发；新增第三方模块后会自动出现在 `alphapilot modules` 与 `alphapilot portal` 页面中。

#### 4.0 股票数据 K 线可视化（`data_viz`）

查看 `prepare_data` 下载到本地的 CSV 行情（`baostock/` 与 `tushare/` 下各复权目录均可选）：

```bash
alphapilot data_viz --port 19902
```

浏览器打开 `http://localhost:19902`，可：

- 选择数据源与复权类型目录（baostock / tushare · 除权 / 前复权 / 后复权）
- 选择股票代码，并筛选时间区间（近 1/3/6/12 月或自定义）
- 查看 **K 线 + 成交量** 图；鼠标悬停显示开高低收、涨跌幅、成交额等
- 导出当前区间 CSV

#### 4.1 统一 Web 门户（推荐）

首次从源码运行新版门户前，请先确认前端已构建：

```bash
cd alphapilot/modules/portal/web
PATH=/opt/homebrew/bin:$PATH npm install --registry=https://registry.npmmirror.com
PATH=/opt/homebrew/bin:$PATH npm run build
cd -
```

然后启动 FastAPI 后端并托管前端静态文件：

```bash
alphapilot portal --port 19901
```

浏览器打开 `http://localhost:19901`。如果只想临时使用旧版 Streamlit 门户，可运行：

```bash
alphapilot portal_legacy --port 19901
```

新版门户使用 **扁平左侧导航**（支持中/英切换；顶栏显示定时任务守护进程状态；各页共用后台任务面板）：

| 菜单 | 路径 | 主要功能 |
|------|------|----------|
| 首页 | `/` | 关键指标、最近挖掘会话、快捷入口、最近任务 |
| 因子挖掘 | `/mining` | 启动 LLM / AlphaForge 挖掘；浏览/查看/删除 `log/` 会话 |
| 回测 | `/backtest` | 因子/策略回测表单、workspace 列表（可删除）、收益曲线与明细 |
| 因子/策略库 | `/library` | 因子校验/增删改、分类、导入导出；策略资产查看/导出/删除 |
| 市场数据 | `/market` | 数据下载/转换/h5、单股管理、K 线查看 |
| 每日交易 | `/daily-trade` | `daily_signals` 后台 job |
| 定时任务 | `/scheduler` | cron 式任务与「完成后通知」 |
| 通知 | `/notifications` | Telegram / 飞书 / 邮件配置与测试 |
| 高级 | `/advanced` | 系统/模块清单、JSON 命令调度、重新加载引擎 |

**本地开发**（前端热更新）：

```bash
# 终端 1
alphapilot portal --port 19901

# 终端 2
cd alphapilot/modules/portal/web && npm run dev
# 浏览器打开 http://localhost:5173
```

门户使用 `.env` 中的 `ALPHAPILOT_LOG_DIR`、`ALPHAPILOT_WORKSPACE_ROOT`、`ALPHAPILOT_FACTOR_ZOO_DIR`、`ALPHAPILOT_STRATEGY_PARAM_DIR` 等作为默认路径。

#### 4.2 挖掘日志（portal「因子挖掘」页，原 `alphapilot ui`）

在 portal「因子挖掘」页中：

- 以 JSON kwargs 启动 LLM 挖掘或 AlphaForge（GP/RL/AFF/DSO）后台 job
- 浏览 `log/` 下挖掘会话列表，打开会话内文件查看文本内容
- 删除单个 log 会话目录（**不**连带删除 `strategy_zoo` 或回测 workspace）
- 页面底部任务面板可查看 job 进度 / 日志 / 取消

> 带 Qlib 报告图、多轮假说迭代的完整 Streamlit 挖掘面板仍可通过 `alphapilot portal_legacy` 访问。`alphapilot ui` 已弃用，执行后仅打印 portal 重定向提示。

#### 4.3 回测详情（portal「回测」页，原 `alphapilot backtest_ui`）

portal「回测」页在同一屏幕内提供：上方因子/策略回测启动表单；下方 workspace 列表（可**删除**含 `ret.pkl` 的工作区）；选中 workspace 后展示收益曲线、指标、成交与持仓。列表会尽量显示 **`log/` 里对应的会话文件夹名**。数据由 backtest system 的 `BacktestResultStore` 加载，底层解析在 `systems/backtest/artifacts.py`。

「回测详情」顶部还有 **因子排行榜** 面板，会扫描 workspace 根目录下的 `*_leaderboard.csv`：

| 文件 | 来源 | 用途 |
|------|------|------|
| `factor_ic_leaderboard.csv` | `backtest --mode=single_ic` | 快速查看每个因子的 IC / RankIC / ICIR |
| `factor_portfolio_leaderboard.csv` | `backtest --mode=multi_sequential` | 对比每个因子单独跑组合回测后的指标 |

也可单独启动回测查看器（功能与 portal 子页相同）：

```bash
alphapilot backtest_viz --port 19903
```

手动指定 workspace 与 log 标题（可选）：在 log 根目录创建 `backtest_workspace_labels.json`（默认即 `log/backtest_workspace_labels.json`）：

```json
{
  "ecd2cf928a9243ee98d7649c97bb14d5": "run02_best",
  "f1c4e8f317f6431d8d7317f1a81decab": "run04_mainboard_bad"
}
```

说明：只有仍含 `ret.pkl` 的 workspace 会出现在收益详情的 workspace 下拉列表中；`single_ic` 只生成排行榜、不生成组合 `ret.pkl`，因此请在“因子排行榜”面板查看。`run01`/`run02` 若已清理旧 workspace，需重新跑完回测或用手动映射文件关联。

> `alphapilot backtest_ui` 已弃用。如需修改默认路径，请在 `.env` 中设置 `ALPHAPILOT_WORKSPACE_ROOT`（或 `ALPHAPILOT_BACKTEST_ROOT`）与 `ALPHAPILOT_LOG_DIR`。

#### 4.4 任务完成通知（portal「通知」页）

后台任务（定时任务、AlphaForge、Portal 触发的挖掘/回测/数据 job 等）结束时会推送标题、状态、Job ID 与结果摘要。支持 **Telegram**、**飞书自定义机器人 Webhook**、**SMTP 邮件** 三个频道，可并行启用。

1. 打开 portal → **通知**，填写频道凭证并 **Save**
2. 点 **Test Send** 验证（须先 Save）
3. 在 **定时任务** 创建任务时勾选「完成后通知」，或在通知页开启「所有后台任务完成都通知」

凭证默认写入 `~/.alphapilot/credentials/notify.json`（不在 git 仓库内）。服务器可用 `ALPHAPILOT_NOTIFY_*` 环境变量覆盖，详见 [§7](#7-任务完成通知alphapilotsystemsnotify) 与上方 [配置说明](#配置说明)。

### 5. 清理缓存

在 **AlphaPilot 项目根目录** 下执行。修改股票池、Qlib 模板 yaml 回测区间、`generate.py` 字段，或希望因子/回测从头跑时，建议先清缓存。

#### 缓存目录说明

| 路径 | 内容 | 何时需要清理 |
|------|------|----------------|
| `pickle_cache/mine/` | **因子挖掘**（`alphapilot mine`）的因子 `execute`、Qlib `develop` 缓存 | 改 yaml/因子后清此目录；与回测缓存互不影响 |
| `pickle_cache/backtest/` | **`backtest` / `strategy_backtest`** 等一般回测缓存 | 改 yaml/因子后清此目录 |
| `pickle_cache/`（旧版单目录） | 未设置 scope 时的回退路径 | 新项目建议用上面两个子目录 |
| `important_data/strategy_zoo/` | `mine` 保存的策略资产与 `retests/` 复测记录 | Portal「策略」或 `delete_strategy` 可删；换策略或重导资产时再清理 |
| `important_data/factor_zoo/` | 因子库 `factor_zoo.db`（校验/去重参考库；可显式导出 CSV） | Portal「因子」、`factor_validate` / `factor_add` 或 `import_factors_from_log.py` 维护 |
| `important_data/factor_qlib_templates/` | 用户自定义 Qlib 模板（yaml + `read_exp_res.py`） | 修改回测区间、组合策略参数时编辑此目录 |
| `log/` | 挖掘会话日志与 snapshot | Portal「挖掘日志」或 `delete_mine_log` 可删单会话；`clean_log_dirs.py` 可清理空目录/桩目录 |
| `important_data/stock_lists/` | 股票池 CSV（`prepare_data` 默认列表等） | 换股票池后重新 `download` / `convert` / `h5`，并同步 yaml 中 `market` |
| `git_ignore_folder/` | 工作区、回测产物、`daily_pv.h5` 副本等 | 更换股票池、重跑 `mine` / `backtest` |
| `git_ignore_folder/portfolio_state/` | `daily_signals` 滚动持仓 JSON（`<策略名>.json`） | 换策略或想从空仓重跑时删除对应文件 |
| `alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_*.h5` | 从 Qlib 导出的价量 h5 源文件 | 修改 `market`、股票池或 `generate.py` |
| `prompt_cache.db`（可选） | LLM 对话/Embedding 本地缓存（`.env` 开启缓存时） | 更换模型或希望 LLM 输出不复用旧缓存 |

Pickle 缓存相关环境变量（见 `.env.example`）：`ALPHAPILOT_PICKLE_CACHE_DIR_MINE`、`ALPHAPILOT_PICKLE_CACHE_DIR_BACKTEST`；`ALPHAPILOT_PICKLE_CACHE_ENABLED=false` 可关闭。定义位置：`alphapilot/core/conf.py`（默认根路径）、`alphapilot/core/pickle_cache.py`（按 mine/backtest 解析）。

#### 常用命令

**仅清运行缓存**（改 Qlib 模板 yaml 持仓数、训练区间等，股票池未变）：

```bash
cd /path/to/AlphaPilot

rm -rf ./pickle_cache/mine/* ./pickle_cache/backtest/*
rm -rf ./git_ignore_folder/*
```

**清运行缓存 + 价量 h5**（改股票池、`market` 或 `generate.py` 后必做）：

```bash
cd /path/to/AlphaPilot

rm -rf ./pickle_cache/mine/* ./pickle_cache/backtest/*
rm -rf ./git_ignore_folder/*
rm -f alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_all.h5
rm -f alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_debug.h5

# 重新生成 h5（或在下次 alphapilot mine 时自动生成；默认读 baostock/qlib）
alphapilot prepare_data h5
# 若使用 Tushare：alphapilot prepare_data h5 --qlib_dir ~/.qlib/qlib_data/cn_data/tushare/qlib --market <你的股票池名>
```

**一键全量清理**（运行缓存 + h5 + 可选 LLM 缓存）：

```bash
cd /path/to/AlphaPilot

rm -rf ./pickle_cache/mine/* ./pickle_cache/backtest/*
rm -rf ./git_ignore_folder/*
rm -f alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_all.h5
rm -f alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_debug.h5
rm -f ./prompt_cache.db   # 未启用 LLM 缓存时可省略

alphapilot prepare_data h5
# 若使用 Tushare：同上，加 --qlib_dir ~/.qlib/qlib_data/cn_data/tushare/qlib --market <你的股票池名>
```

清理完成后重新执行 `alphapilot mine` 或 `alphapilot backtest`。

---

## 目录结构（简要）

```
AlphaPilot/
├── alphapilot/                 # 主程序
│   ├── kernel/                 # MainEngine / Context / 配置 / 插件发现
│   ├── systems/                # 系统层（data/factor/strategy/backtest/notify）
│   │   ├── data/               # 数据下载、复权、Qlib 转换、h5（prepare_data 实现）
│   │   ├── factor/             # 因子库（factor_zoo）、结构化表达式校验（FactorValidationResult）
│   │   ├── backtest/           # 回测：engines/、pipelines/、live/（日频信号）、artifacts、qlib_yaml/
│   │   ├── strategy/           # 策略资产存储（strategy_zoo）、复测编排（backtest.py）
│   │   └── notify/             # 任务完成通知（Telegram / 飞书 / 邮件 SMTP）
│   ├── adapters/               # LLM/数据源可插拔适配层（回测见 systems/backtest/）
│   ├── modules/                # 功能模块（alpha_mining/portal/platform/data_viz/backtest_viz/strategy_backtest/daily_trade/qlib_yaml/factor_cli + 插件）
│   │   ├── alpha_mining/       # 因子挖掘（qlib 场景 + loops + conf + registry）
│   │   ├── platform/           # prepare_data、单股数据管理、modules 命令；ui/backtest_ui 弃用提示
│   │   ├── portal/             # 统一 Web 门户（FastAPI + React；legacy Streamlit 见 app.py）
│   │   │   ├── api.py          # FastAPI 后端（alphapilot portal）
│   │   │   ├── web/            # React/TypeScript 前端（npm run build → dist/）
│   │   │   ├── app.py          # Streamlit 旧版（alphapilot portal_legacy）
│   │   │   ├── jobs.py / schedules.py
│   │   ├── data_viz/           # 股票 K 线（alphapilot data_viz）
│   │   ├── backtest_viz/       # 回测详情 UI（alphapilot backtest_viz）
│   │   ├── strategy_backtest/  # 策略资产列表与复测 CLI
│   │   ├── daily_trade/        # 日频交易信号 CLI（daily_signals / daily_state）
│   │   ├── qlib_yaml/          # Qlib qrun yaml 生成与校验（qlib_yaml_generate / qlib_yaml_validate）
│   │   ├── factor/             # 因子库 CLI（factor_validate / factor_add）
│   │   ├── alphaforge/         # AlphaForge 公共层（vendor 引擎 + translate/pipeline/data_adapter，非注册模块）
│   │   ├── alphaforge_aff/     # AFF（GAN）公式化挖掘（mine_aff）
│   │   └── alphaforge_search/  # GP / RL / DSO 公式化挖掘（mine_gp / mine_rl / mine_dso）
│   └── log/ui/                 # 挖掘日志 Streamlit panel（portal_legacy 嵌入；新版 portal 经 API 读 log）
├── tests/                      # pytest（如 systems/factor/test_factor_validation.py）
├── .env.example             # 环境变量模板
├── import_factors_from_log.py  # 从 log 提取因子公式写入因子库（去重；--validate 打印拒绝原因）
├── clean_log_dirs.py        # 清理 log 下空目录与失败桩目录
├── important_data/          # 用户数据（见 important_data/README.md；strategy_zoo 等已 gitignore）
│   ├── strategy_zoo/        # mine 保存的策略与 retests/
│   ├── factor_zoo/          # 因子库 factor_zoo.db
│   ├── factor_qlib_templates/  # Qlib 回测模板（mine 默认，推荐在此改 yaml）
│   └── stock_lists/         # 股票池 CSV（prepare_data 默认列表）
└── git_ignore_folder/       # 运行产物（已 gitignore）
    ├── RD-Agent_workspace/     # 每轮回测工作区
    └── portfolio_state/        # daily_signals 滚动持仓 JSON

~/.qlib/qlib_data/cn_data/   # 行情数据根目录（不在仓库内）
    ├── baostock/             # baostock CSV、download_state.csv、qlib 二进制
    └── tushare/              # Tushare CSV、download_state.csv、qlib 二进制

~/.alphapilot/credentials/   # Portal 通知频道凭证（notify.json，不在仓库内）
```

---

## 开发与测试

```bash
pip install -e .
python -m pytest tests/systems/factor/test_factor_validation.py -v
```

当前包含因子表达式结构化校验（`FactorValidationResult`）、因子库添加拦截、Portal 文案格式化、CLI 模块等用例。

---

## 致谢

本项目基于论文 **[AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay](https://arxiv.org/abs/2502.16789)**（KDD 2025）及其开源实现 [RndmVariableQ/AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent) 进行开发与定制。实现思路亦参考 [RD-Agent](https://github.com/microsoft/RD-Agent)。感谢原作者与社区的工作。

若使用原论文方法，请引用：

```bibtex
@misc{tang2025alphaagentllmdrivenalphamining,
      title={AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay},
      author={Ziyi Tang and Zechuan Chen and Jiarui Yang and Jiayao Mai and Yongsen Zheng and Keze Wang and Jinrui Chen and Liang Lin},
      year={2025},
      eprint={2502.16789},
      archivePrefix={arXiv},
      primaryClass={cs.CE},
      url={https://arxiv.org/abs/2502.16789},
}
```
