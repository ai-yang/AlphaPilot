"""Default factor management system.

Wraps the factor DSL + the file-based factor zoo, and exposes the
existing JSON/PDF import loaders behind a single ``import_factors`` API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alphapilot.systems.factor.base import BaseFactorSystem
from alphapilot.systems.factor.database import build_factor_database
from alphapilot.systems.factor.types import (
    OK_CODE,
    REJECT_DUPLICATE_EXPRESSION,
    REJECT_DUPLICATE_NAME,
    REJECT_MISSING_NAME,
    FactorValidationResult,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class FactorSystem(BaseFactorSystem):
    """Factor import + zoo + expression evaluation."""

    def setup(self, context: "Context") -> None:
        self.context = context
        cfg = context.config.factor
        self._database = build_factor_database(cfg.database_backend, cfg.zoo_dir)

    def import_factors(self, source: Any, *, kind: str = "csv") -> Any:
        if kind in ("csv", "json", "dict"):
            from alphapilot.systems.factor.loaders.json_loader import (
                FactorExperimentLoaderFromDict,
            )

            if kind == "dict":
                return FactorExperimentLoaderFromDict().load(source)
            import pandas as pd

            records = (
                pd.read_csv(source).to_dict(orient="records")
                if kind == "csv"
                else source
            )
            return FactorExperimentLoaderFromDict().load(records)
        if kind == "pdf":
            from alphapilot.systems.factor.loaders.pdf_loader import (
                FactorExperimentLoaderFromPDFfiles,
            )

            return FactorExperimentLoaderFromPDFfiles().load(source)
        raise ValueError(f"Unsupported factor import kind: {kind!r}")

    def is_acceptable(self, expression: str) -> bool:
        return self._database.is_acceptable(expression)

    def validate_expression(self, expression: str) -> FactorValidationResult:
        return self._database.validate(expression)

    def add_factor(
        self,
        factor_name: str,
        factor_expression: str,
        *,
        categories: list[str] | None = None,
        save: bool = True,
    ) -> FactorValidationResult:
        """Validate then add a factor; return structured result on failure.

        *categories* (optional) assigns the new factor to those categories when
        the backend supports a registry; ignored otherwise.
        """
        name = factor_name.strip()
        expr = factor_expression.strip()
        if not name:
            return FactorValidationResult(
                acceptable=False,
                code=REJECT_MISSING_NAME,
                message="Factor name is required.",
                details=None,
            )

        for item in self.list_factors():
            if item["factor_name"] == name:
                return FactorValidationResult(
                    acceptable=False,
                    code=REJECT_DUPLICATE_NAME,
                    message=f"Factor name '{name}' already exists in the zoo.",
                    details={"factor_name": name},
                )

        validation = self.validate_expression(expr)
        if not validation.acceptable:
            return validation

        for item in self.list_factors():
            if item["factor_expression"].strip() == expr:
                return FactorValidationResult(
                    acceptable=False,
                    code=REJECT_DUPLICATE_EXPRESSION,
                    message="An identical factor expression already exists in the zoo.",
                    details={"factor_name": item["factor_name"]},
                )

        self._database.add(name, expr)
        if categories and getattr(self._database, "supports_categories", False):
            self._database.set_factor_categories(name, categories)
        if save:
            self._database.save()
        return FactorValidationResult(
            acceptable=True,
            code=OK_CODE,
            message=f"Factor '{name}' added.",
            details={"factor_name": name, "categories": categories or []},
        )

    def evaluate_expression(self, expression: str) -> Any:
        from alphapilot.systems.factor.expression import parse_expression

        return parse_expression(expression)

    def list_factors(self) -> list[dict[str, Any]]:
        return self._database.list_factors()

    def delete_factor(self, factor_name: str, *, save: bool = True) -> bool:
        removed = self._database.delete(factor_name.strip())
        if removed and save:
            self._database.save()
            self._database.reload()
        return removed

    def delete_factors(
        self, factor_names: list[str], *, save: bool = True
    ) -> dict[str, list[str]]:
        """Delete several factors at once with a single persist/reload.

        Returns ``{"deleted": [...], "missing": [...]}``. Used by the portal's
        duplicate-cleanup flow so removing a whole group of duplicates does not
        rewrite the zoo once per factor.
        """
        deleted: list[str] = []
        missing: list[str] = []
        for name in factor_names:
            if self._database.delete(name.strip()):
                deleted.append(name)
            else:
                missing.append(name)
        if deleted and save:
            self._database.save()
            self._database.reload()
        return {"deleted": deleted, "missing": missing}

    def find_duplicate_factors(
        self, *, similarity_threshold: float = 0.8
    ) -> dict[str, Any]:
        """Scan the zoo for duplicate / near-duplicate factor expressions.

        Reuses the AST comparison primitives the regulator already uses
        (:func:`parse_expression` + :func:`find_largest_common_subtree`):

        * **Equivalence groups** -- factors whose ASTs are equal (commutativity
          and ``5`` vs ``5.0`` aware). Two trees are equal iff their largest
          common subtree spans both whole trees, so equal trees share the same
          node count; we only compare within a node-count bucket.
        * **Similar pairs** -- non-equivalent factors whose shared subtree covers
          at least ``similarity_threshold`` of the larger tree (the "degree" of
          duplication), reported read-only.
        """
        from collections import defaultdict

        from alphapilot.components.coder.factor_coder.factor_ast import (
            find_largest_common_subtree,
            parse_expression,
        )

        factors = self.list_factors()
        parsed: list[dict[str, Any]] = []
        unparsable: list[str] = []
        for item in factors:
            expr = item["factor_expression"]
            try:
                tree = parse_expression(expr)
                size = find_largest_common_subtree(tree, tree).size
            except Exception:  # noqa: BLE001 - a malformed legacy entry must not break the scan
                unparsable.append(item["factor_name"])
                continue
            parsed.append(
                {
                    "factor_name": item["factor_name"],
                    "factor_expression": expr,
                    "categories": item.get("categories", []),
                    "tree": tree,
                    "size": size,
                }
            )

        # --- equivalence grouping via union-find within equal-size buckets ---
        parent = list(range(len(parsed)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        size_buckets: dict[int, list[int]] = defaultdict(list)
        for idx, p in enumerate(parsed):
            size_buckets[p["size"]].append(idx)

        for size, idxs in size_buckets.items():
            for ii in range(len(idxs)):
                for jj in range(ii + 1, len(idxs)):
                    a, b = idxs[ii], idxs[jj]
                    if find(a) == find(b):
                        continue
                    match = find_largest_common_subtree(parsed[a]["tree"], parsed[b]["tree"])
                    if match is not None and match.size == size:
                        union(a, b)

        members_by_root: dict[int, list[int]] = defaultdict(list)
        for idx in range(len(parsed)):
            members_by_root[find(idx)].append(idx)

        groups: list[dict[str, Any]] = []
        grouped: set[int] = set()
        for root, member_idxs in members_by_root.items():
            if len(member_idxs) < 2:
                continue
            grouped.update(member_idxs)
            members = [
                {
                    "factor_name": parsed[i]["factor_name"],
                    "factor_expression": parsed[i]["factor_expression"],
                    "categories": parsed[i]["categories"],
                }
                for i in member_idxs
            ]
            # Keep the most-categorised (then lexicographically first) factor.
            keep = min(
                members,
                key=lambda m: (-len(m["categories"]), m["factor_name"]),
            )
            groups.append(
                {
                    "members": members,
                    "canonical": str(parsed[member_idxs[0]]["tree"]),
                    "suggested_keep": keep["factor_name"],
                    "suggested_delete": [
                        m["factor_name"] for m in members if m["factor_name"] != keep["factor_name"]
                    ],
                }
            )
        groups.sort(key=lambda g: (-len(g["members"]), g["suggested_keep"]))

        # --- near-duplicate similarity pairs (advisory, not for deletion) ---
        similar_pairs: list[dict[str, Any]] = []
        n = len(parsed)
        for i in range(n):
            for j in range(i + 1, n):
                if find(i) == find(j):
                    continue  # already an exact-equivalence group
                size_i, size_j = parsed[i]["size"], parsed[j]["size"]
                larger = max(size_i, size_j)
                # ratio = shared / larger can only reach the threshold when the
                # smaller tree is itself large enough; prune cheaply first.
                if larger == 0 or min(size_i, size_j) / larger < similarity_threshold:
                    continue
                match = find_largest_common_subtree(parsed[i]["tree"], parsed[j]["tree"])
                shared = match.size if match is not None else 0
                ratio = shared / larger
                if ratio >= similarity_threshold:
                    similar_pairs.append(
                        {
                            "factor_a": parsed[i]["factor_name"],
                            "factor_b": parsed[j]["factor_name"],
                            "similarity": round(ratio, 4),
                            "shared": str(match.root1) if match is not None else "",
                        }
                    )
        similar_pairs.sort(key=lambda p: p["similarity"], reverse=True)

        return {
            "groups": groups,
            "similar_pairs": similar_pairs,
            "n_factors": len(factors),
            "n_duplicate_groups": len(groups),
            "n_redundant_factors": sum(len(g["suggested_delete"]) for g in groups),
            "unparsable": unparsable,
            "similarity_threshold": similarity_threshold,
        }

    def rename_factor(
        self, factor_name: str, new_name: str, *, save: bool = True
    ) -> FactorValidationResult:
        """Rename a factor (expression and category links preserved).

        Mirrors ``add_factor``'s name checks: the new name must be non-empty and must not collide
        with an existing factor.
        """
        old = factor_name.strip()
        new = new_name.strip()
        if not new:
            return FactorValidationResult(
                acceptable=False,
                code=REJECT_MISSING_NAME,
                message="New factor name is required.",
                details=None,
            )
        if new == old:
            return FactorValidationResult(
                acceptable=True, code=OK_CODE, message="Name unchanged.", details={"factor_name": old}
            )
        for item in self.list_factors():
            if item["factor_name"] == new:
                return FactorValidationResult(
                    acceptable=False,
                    code=REJECT_DUPLICATE_NAME,
                    message=f"Factor name '{new}' already exists in the zoo.",
                    details={"factor_name": new},
                )
        if not self._database.rename(old, new):
            return FactorValidationResult(
                acceptable=False,
                code=REJECT_MISSING_NAME,
                message=f"Factor '{old}' not found in the zoo.",
                details={"factor_name": old},
            )
        if save:
            self._database.save()
            self._database.reload()
        return FactorValidationResult(
            acceptable=True,
            code=OK_CODE,
            message=f"Factor renamed '{old}' -> '{new}'.",
            details={"factor_name": new, "previous_name": old},
        )

    @property
    def database(self) -> Any:
        return self._database
