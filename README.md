<div align="center">

<img src="docs/AlphaPilot_logo.svg" alt="AlphaPilot" width="760">

### LLM 驱动的 A 股量化因子挖掘、回测与策略研究平台

`多 Agent 因子挖掘`&nbsp;·&nbsp;`Qlib 回测`&nbsp;·&nbsp;`Web 门户`&nbsp;·&nbsp;`数据准备`&nbsp;·&nbsp;`日频信号`&nbsp;·&nbsp;`Telegram/飞书 通讯`

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-22C55E">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white">
  <img alt="Backtest" src="https://img.shields.io/badge/Backtest-Qlib-FF6A00">
  <img alt="Portal" src="https://img.shields.io/badge/Portal-FastAPI%20%2B%20React-0EA5E9">
  <img alt="Notify" src="https://img.shields.io/badge/Notify-Telegram%20%7C%20Feishu-26A5E4?logo=telegram&logoColor=white">
  <img alt="Status" src="https://img.shields.io/badge/status-alpha-yellow">
</p>

[快速开始](#-快速开始)&nbsp;·&nbsp;[核心功能](#-核心功能)&nbsp;·&nbsp;[典型工作流](#-典型工作流)&nbsp;·&nbsp;[文档](#-更多文档)&nbsp;·&nbsp;[Docker 部署](docs/DOCKER.md)

</div>

---

## 📖 项目简介

AlphaPilot 是一个面向 A 股量化研究的因子挖掘与策略验证平台，围绕因子生成、回测评估、策略复测和日常研究操作提供统一工作流。项目使用 LLM 驱动多 Agent 因子研究流程，使用 Qlib 完成回测与信号验证，并提供 Web 门户管理数据、任务、通知和研究资产。

## ✨ 核心功能

| 能力 | 关键入口 | 说明 |
|------|----------|------|
| 🧠 因子挖掘 | `alphapilot mine` | LLM 多 Agent 流程 + AlphaForge / GP / RL / AFF 公式化方法 |
| 📊 回测评估 | `alphapilot backtest` | 组合回测、逐因子 IC 快筛、排行榜与收益曲线 |
| 🧩 策略复测 | `alphapilot strategy_backtest` | 复用已沉淀的策略资产与模型继续验证 |
| 📅 日频信号 | `alphapilot daily_signals` | 按交易日推进持仓、生成单日调仓信号 |
| 🖥️ 统一门户 | `alphapilot portal` | 数据 / 因子 / 回测 / 任务 / 通知集中到同一界面 |
| 🗄️ 数据准备 | `alphapilot prepare_data` | baostock / tushare → Qlib → 因子 h5 全链路 |
| 🔔 通知与远程 | `alphapilot notify_commands` | 任务完成推送（Telegram / 飞书 / 邮件）+ 聊天命令远程发起与查询任务 |

### 因子挖掘

AlphaPilot 的主线能力是自动化因子研究。你可以用自然语言启动 LLM 驱动的多 Agent 挖掘流程，也可以在同一套项目里使用公式化方法生成候选因子，再统一进入校验、回测和资产沉淀。

- 统一管理 Idea Agent、Factor Agent、Eval Agent 三段研究流程
- 支持 `alphapilot mine` 启动 LLM 驱动的因子挖掘
- 支持 GP、RL、AFF 等公式化挖掘方法
- 因子可落入因子库，并继续进入回测或策略资产管理

关键入口：`alphapilot mine --direction "你的市场假说"`

> 🖼️ *截图占位：因子挖掘流程 / 挖掘任务页面*

### 回测与评估

项目内置多种回测与评估模式，既能做正式组合回测，也能快速筛选大量候选因子。首页只保留常用入口，更多回测命令与参数见 [CLI 命令参考](docs/alphapilot-cli.md)。

- `multi_combined`：多因子合并训练并完成组合回测
- `single_ic`：逐因子快速计算 IC、RankIC、ICIR
- `multi_sequential`：逐因子分别跑完整组合回测
- 门户「回测」页统一可视化：收益 / 超额 / 账户 / 换手率曲线、每日明细、因子排行榜与对比基准

关键入口：`alphapilot backtest --factor_path /path/to/factors.csv`

> 🖼️ *截图占位：回测详情 / 因子排行榜*

### 策略复测与日频信号

当你已经沉淀了策略资产后，可以直接复用已有因子和模型继续验证，而不必重新跑完整挖掘流程。对于按日推进的研究或模拟交易场景，还可以基于已有策略生成单日调仓信号。

- `strategy_backtest` 支持对已保存策略资产重新回测
- `daily_signals` 支持按指定交易日推进持仓状态
- 适合做模型复用、策略复验和单日调仓演练
- 结果可回流到策略资产和门户页面中统一查看

关键入口：`alphapilot strategy_backtest --strategy_name "<策略名>" --mode=retrain`

> 🖼️ *截图占位：策略复测结果 / 每日交易信号*

### 统一 Web 门户

AlphaPilot 提供统一 Web 门户作为日常研究入口，将数据、因子、回测、任务和通知集中到同一个界面，避免在多个独立脚本和页面之间切换。

- 统一访问因子挖掘、回测、策略库、市场数据和通知配置
- 支持后台任务、定时任务和结果查看
- 「回测」页内置完整可视化：累计收益 / 超额 / 账户 / 换手率图表、日期范围筛选、每日明细、因子排行榜与对比基准
- 适合本地研究环境和服务器部署场景

关键入口：`alphapilot portal`

> 🖼️ *截图占位：门户首页 / 任务面板*

### 数据准备与管理

项目内置 A 股数据准备流程，可从原始行情到 Qlib 数据、再到因子计算所需 h5 文件形成完整链路。首页只保留最短路径，下载源、复权方式和高级参数见详细文档。

- 支持 baostock 和 tushare 数据源
- 支持行情下载、复权处理、Qlib 转换和 h5 生成
- 支持股票池管理与单股数据维护
- 与因子挖掘、回测和日频信号直接衔接

关键入口：`alphapilot prepare_data download --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv`

> 🖼️ *截图占位：市场数据页面 / K 线与数据管理*

### 通知与远程控制

研究任务往往耗时较长，AlphaPilot 内置任务通知与双向聊天命令系统：后台任务结束会主动推送结果，你也可以直接通过聊天工具远程发起、查询和管理任务，无需一直守在终端前。

- 支持 **Telegram、飞书、邮件** 三种通知渠道
- 任务完成（或全部任务）自动推送结果与状态
- Telegram / 飞书 命令接收器，支持 `/mine`、`/backtest`、`/data`、`/status`、`/jobs`、`/cancel`、`/log`、`/result` 等命令
- 白名单用户鉴权，可远程发起任务并查看日志、产物与运行状态
- 凭证在门户「通知」页配置，或通过 `ALPHAPILOT_NOTIFY_*` 环境变量注入

关键入口：`alphapilot notify_commands --channel telegram`

> 🖼️ *截图占位：通知配置页 / Telegram 命令交互*

## 🚀 快速开始

以下流程以本地安装为主，目标是尽快跑通一条最短闭环。**Docker 一键部署**请直接看 [docs/DOCKER.md](docs/DOCKER.md)。

### 1. 创建环境

```bash
conda create -n alphapilot python=3.11
conda activate alphapilot
```

### 2. 安装项目

```bash
git clone <your-repo-url>
cd AlphaPilot
pip install -e .
```

如需使用 Web 门户前端，请额外准备 Node.js，并在 `alphapilot/modules/portal/web` 下构建前端资源：

```bash
cd alphapilot/modules/portal/web
npm install
npm run build
cd ../../../../
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

至少补齐以下配置：

```env
OPENAI_API_KEY=<your_api_key>
OPENAI_BASE_URL=<your_api_base_url>
CHAT_MODEL=<your_chat_model>
REASONING_MODEL=<your_reasoning_model>
```

### 4. 准备数据

```bash
alphapilot prepare_data download \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode backward

alphapilot prepare_data convert \
  --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \
  --adjust_mode backward \
  --market main_stock_2026_4_27

alphapilot prepare_data h5
```

### 5. 启动门户

```bash
alphapilot portal
```

默认访问地址：`http://127.0.0.1:19901`

> 时区默认 **Asia/Shanghai**（影响定时任务触发与时间戳显示）。可在门户「高级」页「门户设置」修改，或用 `alphapilot timezone Asia/Shanghai` 设置。

### 6. 运行一次任务

启动一次因子挖掘：

```bash
alphapilot mine --direction "行为金融学假说" --step_n 5
```

或对已有因子文件执行一次回测：

```bash
alphapilot backtest --factor_path /path/to/factors.csv
```

## 🧭 典型工作流

1. 先用 `prepare_data` 准备行情、Qlib 数据和 `daily_pv.h5`。
2. 用 `mine` 或 AlphaForge 系列命令生成候选因子。
3. 用 `backtest` 做组合回测或 IC 快筛，并在门户中查看结果。
4. 将有效策略沉淀到策略资产，再用 `strategy_backtest` 或 `daily_signals` 持续验证。

## 📚 更多文档

- [完整 CLI 命令参考](docs/alphapilot-cli.md)
- [项目目录与架构说明](docs/alphapilot-structure.md)
- [Docker 部署与服务化运行](docs/DOCKER.md)
- [Docker 实际运行记录与排错](docs/DOCKER-RUN.md)
- [important_data 目录、模板与资产说明](important_data/README.md)
- [AlphaForge 相关说明](alphapilot/modules/alphaforge/README.md)

## 📂 目录结构

```text
AlphaPilot/
├── alphapilot/          # 主程序与模块
├── important_data/      # 因子库、策略资产、模板、股票池
├── docs/                # 详细文档
├── tests/               # 测试用例
├── docker-compose.yml   # Docker 服务编排
└── README.md            # 项目首页
```

## 🚧 开发状态与路线图

> AlphaPilot 仍在持续开发中：目前存在部分已知 bug 正在修复与优化，功能和接口可能调整，项目会保持更新。

计划中的方向：

- [ ] 🧪 模拟盘交易系统（paper trading）
- [ ] 💹 实盘交易系统
- [ ] 🧠 接入更多因子挖掘方法
- [ ] 🐛 持续修复已知问题、完善文档与稳定性

欢迎通过 Issue / PR 反馈问题与建议。

## 🙏 致谢

本项目受到 [RndmVariableQ/AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent) 以及[DulyHao/AlphaForge](https://github.com/DulyHao/AlphaForge)启发，进行开发与优化。感谢原作者与社区的工作。

<div align="center">
<br>
<img src="docs/logo.svg" alt="AlphaPilot" width="56">
<br>
<sub><b>AlphaPilot</b> · A 股量化研究平台</sub>
</div>
