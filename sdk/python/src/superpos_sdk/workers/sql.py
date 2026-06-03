"""SQL service worker — execute queries against relational databases.

Install the optional dependency::

    pip install superpos-sdk[sql]

Supported databases (via SQLAlchemy):

- PostgreSQL — ``postgresql+psycopg2://...`` or ``postgresql://...``
- MySQL       — ``mysql+pymysql://...``
- SQLite      — ``sqlite:///path/to/db.sqlite3`` or ``sqlite:///:memory:``
- MS SQL Server — ``mssql+pyodbc://...``

Connection string resolution (highest priority first):

1. ``task["payload"]["params"]["connection_string"]``
2. ``SQL_CONNECTION_STRING`` environment variable

Supported operations
--------------------

``query``
    Execute a SELECT statement and return rows as a list of dicts.

    ``{"connection_string": "sqlite:///:memory:", "sql": "SELECT 1 AS n",
       "params": {}}``

``execute``
    Execute an INSERT / UPDATE / DELETE / DDL statement.

    ``{"connection_string": "...", "sql": "INSERT INTO t VALUES (:v)",
       "params": {"v": 42}}``
"""

from __future__ import annotations

import os
from typing import Any

from superpos_sdk.service_worker import ServiceWorker


class SqlWorker(ServiceWorker):
    """Service worker that executes SQL statements via SQLAlchemy.

    Supports any SQLAlchemy-compatible database.  The connection string is
    taken from *params* first, then the ``SQL_CONNECTION_STRING`` env var.
    """

    CAPABILITY = "data:sql"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _engine(self, connection_string: str):
        """Create and return a SQLAlchemy engine."""
        try:
            from sqlalchemy import create_engine
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "sqlalchemy is required for SqlWorker. "
                "Install it with: pip install superpos-sdk[sql]"
            ) from exc

        return create_engine(connection_string)

    def _connection_string(self, params: dict[str, Any]) -> str:
        cs = params.get("connection_string") or os.environ.get("SQL_CONNECTION_STRING", "")
        if not cs:
            raise ValueError(
                "SQL connection string not found. "
                "Pass connection_string in params or set SQL_CONNECTION_STRING env var."
            )
        return cs

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def query(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a SELECT query and return all rows as dicts.

        Args:
            params: Must include ``sql``.  Optional: ``connection_string``,
                ``params`` (dict of bind parameters).

        Returns:
            Dict with ``rows`` (list of dicts) and ``row_count``.

        Raises:
            ValueError: When ``sql`` is missing or connection string is not
                configured.
            RuntimeError: On SQL execution errors.
        """
        try:
            from sqlalchemy import text
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "sqlalchemy is required for SqlWorker. "
                "Install it with: pip install superpos-sdk[sql]"
            ) from exc

        sql = params.get("sql")
        if not sql:
            raise ValueError("params.sql is required for the 'query' operation")

        cs = self._connection_string(params)
        bind_params = params.get("params") or {}

        engine = self._engine(cs)
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql), bind_params)
                keys = list(result.keys())
                rows = [dict(zip(keys, row)) for row in result.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"SQL query failed: {exc}") from exc
        finally:
            engine.dispose()

        return {"rows": rows, "row_count": len(rows)}

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a non-SELECT statement (INSERT, UPDATE, DELETE, DDL).

        Args:
            params: Must include ``sql``.  Optional: ``connection_string``,
                ``params`` (dict of bind parameters).

        Returns:
            Dict with ``rowcount`` (affected rows, -1 for DDL) and
            ``success``.

        Raises:
            ValueError: When ``sql`` is missing or connection string is not
                configured.
            RuntimeError: On SQL execution errors.
        """
        try:
            from sqlalchemy import text
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "sqlalchemy is required for SqlWorker. "
                "Install it with: pip install superpos-sdk[sql]"
            ) from exc

        sql = params.get("sql")
        if not sql:
            raise ValueError("params.sql is required for the 'execute' operation")

        cs = self._connection_string(params)
        bind_params = params.get("params") or {}

        engine = self._engine(cs)
        try:
            with engine.begin() as conn:
                result = conn.execute(text(sql), bind_params)
                rowcount = result.rowcount
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"SQL execute failed: {exc}") from exc
        finally:
            engine.dispose()

        return {"rowcount": rowcount, "success": True}
