"""Shared fixtures for SDK tests."""

from __future__ import annotations

import pytest

from superpos_sdk import SuperposClient

BASE_URL = "https://superpos.test"
HIVE_ID = "01HXYZ00000000000000000001"
AGENT_ID = "01HXYZ00000000000000000002"
TASK_ID = "01HXYZ00000000000000000003"
ENTRY_ID = "01HXYZ00000000000000000004"
TOKEN = "test-token-abc123"


@pytest.fixture()
def client():
    c = SuperposClient(BASE_URL)
    yield c
    c.close()


@pytest.fixture()
def authed_client():
    c = SuperposClient(BASE_URL, token=TOKEN)
    yield c
    c.close()


def envelope(data=None, *, meta=None, errors=None):
    """Build an Superpos API envelope dict."""
    return {
        "data": data,
        "meta": meta or {},
        "errors": errors,
    }
