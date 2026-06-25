from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from alphapilot.modules.portal import jobs
from alphapilot.modules.portal.api import create_app
from alphapilot.systems.notify import config as notify_config
from alphapilot.systems.notify.commands import authorize, dispatch_text, parse_command
from alphapilot.systems.notify.inbound import InboundMessage


class FakeDataSystem:
    def __init__(self) -> None:
        self.actions: list[tuple[str, dict[str, Any]]] = []

    def list_symbols(self, *_args: Any, **_kwargs: Any) -> dict[str, list[str]]:
        return {"none": ["sh600000"], "backward": ["sh600000"]}

    def get_universe(self, **_options: Any) -> list[str]:
        return ["sh600000", "sz000001"]

    def run_action(self, action: str, **options: Any) -> dict[str, Any]:
        self.actions.append((action, options))
        if action == "bad":
            raise ValueError("bad action")
        return {"action": action, "options": options}

    def delete_symbol(self, symbol: str, **options: Any) -> dict[str, Any]:
        return {"symbol": symbol, "deleted": True, "options": options}

    def refresh_symbol(self, symbol: str, **options: Any) -> dict[str, Any]:
        return {"symbol": symbol, "refreshed": True, "options": options}

    def trim_symbol(self, symbol: str, **options: Any) -> dict[str, Any]:
        return {"symbol": symbol, "trimmed": True, "options": options}

    def apply_adjust_symbol(self, symbol: str, **options: Any) -> dict[str, Any]:
        return {"symbol": symbol, "adjusted": True, "options": options}

    def rebuild_h5(self, **options: Any) -> dict[str, Any]:
        return {"rebuilt": True, "options": options}


@dataclass
class FakeValidation:
    acceptable: bool
    code: str = "ok"
    message: str = "ok"
    details: dict[str, Any] | None = None


class FakeFactorDb:
    supports_categories = True

    def __init__(self) -> None:
        self.categories = ["momentum"]
        self.factors: list[dict[str, Any]] = []

    def list_categories(self) -> list[str]:
        return self.categories

    def create_category(self, name: str) -> bool:
        self.categories.append(name)
        return True

    def add_factors_to_category(self, factor_names: list[str], category: str) -> dict[str, Any]:
        return {"category": category, "requested": factor_names, "changed": factor_names, "unchanged": [], "missing": []}


class FakeFactorSystem:
    def __init__(self) -> None:
        self.database = FakeFactorDb()

    def list_factors(self) -> list[dict[str, Any]]:
        return self.database.factors

    def add_factor(self, factor_name: str, factor_expression: str, categories: list[str] | None = None) -> FakeValidation:
        self.database.factors.append(
            {"factor_name": factor_name, "factor_expression": factor_expression, "categories": categories or []}
        )
        return FakeValidation(True, details={"factor_name": factor_name})

    def validate_expression(self, expression: str) -> FakeValidation:
        return FakeValidation(bool(expression.strip()))

    def delete_factor(self, factor_name: str) -> bool:
        before = len(self.database.factors)
        self.database.factors = [f for f in self.database.factors if f["factor_name"] != factor_name]
        return len(self.database.factors) != before

    def import_factors(self, source: Any, *, kind: str = "csv") -> dict[str, Any]:
        return {"kind": kind, "source": str(source), "imported": 1}

    def create_category(self, name: str) -> bool:
        return self.database.create_category(name)

    def rename_category(self, old_name: str, new_name: str) -> bool:
        self.database.categories = [new_name if item == old_name else item for item in self.database.categories]
        return True

    def delete_category(self, name: str) -> bool:
        self.database.categories = [item for item in self.database.categories if item != name]
        return True

    def add_factors_to_category(self, factor_names: list[str], category: str) -> dict[str, Any]:
        return self.database.add_factors_to_category(factor_names, category)

    def remove_factors_from_category(self, factor_names: list[str], category: str) -> dict[str, Any]:
        return {"category": category, "requested": factor_names, "changed": factor_names, "unchanged": [], "missing": []}

    def set_factor_categories(self, factor_name: str, categories: list[str]) -> bool:
        for row in self.database.factors:
            if row["factor_name"] == factor_name:
                row["categories"] = categories
                return True
        return False

    def factors_in_category(self, name: str) -> list[dict[str, Any]]:
        return [row for row in self.database.factors if name in row.get("categories", [])]

    def export_category_csv(self, name: str, _output_path: Any) -> int:
        return len(self.factors_in_category(name))


class FakeStrategyDb:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def list_strategies(self) -> list[str]:
        return sorted(self.items)

    def save(self, strategy_name: str, params: dict[str, Any]) -> None:
        self.items[strategy_name] = {"strategy_name": strategy_name, **params}

    def load(self, strategy_name: str) -> dict[str, Any] | None:
        return self.items.get(strategy_name)


class FakeStrategySystem:
    def __init__(self) -> None:
        self.param_database = FakeStrategyDb()

    def get_strategy(self, strategy_name: str) -> dict[str, Any] | None:
        return self.param_database.load(strategy_name)

    def import_strategy(self, source: Any, *, kind: str = "pdf") -> dict[str, Any]:
        self.param_database.save("imported", {"source": str(source), "kind": kind})
        return {"strategy_name": "imported", "kind": kind}

    def delete_strategy(self, strategy_name: str) -> bool:
        return self.param_database.items.pop(strategy_name, None) is not None


class FakeBacktestResults:
    def list_runs(self) -> list[dict[str, Any]]:
        return []


class FakeBacktestSystem:
    results = FakeBacktestResults()

    def delete_workspace(self, workspace_id: str) -> bool:
        return workspace_id == "run1"


class FakeConfig:
    class data:
        qlib_data_dir = "qlib"
        raw_data_dir = "raw"

    class factor:
        zoo_dir = "zoo"

    class strategy:
        param_dir = "strategies"

    class backtest:
        workspace_root = "workspaces"

    def summary(self) -> str:
        return "fake"


class FakeEngine:
    def __init__(self) -> None:
        self.config = FakeConfig()
        self.systems = {
            "data": FakeDataSystem(),
            "factor": FakeFactorSystem(),
            "strategy": FakeStrategySystem(),
            "backtest": FakeBacktestSystem(),
        }
        self.modules = {}

    def get_system(self, name: str) -> Any:
        return self.systems[name]


def client(tmp_path: Path, monkeypatch) -> TestClient:  # noqa: ANN001
    monkeypatch.setenv("ALPHAPILOT_PORTAL_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("ALPHAPILOT_PORTAL_SCHEDULE_ROOT", str(tmp_path / "schedules"))
    monkeypatch.setenv("ALPHAPILOT_PORTAL_ENV_PATH", str(tmp_path / "portal-env.json"))
    monkeypatch.setenv("ALPHAPILOT_NOTIFY_CREDENTIALS_PATH", str(tmp_path / "notify.json"))
    monkeypatch.setenv("ALPHAPILOT_NOTIFY_COMMAND_ROOT", str(tmp_path / "notify-commands"))
    return TestClient(create_app(engine=FakeEngine()))


def test_status_and_factor_crud(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)

    status = c.get("/api/status")
    assert status.status_code == 200
    assert status.json()["metrics"]["symbols"] == 1

    created = c.post(
        "/api/factors",
        json={"factor_name": "mom", "factor_expression": "$close", "categories": ["momentum"]},
    )
    assert created.status_code == 200
    assert created.json()["acceptable"] is True

    factors = c.get("/api/factors").json()
    assert factors["factors"][0]["factor_name"] == "mom"
    assert factors["categories"] == ["momentum"]

    deleted = c.delete("/api/factors/mom")
    assert deleted.json()["deleted"] is True


def test_schedule_crud(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)

    created = c.post(
        "/api/schedules",
        json={"name": "download", "kind": "data", "time": "18:00", "kwargs": {"action": "download"}},
    )
    assert created.status_code == 200
    sid = created.json()["schedule_id"]

    patched = c.patch(f"/api/schedules/{sid}", json={"enabled": False})
    assert patched.json()["enabled"] is False

    listed = c.get("/api/schedules")
    assert len(listed.json()) == 1

    deleted = c.delete(f"/api/schedules/{sid}")
    assert deleted.json()["deleted"] is True


def test_portal_env_api_masks_and_saves(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)

    saved = c.patch(
        "/api/portal/env",
        json={"values": {"OPENAI_API_KEY": "secret-key", "CHAT_MODEL": "qwen-plus", "ALPHAPILOT_PICKLE_CACHE_ENABLED": "false"}},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["values"]["OPENAI_API_KEY"] == "********"
    assert body["values"]["CHAT_MODEL"] == "qwen-plus"
    assert body["values"]["ALPHAPILOT_PICKLE_CACHE_ENABLED"] == "false"

    kept = c.patch("/api/portal/env", json={"values": {"OPENAI_API_KEY": "", "CHAT_MODEL": ""}})
    assert kept.status_code == 200
    body = kept.json()
    assert body["values"]["OPENAI_API_KEY"] == "********"
    assert "CHAT_MODEL" not in body["values"]


def test_portal_env_rejects_unknown_key(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)
    response = c.patch("/api/portal/env", json={"values": {"BAD_KEY": "x"}})
    assert response.status_code == 400


def test_portal_env_precedence(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from alphapilot.modules.portal.env_config import apply_portal_env, save_env_values

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALPHAPILOT_PORTAL_ENV_PATH", str(tmp_path / "env.json"))
    (tmp_path / ".env").write_text("CHAT_MODEL=from-dotenv\nOPENAI_BASE_URL=https://dotenv.example\n", encoding="utf-8")
    save_env_values({"CHAT_MODEL": "from-portal", "OPENAI_BASE_URL": "https://portal.example"})

    target = {"CHAT_MODEL": "from-dotenv", "OPENAI_BASE_URL": "https://system.example"}
    applied = apply_portal_env(target)
    assert target["CHAT_MODEL"] == "from-portal"
    assert target["OPENAI_BASE_URL"] == "https://system.example"
    assert applied == {"CHAT_MODEL": "from-portal"}


def test_log_cleanup_api_previews_and_deletes(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)
    log_root = tmp_path / "log"
    empty = log_root / "empty-session"
    keep = log_root / "keep-session"
    empty.mkdir(parents=True)
    keep.mkdir(parents=True)
    (keep / "result.json").write_text("{}", encoding="utf-8")

    preview = c.post("/api/logs/cleanup", json={"log_dir": str(log_root)})

    assert preview.status_code == 200
    assert preview.json()["execute"] is False
    assert preview.json()["removed"] == 1
    assert preview.json()["paths"] == ["empty-session"]
    assert empty.exists()

    deleted = c.post("/api/logs/cleanup", json={"log_dir": str(log_root), "execute": True})

    assert deleted.status_code == 200
    assert deleted.json()["execute"] is True
    assert deleted.json()["removed"] == 1
    assert not empty.exists()
    assert keep.exists()


def test_job_routes_are_json_wrappers(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)

    def fake_start(kind: str, kwargs: dict[str, Any], **_opts: Any) -> dict[str, Any]:
        return {"job_id": "j1", "kind": kind, "status": "running", "params": kwargs}

    monkeypatch.setattr(jobs, "start_job", fake_start)
    monkeypatch.setattr(jobs, "list_jobs", lambda **_opts: [{"job_id": "j1", "kind": "mine", "status": "running"}])
    monkeypatch.setattr(jobs, "read_log_tail", lambda job_id, **_opts: f"log:{job_id}")
    monkeypatch.setattr(jobs, "read_result", lambda job_id, **_opts: {"result": job_id})
    monkeypatch.setattr(jobs, "cancel_job", lambda job_id, **_opts: {"job_id": job_id, "status": "cancelled"})

    started = c.post("/api/jobs", json={"kind": "mine", "kwargs": {"step_n": 1}})
    assert started.json()["job_id"] == "j1"
    assert c.get("/api/jobs").json()[0]["status"] == "running"
    assert c.get("/api/jobs/j1/log").json()["log"] == "log:j1"
    assert c.get("/api/jobs/j1/result").json()["result"] == "j1"
    assert c.post("/api/jobs/j1/cancel").json()["status"] == "cancelled"


def test_notify_command_parse_auth_and_dispatch(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    client(tmp_path, monkeypatch)

    action = parse_command('/run mine {"step_n": 1, "notify": true}')
    assert action.action == "start_job"
    assert action.job_kind == "mine"
    assert action.kwargs == {"step_n": 1, "notify": True}

    data = parse_command("/data action=download source=baostock_cn rebuild_h5=true")
    assert data.job_kind == "data"
    assert data.kwargs == {"action": "download", "source": "baostock_cn", "rebuild_h5": True}

    message = InboundMessage(channel="telegram", text="/jobs", user_id="42", chat_id="100")
    ok, reason = authorize(message)
    assert ok is False
    assert "disabled" in reason

    notify_config.save_notify_config(
        {
            "telegram": {"receive_enabled": True, "allowed_user_ids": ["42"], "allowed_chat_ids": ["100"]},
            "feishu": {},
            "email": {},
            "options": {},
        }
    )
    ok, reason = authorize(message)
    assert ok is True
    assert reason == "allowed"

    started: list[tuple[str, dict[str, Any]]] = []

    def fake_start_job(kind: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        started.append((kind, kwargs))
        return {"job_id": "job1", "kind": kind, "status": "running", "result_summary": None}

    monkeypatch.setattr(jobs, "start_job", fake_start_job)
    result = dispatch_text('/run mine {"step_n": 1}', enforce_auth=False)
    assert result["ok"] is True
    assert started == [("mine", {"step_n": 1})]
    assert "job1" in result["reply"]


def test_notify_natural_language_confirm_and_api_masking(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)
    started: list[tuple[str, dict[str, Any]]] = []

    class FakeLLM:
        def chat_completion(self, *_args: Any, **_kwargs: Any) -> str:
            return '{"action":"start_job","job_kind":"factor_backtest","kwargs":{"factor_names":["mom"]},"summary":"run backtest","risk_level":"medium","requires_confirmation":true}'

    monkeypatch.setattr(
        jobs,
        "start_job",
        lambda kind, kwargs: started.append((kind, kwargs)) or {"job_id": "job2", "kind": kind, "status": "running"},
    )

    planned = dispatch_text("帮我回测 mom 因子", user_id="u1", chat_id="c1", llm_factory=lambda: FakeLLM())
    assert planned["ok"] is True
    assert "/confirm" in planned["reply"]
    confirm_id = planned["data"]["pending"]["id"]

    confirmed = dispatch_text(f"/confirm {confirm_id}", user_id="u1", chat_id="c1")
    assert confirmed["ok"] is True
    assert started == [("factor_backtest", {"factor_names": ["mom"]})]

    notify_config.save_notify_config(
        {
            "telegram": {"enabled": True, "bot_token": "secret-token", "chat_id": "100"},
            "feishu": {"secret": "feishu-secret"},
            "email": {},
            "options": {},
        }
    )
    body = c.get("/api/notify").json()
    assert body["config"]["telegram"]["bot_token"] == notify_config.MASKED_SECRET
    assert body["config"]["feishu"]["secret"] == notify_config.MASKED_SECRET

    body["config"]["telegram"]["chat_id"] = "200"
    saved = c.patch("/api/notify", json={"config": body["config"]})
    assert saved.status_code == 200
    private = notify_config.load_file_config()
    assert private["telegram"]["bot_token"] == "secret-token"
    assert private["telegram"]["chat_id"] == "200"

    response = c.post("/api/notify/commands/dispatch", json={"text": "/jobs"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_data_action_error_response(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)

    ok = c.post("/api/data/actions", json={"action": "download", "options": {"start_date": "2020-01-01"}})
    assert ok.status_code == 200
    assert ok.json()["action"] == "download"

    bad = c.post("/api/data/actions", json={"action": "bad", "options": {}})
    assert bad.status_code == 400
    assert "bad action" in bad.json()["detail"]


def test_data_management_routes(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)

    universe = c.get("/api/data/universe")
    assert universe.status_code == 200
    assert universe.json()["count"] == 2

    symbols = c.get("/api/data/symbols")
    assert symbols.json()["backward"] == ["sh600000"]

    refreshed = c.post("/api/data/symbols/refresh", json={"symbol": "sh600000", "options": {"start_date": "2024-01-01"}})
    assert refreshed.json()["refreshed"] is True

    assert c.post("/api/data/h5/rebuild", json={"market": "cn"}).json()["rebuilt"] is True


def test_factor_category_and_backtest_routes(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)
    c.post("/api/factors", json={"factor_name": "mom", "factor_expression": "$close", "categories": ["momentum"]})

    created = c.post("/api/factors/categories", json={"name": "quality"})
    assert created.json()["created"] is True

    bulk = c.post("/api/factors/categories/bulk?op=add", json={"factor_names": ["mom"], "category": "quality"})
    assert bulk.json()["category"] == "quality"

    def fake_start(kind: str, kwargs: dict[str, Any], **_opts: Any) -> dict[str, Any]:
        assert kind == "factor_backtest"
        assert Path(str(kwargs["factor_path"])).exists()
        return {"job_id": "bt1", "kind": kind, "status": "running", "params": kwargs}

    monkeypatch.setattr(jobs, "start_job", fake_start)
    started = c.post("/api/factors/backtest", json={"factor_names": ["mom"], "options": {"scenario": "factor_backtest"}})
    assert started.json()["job_id"] == "bt1"


def test_strategy_import_export_routes(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    c = client(tmp_path, monkeypatch)
    c.post("/api/strategies", json={"strategy_name": "s1", "params": {"a": 1}})

    out = tmp_path / "strategy.json"
    exported = c.post("/api/strategies/export", json={"strategy_name": "s1", "output_path": str(out)})
    assert exported.json()["saved"] is True
    assert out.exists()

    imported = c.post("/api/strategies/import", json={"kind": "pdf", "source": "paper.pdf"})
    assert imported.json()["strategy_name"] == "imported"
