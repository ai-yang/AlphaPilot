"""Tier 1 (offline): factor management through the real FactorSystem.

Exercises the full CRUD + category surface on a real SQLite-backed zoo rooted
in ``tmp_path`` (via the ``engine`` fixture). No network, no credentials.
"""

from __future__ import annotations

import json

import pytest

GOOD_EXPR = "Mean($close,5)/$close-1"
GOOD_EXPR_2 = "$close/$open-1"


@pytest.fixture()
def factor(engine):
    return engine.get_system("factor")


def test_validate_accepts_and_rejects(factor) -> None:
    assert factor.validate_expression(GOOD_EXPR).acceptable is True
    bad = factor.validate_expression("this is not valid @@@")
    assert bad.acceptable is False
    assert bad.code == "parse_error"


def test_add_list_rename_delete(factor) -> None:
    assert factor.add_factor("f1", GOOD_EXPR).acceptable is True
    assert {f["factor_name"] for f in factor.list_factors()} == {"f1"}

    renamed = factor.rename_factor("f1", "f1b")
    assert renamed.acceptable is True
    assert {f["factor_name"] for f in factor.list_factors()} == {"f1b"}

    assert factor.delete_factor("f1b") is True
    assert factor.list_factors() == []


def test_add_rejects_duplicates_and_blank_name(factor) -> None:
    assert factor.add_factor("dup", GOOD_EXPR).acceptable is True
    assert factor.add_factor("dup", GOOD_EXPR_2).code == "duplicate_name"
    assert factor.add_factor("other", GOOD_EXPR).code == "duplicate_expression"
    assert factor.add_factor("   ", GOOD_EXPR_2).code == "missing_name"


def test_rename_to_existing_name_rejected(factor) -> None:
    factor.add_factor("a", GOOD_EXPR)
    factor.add_factor("b", GOOD_EXPR_2)
    result = factor.rename_factor("a", "b")
    assert result.acceptable is False
    assert result.code == "duplicate_name"


def test_category_crud_and_membership(factor) -> None:
    assert factor.database.supports_categories is True
    factor.add_factor("m1", GOOD_EXPR, categories=["momentum"])
    factor.add_factor("v1", GOOD_EXPR_2)

    assert "momentum" in factor.list_categories()

    # Create + assign a second category, then move membership around.
    assert factor.create_category("value") is True
    factor.add_factors_to_category(["v1"], "value")
    by_name = {f["factor_name"]: f.get("categories", []) for f in factor.list_factors()}
    assert "momentum" in by_name["m1"]
    assert "value" in by_name["v1"]

    factor.remove_factors_from_category(["v1"], "value")
    by_name = {f["factor_name"]: f.get("categories", []) for f in factor.list_factors()}
    assert "value" not in by_name["v1"]

    # Rename + delete a category.
    assert factor.rename_category("momentum", "trend") is True
    assert "trend" in factor.list_categories()
    assert factor.delete_category("trend") is True
    assert "trend" not in factor.list_categories()


def test_set_factor_categories_replaces(factor) -> None:
    factor.add_factor("x", GOOD_EXPR, categories=["a", "b"])
    factor.create_category("c")
    assert factor.set_factor_categories("x", ["c"]) is True
    cats = {f["factor_name"]: set(f.get("categories", [])) for f in factor.list_factors()}
    assert cats["x"] == {"c"}


def test_import_factors_from_csv_and_json(factor, tmp_path) -> None:
    # CSV import via the loader path returns a loaded experiment object.
    csv_path = tmp_path / "factors.csv"
    csv_path.write_text(
        "factor_name,factor_expression\nimp_csv,Mean($close,10)/$close-1\n",
        encoding="utf-8",
    )
    loaded_csv = factor.import_factors(str(csv_path), kind="csv")
    assert loaded_csv is not None

    records = [{"factor_name": "imp_json", "factor_expression": "Std($close,5)"}]
    json_path = tmp_path / "factors.json"
    json_path.write_text(json.dumps(records), encoding="utf-8")
    loaded_json = factor.import_factors(records, kind="json")
    assert loaded_json is not None


def test_persistence_across_reload(factor, isolated_env) -> None:
    # Factor zoo is mirrored to CSV under the isolated zoo dir.
    factor.add_factor("persist_me", GOOD_EXPR)
    csv_mirror = isolated_env.factor_zoo / "factor_zoo.csv"
    assert csv_mirror.exists()
    assert "persist_me" in csv_mirror.read_text(encoding="utf-8")


# --- duplicate detection (commutativity / literal-format aware) --------------
# add_factor only blocks string-identical expressions, so these equivalent
# variants all get into the zoo and must be caught by find_duplicate_factors.
COMMUTE_A = "Mean($high,5)+Mean($low,5)"
COMMUTE_B = "Mean($low,5)+Mean($high,5)"  # same as A, operands swapped
LITERAL_A = "Mean($close, 5.0)"
LITERAL_B = "Mean($close,5)"  # same as A, 5 vs 5.0


def test_find_duplicate_factors_groups_equivalents(factor) -> None:
    factor.add_factor("commute_a", COMMUTE_A, categories=["a"])
    factor.add_factor("commute_b", COMMUTE_B)
    factor.add_factor("literal_a", LITERAL_A)
    factor.add_factor("literal_b", LITERAL_B)
    factor.add_factor("unique", "Std($volume,20)")

    report = factor.find_duplicate_factors(similarity_threshold=0.9)
    groups = {frozenset(m["factor_name"] for m in g["members"]) for g in report["groups"]}
    assert frozenset({"commute_a", "commute_b"}) in groups
    assert frozenset({"literal_a", "literal_b"}) in groups
    assert report["n_duplicate_groups"] == 2
    assert report["n_redundant_factors"] == 2

    grouped = {m["factor_name"] for g in report["groups"] for m in g["members"]}
    assert "unique" not in grouped


def test_find_duplicate_suggested_keep_prefers_categorized(factor) -> None:
    factor.add_factor("plain", COMMUTE_A)
    factor.add_factor("tagged", COMMUTE_B, categories=["x", "y"])
    group = factor.find_duplicate_factors()["groups"][0]
    # The factor carrying the most categories is kept; the rest are deletion candidates.
    assert group["suggested_keep"] == "tagged"
    assert group["suggested_delete"] == ["plain"]


def test_find_duplicate_similar_pairs(factor) -> None:
    factor.add_factor("e", "Mean($close,5)/$close-1")
    factor.add_factor("f", "Mean($close,5)/$open-1")  # shares Mean($close,5), not equivalent
    report = factor.find_duplicate_factors(similarity_threshold=0.4)
    assert report["n_duplicate_groups"] == 0
    pairs = {frozenset({p["factor_a"], p["factor_b"]}) for p in report["similar_pairs"]}
    assert frozenset({"e", "f"}) in pairs


def test_delete_factors_bulk(factor) -> None:
    factor.add_factor("k", COMMUTE_A)
    factor.add_factor("v", COMMUTE_B)
    result = factor.delete_factors(["v", "missing_one"])
    assert result["deleted"] == ["v"]
    assert result["missing"] == ["missing_one"]
    assert {f["factor_name"] for f in factor.list_factors()} == {"k"}
