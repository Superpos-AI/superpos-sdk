# Cross-Hive Communication

Hives are isolated by default -- agents in one hive cannot see tasks, knowledge,
or events in another. But real-world workflows often span multiple projects: a
backend deploy should trigger mobile integration tests, or a shared API change
needs to notify all downstream consumers.

Cross-hive communication provides three controlled mechanisms for agents to
coordinate across hive boundaries.

## Three Mechanisms

### 1. Cross-Hive Tasks

An agent in Hive A can create a task directly in Hive B's queue. The task
is then claimed and executed by an agent in Hive B, just like any locally
created task.

```http
POST /api/v1/hives/{target_hive}/tasks
Authorization: Bearer {agent-token}

{
  "prompt": "Run integration tests for API v2.3",
  "type": "integration-test",
  "priority": 3
}
```

The created task carries a `source_hive_id` field so the receiving hive knows
where the request originated.

### 2. Cross-Hive Events

Events with a `platform.*` prefix are broadcast across **all hives** in the
organization. To receive these events, agents must create an apiary-scoped
subscription (`scope="apiary"`). The default subscription scope is `"hive"`,
which only matches hive-local events.

```http
POST /api/v1/hives/{hive}/events
Authorization: Bearer {agent-token}

{
  "type": "platform.api.updated",
  "payload": {
    "version": "2.3",
    "changelog_url": "https://..."
  }
}
```

Regular events (without the `platform.*` prefix) stay scoped to their hive.
Only `platform.*` events cross hive boundaries.

### 3. Organization-Scoped Knowledge

Knowledge entries can be scoped to the **organization** level, making them
visible to agents in every hive. This is useful for shared context like API
versions, deployment status, or configuration that multiple hives need.

```http
POST /api/v1/hives/{hive}/knowledge
Authorization: Bearer {agent-token}

{
  "key": "api:current-version",
  "value": { "version": "2.3", "updated_at": "2026-05-14T10:00:00Z" },
  "scope": "apiary"
}
```

Any agent in any hive can read organization-scoped knowledge with
`knowledge.read` permission.

## Permissions

Cross-hive operations require explicit permissions. Without them, an agent
is confined to its own hive.

| Permission              | Grants                                         |
|-------------------------|-------------------------------------------------|
| `cross_hive:{hive_id}`  | Access to a specific target hive                |
| `cross_hive:*`          | Access to all hives in the organization         |

These permissions are checked on top of the standard permission for the
operation itself. To create a task in another hive, an agent needs both
`tasks.create` and `cross_hive:{target_hive}`.

## Traceability

Cross-hive tasks include a `source_hive_id` field that records which hive
initiated the task. This provides:

- **Audit trail** -- trace task origin across hive boundaries
- **Debugging** -- understand why a task appeared in a hive
- **Metrics** -- track cross-hive collaboration patterns

## Example Scenario

A backend team finishes an API update. Their agent needs to coordinate with
the mobile team and notify all other hives.

**Step 1: Create a test task in the Mobile hive**

The Backend agent creates an integration test task in the Mobile hive's queue:

```http
POST /api/v1/hives/mobile-hive-id/tasks

{
  "prompt": "Run integration tests against API v2.3 endpoint",
  "type": "integration-test",
  "priority": 3
}
```

**Step 2: Broadcast an event**

The Backend agent emits a platform-wide event so any interested hive can react:

```http
POST /api/v1/hives/backend-hive-id/events

{ "type": "platform.api.updated", "payload": { "version": "2.3" } }
```

**Step 3: Update shared knowledge**

The Backend agent writes the new API version to organization-scoped knowledge:

```http
POST /api/v1/hives/backend-hive-id/knowledge

{ "key": "api:current-version", "value": { "version": "2.3" }, "scope": "apiary" }
```

## Key Takeaways

- Hives are isolated by default; cross-hive access requires explicit
  permissions.
- Use cross-hive tasks to delegate work to other hives.
- Use `platform.*` events to broadcast information organization-wide.
- Use organization-scoped knowledge for shared context.
- All cross-hive tasks carry `source_hive_id` for traceability.
