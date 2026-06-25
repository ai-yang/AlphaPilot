# Contributing to AlphaPilot

[中文](#中文) | [English](#english)

## 中文

感谢你愿意参与 AlphaPilot 的开发。AlphaPilot 是一个面向股票量化研究的项目，覆盖数据准备、因子挖掘、回测、策略资产、通知系统和 Web 门户。贡献时请尽量保持改动聚焦、可复现、可测试。

### 参与方式

- 缺陷修复：请优先提交可复现步骤、实际结果、期望结果和相关日志。
- 新功能：请说明使用场景、期望工作流、影响模块和验收标准。
- 文档改进：可以直接提交 PR；如果涉及行为变化，请同步更新中英文说明。
- 问题讨论：提交 Issue 前请先搜索已有 Issue 和 PR，避免重复上下文。

### 开发环境

推荐使用 Python 3.10 或 3.11。

```bash
conda create -n alphapilot python=3.11
conda activate alphapilot
pip install -e .
```

如需调试 Web 门户前端，请安装 Node.js，并在前端目录安装依赖：

```bash
cd alphapilot/modules/portal/web
npm install
```

如需调用 LLM、真实行情源或通知通道，请复制并配置本地环境变量：

```bash
cp .env.example .env
```

不要提交 `.env`、API Key、访问令牌、真实用户标识、私有日志或生产数据。

### 项目结构速览

- `alphapilot/app/`：命令行入口。
- `alphapilot/kernel/`：模块发现、配置、上下文和运行引擎。
- `alphapilot/systems/`：数据、因子、回测、策略和通知等核心系统。
- `alphapilot/modules/`：CLI/Portal 可调用的功能模块。
- `alphapilot/modules/portal/web/`：React + Vite 前端。
- `tests/`：后端测试。
- `docs/`：部署、CLI 和结构文档。
- `important_data/`：示例股票池和配置模板。

### 代码规范

- 遵循现有代码风格、命名方式和模块边界。
- 优先复用已有系统、模块、适配器和工具函数，避免为局部需求引入过宽抽象。
- 保持改动范围聚焦；不要在同一个 PR 中混合无关重构、格式化和功能改动。
- 用户可见行为变化需要更新 README、`docs/` 或相关示例。
- 中英文文档并存时，请尽量同步更新两种语言。
- 对外部服务、网络、文件系统、数据源和长任务相关逻辑，要补充错误处理和测试说明。

### 测试

后端默认测试会跳过真实网络、真实数据、慢任务、真实 LLM 和真实通知测试：

```bash
pytest
```

运行指定测试：

```bash
pytest tests/test_portal_api.py
```

需要显式运行外部依赖测试时，请确认本地已配置对应凭证和数据，并使用 pytest marker：

```bash
pytest -m real_data
pytest -m real_llm
pytest -m real_notify
pytest -m slow
```

前端检查：

```bash
cd alphapilot/modules/portal/web
npm run typecheck
npm run test
npm run build
```

如果没有运行某项测试，请在 PR 的 Testing 部分说明原因。

### 本地运行

启动 Web 门户：

```bash
alphapilot portal
```

默认地址为 `http://127.0.0.1:19901`。

常用 CLI 入口包括：

```bash
alphapilot prepare_data --help
alphapilot mine --help
alphapilot backtest --help
alphapilot strategy_backtest --help
alphapilot notify_commands --help
```

### 提交 PR 前

请确认：

- 已搜索相关 Issue 或 PR。
- 改动范围清晰，PR 描述说明了改了什么和为什么改。
- 已运行与改动相关的测试，或说明未运行原因。
- 已更新必要文档、示例或截图。
- 未提交密钥、令牌、私有数据、真实通知收件人或大体积生成文件。
- 涉及 Web UI 的改动已附带截图或说明关键交互验证方式。
- 涉及数据下载、LLM、通知等外部服务的改动说明了所需环境变量和失败场景。

## English

Thank you for contributing to AlphaPilot. AlphaPilot is a stock-focused quantitative research project covering data preparation, factor mining, backtesting, strategy assets, notifications, and a Web portal. Please keep contributions focused, reproducible, and testable.

### Ways to Contribute

- Bug fixes: include reproduction steps, actual behavior, expected behavior, and relevant logs.
- Features: describe the use case, expected workflow, affected area, and acceptance criteria.
- Documentation: documentation-only PRs are welcome; if behavior changes, update the relevant Chinese and English docs.
- Discussions: search existing issues and PRs before opening a new one.

### Development Setup

Python 3.10 or 3.11 is recommended.

```bash
conda create -n alphapilot python=3.11
conda activate alphapilot
pip install -e .
```

For Web portal frontend work, install Node.js and install dependencies in the frontend package:

```bash
cd alphapilot/modules/portal/web
npm install
```

For LLM calls, real market data sources, or notification channels, copy and configure local environment variables:

```bash
cp .env.example .env
```

Do not commit `.env`, API keys, access tokens, real user identifiers, private logs, or production data.

### Project Layout

- `alphapilot/app/`: command-line entry points.
- `alphapilot/kernel/`: module discovery, configuration, context, and runtime engine.
- `alphapilot/systems/`: core systems for data, factors, backtesting, strategies, and notifications.
- `alphapilot/modules/`: feature modules exposed through CLI or Portal.
- `alphapilot/modules/portal/web/`: React + Vite frontend.
- `tests/`: backend tests.
- `docs/`: deployment, CLI, and architecture docs.
- `important_data/`: sample stock pools and configuration templates.

### Code Guidelines

- Follow the existing style, naming, and module boundaries.
- Prefer existing systems, modules, adapters, and utility functions over new broad abstractions.
- Keep changes focused; avoid mixing unrelated refactors, formatting churn, and feature work in one PR.
- Update README, `docs/`, or examples when user-visible behavior changes.
- When Chinese and English docs both exist, keep them in sync when practical.
- For external services, network access, file systems, data sources, and long-running tasks, include error handling and testing notes.

### Testing

The default backend test run skips real network, real data, slow jobs, real LLM, and real notification tests:

```bash
pytest
```

Run a specific test file:

```bash
pytest tests/test_portal_api.py
```

When you intentionally run tests that depend on external services, make sure the required credentials and data are configured, then use the relevant pytest marker:

```bash
pytest -m real_data
pytest -m real_llm
pytest -m real_notify
pytest -m slow
```

Frontend checks:

```bash
cd alphapilot/modules/portal/web
npm run typecheck
npm run test
npm run build
```

If you skip a relevant test, explain why in the PR Testing section.

### Running Locally

Start the Web portal:

```bash
alphapilot portal
```

The default URL is `http://127.0.0.1:19901`.

Common CLI entry points:

```bash
alphapilot prepare_data --help
alphapilot mine --help
alphapilot backtest --help
alphapilot strategy_backtest --help
alphapilot notify_commands --help
```

### Before Opening a PR

Please confirm that:

- You searched for related issues or PRs.
- The PR scope is clear, and the description explains what changed and why.
- You ran tests relevant to the change, or explained why they were not run.
- You updated required docs, examples, or screenshots.
- You did not commit secrets, tokens, private data, real notification recipients, or large generated files.
- Web UI changes include screenshots or notes on key interaction checks.
- Changes involving data downloads, LLMs, notifications, or other external services document required environment variables and failure cases.
