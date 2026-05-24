# money_is_all_you_need

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

### 3. 数据下载脚本（`prepare_cn_data.py`）

- 通过 baostock 下载 A 股日线数据
- 支持从 CSV 指定股票列表（默认读取 `backup_data/kechuang_stock.csv`）
- 数据输出目录：`~/.qlib/qlib_data/cn_data/raw_data_back_adjust`

### 4. 回测与因子数据配置

- `alphaagent/scenarios/qlib/experiment/factor_template/conf.yaml`：基线回测（仅内置价量特征）
- `alphaagent/scenarios/qlib/experiment/factor_template/conf_cn_combined_kdd_ver.yaml`：合并 LLM 新因子后的回测
- `alphaagent/scenarios/qlib/experiment/factor_data_template/generate.py`：从 Qlib 导出 `daily_pv.h5` 供因子代码使用

可按需修改股票池（`market` / `instruments`）、训练/验证/测试区间、持仓数量等。

### 5. 辅助数据目录（`backup_data/`）

存放个人股票列表 CSV、架构图等，**不参与**程序自动加载，仅作备份与参考。

### 6. 运行注意事项

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

### 3. 安装 Qlib

Qlib 以 **Python 包** 形式安装即可，日常运行不依赖 qlib 源码目录：

```bash
git clone https://github.com/microsoft/qlib.git
cd qlib
pip install .
cd ..
```

### 4. 准备行情数据

**步骤 A：下载 CSV（baostock）**

```bash
cd AlphaAgent
python prepare_cn_data.py
```

可在 `prepare_cn_data.py` 末尾修改 `STOCK_CSV`、`START_DATE`、`END_DATE`、`DATA_DIR`。

**步骤 B：转换为 Qlib 二进制格式**

```bash
cd qlib
python scripts/dump_bin.py dump_all \
  --include_fields open,high,low,close,preclose,volume,amount,turn,factor \
  --data_path ~/.qlib/qlib_data/cn_data/raw_data_back_adjust \
  --qlib_dir ~/.qlib/qlib_data/cn_data \
  --date_field_name date \
  --symbol_field_name code

python scripts/data_collector/future_calendar_collector.py \
  --qlib_dir ~/.qlib/qlib_data/cn_data/ --region cn
```

如需指数成分股文件，可额外运行 `cn_index/collector.py`；若使用自定义股票池，在 `~/.qlib/qlib_data/cn_data/instruments/` 下维护对应的 `.txt` 文件，并在 `conf.yaml` 中设置 `market`。

**步骤 C：生成因子用 h5（首次运行 mine 时也可能自动生成）**

```bash
cd alphaagent/scenarios/qlib/experiment/factor_data_template
python generate.py
```

修改股票池或字段后，需删除 `daily_pv_all.h5`、`daily_pv_debug.h5`，并清理 `git_ignore_folder/`、`pickle_cache/` 缓存后重新生成。

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

浏览器打开 `http://localhost:19900`，在界面中选择 `git_ignore_folder/RD-Agent_workspace` 下含 `ret.pkl` 的工作区目录。

指定工作区根目录：

```bash
alphaagent backtest_ui --workspace_root /path/to/git_ignore_folder/RD-Agent_workspace
```

### 4. 修改回测参数后清缓存

```bash
rm -rf ./pickle_cache/*
rm -rf ./git_ignore_folder/*
```

若更改股票池或 `generate.py`，还需删除 `factor_data_template/daily_pv_*.h5` 后重新运行 `generate.py`。

---

## 目录结构（简要）

```
AlphaAgent/
├── alphaagent/              # 主程序（Agent、回测、因子代码生成）
│   ├── log/ui/              # 运行日志可视化（原版 alphaagent ui）
│   └── app/backtest_viewer/ # 回测结果可视化（本仓库新增 backtest_ui）
├── backup_data/             # 股票列表等辅助文件
├── prepare_cn_data.py       # baostock 数据下载
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
