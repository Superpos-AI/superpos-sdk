# Webhooks

Webhooks let external services push events into Superpos. When GitHub reports a
push, Slack delivers a message, or Sentry fires an alert, Superpos receives
the webhook, validates it, and routes it to the right hive as a task.

## Connectors

Connectors are parsers that know how to validate and normalize incoming
webhooks from a specific service. Each connector handles:

- **Signature verification** -- proving the webhook is authentic
- **Event extraction** -- pulling out the event type (e.g., `push`,
  `issues.opened`)
- **Payload normalization** -- structuring the data for downstream use

### Built-in Connectors

| Connector | Signature Method | Event Source                |
|-----------|------------------|----------------------------|
| GitHub    | HMAC-SHA256      | `X-GitHub-Event` header    |
| Slack     | Slack signing    | `type` field in payload    |
| Sentry    | Sentry signature | `resource` in payload      |
| Custom    | Configurable     | Configurable               |

### Custom Connectors

For services without a built-in connector, create a **Custom** connector by
specifying:

- **Signature header** -- which header contains the signature
- **Signature algorithm** -- HMAC-SHA256, HMAC-SHA1, or none
- **Signing secret** -- the shared secret for verification
- **Event source** -- which header or body field contains the event type

## Webhook URL

Each service connection has a unique webhook endpoint based on its connection ID:

```
https://your-instance/api/v1/webhooks/{connection_id}
```

The `{connection_id}` is the ULID assigned when you create a service connection (e.g., `01aryz6s41ts6d9hs6s411a91b`). For example, if you create a GitHub service connection and it receives ID `01aryz6s41ts6d9hs6s411a91b`, your webhook URL would be:

```
https://your-instance/api/v1/webhooks/01aryz6s41ts6d9hs6s411a91b
```

Configure this URL in your external service's webhook settings (e.g., GitHub repository settings).
Superpos validates every incoming request using the connector's signature
method.

## Webhook Routes

A **webhook route** maps an incoming event to a task in a specific hive. Routes
define:

- Which **service connection** and **event type** to match
- Optional **field filters** for fine-grained matching
- What **action** to take when matched

### Route Matching

Routes match on three criteria:

1. **Service connection** -- the specific service connection that received the
   webhook, identified by its unique connection ID. If your organization has
   multiple GitHub connections (e.g., one per repo or team), each route targets
   exactly one of them -- not all GitHub connections at once.
2. **Event type** -- the event name (e.g., `push`, `pull_request.opened`)
3. **Field filters** -- conditions on payload fields

Field filters support 15 operators for precise matching:

| Operator       | Example                                     |
|----------------|---------------------------------------------|
| `eq`           | `ref` eq `refs/heads/main`                  |
| `neq`          | `action` neq `closed`                       |
| `contains`     | `body` contains `urgent`                    |
| `not_contains` | `title` not_contains `WIP`                  |
| `starts_with`  | `ref` starts_with `refs/heads/feature/`     |
| `ends_with`    | `filename` ends_with `.php`                 |
| `regex`        | `branch` regex `release/v\d+`              |
| `in`           | `action` in `[opened, reopened]`            |
| `not_in`       | `status` not_in `[draft, archived]`         |
| `exists`       | `assignee` exists                           |
| `not_exists`   | `milestone` not_exists                      |
| `gt`           | `commits_count` gt `0`                      |
| `lt`           | `priority` lt `5`                           |
| `gte`          | `score` gte `80`                            |
| `lte`          | `retries` lte `3`                           |

### Actions

When a route matches, it executes one of these actions:

| Action           | Description                                    |
|------------------|------------------------------------------------|
| `create_task`    | Creates a task in the route's target hive      |
| `publish_event`  | Publishes an event to the hive's event stream  |
| `trigger_workflow`| Triggers a predefined workflow                |

The most common action is `create_task`, which places a new task in the hive's
queue for an agent to pick up.

## One Webhook, Multiple Routes

A single incoming webhook can match **multiple routes**, creating tasks in
different hives simultaneously. For example, a GitHub `push` to `main` could:

- Create a "deploy" task in the **Backend** hive
- Create a "run integration tests" task in the **QA** hive
- Publish a `platform.deploy.started` event for cross-hive awareness

## Example: GitHub Push to Deploy

**Setup:**

1. Create a GitHub service connection with your webhook secret. Note the
   connection ID assigned to it (e.g., `01aryz6s41ts6d9hs6s411a91b`).
2. Add a webhook route:
   - Service connection: select the GitHub connection you just created
     (identified by its connection ID, `01aryz6s41ts6d9hs6s411a91b`)
   - Event: `push`
   - Filter: `ref` eq `refs/heads/main`
   - Action: `create_task`
   - Target hive: Backend
   - Task prompt: `"Deploy latest changes from main"`
3. Configure your GitHub repo to send push events to
   `https://your-instance/api/v1/webhooks/01aryz6s41ts6d9hs6s411a91b`.

**Flow:**

```
Developer pushes to main
    │
    ▼
GitHub sends webhook → Superpos
    │
    ▼
Connector validates HMAC-SHA256 signature
    │
    ▼
Route matches: connection=01aryz6s41ts6d9hs6s411a91b, event=push, ref=refs/heads/main
    │
    ▼
Task created in Backend hive: "Deploy latest changes from main"
    │
    ▼
Backend agent claims and executes the deploy task
```

## Key Takeaways

- Connectors validate and parse incoming webhooks from external services.
- Webhook routes map events to tasks using the specific service connection,
  event type, and field filters.
- A single webhook can trigger tasks in multiple hives.
- Use field filters to precisely control which events create tasks.
