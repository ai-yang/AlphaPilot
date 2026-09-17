# Running AlphaPilot in Docker

This packages the whole stack — FastAPI + React **portal**, LLM factor **mining**, qlib
**backtest**, and **data download** — into one image. The `portal` service starts the
unified research runtime, which dispatches both queued jobs and schedules. The
`notify` service is optional; no separate scheduler container is needed.

LLM-generated factor/backtest code runs **as local subprocesses inside the container**
(`USE_LOCAL=True`), so there is **no docker-in-docker** and no Docker socket to mount.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage: Node builds the React `dist/`, then a Python 3.11 runtime |
| `docker-compose.yml` | `portal` and optional `notify`; state and research assets bind-mounted to `./docker-data/` |
| `.dockerignore` | Keeps the ~1.9 GB of local caches/secrets out of the build context |
| `.env.docker.example` | Template for the `.env` compose reads (API keys, tokens) |

## Quick start

```bash
[ -f .env ] || cp .env.docker.example .env  # keep existing configuration; fill in model settings as needed
mkdir -p docker-data/{qlib-data,app-config,workspace,pickle-cache,logs,factor-zoo,strategy-zoo,stock-pools}
docker compose build portal         # first build is large/slow (torch + scientific stack)
docker compose up -d portal
# open http://localhost:19901
```

The host port binds to `127.0.0.1` by default. If a native AlphaPilot Portal already
uses port 19901, set `ALPHAPILOT_PORTAL_PUBLISHED_PORT=19921` in `.env` and use
`http://127.0.0.1:19921`. The container still listens on port 19901. Set
`ALPHAPILOT_PORTAL_BIND_ADDRESS` explicitly when a different host binding is needed.

Create a research credential **inside this deployment**, then enter the returned
Token in the GUI's research connection control (研究服务). Host-workspace credentials
do not authenticate against a fresh Docker workspace.

```bash
docker compose exec portal alphapilot research_token create --client_id=gui --scopes=research:read,research:write,jobs:submit,jobs:cancel,data:write,signals:write,schedules:write
```

The plaintext Token is shown once. GUI research credentials are separate from
trading operator credentials. See [Research API v1](research/README.md) for scopes,
revocation, and API examples.

Optional Telegram/Feishu command receiver (needs a configured channel):

```bash
docker compose --profile notify up -d notify
```

## First run: download market data

Market data (~2.4 GB) is **not** baked into the image. On first use, trigger a data job
from the portal **Data** page, or from the CLI:

```bash
docker compose exec portal alphapilot prepare_data download --source baostock_cn --adjust_mode forward
docker compose exec portal alphapilot prepare_data convert --source baostock_cn --adjust_mode forward --market main_stock_2026_4_27
# tushare also needs TUSHARE_TOKEN in .env
```

It lands in `./docker-data/qlib-data/qlib_data/cn_data/...` on the host and persists across
restarts. Requires network access.

**Already have the data?** `./docker-data/qlib-data/` maps to the container's `/root/.qlib`,
so copy your existing host data in, preserving the `qlib_data/...` layout — no re-download:

```bash
mkdir -p docker-data/qlib-data
cp -a ~/.qlib/. docker-data/qlib-data/   # copy CONTENTS, without an extra .qlib directory
```

Copy data while its source is idle. A dataset also needs a published research
revision marker; if `list_datasets` reports `ready=false`, run the matching
`prepare_data convert` operation to publish the selected adjustment mode. Copying
market data does not import factors, strategies, or stock pools.

## Persistent state (host bind mounts under `./docker-data/`)

Every artifact is a plain file on the host — browse it directly, no `docker cp`. `docker compose
down` (without `-v`) leaves it untouched.

| Host (`./docker-data/`) | Container path | Holds |
|--------|-------|-------|
| `qlib-data/` | `/root/.qlib` | downloaded market data (~2.4 GB) |
| `app-config/` | `/root/.alphapilot` | portal settings/env.json, runtime, notify creds & state |
| `workspace/` | `/app/git_ignore_folder` | mining/backtest run workspaces, factor_h5 cache, job/schedule state |
| `pickle-cache/` | `/app/pickle_cache` | reusable mine/backtest result cache |
| `logs/` | `/app/log` | application + LLM message logs |
| `factor-zoo/` | `/app/important_data/factor_zoo` | factor database and categories |
| `strategy-zoo/` | `/app/important_data/strategy_zoo` | strategy metadata and saved models |
| `stock-pools/` | `/app/important_data/stock_pools` | user stock-pool definitions |

Bundled templates, stock lists, and local strategy examples are copied from source
into the image. User factor/strategy libraries and stock pools are excluded from
the build context; import assets through the research API or migrate their storage
while both workspaces are stopped. Rebuilding the image must not be used to transfer
user assets.

When upgrading an old Compose deployment, drain active jobs and stop the old
services before switching configurations. Retire its standalone `scheduler`
container, preserve its research assets, and follow the [research migration guide](research/migration.md).
Legacy images stored libraries in their writable layer: export or copy those
directories **before removing the old containers**. Container recreation retains
persisted records and completed results; it terminates in-flight processes, which
the runtime reconciles instead of blindly rerunning. Restarting only the Portal
process within a live container is different: the research runtime can continue.

## Verify

```bash
# 1) frontend is built & served
curl -f http://localhost:19901/

# 2) the heavy stack imports cleanly (numpy-compat shim + qlib/torch/tables)
docker compose exec portal \
  python -c "import alphapilot, qlib, torch, tables, xgboost, catboost; print('ok', alphapilot.__version__)"

# 3) end-to-end local execution: run a small/debug mine or backtest from the portal,
#    then on the HOST confirm output appears (no Docker socket, no `docker exec`):
ls docker-data/workspace/runs/        # run workspace dirs
ls docker-data/logs/                  # log session dirs

# 4) queue and schedule dispatcher status; Compose health also checks this
docker compose exec portal alphapilot task_runtime status
docker compose ps
```

## Connect MCP to the Docker workspace

The independent [alphapilot-mcp](https://github.com/ai-yang/alphapilot-mcp) service
connects to the same `/api/v1` contract. Create a separate research credential for
each client inside the container:

```bash
docker compose exec portal alphapilot research_token create --client_id=codex --scopes=research:read,research:write,jobs:submit,jobs:cancel
```

For MCP running on the host, set `ALPHAPILOT_BASE_URL` to the Portal's published
address and `ALPHAPILOT_RESEARCH_TOKEN` to this deployment's Token. For MCP in
another container, attach it to the Compose network and use
`http://portal:19901`; `127.0.0.1` inside that container refers to MCP itself.
The private MCP HTTP endpoint has its own Bearer credential mapped to the backend
research Token. See the [MCP setup section](../README.md#研究-api-与-mcp-接入)
for clients and installation, and the MCP repository for its Docker image and
credential mapping. Neither MCP nor its container needs access to market-data
volumes or the Docker socket.

## Notes & gotchas

- **Architecture.** The default build targets **linux/amd64** (the torch CPU wheel is pulled
  from `download.pytorch.org/whl/cpu`). On an Apple-Silicon dev box, either build for amd64
  (`docker buildx build --platform linux/amd64 ...`). Native arm64 is not part of
  this Compose deployment's tested configuration.
- **Secrets.** `.env` is `.dockerignore`d and injected at runtime — never baked into the
  image. Local credentials and runtime directories are excluded from the build context.
- **Bind-mount ownership (Linux hosts).** The container runs as root, so files written into
  `./docker-data/` are root-owned. Pre-create the dirs (the `mkdir -p` above) or `chown` them
  afterwards. On macOS Docker Desktop this is transparently mapped to your user.
- **Don't reuse a host `app-config`.** A host `~/.alphapilot/portal/env.json` may store
  host-absolute data paths (`/Users/...`) that don't exist in the container. Let the container
  manage its own `app-config/`, or set data paths via `.env` — don't copy the host one in.
- **Memory / shm.** Backtests load the full dataset per worker and the portal spawns job
  workers. `portal` sets `shm_size: 2gb`; raise it, and
  set a `mem_limit`, if you run several concurrent jobs or hit OOM.
- **Portal bind.** Compose runs the portal on `0.0.0.0:19901` (the in-code default is
  `127.0.0.1`, which is unreachable from outside the container).
- **Restart control.** The portal's in-UI restart sends `SIGUSR1` and `os.execv`s itself;
  `tini` (image PID 1) reaps spawned workers and forwards `SIGTERM` for clean shutdown.
- **Build version.** `SETUPTOOLS_SCM_PRETEND_VERSION` is set because `.git` is excluded from
  the build context; the in-image version reports `0.0.0`.
- **pyqlib build.** If `pyqlib` has no prebuilt wheel for your platform it compiles from
  source; `build-essential` + `libhdf5-dev` in the image cover that, but it lengthens the
  first build.
- **Isolated execution (not enabled).** The `use_local=False` path (running generated code in
  sibling `local_qlib` containers) is intentionally unsupported here — it would need that
  image built and `/var/run/docker.sock` mounted. Compose pins `USE_LOCAL=True` so a
  host `.env` cannot accidentally enable that path.
- **Optional notification process.** `notify` waits for a healthy Portal and shares
  its PID namespace, so process identities in the shared workspace remain meaningful.
  Enable it only after configuring the desired channel.
- **Live image prerequisites.** `Dockerfile.live` is a separate optional build. It
  requires the locally installed `alphapilot_tts`, `alphapilot_xtpx`, `alphapilot_emt`
  binding sources and broker plugin directories. These private/vendor packages are
  not included in a normal clone; the research image does not require them.
