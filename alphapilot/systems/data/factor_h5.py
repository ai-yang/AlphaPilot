"""Content-addressed factor h5 cache (``daily_pv.h5``) keyed by data spec.

Replaces the single global ``factor_implementation_source_data*`` folders with a per
``market``/spec physical cache so parallel mining/backtest/live tasks never overwrite each
other's factor source, and so factor-execution / backtest pickle caches can include a data
fingerprint.

Layout (under repo ``git_ignore_folder/factor_h5_cache/``)::

    <spec_hash>/
      all/   { daily_pv.h5, README.md }   # full universe, fixed filename for factor scripts
      debug/ { daily_pv.h5, README.md }   # first N instruments
      manifest.json
      .complete
    <spec_hash>.lock                       # FileLock guarding the build

``manifest.json`` / ``.complete`` live at the spec-hash root, *never* inside ``all``/``debug``
(``factor_coder.data.get_file_desc`` only understands ``.h5``/``.md`` and would raise on json).

The module is intentionally import-light: qlib / generate_h5 / pandas are imported lazily so
``import alphapilot.systems.data.factor_h5`` (and the resolve helpers that depend on it) does
not pull qlib into every process.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from alphapilot.core.utils import md5_hash
from alphapilot.log import logger

# Bump when the h5 generation logic changes so existing caches are considered stale.
# v1: per-instrument $return (fixed groupby) + debug sliced from the full frame.
GENERATOR_VERSION = 1

DEFAULT_START = "2015-01-01"
DEFAULT_FIELDS: tuple[str, ...] = ("$open", "$close", "$high", "$low", "$volume")
DEFAULT_DEBUG_STOCK_COUNT = 100

# Env vars used to pass the data context across processes (multiprocessing spawn / Docker /
# qrun) where the python ``FactorDataContext`` object is not directly reachable.
ENV_DATA_DIR = "ALPHAPILOT_FACTOR_DATA_DIR"
ENV_DATA_DEBUG_DIR = "ALPHAPILOT_FACTOR_DATA_DEBUG_DIR"
ENV_FINGERPRINT = "ALPHAPILOT_FACTOR_DATA_FINGERPRINT"
ENV_MARKET = "ALPHAPILOT_FACTOR_DATA_MARKET"


def factor_h5_cache_root() -> Path:
    """Cache root, kept under the repo ``git_ignore_folder`` so Docker mounts can see it."""
    return Path("git_ignore_folder") / "factor_h5_cache"


def _default_market() -> str:
    from alphapilot.systems.data.prepare_cn import DEFAULT_STOCK_CSV
    from alphapilot.systems.data.stock_list import default_market_name

    return default_market_name(DEFAULT_STOCK_CSV)


def _default_qlib_dir() -> Path:
    from alphapilot.systems.data.data_paths import existing_baostock_qlib_dir

    return existing_baostock_qlib_dir()


def _instruments_hash(qlib_dir: Path, market: str) -> str:
    p = Path(qlib_dir).expanduser() / "instruments" / f"{market}.txt"
    if p.exists():
        return hashlib.md5(p.read_bytes()).hexdigest()
    return "no-instruments-file"


@dataclass(frozen=True)
class FactorDataSpec:
    """Inputs that fully determine a ``daily_pv.h5`` build."""

    qlib_dir: Path
    market: str
    start_date: str = DEFAULT_START
    fields: tuple[str, ...] = DEFAULT_FIELDS
    debug_stock_count: int = DEFAULT_DEBUG_STOCK_COUNT
    freq: str = "day"

    def fingerprint(self) -> str:
        payload = {
            "qlib_dir": str(Path(self.qlib_dir).expanduser().resolve()),
            "market": self.market,
            "start_date": self.start_date,
            "fields": list(self.fields),
            "debug_stock_count": self.debug_stock_count,
            "instruments_hash": _instruments_hash(self.qlib_dir, self.market),
            "generator_version": GENERATOR_VERSION,
        }
        # Only fold ``freq`` into the hash for intraday data so existing daily cache
        # fingerprints stay byte-identical (no needless rebuilds on upgrade).
        if self.freq != "day":
            payload["freq"] = self.freq
        return md5_hash(json.dumps(payload, sort_keys=True))


@dataclass(frozen=True)
class FactorDataContext:
    """Resolved data context threaded through mine/backtest/live."""

    spec: FactorDataSpec
    cache_dir: Path
    data_dir: Path
    debug_dir: Path
    fingerprint: str

    def env(self) -> dict[str, str]:
        return {
            ENV_DATA_DIR: str(self.data_dir),
            ENV_DATA_DEBUG_DIR: str(self.debug_dir),
            ENV_FINGERPRINT: self.fingerprint,
            ENV_MARKET: self.spec.market,
        }


def resolve_market(*, explicit: str | None = None, yaml_params: Any = None) -> str:
    """``explicit`` > ``yaml_params.market`` (aligns h5 universe with qrun) > stock-csv default."""
    if explicit:
        return explicit
    if yaml_params is not None:
        market = getattr(yaml_params, "market", None)
        if market is None and isinstance(yaml_params, dict):
            market = yaml_params.get("market")
        if market:
            return market
    return _default_market()


def _is_complete(cache_dir: Path, fingerprint: str) -> bool:
    if not (cache_dir / ".complete").exists():
        return False
    manifest = cache_dir / "manifest.json"
    if not manifest.exists():
        return False
    if not (cache_dir / "all" / "daily_pv.h5").exists():
        return False
    if not (cache_dir / "debug" / "daily_pv.h5").exists():
        return False
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("spec_hash") == fingerprint


def _readme_source() -> Path:
    from alphapilot.components.coder.factor_coder.data import default_factor_data_template_dir

    return default_factor_data_template_dir() / "README.md"


def _generate_in_docker(out_dir: Path, spec: FactorDataSpec) -> None:
    from alphapilot.utils.env import QTDockerEnv

    repo_root = Path(__file__).resolve().parents[3]
    qtde = QTDockerEnv(is_local=False)
    qtde.prepare()
    out = str(out_dir).replace("\\", "\\\\")
    qdir = str(Path(spec.qlib_dir).expanduser()).replace("\\", "\\\\")
    entry = (
        "python -c \"from alphapilot.systems.data.generate_h5 import generate_daily_pv_h5; "
        f"generate_daily_pv_h5(qlib_dir=r'{qdir}', output_dir=r'{out}', market={spec.market!r}, "
        f"start_date={spec.start_date!r}, debug_stock_count={spec.debug_stock_count}, freq={spec.freq!r})\""
    )
    qtde.run(local_path=str(repo_root), entry=entry)


def _write_manifest(cache_dir: Path, spec: FactorDataSpec) -> None:
    all_h5 = cache_dir / "all" / "daily_pv.h5"
    st = all_h5.stat()
    manifest = {
        "spec_hash": spec.fingerprint(),
        "market": spec.market,
        "qlib_dir": str(Path(spec.qlib_dir).expanduser().resolve()),
        "start_date": spec.start_date,
        "fields": list(spec.fields),
        "debug_stock_count": spec.debug_stock_count,
        "freq": spec.freq,
        "instruments_hash": _instruments_hash(spec.qlib_dir, spec.market),
        "generator_version": GENERATOR_VERSION,
        "daily_pv_size": st.st_size,
        "daily_pv_mtime_ns": st.st_mtime_ns,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _build_into(tmp_dir: Path, spec: FactorDataSpec, *, use_local: bool) -> None:
    import pandas as pd

    tmp_dir.mkdir(parents=True, exist_ok=True)
    gen_dir = tmp_dir / "_gen"
    gen_dir.mkdir(parents=True, exist_ok=True)

    if use_local:
        from alphapilot.systems.data.generate_h5 import generate_daily_pv_h5

        generate_daily_pv_h5(
            qlib_dir=spec.qlib_dir,
            output_dir=gen_dir,
            market=spec.market,
            fields=list(spec.fields),
            start_date=spec.start_date,
            debug_stock_count=spec.debug_stock_count,
            freq=spec.freq,
        )
    else:
        _generate_in_docker(gen_dir, spec)

    all_src = gen_dir / "daily_pv_all.h5"
    debug_src = gen_dir / "daily_pv_debug.h5"
    if not all_src.exists() or not debug_src.exists():
        raise RuntimeError(f"h5 generation did not produce expected files under {gen_dir}")

    all_dir = tmp_dir / "all"
    debug_dir = tmp_dir / "debug"
    all_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(all_src), str(all_dir / "daily_pv.h5"))
    shutil.move(str(debug_src), str(debug_dir / "daily_pv.h5"))

    readme = _readme_source()
    if readme.exists():
        shutil.copy(readme, all_dir / "README.md")
        shutil.copy(readme, debug_dir / "README.md")

    shutil.rmtree(gen_dir, ignore_errors=True)

    # Validate the published h5 can be opened before marking the cache complete.
    for p in (all_dir / "daily_pv.h5", debug_dir / "daily_pv.h5"):
        pd.read_hdf(p, key="data")

    _write_manifest(tmp_dir, spec)
    (tmp_dir / ".complete").write_text("", encoding="utf-8")


def build_or_get_cache(spec: FactorDataSpec, *, use_local: bool = True) -> Path:
    """Return the ``<spec_hash>`` cache dir, building it atomically under a FileLock if missing."""
    fingerprint = spec.fingerprint()
    root = factor_h5_cache_root().resolve()
    final = root / fingerprint
    if _is_complete(final, fingerprint):
        return final

    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / f"{fingerprint}.lock")):
        if _is_complete(final, fingerprint):
            return final
        logger.info(
            f"[factor_h5] building cache market={spec.market} spec_hash={fingerprint} "
            f"(use_local={use_local})"
        )
        tmp_dir = root / f".tmp-{fingerprint}-{os.getpid()}"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        try:
            _build_into(tmp_dir, spec, use_local=use_local)
            if final.exists():
                shutil.rmtree(final, ignore_errors=True)
            os.replace(tmp_dir, final)
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
    return final


def context_from_cache_dir(spec: FactorDataSpec, cache_dir: Path) -> FactorDataContext:
    cache_dir = Path(cache_dir).resolve()
    return FactorDataContext(
        spec=spec,
        cache_dir=cache_dir,
        data_dir=(cache_dir / "all").resolve(),
        debug_dir=(cache_dir / "debug").resolve(),
        fingerprint=spec.fingerprint(),
    )


def apply_context_env(ctx: FactorDataContext) -> None:
    """Publish *ctx* to ``os.environ`` so spawned subprocesses / qrun / Docker resolve it."""
    os.environ.update(ctx.env())


def load_context_from_cache_dir(cache_dir: str | Path) -> FactorDataContext:
    """Rehydrate a context from an already-built cache dir (reuse path), via its manifest."""
    cache_dir = Path(cache_dir).resolve()
    manifest = cache_dir / "manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(f"No manifest.json under factor data dir: {cache_dir}")
    data = json.loads(manifest.read_text())
    spec = FactorDataSpec(
        qlib_dir=Path(data["qlib_dir"]),
        market=data["market"],
        start_date=data.get("start_date", DEFAULT_START),
        fields=tuple(data.get("fields", DEFAULT_FIELDS)),
        debug_stock_count=data.get("debug_stock_count", DEFAULT_DEBUG_STOCK_COUNT),
        freq=data.get("freq", "day"),
    )
    return FactorDataContext(
        spec=spec,
        cache_dir=cache_dir,
        data_dir=(cache_dir / "all").resolve(),
        debug_dir=(cache_dir / "debug").resolve(),
        fingerprint=data.get("spec_hash") or spec.fingerprint(),
    )


def prepare_factor_data_context(
    *,
    market: str | None = None,
    qlib_dir: str | Path | None = None,
    start_date: str = DEFAULT_START,
    fields: list[str] | tuple[str, ...] | None = None,
    debug_stock_count: int = DEFAULT_DEBUG_STOCK_COUNT,
    yaml_params: Any = None,
    use_local: bool = True,
    freq: str = "day",
) -> FactorDataContext:
    """Resolve a spec for *market*, ensure its cache, and return the data context."""
    resolved_market = resolve_market(explicit=market, yaml_params=yaml_params)
    resolved_qlib = Path(qlib_dir).expanduser() if qlib_dir else _default_qlib_dir()
    spec = FactorDataSpec(
        qlib_dir=resolved_qlib,
        market=resolved_market,
        start_date=start_date,
        fields=tuple(fields) if fields else DEFAULT_FIELDS,
        debug_stock_count=debug_stock_count,
        freq=freq,
    )
    cache_dir = build_or_get_cache(spec, use_local=use_local)
    ctx = context_from_cache_dir(spec, cache_dir)
    logger.info(
        f"[factor_h5] context ready market={resolved_market} spec_hash={ctx.fingerprint} "
        f"data_dir={ctx.data_dir}"
    )
    return ctx


def clean_factor_h5_cache(market: str | None = None) -> int:
    """Delete factor h5 cache entries (and stale tmp/lock files). Returns dirs removed.

    When *market* is given, only entries whose manifest market matches are removed.
    """
    root = factor_h5_cache_root().resolve()
    if not root.exists():
        return 0
    removed = 0
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.startswith(".tmp-"):
            shutil.rmtree(entry, ignore_errors=True)
            continue
        if entry.is_file() and entry.suffix == ".lock":
            entry.unlink(missing_ok=True)
            continue
        if not entry.is_dir():
            continue
        if market is not None:
            manifest = entry / "manifest.json"
            try:
                if json.loads(manifest.read_text()).get("market") != market:
                    continue
            except (OSError, json.JSONDecodeError):
                continue
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
    logger.info(f"[factor_h5] cleaned {removed} cache entr{'y' if removed == 1 else 'ies'} from {root}")
    return removed


def prepare_or_reuse_context(
    *,
    market: str | None = None,
    qlib_dir: str | Path | None = None,
    yaml_params: Any = None,
    factor_data_dir: str | Path | None = None,
    start_date: str = DEFAULT_START,
    use_local: bool = True,
    freq: str = "day",
) -> FactorDataContext:
    """Reuse *factor_data_dir* when given, else build/hit the cache for the resolved market."""
    if factor_data_dir:
        return load_context_from_cache_dir(factor_data_dir)
    return prepare_factor_data_context(
        market=market,
        qlib_dir=qlib_dir,
        yaml_params=yaml_params,
        start_date=start_date,
        use_local=use_local,
        freq=freq,
    )
