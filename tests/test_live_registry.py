"""Broker registry: spec lookup, env->setting building, JSON override, adapter wiring."""

from __future__ import annotations

import sys
import types

import pytest

from alphapilot.systems.live.brokers import registry as reg


def test_builtin_brokers_registered() -> None:
    names = [spec.name for spec in reg.list_brokers()]
    assert names == ["emt", "xtp"]
    assert reg.get_broker("XTP").gateway_path == "vnpy_xtp:XtpGateway"
    assert reg.get_broker("emt").gateway_name == "EMT"


def test_unknown_broker_raises() -> None:
    with pytest.raises(ValueError, match="unknown broker"):
        reg.get_broker("nope")


def test_build_connect_setting_from_env() -> None:
    env = {
        "ALPHAPILOT_LIVE_XTP_ACCOUNT": "user1",
        "ALPHAPILOT_LIVE_XTP_PASSWORD": "pw",
        "ALPHAPILOT_LIVE_XTP_CLIENT_ID": "7",
        "ALPHAPILOT_LIVE_XTP_QUOTE_HOST": "119.0.0.1",
        "ALPHAPILOT_LIVE_XTP_QUOTE_PORT": "6002",
        "ALPHAPILOT_LIVE_XTP_TRADE_HOST": "119.0.0.2",
        "ALPHAPILOT_LIVE_XTP_TRADE_PORT": "6001",
        "ALPHAPILOT_LIVE_XTP_SOFTWARE_KEY": "key123",
    }
    setting = reg.build_connect_setting("xtp", env)
    assert setting["账号"] == "user1"
    assert setting["客户号"] == 7                       # cast to int
    assert setting["行情端口"] == 6002
    assert setting["授权码"] == "key123"
    assert setting["行情协议"] == "TCP"                  # default kept
    assert setting["日志级别"] == "INFO"


def test_build_connect_setting_json_override() -> None:
    env = {"ALPHAPILOT_LIVE_EMT_SETTING_JSON": '{"账号": "a", "客户号": 3}'}
    assert reg.build_connect_setting("emt", env) == {"账号": "a", "客户号": 3}
    with pytest.raises(ValueError, match="JSON object"):
        reg.build_connect_setting("emt", {"ALPHAPILOT_LIVE_EMT_SETTING_JSON": "[1]"})


def test_missing_setting_fields() -> None:
    missing = reg.missing_setting_fields("emt", {})
    assert "ALPHAPILOT_LIVE_EMT_ACCOUNT" in missing
    assert "ALPHAPILOT_LIVE_EMT_PASSWORD" in missing
    # ints with non-empty defaults are not "missing"
    assert "ALPHAPILOT_LIVE_EMT_CLIENT_ID" not in missing
    assert reg.missing_setting_fields("emt", {"ALPHAPILOT_LIVE_EMT_SETTING_JSON": "{}"}) == []


def test_resolve_gateway_class_import_error_message() -> None:
    # vn.py gateways are not installed on the dev Mac -> actionable ImportError.
    if reg.gateway_importable("xtp"):
        pytest.skip("vnpy_xtp installed in this env")
    with pytest.raises(ImportError, match="Dockerfile.live"):
        reg.resolve_gateway_class("xtp")


def test_resolve_gateway_class_with_fake_module(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("vnpy_xtp")

    class XtpGateway:  # noqa: D401 - stub
        pass

    fake.XtpGateway = XtpGateway
    monkeypatch.setitem(sys.modules, "vnpy_xtp", fake)
    assert reg.resolve_gateway_class("xtp") is XtpGateway
    assert reg.gateway_importable("xtp")


def test_register_custom_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = reg.BrokerSpec(name="demo", gateway_path="demo_pkg:DemoGateway", gateway_name="DEMO")
    monkeypatch.setitem(reg._BROKERS, "demo", spec)
    assert reg.get_broker("demo").gateway_name == "DEMO"
    setting = reg.build_connect_setting("demo", {"ALPHAPILOT_LIVE_DEMO_ACCOUNT": "x"})
    assert setting["账号"] == "x"


def test_adapter_connect_uses_registry_when_setting_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from alphapilot.systems.live.brokers.vnpy_adapter import VnpyBinding, VnpyBrokerAdapter

    sent = {}

    class FakeMainEngine:
        def connect(self, setting, name):
            sent["setting"] = setting
            sent["name"] = name

    class FakeEventEngine:
        def register(self, *_a):
            pass

    binding = VnpyBinding(
        main_engine=FakeMainEngine(), event_engine=FakeEventEngine(), gateway_name="XTP",
        OrderRequestCls=None, CancelRequestCls=None, SubscribeRequestCls=None,
        Direction=None, Offset=None, OrderType=None, Exchange=None,
        EVENT_ORDER="o", EVENT_TRADE="t", EVENT_POSITION="p",
        EVENT_ACCOUNT="a", EVENT_CONTRACT="c", EVENT_TICK="k",
    )
    adapter = VnpyBrokerAdapter("XTP", binding=binding)
    monkeypatch.setenv("ALPHAPILOT_LIVE_XTP_ACCOUNT", "envuser")
    adapter.connect({})
    assert sent["name"] == "XTP"
    assert sent["setting"]["账号"] == "envuser"          # built from env via registry