"""Tests for discover_service_catalog() — pagination and per_page clamping."""

from __future__ import annotations

from superpos_sdk import SuperposClient

from .conftest import BASE_URL, HIVE_ID, TOKEN


def _service(name: str) -> dict:
    return {
        "id": f"svc-{name}",
        "name": name,
        "service_type": "github",
        "status": "active",
        "capabilities": [],
        "metadata": {},
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
    }


def _envelope(data):
    return {"data": data, "meta": {}, "errors": None}


class TestDiscoverServiceCatalogPerPageClamping:
    def test_per_page_above_100_clamped_to_100(self, httpx_mock):
        """per_page=500 should be clamped to 100.

        Without the fix, the API would silently return only 100 items per
        page and the sentinel ``len(100) < 500`` would be False, making the
        pager think page 1 was the last page and returning only 100 results
        even when more pages exist.

        With the fix, effective_per_page=100 and the pager correctly continues
        to page 2 when a full page is received.
        """
        page1 = [_service(f"svc{i}") for i in range(100)]
        page2 = [_service(f"svc{i}") for i in range(100, 110)]

        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services?status=active&per_page=100&page=1",
            json=_envelope(page1),
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services?status=active&per_page=100&page=2",
            json=_envelope(page2),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=500)

        # Both pages fetched correctly because clamped per_page=100 means
        # len(page1)==100 is not < 100, so page 2 is requested.
        assert len(results) == 110

    def test_per_page_above_100_fetches_multiple_pages_when_needed(self, httpx_mock):
        """When API has more than 100 items and per_page>100, pager should
        keep fetching pages using the clamped value of 100."""
        page1 = [_service(f"svc{i}") for i in range(100)]
        page2 = [_service(f"svc{i}") for i in range(100, 120)]

        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services?status=active&per_page=100&page=1",
            json=_envelope(page1),
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services?status=active&per_page=100&page=2",
            json=_envelope(page2),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=500)

        assert len(results) == 120

    def test_per_page_zero_clamped_to_1(self, httpx_mock):
        """per_page=0 must be clamped to 1 to avoid an infinite loop where
        the API returns 1 item and len([1]) < 0 is always False."""
        page1 = [_service("svc0")]

        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services?status=active&per_page=1&page=1",
            json=_envelope(page1),
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services?status=active&per_page=1&page=2",
            json=_envelope([]),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=0)

        assert len(results) == 1

    def test_per_page_negative_clamped_to_1(self, httpx_mock):
        """per_page=-5 must also be clamped to 1."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services?status=active&per_page=1&page=1",
            json=_envelope([]),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID, per_page=-5)

        assert results == []

    def test_per_page_within_range_unchanged(self, httpx_mock):
        """per_page=50 (default) should be sent as-is."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/services?status=active&per_page=50&page=1",
            json=_envelope([_service("svc0"), _service("svc1")]),
        )

        with SuperposClient(BASE_URL, token=TOKEN) as c:
            results = c.discover_service_catalog(HIVE_ID)

        assert len(results) == 2
