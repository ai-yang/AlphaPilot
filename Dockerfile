# syntax=docker/dockerfile:1

############################################################
# Stage 1 — build the React/Vite portal frontend.
# The portal's `web/dist` is gitignored (not committed), so FastAPI has nothing
# to serve unless we build it here. Output is copied into the runtime image.
############################################################
FROM node:20-slim AS web-builder
WORKDIR /web

# Install deps from the lockfile first for layer caching.
COPY alphapilot/modules/portal/web/package.json alphapilot/modules/portal/web/package-lock.json ./
RUN npm ci

# Build -> /web/dist (served by FastAPI create_app(static_dir=.../web/dist)).
COPY alphapilot/modules/portal/web/ ./
RUN npm run build


############################################################
# Stage 2 — Python runtime.
############################################################
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # setuptools_scm derives the version from git; .git is excluded from the
    # build context, so pin a version here or the install fails.
    SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 \
    # Run LLM-generated factor/backtest code as local subprocesses inside this
    # container (no docker-in-docker). This is the project's default.
    USE_LOCAL=True

# System deps:
#  - build-essential / pkg-config : compile python-Levenshtein and any sdist-only deps
#  - libgomp1                      : OpenMP runtime for xgboost / catboost / lightgbm(qlib)
#  - libhdf5-dev                   : HDF5 for pytables (`tables`); also covers source builds
#  - tini                          : PID 1 init (reap spawned job workers, forward SIGTERM)
#  - curl + ca-certificates        : healthcheck + HTTPS for data download / LLM APIs
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libgomp1 \
        libhdf5-dev \
        tini \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU-only torch first so the `alphaforge` extra below doesn't pull the
# multi-GB CUDA build. NOTE: this index targets linux/amd64. If you build for
# linux/arm64, remove this line and let PyPI resolve torch.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Runtime dependencies (declared in requirements.txt, consumed via pyproject).
# Copied alone first so this heavy layer is cached across source-only changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# `alphaforge` optional extra (AFF GAN + GP + RL). torch already satisfied above.
RUN pip install --no-cache-dir gym stable-baselines3 sb3-contrib shimmy

# Project source. Editable install so the package keeps living at /app/alphapilot:
# the code resolves the frontend, important_data, and the branding logo via
# Path(__file__)/relative-CWD paths, which must point at this tree (not site-packages).
COPY pyproject.toml README.md ./
COPY alphapilot/ ./alphapilot/
COPY important_data/ ./important_data/
COPY docs/ ./docs/
RUN pip install --no-cache-dir --no-deps -e .

# Drop the freshly built frontend into the package tree FastAPI serves from.
COPY --from=web-builder /web/dist ./alphapilot/modules/portal/web/dist

EXPOSE 19901

# tini as PID 1: reaps non-daemon spawned job workers and forwards signals so the
# portal's SIGUSR1 self-restart (os.execv) and SIGTERM shutdown behave correctly.
ENTRYPOINT ["tini", "--"]
# Default command; docker-compose overrides per service (portal / scheduler / notify).
CMD ["alphapilot", "portal", "--host", "0.0.0.0", "--port", "19901"]
