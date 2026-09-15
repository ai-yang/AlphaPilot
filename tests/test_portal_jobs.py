"""Trusted Python facade delegates to the same persistent queue as v1 HTTP.

State-machine/recovery coverage lives in test_research_runtime.py; the old
request-owned process launcher and JSON-file state authority were removed.
"""
from __future__ import annotations

import pytest

from alphapilot.modules.portal import jobs
from alphapilot.research.auth import Actor
from alphapilot.research.common import ResearchError
from alphapilot.research.store import Store
from alphapilot.research.tasks import TaskService


@pytest.fixture
def facade(isolated_env, monkeypatch):
    from alphapilot.research import executor
    tasks = TaskService(Store(), object(), autostart=False)
    monkeypatch.setattr(jobs, "_service", lambda *_: tasks)
    monkeypatch.setattr(executor, "prepare", lambda engine, store, spec, folder, actor: (
        {"kind": spec.kind, "input": spec.input.model_dump(mode="json"), "resources": [], "folder": str(folder)}, spec.input.model_dump(mode="json")))
    return tasks


def test_facade_admits_queued_idempotent_tasks_without_launching_request_processes(facade):
    payload = {"input": {"dataset_id": "fixture", "max_steps": 1}}
    first = jobs.start_job("mine", payload, idempotency_key="intent")
    second = jobs.start_job("mine", payload, idempotency_key="intent")
    assert first["status"] == "queued"
    assert first["job_id"] == second["job_id"]
    assert jobs.list_jobs() == facade.list(Actor.local())["items"]
    assert jobs.read_progress(first["job_id"])["stage"] == "queued"
    assert jobs.read_result(first["job_id"])["availability"] == "pending"
    assert jobs.cancel_job(first["job_id"])["status"] == "cancelled"
    assert jobs.clear_finished_jobs() == 1
    assert jobs.list_jobs() == []
    with pytest.raises(ResearchError, match="deleted"):
        jobs.start_job("mine", payload, idempotency_key="intent")


def test_removed_process_factory_is_rejected(facade):
    with pytest.raises(ValueError, match="TaskRuntime"):
        jobs.start_job("mine", {}, process_factory=object())


@pytest.mark.parametrize("job_id", ["..", "../secret", "/tmp/secret", "a\\b"])
def test_facade_rejects_path_traversal(facade, job_id):
    for read in (jobs.get_job, jobs.read_log_tail, jobs.read_result, jobs.cancel_job):
        with pytest.raises(ResearchError):
            read(job_id)


def test_unknown_kwargs_and_unbounded_mining_are_not_accepted(facade):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        jobs.start_job("mine", {"input": {"dataset_id": "fixture"}})
    with pytest.raises(ValidationError):
        jobs.start_job("mine", {"input": {"dataset_id": "fixture", "max_steps": 1, "api_key": "never-persist"}})
    assert jobs.list_jobs() == []
