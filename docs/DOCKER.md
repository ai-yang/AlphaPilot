# Running AlphaPilot in Docker

This packages the whole stack — FastAPI + React **portal**, LLM factor **mining**, qlib
**backtest**, and **data download** — into one image, run via `docker compose` as three
services (`portal`, `scheduler`, `notify`).

LLM-generated factor/backtest code runs **as local subprocesses inside the container**
(`USE_LOCAL=True`), so there is **no docker-in-docker** and no Docker socket to mount.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage: Node builds the React `dist/`, then a Python 3.11 runtime |
| `docker-compose.yml` | `portal` + `scheduler` + `notify` off one image, with named volumes |
| `.dockerignore` | Keeps the ~1.9 GB of local caches/secrets out of the build context |
| `.env.docker.example` | Template for the `.env` compose reads (API keys, tokens) |

## Quick start

```bash
cp .env.docker.example .env        # fill in OPENAI_API_KEY, CHAT_MODEL, etc.
docker compose build               # first build is large/slow (torch + scientific stack)
docker compose up -d portal scheduler
# open http://localhost:19901
```

Optional Telegram/Feishu command receiver (needs a configured channel):

```bash
docker compose --profile notify up -d notify
```

## First run: download market data

Market data (~2.4 GB) is **not** baked into the image. On first use, trigger a data job
from the portal **Data** page, or from the CLI:

```bash
docker compose exec portal alphapilot platform prepare_data download   # baostock (no token)
# tushare also needs TUSHARE_TOKEN in .env
```

It lands in the `qlib_data` volume (`/root/.qlib/qlib_data/cn_data/...`) and persists across
restarts. Requires network access.

## Volumes (persistent state)

| Volume | Mount | Holds |
|--------|-------|-------|
| `qlib_data` | `/root/.qlib` | downloaded market data (~2.4 GB) |
| `alphapilot_home` | `/root/.alphapilot` | portal settings/env, runtime, notify creds & state |
| `git_ignore` | `/app/git_ignore_folder` | run workspaces, factor_h5 cache, job/schedule state |
| `pickle_cache` | `/app/pickle_cache` | reusable mine/backtest result cache |
| `logs` | `/app/log` | application + LLM message logs |

## Verify

```bash
# 1) frontend is built & served
curl -f http://localhost:19901/

# 2) the heavy stack imports cleanly (numpy-compat shim + qlib/torch/tables)
docker compose run --rm portal \
  python -c "import alphapilot, qlib, torch, tables, xgboost, catboost; print('ok', alphapilot.__version__)"

# 3) end-to-end local execution: run a small/debug mine or backtest from the portal
#    and confirm output under git_ignore_folder/runs/<id>/  (no Docker socket involved)
```

## Notes & gotchas

- **Architecture.** The default build targets **linux/amd64** (the torch CPU wheel is pulled
  from `download.pytorch.org/whl/cpu`). On an Apple-Silicon dev box, either build for amd64
  (`docker buildx build --platform linux/amd64 ...`) or, to build a native arm64 image,
  remove the explicit `pip install torch --index-url .../whl/cpu` line in the `Dockerfile`
  and let PyPI resolve torch.
- **Secrets.** `.env` is `.dockerignore`d and injected at runtime — never baked into the
  image. The repo's existing local `.env` holds a real `TUSHARE_TOKEN`; consider rotating it.
- **Memory / shm.** Backtests load the full dataset per worker and the portal spawns job
  workers (`multiprocessing` spawn). `portal`/`scheduler` set `shm_size: 2gb`; raise it, and
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
  image built and `/var/run/docker.sock` mounted.
