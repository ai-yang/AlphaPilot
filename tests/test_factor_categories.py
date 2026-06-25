"""Tests for the SQLite factor zoo backend and its many-to-many categories."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from alphapilot.systems.factor.database import (
    FileFactorDatabase,
    SqliteFactorDatabase,
    build_factor_database,
)


@pytest.fixture()
def db(tmp_path: Path) -> SqliteFactorDatabase:
    return SqliteFactorDatabase(tmp_path)


def test_factory_builds_sqlite_backend(tmp_path: Path) -> None:
    assert isinstance(build_factor_database("sqlite", tmp_path), SqliteFactorDatabase)
    assert isinstance(build_factor_database("file", tmp_path), FileFactorDatabase)
    with pytest.raises(ValueError):
        build_factor_database("nope", tmp_path)


def test_add_list_and_categories_many_to_many(db: SqliteFactorDatabase) -> None:
    db.add("mom", "Mean($close,5)/$close")
    db.add("rev", "Std($volume,10)")
    db.set_factor_categories("mom", ["momentum", "shared"])
    db.set_factor_categories("rev", ["reversal", "shared"])

    by_name = {f["factor_name"]: f["categories"] for f in db.list_factors()}
    assert by_name == {"mom": ["momentum", "shared"], "rev": ["reversal", "shared"]}
    assert db.list_categories() == ["momentum", "reversal", "shared"]
    # one category -> many factors
    assert {f["factor_name"] for f in db.factors_in_category("shared")} == {
        "mom",
        "rev",
    }


def test_create_empty_category_and_rename(db: SqliteFactorDatabase) -> None:
    assert db.create_category("ideas") is True
    assert db.create_category("ideas") is False  # idempotent
    assert "ideas" in db.list_categories()  # empty category persists

    db.add("a", "$close")
    db.set_factor_categories("a", ["ideas"])
    assert db.rename_category("ideas", "concepts") is True
    assert db.list_categories() == ["concepts"]
    assert db.list_factors()[0]["categories"] == ["concepts"]


def test_delete_category_cascade_keeps_factor(db: SqliteFactorDatabase) -> None:
    db.add("a", "$close")
    db.set_factor_categories("a", ["x", "y"])
    assert db.delete_category("x") is True
    assert db.list_factors()[0]["categories"] == ["y"]  # factor kept, link removed


def test_delete_factor_cascades_links(db: SqliteFactorDatabase) -> None:
    db.add("a", "$close")
    db.set_factor_categories("a", ["x"])
    assert db.delete("a") is True
    assert db.list_factors() == []
    # category registry entry survives a factor deletion
    assert "x" in db.list_categories()


def test_sqlite_backend_does_not_auto_migrate_csv(tmp_path: Path) -> None:
    pd.DataFrame(
        {"factor_name": ["legacy"], "factor_expression": ["Ref($close,1)/$close-1"]}
    ).to_csv(tmp_path / "factor_zoo.csv", index=False)

    db = SqliteFactorDatabase(tmp_path)
    assert db.list_factors() == []


def test_save_materializes_two_column_csv(
    db: SqliteFactorDatabase, tmp_path: Path
) -> None:
    db.add("a", "$close")
    db.set_factor_categories("a", ["x"])
    db.save()
    mirror = pd.read_csv(tmp_path / "factor_zoo.csv")
    assert list(mirror.columns) == ["factor_name", "factor_expression"]  # back-compat


def test_export_category_csv(db: SqliteFactorDatabase, tmp_path: Path) -> None:
    db.add("a", "$close")
    db.add("b", "$open")
    db.set_factor_categories("a", ["keep"])
    out = tmp_path / "cat.csv"
    assert db.export_category_csv("keep", out) == 1
    exported = pd.read_csv(out)
    assert list(exported.columns) == ["factor_name", "factor_expression"]
    assert exported["factor_name"].tolist() == ["a"]


def test_bulk_add_category_is_additive_and_creates_category(
    db: SqliteFactorDatabase,
) -> None:
    db.add("a", "$close")
    db.add("b", "$open")
    db.set_factor_categories("a", ["existing"])

    summary = db.add_factors_to_category(["a", "b"], "momentum")

    assert summary == {
        "category": "momentum",
        "requested": ["a", "b"],
        "changed": ["a", "b"],
        "unchanged": [],
        "missing": [],
    }
    by_name = {f["factor_name"]: f["categories"] for f in db.list_factors()}
    assert by_name["a"] == ["existing", "momentum"]
    assert by_name["b"] == ["momentum"]
    assert "momentum" in db.list_categories()


def test_bulk_add_category_reports_unchanged_and_missing(
    db: SqliteFactorDatabase,
) -> None:
    db.add("a", "$close")
    db.add_factors_to_category(["a"], "momentum")

    summary = db.add_factors_to_category(["a", "a", "missing"], "momentum")

    assert summary["requested"] == ["a", "missing"]
    assert summary["changed"] == []
    assert summary["unchanged"] == ["a"]
    assert summary["missing"] == ["missing"]
    assert db.list_factors()[0]["categories"] == ["momentum"]


def test_bulk_remove_category_preserves_other_categories(
    db: SqliteFactorDatabase,
) -> None:
    db.add("a", "$close")
    db.add("b", "$open")
    db.set_factor_categories("a", ["momentum", "keep"])
    db.set_factor_categories("b", ["keep"])

    summary = db.remove_factors_from_category(["a", "b", "missing"], "momentum")

    assert summary["changed"] == ["a"]
    assert summary["unchanged"] == ["b"]
    assert summary["missing"] == ["missing"]
    by_name = {f["factor_name"]: f["categories"] for f in db.list_factors()}
    assert by_name["a"] == ["keep"]
    assert by_name["b"] == ["keep"]


def test_bulk_remove_nonexistent_category_does_not_create_it(
    db: SqliteFactorDatabase,
) -> None:
    db.add("a", "$close")

    summary = db.remove_factors_from_category(["a"], "ghost")

    assert summary["changed"] == []
    assert summary["unchanged"] == ["a"]
    assert "ghost" not in db.list_categories()


def test_bulk_category_empty_inputs(db: SqliteFactorDatabase) -> None:
    db.add("a", "$close")

    assert db.add_factors_to_category([], "x") == {
        "category": "x",
        "requested": [],
        "changed": [],
        "unchanged": [],
        "missing": [],
    }
    assert "x" not in db.list_categories()
    with pytest.raises(ValueError):
        db.add_factors_to_category(["a"], "")
    with pytest.raises(ValueError):
        db.remove_factors_from_category(["a"], " ")


def test_bulk_category_save_materializes_csv(
    db: SqliteFactorDatabase, tmp_path: Path
) -> None:
    db.add("a", "$close")
    db.add_factors_to_category(["a"], "x")
    db.save()

    mirror = pd.read_csv(tmp_path / "factor_zoo.csv")
    assert mirror["factor_name"].tolist() == ["a"]
    assert list(mirror.columns) == ["factor_name", "factor_expression"]


def test_file_backend_has_no_categories(tmp_path: Path) -> None:
    fdb = FileFactorDatabase(tmp_path)
    assert fdb.supports_categories is False
    assert fdb.list_categories() == []
    with pytest.raises(NotImplementedError):
        fdb.create_category("x")
    with pytest.raises(NotImplementedError):
        fdb.add_factors_to_category(["a"], "x")


def test_match_alphazoo_tolerates_extra_columns() -> None:
    from alphapilot.components.coder.factor_coder.factor_ast import match_alphazoo

    df = pd.DataFrame(
        {
            "factor_name": ["a"],
            "factor_expression": ["$close"],
            "categories": ["momentum"],  # extra column must not break dedup
        }
    )
    # Should not raise "too many values to unpack".
    size, _subtree, _alpha = match_alphazoo("$close", df)
    assert isinstance(size, int)


def test_rename_factor_sqlite_preserves_expression_and_categories(db: SqliteFactorDatabase) -> None:
    db.add("old_mom", "Mean($close,5)/$close")
    db.set_factor_categories("old_mom", ["momentum", "shared"])

    assert db.rename("old_mom", "new_mom") is True
    factors = {f["factor_name"]: f for f in db.list_factors()}
    assert "old_mom" not in factors
    assert factors["new_mom"]["factor_expression"] == "Mean($close,5)/$close"
    # category links reference the factor id, so they survive the rename
    assert factors["new_mom"]["categories"] == ["momentum", "shared"]
    # renaming a missing factor is a no-op
    assert db.rename("nope", "whatever") is False


def test_rename_factor_file_backend(tmp_path: Path) -> None:
    fdb = FileFactorDatabase(tmp_path)
    fdb.add("alpha", "$close/Ref($close,1)-1")
    assert fdb.rename("alpha", "alpha_renamed") is True
    names = {f["factor_name"]: f["factor_expression"] for f in fdb.list_factors()}
    assert "alpha" not in names
    assert names["alpha_renamed"] == "$close/Ref($close,1)-1"
    assert fdb.rename("missing", "x") is False
