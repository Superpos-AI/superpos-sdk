"""Tests for SqlWorker — uses SQLite in-memory for real SQL execution."""

from __future__ import annotations

import pytest

from superpos_sdk.workers.sql import SqlWorker

BASE_URL = "https://superpos.test"
HIVE_ID = "01HXYZ00000000000000000001"
SQLITE_CS = "sqlite:///:memory:"


def _worker() -> SqlWorker:
    return SqlWorker(BASE_URL, HIVE_ID, name="sql-worker", secret="s3cr3t")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def populated_db():
    """Create a fresh SQLite in-memory DB with a test table and return the CS."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        pytest.skip("sqlalchemy not installed")

    # We can't return an in-memory engine directly because each connection
    # to sqlite:///:memory: creates a new database.  Use a file-based temp DB
    # via pytest tmp_path, or use the special check_same_thread=False + static
    # singleton approach.  For simplicity, pre-populate via the worker itself
    # and use the same connection string — SQLite :memory: creates the same
    # DB within one process as long as we use the same URL when using
    # connect_args.  The simplest approach: use a named temp file.
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name

    cs = f"sqlite:///{path}"
    engine = create_engine(cs)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)"))
        conn.execute(text("INSERT INTO items (name, value) VALUES ('alpha', 1)"))
        conn.execute(text("INSERT INTO items (name, value) VALUES ('beta', 2)"))
    engine.dispose()
    return cs


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestSqlWorkerQuery:
    def test_query_returns_rows_as_dicts(self, populated_db):
        worker = _worker()
        result = worker.query({"connection_string": populated_db, "sql": "SELECT * FROM items"})

        assert result["row_count"] == 2
        rows = result["rows"]
        assert isinstance(rows, list)
        assert rows[0]["name"] == "alpha"
        assert rows[0]["value"] == 1

    def test_query_with_bind_params(self, populated_db):
        worker = _worker()
        result = worker.query(
            {
                "connection_string": populated_db,
                "sql": "SELECT * FROM items WHERE name = :n",
                "params": {"n": "beta"},
            }
        )

        assert result["row_count"] == 1
        assert result["rows"][0]["value"] == 2

    def test_query_no_rows(self, populated_db):
        worker = _worker()
        result = worker.query(
            {
                "connection_string": populated_db,
                "sql": "SELECT * FROM items WHERE value > 999",
            }
        )

        assert result["row_count"] == 0
        assert result["rows"] == []

    def test_query_missing_sql_raises(self):
        worker = _worker()
        with pytest.raises(ValueError, match="sql is required"):
            worker.query({"connection_string": SQLITE_CS})

    def test_query_missing_connection_string_raises(self):
        worker = _worker()
        with pytest.raises(ValueError, match="connection string"):
            worker.query({"sql": "SELECT 1"})

    def test_query_sql_error_raises_runtime(self):
        worker = _worker()
        with pytest.raises(RuntimeError, match="SQL query failed"):
            worker.query({"connection_string": SQLITE_CS, "sql": "SELECT * FROM nonexistent"})


# ---------------------------------------------------------------------------
# Execute tests
# ---------------------------------------------------------------------------


class TestSqlWorkerExecute:
    def test_execute_insert_returns_rowcount(self, populated_db):
        worker = _worker()
        result = worker.execute(
            {
                "connection_string": populated_db,
                "sql": "INSERT INTO items (name, value) VALUES (:n, :v)",
                "params": {"n": "gamma", "v": 3},
            }
        )

        assert result["success"] is True
        assert result["rowcount"] == 1

    def test_execute_update_returns_rowcount(self, populated_db):
        worker = _worker()
        result = worker.execute(
            {
                "connection_string": populated_db,
                "sql": "UPDATE items SET value = 99 WHERE name = :n",
                "params": {"n": "alpha"},
            }
        )

        assert result["rowcount"] == 1
        assert result["success"] is True

    def test_execute_delete_returns_rowcount(self, populated_db):
        worker = _worker()
        result = worker.execute(
            {
                "connection_string": populated_db,
                "sql": "DELETE FROM items WHERE name = :n",
                "params": {"n": "beta"},
            }
        )

        assert result["rowcount"] == 1

    def test_execute_missing_sql_raises(self):
        worker = _worker()
        with pytest.raises(ValueError, match="sql is required"):
            worker.execute({"connection_string": SQLITE_CS})

    def test_execute_sql_error_raises_runtime(self):
        worker = _worker()
        with pytest.raises(RuntimeError, match="SQL execute failed"):
            worker.execute(
                {"connection_string": SQLITE_CS, "sql": "INSERT INTO nonexistent VALUES (1)"}
            )

    def test_connection_string_from_env(self, monkeypatch, populated_db):
        monkeypatch.setenv("SQL_CONNECTION_STRING", populated_db)
        worker = _worker()
        result = worker.query({"sql": "SELECT COUNT(*) AS cnt FROM items"})
        assert result["row_count"] == 1
        assert result["rows"][0]["cnt"] == 2
