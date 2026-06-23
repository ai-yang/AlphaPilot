# Docker 实际运行记录（Apple Silicon / macOS）

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
cd /Users/wangrui/MyCodes/money_is_all_you_need

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
