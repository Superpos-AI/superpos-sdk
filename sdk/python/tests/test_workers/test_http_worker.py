"""Tests for HttpWorker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from superpos_sdk.workers.http import HttpWorker

BASE_URL = "https://superpos.test"
HIVE_ID = "01HXYZ00000000000000000001"


def _worker() -> HttpWorker:
    return HttpWorker(BASE_URL, HIVE_ID, name="http-worker", secret="s3cr3t")


class TestHttpWorkerRequest:
    def _mock_response(
        self,
        *,
        status_code: int = 200,
        text: str = '{"ok": true}',
        headers: dict | None = None,
        elapsed_ms: int = 50,
    ) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        resp.headers = headers or {"content-type": "application/json"}

        elapsed = MagicMock()
        elapsed.total_seconds.return_value = elapsed_ms / 1000.0
        resp.elapsed = elapsed
        return resp

    def test_get_request_returns_expected_shape(self):
        worker = _worker()
        mock_resp = self._mock_response(status_code=200, text="hello")

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = worker.request({"url": "https://example.com", "method": "GET"})

        assert result["status_code"] == 200
        assert result["body"] == "hello"
        assert "content-type" in result["headers"]
        assert isinstance(result["elapsed_ms"], int)

    def test_post_with_dict_body_sends_json(self):
        worker = _worker()
        mock_resp = self._mock_response(status_code=201, text='{"id": 1}')

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = worker.request(
                {
                    "url": "https://example.com/api",
                    "method": "POST",
                    "body": {"key": "value"},
                }
            )
            call_kwargs = mock_client.request.call_args[1]

        assert result["status_code"] == 201
        assert "json" in call_kwargs
        assert call_kwargs["json"] == {"key": "value"}

    def test_post_with_string_body_sends_content(self):
        worker = _worker()
        mock_resp = self._mock_response(status_code=200, text="ok")

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            worker.request(
                {
                    "url": "https://example.com/api",
                    "method": "POST",
                    "body": "raw string body",
                }
            )
            call_kwargs = mock_client.request.call_args[1]

        assert "content" in call_kwargs

    def test_missing_url_raises_value_error(self):
        worker = _worker()
        with pytest.raises(ValueError, match="url is required"):
            worker.request({})

    def test_timeout_forwarded_to_httpx(self):
        worker = _worker()
        mock_resp = self._mock_response()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            worker.request({"url": "https://example.com", "timeout": 10})
            call_kwargs = mock_client.request.call_args[1]

        assert call_kwargs["timeout"] == 10.0

    def test_timeout_error_raises_runtime_error(self):
        import httpx

        worker = _worker()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.side_effect = httpx.TimeoutException("timed out")
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="timed out"):
                worker.request({"url": "https://example.com"})

    def test_connect_error_raises_runtime_error(self):
        import httpx

        worker = _worker()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.side_effect = httpx.ConnectError("refused")
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="Connection error"):
                worker.request({"url": "https://example.com"})

    def test_default_method_is_get(self):
        worker = _worker()
        mock_resp = self._mock_response()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            worker.request({"url": "https://example.com"})
            call_args = mock_client.request.call_args[0]

        assert call_args[0] == "GET"

    def test_custom_headers_forwarded(self):
        worker = _worker()
        mock_resp = self._mock_response()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            worker.request({"url": "https://example.com", "headers": {"X-Custom": "value"}})
            call_kwargs = mock_client.request.call_args[1]

        assert call_kwargs["headers"] == {"X-Custom": "value"}
