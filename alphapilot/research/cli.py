"""Local owner administration; these commands are never exposed as MCP tools."""
from __future__ import annotations

from .auth import AuthService
from .common import ResearchError
from .store import Store


def research_token(action: str = "list", client_id: str | None = None, scopes=None,
                   credential_id: str | None = None, expires: str | None = None):
    service = AuthService(Store())
    if action == "list":
        return service.list()
    if action == "create":
        selected = scopes.split(",") if isinstance(scopes, str) else scopes or ["research:read"]
        return service.create(client_id or "", selected, expires)
    if action == "revoke":
        service.revoke(credential_id or "")
        return {"revoked": credential_id}
    raise ResearchError("INVALID_ACTION", "Expected create, list or revoke", 422)


def task_runtime(action: str = "status"):
    from .runtime import ensure_running, status
    store = Store()
    if action == "start":
        store.set_setting("drain", False)
        return ensure_running(store)
    if action == "stop":
        store.set_setting("drain", True)
        return {**status(store), "draining": True}
    if action == "status":
        return status(store)
    raise ResearchError("INVALID_ACTION", "Expected start, stop (drain) or status", 422)
