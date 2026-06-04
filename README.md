# AlphaPilot

基于 [AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent)（KDD 2025）的本地化 fork，面向 A 股因子挖掘与 Qlib 回测。本仓库在保留原项目核心流程（假设生成 → 因子构造 → 回测评估）的基础上，增加了 API 兼容、回测可视化等改动，便于在本地环境稳定运行。

---

## 项目简介

AlphaPilot 通过三个 Agent 协作完成因子挖掘：

| Agent | 职责 |
|-------|------|
| **Idea Agent** | 根据市场假说提出可验证的因子方向 |
| **Factor Agent** | 将假说转化为因子表达式并生成代码 |
| **Eval Agent** | 用 Qlib 回测评估因子，并反馈迭代 |

本仓库使用 [Qlib](https://github.com/microsoft/qlib) 作为回测引擎，使用 OpenAI 兼容 API 调用大模型。

---

## 相对原版的改动说明

### 1. LLM JSON 解析容错（`alphapilot/oai/llm_utils.py`）

适配 MiniMax 等推理模型的非标准 JSON 输出（代码块包裹、尾逗号、推理块等），新增 `extract_and_validate_llm_json()`，降低因子构造阶段 `json.loads` 失败概率。

### 2. 回测结果可视化（`alphapilot/app/backtest_viewer/`）

在原版 `alphapilot ui`（运行日志总览）之外，新增独立的回测查看器 `backtest_ui`，支持：

- 收益曲线、超额收益、回撤
- 日换手与成本
- 当日成交、持仓明细

CLI 入口：`alphapilot backtest_ui`（见下方使用流程）。原版日志界面仍使用 `alphapilot ui`，并新增统一门户 `alphapilot portal` 作为推荐入口。

### 3. 数据准备命令（`alphapilot prepare_data`）

- 内置原 qlib `dump_bin.py`、`future_calendar_collector.py`（无需 clone qlib 仓库）
- 通过 baostock 下载行情：支持**直接下载前/后复权**（`--adjust_mode forward|backward`），或下载除权日线 + 复权因子后用 `apply_adjust` 本地合成，再 `convert` 为 Qlib 与 `daily_pv.h5`
- 默认股票列表：`backup_data/main_stock_2026_4_27.csv`

> 当前 CLI 已改为 **modules-only** 分发，`prepare_data` 由内置 `platform` 模块提供。  
> 从本地化重构版本起，`prepare_data` 的各 action 统一经由 **data system** 调度（单一入口），避免模块层直接分支调用。  
> 数据下载、复权、Qlib 转换、h5 生成等**核心实现位于** `alphapilot/systems/data/`（`app/data` 兼容层已移除）。  
> 你可以继续使用原有风格：`alphapilot prepare_data download ...`，也可使用显式 action 风格：`alphapilot prepare_data --action download ...`。

示例（两种写法等价）：

```bash
# 旧写法（仍可用）
alphapilot prepare_data download --stock_csv backup_data/main_stock_2026_4_27.csv

# 新写法（modules-only 语义更清晰）
alphapilot prepare_data --action download --stock_csv backup_data/main_stock_2026_4_27.csv
```

### 4. 回测与因子数据配置

**内置模板**（`alphapilot/modules/alpha_mining/qlib/experiment/factor_template/`）：

| 文件 | 用途 |
|------|------|
| `conf.yaml` | 基线回测（仅内置价量特征） |
| `conf_cn_combined_kdd_ver.yaml` | 合并 LLM 新因子后的回测（`mine` 多轮常用） |
| `read_exp_res.py` | `qrun` 后导出 IC、收益等到 `qlib_res.csv` / `ret.pkl` |

**自定义模板目录（推荐二开）**：可将上述文件复制到 `important_data/factor_qlib_templates/` 后只改副本，避免动仓库内置配置。说明见该目录下 [README.md](important_data/factor_qlib_templates/README.md)。

**可选环境变量**（前缀 `QLIB_FACTOR_`，在 `.env` 中配置；CLI 参数优先）：

| 变量 | 含义 |
|------|------|
| `QLIB_FACTOR_QLIB_TEMPLATE_DIR` | 拷入 workspace 的模板目录（相对项目根，如 `important_data/factor_qlib_templates`） |
| `QLIB_FACTOR_QLIB_CONFIG_NAME` | 上述目录中的 yaml 文件名（如 `conf_cn_combined_kdd_ver.yaml`） |

`alphapilot prepare_data h5` 会从 Qlib 导出 `daily_pv.h5` 到 `git_ignore_folder/factor_implementation_source_data*`，供因子 Python 代码使用。

可按需修改股票池（`market` / `instruments`）、训练/验证/测试区间、持仓数量等。

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
- `mine/backtest/strategy_backtest/prepare_data/ui/backtest_ui/portal` 统一由模块贡献命令（modules-only）

**数据系统代码位置（供二开参考）**

| 模块 | 路径 | 职责 |
|------|------|------|
| CLI 编排 | `systems/data/prepare_data.py` | `PrepareDataCLI`，对应 `alphapilot prepare_data` 各子命令 |
| 下载 | `systems/data/prepare_cn.py` | baostock 下载、复权因子刷新 |
| 复权 | `systems/data/adjust_prices.py` | 除权 CSV 本地合成前/后复权 |
| Qlib 转换 | `systems/data/qlib_convert.py` | CSV → Qlib 二进制 |
| h5 导出 | `systems/data/generate_h5.py` | 生成 `daily_pv.h5` |
| dump 工具 | `systems/data/qlib_dump/` | `dump_bin`、交易日历扩展 |
| 系统 API | `systems/data/service.py` | `QlibDataSystem` 与 typed DTO（`types.py`） |

程序化调用示例：

```python
from alphapilot.kernel import build_engine
from alphapilot.systems.data.types import DataDownloadCommand

engine = build_engine()
data = engine.get_system("data")
data.run_download(DataDownloadCommand(
    start_date="2005-01-01",
    stock_csv="backup_data/main_stock_2026_4_27.csv",
    options={"adjust_mode": "backward"},
))
```

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

安装后 CLI 命令为 **`alphapilot`**（例如 `alphapilot mine`）。若你此前安装过旧包名 `alphaagent`，请先 `pip uninstall alphaagent` 再重新 `pip install -e .`。

可选环境变量前缀已由 `ALPHAAGENT_*` 统一为 **`ALPHAPILOT_*`**（如 `ALPHAPILOT_QLIB_DATA_DIR`、`ALPHAPILOT_WORKSPACE_ROOT`）。旧前缀不再读取。

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

# 后复权（写入 ~/.qlib/qlib_data/cn_data/raw_data_back_adjust）
alphapilot prepare_data download \
  --stock_csv backup_data/main_stock_2026_4_27.csv \
  --adjust_mode backward

# 或前复权（写入 raw_data_forward_adjust）
# alphapilot prepare_data download \
#   --stock_csv backup_data/main_stock_2026_4_27.csv \
#   --adjust_mode forward

# 转 Qlib + 日历 + h5（adjust_mode 与下载时一致）
alphapilot prepare_data convert \
  --stock_csv backup_data/main_stock_2026_4_27.csv \
  --adjust_mode backward \
  --market main_stock_2026_4_27
```

同样支持增量：再次执行 `download` 只会补最新交易日。中文别名：`前复权`、`后复权`。

#### 方式 B：除权 + 本地复权（默认，便于核对因子）

先下除权价与复权因子，再在本地合成前/后复权 CSV，适合需要自行核对除权因子、或希望与本地 `apply_adjust` 逻辑一致时使用。

```bash
cd AlphaPilot

# 1) 仅下载：除权行情（增量）+ 复权因子（每次更新行情后全量覆盖）
alphapilot prepare_data download --stock_csv backup_data/main_stock_2026_4_27.csv --adjust_mode none

# 2) 合成为前复权或后复权 CSV（供训练 / convert）
alphapilot prepare_data apply_adjust --adjust_mode backward
# alphapilot prepare_data apply_adjust --adjust_mode forward

# 若早期复权价仍等于除权价，先刷新全历史复权因子（自 1990 年起）
alphapilot prepare_data refresh_factors --stock_csv backup_data/main_stock_2026_4_27.csv

# 3) 转 Qlib + 日历 + h5（data_path / adjust_mode 与上一步复权类型一致）
alphapilot prepare_data convert \
  --stock_csv backup_data/main_stock_2026_4_27.csv \
  --adjust_mode backward \
  --market main_stock_2026_4_27
```

一键全流程（方式 B：下载除权 → 本地复权 → convert）：

```bash
alphapilot prepare_data pipeline \
  --stock_csv backup_data/main_stock_2026_4_27.csv \
  --target_mode forward
```

**指定股票列表**

```bash
alphapilot prepare_data download --stock_csv my_stocks.csv --code_column ts_code
alphapilot prepare_data download --stock_csv watchlist.txt --market watchlist
alphapilot prepare_data download --all_market True
```

`--adjust_mode` / `--target_mode` 支持：`none`（除权/不复权）、`forward`（前复权）、`backward`（后复权），以及中文 `除权`、`前复权`、`后复权`。

支持的代码格式：`300001.SZ`、`sz.300001`、`SH600000`、纯 6 位数字。

下载后会写入 `instruments/{market}.txt`，**请在** `conf.yaml` **里把** `market` **改成同名**。

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

默认路径：

| 参数 | 默认值 |
|------|--------|
| `--stock_csv` | `backup_data/main_stock_2026_4_27.csv` |
| `--market` | 与 `stock_csv` 文件名相同 |
| `download` 默认 `--adjust_mode` | `none`（除权）；设为 `forward` / `backward` 则直接下载已复权 CSV |
| CSV 除权 | `~/.qlib/qlib_data/cn_data/raw_data_no_adjust` |
| CSV 前复权 / 后复权 | `raw_data_forward_adjust` / `raw_data_back_adjust`（可直接 `download` 写入，或由 `apply_adjust` 生成） |
| 复权因子 | `~/.qlib/qlib_data/cn_data/adjust_factors`（仅 `adjust_mode=none` 时下载） |
| Qlib 数据 | `~/.qlib/qlib_data/cn_data` |

如需指数成分股文件，仍可在 qlib 源码中运行 `cn_index/collector.py`（可选）；若使用自定义股票池，在 `~/.qlib/qlib_data/cn_data/instruments/` 下维护 `.txt`，并在 `conf.yaml` 中设置 `market`。

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

# 可选：Qlib 回测模板与 yaml（mine / backtest / strategy_backtest 共用 QLIB_FACTOR_ 前缀）
# QLIB_FACTOR_QLIB_TEMPLATE_DIR=important_data/factor_qlib_templates
# QLIB_FACTOR_QLIB_CONFIG_NAME=conf_cn_combined_kdd_ver.yaml

# 可选：因子 factor.py 子进程 Python（默认当前解释器 sys.executable）
# FACTOR_CoSTEER_PYTHON_BIN=/path/to/python
```

---

## 使用流程

### 0. 查看当前可用模块与命令（推荐先执行）

```bash
alphapilot modules
```

输出会列出当前内置模块与通过 `entry_points` 自动发现的第三方模块，以及每个模块暴露的命令。新增插件后，这里和 `alphapilot portal` 页面都会自动出现。

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

回测工作区与日志默认在 `git_ignore_folder/` 下。

### 2. 多因子回测

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

同样支持 `--qlib_template_dir`、`--qlib_config_name`（或 `.env` 中的 `QLIB_FACTOR_*`）。

### 3. 策略资产复测（`strategy_backtest`）

`mine` 每轮结束后会在 `important_data/strategy_zoo/<策略名>/` 落盘策略资产（因子公式、`fitted_model.pkl`、IC 等指标、`metadata.json`）。可用独立命令对**已保存资产**重新回测，无需重跑完整挖掘流程。

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
| `--mode` | `retrain`：按资产内公式重算因子并重新训练回测；`reuse_model`：尝试复用已保存模型；`both`：两种都跑 |
| `--qlib_data_dir` | 可选，切换 Qlib 数据目录（不设则用默认 `~/.qlib/...`） |
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

### 4. 可视化工具

项目提供四个 Streamlit 界面，用途不同：

| 命令 | 来源 | 主要用途 |
|------|------|----------|
| `alphapilot portal` | 本仓库新增（modules 统一入口） | 一站式 Web 门户：系统状态、股票/因子/模型信息、导入导出、动态模块列表与命令执行 |
| `alphapilot data_viz` | 本仓库新增 | 查看已下载股票 CSV：**K 线图**、时间段筛选、鼠标悬停 OHLCV 详情 |
| `alphapilot ui` | 原版自带 | 查看因子挖掘**运行日志**（假说、因子代码、反馈、Qlib 报告图等） |
| `alphapilot backtest_ui` | 本仓库新增 | 查看单次回测**交易与收益**（持仓、成交、收益曲线等） |

> 说明：CLI 入口已改为 **modules-only** 分发，`mine/backtest/strategy_backtest/prepare_data/ui/backtest_ui/portal` 均由内置模块提供；新增第三方模块后会自动出现在 `alphapilot modules` 与 `alphapilot portal` 页面中。

#### 4.0 股票数据 K 线可视化（`data_viz`）

查看 `prepare_data` 下载到本地的 CSV 行情（默认在 `~/.qlib/qlib_data/cn_data/raw_data_*`）：

```bash
alphapilot data_viz --port 19902
```

浏览器打开 `http://localhost:19902`，可：

- 选择复权类型目录（除权 / 前复权 / 后复权）
- 选择股票代码，并筛选时间区间（近 1/3/6/12 月或自定义）
- 查看 **K 线 + 成交量** 图；鼠标悬停显示开高低收、涨跌幅、成交额等
- 导出当前区间 CSV

#### 4.1 统一 Web 门户（推荐）

```bash
alphapilot portal --port 19901
```

浏览器打开 `http://localhost:19901`，可在一个页面中访问：
- Data/Factor/Strategy/Backtest 四大系统能力
- **股票 K 线** 标签页（内嵌 `data_viz`，无需单独开 `data_viz` 服务）
- 模块动态列表（自动显示新插件/新包）
- 模块命令调度（JSON 参数）
- 因子库与模型参数导入导出

#### 4.2 运行日志可视化（原版 `alphapilot ui`）

用于监控 `alphapilot mine` 的完整迭代过程，包括每轮假说、因子表达式、代码反馈、回测指标图表等。

```bash
alphapilot ui --port 19899 --log_dir log/
```

浏览器打开 `http://localhost:19899`。`log_dir` 指向运行产生的日志目录，默认为项目下的 `log/`（若你修改过日志输出路径，请对应调整）。

开启调试模式：

```bash
alphapilot ui --port 19899 --log_dir log/ --debug
```

#### 4.3 回测结果可视化（本仓库 `backtest_ui`）

用于查看某次 Qlib 回测工作区的明细结果，适合分析具体某轮回测的持仓与收益。

```bash
alphapilot backtest_ui --port 19900
```

浏览器打开 `http://localhost:19900`，在界面中选择 `git_ignore_folder/RD-Agent_workspace` 下含 `ret.pkl` 的工作区目录。下拉列表会尽量显示 **`log/` 里对应的会话文件夹名**（如 `run02_best`）：默认按 **workspace 与 log 目录的创建时间一一对应**（`run01` → `run02_best` → `run03_…` → `run04_…`）；同一 log 下多次回测会显示为 `run04_mainboard_bad (05-25 16:24)` 等。若仍不对，可在 `log/backtest_workspace_labels.json` 里手动指定（见下）。

手动指定 workspace 与 log 标题（可选）：

```json
{
  "ecd2cf928a9243ee98d7649c97bb14d5": "run02_best",
  "f1c4e8f317f6431d8d7317f1a81decab": "run04_mainboard_bad"
}
```

说明：只有仍含 `ret.pkl` 的 workspace 会出现在列表中；`run01`/`run02` 若已清理旧 workspace，需重新跑完回测或用手动映射文件关联。

指定工作区根目录与 log 目录：

```bash
alphapilot backtest_ui --workspace_root /path/to/git_ignore_folder/RD-Agent_workspace --log_dir log/
```

### 5. 清理缓存

在 **AlphaPilot 项目根目录** 下执行。修改股票池、`conf.yaml` 回测区间、`generate.py` 字段，或希望因子/回测从头跑时，建议先清缓存。

#### 缓存目录说明

| 路径 | 内容 | 何时需要清理 |
|------|------|----------------|
| `pickle_cache/` | 因子计算、Qlib 回测等步骤的 pickle 缓存 | 修改回测参数、因子逻辑，或结果异常需重跑；**因子 `execute` 仅缓存成功结果**，旧失败条目会在下次执行时自动丢弃 |
| `important_data/strategy_zoo/` | `mine` 保存的策略资产与 `retests/` 复测记录 | 一般无需删；换策略或只想重导资产时再清理 |
| `important_data/factor_qlib_templates/` | 用户自定义 Qlib 模板（yaml + `read_exp_res.py`） | 修改回测区间、组合策略参数时编辑此目录 |
| `git_ignore_folder/` | 工作区、回测产物、`daily_pv.h5` 副本等 | 更换股票池、重跑 `mine` / `backtest` |
| `alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_*.h5` | 从 Qlib 导出的价量 h5 源文件 | 修改 `market`、股票池或 `generate.py` |
| `prompt_cache.db`（可选） | LLM 对话/Embedding 本地缓存（`.env` 开启缓存时） | 更换模型或希望 LLM 输出不复用旧缓存 |

#### 常用命令

**仅清运行缓存**（改 `conf.yaml` 持仓数、训练区间等，股票池未变）：

```bash
cd /path/to/AlphaPilot

rm -rf ./pickle_cache/*
rm -rf ./git_ignore_folder/*
```

**清运行缓存 + 价量 h5**（改股票池、`market` 或 `generate.py` 后必做）：

```bash
cd /path/to/AlphaPilot

rm -rf ./pickle_cache/*
rm -rf ./git_ignore_folder/*
rm -f alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_all.h5
rm -f alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_debug.h5

# 重新生成 h5（或在下次 alphapilot mine 时自动生成）
alphapilot prepare_data h5
```

**一键全量清理**（运行缓存 + h5 + 可选 LLM 缓存）：

```bash
cd /path/to/AlphaPilot

rm -rf ./pickle_cache/*
rm -rf ./git_ignore_folder/*
rm -f alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_all.h5
rm -f alphapilot/modules/alpha_mining/qlib/experiment/factor_data_template/daily_pv_debug.h5
rm -f ./prompt_cache.db   # 未启用 LLM 缓存时可省略

alphapilot prepare_data h5
```

清理完成后重新执行 `alphapilot mine` 或 `alphapilot backtest`。

---

## 目录结构（简要）

```
AlphaPilot/
├── alphapilot/                 # 主程序
│   ├── kernel/                 # MainEngine / Context / 配置 / 插件发现
│   ├── systems/                # 四大系统（data/factor/strategy/backtest）
│   │   └── data/               # 数据下载、复权、Qlib 转换、h5（prepare_data 实现）
│   ├── adapters/               # LLM/数据源等外部接口适配层
│   ├── modules/                # 功能模块（alpha_mining/platform/strategy_backtest + 插件）
│   │   ├── alpha_mining/       # 因子挖掘（qlib 场景 + loops + conf + registry）
│   │   └── strategy_backtest/  # 策略资产列表与复测 CLI
│   ├── systems/strategy/       # 策略资产存储（strategy_zoo）与复测编排
│   ├── app/portal/             # 统一 Web 门户（alphapilot portal）
│   ├── app/backtest_viewer/    # 回测结果可视化（alphapilot backtest_ui）
│   └── log/ui/                 # 运行日志可视化（alphapilot ui）
├── .env.example             # 环境变量模板
├── important_data/          # 策略资产与 Qlib 模板（已 gitignore）
│   ├── strategy_zoo/        # mine 保存的策略与 retests/
│   └── factor_qlib_templates/  # 可选：自定义 Qlib 回测模板
└── git_ignore_folder/       # 运行产物（已 gitignore）
    └── RD-Agent_workspace/     # 每轮回测工作区

~/.qlib/qlib_data/cn_data/   # Qlib 行情数据（不在仓库内）
```

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
