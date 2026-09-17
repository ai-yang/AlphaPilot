# Docker 实际运行记录

## 2026-09-17：Linux amd64、研究 v1 与 MCP

本次在 Linux amd64、Docker Engine 26.0.0、Compose 2.25.0 上，从源码实际构建并启动了主项目和独立 MCP 镜像。使用单独的 Compose 项目、随机本机端口、现有行情的副本和临时研究凭据；没有调用模型 API、发送通知或连接券商。本机原有 AlphaPilot 服务保持运行。

| 检查 | 结果 |
|------|------|
| 主项目镜像构建、前端静态资源、Portal 与研究运行时健康检查 | 通过 |
| Python 依赖一致性及 Qlib / Torch / PyTables / XGBoost / CatBoost 导入 | 通过；`pip check` 无冲突，Torch 为 CPU 版 |
| 研究鉴权、只读凭据限制、旧研究地址返回 410 | 通过 |
| 数据集/模板/模型目录、一元负号表达式验证、拒绝未来引用 | 通过 |
| 因子、策略、股票池创建及过期 revision 冲突 | 通过 |
| 资产导出、JSON 上传、禁用状态的调度保存与查询 | 通过 |
| 真实内联 `single_ic` 回测、日期边界、幂等提交、同键不同参数冲突、取消 | 修复评分日期遗漏后通过 |
| 运行/产物读取和下载 SHA-256 校验 | 通过 |
| 强制重建 Portal 容器后，凭据、资产版本、任务、调度及产物仍可读取 | 通过 |
| 浏览器登录及首页、挖掘、回测、资产库、市场数据、日频模拟、调度七个页面 | 通过；无未处理脚本异常或 API 500 |
| MCP 容器 stdio / Streamable HTTP、共享任务查询 | 通过；默认核心 44 个工具，启用文件组后为 53 个 |
| stdio 提交、HTTP 取消、另一端看到相同取消状态 | 通过 |
| 经 MCP HTTP 网关下载及上传文件 | 通过；下载大小和 SHA-256 一致 |
| Docker 静态契约回归 | 4 项通过 |
| IC 日期、研究 API、任务运行时与研究流程回归 | 76 项通过 |

真实回测使用 `baostock_cn:day:forward` 的 30 只股票副本，表达式为 `ZSCORE(-TS_SUM($return,5))`。修复后的任务 `7c6c80f8445c492180a5b31f49d9b3a1` 成功，登记 3 个运行和 2 个产物，结果为 `complete`。请求评分区间为 2025-01-01 至 2025-05-30；实际有效样本为 2025-01-02 至 2025-05-28，共 95 个交易日，覆盖有效。期末两根 bar 用于计算默认收益标签。本次没有启动新一轮自主挖掘。

首次任务 `0fb2abe5dcbd45498ec9db7e21d61eb4` 虽报告成功，但核对指标发现其使用了 2017–2026 的全部历史。原因是 `QlibSignalEngine` 仅在显式标签分支传入日期边界，默认收益标签分支忽略了它们。现已统一按解析后的 `test_start/test_end`（缺失时回退 `start_time/end_time`）截取评分数据，并增加实际指标与覆盖范围回归；首次结果仅保留作诊断，不作为通过证据。

本次构建的主镜像约 4.09 GB，MCP 镜像约 252 MB；主镜像内为 Qlib 0.9.7、Torch 2.14.0+cpu、PyTables 3.11.1、XGBoost 3.2.0、CatBoost 1.2.10。镜像使用独立测试标签 `alphapilot:docker-smoke-20260917` 和 `alphapilot-mcp:docker-smoke-20260917`。浏览器检查针对本次构建时的前端快照。

本次修复了部署配置中的问题：

- Portal 已自动启动包含调度器的 TaskRuntime，旧 Compose 又单独启动 `scheduler`，会竞争同一工作区锁；统一由 Portal 启动。
- 原因子库、策略库、股票池位于容器可写层，不同服务不共享，重建也会丢失；增加三个持久化挂载，并从构建上下文排除用户研究资产。
- 原构建上下文未排除 `docker-data/`；补充排除持久数据和本地工具配置，避免后续构建携带运行数据。
- 固定容器内 `USE_LOCAL=True`，默认仅发布本机端口，允许配置发布端口；健康检查同时检查研究运行时。
- 镜像补充内置策略示例；文档修正数据复制的目录层级、数据准备命令，并补充研究 Token 和 MCP 接入步骤。
- 修复 `single_ic` 默认标签忽略评分日期的问题，GUI、MCP 和直接研究 API 调用共用这一修复。

当前部署步骤以 [DOCKER.md](DOCKER.md) 为准。完整本地测试报告、脚本和截图位于 `git_ignore_folder/qa/docker/20260917/`，行情副本、凭据和运行日志不进入 Git。

最终 20 项容器验收检查通过，另有 80 项自动回归通过。测试完成时没有活动任务，已撤销临时研究凭据并移除测试容器与网络；测试镜像和报告保留。

**范围限制：** 本次没有逐项运行自主/AFF/GP/RL 挖掘、外网行情下载、报告 OCR、策略复测和模拟会话推进，也没有验证通知投递和券商连接。可选 `Dockerfile.live` 依赖的 `alphapilot_tts`、`alphapilot_xtpx`、`alphapilot_emt`、XTP/EMT 插件源码目录当前缺失，因此该专用镜像尚不具备完整构建条件；普通研究镜像不依赖这些包。

## 历史记录：Apple Silicon / macOS

> 以下保留旧版本运行记录，其中独立 `scheduler` 服务和旧 CLI 命令已被后续研究 v1 改造替代；请勿直接照搬到当前版本。

本文记录在本机（**Apple Silicon, arm64, Docker Desktop**）把 AlphaPilot 用 Docker 跑起来的
完整步骤、遇到的报错与修复。结论：**已成功运行**，Portal 在 http://localhost:19901 健康提供服务。

> 架构/排错参考见 [DOCKER.md](DOCKER.md)；本文是“照着做就能跑起来”的实操版。

---

## 0. 环境

| 项 | 值 |
|---|---|
| 宿主 | macOS, Apple Silicon（`uname -m` = `arm64`） |
| Docker | Engine 29.x，Compose v2，Docker VM ≈ 7.7 GB RAM / 10 CPU |
| 镜像 | `alphapilot:latest`，**linux/amd64**，约 1.59 GB |
| 关键版本（容器内） | alphapilot 0.0.0 · torch 2.12.1+cpu · qlib 0.9.7 |

**为什么是 amd64？** 微软 qlib（`pyqlib`）只发布 linux/**amd64** wheel，没有 arm64。所以镜像固定
`platform: linux/amd64`，在 Apple Silicon 上由 Docker Desktop 模拟运行。建议在
**Docker Desktop → Settings → General 勾选 “Use Rosetta for x86/amd64 emulation”** 以获得更好性能。

---

## 1. 运行步骤（可复现）

```bash
cd /path/to/AlphaPilot

# 1) 准备 .env（compose 的 env_file，放 LLM key / TUSHARE_TOKEN 等）
cp .env.docker.example .env          # 然后编辑填入你的值

# 2) 建好宿主持久化目录（所有产物都落在 ./docker-data/）
mkdir -p docker-data/{qlib-data,app-config,workspace,pickle-cache,logs}

# 3) 代理/国内网络：指定 Debian apt 镜像（见下方“报错 4”）。本机已写入 .env：
#    APT_MIRROR=mirrors.aliyun.com

# 4) 构建镜像（首次较慢：amd64 模拟 + torch/qlib/科学计算栈）
docker compose build

# 5) 启动 Portal + 定时任务
docker compose up -d portal scheduler

# 6) 浏览器打开
open http://localhost:19901
```

可选：Telegram/飞书命令接收器（需先配置频道凭证）

```bash
docker compose --profile notify up -d notify
```

---

## 2. 遇到的报错与修复

构建/启动过程中依次碰到 4 个问题，均已在仓库内修好（改动：`Dockerfile`、`docker-compose.yml`、
`.env` / `.env.docker.example`）。

### 报错 1 — torch 安装失败（架构）
- **现象**：Dockerfile 里 `pip install torch --index-url https://download.pytorch.org/whl/cpu`，
  该索引只有 amd64 wheel。
- **根因**：torch 的 CPU 索引不含本机原生 arm64 包。
- **修复**：改为按 `TARGETARCH` 分流——amd64 用 CPU 索引，arm64 让 PyPI 解析（那里本就是 CPU 版）。
  （`Dockerfile` 中 `ARG TARGETARCH` 的 `if` 分支。）

### 报错 2 — `apt-get` 503，构建中断
- **现象**：`E: Failed to fetch http://deb.debian.org/... 503 Service Unavailable [IP: 198.18.0.195]`。
- **根因**：`198.18.0.0/16` 是 Clash/Surge TUN “fake-ip” 段；代理在拦截 `deb.debian.org` 的
  **HTTP(80)** 下载时间歇性返回 503。
- **修复（第一层）**：给 apt 加 `-o Acquire::Retries=5`，让失败的 .deb 自动重试。

### 报错 3 — `pyqlib` 找不到可安装版本
- **现象**：`ERROR: No matching distribution found for pyqlib`。
- **根因**：`pyqlib` 无 linux/arm64 wheel；本机原生 arm64 构建装不上（amd64 有
  `pyqlib-0.9.7-cp311-manylinux_x86_64.whl`，实测可装）。
- **修复**：在 `docker-compose.yml` 的共享配置里固定 `platform: linux/amd64`（构建与运行都走 amd64）。

### 报错 4 — 切到 amd64 后 apt 仍 503（重试不够）
- **现象**：换 amd64 重新构建，apt 依旧被代理 503，`Retries=5` 也救不回来。
- **根因**：代理对 `deb.debian.org` 的 HTTP 拦截是持续性的，而 **pip 走 HTTPS(443) 正常**
  （pyqlib 测试能从 PyPI 下载），所以只有 apt 的 HTTP 镜像有问题。
- **修复**：把 apt 源换成代理会“直连放行”的国内镜像。新增可配置构建参数 `APT_MIRROR`
  （`Dockerfile` 里按它 `sed` 改写 `/etc/apt/sources.list.d/debian.sources`；`docker-compose.yml`
  的 `build.args` 从 `.env` 读取），本机 `.env` 设为 `APT_MIRROR=mirrors.aliyun.com`。
  默认仍是官方 `deb.debian.org`，不影响其它网络环境。

> 之后 `docker compose build` 一次通过；`docker compose up -d` 后 Portal 进入 `healthy`。

---

## 3. 验证结果（均通过）

```bash
# 服务状态：portal=healthy / scheduler=running，restarts=0
docker compose ps

# 1) 前端被正确构建并提供（标题 + 命中的资源 200）
curl -s http://localhost:19901/ | grep -o '<title>[^<]*</title>'      # <title>AlphaPilot Portal</title>

# 2) 容器内重型依赖可正常 import（numpy 兼容垫片 + qlib/torch/tables）
docker compose exec portal \
  python -c "import alphapilot, qlib, torch, tables, xgboost, catboost; print('ok', qlib.__version__)"
# → ok 0.9.7

# 3) 产物确实落到宿主 ./docker-data/（不再只在容器内）
ls docker-data/app-config/portal/        # runtime.json
ls docker-data/logs/                     # 日志会话目录
ls docker-data/workspace/portal_schedules/   # scheduler 状态
```

---

## 4. 数据落盘位置（宿主 bind mount）

所有持久化数据都是 `./docker-data/` 下可直接浏览的普通文件，`docker compose down` 不会删除。

| 宿主 `./docker-data/` | → 容器内 | 内容 |
|---|---|---|
| `qlib-data/` | `/root/.qlib` | 行情数据（约 2.4 GB） |
| `app-config/` | `/root/.alphapilot` | portal 设置 / env.json / 通知凭据 / runtime |
| `workspace/` | `/app/git_ignore_folder` | 挖掘&回测 runs、factor_h5 缓存、jobs/schedules |
| `pickle-cache/` | `/app/pickle_cache` | mine/backtest 结果复用缓存 |
| `logs/` | `/app/log` | 应用 + LLM 消息日志 |

**首次行情数据**（约 2.4 GB，不在镜像里）：在 Portal「市场数据」页触发下载，或

```bash
docker compose exec portal alphapilot platform prepare_data download   # baostock，无需 token
```

已有数据可直接复用（免下载，保持 `qlib_data/...` 层级）：

```bash
cp -R ~/.qlib/ docker-data/qlib-data/      # → docker-data/qlib-data/qlib_data/cn_data/...
```

---

## 5. 常用运维命令

```bash
docker compose logs -f portal          # 跟踪日志
docker compose ps                      # 服务/健康状态
docker compose restart portal          # 重启
docker compose down                    # 停止并删容器（./docker-data/ 数据保留）
docker compose up -d --build portal    # 改代码/前端后重建并重启
```

> 注意：改了 React 前端（`web/src`）后需要重建镜像（前端在构建阶段 `npm run build` 进镜像）。
> Linux 宿主上容器以 root 写入 `./docker-data/`，文件属主为 root（macOS Docker Desktop 会自动映射到当前用户）。
