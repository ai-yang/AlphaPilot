"""Durable state-machine tests: no LLMs, market downloads or broker plugins."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from alphapilot.research.auth import Actor, AuthService
from alphapilot.research.common import ResearchError, atomic_json, encode, now
from alphapilot.research.execution import ExecutionHandle, ResourceLockService, alive, identity, resource_path
from alphapilot.research.models import ScheduleCreate
from alphapilot.research.runtime import TaskRuntime, worker
from alphapilot.research.schedules import ScheduleService
from alphapilot.research.store import Store
from alphapilot.research.tasks import TaskService


@pytest.fixture(autouse=True)
def installed_live_test_plugins():
    yield


@pytest.fixture
def workspace(tmp_path, monkeypatch, isolated_env):
    monkeypatch.setenv("ALPHAPILOT_PORTAL_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("ALPHAPILOT_RESEARCH_AUTOSTART", "0")
    for key in ("ALPHAPILOT_PORTAL_JOB_ID", "ALPHAPILOT_PORTAL_JOB_DIR", "ALPHAPILOT_JOB_ATTEMPT", "ALPHAPILOT_EXECUTION_ID"):
        monkeypatch.setenv(key, "")
    store = Store()
    from alphapilot.research import executor, runtime
    monkeypatch.setattr(executor, "prepare", lambda engine, store, spec, folder, actor: (
        {"kind": spec.kind, "input": spec.input.model_dump(mode="json"), "folder": str(folder), "resources": [{"resource": "fixture-dataset", "mode": "read"}]}, spec.input.model_dump(mode="json")))
    monkeypatch.setattr(executor, "execute", lambda _: {"factors": [], "qualified_count": 0})
    monkeypatch.setattr(runtime, "identity", lambda *args: {"pid": 999999999, "created": 1, "boot": psutil.boot_time()})
    from alphapilot.modules.portal import env_config
    monkeypatch.setattr(env_config, "apply_portal_env", lambda: None)
    tasks = TaskService(store, engine=object(), autostart=False)
    return tasks, TaskRuntime(store), Actor.local()


def submit(workspace, key="task"):
    tasks, runtime, actor = workspace
    return tasks.submit({"kind": "mine", "input": {"dataset_id": "fixture", "max_steps": 2}}, actor, key)


def test_concurrent_idempotency_is_atomic(workspace):
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda _: submit(workspace), range(12)))
    assert len({r["job_id"] for r in rows}) == 1
    tasks, _, actor = workspace
    assert len(tasks.list(actor)["items"]) == 1
    assert len(list(tasks.store.root.glob("*/job.json"))) == 1


def test_capacity_and_client_specific_idempotency(workspace, monkeypatch):
    monkeypatch.setenv("ALPHAPILOT_RESEARCH_MAX_QUEUED", "1")
    first = submit(workspace)
    assert submit(workspace)["job_id"] == first["job_id"]
    with pytest.raises(ResearchError, match="queue"):
        submit(workspace, "second")
    tasks, runtime, actor = workspace
    assert runtime.claim()
    second = submit(workspace, "second")
    assert runtime.claim() is None
    assert second["status"] == "queued"


def test_worker_fences_and_completion_wait_for_reconciliation(workspace):
    tasks, runtime, actor = workspace
    job = submit(workspace)
    key, attempt = runtime.claim()
    assert not worker(tasks.store, key, "wrong-attempt")
    assert worker(tasks.store, key, attempt)
    assert tasks.get(key, actor)["status"] == "running"
    restarted = TaskRuntime(Store(tasks.store.root))
    restarted.reconcile()
    assert tasks.get(key, actor)["status"] == "succeeded"
    assert tasks.read_result(key, actor)["availability"] == "complete"
    assert tasks.read_result(key, actor)["summary"] == {"factors": [], "qualified_count": 0}
    assert restarted.claim() is None


def test_cancel_before_worker_registration(workspace):
    tasks, runtime, actor = workspace
    submit(workspace)
    key, attempt = runtime.claim()
    assert tasks.cancel(key, actor)["status"] == "cancelling"
    assert not worker(tasks.store, key, attempt)
    runtime.reconcile()
    assert tasks.get(key, actor)["status"] == "cancelled"
    assert runtime.claim() is None


def test_late_completion_cannot_overwrite_cancel(workspace, monkeypatch):
    tasks, runtime, actor = workspace
    submit(workspace)
    key, attempt = runtime.claim()
    from alphapilot.research import executor
    def late(_):
        tasks.cancel(key, actor)
        return {"late": True}
    monkeypatch.setattr(executor, "execute", late)
    assert not worker(tasks.store, key, attempt)
    runtime.reconcile()
    assert tasks.get(key, actor)["status"] == "cancelled"
    assert not (tasks.store.root / key / "result.json").exists()
    assert tasks.read_result(key, actor)["availability"] == "unavailable"


def test_lost_execution_is_not_automatically_retried(workspace):
    tasks, runtime, actor = workspace
    submit(workspace)
    key, attempt = runtime.claim()
    with tasks.store.connect(write=True) as db:
        row = json.loads(db.execute("SELECT payload FROM jobs WHERE id=?", (key,)).fetchone()[0])
        row.update(status="running", started_at=now())
        db.execute("UPDATE jobs SET status='running',payload=? WHERE id=?", (encode(row), key))
    TaskRuntime(Store(tasks.store.root)).reconcile()
    assert tasks.get(key, actor)["status"] == "lost"
    assert runtime.claim() is None


def test_unregistered_start_can_be_requeued_only_after_cleanup(workspace):
    tasks, runtime, actor = workspace
    submit(workspace)
    key, attempt = runtime.claim()
    with tasks.store.connect(write=True) as db:
        db.execute("UPDATE executions SET created=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat(), attempt))
    runtime.reconcile()
    assert tasks.get(key, actor)["status"] == "cancelling"
    assert not worker(tasks.store, key, attempt)
    runtime.reconcile()
    assert tasks.get(key, actor)["status"] == "queued"
    assert runtime.claim()[1] != attempt


def test_docker_unavailable_blocks_cancellation_and_resources(workspace, monkeypatch):
    tasks, runtime, actor = workspace
    submit(workspace)
    key, attempt = runtime.claim()
    ExecutionHandle(tasks.store, attempt).docker_intent()
    tasks.cancel(key, actor)
    import docker
    monkeypatch.setattr(docker, "from_env", lambda **_: (_ for _ in ()).throw(ConnectionError("offline")))
    runtime.reconcile()
    assert tasks.get(key, actor)["status"] == "cancelling"
    assert tasks.get(key, actor)["error"]["code"] == "EXECUTION_UNCONFIRMED"
    with tasks.store.connect() as db:
        assert db.execute("SELECT 1 FROM locks WHERE owner=?", (attempt,)).fetchone()
    monkeypatch.setattr(docker, "from_env", lambda **_: SimpleNamespace(containers=SimpleNamespace(list=lambda **_: [])))
    runtime.reconcile()
    assert tasks.get(key, actor)["status"] == "cancelled"


def test_resource_locks_and_symlink_aliases(workspace, tmp_path):
    tasks, _, _ = workspace
    directory = tmp_path / "data"; directory.mkdir()
    alias = tmp_path / "alias"; alias.symlink_to(directory)
    assert resource_path(alias) == resource_path(directory)
    locks = ResourceLockService(tasks.store)
    resource = resource_path(directory)
    assert locks.acquire("one", [{"resource": resource, "mode": "read"}])
    assert locks.acquire("two", [{"resource": resource_path(alias), "mode": "read"}])
    assert not locks.acquire("writer", [{"resource": resource, "mode": "write"}])
    locks.release("one"); locks.release("two")
    assert locks.acquire("writer", [{"resource": resource, "mode": "write"}])
    assert not locks.acquire("reader", [{"resource": resource, "mode": "read"}])


def test_pid_birth_time_prevents_reuse():
    saved = identity()
    assert alive(saved)
    assert not alive({**saved, "created": saved["created"] - 10})
    assert not alive({**saved, "boot": saved["boot"] - 1})


def test_real_process_group_cancellation(workspace):
    tasks, _, _ = workspace
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        with tasks.store.connect(write=True) as db:
            db.execute("INSERT INTO executions(id,identity,created) VALUES (?,?,?)", ("child", encode(identity(process.pid)), now()))
        assert ExecutionHandle(tasks.store, "child").stop(grace=.2)
        process.wait(timeout=3)
        assert not psutil.pid_exists(process.pid)
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=3)


def test_schedules_idempotency_and_revocation(workspace):
    tasks, _, _ = workspace
    auth = AuthService(tasks.store)
    issued = auth.create("scheduler-test", ["research:read", "research:write", "jobs:submit", "schedules:write"])
    actor = auth.authenticate("Bearer " + issued["token"], "schedule-test")
    service = ScheduleService(tasks)
    row = service.save(ScheduleCreate(name="daily", time="09:00", timezone="UTC", job={"kind": "mine", "input": {"dataset_id": "fixture", "max_steps": 2}}), actor)
    instant = datetime(2026, 9, 14, 10, tzinfo=timezone.utc)
    assert len(service.run_due(instant)) == 1
    assert service.run_due(instant) == []
    auth.revoke(issued["credential_id"])
    outcome = service.run_due(instant + timedelta(days=1))
    assert "error" in outcome[0]
    assert len(tasks.list(Actor.local())["items"]) == 1


def test_partial_artifacts_survive_failure(workspace, tmp_path, monkeypatch):
    tasks, runtime, actor = workspace
    submit(workspace)
    key, attempt = runtime.claim()
    from alphapilot.research import executor
    from alphapilot.research.artifacts import ArtifactService
    def fails(_):
        ArtifactService(tasks.store).register_json({"metrics": {"ic": .1}}, kind="evaluation", job_id=key, attempt=attempt)
        raise ResearchError("BUSINESS_FAILURE", "strategy failed")
    monkeypatch.setattr(executor, "execute", fails)
    worker(tasks.store, key, attempt)
    runtime.reconcile()
    result = tasks.read_result(key, actor)
    assert result["availability"] == "partial"
    assert result["error"]["code"] == "BUSINESS_FAILURE"
    assert len(result["artifact_ids"]) == 1


def test_session_commit_is_recoverable_and_day_idempotent(workspace, tmp_path, monkeypatch):
    from alphapilot.systems.backtest.live import session
    from alphapilot.systems.backtest.live.types import PortfolioState
    from alphapilot.research import common
    root = tmp_path / "sessions"
    folder = root / "demo"
    atomic_json(folder / "session.json", {"name": "demo", "current_date": None, "init_cash": 100, "source_strategy": "fixture"})
    state = PortfolioState(date="2026-01-05", cash=90)
    summary = {"date": "2026-01-05", "trades": [], "new_cash": 90, "n_positions": 0}
    original = common.atomic_json
    def interrupted(path, value):
        if path.name == "state.json":
            raise OSError("simulated crash during publication")
        return original(path, value)
    monkeypatch.setattr(common, "atomic_json", interrupted)
    with pytest.raises(OSError):
        session.commit_day("demo", state, summary, root=root)
    assert (folder / ".commit.json").exists()
    monkeypatch.setattr(common, "atomic_json", original)
    recovered = session.load_session("demo", root=root)
    assert recovered["manifest"]["current_date"] == "2026-01-05"
    assert recovered["state"]["cash"] == 90
    assert not (folder / ".commit.json").exists()
    prior = session.commit_day("demo", PortfolioState(date="2026-01-05", cash=1), summary, root=root)
    assert prior["new_cash"] == 90
    assert len(session.read_log("demo", root=root)) == 1
    assert session.adjust_cash("demo", 10, root=root)["new_cash"] == 100
    assert session.load_session("demo", root=root)["state"]["cash"] == 100


def test_local_subprocess_registers_before_execution(workspace, tmp_path):
    from alphapilot.research.execution import managed_local_command
    tasks, _, _ = workspace
    marker = tmp_path / "executed.txt"
    locks = ResourceLockService(tasks.store)
    with locks.hold([{"resource": "local-test", "mode": "write"}]) as owner:
        command, env, isolate = managed_local_command([sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ok')", str(marker)], dict(os.environ))
        result = subprocess.run(command, env=env, cwd=tmp_path, start_new_session=isolate, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert marker.read_text() == "ok"
        with tasks.store.connect() as db:
            assert db.execute("SELECT identity FROM child_processes WHERE execution_id=?", (owner,)).fetchone()
    marker.unlink()
    denied = subprocess.run(command, env=env, cwd=tmp_path, start_new_session=isolate, capture_output=True, text=True, timeout=15)
    assert denied.returncode != 0 and not marker.exists()


def test_migration_preserves_ids_results_and_does_not_guess_run_links(workspace, tmp_path, monkeypatch):
    from alphapilot.research.migration import migrate
    tasks, _, actor = workspace
    monkeypatch.setenv("ALPHAPILOT_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ALPHAPILOT_PORTAL_SCHEDULE_ROOT", str(tmp_path / "schedules"))
    atomic_json(tasks.store.root / "historic" / "job.json", {"job_id": "historic", "kind": "factor_backtest", "status": "succeeded"})
    atomic_json(tasks.store.root / "historic" / "result.json", {"result": {"ic": .2}})
    atomic_json(tmp_path / "runs" / "unlinked" / "manifest.json", {"command": "backtest", "status": "succeeded"})
    with pytest.raises(ResearchError, match="migration|migrate"):
        submit(workspace)
    assert migrate(tasks.store, object())["executed"] is False
    report = migrate(tasks.store, object(), execute=True)
    assert Path(report["backup"]).is_dir()
    assert tasks.get("historic", actor)["job_id"] == "historic"
    assert tasks.read_result("historic", actor)["summary"] == {"ic": .2}
    from alphapilot.research.artifacts import ArtifactService
    assert ArtifactService(tasks.store).run("unlinked", actor)["job_id"] is None
    assert ArtifactService(tasks.store).run("unlinked", actor)["association"] == "unknown"
    assert migrate(tasks.store, object(), execute=True)["jobs"] == 0


def test_uncommitted_result_is_not_visible(workspace):
    tasks, runtime, actor = workspace
    job = submit(workspace)
    key, attempt = runtime.claim()
    atomic_json(tasks.store.root / key / f"result.{attempt}.json", {"uncommitted": True})
    atomic_json(tasks.store.root / key / "result.json", {"orphan_from_old_publication": True})
    assert tasks.read_result(key, actor)["summary"] is None
    tasks.cancel(key, actor)
    runtime.reconcile()
    assert tasks.read_result(key, actor)["availability"] == "unavailable"


def test_overlapping_lock_scopes_do_not_release_other_threads(workspace, monkeypatch):
    import threading
    tasks, _, _ = workspace
    owner = "shared-owner"
    with tasks.store.connect(write=True) as db:
        db.execute("INSERT INTO executions(id,identity,created) VALUES (?,?,?)", (owner, encode(identity()), now()))
    monkeypatch.setenv("ALPHAPILOT_EXECUTION_ID", owner)
    acquired, release = threading.Event(), threading.Event()
    def other_scope():
        with ResourceLockService(tasks.store).hold([{"resource": "overlap", "mode": "read"}]):
            acquired.set()
            assert release.wait(10)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            with ResourceLockService(tasks.store).hold([{"resource": "overlap", "mode": "read"}]):
                future = pool.submit(other_scope)
                assert acquired.wait(10)
            assert not ResourceLockService(tasks.store).acquire("competitor", [{"resource": "overlap", "mode": "write"}])
        finally:
            release.set()
        future.result()
    assert ResourceLockService(tasks.store).acquire("competitor", [{"resource": "overlap", "mode": "write"}])


def test_pending_cli_cleanup_is_retried_without_stopping_the_owner(workspace, monkeypatch):
    tasks, runtime, _ = workspace
    monkeypatch.setattr(ExecutionHandle, "stop", lambda *_args, **_kwargs: False)
    with pytest.raises(ResearchError, match="cleanup"):
        with ResourceLockService(tasks.store).hold([{"resource": "cli-data", "mode": "write"}]) as owner:
            pass
    calls = []
    monkeypatch.setattr(ExecutionHandle, "stop", lambda self, **kwargs: calls.append(kwargs) or True)
    runtime.reconcile()
    assert calls == [{"stop_process": False}]
    with tasks.store.connect() as db:
        assert not db.execute("SELECT 1 FROM locks WHERE owner=?", (owner,)).fetchone()


def test_each_experiment_has_a_run_and_successful_runs_survive_later_failure(workspace, monkeypatch):
    tasks, runtime, actor = workspace
    from alphapilot.research import executor
    from alphapilot.research.artifacts import record_experiment, ArtifactService
    from alphapilot.systems.run_workspace import run_workspace
    def execute(_):
        with run_workspace(command="multi_sequential") as run:
            run.record(normalized_input={"mode": "multi_sequential"}, dataset_revision="data-v2")
            record_experiment(SimpleNamespace(), {"IC": .1})
            record_experiment(SimpleNamespace(), {"IC": .2})
            raise ResearchError("BUSINESS_FAILURE", "third factor failed")
    monkeypatch.setattr(executor, "execute", execute)
    submit(workspace)
    key, attempt = runtime.claim()
    worker(tasks.store, key, attempt)
    runtime.reconcile()
    job = tasks.get(key, actor)
    runs = [ArtifactService(tasks.store).run(r, actor) for r in job["run_ids"]]
    evaluations = [r for r in runs if r["command"] == "factor_evaluation"]
    assert len(evaluations) == 2
    assert all(r["status"] == "succeeded" and r["dataset_revision"] == "data-v2" for r in evaluations)
    assert all(len(r["artifacts"]) == 1 for r in evaluations)
    assert tasks.read_result(key, actor)["availability"] == "partial"


def test_docker_nonzero_exit_is_an_execution_failure(workspace, monkeypatch):
    from alphapilot.utils.env import DockerConf, DockerEnv
    container = SimpleNamespace(id="fake", name="fake", start=lambda: None,
        logs=lambda **kw: iter([b"failed calculation"]), wait=lambda: {"StatusCode": 7},
        stop=lambda **kw: None, remove=lambda: None)
    calls = []
    client = SimpleNamespace(containers=SimpleNamespace(create=lambda **kw: calls.append(kw) or container))
    import docker
    monkeypatch.setattr(docker, "from_env", lambda **kw: client)
    env = DockerEnv(DockerConf.model_construct(image="fixture", mount_path="/workspace", default_entry="python run.py", enable_gpu=False))
    with pytest.raises(RuntimeError, match="status 7"):
        env.run()
    assert len(calls) == 1


def test_migration_resumes_after_artifact_commit_without_duplicate_publications(workspace, tmp_path, monkeypatch):
    from alphapilot.research.migration import migrate
    from alphapilot.research.artifacts import ArtifactService
    tasks, _, actor = workspace
    monkeypatch.setenv("ALPHAPILOT_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ALPHAPILOT_PORTAL_SCHEDULE_ROOT", str(tmp_path / "schedules"))
    run = tmp_path / "runs" / "interrupted"
    atomic_json(run / "manifest.json", {"command": "backtest", "status": "completed"})
    atomic_json(run / "workspaces" / "eval" / "one.json", {"ic": .2})
    atomic_json(run / "workspaces" / "eval" / "two.json", {"ic": .3})
    original = ArtifactService.register
    def crash_after_commit(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise KeyboardInterrupt("migration process terminated")
    monkeypatch.setattr(ArtifactService, "register", crash_after_commit)
    with pytest.raises(KeyboardInterrupt):
        migrate(tasks.store, object(), execute=True)
    with pytest.raises(ResearchError, match="Resume"):
        tasks.store.require_migrated()
    assert len(ArtifactService(tasks.store).run("interrupted", actor)["artifacts"]) == 1
    monkeypatch.setattr(ArtifactService, "register", original)
    migrate(tasks.store, object(), execute=True)
    tasks.store.require_migrated()
    result = ArtifactService(tasks.store).run("interrupted", actor)
    assert result["migration_artifacts"] == "complete"
    assert len(result["artifacts"]) == 2
    migrate(tasks.store, object(), execute=True)
    assert len(ArtifactService(tasks.store).run("interrupted", actor)["artifacts"]) == 2


def test_missing_successful_result_is_unavailable_not_a_zero_output(workspace):
    tasks, runtime, actor = workspace
    submit(workspace)
    key, attempt = runtime.claim()
    worker(tasks.store, key, attempt)
    runtime.reconcile()
    assert tasks.read_result(key, actor)["availability"] == "complete"
    (tasks.store.root / key / f"result.{attempt}.json").unlink()
    assert tasks.read_result(key, actor)["availability"] == "unavailable"


@pytest.mark.parametrize("mode,experiments", [("single_ic", 1), ("multi_combined", 1), ("multi_sequential", 2)])
def test_backtest_modes_publish_every_evaluation(workspace, tmp_path, monkeypatch, mode, experiments):
    import pandas as pd
    from alphapilot.research.artifacts import ArtifactService
    from alphapilot.systems.backtest.pipelines.factor_evaluation import FactorEvaluationPipeline
    from alphapilot.systems.backtest.engines.qlib_workflow import QlibWorkflowEngine
    from alphapilot.systems.backtest.engines.qlib_signal import QlibSignalEngine
    from alphapilot.systems.backtest import qlib_config
    from alphapilot.systems.backtest.types import FactorBacktestRequest, FactorDefinition
    from alphapilot.systems.run_workspace import run_workspace
    tasks, _, actor = workspace
    pipeline = FactorEvaluationPipeline()
    counter = []
    def build(*args, **kwargs):
        folder = tmp_path / f"experiment-{len(counter)}"
        folder.mkdir()
        experiment = SimpleNamespace(experiment_workspace=SimpleNamespace(workspace_path=folder), run_env={})
        counter.append(experiment)
        return experiment, object(), True
    def calculate(self, experiment, **kwargs):
        if mode != "single_ic":
            frame = pd.DataFrame({"return": [.01, -.02, .03], "bench": [.001, .002, .003], "cost": [.001, .001, .001],
                                  "turnover": [.1, .2, .1], "account": [101., 99., 102.], "cash": [50., 49., 51.]},
                                 index=pd.date_range("2026-01-05", periods=3, freq="B"))
            frame.to_pickle(experiment.experiment_workspace.workspace_path / "ret.pkl")
        return SimpleNamespace(experiment=experiment, metrics=pd.Series({"IC": .1 * len(counter)}), per_factor=[{"factor_name": "first", "IC": .1}])
    monkeypatch.setattr(pipeline, "_build_experiment", build)
    monkeypatch.setattr(pipeline, "_develop", lambda scenario, experiment: experiment)
    monkeypatch.setattr(QlibWorkflowEngine, "run", calculate)
    monkeypatch.setattr(QlibSignalEngine, "run", calculate)
    monkeypatch.setattr(qlib_config, "resolve_qlib_config_name", lambda _: "fixture.yaml")
    with run_workspace(command="backtest") as parent:
        result = pipeline.run(object(), FactorBacktestRequest(mode=mode, factors=[
            FactorDefinition(factor_name="first", factor_expression="$close"),
            FactorDefinition(factor_name="second", factor_expression="$volume")]))
    assert len(result.experiments) == experiments
    registry = ArtifactService(tasks.store)
    evaluations = [run for run in registry.runs(actor)["items"] if run.get("parent_run_id") == parent.run_id]
    assert len(evaluations) == experiments
    for run in evaluations:
        kinds = {a["kind"] for a in run["artifacts"]}
        assert "evaluation" in kinds
        if mode != "single_ic":
            assert {"backtest_summary", "report", "cumulative"} <= kinds
    if mode == "multi_sequential":
        leaderboard = next(a for a in registry.run(parent.run_id, actor)["artifacts"] if a["kind"] == "factor_portfolio_leaderboard")
        assert [row["factor_name"] for row in registry.table(leaderboard["artifact_id"], actor)["items"]] == ["second", "first"]


def test_autonomous_mining_registers_evaluations_at_the_service_boundary(workspace, monkeypatch):
    from alphapilot.systems.backtest.service import QlibBacktestSystem
    from alphapilot.systems.backtest.runners.factor_runner import QlibFactorRunner
    from alphapilot.systems.backtest import qlib_config
    from alphapilot.systems.backtest.types import FactorExperimentBacktestRequest
    from alphapilot.systems.run_workspace import run_workspace
    from alphapilot.research.artifacts import ArtifactService
    tasks, _, actor = workspace
    experiment = SimpleNamespace(result={"IC": .15})
    monkeypatch.setattr(QlibFactorRunner, "__init__", lambda self, scenario: None)
    monkeypatch.setattr(QlibFactorRunner, "develop", lambda self, value, **kwargs: value)
    monkeypatch.setattr(qlib_config, "resolve_qlib_config_name", lambda _: "fixture.yaml")
    system = QlibBacktestSystem()
    system.context = None
    with run_workspace(command="mine") as parent:
        returned = system.run_factor_experiment(FactorExperimentBacktestRequest(experiment=experiment, use_local=True))
    assert returned is experiment
    runs = ArtifactService(tasks.store).runs(actor)["items"]
    evaluation = next(run for run in runs if run.get("parent_run_id") == parent.run_id)
    assert evaluation["command"] == "factor_evaluation"
    assert any(artifact["kind"] == "evaluation" for artifact in evaluation["artifacts"])
