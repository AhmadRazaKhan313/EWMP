"""The finance migration builds on a fresh database and round-trips."""
import pytest

from tests.test_fresh_database_migrates_postgres import _alembic, _columns, fresh_database  # noqa: F401

TABLES = ("fin_accounts", "fin_journal_entries", "fin_journal_lines", "fin_exchange_rates", "fin_tax_rates")


@pytest.mark.asyncio
async def test_finance_tables_created_and_round_trip(fresh_database):  # noqa: F811
    assert _alembic(fresh_database, "upgrade", "head").returncode == 0
    for t in TABLES:
        assert "tenant_id" in await _columns(fresh_database, t), t
    down = _alembic(fresh_database, "downgrade", "c6e8a0b2d4f7")
    assert down.returncode == 0, down.stderr[-2000:]
    for t in TABLES:
        assert not await _columns(fresh_database, t), t
    up = _alembic(fresh_database, "upgrade", "head")
    assert up.returncode == 0, up.stderr[-2000:]
    assert "debit" in await _columns(fresh_database, "fin_journal_lines")
