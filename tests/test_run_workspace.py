#!/usr/bin/env python3
"""Unit tests for the per-task run workspace (systems/run_workspace.py).

Runs without qlib: exercises run-dir naming/layout, workspace-root relocation (contextvar + env),
factor-data symlink + manifest, list/delete, and restore-on-exception.
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


class RunWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        import alphapilot.systems.run_workspace as rw
        import alphapilot.core.workspace as cw

        self.rw = rw
        self.cw = cw
        self.tmp = Path(tempfile.mkdtemp(prefix="run_ws_test_"))
        self.runs = self.tmp / "runs"
        rw.runs_root = lambda: self.runs  # redirect runs root
        os.environ.pop(rw.WORKSPACE_ROOT_ENV, None)
        self.default_root = cw.resolve_workspace_root()

    def test_layout_relocation_and_restore(self) -> None:
        from alphapilot.core.experiment import FBWorkspace

        with self.rw.run_workspace(command="mine", market="csi500") as run:
            self.assertRegex(run.run_id, r"^\d{8}-\d{6}__mine__csi500__[0-9a-f]{6}$")
            self.assertTrue(run.workspaces_dir.is_dir())
            # workspace root is relocated (contextvar + env) for the duration of the run
            self.assertEqual(self.cw.resolve_workspace_root(), run.workspaces_dir)
            self.assertEqual(os.environ[self.rw.WORKSPACE_ROOT_ENV], str(run.workspaces_dir))
            # a workspace created now lands under runs/<id>/workspaces/
            ws = FBWorkspace()
            self.assertEqual(ws.workspace_path.parent, run.workspaces_dir)
            # initial manifest
            manifest = json.loads(run.manifest_path.read_text())
            self.assertEqual(manifest["command"], "mine")
            self.assertEqual(manifest["market"], "csi500")
            self.assertEqual(manifest["status"], "running")

        # restored after exit
        self.assertEqual(self.cw.resolve_workspace_root(), self.default_root)
        self.assertNotIn(self.rw.WORKSPACE_ROOT_ENV, os.environ)
        self.assertIsNone(self.rw.current_run())
        manifest = json.loads(run.manifest_path.read_text())
        self.assertEqual(manifest["status"], "completed")
        self.assertIn("finished_at", manifest)

    def test_attach_factor_data_symlink_and_manifest(self) -> None:
        shared_cache = self.tmp / "factor_h5_cache" / "deadbeef"
        (shared_cache / "all").mkdir(parents=True)
        (shared_cache / "all" / "daily_pv.h5").write_text("x")
        ctx = types.SimpleNamespace(
            cache_dir=shared_cache,
            fingerprint="deadbeef",
            spec=types.SimpleNamespace(market="csi500"),
        )
        with self.rw.run_workspace(command="backtest", market="csi500", factor_data_ctx=ctx) as run:
            link = run.root / "factor_data"
            self.assertTrue(link.is_symlink())
            self.assertEqual(Path(os.readlink(link)), shared_cache)
            manifest = json.loads(run.manifest_path.read_text())
            self.assertEqual(manifest["spec_hash"], "deadbeef")
            self.assertEqual(manifest["factor_data_dir"], str(shared_cache))

    def test_list_and_delete_run_preserves_shared_cache(self) -> None:
        shared_cache = self.tmp / "factor_h5_cache" / "spec1"
        shared_cache.mkdir(parents=True)
        ctx = types.SimpleNamespace(
            cache_dir=shared_cache, fingerprint="spec1", spec=types.SimpleNamespace(market="m1")
        )
        with self.rw.run_workspace(command="mine", market="m1", factor_data_ctx=ctx) as r1:
            run1_id = r1.run_id
        with self.rw.run_workspace(command="backtest", market="m2") as r2:
            run2_id = r2.run_id

        listed = {r["run_id"] for r in self.rw.list_runs()}
        self.assertEqual(listed, {run1_id, run2_id})

        self.assertTrue(self.rw.delete_run(run1_id))
        self.assertFalse((self.runs / run1_id).exists())
        # deleting the run unlinked the symlink but kept the shared cache target
        self.assertTrue(shared_cache.exists())
        self.assertEqual({r["run_id"] for r in self.rw.list_runs()}, {run2_id})

    def test_restore_on_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.rw.run_workspace(command="mine", market="m1") as run:
                self.assertEqual(self.cw.resolve_workspace_root(), run.workspaces_dir)
                raise RuntimeError("boom")
        # state restored despite the exception
        self.assertEqual(self.cw.resolve_workspace_root(), self.default_root)
        self.assertNotIn(self.rw.WORKSPACE_ROOT_ENV, os.environ)
        self.assertIsNone(self.rw.current_run())
        manifest = json.loads(run.manifest_path.read_text())
        self.assertEqual(manifest["status"], "failed")

    def test_delete_run_rejects_escape(self) -> None:
        with self.assertRaises(Exception):
            self.rw.delete_run("../../etc")


if __name__ == "__main__":
    unittest.main()
