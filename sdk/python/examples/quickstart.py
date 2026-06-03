"""Quickstart — register an agent, create a task, store knowledge.

Prerequisites
-------------
Freshly registered agents have **no permissions** by default.
Before running this example an administrator must grant the required
permissions via the Superpos dashboard or CLI::

    php artisan apiary:grant-permission <agent-id> tasks.create
    php artisan apiary:grant-permission <agent-id> knowledge.write

Without these grants, ``create_task`` and ``create_knowledge`` will
raise ``PermissionError`` (HTTP 403).

Steps that only need authentication (register, heartbeat, update_status,
logout) work immediately after registration.
"""

from superpos_sdk import SuperposClient
from superpos_sdk.exceptions import PermissionError

SUPERPOS_URL = "http://localhost:8080"
HIVE_ID = "your-hive-id-here"  # 26-char ULID

with SuperposClient(SUPERPOS_URL) as client:
    # 1. Register a new agent (token is stored automatically)
    #    This always succeeds — no special permissions needed.
    data = client.register(
        name="quickstart-agent",
        hive_id=HIVE_ID,
        secret="change-me-to-something-secure",
        capabilities=["summarize", "translate"],
    )
    agent_id = data["agent"]["id"]
    print(f"Registered as {agent_id}")

    # 2. Send a heartbeat (no extra permissions required)
    client.heartbeat()

    # 3. Create a task for another agent to pick up
    #    Requires permission: tasks.create
    try:
        task = client.create_task(
            HIVE_ID,
            task_type="summarize",
            payload={"url": "https://example.com/article"},
        )
        print(f"Created task {task['id']} (status={task['status']})")
    except PermissionError:
        print(
            f"Skipped task creation — agent {agent_id} lacks 'tasks.create' "
            "permission. Grant it via the dashboard or CLI, then retry."
        )

    # 4. Store a knowledge entry
    #    Requires permission: knowledge.write
    try:
        entry = client.create_knowledge(
            HIVE_ID,
            key="config.default_language",
            value={"lang": "en", "fallback": "es"},
        )
        print(f"Stored knowledge entry {entry['id']} v{entry['version']}")
    except PermissionError:
        print(
            f"Skipped knowledge write — agent {agent_id} lacks "
            "'knowledge.write' permission. Grant it via the dashboard or CLI."
        )

    # 5. Clean up
    client.update_status("offline")
    client.logout()
