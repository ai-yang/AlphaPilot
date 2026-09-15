# 研究 API v1 停机迁移

本次升级同时切换后端、GUI 和研究命令入口。旧研究 HTTP 地址返回结构化 `410 API_REMOVED`，不再保留并行写入口。交易、通知配置和 Portal 管理接口保持各自原有鉴权。

## 升级顺序

1. 在旧版本暂停调度、飞书/Telegram 的研究提交和 GUI 提交，等待已有任务结束。停止旧 Portal 和旧 scheduler；不要只关闭浏览器。
2. 保留原来的工作区目录和环境配置，安装新代码及依赖。所有进程必须使用同一个 `ALPHAPILOT_PORTAL_JOB_ROOT` 和数据、因子、策略、会话目录。
3. 预览迁移：`alphapilot research_migrate`。此命令不执行历史计算，不调用模型、不发送通知。存在旧 worker、旧 scheduler 或新 TaskRuntime 时会拒绝执行。
4. 执行：`alphapilot research_migrate --execute=True`。命令先备份 SQLite、旧任务、运行目录、旧调度和迁移涉及的历史工作区，再写入索引。返回 `backup` 和需要人工重建的调度项。
5. 使用 `research_token create` 为 GUI 和各个外部客户端创建独立凭据，同时部署新 GUI 构建和后端。启动 Portal 和 TaskRuntime，核对历史任务与产物。
6. 旧 Qlib 目录没有可靠的复权模式/数据版本标记时会显示待准备。通过 v1 数据 `convert`（已有 CSV）或 `pipeline`（重新下载并转换）发布明确数据版本，再提交研究任务。

研究服务发现尚未迁移的旧任务或旧调度时会拒绝写入，避免新旧执行器同时工作。迁移过程中如被中断，再次运行相同命令；已完成记录按原 ID 跳过，未完成的产物转换继续执行并复用已发布的文件，避免重复。迁移持续持有工作区运行时锁；未完成的迁移会阻止新研究写入，直到恢复完成。旧调度文件在备份和持久化后移出旧入口，后续删除新调度不会令旧调度重新生效。

## 保留内容与结果解释

- 原任务 ID 保留；旧日志、输入和结果有备份。不能恢复的旧运行状态变为 `lost`，不会自动再次计算。
- 有显式 job_id 的历史 Run 保留关联；无可靠关联的旧 Run、平铺工作区和独立挖掘日志标记 `association: unknown`，不按文件时间猜测所属任务。
- 历史可信本地产物在迁移时转换为 JSON/CSV 曲线、表格和摘要；公共 API 不接受或反序列化客户端上传的 pickle。
- 无法由当前依赖读取的历史结果保留运行记录，并发布 `LEGACY_ARTIFACT_UNAVAILABLE` 产物；原文件位于备份中。该情况不等同于原研究计算失败。
- 旧调度参数能够转为 v1 类型时保留原 ID；包含任意路径或缺少有限预算、资源 ID 时保留为禁用记录，显示 `migration_error`，需要用 GUI 重建。
- 策略数据和已有模型保持在本地。对外导出使用研究配方，不传输可执行模型 pickle。

## 旧地址替换

| 旧地址 | v1 入口 |
| --- | --- |
| `/api/jobs`、`/api/jobs/{id}/progress` | `/api/v1/jobs`、`/api/v1/jobs/{id}` |
| `/api/jobs/{id}/log` | `/api/v1/jobs/{id}/logs?cursor=0` |
| `/api/factors`、`/api/strategies` | `/api/v1/factors`、`/api/v1/strategies` |
| `/api/backtests`、`/api/mining/sessions` | `/api/v1/runs`、`/api/v1/artifacts/{id}` |
| `/api/data`、`/api/market` | `/api/v1/datasets` 和强类型 data Job |
| `/api/daily-trade`、`/api/trade-sessions` | daily_signals Job、`/api/v1/signal-sessions` |
| `/api/schedules` | `/api/v1/schedules` |
| `/api/report-factors/extract` | `/api/v1/uploads` + report_factor_extract Job |
| `/api/notify/commands/plan`、`/dispatch` | `/api/v1/commands/plan`、`/dispatch` |
| `/api/modules/run` 中的研究命令 | 相应 v1 类型接口；旧通用入口返回 410 |

新 GUI 的任务面板从详情接口持续读取选中任务，列表翻页不影响详情。任务完成后可按 Run 浏览多次实验的结果；结果不是“最近一次回测”的目录扫描。

## 运维与回退

`alphapilot task_runtime stop` 停止新提交和派发，等待执行中的任务结束后退出；排队任务保留到下次 `start`。需要结束排队任务时先调用取消接口。直接重启 Portal 不会停止计算。

取消中长时间显示 `EXECUTION_UNCONFIRMED` 时检查 Docker 和进程权限，恢复可观测性后运行时会继续确认。不要手工清空资源锁后继续写数据。

回退前停止新提交并等待新任务结束，停止所有运行时，然后恢复迁移返回的备份与旧 GUI/后端。新版本创建的任务和资产不保证能被旧版本读取；先保留完整的新工作区备份，再执行恢复。
