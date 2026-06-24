"""CLI module for factor zoo validation, management, and categories."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule
from alphapilot.systems.factor.types import FactorValidationResult

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def _print_validation(
    result: FactorValidationResult, *, expression: str | None = None
) -> None:
    if expression is not None:
        print(f"Expression: {expression}")
    status = "PASS" if result.acceptable else "FAIL"
    print(f"Status: {status}")
    print(f"Code: {result.code}")
    print(f"Message: {result.message}")
    if result.details:
        print(
            f"Details: {json.dumps(result.details, ensure_ascii=False, indent=2, default=str)}"
        )


def _parse_categories(value: Any) -> list[str]:
    """Normalize a CLI ``--categories`` value (``"a,b"`` or a list) to a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).split(",")
    return [str(c).strip() for c in items if str(c).strip()]


def _parse_factor_names(value: Any) -> list[str]:
    """Normalize a CLI factor-name list (``"a,b"`` or a list) to a list."""
    return _parse_categories(value)


class FactorModule(BaseModule):
    """Validate, add, categorize, and list factors via CLI."""

    name = "factor"

    def setup(self, context: "Context") -> None:
        self.context = context

    def factor_validate(self, expression: str) -> dict[str, Any]:
        """Validate a factor expression and print the rejection reason if any."""
        result = self.context.factor().validate_expression(expression)
        _print_validation(result, expression=expression)
        if not result.acceptable:
            sys.exit(1)
        return result.to_dict()

    def factor_add(
        self, factor_name: str, expression: str, categories: Any = None
    ) -> dict[str, Any]:
        """Validate then add a factor; ``--categories=a,b`` assigns categories."""
        cats = _parse_categories(categories)
        result = self.context.factor().add_factor(
            factor_name, expression, categories=cats
        )
        _print_validation(result, expression=expression)
        if not result.acceptable:
            sys.exit(1)
        return result.to_dict()

    def factor_rename(self, factor_name: str, new_name: str) -> dict[str, Any]:
        """Rename a factor in the zoo (expression and categories are preserved)."""
        result = self.context.factor().rename_factor(factor_name, new_name)
        _print_validation(result, expression=new_name)
        if not result.acceptable:
            sys.exit(1)
        return result.to_dict()

    def factor_list(self, category: str | None = None) -> list[dict[str, Any]]:
        """List factors in the zoo, optionally filtered to a single ``--category``."""
        factor_system = self.context.factor()
        if category:
            factors = factor_system.factors_in_category(category)
        else:
            factors = factor_system.list_factors()
        for item in factors:
            cats = ", ".join(item.get("categories", []))
            suffix = f"  [{cats}]" if cats else ""
            print(f"{item['factor_name']}: {item['factor_expression']}{suffix}")
        return factors

    def factor_categorize(
        self, factor_name: str, categories: Any = None
    ) -> dict[str, Any]:
        """Replace a factor's categories with ``--categories=a,b`` (creates missing ones)."""
        cats = _parse_categories(categories)
        ok = self.context.factor().set_factor_categories(factor_name, cats)
        if not ok:
            print(f"Factor not found: {factor_name}")
            sys.exit(1)
        print(f"Set categories of '{factor_name}' to: {cats or '[]'}")
        return {"factor_name": factor_name, "categories": cats}

    def factor_category_add(self, factor_names: Any, category: str) -> dict[str, Any]:
        """Add one category to multiple factors without replacing existing categories."""
        names = _parse_factor_names(factor_names)
        summary = self.context.factor().add_factors_to_category(names, category)
        print(
            f"Added category '{summary['category']}' to {len(summary['changed'])} factor(s); "
            f"unchanged={len(summary['unchanged'])}, missing={len(summary['missing'])}."
        )
        return summary

    def factor_category_remove(
        self, factor_names: Any, category: str
    ) -> dict[str, Any]:
        """Remove one category from multiple factors while preserving other categories."""
        names = _parse_factor_names(factor_names)
        summary = self.context.factor().remove_factors_from_category(names, category)
        print(
            f"Removed category '{summary['category']}' from {len(summary['changed'])} factor(s); "
            f"unchanged={len(summary['unchanged'])}, missing={len(summary['missing'])}."
        )
        return summary

    def category_list(self) -> list[str]:
        """List all categories in the registry."""
        names = self.context.factor().list_categories()
        for name in names:
            print(name)
        return names

    def category_create(self, name: str) -> dict[str, Any]:
        """Create an (initially empty) category."""
        created = self.context.factor().create_category(name)
        print(f"Category '{name}' {'created' if created else 'already exists'}.")
        return {"name": name, "created": created}

    def category_rename(self, old_name: str, new_name: str) -> dict[str, Any]:
        """Rename a category."""
        ok = self.context.factor().rename_category(old_name, new_name)
        if not ok:
            print(f"Category not found: {old_name}")
            sys.exit(1)
        print(f"Renamed category '{old_name}' -> '{new_name}'.")
        return {"old_name": old_name, "new_name": new_name}

    def category_delete(self, name: str) -> dict[str, Any]:
        """Delete a category (factors are kept; only the assignments are removed)."""
        removed = self.context.factor().delete_category(name)
        if not removed:
            print(f"Category not found: {name}")
            sys.exit(1)
        print(f"Deleted category '{name}'.")
        return {"name": name, "removed": removed}

    def factor_duplicates(self, similarity_threshold: float = 0.8) -> dict[str, Any]:
        """Report duplicate / near-duplicate factors in the zoo.

        Groups factors whose expressions are equivalent (commutativity and
        ``5`` vs ``5.0`` aware) and lists near-duplicate pairs whose shared
        subtree covers at least ``--similarity_threshold`` of the larger tree.
        """
        report = self.context.factor().find_duplicate_factors(
            similarity_threshold=similarity_threshold
        )
        groups = report["groups"]
        if not groups:
            print("No duplicate factors found.")
        for i, group in enumerate(groups, 1):
            print(f"\nDuplicate group {i} (keep: {group['suggested_keep']}):")
            for member in group["members"]:
                tag = "keep" if member["factor_name"] == group["suggested_keep"] else "dup "
                print(f"  [{tag}] {member['factor_name']}: {member['factor_expression']}")
        if report["similar_pairs"]:
            print("\nNear-duplicate pairs:")
            for pair in report["similar_pairs"]:
                print(
                    f"  {pair['factor_a']} ~ {pair['factor_b']}  "
                    f"({pair['similarity'] * 100:.0f}% shared: {pair['shared']})"
                )
        print(
            f"\n{report['n_factors']} factors, {report['n_duplicate_groups']} duplicate "
            f"group(s), {report['n_redundant_factors']} redundant."
        )
        return report

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "factor_validate": self.factor_validate,
            "factor_add": self.factor_add,
            "factor_rename": self.factor_rename,
            "factor_list": self.factor_list,
            "factor_duplicates": self.factor_duplicates,
            "factor_categorize": self.factor_categorize,
            "factor_category_add": self.factor_category_add,
            "factor_category_remove": self.factor_category_remove,
            "category_list": self.category_list,
            "category_create": self.category_create,
            "category_rename": self.category_rename,
            "category_delete": self.category_delete,
        }
