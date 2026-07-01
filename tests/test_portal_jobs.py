from __future__ import annotations

from typing import Any

import alphapilot.kernel

from alphapilot.modules.portal import jobs


class FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.started = False

    def start(self) -> None:
        self.started = True


def test_start_job_persists_unique_directories(tmp_path):
    pids = iter([1111, 2222])

    def factory(_target, _args):
        return FakeProcess(next(pids))

    first = jobs.start_job(
        "mine",
        {"step_n": 1, "scenario": "alpha_factor_mining"},
        job_root=tmp_path,
        process_factory=factory,
    )
    second = jobs.start_job(
        "factor_backtest",
        {"factor_path": "factor.csv"},
        job_root=tmp_path,
        process_factory=factory,
    )

    assert first["job_id"] != second["job_id"]
    assert first["status"] == "running"
    assert second["status"] == "running"
    assert (tmp_path / first["job_id"] / "job.json").exists()
    assert (tmp_path / first["job_id"] / "run.log").exists()
    assert (tmp_path / second["job_id"] / "job.json").exists()

    listed = jobs.list_jobs(job_root=tmp_path, refresh=False)
    assert {job["job_id"] for job in listed} == {first["job_id"], second["job_id"]}


def test_timing_backtest_job_kind_dispatches_to_timing_module(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeTimingModule:
        def timing_backtest(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"strategy": kwargs["strategy_name"], "artifact_dir": "/tmp/timing"}

    class FakeEngine:
        def get_module(self, name: str) -> Any:
            assert name == "timing"
            return FakeTimingModule()

    monkeypatch.setattr(alphapilot.kernel, "build_engine", lambda discover=True: FakeEngine())

    result = jobs._run_target("timing_backtest", {"strategy_name": "dual_ma", "symbols": ["000001"]})

    assert "timing_backtest" in jobs.VALID_KINDS
    assert result["strategy"] == "dual_ma"
    assert calls == [{"strategy_name": "dual_ma", "symbols": ["000001"]}]


def test_running_job_without_process_is_marked_lost(tmp_path, monkeypatch):
    def factory(_target, _args):
        return FakeProcess(3333)

    job = jobs.start_job(
        "mine",
        {"step_n": 1},
        job_root=tmp_path,
        process_factory=factory,
    )
    monkeypatch.setattr(jobs, "_pid_exists", lambda _pid: False)

    refreshed = jobs.get_job(job["job_id"], job_root=tmp_path)

    assert refreshed["status"] == "lost"
    assert "Worker process is no longer running" in refreshed["error"]


def test_cancel_job_records_cancelled_status(tmp_path, monkeypatch):
    killed: list[tuple[int, int]] = []

    def factory(_target, _args):
        return FakeProcess(4444)

    job = jobs.start_job(
        "strategy_backtest",
        {"strategy_name": "demo", "mode": "both"},
        job_root=tmp_path,
        process_factory=factory,
    )
    monkeypatch.setattr(jobs, "_pid_exists", lambda _pid: True)
    monkeypatch.setattr(jobs.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(jobs.time, "sleep", lambda _seconds: None)

    cancelled = jobs.cancel_job(job["job_id"], job_root=tmp_path)

    assert cancelled["status"] == "cancelled"
    assert cancelled["returncode"] < 0
    assert killed


def test_read_progress_infers_tqdm_percentage(tmp_path, monkeypatch):
    def factory(_target, _args):
        return FakeProcess(5555)

    job = jobs.start_job("data", {"action": "download"}, job_root=tmp_path, process_factory=factory)
    monkeypatch.setattr(jobs, "_pid_exists", lambda _pid: True)
    (tmp_path / job["job_id"] / "run.log").write_text("下载进度:  42%|####      | 42/100\n", encoding="utf-8")

    progress = jobs.read_progress(job["job_id"], job_root=tmp_path)

    assert progress["status"] == "running"
    assert progress["percent"] == 42
    assert "42%" in progress["message"]


def test_read_progress_preserves_structured_fields(tmp_path, monkeypatch):
    def factory(_target, _args):
        return FakeProcess(6666)

    job = jobs.start_job("data", {"action": "download"}, job_root=tmp_path, process_factory=factory)
    monkeypatch.setattr(jobs, "_pid_exists", lambda _pid: True)
    monkeypatch.setenv("ALPHAPILOT_PORTAL_JOB_DIR", str(tmp_path / job["job_id"]))

    jobs.update_current_job_progress(
        12,
        "download:baostock",
        "下载仍在进行 1/10，等待 9 个任务返回",
        completed=1,
        total=10,
        pending=9,
        current_symbol="sh600000",
    )
    progress = jobs.read_progress(job["job_id"], job_root=tmp_path)

    assert progress["percent"] == 12
    assert progress["completed"] == 1
    assert progress["total"] == 10
    assert progress["pending"] == 9
    assert progress["current_symbol"] == "sh600000"


def test_data_job_progress_can_be_computed_from_raw_csv_files(tmp_path, monkeypatch):
    def factory(_target, _args):
        return FakeProcess(7777)

    stock_csv = tmp_path / "stocks.csv"
    stock_csv.write_text("code\nsh.600000\nsz.000001\nsh.600001\n", encoding="utf-8")
    raw_dir = tmp_path / "raw_none"
    raw_dir.mkdir()
    (raw_dir / "sh600000.csv").write_text("date,code,close\n2026-06-18,sh600000,10\n", encoding="utf-8")
    (raw_dir / "sz000001.csv").write_text("date,code,close\n2026-06-17,sz000001,9\n", encoding="utf-8")

    job = jobs.start_job(
        "data",
        {
            "action": "download",
            "source": "baostock_cn",
            "start_date": "2026-06-01",
            "end_date": "2026-06-18",
            "stock_csv": str(stock_csv),
            "adjust_mode": "none",
            "data_dir": str(raw_dir),
        },
        job_root=tmp_path / "jobs",
        process_factory=factory,
    )
    monkeypatch.setattr(jobs, "_pid_exists", lambda _pid: True)

    progress = jobs.read_progress(job["job_id"], job_root=tmp_path / "jobs")

    assert progress["progress_source"] == "disk"
    assert progress["completed"] == 1
    assert progress["total"] == 3
    assert progress["pending"] == 2
    assert progress["latest_data_date"] == "2026-06-18"
