"""Tests for SheetsWorker."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from superpos_sdk.workers.sheets import SheetsWorker

BASE_URL = "https://superpos.test"
HIVE_ID = "01HXYZ00000000000000000001"

FAKE_CREDS_JSON = json.dumps(
    {
        "type": "service_account",
        "project_id": "test",
        "private_key_id": "key1",
        "private_key": (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xHn/ygWep4PAtesbbOl2n1nOHb0m5ueEMrwV\n"
            "-----END RSA PRIVATE KEY-----\n"
        ),
        "client_email": "test@test.iam.gserviceaccount.com",
        "client_id": "123456",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)

SPREADSHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"


def _worker() -> SheetsWorker:
    return SheetsWorker(BASE_URL, HIVE_ID, name="sheets-worker", secret="s3cr3t")


def _mock_service():
    svc = MagicMock()
    return svc


class TestSheetsWorkerCredentials:
    def test_missing_credentials_raises(self):
        worker = _worker()
        with pytest.raises(ValueError, match="GOOGLE_CREDENTIALS"):
            worker.read_range({"spreadsheet_id": SPREADSHEET_ID, "range": "A1:B2"})

    def test_env_credentials_used(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        fake_svc = MagicMock()
        get_exec = fake_svc.spreadsheets.return_value.values.return_value.get.return_value.execute
        get_exec.return_value = {"values": [["a", "b"]], "range": "A1:B1", "majorDimension": "ROWS"}
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.read_range({"spreadsheet_id": SPREADSHEET_ID, "range": "A1:B1"})

        assert result["values"] == [["a", "b"]]

    def test_payload_credentials_override(self, monkeypatch):
        """Credentials passed in params take precedence over env vars."""
        monkeypatch.setenv("GOOGLE_CREDENTIALS", "env-value-that-should-not-be-used")
        worker = _worker()

        captured = {}

        def fake_service(credentials=None):
            captured["credentials"] = credentials
            svc = MagicMock()
            get_exec = svc.spreadsheets.return_value.values.return_value.get.return_value.execute
            get_exec.return_value = {"values": [], "range": "A1", "majorDimension": "ROWS"}
            return svc

        with patch.object(worker, "_service", side_effect=fake_service):
            worker.read_range(
                {
                    "spreadsheet_id": SPREADSHEET_ID,
                    "range": "A1",
                    "credentials": FAKE_CREDS_JSON,
                }
            )

        assert captured["credentials"] == FAKE_CREDS_JSON


class TestSheetsWorkerReadRange:
    def test_read_range_returns_shape(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        fake_svc = MagicMock()
        get_exec = fake_svc.spreadsheets.return_value.values.return_value.get.return_value.execute
        get_exec.return_value = {
            "values": [["Name", "Age"], ["Alice", "30"]],
            "range": "Sheet1!A1:B2",
            "majorDimension": "ROWS",
        }
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.read_range({"spreadsheet_id": SPREADSHEET_ID, "range": "Sheet1!A1:B2"})

        assert result["values"] == [["Name", "Age"], ["Alice", "30"]]
        assert result["range"] == "Sheet1!A1:B2"
        assert result["major_dimension"] == "ROWS"

    def test_read_range_empty_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        fake_svc = MagicMock()
        get_exec = fake_svc.spreadsheets.return_value.values.return_value.get.return_value.execute
        get_exec.return_value = {}
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.read_range({"spreadsheet_id": SPREADSHEET_ID, "range": "A1:Z100"})

        assert result["values"] == []


class TestSheetsWorkerWriteRange:
    def test_write_range_returns_update_stats(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        fake_svc = MagicMock()
        upd_chain = fake_svc.spreadsheets.return_value.values.return_value.update.return_value
        upd_exec = upd_chain.execute
        upd_exec.return_value = {
            "updatedRange": "Sheet1!A1:B2",
            "updatedRows": 2,
            "updatedColumns": 2,
            "updatedCells": 4,
        }
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.write_range(
                {
                    "spreadsheet_id": SPREADSHEET_ID,
                    "range": "Sheet1!A1",
                    "values": [["a", "b"], ["c", "d"]],
                }
            )

        assert result["updated_rows"] == 2
        assert result["updated_cells"] == 4


class TestSheetsWorkerAppendRows:
    def test_append_rows_returns_shape(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        fake_svc = MagicMock()
        app_chain = fake_svc.spreadsheets.return_value.values.return_value.append.return_value
        app_exec = app_chain.execute
        app_exec.return_value = {
            "spreadsheetId": SPREADSHEET_ID,
            "tableRange": "Sheet1!A1:B5",
            "updates": {"updatedRows": 2},
        }
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.append_rows(
                {
                    "spreadsheet_id": SPREADSHEET_ID,
                    "range": "Sheet1!A1",
                    "values": [["e", "f"]],
                }
            )

        assert result["spreadsheet_id"] == SPREADSHEET_ID
        assert result["updates"]["updatedRows"] == 2


class TestSheetsWorkerGetSpreadsheet:
    def test_get_spreadsheet_returns_resource(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        metadata = {
            "spreadsheetId": SPREADSHEET_ID,
            "properties": {"title": "My Sheet"},
            "sheets": [],
        }
        fake_svc = MagicMock()
        fake_svc.spreadsheets.return_value.get.return_value.execute.return_value = metadata
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.get_spreadsheet({"spreadsheet_id": SPREADSHEET_ID})

        assert result["spreadsheetId"] == SPREADSHEET_ID
        assert result["properties"]["title"] == "My Sheet"
