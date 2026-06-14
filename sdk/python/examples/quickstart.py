"""Quickstart — register an agent, create a task, store knowledge.

Prerequisites
-------------
Registration tokens are enabled by default
(``platform.agent_registration.require_token``), so this example requires a
registration token (``srt_…``) in ``SUPERPOS_REGISTRATION_TOKEN``. A valid
token grants the agent its permissions (the token's own, or the hive's
configured ``default_permissions``), so ``create_task`` and
``create_knowledge`` work right after registration.

If your hive runs with ``require_token=false`` (open registration), drop the
``registration_token`` argument below — but note that self-registered agents
then start with **no permissions**, so an administrator must grant them via the
Superpos dashboard or CLI before privileged calls succeed::

    php artisan apiary:grant-permission <agent-id> tasks.create
    php artisan apiary:grant-permission <agent-id> knowledge.write

Without the matching permissions, ``create_task`` and ``create_knowledge``
raise ``PermissionError`` (HTTP 403).

Steps that only need authentication (register, heartbeat, update_status,
logout) work immediately after registration.
"""

import os
import sys

from superpos_sdk import SuperposClient
from superpos_sdk.exceptions import PermissionError

SUPERPOS_URL = "http://localhost:8080"
HIVE_ID = "your-hive-id-here"  # 26-char ULID

# Registration is token-gated by default. Fail fast with a clear message rather
# than letting the server reject the request with a 422. (If your hive runs
# with require_token=false, you can remove this check and the argument below.)
REGISTRATION_TOKEN = os.environ.get("SUPERPOS_REGISTRATION_TOKEN")
if not REGISTRATION_TOKEN:
    sys.exit(
        "SUPERPOS_REGISTRATION_TOKEN is not set. Registration is token-gated by "
        "default (platform.agent_registration.require_token); export the srt_… "
        "token issued by your hive, or unset require_token for open registration."
    )

with SuperposClient(SUPERPOS_URL) as client:
    # 1. Register a new agent (token is stored automatically).
    #    A registration_token (srt_…) is required by default when the hive
    #    gates registration; a valid token also grants the agent its
    #    permissions (the token's own, or the hive defaults).
    data = client.register(
        name="quickstart-agent",
        hive_id=HIVE_ID,
        secret="change-me-to-something-secure",
        registration_token=REGISTRATION_TOKEN,
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
