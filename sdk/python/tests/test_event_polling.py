"""Tests for event polling and subscription management."""

from __future__ import annotations

import json

from superpos_sdk import Event, Subscription, SuperposClient

from .conftest import BASE_URL, HIVE_ID, TOKEN, envelope

EVENT_ID_1 = "01HXYZ00000000000000000010"
EVENT_ID_2 = "01HXYZ00000000000000000011"
HIVE_ID_2 = "01HXYZ00000000000000000099"


def _event_data(**overrides):
    base = {
        "id": EVENT_ID_1,
        "organization_id": "A" * 26,
        "hive_id": HIVE_ID,
        "type": "task.completed",
        "source_agent_id": "01HXYZ00000000000000000002",
        "payload": {"task_id": "T1"},
        "is_cross_hive": False,
        "seq": 1,
        "created_at": "2026-03-01T12:00:00Z",
    }
    base.update(overrides)
    return base


def _subscription_data(**overrides):
    base = {
        "agent_id": "01HXYZ00000000000000000002",
        "event_type": "task.completed",
        "scope": "hive",
        "created_at": "2026-03-01T12:00:00Z",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------
# Subscribe
# ------------------------------------------------------------------


class TestSubscribe:
    def test_subscribe(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions",
            method="POST",
            status_code=201,
            json=envelope(_subscription_data()),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            sub = c.subscribe("task.completed")
        assert sub["event_type"] == "task.completed"
        assert sub["scope"] == "hive"
        body = json.loads(httpx_mock.get_request().content)
        assert body["event_type"] == "task.completed"
        assert body["scope"] == "hive"

    def test_subscribe_apiary_scope(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions",
            method="POST",
            status_code=201,
            json=envelope(_subscription_data(scope="apiary")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            sub = c.subscribe("apiary.broadcast", scope="apiary")
        assert sub["scope"] == "apiary"
        body = json.loads(httpx_mock.get_request().content)
        assert body["scope"] == "apiary"


# ------------------------------------------------------------------
# Unsubscribe
# ------------------------------------------------------------------


class TestUnsubscribe:
    def test_unsubscribe(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions/task.completed",
            method="DELETE",
            status_code=204,
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.unsubscribe("task.completed")
        req = httpx_mock.get_request()
        assert req.method == "DELETE"


# ------------------------------------------------------------------
# List subscriptions
# ------------------------------------------------------------------


def _capability_pool_data(**overrides):
    base = {
        "id": "01HXYZ00000000000000000050",
        "organization_id": "A" * 26,
        "hive_id": HIVE_ID,
        "capability": "github.review",
        "event_type": "task.completed",
        "scope": "hive",
        "created_at": "2026-03-01T12:00:00Z",
    }
    base.update(overrides)
    return base


class TestListSubscriptions:
    def test_list_subscriptions(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions",
            method="GET",
            json=envelope(
                [
                    _subscription_data(),
                    _subscription_data(event_type="agent.offline"),
                ]
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            subs = c.list_subscriptions()
        assert len(subs) == 2
        assert subs[0]["event_type"] == "task.completed"
        assert subs[1]["event_type"] == "agent.offline"

    def test_list_capability_pool_subscriptions(self, httpx_mock):
        pools = [
            _capability_pool_data(),
            _capability_pool_data(
                hive_id=None,
                scope="apiary",
                capability="ops.deploy",
                event_type="apiary.broadcast",
            ),
        ]
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions",
            method="GET",
            json=envelope(
                [_subscription_data()],
                meta={
                    "count": 1,
                    "capability_pools": pools,
                    "capability_pool_count": len(pools),
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_capability_pool_subscriptions()
        assert len(result) == 2
        assert result[0]["capability"] == "github.review"
        assert result[0]["scope"] == "hive"
        assert result[1]["scope"] == "apiary"
        assert result[1]["hive_id"] is None

    def test_list_capability_pool_subscriptions_empty_meta(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions",
            method="GET",
            json=envelope([_subscription_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_capability_pool_subscriptions()
        assert result == []

    def test_list_subscriptions_with_pools(self, httpx_mock):
        pools = [_capability_pool_data()]
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions",
            method="GET",
            json=envelope(
                [
                    _subscription_data(),
                    _subscription_data(event_type="agent.offline"),
                ],
                meta={
                    "count": 2,
                    "capability_pools": pools,
                    "capability_pool_count": 1,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_subscriptions_with_pools()
        assert len(result["subscriptions"]) == 2
        assert result["subscriptions"][0]["event_type"] == "task.completed"
        assert len(result["capability_pools"]) == 1
        assert result["capability_pools"][0]["capability"] == "github.review"
        assert result["capability_pool_count"] == 1

    def test_list_subscriptions_with_pools_empty_meta(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions",
            method="GET",
            json=envelope([_subscription_data()]),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.list_subscriptions_with_pools()
        assert len(result["subscriptions"]) == 1
        assert result["capability_pools"] == []
        assert result["capability_pool_count"] == 0


# ------------------------------------------------------------------
# Replace subscriptions
# ------------------------------------------------------------------


class TestReplaceSubscriptions:
    def test_replace_subscriptions(self, httpx_mock):
        new_subs = [
            {"event_type": "task.completed", "scope": "hive"},
            {"event_type": "apiary.deploy", "scope": "apiary"},
        ]
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/subscriptions",
            method="PUT",
            json=envelope(
                [
                    _subscription_data(),
                    _subscription_data(event_type="apiary.deploy", scope="apiary"),
                ]
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            subs = c.replace_subscriptions(new_subs)
        assert len(subs) == 2
        body = json.loads(httpx_mock.get_request().content)
        assert body["subscriptions"] == new_subs


# ------------------------------------------------------------------
# Poll events
# ------------------------------------------------------------------


class TestPollEvents:
    def test_poll_returns_events(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data(), _event_data(id=EVENT_ID_2, seq=2)],
                meta={
                    "count": 2,
                    "has_more": False,
                    "next_cursor": EVENT_ID_2,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            events = c.poll_events(HIVE_ID)
        assert len(events) == 2
        assert isinstance(events[0], Event)
        assert events[0].id == EVENT_ID_1
        assert events[1].id == EVENT_ID_2

    def test_poll_empty(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            events = c.poll_events(HIVE_ID)
        assert events == []

    def test_poll_with_limit(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll?limit=10",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 10,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            events = c.poll_events(HIVE_ID, limit=10)
        assert len(events) == 1

    def test_poll_with_since(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll?since=2026-03-01T00%3A00%3A00Z",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            events = c.poll_events(HIVE_ID, since="2026-03-01T00:00:00Z")
        assert len(events) == 1

    def test_poll_tracks_cursor(self, httpx_mock):
        """Second poll should include last_event_id from the first poll."""
        # First poll — no cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Second poll — should include cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll?last_event_id={EVENT_ID_1}",
            json=envelope(
                [_event_data(id=EVENT_ID_2, seq=2)],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_2,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            first = c.poll_events(HIVE_ID)
            assert len(first) == 1

            second = c.poll_events(HIVE_ID)
            assert len(second) == 1
            assert second[0].id == EVENT_ID_2

    def test_poll_repolls_on_has_more(self, httpx_mock):
        """When has_more is true, poll_events re-polls automatically."""
        # Page 1 — has_more=True
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll?limit=1",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": True,
                    "next_cursor": EVENT_ID_1,
                    "limit": 1,
                },
            ),
        )
        # Page 2 — has_more=False (last page)
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll?last_event_id={EVENT_ID_1}&limit=1",
            json=envelope(
                [_event_data(id=EVENT_ID_2, seq=2)],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_2,
                    "limit": 1,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            events = c.poll_events(HIVE_ID, limit=1)
        assert len(events) == 2
        assert events[0].id == EVENT_ID_1
        assert events[1].id == EVENT_ID_2

    def test_first_poll_no_cursor(self, httpx_mock):
        """First poll without cursor or since should omit both params."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            events = c.poll_events(HIVE_ID)
        assert events == []
        req = httpx_mock.get_request()
        assert b"last_event_id" not in req.url.raw_path
        assert b"since" not in req.url.raw_path

    def test_reset_cursor(self, httpx_mock):
        """After reset_event_cursor, the next poll should not include last_event_id."""
        # First poll — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Second poll — cursor reset, no last_event_id
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.reset_event_cursor()
            c.poll_events(HIVE_ID)

        requests = httpx_mock.get_requests()
        assert len(requests) == 2
        assert b"last_event_id" not in requests[1].url.raw_path

    def test_reset_cursor_per_hive(self, httpx_mock):
        """reset_event_cursor(hive_id) clears only that hive's cursor."""
        # Poll Hive A — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive B — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID_2}/events/poll",
            json=envelope(
                [_event_data(hive_id=HIVE_ID_2)],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_2,
                    "limit": 50,
                },
            ),
        )
        # After resetting only Hive A, poll Hive A — no cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive B — should still have cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID_2}/events/poll?last_event_id={EVENT_ID_2}",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.poll_events(HIVE_ID_2)
            c.reset_event_cursor(HIVE_ID)
            c.poll_events(HIVE_ID)
            c.poll_events(HIVE_ID_2)

        requests = httpx_mock.get_requests()
        assert len(requests) == 4
        # Hive A poll after reset — no cursor
        assert b"last_event_id" not in requests[2].url.raw_path
        # Hive B poll after reset of Hive A — still has cursor
        assert b"last_event_id" in requests[3].url.raw_path


# ------------------------------------------------------------------
# poll_events() returns typed Event objects
# ------------------------------------------------------------------


class TestPollEventsReturnsTypedObjects:
    def test_poll_returns_event_instances(self, httpx_mock):
        """poll_events() must return Event objects, not raw dicts."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={"count": 1, "has_more": False, "next_cursor": EVENT_ID_1, "limit": 50},
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            events = c.poll_events(HIVE_ID)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, Event)
        assert event.id == EVENT_ID_1
        assert event.type == "task.completed"
        assert event.payload == {"task_id": "T1"}
        assert event.source_agent_id == "01HXYZ00000000000000000002"
        assert event.hive_id == HIVE_ID
        assert event.is_cross_hive is False
        assert event.seq == 1
        assert event.created_at == "2026-03-01T12:00:00Z"

    def test_poll_with_meta_returns_raw_dicts(self, httpx_mock):
        """poll_events_with_meta() returns raw envelope with dict events."""
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={"count": 1, "has_more": False, "next_cursor": EVENT_ID_1, "limit": 50},
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.poll_events_with_meta(HIVE_ID)
        assert isinstance(result["data"][0], dict)
        assert result["data"][0]["id"] == EVENT_ID_1


# ------------------------------------------------------------------
# Per-hive cursor isolation
# ------------------------------------------------------------------


class TestPerHiveCursorIsolation:
    def test_cursors_are_independent_per_hive(self, httpx_mock):
        """Polling Hive A then Hive B: Hive B's first poll has no cursor from Hive A."""
        # Poll Hive A — sets cursor EVENT_ID_1
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive B — first poll, should have no cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID_2}/events/poll",
            json=envelope(
                [_event_data(hive_id=HIVE_ID_2)],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_2,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.poll_events(HIVE_ID_2)

        requests = httpx_mock.get_requests()
        assert len(requests) == 2
        # Hive B's first poll must NOT include last_event_id from Hive A
        assert b"last_event_id" not in requests[1].url.raw_path

    def test_cursor_tracks_separately(self, httpx_mock):
        """Poll Hive A (cursor X), poll Hive B (cursor Y), poll Hive A again — uses cursor X."""
        # Poll Hive A — sets cursor EVENT_ID_1
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive B — sets cursor EVENT_ID_2
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID_2}/events/poll",
            json=envelope(
                [_event_data(hive_id=HIVE_ID_2, id=EVENT_ID_2)],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_2,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive A again — should use EVENT_ID_1, not EVENT_ID_2
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll?last_event_id={EVENT_ID_1}",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.poll_events(HIVE_ID_2)
            c.poll_events(HIVE_ID)

        requests = httpx_mock.get_requests()
        assert len(requests) == 3
        # Third request (Hive A again) must use EVENT_ID_1 as cursor
        assert f"last_event_id={EVENT_ID_1}".encode() in requests[2].url.raw_path

    def test_reset_single_hive_cursor(self, httpx_mock):
        """Reset only Hive A's cursor — Hive B's cursor remains."""
        # Poll Hive A — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive B — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID_2}/events/poll",
            json=envelope(
                [_event_data(hive_id=HIVE_ID_2, id=EVENT_ID_2)],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_2,
                    "limit": 50,
                },
            ),
        )
        # After reset(HIVE_ID), poll Hive A — no cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive B — should still have cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID_2}/events/poll?last_event_id={EVENT_ID_2}",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.poll_events(HIVE_ID_2)
            c.reset_event_cursor(HIVE_ID)
            c.poll_events(HIVE_ID)
            c.poll_events(HIVE_ID_2)

        requests = httpx_mock.get_requests()
        assert len(requests) == 4
        # Hive A after reset — no cursor
        assert b"last_event_id" not in requests[2].url.raw_path
        # Hive B after Hive A reset — still has cursor
        assert b"last_event_id" in requests[3].url.raw_path

    def test_reset_all_cursors(self, httpx_mock):
        """Reset all cursors — both hives poll without cursor."""
        # Poll Hive A — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive B — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID_2}/events/poll",
            json=envelope(
                [_event_data(hive_id=HIVE_ID_2, id=EVENT_ID_2)],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_2,
                    "limit": 50,
                },
            ),
        )
        # After reset_all, poll Hive A — no cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        # Poll Hive B — also no cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID_2}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.poll_events(HIVE_ID_2)
            c.reset_event_cursor()
            c.poll_events(HIVE_ID)
            c.poll_events(HIVE_ID_2)

        requests = httpx_mock.get_requests()
        assert len(requests) == 4
        # Both polls after reset — no cursor
        assert b"last_event_id" not in requests[2].url.raw_path
        assert b"last_event_id" not in requests[3].url.raw_path


# ------------------------------------------------------------------
# Poll events with meta
# ------------------------------------------------------------------


class TestPollEventsWithMeta:
    def test_returns_full_envelope(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            result = c.poll_events_with_meta(HIVE_ID)
        assert "data" in result
        assert "meta" in result
        assert result["meta"]["next_cursor"] == EVENT_ID_1

    def test_updates_cursor(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll?last_event_id={EVENT_ID_1}",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events_with_meta(HIVE_ID)
            c.poll_events_with_meta(HIVE_ID)
        requests = httpx_mock.get_requests()
        assert len(requests) == 2


# ------------------------------------------------------------------
# Publish event
# ------------------------------------------------------------------


class TestPublishEvent:
    def test_publish_event(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events",
            method="POST",
            status_code=201,
            json=envelope(_event_data(type="task.started")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            event = c.publish_event(HIVE_ID, event_type="task.started")
        assert event["type"] == "task.started"
        body = json.loads(httpx_mock.get_request().content)
        assert body["type"] == "task.started"

    def test_publish_event_with_payload(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events",
            method="POST",
            status_code=201,
            json=envelope(
                _event_data(
                    type="deploy.complete",
                    payload={"version": "1.2.3"},
                )
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            event = c.publish_event(
                HIVE_ID,
                event_type="deploy.complete",
                payload={"version": "1.2.3"},
            )
        assert event["payload"]["version"] == "1.2.3"
        body = json.loads(httpx_mock.get_request().content)
        assert body["type"] == "deploy.complete"
        assert body["payload"] == {"version": "1.2.3"}

    def test_publish_event_without_payload(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events",
            method="POST",
            status_code=201,
            json=envelope(_event_data(type="ping")),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.publish_event(HIVE_ID, event_type="ping")
        body = json.loads(httpx_mock.get_request().content)
        assert body["type"] == "ping"
        assert "payload" not in body


# ------------------------------------------------------------------
# Model data classes
# ------------------------------------------------------------------


class TestEventModel:
    def test_from_dict(self):
        data = _event_data()
        event = Event.from_dict(data)
        assert event.id == EVENT_ID_1
        assert event.type == "task.completed"
        assert event.payload == {"task_id": "T1"}
        assert event.source_agent_id == "01HXYZ00000000000000000002"
        assert event.hive_id == HIVE_ID
        assert event.is_cross_hive is False
        assert event.seq == 1
        assert event.created_at == "2026-03-01T12:00:00Z"

    def test_from_dict_with_invoke(self):
        data = _event_data(invoke={"instructions": "do something"})
        event = Event.from_dict(data)
        assert event.invoke == {"instructions": "do something"}

    def test_from_dict_minimal(self):
        data = {"id": "E1", "type": "test"}
        event = Event.from_dict(data)
        assert event.id == "E1"
        assert event.type == "test"
        assert event.payload == {}
        assert event.source_agent_id is None
        assert event.is_cross_hive is False


# ------------------------------------------------------------------
# Cursor reset on identity change
# ------------------------------------------------------------------


class TestCursorResetOnIdentityChange:
    def test_register_resets_cursor(self, httpx_mock):
        """After register(), the event cursor should be cleared."""
        # First poll — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Register as a new agent
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/register",
            method="POST",
            status_code=201,
            json=envelope({"agent": {"id": "NEW_AGENT"}, "token": "new-token"}),
        )
        # Second poll — cursor should be cleared
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.register(
                name="new-agent",
                hive_id=HIVE_ID,
                secret="s3cret",
                agent_type="worker",
            )
            c.poll_events(HIVE_ID)

        requests = httpx_mock.get_requests()
        poll_requests = [r for r in requests if b"/events/poll" in r.url.raw_path]
        assert len(poll_requests) == 2
        assert b"last_event_id" not in poll_requests[1].url.raw_path

    def test_login_resets_cursor(self, httpx_mock):
        """After login(), the event cursor should be cleared."""
        # First poll — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Login as a different agent
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/login",
            method="POST",
            json=envelope({"agent": {"id": "NEW_AGENT"}, "token": "new-token"}),
        )
        # Second poll — cursor should be cleared
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.login(agent_id="NEW_AGENT", secret="s3cret")
            c.poll_events(HIVE_ID)

        requests = httpx_mock.get_requests()
        poll_requests = [r for r in requests if b"/events/poll" in r.url.raw_path]
        assert len(poll_requests) == 2
        assert b"last_event_id" not in poll_requests[1].url.raw_path

    def test_logout_resets_cursor(self, httpx_mock):
        """After logout(), the event cursor should be cleared."""
        # First poll — sets cursor
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [_event_data()],
                meta={
                    "count": 1,
                    "has_more": False,
                    "next_cursor": EVENT_ID_1,
                    "limit": 50,
                },
            ),
        )
        # Logout
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/agents/logout",
            method="POST",
            status_code=204,
        )
        # Second poll — cursor should be cleared (re-set token first)
        httpx_mock.add_response(
            url=f"{BASE_URL}/api/v1/hives/{HIVE_ID}/events/poll",
            json=envelope(
                [],
                meta={
                    "count": 0,
                    "has_more": False,
                    "next_cursor": None,
                    "limit": 50,
                },
            ),
        )
        with SuperposClient(BASE_URL, token=TOKEN) as c:
            c.poll_events(HIVE_ID)
            c.logout()
            # Re-set token so we can poll again
            c.token = TOKEN
            c.poll_events(HIVE_ID)

        requests = httpx_mock.get_requests()
        poll_requests = [r for r in requests if b"/events/poll" in r.url.raw_path]
        assert len(poll_requests) == 2
        assert b"last_event_id" not in poll_requests[1].url.raw_path


class TestSubscriptionModel:
    def test_from_dict(self):
        data = _subscription_data()
        sub = Subscription.from_dict(data)
        assert sub.agent_id == "01HXYZ00000000000000000002"
        assert sub.event_type == "task.completed"
        assert sub.scope == "hive"
        assert sub.created_at == "2026-03-01T12:00:00Z"

    def test_from_dict_minimal(self):
        data = {"agent_id": "A1", "event_type": "test"}
        sub = Subscription.from_dict(data)
        assert sub.agent_id == "A1"
        assert sub.event_type == "test"
        assert sub.scope == "hive"
        assert sub.created_at is None
