"""Fail-closed VWAP and provider-binding contracts for AlphaForge."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

import alphapilot.modules.alphaforge  # noqa: F401 - installs vendored paths
from alphapilot.modules.alphaforge.data_adapter import (
    LoadedTrainingData,
    TargetSpec,
    TrainingSpec,
    VwapSpec,
    build_stock_data,
)


def _provider(
    root: Path,
    *,
    symbols: tuple[str, ...] = ("SH600000", "SZ000001"),
    factor_symbols: tuple[str, ...] = (),
) -> Path:
    (root / "instruments").mkdir(parents=True)
    (root / "features").mkdir()
    (root / "instruments" / "test_market.txt").write_text(
        "".join(f"{symbol}\t2020-01-01\t2024-12-31\n" for symbol in symbols),
        encoding="utf-8",
    )
    normalized_factor_symbols = {symbol.lower() for symbol in factor_symbols}
    for symbol in symbols:
        feature_dir = root / "features" / symbol.lower()
        feature_dir.mkdir()
        if symbol.lower() in normalized_factor_symbols:
            (feature_dir / "factor.day.bin").write_bytes(b"factor")
    return root


def _capture_stock_data(monkeypatch):  # noqa: ANN001, ANN202
    from alphagen_qlib import stock_data as vendor

    calls: list[dict] = []

    def fake_stock_data(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(vendor, "StockData", fake_stock_data)
    return calls


def _build(provider, monkeypatch, **overrides):  # noqa: ANN001, ANN003, ANN202
    calls = _capture_stock_data(monkeypatch)
    kwargs = {
        "qlib_dir": provider,
        "instruments": "test_market",
        "start_time": "2020-01-01",
        "end_time": "2023-12-31",
        "device": "cpu",
    }
    kwargs.update(overrides)
    result = build_stock_data(**kwargs)
    return result, calls


def test_vwap_spec_is_immutable_normalized_and_has_one_explicit_factor() -> None:
    default = VwapSpec()
    adjusted = VwapSpec(" FACTOR_ADJUSTED_AMOUNT_VOLUME ")

    assert default.mode == "amount_volume"
    assert default.qlib_expression == "($amount/$volume)"
    assert default.requires_factor is False
    assert adjusted.mode == "factor_adjusted_amount_volume"
    assert adjusted.qlib_expression == "(($amount/$volume)*$factor)"
    assert adjusted.qlib_expression.count("$factor") == 1
    with pytest.raises(AttributeError):
        adjusted.mode = "amount_volume"  # type: ignore[misc]
    with pytest.raises(ValueError, match="vwap_mode"):
        VwapSpec("auto")


def test_factor_adjusted_vwap_requires_complete_market_coverage(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    complete = _provider(
        tmp_path / "complete",
        factor_symbols=("SH600000", "SZ000001"),
    )
    result, calls = _build(
        complete,
        monkeypatch,
        vwap_spec=VwapSpec("factor_adjusted_amount_volume"),
    )

    assert len(calls) == 1
    assert result.vwap_expression == "(($amount/$volume)*$factor)"
    assert result.vwap_expression.count("$factor") == 1


def test_market_file_lookup_accepts_normalized_market_name(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    provider = _provider(
        tmp_path / "provider",
        factor_symbols=("SH600000", "SZ000001"),
    )
    result, calls = _build(
        provider,
        monkeypatch,
        instruments="TEST_MARKET",
        vwap_spec="factor_adjusted_amount_volume",
    )

    assert len(calls) == 1
    assert result.instrument == "TEST_MARKET"


@pytest.mark.parametrize(
    "factor_symbols",
    [(), ("SH600000",)],
    ids=["missing", "partial"],
)
def test_missing_or_partial_factor_coverage_fails_before_stock_data(
    tmp_path: Path, monkeypatch, factor_symbols: tuple[str, ...]
) -> None:  # noqa: ANN001
    provider = _provider(tmp_path / "provider", factor_symbols=factor_symbols)
    calls = _capture_stock_data(monkeypatch)

    with pytest.raises(ValueError, match="full \\$factor coverage") as exc:
        build_stock_data(
            qlib_dir=provider,
            instruments="test_market",
            start_time="2020-01-01",
            end_time="2023-12-31",
            device="cpu",
            vwap_spec=VwapSpec("factor_adjusted_amount_volume"),
        )

    assert calls == []
    if factor_symbols:
        assert "sz000001" in str(exc.value)


def test_raw_true_is_fail_closed_and_never_downgrades(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    missing = _provider(tmp_path / "missing")
    calls = _capture_stock_data(monkeypatch)
    with pytest.raises(ValueError, match="full \\$factor coverage"):
        build_stock_data(
            qlib_dir=missing,
            instruments="test_market",
            start_time="2020-01-01",
            end_time="2023-12-31",
            device="cpu",
            raw=True,
        )
    assert calls == []

    complete = _provider(
        tmp_path / "complete",
        factor_symbols=("SH600000", "SZ000001"),
    )
    result, complete_calls = _build(complete, monkeypatch, raw=True)
    assert len(complete_calls) == 1
    assert result.raw is True
    # Raw OHLCV adjustment does not implicitly change the explicit VWAP mode.
    assert result.vwap_expression == "($amount/$volume)"


def test_empty_factor_feature_is_not_treated_as_full_coverage(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    provider = _provider(
        tmp_path / "provider",
        factor_symbols=("SH600000", "SZ000001"),
    )
    (provider / "features" / "sz000001" / "factor.day.bin").write_bytes(b"")
    calls = _capture_stock_data(monkeypatch)

    with pytest.raises(ValueError, match="full \\$factor coverage"):
        build_stock_data(
            qlib_dir=provider,
            instruments="test_market",
            start_time="2020-01-01",
            end_time="2023-12-31",
            device="cpu",
            vwap_spec="factor_adjusted_amount_volume",
        )
    assert calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"raw": True},
        {"vwap_spec": VwapSpec("factor_adjusted_amount_volume")},
    ],
)
def test_factor_dependent_modes_reject_non_file_providers(
    monkeypatch, overrides: dict
) -> None:  # noqa: ANN001
    calls = _capture_stock_data(monkeypatch)
    with pytest.raises(ValueError, match="local filesystem Qlib provider"):
        build_stock_data(
            qlib_dir={"day": "memory://provider"},
            instruments="test_market",
            start_time="2020-01-01",
            end_time="2023-12-31",
            device="cpu",
            **overrides,
        )
    assert calls == []


def test_default_unadjusted_vwap_keeps_non_file_provider_compatibility(
    monkeypatch,
) -> None:  # noqa: ANN001
    result, calls = _build(
        {"day": "memory://provider"},
        monkeypatch,
        vwap_spec="amount_volume",
    )

    assert len(calls) == 1
    assert result.qlib_path == {"day": "memory://provider"}
    assert result.vwap_expression == "($amount/$volume)"


@pytest.mark.parametrize(
    "overrides",
    [
        {"raw": True},
        {"vwap_spec": VwapSpec("factor_adjusted_amount_volume")},
    ],
)
def test_factor_dependent_minute_modes_are_rejected(
    tmp_path: Path, monkeypatch, overrides: dict
) -> None:  # noqa: ANN001
    provider = _provider(
        tmp_path / "provider",
        factor_symbols=("SH600000", "SZ000001"),
    )
    calls = _capture_stock_data(monkeypatch)
    with pytest.raises(ValueError, match="only for day frequency"):
        build_stock_data(
            qlib_dir=provider,
            instruments="test_market",
            start_time="2020-01-01",
            end_time="2023-12-31",
            device="cpu",
            freq="min",
            **overrides,
        )
    assert calls == []


def test_vendor_uses_resolved_vwap_without_raw_double_adjustment() -> None:
    from alphagen_qlib.stock_data import FeatureType, StockData

    captured: list[str] = []
    stock = StockData.__new__(StockData)
    stock._features = list(FeatureType)
    stock.raw = True
    stock.vwap_expression = "(($amount/$volume)*$factor)"

    class CapturedExpressions(RuntimeError):
        pass

    def capture(expressions):  # noqa: ANN001, ANN202
        captured.extend(expressions)
        raise CapturedExpressions

    stock._load_exprs = capture
    with pytest.raises(CapturedExpressions):
        stock._get_data()

    assert captured == [
        "$open*$factor",
        "$close*$factor",
        "$high*$factor",
        "$low*$factor",
        "$volume/$factor/1000000",
        "(($amount/$volume)*$factor)",
    ]
    assert captured[-1].count("$factor") == 1


def test_stock_data_reinitializes_qlib_only_when_provider_identity_changes(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    import qlib
    from alphagen_qlib.stock_data import StockData

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    calls: list[object] = []

    def fake_init(*, provider_uri, region):  # noqa: ANN001, ANN202
        assert region
        calls.append(provider_uri)

    monkeypatch.setattr(qlib, "init", fake_init)
    monkeypatch.setattr(StockData, "_qlib_provider_identity", None)

    StockData._init_qlib(first)
    StockData._init_qlib(str(first))
    StockData._init_qlib(second)
    StockData._init_qlib({"day": "memory://provider"})
    StockData._init_qlib({"day": "memory://provider"})

    assert calls == [first, second, {"day": "memory://provider"}]


def test_vwap_mode_is_an_explicit_public_parameter_for_every_miner() -> None:
    from alphapilot.modules.alphaforge_aff.miner import AFFMiner
    from alphapilot.modules.alphaforge_aff.module import AlphaForgeAFFModule
    from alphapilot.modules.alphaforge_search.module import AlphaForgeSearchModule
    from alphapilot.modules.alphaforge_search.runners.gp_runner import GPRunner
    from alphapilot.modules.alphaforge_search.runners.rl_runner import RLRunner

    callables = (
        GPRunner,
        RLRunner,
        AFFMiner,
        AlphaForgeSearchModule.mine_gp,
        AlphaForgeSearchModule.mine_rl,
        AlphaForgeAFFModule.mine_aff,
    )
    for callable_ in callables:
        parameter = inspect.signature(callable_).parameters["vwap_mode"]
        assert parameter.default == "amount_volume"

    for runner_class in (GPRunner, RLRunner, AFFMiner):
        runner = runner_class(
            context=SimpleNamespace(),
            vwap_mode=" FACTOR_ADJUSTED_AMOUNT_VOLUME ",
        )
        assert runner.vwap_spec == VwapSpec("factor_adjusted_amount_volume")


def test_loaded_training_data_keeps_legacy_positional_construction() -> None:
    training = TrainingSpec("2020-01-01", "2020-12-31", "explicit_dates")
    target = TargetSpec(5, "close")

    loaded = LoadedTrainingData(
        object(),
        training,
        target,
        "2020-01-02",
        "2020-12-30",
    )

    assert loaded.vwap_spec == VwapSpec("amount_volume")
