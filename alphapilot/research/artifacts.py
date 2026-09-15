"""Explicit run/immutable artifact registry for remote consumers."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import uuid
from pathlib import Path

from .auth import Actor
from .common import ResearchError, atomic_json, encode, now, opaque
from .store import Store
from .tasks import page


def public_value(value):
    """Remove internal storage/execution references from structured domain output."""
    from .common import json_value
    value = json_value(value)
    if isinstance(value, dict):
        return {k: public_value(v) for k, v in value.items()
                if not any(p in k.lower() for p in ("path", "_dir", "provider_uri", "artifact_uri", "token", "secret", "password", "api_key"))}
    if isinstance(value, list):
        return [public_value(v) for v in value]
    return value


class ArtifactService:
    def __init__(self, store: Store):
        self.store = store

    def register(self, path: Path, *, kind: str, job_id: str | None = None,
                 run_id: str | None = None, attempt: str | None = None, published: bool = True) -> dict:
        key = uuid.uuid4().hex
        destination = self.store.root / "artifacts" / key / path.name
        destination.parent.mkdir(parents=True)
        checksum = hashlib.sha256()
        with path.open("rb") as source, destination.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                checksum.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        payload = {"artifact_id": key, "job_id": job_id, "run_id": run_id, "kind": kind,
                   "schema_version": "1", "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                   "size": destination.stat().st_size, "sha256": checksum.hexdigest(), "name": path.name,
                   "created_at": now(), "content_url": f"/api/v1/artifacts/{key}/content"}
        try:
            with self.store.connect(write=True) as db:
                if job_id and attempt:
                    row = db.execute("SELECT status,attempt FROM jobs WHERE id=?", (job_id,)).fetchone()
                    if not row or row["attempt"] != attempt or row["status"] != "running":
                        raise ResearchError("EXECUTION_ENDED", "Cannot publish from an inactive execution", 409)
                db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?)",
                           (key, job_id, run_id, attempt, str(destination), encode(payload), int(published)))
        except BaseException:
            shutil.rmtree(destination.parent, ignore_errors=True)
            raise
        return payload

    def register_json(self, value, *, kind: str, **kwargs) -> dict:
        temp = self.store.root / "staging" / f"{uuid.uuid4().hex}.json"
        atomic_json(temp, value)
        try:
            return self.register(temp, kind=kind, **kwargs)
        finally:
            temp.unlink(missing_ok=True)

    def get(self, artifact_id: str, actor: Actor, *, content: bool = False):
        actor.require("research:read")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=? AND published=1", (opaque(artifact_id),)).fetchone()
        if not row:
            raise ResearchError("NOT_FOUND", "Artifact not found", 404)
        if content:
            path = Path(row["path"]).resolve()
            if self.store.root / "artifacts" not in path.parents or not path.is_file():
                raise ResearchError("ARTIFACT_UNAVAILABLE", "Artifact content is unavailable", 404)
            return path
        return json.loads(row["payload"])

    def runs(self, actor: Actor, *, cursor=None, limit=50) -> dict:
        actor.require("research:read")
        with self.store.connect() as db:
            rows = db.execute("SELECT id FROM runs ORDER BY id DESC").fetchall()
        return page([self.run(row[0], actor) for row in rows], cursor, limit)

    def run(self, run_id: str, actor: Actor) -> dict:
        actor.require("research:read")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (opaque(run_id),)).fetchone()
            artifacts = db.execute("SELECT payload FROM artifacts WHERE run_id=? AND published=1 ORDER BY id", (run_id,)).fetchall()
        if not row:
            raise ResearchError("NOT_FOUND", "Research run not found", 404)
        return {**public_value(json.loads(row["payload"])), "run_id": run_id, "job_id": row["job_id"],
                "artifacts": [json.loads(a[0]) for a in artifacts]}

    def table(self, artifact_id: str, actor: Actor, *, cursor=None, limit=50) -> dict:
        import pandas as pd
        path = self.get(artifact_id, actor, content=True)
        if path.suffix == ".csv":
            df = pd.read_csv(path)
        elif path.suffix == ".json":
            value = json.loads(path.read_text())
            df = pd.DataFrame(value if isinstance(value, list) else value.get("rows", []))
        else:
            raise ResearchError("NOT_A_TABLE", "Artifact is not a supported table", 422)
        from .common import json_value
        return {"columns": [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns],
                **page(json_value(df.to_dict(orient="records")), cursor, limit)}


def record_run(run_id: str, path: Path, payload: dict) -> None:
    store = Store()
    job_id, attempt = os.getenv("ALPHAPILOT_PORTAL_JOB_ID"), os.getenv("ALPHAPILOT_JOB_ATTEMPT")
    with store.connect(write=True) as db:
        if job_id:
            job = db.execute("SELECT attempt,status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["attempt"] != attempt or job["status"] not in {"running", "cancelling"}:
                return
        db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
                   (run_id, job_id, attempt, str(path), encode(payload)))


def record_output(value, kind: str, *, path: Path | None = None) -> dict | None:
    from alphapilot.systems.run_workspace import current_run
    run = current_run()
    if run is None:
        return None
    service = ArtifactService(Store())
    args = {"kind": kind, "run_id": run.run_id, "job_id": os.getenv("ALPHAPILOT_PORTAL_JOB_ID"),
            "attempt": os.getenv("ALPHAPILOT_JOB_ATTEMPT")}
    return service.register(path, **args) if path else service.register_json(public_value(value), **args)


def record_experiment(experiment, metrics, per_factor=None) -> None:
    """Register an experiment at production time, including IC-only experiments."""
    from alphapilot.systems.run_workspace import current_run, run_workspace
    run = current_run()
    if run is None:
        return
    workspace = getattr(getattr(experiment, "experiment_workspace", None), "workspace_path", None)
    # Each evaluation has its own Run, so sequential backtests expose an
    # unambiguous set of curves/tables for every factor, not just the last one.
    with run_workspace(command="factor_evaluation", market=run._manifest.get("market")) as evaluation:
        evaluation.record(parent_run_id=run.run_id,
                          normalized_input=run._manifest.get("normalized_input"),
                          dataset_revision=run._manifest.get("dataset_revision"),
                          execution_configuration=public_value(getattr(experiment, "yaml_params", None)),
                          experiment_id=Path(workspace).name if workspace else None)
        record_output({"experiment_id": Path(workspace).name if workspace else None,
                       "metrics": metrics, "per_factor": per_factor}, "evaluation")
        if workspace is not None:
            publish_backtest(Path(workspace), lambda value, kind, path=None: record_output(value, kind, path=path))


def publish_backtest(workspace: Path, emit) -> None:
    """Convert a trusted result at production/migration time to public artifacts."""
    if workspace is None or not (Path(workspace) / "ret.pkl").is_file():
        return
    from alphapilot.systems.backtest.artifacts import load_backtest, build_summary
    from alphapilot.modules.backtest_viz.charts import nav_return_series
    data = load_backtest(Path(workspace))
    emit({"experiment_id": Path(workspace).name, "summary": build_summary(data.report),
          "metrics": data.metrics}, "backtest_summary")
    for kind, frame in (("report", data.report), ("cumulative", nav_return_series(data.report)),
                        ("trades", data.trades), ("holdings", data.holdings)):
        if frame is None:
            continue
        frame = frame.copy()
        if kind in {"report", "cumulative"}:
            frame.index.name = "date"
            frame = frame.reset_index()
        target = Path(workspace) / f"research_{kind}.csv"
        frame.to_csv(target, index=False)
        emit(None, kind, path=target)


def publish_logs(source: Path, emit) -> None:
    """Expose readable research logs, never Python object/pickle session state."""
    for path in sorted(source.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix in {".log", ".txt", ".json", ".md", ".csv", ".py"}:
            emit(None, "mining_log", path=path)
