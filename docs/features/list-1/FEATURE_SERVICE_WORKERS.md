# Superpos — Feature: Service Workers (Async Data Requests)

## Addendum to PRODUCT.md v4.0

---

## 1. Problem

AI agents often need data from external services: emails from Gmail, issues from Jira, rows from Google Sheets, messages from Slack. Today there are two bad options:

**Blocking call** — agent waits for response. Expensive (agent is idle), fragile (timeouts), and breaks the autonomous poll-sleep cycle.

**Service Proxy** — works for simple single HTTP requests, but falls apart for complex operations: paginated fetches (100 emails = 10 API calls), filtered aggregations, multi-step workflows (search → fetch → transform), or services with non-REST APIs (GraphQL, gRPC, custom SDKs).

## 2. Solution: Service Workers

Lightweight agents that bridge the bus and external APIs. They look like regular agents but their sole job is data fetching/pushing.

```
┌──────────────┐     task: data_request      ┌──────────────────┐
│   Agent A     │ ──────────────────────────▸ │   Task Queue      │
│  (AI agent)   │                             │                    │
│               │     doesn't wait,           │                    │
│               │     continues polling       │                    │
└──────────────┘                              └────────┬───────────┘
                                                       │ poll
       result comes back                        ┌──────▼──────────┐
       on next poll cycle                       │  Gmail Worker    │
            │                                   │  (Service Worker)│
            │                                   │                  │
┌───────────▼──┐     task.result = data         │  - paginates     │
│   Agent A     │ ◂─────────────────────────── │  - filters       │
│  sees result  │                               │  - transforms    │
│  continues    │                               │  - retries       │
└──────────────┘                               └──────────────────┘
```

The AI agent never blocks. It lives in a clean cycle:

```
loop:
  request data I need  →  sleep  →  poll for results  →  work  →  repeat
```

## 3. How It Differs from Service Proxy

| Aspect              | Service Proxy                     | Service Worker                    |
|---------------------|-----------------------------------|-----------------------------------|
| **Complexity**      | Single HTTP request               | Multi-step operations             |
| **Blocking**        | Sync (agent waits for response)   | Fully async (fire and forget)     |
| **Use case**        | POST a comment, GET a file        | Fetch 100 emails, aggregate data  |
| **Pagination**      | Not supported                     | Handled by worker                 |
| **Transformation**  | Raw API response                  | Structured, filtered, cleaned     |
| **Error handling**  | Single retry                      | Worker manages retries internally |
| **Auth**            | Proxy injects credentials         | Worker has its own service access |
| **Implementation**  | Built into Superpos core            | Regular agent with data capability|

They complement each other. Proxy for simple, workers for complex.

## 4. Service Worker = Agent with Data Capability

A Service Worker is **not** a new concept in the system. It's a regular agent that:

1. Registers with capability like `data:gmail`, `data:sheets`, `data:jira`
2. Polls for tasks of type `data_request`
3. Executes complex operations against external APIs
4. Returns structured results via task completion

```json
POST /api/v1/agents/register
{
  "name": "gmail-worker",
  "type": "service_worker",
  "hive": "backend",
  "capabilities": ["data:gmail"],
  "requested_permissions": ["services:gmail"],
  "metadata": {
    "supported_operations": ["fetch_emails", "search_emails", "fetch_thread"],
    "max_concurrent_tasks": 5
  }
}
```

**Capability naming convention:** Service worker capabilities MUST use the `data:{service}` prefix (e.g., `data:gmail`, `data:jira`). This is convention, not enforced at registration, but SDK helpers and dashboard discovery rely on `data:*` wildcard matching. General agent capabilities use flat names (`code_review`, `testing`) or colon-namespaced names (`testing:chrome`).

## 5. Data Request Protocol

### 5.1 Requesting Data (AI Agent → Bus)

The AI agent creates a task targeting a data capability:

```json
POST /api/v1/tasks
{
  "type": "data_request",
  "target_capability": "data:gmail",
  "payload": {
    "operation": "fetch_emails",
    "params": {
      "query": "from:client@acme.com after:2025-02-01",
      "max_results": 100,
      "fields": ["from", "subject", "date", "snippet"]
    },
    "result_format": "array",
    "delivery": "task_result"
  }
}
```

Response:

```json
{
  "task_id": "tsk_abc123",
  "status": "pending",
  "message": "Data request queued"
}
```

Agent saves `task_id` and **moves on** — does other work, sleeps, whatever.

### 5.2 Worker Picks Up Request

Gmail Worker polls, claims the task, executes:

```
1. Parse operation: "fetch_emails"
2. Build Gmail API query from params
3. Paginate through results (may need 5-10 API calls)
4. Filter to requested fields
5. Transform to consistent format
6. Complete task with result
```

### 5.3 Worker Returns Data

```json
PATCH /api/v1/tasks/tsk_abc123/complete
{
  "result": {
    "data": [
      {
        "from": "client@acme.com",
        "subject": "Q1 Report Review",
        "date": "2025-02-15T09:30:00Z",
        "snippet": "Please find attached..."
      },
      // ... 99 more
    ],
    "metadata": {
      "total_fetched": 100,
      "total_available": 342,
      "has_more": true,
      "next_page_token": "pg_xyz789",
      "api_calls_made": 7,
      "fetched_at": "2025-02-20T12:00:00Z"
    }
  }
}
```

### 5.4 Worker Error Handling

If a worker fails mid-operation (e.g., successfully fetched pages 1-6 of 10, then hit an API error):

1. Worker completes the task as `failed` with partial data in `result.partial_data` and the error in `result.error`:
```json
{
  "status": "failed",
  "result": {
    "error": "Gmail API rate limit exceeded after page 6",
    "partial_data": [ /* pages 1-6 of results */ ],
    "metadata": { "pages_fetched": 6, "pages_total": 10 }
  }
}
```
2. Workers handle their own internal retries for transient API errors (rate limits, timeouts) before reporting failure.
3. Task-level retry (from `failure_policy`) re-creates the full request — the worker starts over from page 1. For resumable operations, the requesting agent can use `continuation_of` to resume from the last successful page.

### 5.5 Agent Retrieves Result

On next poll, agent checks its pending data requests:

```json
GET /api/v1/tasks?type=data_request&source_agent_id=me&status=completed
```

Or poll a specific task:

```json
GET /api/v1/tasks/tsk_abc123
```

Result is right there in `task.result`. Agent picks it up, continues work.

### 5.6 Large Results: Knowledge Store Delivery

For very large datasets (>1MB), worker stores data in Knowledge Store:

```json
PATCH /api/v1/tasks/tsk_abc123/complete
{
  "result": {
    "delivery": "knowledge_store",
    "knowledge_key": "data:gmail:fetch_abc123",
    "record_count": 5000,
    "size_bytes": 2400000
  },
  "knowledge_entries": [
    {
      "key": "data:gmail:fetch_abc123",
      "value": { /* ... large dataset ... */ },
      "scope": "agent:agt_requester",
      "ttl": "2025-02-21T12:00:00Z"
    }
  ]
}
```

Agent reads from knowledge store. TTL auto-cleans after consumption.

## 6. Continuation / Pagination

Agent can request more data using the page token from previous result:

```json
POST /api/v1/tasks
{
  "type": "data_request",
  "target_capability": "data:gmail",
  "payload": {
    "operation": "fetch_emails",
    "params": {
      "query": "from:client@acme.com after:2025-02-01",
      "max_results": 100,
      "page_token": "pg_xyz789"
    },
    "continuation_of": "tsk_abc123"
  }
}
```

Worker sees `continuation_of`, can reuse cached API state if available.

## 7. Delivery Modes

| Mode            | When to use                        | How it works                       |
|-----------------|------------------------------------|------------------------------------|
| `task_result`   | Small results (<1MB)               | Data in task.result JSONB          |
| `knowledge`     | Large results, reusable data       | Worker writes to Knowledge Store   |
| `stream`        | Ongoing / real-time data           | Worker creates multiple tasks      |

### Stream Delivery

For ongoing data (e.g., "watch for new emails from this sender"):

```json
POST /api/v1/tasks
{
  "type": "data_request",
  "target_capability": "data:gmail",
  "payload": {
    "operation": "watch_emails",
    "params": {
      "query": "from:client@acme.com",
      "poll_interval_seconds": 60,
      "duration_minutes": 30
    },
    "delivery": "stream"
  }
}
```

Worker creates a new child task for each batch of new emails it finds:

```json
POST /api/v1/tasks
{
  "type": "data_response",
  "target_agent_id": "agt_requester",
  "parent_task_id": "tsk_watch_abc",
  "payload": {
    "batch": 3,
    "data": [ /* new emails since last check */ ],
    "has_more": true
  }
}
```

Agent sees `data_response` tasks in its poll and processes incrementally.

**Stream completion:** The worker completes the parent watch task when the stream ends (duration expires or the watch is explicitly stopped). The parent result contains a summary: `{ "batches_delivered": N, "total_records": M }`. The requesting agent knows the stream is complete when the parent task status becomes `completed`.

## 8. Built-in Operations

Each Service Worker publishes its supported operations when registering.
The agent (or dashboard) can discover what's available:

```json
GET /api/v1/agents?capability=data:*
```

```json
{
  "data": [
    {
      "name": "gmail-worker",
      "capabilities": ["data:gmail"],
      "metadata": {
        "supported_operations": [
          {
            "name": "fetch_emails",
            "description": "Fetch emails matching a query",
            "params": {
              "query": { "type": "string", "required": true, "description": "Gmail search query" },
              "max_results": { "type": "integer", "default": 50, "max": 500 },
              "fields": { "type": "array", "default": ["from", "subject", "date", "body"] }
            }
          },
          {
            "name": "search_emails",
            "description": "Search and return email IDs + snippets",
            "params": { /* ... */ }
          },
          {
            "name": "send_email",
            "description": "Send an email (requires approval policy)",
            "params": { /* ... */ }
          }
        ]
      }
    }
  ]
}
```

This is essentially a **service catalog** — agents can discover what data they can request.

## 9. Write Operations & Action Policies

Service Workers can also **write** data (send email, create Jira issue, etc.).
These go through the same Action Policy engine:

```json
POST /api/v1/tasks
{
  "type": "data_request",
  "target_capability": "data:gmail",
  "payload": {
    "operation": "send_email",
    "params": {
      "to": "client@acme.com",
      "subject": "Updated Report",
      "body": "Please see the revised version..."
    }
  }
}
```

The Service Worker's action policy might require approval for sends:

```json
{
  "rules": {
    "allow": [
      { "operation": "fetch_emails" },
      { "operation": "search_emails" }
    ],
    "require_approval": [
      { "operation": "send_email" },
      { "operation": "delete_email" }
    ],
    "deny": [
      { "operation": "delete_all" }
    ]
  }
}
```

Worker checks policy before executing, creates approval request if needed.

## 10. Example Flow: Full Cycle

Scenario: AI code review agent needs to check if a similar PR was discussed in email.

```
1. Agent receives task: review PR #42
2. Agent creates data_request:
   {
     target_capability: "data:gmail",
     operation: "search_emails",
     params: { query: "subject:authentication refactor" }
   }
   → gets back task_id: tsk_email_req

3. Agent continues reviewing the PR code (doesn't wait!)

4. Gmail Worker picks up tsk_email_req
   → searches Gmail API
   → finds 3 relevant email threads
   → completes task with results

5. Agent finishes code analysis, checks tsk_email_req
   → status: completed
   → reads email context from result

6. Agent combines code review + email context
   → writes PR comment with full context
   → completes original review task
```

Total agent idle time: **zero**. Agent was doing useful work while Gmail Worker fetched data.

## 11. Pre-built Service Workers

Ship with Superpos or available via Marketplace:

| Worker            | Capability      | Operations                                        |
|-------------------|-----------------|---------------------------------------------------|
| **Gmail Worker**  | `data:gmail`    | fetch_emails, search, send, watch                 |
| **Sheets Worker** | `data:sheets`   | read_range, write_range, create_sheet             |
| **Jira Worker**   | `data:jira`     | fetch_issues, create_issue, update_status, search |
| **Slack Worker**  | `data:slack`    | fetch_messages, post_message, search, list_channels|
| **GitHub Worker** | `data:github`   | fetch_prs, fetch_issues, search_code, fetch_files |
| **HTTP Worker**   | `data:http`     | Generic: any URL, pagination, auth handling       |
| **SQL Worker**    | `data:sql`      | Run read queries against connected databases      |

Each worker is a standalone script (Python/Node/PHP) that:
- Registers as agent with `data:*` capability
- Polls for `data_request` tasks
- Has its own service connection credentials (via proxy or direct)
- Handles retries, rate limiting, pagination internally

## 12. Writing a Custom Service Worker

Minimal Python example:

```python
from superpos_sdk import SuperposClient

client = SuperposClient(
    url="https://your-apiary.ai",
    token="tok_xxx"
)

# Register as service worker
client.register(
    name="custom-crm-worker",
    type="service_worker",
    hive="backend",
    capabilities=["data:crm"],
    metadata={
        "supported_operations": ["fetch_contacts", "search_deals"]
    }
)

# Poll loop
while True:
    tasks = client.poll()
    for task in tasks:
        if task.type == "data_request":
            result = handle_crm_request(task.payload)
            client.complete(task.id, result=result)
    
    client.sleep()  # respects server-provided poll interval


def handle_crm_request(payload):
    op = payload["operation"]
    params = payload["params"]
    
    if op == "fetch_contacts":
        contacts = crm_api.get_contacts(**params)
        return {"data": contacts, "metadata": {"count": len(contacts)}}
    
    if op == "search_deals":
        deals = crm_api.search_deals(**params)
        return {"data": deals}
    
    raise ValueError(f"Unknown operation: {op}")
```

That's it. ~30 lines of code to bridge any service into the Superpos bus.

## 13. Dashboard: Service Worker View

Additions to dashboard:

- **Service Catalog** — list of all registered data capabilities, their operations, online status
- **Data Request Monitor** — pending/active/completed data requests, latency stats
- **Worker Health** — per-worker: tasks processed, error rate, avg response time
- Operation-level metrics: "fetch_emails avg 2.3s, search_emails avg 800ms"

## 14. Implementation Notes

### No new tables needed

Service Workers use existing infrastructure:
- `agents` table — workers register as agents with `type: service_worker`
- `tasks` table — data requests are regular tasks with `type: data_request`
- `knowledge_entries` — large result delivery
- `action_policies` — operation-level policies on workers
- `activity_log` — full audit trail

### New conventions (not schema changes)
- Task type `data_request` / `data_response` — reserved types
- Capability prefix `data:*` — convention for data workers
- Agent metadata `supported_operations` — service catalog schema
- Payload schema: `{ operation, params, delivery, result_format }`

### SDK additions
- `client.data_request(capability, operation, params)` — convenience method
- `client.await_data(task_id, timeout=None)` — optional blocking wait for simple scripts
- `client.discover_services()` — list available data capabilities
- Worker base class with operation routing

---

*Feature version: 1.0*
*Depends on: PRODUCT.md v4.0 (core task system, agent registration, knowledge store)*
