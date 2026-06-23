"""Factor database (factor zoo) abstraction.

Provides a small storage-agnostic facade over the factor zoo. Two backends:

- ``file``   — the legacy CSV zoo wrapping ``FactorRegulator`` (no categories).
- ``sqlite`` — SQLite store supporting a many-to-many factor↔category registry,
  with optional CSV export/mirror support for compatibility.

Both expose the same :class:`BaseFactorDatabase` interface; category methods have
safe defaults on the base so the ``file`` backend stays valid.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from contextlib import closing
from pathlib import Path
from typing import Any

from alphapilot.log import logger
from alphapilot.systems.factor.types import FactorValidationResult


class BaseFactorDatabase(ABC):
    """Store / dedup / query mined factor expressions."""

    #: Whether this backend supports the category registry (overridden by sqlite).
    supports_categories: bool = False

    @abstractmethod
    def is_acceptable(self, expression: str) -> bool:
        """Whether *expression* is parsable and original enough to keep."""

    @abstractmethod
    def validate(self, expression: str) -> FactorValidationResult:
        """Validate *expression* and return a structured result with rejection reason."""

    @abstractmethod
    def add(self, factor_name: str, factor_expression: str) -> bool:
        """Add a factor to the zoo; return True if added."""

    @abstractmethod
    def list_factors(self) -> list[dict[str, Any]]:
        """Return all factors in the zoo (each dict carries a ``categories`` list)."""

    @abstractmethod
    def delete(self, factor_name: str) -> bool:
        """Remove a factor by name; return True if removed."""

    @abstractmethod
    def rename(self, old_name: str, new_name: str) -> bool:
        """Rename a factor (expression and category links preserved); True if renamed."""

    @abstractmethod
    def save(self, output_path: str | None = None) -> None:
        """Persist the zoo to disk."""

    # ---- Category registry (default: unsupported; sqlite backend overrides) ----

    def list_categories(self) -> list[str]:
        """Return all category names (empty when the backend has no registry)."""
        return []

    def create_category(self, name: str) -> bool:
        raise NotImplementedError("Categories require the 'sqlite' factor backend.")

    def rename_category(self, old_name: str, new_name: str) -> bool:
        raise NotImplementedError("Categories require the 'sqlite' factor backend.")

    def delete_category(self, name: str) -> bool:
        raise NotImplementedError("Categories require the 'sqlite' factor backend.")

    def set_factor_categories(self, factor_name: str, categories: list[str]) -> bool:
        raise NotImplementedError("Categories require the 'sqlite' factor backend.")

    def add_factors_to_category(
        self, factor_names: list[str], category: str
    ) -> dict[str, Any]:
        raise NotImplementedError("Categories require the 'sqlite' factor backend.")

    def remove_factors_from_category(
        self, factor_names: list[str], category: str
    ) -> dict[str, Any]:
        raise NotImplementedError("Categories require the 'sqlite' factor backend.")

    def factors_in_category(self, name: str) -> list[dict[str, Any]]:
        return []

    def export_category_csv(self, name: str, output_path: str | Path) -> int:
        raise NotImplementedError("Categories require the 'sqlite' factor backend.")


class FileFactorDatabase(BaseFactorDatabase):
    """CSV-backed factor zoo wrapping the legacy ``FactorRegulator`` (no categories)."""

    supports_categories = False

    def __init__(self, zoo_dir: Path, duplication_threshold: int = 8) -> None:
        self.zoo_dir = Path(zoo_dir)
        self.zoo_path = self.zoo_dir / "factor_zoo.csv"
        self._regulator: Any | None = None
        self._duplication_threshold = duplication_threshold

    @property
    def regulator(self) -> Any:
        if self._regulator is None:
            from alphapilot.systems.factor.regulator.factor_regulator import (
                FactorRegulator,
            )

            zoo_path = str(self.zoo_path) if self.zoo_path.exists() else None
            self._regulator = FactorRegulator(
                factor_zoo_path=zoo_path,
                duplication_threshold=self._duplication_threshold,
            )
        return self._regulator

    def validate(self, expression: str) -> FactorValidationResult:
        return self.regulator.validate_expression(expression)

    def is_acceptable(self, expression: str) -> bool:
        return self.validate(expression).acceptable

    def add(self, factor_name: str, factor_expression: str) -> bool:
        return self.regulator.add_factor(factor_name, factor_expression)

    def list_factors(self) -> list[dict[str, Any]]:
        return [{**item, "categories": []} for item in self.regulator.list_factors()]

    def delete(self, factor_name: str) -> bool:
        return self.regulator.remove_factor(factor_name)

    def rename(self, old_name: str, new_name: str) -> bool:
        return self.regulator.rename_factor(old_name, new_name)

    def reload(self) -> None:
        self._regulator = None

    def save(self, output_path: str | None = None) -> None:
        self.zoo_dir.mkdir(parents=True, exist_ok=True)
        self.regulator.save_factor_zoo(output_path or str(self.zoo_path))


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    expression TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS factor_categories (
    factor_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    PRIMARY KEY (factor_id, category_id),
    FOREIGN KEY (factor_id) REFERENCES factors(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
);
"""


class SqliteFactorDatabase(BaseFactorDatabase):
    """SQLite-backed zoo with a many-to-many factor↔category registry.

    Validation/dedup reuse the existing ``FactorRegulator`` (fed a 2-column
    DataFrame of DB rows, so ``match_alphazoo`` is unaffected). ``save()`` can
    export a two-column CSV mirror for compatibility.
    """

    supports_categories = True

    def __init__(self, zoo_dir: Path, duplication_threshold: int = 8) -> None:
        self.zoo_dir = Path(zoo_dir)
        self.zoo_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.zoo_dir / "factor_zoo.db"
        self.csv_path = self.zoo_dir / "factor_zoo.csv"
        self._duplication_threshold = duplication_threshold
        self._regulator: Any | None = None
        self._ensure_schema()

    # ---- connection / schema ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA_SQL)

    # ---- validation / dedup (reuse FactorRegulator over a 2-col frame) ----

    def _build_regulator(self) -> Any:
        import pandas as pd

        from alphapilot.systems.factor.regulator.factor_regulator import FactorRegulator

        reg = FactorRegulator(
            factor_zoo_path=None, duplication_threshold=self._duplication_threshold
        )
        rows = self._factor_rows()
        reg.alphazoo = pd.DataFrame(rows, columns=["factor_name", "factor_expression"])
        return reg

    @property
    def regulator(self) -> Any:
        if self._regulator is None:
            self._regulator = self._build_regulator()
        return self._regulator

    def reload(self) -> None:
        self._regulator = None

    def validate(self, expression: str) -> FactorValidationResult:
        return self.regulator.validate_expression(expression)

    def is_acceptable(self, expression: str) -> bool:
        return self.validate(expression).acceptable

    # ---- factor CRUD ----

    def _factor_rows(self) -> list[tuple[str, str]]:
        with closing(self._connect()) as conn:
            return [
                (str(name), str(expr))
                for name, expr in conn.execute(
                    "SELECT name, expression FROM factors ORDER BY id"
                )
            ]

    def add(self, factor_name: str, factor_expression: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO factors(name, expression) VALUES (?, ?)",
                (factor_name, factor_expression),
            )
        self.reload()
        if cur.rowcount:
            logger.info(
                f"Added new factor: {factor_name} with expression: {factor_expression}"
            )
            return True
        return False

    def list_factors(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            factors = conn.execute(
                "SELECT id, name, expression FROM factors ORDER BY id"
            ).fetchall()
            links = conn.execute(
                """
                SELECT fc.factor_id, c.name
                FROM factor_categories fc JOIN categories c ON c.id = fc.category_id
                ORDER BY c.name
                """
            ).fetchall()
        cats_by_factor: dict[int, list[str]] = {}
        for factor_id, cat_name in links:
            cats_by_factor.setdefault(factor_id, []).append(str(cat_name))
        return [
            {
                "factor_name": str(name),
                "factor_expression": str(expr),
                "categories": cats_by_factor.get(factor_id, []),
            }
            for factor_id, name, expr in factors
        ]

    def delete(self, factor_name: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("DELETE FROM factors WHERE name = ?", (factor_name,))
        self.reload()
        if cur.rowcount:
            logger.info(f"Removed factor: {factor_name}")
            return True
        return False

    def rename(self, old_name: str, new_name: str) -> bool:
        # The category links reference factors by id, so updating the name keeps them intact.
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE factors SET name = ? WHERE name = ?", (new_name, old_name)
            )
        self.reload()
        if cur.rowcount:
            logger.info(f"Renamed factor: {old_name} -> {new_name}")
            return True
        return False

    def save(self, output_path: str | None = None) -> None:
        """Re-materialize the CSV mirror (DB writes are already committed)."""
        import pandas as pd

        target = Path(output_path) if output_path else self.csv_path
        target.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(
            self._factor_rows(), columns=["factor_name", "factor_expression"]
        )
        df.to_csv(target, index=False)
        logger.info(f"Saved factor zoo CSV mirror to {target}")

    # ---- category registry ----

    def list_categories(self) -> list[str]:
        with closing(self._connect()) as conn:
            return [
                str(name)
                for (name,) in conn.execute("SELECT name FROM categories ORDER BY name")
            ]

    def create_category(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO categories(name) VALUES (?)", (name,)
            )
        return bool(cur.rowcount)

    def rename_category(self, old_name: str, new_name: str) -> bool:
        new_name = (new_name or "").strip()
        if not new_name:
            return False
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE categories SET name = ? WHERE name = ?", (new_name, old_name)
            )
        return bool(cur.rowcount)

    def delete_category(self, name: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("DELETE FROM categories WHERE name = ?", (name,))
        return bool(cur.rowcount)

    def _category_id(self, conn: sqlite3.Connection, name: str) -> int:
        conn.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (name,))
        return conn.execute(
            "SELECT id FROM categories WHERE name = ?", (name,)
        ).fetchone()[0]

    @staticmethod
    def _clean_factor_names(factor_names: list[str]) -> list[str]:
        clean: list[str] = []
        seen: set[str] = set()
        for name in factor_names or []:
            factor_name = str(name).strip()
            if factor_name and factor_name not in seen:
                clean.append(factor_name)
                seen.add(factor_name)
        return clean

    @staticmethod
    def _empty_category_summary(category: str, requested: list[str]) -> dict[str, Any]:
        return {
            "category": category,
            "requested": requested,
            "changed": [],
            "unchanged": [],
            "missing": [],
        }

    def set_factor_categories(self, factor_name: str, categories: list[str]) -> bool:
        clean = [c.strip() for c in (categories or []) if c and c.strip()]
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT id FROM factors WHERE name = ?", (factor_name,)
            ).fetchone()
            if row is None:
                return False
            factor_id = row[0]
            conn.execute(
                "DELETE FROM factor_categories WHERE factor_id = ?", (factor_id,)
            )
            for cat in clean:
                category_id = self._category_id(conn, cat)
                conn.execute(
                    "INSERT OR IGNORE INTO factor_categories(factor_id, category_id) VALUES (?, ?)",
                    (factor_id, category_id),
                )
        return True

    def add_factors_to_category(
        self, factor_names: list[str], category: str
    ) -> dict[str, Any]:
        category = (category or "").strip()
        if not category:
            raise ValueError("category is required")
        requested = self._clean_factor_names(factor_names)
        if not requested:
            return self._empty_category_summary(category, requested)

        changed: list[str] = []
        unchanged: list[str] = []
        missing: list[str] = []
        with closing(self._connect()) as conn, conn:
            category_id = self._category_id(conn, category)
            for factor_name in requested:
                row = conn.execute(
                    "SELECT id FROM factors WHERE name = ?", (factor_name,)
                ).fetchone()
                if row is None:
                    missing.append(factor_name)
                    continue
                factor_id = row[0]
                cur = conn.execute(
                    "INSERT OR IGNORE INTO factor_categories(factor_id, category_id) VALUES (?, ?)",
                    (factor_id, category_id),
                )
                if cur.rowcount:
                    changed.append(factor_name)
                else:
                    unchanged.append(factor_name)
        return {
            "category": category,
            "requested": requested,
            "changed": changed,
            "unchanged": unchanged,
            "missing": missing,
        }

    def remove_factors_from_category(
        self, factor_names: list[str], category: str
    ) -> dict[str, Any]:
        category = (category or "").strip()
        if not category:
            raise ValueError("category is required")
        requested = self._clean_factor_names(factor_names)
        if not requested:
            return self._empty_category_summary(category, requested)

        changed: list[str] = []
        unchanged: list[str] = []
        missing: list[str] = []
        with closing(self._connect()) as conn, conn:
            cat_row = conn.execute(
                "SELECT id FROM categories WHERE name = ?", (category,)
            ).fetchone()
            category_id = cat_row[0] if cat_row is not None else None
            for factor_name in requested:
                row = conn.execute(
                    "SELECT id FROM factors WHERE name = ?", (factor_name,)
                ).fetchone()
                if row is None:
                    missing.append(factor_name)
                    continue
                if category_id is None:
                    unchanged.append(factor_name)
                    continue
                factor_id = row[0]
                cur = conn.execute(
                    "DELETE FROM factor_categories WHERE factor_id = ? AND category_id = ?",
                    (factor_id, category_id),
                )
                if cur.rowcount:
                    changed.append(factor_name)
                else:
                    unchanged.append(factor_name)
        return {
            "category": category,
            "requested": requested,
            "changed": changed,
            "unchanged": unchanged,
            "missing": missing,
        }

    def factors_in_category(self, name: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT f.name, f.expression
                FROM factors f
                JOIN factor_categories fc ON fc.factor_id = f.id
                JOIN categories c ON c.id = fc.category_id
                WHERE c.name = ?
                ORDER BY f.id
                """,
                (name,),
            ).fetchall()
        return [{"factor_name": str(n), "factor_expression": str(e)} for n, e in rows]

    def export_category_csv(self, name: str, output_path: str | Path) -> int:
        import pandas as pd

        rows = self.factors_in_category(name)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=["factor_name", "factor_expression"]).to_csv(
            target, index=False
        )
        return len(rows)


def build_factor_database(backend: str, zoo_dir: Path) -> BaseFactorDatabase:
    """Factory: build a factor database for the configured backend."""
    if backend == "file":
        return FileFactorDatabase(zoo_dir)
    if backend == "sqlite":
        return SqliteFactorDatabase(zoo_dir)
    raise ValueError(f"Unsupported factor database backend: {backend!r}")
