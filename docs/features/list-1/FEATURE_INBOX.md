# Superpos — Feature: Inbox (Simple Webhook-to-Task)

## Addendum to PRODUCT.md v4.0

---

## 1. Problem

Current webhook flow is powerful but heavy:

```
Register service connection → install connector → configure webhook route
→ set field filters → define payload mapping → paste URL in external service
```

This is great for GitHub/Slack/Jira where you need signature validation, event parsing, and smart filtering. But many real-world cases are simpler:

- "I want to POST JSON from my CI pipeline and have an agent handle it"
- "I have a Zapier/Make workflow that should trigger an agent"
- "My monitoring tool sends alerts via webhook — just make it a task"
- "I'm prototyping and want the fastest path from HTTP request to agent task"

For these cases, the full connector + route setup is friction that slows adoption.

## 2. Solution: Inbox

An **Inbox** is a simple, pre-authenticated URL that converts any POST into a task.

```
POST https://acme.apiary.ai/inbox/inb_a1B2c3D4e5F6

{ "server": "web-03", "alert": "CPU > 95%", "severity": "high" }

→ Task created in target hive, agent picks it up
```

No connector. No route config. No signature validation.
Just URL → task.

**ID vs Slug:** Every inbox has two identifiers. The **id** is a standard 26-character ULID (like all Superpos resources). The **slug** is a URL-safe string prefixed `inb_` followed by 12 random characters (e.g. `inb_a1B2c3D4e5F6`). The public receiver URL uses the slug — it is what you copy/paste into external services. The id is what the API returns for management operations (list, show, update, delete).

## 3. How It Works

### 3.1 Create an Inbox

Dashboard: Hive → Inboxes → "New Inbox"

Or via API:

```json
POST /api/v1/hives/{hive}/inboxes
{
  "name": "CI Pipeline Alerts",
  "task_type": "ci_alert",
  "target_capability": "ops",
  "priority": 3,
  "description": "Receives POST from GitHub Actions on failure"
}
```

Response:

```json
{
  "id": "01HQXK5V8N3YGT4P9RZM6WJCBA",
  "superpos_id": "01HQXK5V8N3YGT4P9RZM6WJAAA",
  "hive_id": "01HQXK5V8N3YGT4P9RZM6WJBBB",
  "name": "CI Pipeline Alerts",
  "slug": "inb_a1B2c3D4e5F6",
  "task_type": "ci_alert",
  "target_capability": "ops",
  "priority": 3,
  "is_active": true,
  "created_at": "2025-02-20T10:00:00Z",
  "updated_at": "2025-02-20T10:00:00Z"
}
```

The `id` is the ULID used for management API calls. The `slug` is what goes in the public URL — copy `https://acme.apiary.ai/inbox/inb_a1B2c3D4e5F6` and paste it wherever you need.

### 3.2 Send Data to Inbox

```
POST /inbox/inb_a1B2c3D4e5F6
Content-Type: application/json

{
  "repo": "acme/backend",
  "workflow": "tests",
  "status": "failure",
  "branch": "main",
  "commit": "a1b2c3d",
  "url": "https://github.com/acme/backend/actions/runs/12345"
}
```

Response:

```json
{
  "task_id": "tsk_xyz789",
  "status": "pending",
  "message": "Task created from inbox"
}
```

### 3.3 What Gets Created

The entire POST body becomes the task payload, wrapped with inbox metadata:

```json
{
  "id": "tsk_xyz789",
  "type": "ci_alert",
  "hive_id": "hiv_backend",
  "target_capability": "ops",
  "priority": "high",
  "status": "pending",
  "payload": {
    "_inbox": {
      "inbox_id": "01HQXK5V8N3YGT4P9RZM6WJCBA",
      "inbox_name": "CI Pipeline Alerts",
      "received_at": "2025-02-20T12:34:56Z",
      "source_ip": "140.82.112.1",
      "content_type": "application/json"
    },
    "_body": {
      "repo": "acme/backend",
      "workflow": "tests",
      "status": "failure",
      "branch": "main",
      "commit": "a1b2c3d",
      "url": "https://github.com/acme/backend/actions/runs/12345"
    }
  }
}
```

`_inbox` — metadata added by Superpos.
`_body` — raw POST body, untouched.

Agent receives the full context and decides what to do.

## 4. Inbox Configuration Options

### 4.1 Minimal (zero config)

```json
POST /api/v1/hives/{hive}/inboxes
{
  "name": "Quick Webhook"
}
```

Defaults: task_type = `inbox`, no target filtering, normal priority, current hive.
Any agent can pick it up.

### 4.2 Full Config

```json
POST /api/v1/hives/{hive}/inboxes
{
  "name": "Production Alerts",
  "task_type": "production_alert",
  "target_capability": "incident_response",
  "target_agent_id": null,
  "priority": "critical",
  "description": "PagerDuty → Superpos bridge",

  "transform": {
    "task_type_from": "$.severity",
    "priority_from": "$.urgency",
    "mapping": {
      "priority": {
        "P1": "critical",
        "P2": "high",
        "P3": "normal",
        "P4": "low"
      }
    }
  },

  "security": {
    "secret": "whsec_abc123",
    "signature_header": "X-Webhook-Signature",
    "signature_algo": "hmac-sha256",
    "allowed_ips": ["140.82.112.0/20"]
  },

  "limits": {
    "max_requests_per_minute": 60,
    "max_payload_bytes": 65536,
    "deduplicate_field": "$.event_id",
    "deduplicate_window": 300
  },

  "failure_policy": {
    "task_timeout": 600,
    "max_retries": 3,
    "guarantee": "at_least_once"
  }
}
```

Everything optional. Start simple, add config as needed.

### 4.3 Feature Breakdown

| Feature                | Default            | Description                              |
|------------------------|--------------------|------------------------------------------|
| `task_type`            | `"inbox"`          | Task type for created tasks              |
| `target_capability`    | `null` (any)       | Route to agents with this capability     |
| `target_agent_id`      | `null` (any)       | Route to specific agent                  |
| `priority`             | `"normal"`         | Task priority                            |
| `transform`            | none               | Map payload fields to task fields        |
| `security.secret`      | none               | HMAC signature validation                |
| `security.allowed_ips` | any                | IP allowlist                             |
| `limits.rate`          | 60/min             | Rate limiting                            |
| `limits.deduplicate`   | none               | Deduplicate by payload field             |
| `failure_policy`       | system defaults    | Task failure/retry config                |

## 5. Payload Transform

Optional lightweight mapping from webhook payload to task fields.
Simpler than full connector parsing — just JSONPath extraction.

> The transform schema is the same as in §4.2. The example below shows a different use case (monitoring alerts vs the PagerDuty incident response example above) to illustrate how the same mechanism adapts to different webhook sources.

```json
{
  "transform": {
    "task_type_from": "$.event_type",
    "priority_from": "$.severity",
    "mapping": {
      "priority": {
        "critical": "critical",
        "warning": "high",
        "info": "low"
      }
    },
    "extract": {
      "title": "$.alert.name",
      "source": "$.source.host"
    }
  }
}
```

Result: task gets `type` from webhook's `event_type`, priority mapped from `severity`, and `title`/`source` extracted into top-level payload.

Created task payload:

```json
{
  "_inbox": { ... },
  "_body": { /* full original body */ },
  "title": "CPU Spike on web-03",
  "source": "web-03.prod"
}
```

Agent gets both clean extracted fields AND full raw body if it needs more.

## 6. Security Tiers

Inboxes support three security levels. Pick what fits your use case.

### Tier 1: URL-only (default)

The inbox URL contains a random slug (`inb_a1B2c3D4e5F6`). Knowing the URL = authorized.
Good for: internal tools, prototyping, trusted sources.

```json
{ "security": {} }
```

### Tier 2: Shared secret

HMAC signature validation — same mechanism as GitHub/Stripe webhooks.

```json
{
  "security": {
    "secret": "whsec_abc123",
    "signature_header": "X-Signature",
    "signature_algo": "hmac-sha256"
  }
}
```

Request must include valid signature. Invalid → 401.

### Tier 3: Secret + IP restriction

Add IP allowlist on top of signature.

```json
{
  "security": {
    "secret": "whsec_abc123",
    "signature_header": "X-Signature",
    "signature_algo": "hmac-sha256",
    "allowed_ips": ["140.82.112.0/20", "192.30.252.0/22"]
  }
}
```

Good for: production services with known IP ranges (GitHub, PagerDuty, etc.)

## 7. Relationship to Webhook Routes

Inbox is the **simple path**. Webhook Routes are the **powerful path**. Same underlying task creation, different entry points.

```
                    ┌─────────────────────────────────────────┐
                    │             Incoming HTTP POST           │
                    └───────────────┬─────────────────────────┘
                                    │
                        ┌───────────▼──────────┐
                        │   URL routing         │
                        │                       │
            ┌───────────┴───────┐     ┌────────┴──────────┐
            │                   │     │                    │
   /inbox/inb_xxx         /webhooks/github
            │                   │     │                    │
            ▼                   │     ▼                    │
   ┌────────────────┐          │  ┌──────────────────┐    │
   │  Inbox          │          │  │  Webhook Route    │    │
   │                 │          │  │                    │    │
   │  - URL auth     │          │  │  - Connector       │    │
   │  - Optional     │          │  │    validates sig   │    │
   │    signature    │          │  │  - Parses payload  │    │
   │  - Optional     │          │  │  - Field filters   │    │
   │    transform   │          │  │  - Payload mapping │    │
   │  - Rate limit   │          │  │  - Route matching  │    │
   └───────┬────────┘          │  └─────────┬──────────┘    │
           │                   │            │                │
           └───────────────────┴────────────┘                │
                               │                             │
                        ┌──────▼──────────┐                  │
                        │  Create Task    │                  │
                        │  in hive queue  │                  │
                        └─────────────────┘
```

### Migration Path

Start with Inbox (5 seconds to set up) → as needs grow, switch to full Webhook Route.

Dashboard can suggest: "This inbox received 500+ GitHub events. Want to upgrade to a Webhook Route with connector + filters?"

### When to Use What

| Use Case                                  | Inbox | Webhook Route |
|-------------------------------------------|-------|---------------|
| Quick prototype / testing                 | ✅     |               |
| CI/CD pipeline trigger                    | ✅     |               |
| Simple monitoring alert → task            | ✅     |               |
| Zapier/Make/n8n integration               | ✅     |               |
| Custom internal tool webhook              | ✅     |               |
| GitHub with event type filtering          |       | ✅             |
| Slack with slash command parsing          |       | ✅             |
| "Only PRs on main with @bot mention"     |       | ✅             |
| Multiple event types → different tasks    |       | ✅             |
| Complex payload transformation            |       | ✅             |

## 8. Deduplication

Webhooks often arrive multiple times (retries, at-least-once delivery from sender).

```json
{
  "limits": {
    "deduplicate_field": "$.delivery_id",
    "deduplicate_window": 300
  }
}
```

If two POSTs have the same `delivery_id` within 5 minutes → second one returns:

```json
{
  "task_id": "tsk_original",
  "status": "deduplicated",
  "message": "Duplicate delivery, returning existing task"
}
```

Uses the same idempotency key infrastructure from FEATURE_TASK_SEMANTICS.

**Window semantics:**
- The window is **absolute from first receipt**, not sliding. A 300s window means "within 300 seconds of the first time this delivery_id was seen."
- After the window expires, the same `delivery_id` creates a new task (it is treated as a fresh delivery).
- Dedup keys are stored in Redis with TTL equal to `deduplicate_window`, so they auto-expire without cleanup jobs.

## 9. Database

### 9.1 Inboxes Table

```sql
CREATE TABLE inboxes (
    id              VARCHAR(26) PRIMARY KEY,     -- ULID
    superpos_id       VARCHAR(26) NOT NULL REFERENCES apiaries(id),
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL,       -- URL-safe identifier (inb_ + 12 random chars)
    description     TEXT,
    
    -- Task creation config
    task_type       VARCHAR(100) DEFAULT 'inbox',
    target_capability VARCHAR(100),
    target_agent_id VARCHAR(26) REFERENCES agents(id),
    priority        SMALLINT DEFAULT 2,
    failure_policy  JSONB DEFAULT '{}',
    guarantee       VARCHAR(20) DEFAULT 'at_least_once',
    
    -- Payload transform
    transform       JSONB DEFAULT NULL,
    
    -- Security
    secret_hash     VARCHAR(255),                -- hashed shared secret
    signature_header VARCHAR(100),
    signature_algo  VARCHAR(20),
    allowed_ips     JSONB DEFAULT NULL,           -- ["cidr", "cidr"]
    
    -- Limits
    rate_limit      INTEGER DEFAULT 60,           -- requests per minute
    max_payload_bytes INTEGER DEFAULT 65536,
    deduplicate_field VARCHAR(255),
    deduplicate_window INTEGER DEFAULT 300,       -- seconds
    
    -- State
    is_active       BOOLEAN DEFAULT TRUE,
    request_count   BIGINT DEFAULT 0,
    last_request_at TIMESTAMP,
    
    created_by      BIGINT,                       -- user or agent who created
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(superpos_id, hive_id, slug)
);

CREATE INDEX idx_inboxes_slug ON inboxes (slug) WHERE is_active = TRUE;
```

### 9.2 Inbox Log

Lightweight request log for debugging and dashboard:

```sql
CREATE TABLE inbox_log (
    id              BIGSERIAL PRIMARY KEY,
    superpos_id       VARCHAR(26) NOT NULL REFERENCES apiaries(id) ON DELETE CASCADE,
    hive_id         VARCHAR(26) NOT NULL,
    inbox_id        VARCHAR(26) NOT NULL,
    task_id         VARCHAR(26),                -- null if rejected
    slug            VARCHAR(80) NOT NULL,       -- slug at the time of the request
    status_code     SMALLINT NOT NULL,          -- HTTP response code (201, 200, 401, 403, 409, 413, 429)
    outcome         VARCHAR(30) NOT NULL,       -- 'success', 'duplicate', 'auth_failed', 'rate_limited', 'rejected', 'ip_blocked', 'dedup_contention'
    error_code      VARCHAR(50),                -- e.g. 'invalid_signature', 'payload_too_large', 'dedup_lock_contention'
    source_ip       VARCHAR(45) NOT NULL,       -- supports IPv4 and IPv6
    content_length  INTEGER UNSIGNED,           -- bytes, nullable
    duration_ms     INTEGER UNSIGNED,           -- request processing time, nullable
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_inbox_log_apiary ON inbox_log (superpos_id, created_at);
CREATE INDEX idx_inbox_log_hive ON inbox_log (hive_id, created_at);
CREATE INDEX idx_inbox_log_inbox ON inbox_log (inbox_id, created_at);
```

## 10. API

### 10.1 Inbox Management

All management endpoints are hive-scoped and require agent authentication:

```
POST   /api/v1/hives/{hive}/inboxes                    — Create inbox
GET    /api/v1/hives/{hive}/inboxes                    — List inboxes in hive
GET    /api/v1/hives/{hive}/inboxes/{inbox}            — Get inbox details + stats
PUT    /api/v1/hives/{hive}/inboxes/{inbox}            — Update config
DELETE /api/v1/hives/{hive}/inboxes/{inbox}            — Delete inbox
POST   /api/v1/hives/{hive}/inboxes/{inbox}/rotate-slug — Rotate slug (new URL, old stops working)
```

The `{inbox}` parameter is the inbox **id** (ULID), not the slug.

### 10.2 Inbox Receiver (public, no auth)

```
POST   /inbox/{slug}               — Receive webhook, create task
```

No API token needed. The slug itself is the auth (Tier 1) or signature validates (Tier 2/3).

### 10.3 Agent-Created Inboxes

Agents with `inboxes.write` permission can create inboxes via API:

```json
POST /api/v1/hives/{hive}/inboxes
{
  "name": "My CI Listener",
  "task_type": "ci_event",
  "target_capability": "ci_handler"
}
```

Use case: agent bootstraps its own infrastructure — "I need a webhook URL for GitHub Actions, let me create one."

## 11. Dashboard

### 11.1 Inbox List

```
┌─────────────────────────────────────────────────────────────┐
│  Inboxes                                          [+ New]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🟢 CI Pipeline Alerts          ci_alert → ops             │
│     https://acme.apiary.ai/inbox/inb_a1B2c3D4e5F6 [Copy]   │
│     1,247 requests · last: 2 min ago                        │
│                                                             │
│  🟢 PagerDuty Bridge            production_alert → infra   │
│     https://acme.apiary.ai/inbox/inb_R3xYp...    [Copy]   │
│     89 requests · last: 1 hour ago                          │
│                                                             │
│  🔴 Prototype Webhook           inbox → any                │
│     https://acme.apiary.ai/inbox/inb_Tn2Kw...    [Copy]   │
│     3 requests · last: 5 days ago                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 Inbox Detail

- URL with copy button
- Request volume chart (last 24h / 7d / 30d)
- Recent request log with expand (see full payload)
- Status breakdown: accepted / rejected / rate_limited / deduplicated
- Config editor (task type, security, transforms, limits)
- "Test" button — send a sample POST from dashboard

### 11.3 Quick Setup Flow

```
Dashboard → Hive → Inboxes → [+ New Inbox]

Step 1: "What should trigger your agent?"
  [ ] CI/CD failure alerts
  [ ] Monitoring alerts
  [ ] Form submissions
  [ ] Custom webhook
  
Step 2: "Which agent handles it?"
  → capability selector or specific agent

Step 3: Here's your URL
  https://acme.apiary.ai/inbox/inb_a1B2c3D4e5F6  [Copy]
  
  "Paste this URL in your CI config / monitoring tool / Zapier"
  
  [Send Test Request]  [Open Settings]
```

Three clicks → working webhook-to-task pipeline.

## 12. Implementation Notes

### 12.1 Request Processing

```php
// InboxController.php
public function receive(string $slug, Request $request)
{
    $inbox = Inbox::where('slug', $slug)
        ->where('is_active', true)
        ->firstOrFail();

    // Security checks
    if ($inbox->allowed_ips && !$this->checkIp($request, $inbox)) {
        return $this->reject($inbox, $request, 'ip_not_allowed', 403);
    }

    if ($inbox->secret_hash && !$this->checkSignature($request, $inbox)) {
        return $this->reject($inbox, $request, 'invalid_signature', 401);
    }

    // Rate limit
    if ($this->isRateLimited($inbox)) {
        return $this->reject($inbox, $request, 'rate_limited', 429);
    }

    // Payload size
    if ($request->getContentLength() > $inbox->max_payload_bytes) {
        return $this->reject($inbox, $request, 'payload_too_large', 413);
    }

    // Deduplication
    if ($inbox->deduplicate_field) {
        $dedupeKey = data_get($request->json(), $inbox->deduplicate_field);
        if ($existing = $this->findDuplicate($inbox, $dedupeKey)) {
            $this->logRequest($inbox, $request, 'deduplicated', $existing->id);
            return response()->json([
                'task_id' => $existing->id,
                'status' => 'deduplicated'
            ]);
        }
    }

    // Build task payload
    $payload = [
        '_inbox' => [
            'inbox_id' => $inbox->id,
            'inbox_name' => $inbox->name,
            'received_at' => now()->toIso8601String(),
            'source_ip' => $request->ip(),
            'content_type' => $request->header('Content-Type'),
        ],
        '_body' => $request->json()->all(),
    ];

    // Apply transform
    if ($inbox->transform) {
        $payload = array_merge($payload, $this->applyTransform($inbox->transform, $payload['_body']));
    }

    // Create task
    $task = Task::create([
        'hive_id' => $inbox->hive_id,
        'superpos_id' => $inbox->superpos_id,
        'type' => $this->resolveTaskType($inbox, $payload['_body']),
        'target_capability' => $inbox->target_capability,
        'target_agent_id' => $inbox->target_agent_id,
        'priority' => $this->resolvePriority($inbox, $payload['_body']),
        'payload' => $payload,
        'failure_policy' => $inbox->failure_policy,
        'guarantee' => $inbox->guarantee,
    ]);

    // Log + update stats
    $this->logRequest($inbox, $request, 'accepted', $task->id);
    $inbox->increment('request_count');
    $inbox->update(['last_request_at' => now()]);

    return response()->json([
        'task_id' => $task->id,
        'status' => 'pending',
    ], 201);
}
```

### 12.2 Non-JSON Payloads

Inbox accepts any Content-Type:

| Content-Type               | `_body` content                     |
|----------------------------|-------------------------------------|
| `application/json`         | Parsed JSON object                  |
| `application/x-www-form-urlencoded` | Parsed form fields         |
| `text/plain`               | `{ "text": "raw body content" }`   |
| `multipart/form-data`      | Parsed fields (files ignored)       |
| Other                      | `{ "raw": "base64 encoded body" }` |

### 12.3 Response Codes

| Code | Meaning                                   |
|------|-------------------------------------------|
| 201  | Task created                              |
| 200  | Deduplicated (returning existing task — returned for all dedup hits regardless of current task status: pending, in_progress, or completed) |
| 401  | Invalid signature                         |
| 403  | IP not allowed                            |
| 404  | Inbox not found or inactive               |
| 409  | Deduplication lock contention — concurrent requests with the same dedup key collided; client should retry after the `retry_after` value in the response |
| 413  | Payload too large                         |
| 429  | Rate limited                              |

## 13. Permissions

| Permission          | Who           | What                                |
|---------------------|---------------|-------------------------------------|
| `inboxes.read`      | Agent         | List/show inboxes via API           |
| `inboxes.write`     | Agent         | Create/update/delete inboxes via API|
| Admin/Member role   | Dashboard user| Full inbox management               |
| Viewer role         | Dashboard user| View inbox list + logs              |
| (none)              | External      | POST to inbox URL                   |

## 14. Implementation Priority

| Priority | Feature                   | Phase   |
|----------|---------------------------|---------|
| P0       | Basic inbox (URL → task)  | Phase 1 |
| P0       | Dashboard: create + list  | Phase 1 |
| P1       | Signature validation      | Phase 2 |
| P1       | Rate limiting             | Phase 2 |
| P1       | Request log               | Phase 2 |
| P2       | Payload transform         | Phase 3 |
| P2       | IP allowlist              | Phase 3 |
| P2       | Deduplication             | Phase 3 |
| P3       | "Upgrade to Webhook Route"| Phase 4 |

Basic inbox is **Phase 1** material — it's the fastest path to "external event → agent task" and great for demos.

---

*Feature version: 1.0*
*Depends on: PRODUCT.md v4.0 (task system, hives)*
*Complements: Webhook Routes (§13 in PRODUCT.md) — Inbox is the simple path, Routes are the powerful path*
