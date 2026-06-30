#!/usr/bin/env python3
"""Unit tests for the content-addressed factor h5 cache (systems/data/factor_h5.py).

Runs without qlib / HDF5: the qlib-backed generator and the ``pd.read_hdf`` validation are
stubbed so we can exercise the spec hashing, atomic cache build, manifest layout, reuse, env
publishing, resolve precedence, cleanup, and the ``$return`` per-instrument fix.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_GEN_CALLS = {"n": 0}


def _install_stubs() -> None:
    """Stub the qlib generator (sys.modules) and pandas.read_hdf validation."""
    fake = types.ModuleType("alphapilot.systems.data.generate_h5")

    def _fake_generate(*, qlib_dir, output_dir, market, fields, start_date, debug_stock_count, freq="day"):
        _GEN_CALLS["n"] += 1
        _GEN_CALLS["freq"] = freq
        out = Path(output_dir)
        (out / "daily_pv_all.h5").write_text(f"ALL:{market}")
        (out / "daily_pv_debug.h5").write_text(f"DEBUG:{market}:{debug_stock_count}")

    fake.generate_daily_pv_h5 = _fake_generate
    sys.modules["alphapilot.systems.data.generate_h5"] = fake

    import pandas as pd

    pd.read_hdf = lambda *a, **k: None  # HDF5 unavailable in CI; treat the file as valid


class FactorH5CacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_stubs()

    def setUp(self) -> None:
        import alphapilot.systems.data.factor_h5 as fh

        self.fh = fh
        self.tmp = Path(tempfile.mkdtemp(prefix="factor_h5_test_"))
        self.cache_root = self.tmp / "cache"
        fh.factor_h5_cache_root = lambda: self.cache_root  # noqa: redirect cache root

        self.qdir = self.tmp / "qlib"
        (self.qdir / "instruments").mkdir(parents=True)
        (self.qdir / "instruments" / "mktA.txt").write_text("SH600000\ta\tb\n")
        (self.qdir / "instruments" / "mktB.txt").write_text("SZ000001\ta\tb\n")
        _GEN_CALLS["n"] = 0
        for k in (fh.ENV_DATA_DIR, fh.ENV_DATA_DEBUG_DIR, fh.ENV_FINGERPRINT, fh.ENV_MARKET):
            os.environ.pop(k, None)

    def _spec(self, market: str = "mktA"):
        return self.fh.FactorDataSpec(qlib_dir=self.qdir, market=market)

    def test_spec_hash_deterministic_and_sensitive(self) -> None:
        self.assertEqual(self._spec("mktA").fingerprint(), self._spec("mktA").fingerprint())
        self.assertNotEqual(self._spec("mktA").fingerprint(), self._spec("mktB").fingerprint())

    def test_cache_layout_and_manifest_placement(self) -> None:
        cdir = self.fh.build_or_get_cache(self._spec(), use_local=True)
        self.assertTrue((cdir / "all" / "daily_pv.h5").exists())
        self.assertTrue((cdir / "debug" / "daily_pv.h5").exists())
        self.assertTrue((cdir / "all" / "README.md").exists())
        self.assertTrue((cdir / "manifest.json").exists())
        self.assertTrue((cdir / ".complete").exists())
        # manifest/.complete must never live inside all/ or debug/ (get_file_desc only knows
        # .h5/.md and would raise NotImplementedError on json).
        self.assertFalse((cdir / "debug" / "manifest.json").exists())
        self.assertFalse(any(p.suffix == ".json" for p in (cdir / "debug").iterdir()))
        self.assertFalse(any(p.suffix == ".json" for p in (cdir / "all").iterdir()))

    def test_manifest_content(self) -> None:
        spec = self._spec()
        cdir = self.fh.build_or_get_cache(spec, use_local=True)
        mani = json.loads((cdir / "manifest.json").read_text())
        self.assertEqual(mani["spec_hash"], spec.fingerprint())
        self.assertEqual(mani["market"], "mktA")
        self.assertEqual(mani["generator_version"], self.fh.GENERATOR_VERSION)
        self.assertIn("instruments_hash", mani)
        self.assertIn("daily_pv_size", mani)

    def test_cache_hit_does_not_rebuild(self) -> None:
        spec = self._spec()
        self.fh.build_or_get_cache(spec, use_local=True)
        n_after_first = _GEN_CALLS["n"]
        self.fh.build_or_get_cache(spec, use_local=True)
        self.assertEqual(_GEN_CALLS["n"], n_after_first, "second call must not regenerate")
        self.assertTrue(self.fh._is_complete(self.cache_root / spec.fingerprint(), spec.fingerprint()))

    def test_load_context_from_cache_dir(self) -> None:
        spec = self._spec()
        cdir = self.fh.build_or_get_cache(spec, use_local=True)
        ctx = self.fh.load_context_from_cache_dir(cdir)
        self.assertEqual(ctx.fingerprint, spec.fingerprint())
        self.assertEqual(ctx.spec.market, "mktA")
        self.assertEqual(ctx.data_dir, (cdir / "all").resolve())
        self.assertEqual(ctx.debug_dir, (cdir / "debug").resolve())

    def test_prepare_or_reuse_context(self) -> None:
        built = self.fh.prepare_factor_data_context(market="mktA", qlib_dir=self.qdir)
        reused = self.fh.prepare_or_reuse_context(factor_data_dir=built.cache_dir)
        self.assertEqual(reused.fingerprint, built.fingerprint)
        other = self.fh.prepare_or_reuse_context(market="mktB", qlib_dir=self.qdir)
        self.assertEqual(other.spec.market, "mktB")
        self.assertNotEqual(other.fingerprint, built.fingerprint)

    def test_env_publish_and_resolve_precedence(self) -> None:
        from alphapilot.components.coder.factor_coder.data import (
            resolve_factor_data_dir,
            resolve_factor_data_fingerprint,
        )

        ctx = self.fh.prepare_factor_data_context(market="mktA", qlib_dir=self.qdir)
        self.fh.apply_context_env(ctx)
        self.assertEqual(os.environ[self.fh.ENV_DATA_DIR], str(ctx.data_dir))
        self.assertEqual(os.environ[self.fh.ENV_FINGERPRINT], ctx.fingerprint)

        ws = types.SimpleNamespace()  # no attached context -> resolves via env
        self.assertEqual(str(resolve_factor_data_dir(ws, "All")), str(ctx.data_dir))
        self.assertEqual(str(resolve_factor_data_dir(ws, "Debug")), str(ctx.debug_dir))
        self.assertEqual(resolve_factor_data_fingerprint(ws), ctx.fingerprint)

        # An attached workspace context wins over env.
        ws.factor_data_context = types.SimpleNamespace(
            data_dir="/x/all", debug_dir="/x/debug", fingerprint="WSWINS"
        )
        self.assertEqual(resolve_factor_data_fingerprint(ws), "WSWINS")
        self.assertEqual(str(resolve_factor_data_dir(ws, "All")), "/x/all")

    def test_clean_factor_h5_cache(self) -> None:
        a = self.fh.prepare_factor_data_context(market="mktA", qlib_dir=self.qdir)
        self.fh.prepare_factor_data_context(market="mktB", qlib_dir=self.qdir)
        # Remove only mktA
        removed = self.fh.clean_factor_h5_cache(market="mktA")
        self.assertEqual(removed, 1)
        self.assertFalse(a.cache_dir.exists())
        # Remove the rest
        self.assertEqual(self.fh.clean_factor_h5_cache(), 1)


class ReturnComputationTests(unittest.TestCase):
    """The $return fix: per-instrument pct_change, and debug sliced from the full frame."""

    def test_return_is_per_instrument_and_debug_slice(self) -> None:
        import numpy as np
        import pandas as pd

        dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])
        idx = pd.MultiIndex.from_product([dates, ["AAA", "BBB"]], names=["datetime", "instrument"])
        closes = {"AAA": [10, 11, 22], "BBB": [100, 90, 99]}
        data = pd.DataFrame(index=idx)
        data["$close"] = [closes[i][list(dates).index(d)] for d, i in idx]

        data["$return"] = data.groupby(level="instrument")["$close"].pct_change().fillna(0)

        self.assertTrue(np.allclose(data.xs("AAA", level="instrument")["$return"], [0.0, 0.1, 1.0]))
        self.assertTrue(np.allclose(data.xs("BBB", level="instrument")["$return"], [0.0, -0.1, 0.1]))

        debug_instruments = data.index.get_level_values("instrument").unique()[:1]
        debug = data.loc[pd.IndexSlice[:, debug_instruments], :].sort_index()
        self.assertEqual(list(debug.index.get_level_values("instrument").unique()), ["AAA"])
        self.assertEqual(list(debug.index.names), ["datetime", "instrument"])
        self.assertTrue(np.allclose(debug["$return"], [0.0, 0.1, 1.0]))


if __name__ == "__main__":
    unittest.main()
