# MCP 真实数据验收（2026-09-16）

本次使用已有 `baostock_cn:day:forward` 行情、`arena_zz_v1` 股票池和后端配置的真实模型，通过独立 `alphapilot-mcp` 服务完成一轮挖掘。没有执行实盘交易或发送渠道通知。

## 结果

- 前三步任务：`f16d880a4faa41dbbbc361c5c6ab9c52`，成功。
- 后两步续跑：`ef789eec27d24b4ba4f8462aba233a4e`，成功；完成 1 轮，3 个候选因子全部入库，保存 1 个策略。
- 续跑任务登记 3 个 Run、39 个 Artifact，结果 `availability=complete`。
- 同输入、同幂等键返回同一任务；stdio 断开后后台计算继续。
- 使用分别认证的 stdio 和 HTTP 客户端查询同一任务；HTTP 客户端提交的排队回测由 stdio 客户端取消，双方看到 `cancelled`。
- 续跑前后的源 Run 保持一致；直接下载和经过 MCP HTTP 网关下载的产物大小、SHA-256 一致。
- 本地详细记录：`git_ignore_folder/qa/mcp/mcp-live-20260916-150028/report.json`。

## 发现并修复的问题

模型生成的 `ZSCORE(-TS_SUM($return,5))` 被旧 AST 验证器误拒绝：`ZSCORE` 已受支持，缺失的是函数参数内的一元负号。增加一元正负号解析并复用已有 AST 节点；数值参数仍保留字面量类型，未来数据引用和非法窗口继续拒绝。执行端改用同一语法检查，消除 `2*-$close` 等合法相邻符号被正则误拒绝的问题，并要求解析完整输入。

修补后，通过 MCP 提交上述原表达式的独立真实 `single_ic` 回测，任务 `3ce8da2bd7814b2185622f266a59677e` 成功，取得完整结果和 IC 评估产物；`DELAY($close,-1)` 验证失败，符合预期。记录位于 `git_ignore_folder/qa/mcp/mcp-unary-backtest-20260916-151538/report.json`。该回归只执行内联因子回测，没有再启动一轮自主挖掘。

独立 MCP 仓库同时修补凭据目录校验：创建、读取和列举凭据时拒绝共享权限或符号链接目录，防止仅校验文件权限而遗漏目录权限；补充了回归测试。

## 自动检查和复现

- 全部因子相关测试，以及研究 v1 API、检查点和任务运行时：213 项通过。
- 独立 MCP：17 项通过，含两种传输和两个协议版本、权限、幂等、文件传输和凭据目录检查。
- GUI 类型检查、OpenAPI 导出一致性检查通过。
- 干净目录生产依赖安装及 Docker 容器中的 MCP 调用闭环通过。

在已经构建的同级 `alphapilot-mcp` 仓库和已配置的 AlphaPilot 环境下：

```sh
python scripts/smoke_research_mcp.py
python scripts/smoke_research_mcp.py --scenario unary-backtest
python -m pytest tests/test_factor*.py tests/test_research_v1.py tests/test_research_checkpoints.py tests/test_research_runtime.py -q
```

真实脚本要求工作区空闲且没有调度；第一条命令使用真实模型并保存研究资产。所有临时凭据在测试结束时撤销，空闲测试运行时停止。行情、凭据、模型文件和完整本地运行日志均不纳入 Git。

本次不包含 AFF/GP/RL 等所有算法的逐项真实计算验收，也未执行浏览器 GUI 视觉验收。三个实际 Agent 客户端的协议兼容记录及复现脚本保存在独立 MCP 仓库。
