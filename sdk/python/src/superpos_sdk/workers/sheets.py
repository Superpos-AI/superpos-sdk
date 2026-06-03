"""Google Sheets service worker — read and write spreadsheet data.

Install the optional dependency::

    pip install superpos-sdk[sheets]

Credentials (env-first, payload fallback):

- ``GOOGLE_CREDENTIALS`` — JSON string of a Google service account key file,
  or a path to the key file.  Can also be passed per-task as ``credentials``
  in the params dict.

Supported operations
--------------------

``read_range``
    ``{"spreadsheet_id": "...", "range": "Sheet1!A1:C10",
       "value_render_option": "FORMATTED_VALUE"}``

``write_range``
    ``{"spreadsheet_id": "...", "range": "Sheet1!A1",
       "values": [["a", "b"], ["c", "d"]],
       "value_input_option": "USER_ENTERED"}``

``append_rows``
    ``{"spreadsheet_id": "...", "range": "Sheet1!A1",
       "values": [["a", "b"], ["c", "d"]],
       "value_input_option": "USER_ENTERED"}``

``get_spreadsheet``
    ``{"spreadsheet_id": "...", "include_grid_data": false}``
"""

from __future__ import annotations

import json
import os
from typing import Any

from superpos_sdk.service_worker import ServiceWorker

_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class SheetsWorker(ServiceWorker):
    """Service worker that proxies Google Sheets API calls via a service account.

    Credentials are read from the ``GOOGLE_CREDENTIALS`` environment variable
    (JSON string or file path).
    """

    CAPABILITY = "data:sheets"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _creds(self, credentials: str | None = None) -> Any:
        """Return google-auth credentials scoped for Sheets."""
        try:
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "google-auth is required for SheetsWorker. "
                "Install it with: pip install superpos-sdk[sheets]"
            ) from exc

        raw = credentials or os.environ.get("GOOGLE_CREDENTIALS", "")
        if not raw:
            raise ValueError(
                "GOOGLE_CREDENTIALS env var not set. "
                "Set it to a service account JSON string or file path."
            )

        if raw.strip().startswith("{"):
            info = json.loads(raw)
        else:
            with open(raw) as fh:
                info = json.load(fh)

        return service_account.Credentials.from_service_account_info(info, scopes=_SHEETS_SCOPES)

    def _require_credentials(self, credentials: str | None = None) -> None:
        """Raise ValueError early if no credentials are available."""
        if not (credentials or os.environ.get("GOOGLE_CREDENTIALS", "")):
            raise ValueError(
                "GOOGLE_CREDENTIALS env var not set. "
                "Set it to a service account JSON string or file path."
            )

    def _service(self, credentials: str | None = None) -> Any:
        """Build and return a Sheets API service object."""
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "google-api-python-client is required for SheetsWorker. "
                "Install it with: pip install superpos-sdk[sheets]"
            ) from exc

        return build("sheets", "v4", credentials=self._creds(credentials), cache_discovery=False)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def read_range(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read values from a spreadsheet range.

        Args:
            params: Must include ``spreadsheet_id`` and ``range``.  Optional:
                ``value_render_option`` (default ``FORMATTED_VALUE``),
                ``date_time_render_option``.

        Returns:
            Dict with ``values`` (list of rows), ``range``, and
            ``majorDimension``.
        """
        self._require_credentials(params.get("credentials"))
        svc = self._service(params.get("credentials"))
        kwargs: dict[str, Any] = {
            "spreadsheetId": params["spreadsheet_id"],
            "range": params["range"],
            "valueRenderOption": params.get("value_render_option", "FORMATTED_VALUE"),
        }
        if params.get("date_time_render_option"):
            kwargs["dateTimeRenderOption"] = params["date_time_render_option"]

        result = (
            svc.spreadsheets()  # type: ignore[attr-defined]
            .values()
            .get(**kwargs)
            .execute()
        )
        return {
            "values": result.get("values", []),
            "range": result.get("range", ""),
            "major_dimension": result.get("majorDimension", "ROWS"),
        }

    def write_range(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write values to a spreadsheet range.

        Args:
            params: Must include ``spreadsheet_id``, ``range``, and
                ``values``.  Optional: ``value_input_option``
                (default ``USER_ENTERED``).

        Returns:
            Dict with ``updated_range``, ``updated_rows``,
            ``updated_columns``, and ``updated_cells``.
        """
        self._require_credentials(params.get("credentials"))
        svc = self._service(params.get("credentials"))
        body = {
            "range": params["range"],
            "majorDimension": params.get("major_dimension", "ROWS"),
            "values": params["values"],
        }
        result = (
            svc.spreadsheets()  # type: ignore[attr-defined]
            .values()
            .update(
                spreadsheetId=params["spreadsheet_id"],
                range=params["range"],
                valueInputOption=params.get("value_input_option", "USER_ENTERED"),
                body=body,
            )
            .execute()
        )
        return {
            "updated_range": result.get("updatedRange", ""),
            "updated_rows": result.get("updatedRows", 0),
            "updated_columns": result.get("updatedColumns", 0),
            "updated_cells": result.get("updatedCells", 0),
        }

    def append_rows(self, params: dict[str, Any]) -> dict[str, Any]:
        """Append rows to a spreadsheet.

        Args:
            params: Must include ``spreadsheet_id``, ``range``, and
                ``values``.  Optional: ``value_input_option``
                (default ``USER_ENTERED``), ``insert_data_option``
                (default ``INSERT_ROWS``).

        Returns:
            Dict with ``spreadsheet_id``, ``table_range``, and ``updates``.
        """
        self._require_credentials(params.get("credentials"))
        svc = self._service(params.get("credentials"))
        body = {
            "majorDimension": params.get("major_dimension", "ROWS"),
            "values": params["values"],
        }
        result = (
            svc.spreadsheets()  # type: ignore[attr-defined]
            .values()
            .append(
                spreadsheetId=params["spreadsheet_id"],
                range=params["range"],
                valueInputOption=params.get("value_input_option", "USER_ENTERED"),
                insertDataOption=params.get("insert_data_option", "INSERT_ROWS"),
                body=body,
            )
            .execute()
        )
        return {
            "spreadsheet_id": result.get("spreadsheetId", ""),
            "table_range": result.get("tableRange", ""),
            "updates": result.get("updates", {}),
        }

    def get_spreadsheet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch spreadsheet metadata (title, sheets, etc.).

        Args:
            params: Must include ``spreadsheet_id``.  Optional:
                ``include_grid_data`` (bool, default False).

        Returns:
            Sheets API spreadsheet resource dict.
        """
        self._require_credentials(params.get("credentials"))
        svc = self._service(params.get("credentials"))
        result = (
            svc.spreadsheets()  # type: ignore[attr-defined]
            .get(
                spreadsheetId=params["spreadsheet_id"],
                includeGridData=bool(params.get("include_grid_data", False)),
            )
            .execute()
        )
        return result
