# Superpos — Data Request Protocol & Conventions

> **Task:** TASK-139
> **Depends on:** TASK-008 (task model)
> **Status:** Implemented

---

## 1. Overview

The **data request protocol** defines how any Superpos agent sends a structured
request to a service worker and how the service worker delivers a response.
It builds on the existing task system, adding a dedicated
`POST /tasks/{id}/deliver-response` endpoint that enables push-style response
delivery without requiring ownership of the target task.

The key idea is **fire-and-forget**:

```
Agent A creates data_request task  →  Agent A continues doing other work
                                      ↓
                               Service Worker polls, claims, executes
                                      ↓
                               Worker calls POST /tasks/{id}/deliver-response
                                      ↓
                    Agent A finds result on its next poll cycle
```

Agent A is never idle waiting for data.

---

## 2. Task Payload Schema

A `data_request` task carries a structured payload:

```json
{
  "operation": "fetch_issues",
  "params": {
    "repo": "acme/backend",
    "state": "open",
    "labels": ["bug"]
  },
  "delivery": "task_result",
  "result_format": "array",
  "continuation_of": null,
  "response_task_id": null
}
```

| Field              | Type     | Required | Description |
|--------------------|----------|----------|-------------|
| `operation`        | string   | yes      | Operation name the service worker will execute (e.g. `fetch_issues`). Uses snake_case or kebab-case — workers normalize both. |
| `params`           | object   | no       | Operation-specific parameters. Schema is defined by the worker. |
| `delivery`         | string   | no       | Result delivery mode: `task_result` (default) or `knowledge`. |
| `result_format`    | string   | no       | Hint to the worker about desired format (e.g. `array`, `object`). |
| `continuation_of`  | ULID     | no       | Task ID of a previous request to continue from (pagination). |
| `response_task_id` | ULID     | no       | If set, the worker should call `POST /tasks/{id}/deliver-response` with *this* task ID to push the result (push-style delivery). |

---

## 3. Response Schema

The task `result` field follows this convention:

**Success:**
```json
{
  "status": "success",
  "data": {
    "issues": [
      { "id": 42, "title": "Fix auth timeout", "state": "open" }
    ]
  },
  "metadata": {
    "total_fetched": 1,
    "has_more": false,
    "fetched_at": "2026-03-01T12:00:00Z"
  }
}
```

**Error:**
```json
{
  "status": "error",
  "error": "GitHub API rate limit exceeded",
  "data": null,
  "metadata": {
    "retry_after": 3600
  }
}
```

| Field      | Type   | Description |
|------------|--------|-------------|
| `status`   | string | `"success"` or `"error"` |
| `data`     | any    | Operation result. Shape is operation-specific. |
| `error`    | string | Human-readable error message when `status="error"`. |
| `metadata` | object | Optional pagination/stats metadata. Worker-defined shape. |

---

## 4. Task Type & Capability Conventions

- **Task type:** always `data_request`
- **Capability naming:** `data:{service}` (e.g. `data:github`, `data:gmail`, `data:jira`)
- **Agent type:** `service_worker`
- **Supported operations:** declared in `agent.metadata.supported_operations` at registration

Example registration:
```json
POST /api/v1/agents/register
{
  "name": "github-worker",
  "type": "service_worker",
  "hive_id": "01HXYZ...",
  "capabilities": ["data:github"],
  "secret": "...",
  "metadata": {
    "supported_operations": [
      { "name": "fetch_issues", "description": "List issues from a GitHub repo" },
      { "name": "create_issue", "description": "Create a new GitHub issue" },
      { "name": "fetch_pull_requests", "description": "List open pull requests" }
    ]
  }
}
```

---

## 5. Delivery Modes

| Mode          | When to use                   | How it works | Status |
|---------------|-------------------------------|--------------|--------|
| `task_result` | Small results (<1 MB)         | Data is stored in `task.result` JSONB | Implemented |
| `knowledge`   | Large / reusable results      | Worker writes to Knowledge Store; result contains the key | _(planned — TASK-144)_ |
| `stream`      | Ongoing / real-time data      | Worker creates child `data_response` tasks per batch | _(planned — TASK-142)_ |

---

## 6. Service Worker Implementation Guide

### 6.1 Python SDK — Subclass Pattern

```python
from superpos_sdk import ServiceWorker

class GitHubWorker(ServiceWorker):
    CAPABILITY = "data:github"

    def fetch_issues(self, params: dict) -> dict:
        """List open issues from a GitHub repository."""
        repo   = params["repo"]
        state  = params.get("state", "open")
        labels = params.get("labels", [])

        # Call the GitHub API (using your preferred client)
        issues = github_client.list_issues(repo, state=state, labels=labels)

        return {
            "status": "success",
            "data": {"issues": [i.to_dict() for i in issues]},
            "metadata": {
                "total_fetched": len(issues),
                "has_more": False,
                "fetched_at": datetime.utcnow().isoformat() + "Z",
            },
        }

    def create_issue(self, params: dict) -> dict:
        """Create a new GitHub issue."""
        issue = github_client.create_issue(
            repo=params["repo"],
            title=params["title"],
            body=params.get("body", ""),
            labels=params.get("labels", []),
        )
        return {
            "status": "success",
            "data": {"issue": issue.to_dict()},
        }
```

Run the worker:

```python
worker = GitHubWorker(
    base_url="https://superpos.example.com",
    hive_id="01HXYZ...",
    name="github-worker",
    secret="s3cr3t",
)
worker.run()  # blocks; Ctrl-C or SIGTERM for graceful shutdown
```

The `ServiceWorker` base class handles:
- Agent registration / login
- Poll loop with `claim_type = "data_request"` filtering
- Atomic task claiming (conflict-safe)
- Operation routing (method name = operation name, hyphens → underscores)
- Structured error reporting on `OperationNotFoundError` or any exception
- Graceful shutdown on SIGINT / SIGTERM

### 6.2 Python SDK — Composition Pattern

```python
from superpos_sdk import ServiceWorker

worker = ServiceWorker(
    base_url="https://superpos.example.com",
    hive_id="01HXYZ...",
    name="github-worker",
    secret="s3cr3t",
)

worker.register_operation("fetch_issues",  lambda p: fetch_issues_impl(p))
worker.register_operation("create_issue",  lambda p: create_issue_impl(p))

worker.run()
```

### 6.3 Python SDK — Dispatching Requests from Inside a Worker

A worker can fan out to another service worker using
`dispatch_data_request()`:

```python
class OrchestratorWorker(ServiceWorker):
    CAPABILITY = "data:orchestrator"

    def fetch_project_summary(self, params: dict) -> dict:
        repo = params["repo"]

        # Dispatch to the GitHub worker — non-blocking
        ref = self.dispatch_data_request(
            "fetch_issues",
            {"repo": repo, "state": "open"},
            target_capability="data:github",
        )
        return {"status": "success", "data": {"github_task_id": ref["id"]}}
```

### 6.4 Python SDK — Push-Style Response Delivery

When the requesting agent sets `response_task_id` in the payload, the worker
should complete that task via `deliver_response()`.  Internally this calls the
dedicated `POST /tasks/{id}/deliver-response` endpoint, which bypasses the
normal `in_progress`/ownership checks that `complete` enforces.  The server
authorises the call by verifying the calling agent has an `in_progress` task
whose `payload.response_task_id` matches the target task ID.

```python
class GitHubWorker(ServiceWorker):
    CAPABILITY = "data:github"

    def fetch_issues(self, params: dict) -> dict:
        issues = github_client.list_issues(params["repo"])
        result = {
            "status": "success",
            "data": {"issues": [i.to_dict() for i in issues]},
        }

        # Push-style: notify the waiting task if requested.
        # self.response_task_id is populated automatically from the task payload
        # by the ServiceWorker base class — no need to read params manually.
        if self.response_task_id:
            self.deliver_response(result, status_message="Issues fetched")

        return result
```

---

## 7. SDK Usage Examples

### 7.1 Python — Requesting Data (Any Agent)

```python
from superpos_sdk import SuperposClient

client = SuperposClient("https://superpos.example.com", token="tok_xxx")

# Fire and forget — returns a task dict immediately
ref = client.data_request(
    hive_id,
    capability="data:github",
    operation="fetch_issues",
    params={"repo": "acme/backend", "state": "open"},
)
task_id = ref["id"]

# Later, check the result:
task = client._request("GET", f"/api/v1/hives/{hive_id}/tasks/{task_id}")
if task["status"] == "completed":
    issues = task["result"]["data"]["issues"]

# Discover available service workers:
services = client.discover_services(hive_id)
for svc in services:
    ops = svc.get("metadata", {}).get("supported_operations", [])
    print(svc["name"], [o["name"] for o in ops])
```

### 7.2 Shell SDK — Requesting Data

```bash
source superpos-sdk.sh

# Send a data_request
TASK_JSON=$(superpos_data_request "$HIVE_ID" \
    -c data:github \
    -o fetch_issues \
    -p '{"repo":"acme/backend","state":"open"}')

TASK_ID=$(echo "$TASK_JSON" | jq -r '.id')
echo "Dispatched: $TASK_ID"

# Discover service workers
superpos_discover_services "$HIVE_ID"
```

### 7.3 Shell SDK — Dispatching from a Worker

```bash
source superpos-sdk.sh

# Inside a service worker handler script:
handle_orchestrate() {
    local params="$1"
    local repo
    repo=$(echo "$params" | jq -r '.repo')

    # Fan out to the GitHub worker
    superpos_data_request_dispatch "$HIVE_ID" \
        -c data:github \
        -o fetch_issues \
        -p "{\"repo\":\"$repo\",\"state\":\"open\"}"
}
```

---

## 8. Full Request/Response Cycle

```
1.  Agent A creates a data_request task:
    POST /api/v1/hives/{hive_id}/tasks
    {
      "type": "data_request",
      "target_capability": "data:github",
      "payload": {
        "operation": "fetch_issues",
        "params": { "repo": "acme/backend", "state": "open" }
      }
    }
    → { "id": "01HREQ...", "status": "pending" }

2.  Agent A saves "01HREQ..." and continues its own work.

3.  GitHubWorker polls, claims "01HREQ...":
    PATCH /api/v1/hives/{hive_id}/tasks/01HREQ.../claim

4.  GitHubWorker executes fetch_issues({"repo": "acme/backend", "state": "open"})
    → calls GitHub API, fetches issues

5.  GitHubWorker completes the task:
    PATCH /api/v1/hives/{hive_id}/tasks/01HREQ.../complete
    {
      "result": {
        "status": "success",
        "data": { "issues": [...] },
        "metadata": { "total_fetched": 7, "has_more": false }
      }
    }

    If a response_task_id was set in the payload, the worker also calls:
    POST /api/v1/hives/{hive_id}/tasks/01HRESP.../deliver-response
    {
      "result": {
        "status": "success",
        "data": { "issues": [...] },
        "metadata": { "total_fetched": 7, "has_more": false }
      }
    }
    → This uses the dedicated deliver-response endpoint which does NOT require
      the response task to be in_progress or owned by the worker.

6.  Agent A polls, finds task "01HREQ..." completed.
    Reads issues from task.result.data.issues
    Continues its workflow.
```

---

## 9. Error Handling Conventions

| Scenario                       | Worker behaviour |
|--------------------------------|-----------------|
| Unknown operation              | `fail_task` with `{"type": "OperationNotFoundError", "operation": "..."}` |
| External API error (transient) | Worker retries internally (e.g. 3× with back-off), then `fail_task` |
| External API error (fatal)     | `fail_task` with `{"status": "error", "error": "..."}` in result |
| Partial success                | `complete_task` with `result.partial_data` and `result.metadata.pages_fetched` |
| Large result (>1 MB)           | _(knowledge-store delivery planned in TASK-144 — currently use `task_result` with chunking or compression)_ |

---

## 10. Related Documents

- [FEATURE_SERVICE_WORKERS.md](features/list-1/FEATURE_SERVICE_WORKERS.md) — service worker architecture overview
- [PRODUCT.md](PRODUCT.md) — full task system schema
- TASK-140 — Python SDK `ServiceWorker` base class implementation
- TASK-141 — built-in service workers (HTTP, GitHub, Slack, Gmail, Sheets, Jira, SQL)
- TASK-142 — stream delivery mode
- TASK-144 — knowledge store delivery for large results

---

*Feature version: 1.0*
*Implemented in: TASK-139*
