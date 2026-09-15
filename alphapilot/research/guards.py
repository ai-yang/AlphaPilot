"""Resource guards also used by trusted foreground CLI/domain entrypoints."""
from __future__ import annotations

import functools
import inspect
import json
from pathlib import Path

from .common import atomic_json, now
from .execution import ResourceLockService, resource_path
from .store import Store


def guarded(kind: str, mode: str):
    def decorate(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            values = dict(signature.bind_partial(*args, **kwargs).arguments)
            owner = args[0] if args else None
            context = getattr(owner, "context", None) or (owner if hasattr(owner, "config") else None)
            config = getattr(context, "config", None)
            if config is None:
                return function(*args, **kwargs)
            for key in ("options", "kwargs"):
                values.update(values.get(key) or {})
            resources = []
            if kind == "data":
                from alphapilot.systems.data import data_paths
                data = config.data
                source = values.get("source") or "baostock_cn"
                roots = [data.qlib_data_dir, data.raw_data_dir, data.factor_dir,
                         *(data_paths.existing_baostock_raw_dir(m) for m in ("none", "forward", "backward"))]
                if source in {"tushare", "tushare_cn"}:
                    roots = [data_paths.existing_tushare_qlib_dir(), data_paths.existing_tushare_factor_dir(),
                             *(data_paths.existing_tushare_raw_dir(m) for m in ("none", "forward", "backward"))]
                freq = values.get("freq", "day")
                if freq != "day":
                    roots.extend([data_paths.baostock_qlib_dir(freq), data_paths.baostock_minute_raw_dir(freq)])
                request = values.get("request")
                params = values.get("yaml_params") or getattr(request, "yaml_params", None)
                if isinstance(params, str) and params.lstrip().startswith("{"):
                    params = json.loads(params)
                if isinstance(params, dict) and params.get("provider_uri"):
                    if mode == "read":
                        roots = [params["provider_uri"]]
                    else:
                        roots.append(params["provider_uri"])
                if mode == "read" and (values.get("qlib_dir") or values.get("qlib_data_dir")):
                    roots = [values.get("qlib_dir") or values.get("qlib_data_dir")]
                for key in ("qlib_dir", "qlib_data_dir", "data_dir", "data_path", "output_dir", "raw_dir", "factor_dir"):
                    if values.get(key):
                        roots.append(values[key])
                resources.extend({"resource": resource_path(p), "mode": mode} for p in roots)
            else:
                if kind == "stock_pool":
                    from alphapilot.kernel.paths import stock_pools_dir
                    root = stock_pools_dir()
                    resources.append({"resource": resource_path(config.data.qlib_data_dir), "mode": mode})
                elif kind == "signal_session":
                    from alphapilot.systems.backtest.live.session import default_sessions_root
                    root = default_sessions_root()
                    name = values.get("session") or values.get("name")
                    if name:
                        from alphapilot.systems.strategy.database import FileStrategyParamDatabase
                        root = Path(root) / FileStrategyParamDatabase._sanitize_name(name)
                else:
                    root = config.factor.zoo_dir if kind == "factor" else config.strategy.param_dir
                    if kind == "strategy":
                        name = values.get("strategy_name") or getattr(values.get("request"), "strategy_name", None) or getattr(values.get("record"), "strategy_name", None)
                        if name:
                            from alphapilot.systems.strategy.database import FileStrategyParamDatabase
                            root = Path(root) / FileStrategyParamDatabase._sanitize_name(name)
                resources.append({"resource": resource_path(root), "mode": mode})
            with ResourceLockService(Store()).hold(resources) as execution_id:
                if kind == "factor" and mode == "write" and values.get("save", True) and hasattr(owner, "database"):
                    owner.database.reload()
                dirty_roots = {}
                if kind == "data" and mode == "write" and not values.get("dry_run"):
                    for root in roots:
                        root = Path(root).expanduser()
                        if (root / "features").exists() or root in {Path(values[k]).expanduser() for k in ("qlib_dir", "qlib_data_dir") if values.get(k)}:
                            marker = root / ".research-dirty.json"
                            if root not in dirty_roots:
                                dirty_roots[root] = json.loads(marker.read_text()) if marker.exists() else None
                                atomic_json(marker, {"owner": execution_id, "action": function.__name__})
                result = function(*args, **kwargs)
                for root, before in dirty_roots.items():
                    marker = root / ".research-revision.json"
                    previous = json.loads(marker.read_text()) if marker.exists() else {}
                    repair = function.__name__ in {"convert", "pipeline"}
                    if repair:
                        source = values.get("source") or values.get("benchmark_source") or "baostock_cn"
                        source = {"baostock": "baostock_cn", "tushare": "tushare_cn"}.get(source, source)
                        previous.update(source=source, adjust_mode=values.get("adjust_mode", "forward"))
                    atomic_json(marker, {**previous, "updated_at": now()})
                    if before is None or (repair and before.get("owner") != execution_id):
                        (root / ".research-dirty.json").unlink(missing_ok=True)
                return result
        return wrapped
    return decorate
