# Money is All Your Need

基于 [AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent)（KDD 2025）的本地化 fork，面向 A 股因子挖掘与 Qlib 回测。本仓库在保留原项目核心流程（假设生成 → 因子构造 → 回测评估）的基础上，增加了 API 兼容、回测可视化等改动，便于在本地环境稳定运行。

---

## 项目简介

AlphaAgent 通过三个 Agent 协作完成因子挖掘：

| Agent | 职责 |
|-------|------|
| **Idea Agent** | 根据市场假说提出可验证的因子方向 |
| **Factor Agent** | 将假说转化为因子表达式并生成代码 |
| **Eval Agent** | 用 Qlib 回测评估因子，并反馈迭代 |

本仓库使用 [Qlib](https://github.com/microsoft/qlib) 作为回测引擎，使用 OpenAI 兼容 API 调用大模型。

---

## 相对原版的改动说明

### 1. LLM JSON 解析容错（`alphaagent/oai/llm_utils.py`）

适配 MiniMax 等推理模型的非标准 JSON 输出（代码块包裹、尾逗号、推理块等），新增 `extract_and_validate_llm_json()`，降低因子构造阶段 `json.loads` 失败概率。

### 2. 回测结果可视化（`alphaagent/app/backtest_viewer/`）

在原版 `alphaagent ui`（运行日志总览）之外，新增独立的回测查看器 `backtest_ui`，支持：

- 收益曲线、超额收益、回撤
- 日换手与成本
- 当日成交、持仓明细

CLI 入口：`alphaagent backtest_ui`（见下方使用流程）。原版日志界面仍使用 `alphaagent ui`。

### 3. 数据准备命令（`alphaagent prepare_data`）

- 内置原 qlib `dump_bin.py`、`future_calendar_collector.py`（无需 clone qlib 仓库）
- 通过 baostock 下载行情：支持**直接下载前/后复权**（`--adjust_mode forward|backward`），或下载除权日线 + 复权因子后用 `apply_adjust` 本地合成，再 `convert` 为 Qlib 与 `daily_pv.h5`
- 默认股票列表：`backup_data/main_stock_2026_4_27.csv`

### 4. 回测与因子数据配置

- `alphaagent/scenarios/qlib/experiment/factor_template/conf.yaml`：基线回测（仅内置价量特征）
- `alphaagent/scenarios/qlib/experiment/factor_template/conf_cn_combined_kdd_ver.yaml`：合并 LLM 新因子后的回测
- `alphaagent prepare_data h5`：从 Qlib 导出 `daily_pv.h5` 供因子代码使用

可按需修改股票池（`market` / `instruments`）、训练/验证/测试区间、持仓数量等。

### 5. 运行注意事项

- 请在 **`AlphaAgent` 项目根目录** 下执行命令，确保 `.env` 能被正确加载
- `.env` 已加入 `.gitignore`，勿将 API Key 提交到仓库

---

## 环境准备

### 1. 创建 Conda 环境

```bash
conda create -n alphaagent python=3.10
conda activate alphaagent
```

### 2. 安装本仓库

```bash
cd AlphaAgent
pip install -e .
```

建议按 `requirements.txt` 安装依赖，避免 numpy / pandas 版本被意外升级：

```bash
pip install -r requirements.txt
```

### 3. macOS 额外依赖（LightGBM 回测）

在 **macOS** 上跑 `alphaagent mine` 时，Qlib 回测默认使用 **LightGBM**（`LGBModel`）。除 conda 环境内的 Python 包外，还需要本机通过 **Homebrew** 安装 OpenMP 运行时；`brew` 装的是**系统级**库（如 `/opt/homebrew/opt/libomp`），**不会**装进 `alphaagent` 虚拟环境，运行时由 LightGBM 动态加载。

**1）安装 libomp（仅需执行一次）**

```bash
brew install libomp
```

**2）确认 Python 依赖版本**

本仓库锁定 `numpy==1.23.5`、`pandas==1.5.3`。若曾执行过 `pip install --upgrade lightgbm` 等命令，可能把 numpy 升到 2.x，导致：

```text
ValueError: numpy.dtype size changed, may indicate binary incompatibility
```

请重新对齐版本（在 `conda activate alphaagent` 后）：

```bash
pip install "numpy==1.23.5" "pandas==1.5.3" --force-reinstall
```

重装 LightGBM 时尽量不要连带升级 numpy，可：

```bash
pip install lightgbm --no-deps
pip install "numpy==1.23.5" "pandas==1.5.3"
```

**3）验证是否可用**

```bash
conda activate alphaagent
python -c "import lightgbm as lgb; print('lightgbm', lgb.__version__)"
```

若仍报 `dlopen` / 找不到 `libomp`，可确认 Homebrew 路径后重装 lightgbm：

```bash
brew --prefix libomp
pip install lightgbm --force-reinstall --no-deps
pip install "numpy==1.23.5" "pandas==1.5.3"
```

Apple Silicon 上 `brew --prefix libomp` 一般为 `/opt/homebrew/opt/libomp`；Intel Mac 多为 `/usr/local/opt/libomp`。

### 4. 准备行情数据

在 **AlphaAgent 根目录** 下准备数据有两种常用方式（二选一即可）。

#### 方式 A：直接下载已复权数据（更简单）

`download` 的 `--adjust_mode` 设为 `forward`（前复权）或 `backward`（后复权）时，由 **baostock 直接返回复权后的 OHLC**，写入对应目录，**无需** `apply_adjust`，也**不会**下载复权因子。

```bash
cd AlphaAgent

# 前复权（写入 ~/.qlib/qlib_data/cn_data/raw_data_forward_adjust）
alphaagent prepare_data download \
  --stock_csv backup_data/main_stock_2026_4_27.csv \
  --adjust_mode forward

# 或后复权（写入 raw_data_back_adjust）
# alphaagent prepare_data download \
#   --stock_csv backup_data/main_stock_2026_4_27.csv \
#   --adjust_mode backward

# 转 Qlib + 日历 + h5（adjust_mode 与下载时一致）
alphaagent prepare_data convert \
  --stock_csv backup_data/main_stock_2026_4_27.csv \
  --adjust_mode forward \
  --market main_stock_2026_4_27
```

同样支持增量：再次执行 `download` 只会补最新交易日。中文别名：`前复权`、`后复权`。

#### 方式 B：除权 + 本地复权（默认，便于核对因子）

先下除权价与复权因子，再在本地合成前/后复权 CSV，适合需要自行核对除权因子、或希望与本地 `apply_adjust` 逻辑一致时使用。

```bash
cd AlphaAgent

# 1) 仅下载：除权行情（增量）+ 复权因子（每次更新行情后全量覆盖）
alphaagent prepare_data download --stock_csv backup_data/main_stock_2026_4_27.csv --adjust_mode none

# 2) 合成为前复权或后复权 CSV（供训练 / convert）
alphaagent prepare_data apply_adjust --adjust_mode backward
# alphaagent prepare_data apply_adjust --adjust_mode forward

# 若早期复权价仍等于除权价，先刷新全历史复权因子（自 1990 年起）
alphaagent prepare_data refresh_factors --stock_csv backup_data/main_stock_2026_4_27.csv

# 3) 转 Qlib + 日历 + h5（data_path / adjust_mode 与上一步复权类型一致）
alphaagent prepare_data convert \
  --stock_csv backup_data/main_stock_2026_4_27.csv \
  --adjust_mode backward \
  --market main_stock_2026_4_27
```

一键全流程（方式 B：下载除权 → 本地复权 → convert）：

```bash
alphaagent prepare_data pipeline \
  --stock_csv backup_data/main_stock_2026_4_27.csv \
  --target_mode forward
```

**指定股票列表**

```bash
alphaagent prepare_data download --stock_csv my_stocks.csv --code_column ts_code
alphaagent prepare_data download --stock_csv watchlist.txt --market watchlist
alphaagent prepare_data download --all_market True
```

`--adjust_mode` / `--target_mode` 支持：`none`（除权/不复权）、`forward`（前复权）、`backward`（后复权），以及中文 `除权`、`前复权`、`后复权`。

支持的代码格式：`300001.SZ`、`sz.300001`、`SH600000`、纯 6 位数字。

下载后会写入 `instruments/{market}.txt`，**请在** `conf.yaml` **里把** `market` **改成同名**。

常用子命令：

```bash
# 直接前复权（跳过 apply_adjust）
alphaagent prepare_data download --stock_csv my_stocks.csv --adjust_mode forward
alphaagent prepare_data convert --stock_csv my_stocks.csv --adjust_mode forward

# 除权 + 本地复权
alphaagent prepare_data download --stock_csv my_stocks.csv --adjust_mode none
alphaagent prepare_data apply_adjust --adjust_mode forward
alphaagent prepare_data convert --stock_csv my_stocks.csv --adjust_mode forward
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

修改股票池或字段后，请按下方 [清理缓存](#5-清理缓存) 删除旧 h5 并重新运行 `alphaagent prepare_data h5`。

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
```

---

## 使用流程

### 1. 因子挖掘（主流程）

在 **AlphaAgent 根目录** 下执行：

```bash
conda activate alphaagent
cd /path/to/AlphaAgent

alphaagent mine --potential_direction "你的市场假说，例如：行为金融学假说"
```

流程概要：

1. Idea Agent 生成/迭代市场假说  
2. Factor Agent 生成因子表达式与 Python 代码  
3. 在 `daily_pv.h5` 上计算因子值  
4. Qlib + LightGBM 回测，输出 IC、收益等指标  
5. 根据反馈进入下一轮  

回测工作区与日志默认在 `git_ignore_folder/` 下。

### 2. 多因子回测

```bash
alphaagent backtest --factor_path /path/to/factors.csv
```

CSV 示例：

```csv
factor_name,factor_expression
MACD_Factor,"MACD($close)"
RSI_Factor,"RSI($close)"
```

### 3. 可视化工具

项目提供两个 Streamlit 界面，用途不同：

| 命令 | 来源 | 主要用途 |
|------|------|----------|
| `alphaagent ui` | 原版自带 | 查看因子挖掘**运行日志**（假说、因子代码、反馈、Qlib 报告图等） |
| `alphaagent backtest_ui` | 本仓库新增 | 查看单次回测**交易与收益**（持仓、成交、收益曲线等） |

#### 3.1 运行日志可视化（原版 `alphaagent ui`）

用于监控 `alphaagent mine` 的完整迭代过程，包括每轮假说、因子表达式、代码反馈、回测指标图表等。

```bash
alphaagent ui --port 19899 --log_dir log/
```

浏览器打开 `http://localhost:19899`。`log_dir` 指向运行产生的日志目录，默认为项目下的 `log/`（若你修改过日志输出路径，请对应调整）。

开启调试模式：

```bash
alphaagent ui --port 19899 --log_dir log/ --debug
```

#### 3.2 回测结果可视化（本仓库 `backtest_ui`）

用于查看某次 Qlib 回测工作区的明细结果，适合分析具体某轮回测的持仓与收益。

```bash
alphaagent backtest_ui --port 19900
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
alphaagent backtest_ui --workspace_root /path/to/git_ignore_folder/RD-Agent_workspace --log_dir log/
```

### 5. 清理缓存

在 **AlphaAgent 项目根目录** 下执行。修改股票池、`conf.yaml` 回测区间、`generate.py` 字段，或希望因子/回测从头跑时，建议先清缓存。

#### 缓存目录说明

| 路径 | 内容 | 何时需要清理 |
|------|------|----------------|
| `pickle_cache/` | 因子计算、Qlib 回测等步骤的 pickle 缓存 | 修改回测参数、因子逻辑，或结果异常需重跑 |
| `git_ignore_folder/` | 工作区、回测产物、`daily_pv.h5` 副本等 | 更换股票池、重跑 `mine` / `backtest` |
| `alphaagent/scenarios/qlib/experiment/factor_data_template/daily_pv_*.h5` | 从 Qlib 导出的价量 h5 源文件 | 修改 `market`、股票池或 `generate.py` |
| `prompt_cache.db`（可选） | LLM 对话/Embedding 本地缓存（`.env` 开启缓存时） | 更换模型或希望 LLM 输出不复用旧缓存 |

#### 常用命令

**仅清运行缓存**（改 `conf.yaml` 持仓数、训练区间等，股票池未变）：

```bash
cd /path/to/AlphaAgent

rm -rf ./pickle_cache/*
rm -rf ./git_ignore_folder/*
```

**清运行缓存 + 价量 h5**（改股票池、`market` 或 `generate.py` 后必做）：

```bash
cd /path/to/AlphaAgent

rm -rf ./pickle_cache/*
rm -rf ./git_ignore_folder/*
rm -f alphaagent/scenarios/qlib/experiment/factor_data_template/daily_pv_all.h5
rm -f alphaagent/scenarios/qlib/experiment/factor_data_template/daily_pv_debug.h5

# 重新生成 h5（或在下次 alphaagent mine 时自动生成）
alphaagent prepare_data h5
```

**一键全量清理**（运行缓存 + h5 + 可选 LLM 缓存）：

```bash
cd /path/to/AlphaAgent

rm -rf ./pickle_cache/*
rm -rf ./git_ignore_folder/*
rm -f alphaagent/scenarios/qlib/experiment/factor_data_template/daily_pv_all.h5
rm -f alphaagent/scenarios/qlib/experiment/factor_data_template/daily_pv_debug.h5
rm -f ./prompt_cache.db   # 未启用 LLM 缓存时可省略

alphaagent prepare_data h5
```

清理完成后重新执行 `alphaagent mine` 或 `alphaagent backtest`。

---

## 目录结构（简要）

```
AlphaAgent/
├── alphaagent/              # 主程序（Agent、回测、因子代码生成）
│   ├── log/ui/              # 运行日志可视化（原版 alphaagent ui）
│   └── app/backtest_viewer/ # 回测结果可视化（本仓库新增 backtest_ui）
├── .env.example             # 环境变量模板
└── git_ignore_folder/       # 运行产物（已 gitignore）

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
