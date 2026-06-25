from __future__ import annotations

from pathlib import Path

import pytest

from alphapilot.log.cleanup import clean_log_dirs, collect_removable_log_dirs


def test_collect_removable_log_dirs_prefers_parent_matches(tmp_path: Path) -> None:
    log_root = tmp_path / "log"
    stub = log_root / "stub-session" / "12345"
    pair = log_root / "pair-session" / "child"
    empty = log_root / "empty-session"
    keep = log_root / "keep-session"
    stub.mkdir(parents=True)
    pair.mkdir(parents=True)
    empty.mkdir(parents=True)
    keep.mkdir(parents=True)
    (stub / "common_logs.log").write_text("started\n", encoding="utf-8")
    (pair.parent / "common_logs.log").write_text("started\n", encoding="utf-8")
    (keep / "result.json").write_text("{}", encoding="utf-8")

    removable = [path.relative_to(log_root) for path in collect_removable_log_dirs(log_root)]

    assert set(removable) == {
        Path("stub-session"),
        Path("pair-session"),
        Path("empty-session"),
    }
    assert Path("pair-session/child") not in removable


def test_clean_log_dirs_preview_and_execute(tmp_path: Path) -> None:
    log_root = tmp_path / "log"
    removable = log_root / "empty-session"
    keep = log_root / "keep-session"
    removable.mkdir(parents=True)
    keep.mkdir(parents=True)
    (keep / "result.json").write_text("{}", encoding="utf-8")

    preview = clean_log_dirs(log_root)

    assert preview.execute is False
    assert preview.removed == 1
    assert preview.paths == [Path("empty-session")]
    assert removable.exists()

    executed = clean_log_dirs(log_root, execute=True)

    assert executed.execute is True
    assert executed.removed == 1
    assert executed.paths == [Path("empty-session")]
    assert not removable.exists()
    assert keep.exists()


def test_clean_log_dirs_requires_existing_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        clean_log_dirs(tmp_path / "missing")
