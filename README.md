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

### 2. 回测结果可视化（`alphapilot/modules/backtest_viz/` + `systems/backtest/artifacts.py`）

在原版 `alphapilot ui`（运行日志总览）之外，新增回测查看器（`backtest_viz` / portal「回测详情」），支持：

- 收益曲线、超额收益、回撤
- 日换手与成本
- 当日成交、持仓明细

原独立界面 `alphapilot ui` / `alphapilot backtest_ui` 已整合进统一门户 `alphapilot portal`（见下方使用流程）。

### 3. 数据准备命令（`alphapilot prepare_data`）

- 内置原 qlib `dump_bin.py`、`future_calendar_collector.py`（无需 clone qlib 仓库）
- 通过 baostock 下载行情：支持**直接下载前/后复权**（`--adjust_mode forward|backward`），或下载除权日线 + 复权因子后用 `apply_adjust` 本地合成，再 `convert` 为 Qlib 与 `daily_pv.h5`
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

### 4. 回测与因子数据配置

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
| `alphapilot backtest` | 未传 `--qlib_config_name` 时，按实验结构自动选：有 `based_experiments` → `conf_cn_combined_kdd_ver.yaml`，否则 `conf.yaml` | 一般 backtest 也会落到 combined |
| `alphapilot strategy_backtest` | 策略 `metadata` 中的记录，否则 `.env` 的 `QLIB_FACTOR_*` | 与 mine 保存时写入的 yaml 名一致 |

模板目录默认优先 `important_data/factor_qlib_templates/`（目录存在时），与是否配置 `.env` 无关；`QLIB_FACTOR_QLIB_TEMPLATE_DIR` 用于显式指定或覆盖。

**二开建议**：将内置模板复制到 `important_data/factor_qlib_templates/` 后只改副本，避免动仓库内置配置。模板说明见 [important_data/factor_qlib_templates/README.md](important_data/factor_qlib_templates/README.md)。

> `alphapilot/modules/alpha_mining/qlib/experiment/factor_template/` 为历史副本，**运行时不会**作为 `qrun` 模板目录；请以 `important_data/factor_qlib_templates/` 或 `systems/backtest/qlib/templates/factor_template/` 为准。

**可选环境变量**（前缀 `QLIB_FACTOR_`，在 `.env` 中配置；CLI 参数优先）：

| 变量 | 含义 |
|------|------|
| `QLIB_FACTOR_QLIB_TEMPLATE_DIR` | 拷入 workspace 的模板目录（相对项目根，如 `important_data/factor_qlib_templates`） |
| `QLIB_FACTOR_QLIB_CONFIG_NAME` | 上述目录中的 yaml 文件名（如 `conf_cn_combined_kdd_ver.yaml`） |

`alphapilot prepare_data h5` 会从 Qlib 导出 `daily_pv.h5` 到 `git_ignore_folder/factor_implementation_source_data*`，供因子 Python 代码使用。

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
- 策略复测编排收拢到 `alphapilot/systems/strategy/backtest.py`，经 `context.backtest()` 执行，**不再**经 `alpha_mining` 模块中转
- 挖掘日志 UI（`alphapilot/log/ui/`）通过 `core.scenario.Scenario` 的 UI trait 分支渲染，**不再 import** `alpha_mining` 具体场景类
- adapter 层仅保留 **LLM + 数据源** 可插拔边界；已移除未接入主路径的 backtest engine adapter（`get_backtest_engine`），回测统一经 `systems/backtest/` 执行（详见 [alphapilot/adapters/README.md](alphapilot/adapters/README.md)）

**数据系统代码位置（供二开参考）**

| 模块 | 路径 | 职责 |
|------|------|------|
| CLI 编排 | `systems/data/prepare_data.py` | `PrepareDataCLI`，对应 `alphapilot prepare_data` 各子命令 |
| 下载 | `systems/data/prepare_cn.py` | baostock 下载、复权因子刷新 |
| 复权 | `systems/data/adjust_prices.py` | 除权 CSV 本地合成前/后复权 |
| Qlib 转换 | `systems/data/qlib_convert.py` | CSV → Qlib 二进制 |
| h5 导出 | `systems/data/generate_h5.py` | 生成 `daily_pv.h5` |
| dump 工具 | `systems/data/qlib_dump/` | `dump_bin`、交易日历扩展 |
| 单股管理 | `systems/data/manage.py` | 单只股票的删除 / 裁剪 / 单股重 dump（`delete_symbol`、`trim_symbol`、`resync_symbol_to_qlib`、instruments 增删改） |
| 系统 API | `systems/data/service.py` | `QlibDataSystem` 与 typed DTO（`types.py`） |
| 路径约定 | `kernel/paths.py` | `important_data_dir`、`strategy_zoo_dir`、`factor_zoo_dir`、`stock_lists_dir`、默认 `stock_csv`、旧路径 remap |

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
- Portal「数据」标签也内嵌了同一套删除 / 刷新 / 裁剪控件与「重建 daily_pv h5」按钮。

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
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode backward

# 或前复权（写入 raw_data_forward_adjust）
# alphapilot prepare_data download \
#   --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
#   --adjust_mode forward

# 转 Qlib + 日历 + h5（adjust_mode 与下载时一致）
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

# 1) 仅下载：除权行情（增量）+ 复权因子（每次更新行情后全量覆盖）
alphapilot prepare_data download --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv --adjust_mode none

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

默认路径：

| 参数 | 默认值 |
|------|--------|
| `--stock_csv` | `important_data/stock_lists/main_stock_2026_4_27.csv` |
| `--market` | 与 `stock_csv` 文件名相同 |
| `download` 默认 `--adjust_mode` | `none`（除权）；设为 `forward` / `backward` 则直接下载已复权 CSV |
| CSV 除权 | `~/.qlib/qlib_data/cn_data/raw_data_no_adjust` |
| CSV 前复权 / 后复权 | `raw_data_forward_adjust` / `raw_data_back_adjust`（可直接 `download` 写入，或由 `apply_adjust` 生成） |
| 复权因子 | `~/.qlib/qlib_data/cn_data/adjust_factors`（仅 `adjust_mode=none` 时下载） |
| Qlib 数据 | `~/.qlib/qlib_data/cn_data` |

如需指数成分股文件，仍可在 qlib 源码中运行 `cn_index/collector.py`（可选）；若使用自定义股票池，在 `~/.qlib/qlib_data/cn_data/instruments/` 下维护 `.txt`，并在 Qlib 模板 yaml 中设置 `market`（与 `convert` 时 `--market` 一致）。

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

# 可选：Qlib 回测模板与 yaml（mine / backtest / strategy_backtest 共用 QLIB_FACTOR_ 前缀）
# QLIB_FACTOR_QLIB_TEMPLATE_DIR=important_data/factor_qlib_templates
# QLIB_FACTOR_QLIB_CONFIG_NAME=conf_cn_combined_kdd_ver.yaml

# 可选：门户 / 回测可视化默认路径（portal、backtest_viz 共用）
# ALPHAPILOT_LOG_DIR=./log
# ALPHAPILOT_WORKSPACE_ROOT=git_ignore_folder/RD-Agent_workspace
# ALPHAPILOT_BACKTEST_ROOT=git_ignore_folder/RD-Agent_workspace

# 可选：因子 factor.py 子进程 Python（默认当前解释器 sys.executable）
# FACTOR_CoSTEER_PYTHON_BIN=/path/to/python
```

---

## 使用流程

### 0. 查看当前可用模块与命令（推荐先执行）

```bash
alphapilot modules
```

输出会列出当前内置模块与通过 `entry_points` 自动发现的第三方模块，以及每个模块暴露的命令（含 `qlib_yaml_generate` / `qlib_yaml_validate`、`factor_validate` / `factor_add`）。新增插件后，这里和 `alphapilot portal` 页面都会自动出现。

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

回测工作区默认在 `git_ignore_folder/RD-Agent_workspace/`；挖掘日志在 `log/`。因子库 CSV 默认在 `important_data/factor_zoo/factor_zoo.csv`（与策略资产一样长期保留，可用 Portal 或 API 管理）。

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

# 校验通过后写入 important_data/factor_zoo/factor_zoo.csv
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

> **注意**：`factor_zoo.csv` 中含逗号的表达式须使用正确 CSV 引号（如 `Ref($close, 1)`）；通过 Portal 保存或 `pandas.to_csv` 会自动处理，手工编辑时请为含逗号字段加引号。

**管理挖掘 log 会话（CLI，可选）**：

```bash
alphapilot list_mine_logs
alphapilot delete_mine_log --session=2026-06-04_15-32-47-893456
```

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

同样支持 `--qlib_template_dir`、`--qlib_config_name`。未传 `--qlib_config_name` 时按实验结构自动选择 yaml（通常为 `conf_cn_combined_kdd_ver.yaml`）；仅 `mine` 会默认读取 `.env` 中的 `QLIB_FACTOR_QLIB_CONFIG_NAME`。

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
| `--mode` | `retrain`：按资产内公式重算因子并重新训练回测；`reuse_model`：加载 `artifacts/fitted_model.pkl` 跳过训练，仍跑信号与组合回测；`both`：两种都跑 |
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

**推荐唯一入口**：`alphapilot portal`（统一门户，已整合原 `ui` 与 `backtest_ui` 的全部功能）。

| 命令 | 状态 | 主要用途 |
|------|------|----------|
| `alphapilot portal` | **推荐** | 一站式 Web 门户：数据/因子/策略/回测、**挖掘日志**、**回测详情**、K 线、模块命令等 |
| `alphapilot data_viz` | 可选独立 | 查看已下载股票 CSV：**K 线图**（门户「股票 K 线」标签已内嵌，通常无需单独启动） |
| `alphapilot backtest_viz` | 可选独立 | 查看回测 workspace 产物（门户「回测 → 回测详情」已内嵌，通常无需单独启动） |
| `alphapilot ui` | **已弃用** | 打印重定向提示 → 请使用 portal「挖掘日志」标签 |
| `alphapilot backtest_ui` | **已弃用** | 打印重定向提示 → 请使用 portal「回测 → 回测详情」或 `backtest_viz` |

> 说明：CLI 入口已改为 **modules-only** 分发；新增第三方模块后会自动出现在 `alphapilot modules` 与 `alphapilot portal` 页面中。

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
- **数据** 标签页：查看路径、加载股票池、运行数据操作，并提供**单股管理**（**删除/刷新/裁剪单只股票**，自动单股重 dump + 「重建 daily_pv h5」按钮）
- **因子** 标签页：校验/添加表达式（**失败时显示具体原因**：语法、与库内过于相似、重名等）、导入导出、**删除单条因子**（`important_data/factor_zoo/factor_zoo.csv`）
- **策略** 标签页：查看/保存策略参数、**删除整个策略资产文件夹**
- **股票 K 线** 标签页（内嵌 `data_viz`）
- **挖掘日志** 标签页（原 `alphapilot ui`：假说、因子代码、反馈、Qlib 报告图等；支持**删除当前 log 会话**）
- **回测** 标签页含两个子页：**运行列表**（可**删除 workspace**）+ **回测详情**（内嵌 `backtest_viz`，原 `alphapilot backtest_ui`）
- 模块动态列表与 JSON 命令调度

门户使用 `.env` 中的 `ALPHAPILOT_LOG_DIR`、`ALPHAPILOT_WORKSPACE_ROOT`、`ALPHAPILOT_FACTOR_ZOO_DIR`、`ALPHAPILOT_STRATEGY_PARAM_DIR` 等作为默认路径。

#### 4.2 挖掘日志（portal「挖掘日志」标签，原 `alphapilot ui`）

用于监控 `alphapilot mine` 的完整迭代过程。在 portal 的「挖掘日志」标签中：
- 选择 `log/` 下的会话目录并刷新
- 查看每轮假说、因子表达式、代码演化、回测反馈与指标图表
- 支持 Start/Stop Mining API（若后端服务可用）
- 勾选确认后可删除当前 log 会话目录（**不**会连带删除 `strategy_zoo` 或回测 workspace）

> `alphapilot ui` 已弃用，执行后仅打印 portal 重定向提示。

#### 4.3 回测详情（portal「回测 → 回测详情」，原 `alphapilot backtest_ui`）

在 portal「回测」标签的「运行列表」子页可列出并**删除**含 `ret.pkl` 的 workspace；「回测详情」子页中选择 `git_ignore_folder/RD-Agent_workspace` 下的工作区，查看收益曲线、持仓、成交等。下拉列表会尽量显示 **`log/` 里对应的会话文件夹名**。数据由 backtest system 的 `BacktestResultStore` 加载，底层解析在 `systems/backtest/artifacts.py`。

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

说明：只有仍含 `ret.pkl` 的 workspace 会出现在列表中；`run01`/`run02` 若已清理旧 workspace，需重新跑完回测或用手动映射文件关联。

> `alphapilot backtest_ui` 已弃用。如需修改默认路径，请在 `.env` 中设置 `ALPHAPILOT_WORKSPACE_ROOT`（或 `ALPHAPILOT_BACKTEST_ROOT`）与 `ALPHAPILOT_LOG_DIR`。

### 5. 清理缓存

在 **AlphaPilot 项目根目录** 下执行。修改股票池、Qlib 模板 yaml 回测区间、`generate.py` 字段，或希望因子/回测从头跑时，建议先清缓存。

#### 缓存目录说明

| 路径 | 内容 | 何时需要清理 |
|------|------|----------------|
| `pickle_cache/mine/` | **因子挖掘**（`alphapilot mine`）的因子 `execute`、Qlib `develop` 缓存 | 改 yaml/因子后清此目录；与回测缓存互不影响 |
| `pickle_cache/backtest/` | **`backtest` / `strategy_backtest`** 等一般回测缓存 | 改 yaml/因子后清此目录 |
| `pickle_cache/`（旧版单目录） | 未设置 scope 时的回退路径 | 新项目建议用上面两个子目录 |
| `important_data/strategy_zoo/` | `mine` 保存的策略资产与 `retests/` 复测记录 | Portal「策略」或 `delete_strategy` 可删；换策略或重导资产时再清理 |
| `important_data/factor_zoo/` | 因子库 `factor_zoo.csv`（校验/去重参考库） | Portal「因子」、`factor_validate` / `factor_add` 或 `import_factors_from_log.py` 维护 |
| `important_data/factor_qlib_templates/` | 用户自定义 Qlib 模板（yaml + `read_exp_res.py`） | 修改回测区间、组合策略参数时编辑此目录 |
| `log/` | 挖掘会话日志与 snapshot | Portal「挖掘日志」或 `delete_mine_log` 可删单会话；`clean_log_dirs.py` 可清理空目录/桩目录 |
| `important_data/stock_lists/` | 股票池 CSV（`prepare_data` 默认列表等） | 换股票池后重新 `download` / `convert` / `h5`，并同步 yaml 中 `market` |
| `git_ignore_folder/` | 工作区、回测产物、`daily_pv.h5` 副本等 | 更换股票池、重跑 `mine` / `backtest` |
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

# 重新生成 h5（或在下次 alphapilot mine 时自动生成）
alphapilot prepare_data h5
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
```

清理完成后重新执行 `alphapilot mine` 或 `alphapilot backtest`。

---

## 目录结构（简要）

```
AlphaPilot/
├── alphapilot/                 # 主程序
│   ├── kernel/                 # MainEngine / Context / 配置 / 插件发现
│   ├── systems/                # 四大系统（data/factor/strategy/backtest）
│   │   ├── data/               # 数据下载、复权、Qlib 转换、h5（prepare_data 实现）
│   │   ├── factor/             # 因子库（factor_zoo）、结构化表达式校验（FactorValidationResult）
│   │   ├── backtest/           # 回测执行与产物（artifacts.py、results.py、qlib_yaml/）
│   │   └── strategy/           # 策略资产存储（strategy_zoo）、复测编排（backtest.py）
│   ├── adapters/               # LLM/数据源可插拔适配层（回测见 systems/backtest/）
│   ├── modules/                # 功能模块（alpha_mining/portal/platform/data_viz/backtest_viz/strategy_backtest/qlib_yaml/factor_cli + 插件）
│   │   ├── alpha_mining/       # 因子挖掘（qlib 场景 + loops + conf + registry）
│   │   ├── platform/           # prepare_data、单股数据管理、modules 命令；ui/backtest_ui 弃用提示
│   │   ├── portal/             # 统一 Web 门户（alphapilot portal）
│   │   ├── data_viz/           # 股票 K 线（alphapilot data_viz）
│   │   ├── backtest_viz/       # 回测详情 UI（alphapilot backtest_viz）
│   │   ├── strategy_backtest/  # 策略资产列表与复测 CLI
│   │   ├── qlib_yaml/          # Qlib qrun yaml 生成与校验（qlib_yaml_generate / qlib_yaml_validate）
│   │   └── factor/             # 因子库 CLI（factor_validate / factor_add）
│   └── log/ui/                 # 挖掘日志 panel（portal 嵌入；基于 Scenario trait，不依赖 alpha_mining）
├── tests/                      # pytest（如 systems/factor/test_factor_validation.py）
├── .env.example             # 环境变量模板
├── import_factors_from_log.py  # 从 log 提取因子公式写入因子库（去重；--validate 打印拒绝原因）
├── clean_log_dirs.py        # 清理 log 下空目录与失败桩目录
├── important_data/          # 用户数据（见 important_data/README.md；strategy_zoo 等已 gitignore）
│   ├── strategy_zoo/        # mine 保存的策略与 retests/
│   ├── factor_zoo/          # 因子库 factor_zoo.csv
│   ├── factor_qlib_templates/  # Qlib 回测模板（mine 默认，推荐在此改 yaml）
│   └── stock_lists/         # 股票池 CSV（prepare_data 默认列表）
└── git_ignore_folder/       # 运行产物（已 gitignore）
    └── RD-Agent_workspace/     # 每轮回测工作区

~/.qlib/qlib_data/cn_data/   # Qlib 行情数据（不在仓库内）
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
