# 独立 MCP 服务支持

[`alphapilot-mcp`](https://github.com/ai-yang/alphapilot-mcp) 是独立 Node/TypeScript 仓库，仅通过研究 HTTP API 接入；AlphaPilot 不依赖 MCP SDK。本次增加的 v1 能力保持既有路由和字段兼容。

- `GET /api/v1/runs?job_id=...`：按任务查询运行。`include_artifacts=false` 避免内嵌完整产物。
- `GET /api/v1/runs/{id}?include_artifacts=false`：查看单次运行元数据。
- `GET /api/v1/artifacts?job_id=...&run_id=...&limit=20&cursor=...`：公开产物分页；游标绑定筛选条件。
- `GET /api/v1/schedules/{id}`：单个调度详情，用于版本检查和暂停/恢复。
- capabilities.features 声明 `run_job_filter`、`artifact_pagination`、`mining_checkpoint_resume`、`schedule_detail`。

自主挖掘每个完成步骤将快照经 fsync 和原子重命名发布，再将 SHA-256、下一步骤和轮次登记到运行记录。`resume_run_id` 指向含 checkpoint 的运行 ID，而非外部路径。服务端拒绝活动源任务、参数/资产版本冲突、数据版本变化、缺失或损坏的快照。

恢复时复制已验证快照和工作目录到新任务，执行时重绑定运行目录、输入快照目录和日志目录。原任务的运行记录、工作文件和日志保持不变。停止事件属于当前实例/进程，不序列化到检查点。MCP 和 HTTP 客户端不接触 pickle。

历史运行如果没有明确记录的可靠检查点，返回 RESUME_UNAVAILABLE；不扫描“最近的”文件猜测恢复位置。可以继续查询和下载其现有产物。

恢复的 max_steps 是本次继续执行的步骤预算。例如先运行 3 步，再从该运行续跑 2 步，总共完成一轮 5 步。除了 max_steps 和 resume_run_id，输入需与原任务解析后的配置一致；后端仍验证所引用资产的版本及执行开始时的数据指纹。

测试范围及实际客户端版本记录在独立仓库 docs/acceptance.md。对外契约源文件为 docs/research/openapi-v1.json，可运行 scripts/export_research_contract.py --check 检查一致性。

日志增量游标按完整 UTF-8 字符推进，避免中文或 emoji 跨分页时损坏。极小的字节限制允许读取一个完整字符（最多 4 字节）；未完成的字符留给下一次读取。

在 MCP 仓库完成 `npm ci && npm run build` 后，可在本项目的 Python 环境执行 `python scripts/smoke_research_mcp.py`。脚本要求工作区空闲且无调度，使用现有行情与真实模型完成一轮挖掘（3 步后续跑 2 步），会保存因子和策略资产。默认连接同级 MCP 仓库，可通过 `MCP_REPOSITORY` 指定。覆盖 stdio/HTTP 共享任务、跨客户端取消和产物下载；结果写入 `git_ignore_folder/qa/mcp/`，临时凭据在结束时撤销。

`--scenario unary-backtest` 可复现一元负号表达式的真实 IC 回测。[最新验收记录](mcp-live-acceptance.md)包含任务 ID、发现的缺陷、修补及验证范围。
