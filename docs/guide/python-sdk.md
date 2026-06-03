# Python SDK

The `superpos-sdk` package provides a minimal Python client for the Superpos v1 API.
It wraps agent authentication, task lifecycle, and knowledge store operations
with typed error handling.

## Installation

```bash
# From the repository root
pip install -e sdk/python

# Or from the SDK directory
cd sdk/python && pip install -e .
```

**Requirements:** Python 3.10+. The only runtime dependency is [httpx](https://www.python-httpx.org/).

## Permissions

Freshly registered agents have **no permissions** by default and cannot access
privileged endpoints. An administrator must grant the required permissions
before the agent can create tasks, write knowledge, etc.

| Endpoint | Required permission |
|----------|---------------------|
| `create_task` | `tasks.create` |
| `claim_task` | `tasks.claim` |
| `complete_task` / `fail_task` / `update_progress` | `tasks.update` |
| `create_knowledge` / `update_knowledge` / `delete_knowledge` | `knowledge.write` (+ `knowledge.write_apiary` for apiary-scoped entries) |
| `list_knowledge` / `search_knowledge` / `get_knowledge` | `knowledge.read` |

Grant permissions via the Superpos dashboard or CLI:

```bash
php artisan apiary:grant-permission <agent-id> tasks.create
php artisan apiary:grant-permission <agent-id> knowledge.write
```

Endpoints that only require authentication (register, login, heartbeat,
`update_status`, `me`, `logout`) work immediately after registration.

Calling a privileged endpoint without the required permission raises
`PermissionError` (HTTP 403).

## Quick start

> **Note:** The example below assumes the agent has been granted `tasks.create`
> permission. Without it, `create_task` will raise `PermissionError`.

```python
from superpos_sdk import SuperposClient

with SuperposClient("http://localhost:8080") as client:
    # Register a new agent (token is stored automatically)
    data = client.register(
        name="my-agent",
        hive_id="01HXYZ...",
        secret="my-secure-secret-16+",
        capabilities=["code", "summarize"],
    )

    # Create a task (requires tasks.create permission)
    task = client.create_task(
        "01HXYZ...",
        task_type="summarize",
        payload={"text": "Hello world"},
        invoke_instructions="Fix failing checks and report back",
        invoke_context={"repo": "Superpos-AI/superpos-sdk", "pr": 123},
    )
    print(f"Task {task['id']} created")
```

## Authentication

The SDK supports two auth flows:

### Register a new agent

```python
client = SuperposClient("http://localhost:8080")
data = client.register(
    name="my-agent",
    hive_id="01HXYZ...",
    secret="change-me-to-something-secure",
)
# client.token is now set — all subsequent calls are authenticated
```

### Login with existing credentials

```python
client = SuperposClient("http://localhost:8080")
client.login(agent_id="01HXYZ...", secret="my-secret")
```

### Pre-configured token

```python
client = SuperposClient("http://localhost:8080", token="your-bearer-token")
```

## Agent lifecycle

```python
# Send heartbeat (call periodically to stay "online")
client.heartbeat(metadata={"cpu": 42, "memory_mb": 512})

# Update status
client.update_status("busy")   # online | busy | idle | offline | error

# Get own profile
agent = client.me()
```

## Task operations

> Requires `tasks.create`, `tasks.claim`, and/or `tasks.update` permissions
> depending on the operation. See [Permissions](#permissions).

### Create a task

```python
task = client.create_task(
    hive_id,
    task_type="process",
    priority=3,                         # 0 (highest) to 4 (lowest)
    target_capability="code",          # optional: route to capable agents
    payload={"input": "data"},
    invoke_instructions="Fix failing checks and report back",
    invoke_context={"repo": "Superpos-AI/superpos-sdk", "pr": 123},
    timeout_seconds=300,
    max_retries=5,
)
```

`invoke_instructions` / `invoke_context` map to canonical top-level
`invoke.instructions` / `invoke.context`.

Mixed-mode compatibility is preserved: legacy `payload["invoke"]` is still accepted,
but when both are present the top-level `invoke.*` values win per field.

### Poll, claim, and complete

```python
# Poll for available tasks
tasks = client.poll_tasks(hive_id, capability="code", limit=5)

if tasks:
    # Atomically claim a task (409 if already claimed)
    task = client.claim_task(hive_id, tasks[0]["id"])

    # Report progress (0–100)
    client.update_progress(hive_id, task["id"], progress=50, status_message="Halfway")

    # Complete with result
    client.complete_task(hive_id, task["id"], result={"output": "done"})
```

### Mark a task as failed

```python
client.fail_task(
    hive_id,
    task["id"],
    error={"type": "ValueError", "message": "Bad input"},
    status_message="Unhandled error",
)
```

## Knowledge store

> Requires `knowledge.read` and/or `knowledge.write` permissions
> depending on the operation. Apiary-scoped writes also require
> `knowledge.write_apiary`. See [Permissions](#permissions).

```python
# Create
entry = client.create_knowledge(
    hive_id,
    key="config.timeout",
    value={"seconds": 30},
    scope="hive",               # hive | apiary | agent:{id}
    visibility="public",        # public | private
    ttl="2026-12-31T23:59:59Z", # optional expiry
)

# Read
entry = client.get_knowledge(hive_id, entry["id"])

# List with filters
entries = client.list_knowledge(hive_id, key="config.*", scope="hive", limit=10)

# Search
results = client.search_knowledge(hive_id, q="timeout")

# Update (bumps version)
client.update_knowledge(hive_id, entry["id"], value={"seconds": 60})

# Delete
client.delete_knowledge(hive_id, entry["id"])
```

## Error handling

All API errors map to typed exceptions with structured error details:

```python
from superpos_sdk import SuperposError, ValidationError, AuthenticationError
from superpos_sdk.exceptions import ConflictError, NotFoundError

try:
    client.claim_task(hive_id, task_id)
except ConflictError as e:
    print(f"Task already claimed: {e}")
except AuthenticationError:
    print("Token expired — re-authenticate")
except SuperposError as e:
    print(f"API error {e.status_code}: {e}")
    for err in e.errors:
        print(f"  [{err.code}] {err.message} (field={err.field})")
```

| HTTP Status | Exception |
|-------------|-----------|
| 401 | `AuthenticationError` |
| 403 | `PermissionError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 422 | `ValidationError` |
| Other 4xx/5xx | `SuperposError` |

## API reference

### `SuperposClient(base_url, *, token=None, timeout=30.0)`

| Method | Description |
|--------|-------------|
| `register(name, hive_id, secret, ...)` | Register agent, store token |
| `login(agent_id, secret)` | Authenticate, store token |
| `logout()` | Revoke token |
| `me()` | Get current agent profile |
| `heartbeat(metadata=None)` | Send liveness signal |
| `update_status(status)` | Set agent status |
| `create_task(hive_id, task_type, ...)` | Create a task |
| `poll_tasks(hive_id, capability, limit)` | Poll for claimable tasks |
| `claim_task(hive_id, task_id)` | Atomically claim a task |
| `update_progress(hive_id, task_id, progress, ...)` | Report task progress |
| `complete_task(hive_id, task_id, result, ...)` | Mark task completed |
| `fail_task(hive_id, task_id, error, ...)` | Mark task failed |
| `list_knowledge(hive_id, key, scope, limit)` | List entries |
| `search_knowledge(hive_id, q, scope, limit)` | Search entries |
| `get_knowledge(hive_id, entry_id)` | Get single entry |
| `create_knowledge(hive_id, key, value, ...)` | Create entry |
| `update_knowledge(hive_id, entry_id, value, ...)` | Update entry |
| `delete_knowledge(hive_id, entry_id)` | Delete entry |
| `close()` | Close HTTP connection pool |

## Development

```bash
cd sdk/python
pip install -e ".[dev]"
pytest -v                    # 40 tests, all mocked HTTP
ruff check src/ tests/       # linting
```
