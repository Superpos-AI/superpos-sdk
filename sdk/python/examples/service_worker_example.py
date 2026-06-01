"""service_worker_example.py — Minimal custom service worker.

Demonstrates the ServiceWorker base class pattern: inherit, declare
CAPABILITY, implement operation methods, and call .run().

Usage:
    export SUPERPOS_BASE_URL="http://localhost:8080"
    export HIVE_ID="01HXYZ..."
    export AGENT_SECRET="your-secret"
    python examples/service_worker_example.py

To request data from this worker (from any agent):
    task = client.data_request(
        hive_id,
        capability="data:crm",
        operation="fetch_contacts",
        params={"filter": "active"},
    )
"""

import logging
import os

from superpos_sdk import ServiceWorker, SuperposClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

SUPERPOS_URL = os.environ.get("SUPERPOS_BASE_URL", "http://localhost:8080")
HIVE_ID = os.environ["HIVE_ID"]
AGENT_SECRET = os.environ["AGENT_SECRET"]


# ── Option A: subclass pattern ────────────────────────────────────────


class CrmWorker(ServiceWorker):
    """Example service worker that bridges a (fake) CRM system."""

    CAPABILITY = "data:crm"

    # Each public method becomes an operation handler.
    # The method name maps to the operation name (underscores ↔ hyphens).

    def fetch_contacts(self, params: dict) -> dict:
        """Return contacts from the CRM system."""
        # Replace with real CRM SDK calls.
        status_filter = params.get("filter", "all")
        contacts = [
            {"id": "c1", "name": "Alice", "status": "active"},
            {"id": "c2", "name": "Bob", "status": "inactive"},
        ]
        if status_filter != "all":
            contacts = [c for c in contacts if c["status"] == status_filter]
        return {
            "data": contacts,
            "metadata": {"count": len(contacts), "filter": status_filter},
        }

    def search_deals(self, params: dict) -> dict:
        """Search deals by keyword."""
        query = params.get("query", "")
        deals = [
            {"id": "d1", "title": "Enterprise License", "value": 50000},
            {"id": "d2", "title": "Support Contract", "value": 12000},
        ]
        results = [d for d in deals if query.lower() in d["title"].lower()]
        return {"data": results, "metadata": {"count": len(results), "query": query}}


# ── Option B: composition pattern (no subclass) ───────────────────────


def run_with_composition():
    """Alternative: register handlers without subclassing."""
    worker = ServiceWorker(
        base_url=SUPERPOS_URL,
        hive_id=HIVE_ID,
        name="crm-worker-v2",
        secret=AGENT_SECRET,
    )

    def fetch_contacts(params: dict) -> dict:
        return {"data": [], "metadata": {"count": 0}}

    worker.register_operation("fetch_contacts", fetch_contacts)
    worker.run()


# ── Sending a data_request (from a regular agent) ────────────────────


def send_request_example():
    """Show how any agent requests data from the CRM worker."""
    client = SuperposClient(SUPERPOS_URL, token=os.environ.get("AGENT_TOKEN", ""))

    # Fire and forget — returns immediately with a task ID.
    ref = client.data_request(
        HIVE_ID,
        capability="data:crm",
        operation="fetch_contacts",
        params={"filter": "active"},
    )
    print(f"Data request created: {ref['id']} (status={ref['status']})")

    # Check the result on the next poll cycle:
    # task = client._request("GET", f"/api/v1/hives/{HIVE_ID}/tasks/{ref['id']}")
    # if task["status"] == "completed":
    #     contacts = task["result"]["data"]

    # Discover available service workers:
    services = client.discover_services(HIVE_ID)
    for svc in services:
        ops = svc.get("metadata", {}).get("supported_operations", [])
        op_names = [o["name"] for o in ops] if ops else []
        print(f"  {svc['name']} ({svc.get('capabilities')}) — ops: {op_names}")

    client.close()


if __name__ == "__main__":
    worker = CrmWorker(
        base_url=SUPERPOS_URL,
        hive_id=HIVE_ID,
        name="crm-worker",
        secret=AGENT_SECRET,
    )
    worker.run()
