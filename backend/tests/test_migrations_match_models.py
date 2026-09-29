"""
Static drift check between the SQLAlchemy models and the migration chain
(issue #6).

This is what should have caught the bug this fix addresses: `AttendancePunch`
and `AttendanceRegularization` both inherit `TenantModel`, which (via
SoftDeleteMixin) maps a `deleted_at` column in Python — but the migration that
created both tables (a1b2c3d4e5f6) only listed `is_deleted` in its
`create_table()` calls, so the column never existed on Postgres. Every
`select(AttendancePunch)` / `select(AttendanceRegularization)` against a real
database failed outright.

No database connection is used here: this statically parses every migration
file's `create_table` / `add_column` / `drop_column` calls to reconstruct
which columns each table ends up with after the full chain, and compares that
against `Base.metadata` (what the ORM models actually declare). It runs as
part of the normal suite (no Postgres required) specifically so this class of
bug is caught without needing a live database.

Run:  cd backend && pytest tests/test_migrations_match_models.py -v
"""

import ast
import re
import glob
import os

import pytest

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "app", "database", "migrations", "versions"
)


def _column_name(node: ast.AST) -> str | None:
    """If `node` is an `sa.Column("name", ...)` call, its column name."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Column"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ):
        return node.args[0].value
    return None


_RAW_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?\s+"
    r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?",
    re.IGNORECASE,
)
_RAW_DROP_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?\s+"
    r"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?",
    re.IGNORECASE,
)


def _raw_sql_column_changes(call: ast.Call) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """`op.execute("ALTER TABLE t ADD COLUMN IF NOT EXISTS c ...")` — raw SQL is
    how idempotent migrations add columns (c4d8f1a6b3e7, b7d4f1a92c63), so it
    must count too, or those columns look missing from the chain."""
    if not call.args or not isinstance(call.args[0], ast.Constant) or not isinstance(call.args[0].value, str):
        return [], []
    sql = call.args[0].value
    return _RAW_ADD_COLUMN.findall(sql), _RAW_DROP_COLUMN.findall(sql)


def _base_column_helpers(tree: ast.Module) -> dict[str, set[str]]:
    """Some migrations factor shared columns (id/tenant_id/timestamps/soft-delete)
    into a module-level helper — e.g. `def _base_columns(): return [sa.Column(...), ...]`
    — then splat it into create_table as `*_base_columns()`. Resolve those so
    the columns they add are not missed."""
    helpers: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        names: set[str] = set()
        for ret in ast.walk(node):
            if not isinstance(ret, ast.Return):
                continue
            elts = ret.value.elts if isinstance(ret.value, (ast.List, ast.Tuple)) else [ret.value]
            for elt in elts:
                name = _column_name(elt)
                if name:
                    names.add(name)
        if names:
            helpers[node.name] = names
    return helpers


def _columns_added_by_create_table(call: ast.Call, helpers: dict[str, set[str]]) -> set[str]:
    names = set()
    for arg in call.args[1:]:
        name = _column_name(arg)
        if name:
            names.add(name)
            continue
        # *_base_columns() — a starred call to a known same-file helper.
        if isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Call):
            fn = arg.value.func
            fn_name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if fn_name in helpers:
                names |= helpers[fn_name]
    return names


def _reconstruct_schema_from_migrations(migrations_dir: str = MIGRATIONS_DIR) -> dict[str, set[str]]:
    """table_name -> set of column names, after replaying every upgrade() in
    the migrations directory (order does not matter for this purpose: a
    column that exists after ANY create_table/add_column and is not later
    dropped is considered present — good enough to catch a column missing
    from every migration, which is exactly this bug)."""
    schema: dict[str, set[str]] = {}
    files = sorted(glob.glob(os.path.join(migrations_dir, "*.py")))
    assert files, f"no migration files found under {migrations_dir}"

    for path in files:
        tree = ast.parse(open(path, encoding="utf-8").read())
        helpers = _base_column_helpers(tree)
        upgrade_fn = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "upgrade"
            ),
            None,
        )
        if upgrade_fn is None:
            continue
        for node in ast.walk(upgrade_fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            fn = node.func.attr
            if fn == "create_table" and node.args and isinstance(node.args[0], ast.Constant):
                table = node.args[0].value
                schema.setdefault(table, set()).update(_columns_added_by_create_table(node, helpers))
            elif fn == "add_column" and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant):
                table = node.args[0].value
                col_call = node.args[1]
                if (
                    isinstance(col_call, ast.Call)
                    and col_call.args
                    and isinstance(col_call.args[0], ast.Constant)
                ):
                    schema.setdefault(table, set()).add(col_call.args[0].value)
            elif fn == "drop_column" and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant):
                table = node.args[0].value
                if isinstance(node.args[1], ast.Constant):
                    schema.get(table, set()).discard(node.args[1].value)
            elif fn == "drop_table" and node.args and isinstance(node.args[0], ast.Constant):
                schema.pop(node.args[0].value, None)
            elif fn == "execute":
                added, dropped = _raw_sql_column_changes(node)
                for table, column in added:
                    schema.setdefault(table, set()).add(column)
                for table, column in dropped:
                    schema.get(table, set()).discard(column)
    return schema


def _model_metadata() -> dict[str, set[str]]:
    import app.models  # noqa: F401 — registers every model on Base.metadata
    from app.core.database import Base

    return {t.name: {c.name for c in t.columns} for t in Base.metadata.sorted_tables}


class TestMigrationsMatchModels:
    def test_every_mapped_column_exists_somewhere_in_the_migration_chain(self):
        migrated = _reconstruct_schema_from_migrations()
        modeled = _model_metadata()

        missing: dict[str, list[str]] = {}
        for table, columns in modeled.items():
            if table not in migrated:
                continue  # a whole missing table is a different failure mode; see below
            gap = sorted(columns - migrated[table])
            if gap:
                missing[table] = gap

        assert not missing, (
            "Columns the ORM models declare but no migration ever creates "
            f"(this is exactly the bug fixed in c4d8f1a6b3e7): {missing}"
        )

    def test_every_model_table_is_created_by_some_migration(self):
        migrated = _reconstruct_schema_from_migrations()
        modeled = _model_metadata()
        missing_tables = sorted(t for t in modeled if t not in migrated)
        assert not missing_tables, f"Model tables with no create_table in any migration: {missing_tables}"

    # ── the specific two tables this fix targeted ────────────────────────────
    @pytest.mark.parametrize("table", ["attendance_punches", "attendance_regularizations"])
    def test_soft_delete_columns_present(self, table):
        migrated = _reconstruct_schema_from_migrations()
        assert {"deleted_at", "is_deleted"} <= migrated[table]

    def test_reconstruction_catches_a_column_missing_on_purpose(self, tmp_path):
        """Meta-test: prove the static check actually detects a gap, using a
        throwaway migrations dir with a column deliberately left out."""
        d = tmp_path / "versions"
        d.mkdir()
        (d / "0001_only.py").write_text(
            "def upgrade():\n"
            "    import sqlalchemy as sa\n"
            "    from alembic import op\n"
            "    op.create_table('widgets', sa.Column('id', sa.Integer()))\n"
        )
        schema = _reconstruct_schema_from_migrations(str(d))
        assert schema == {"widgets": {"id"}}
        assert "name" not in schema["widgets"]  # the deliberately-missing column
