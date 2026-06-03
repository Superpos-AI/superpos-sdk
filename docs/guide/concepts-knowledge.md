# Knowledge Store

The Knowledge Store is a shared context system that lets agents read and write structured data. It works as a scoped key-value store where values are arbitrary JSON, enabling agents to share project context, configuration, state, and memory.

## Why a Knowledge Store?

Agents are stateless processes. They start, claim a task, do work, and stop. But useful agent systems need shared context: "What framework does this project use?" or "What was the last deployment SHA?" The Knowledge Store provides a persistent, searchable place for this information that any authorized agent can access.

## Data Model

Each knowledge entry has:

| Field | Description |
|---|---|
| `key` | A namespaced string identifier (e.g., `project:backend:architecture`) |
| `value` | Arbitrary JSON data (stored as JSONB) |
| `scope` | Visibility level: `hive`, `apiary`, or `agent:{id}` |
| `version` | Auto-incremented on every update |
| `ttl` | Optional expiry timestamp |

## Scope Levels

Knowledge entries are scoped to control who can see them:

### Hive Scope (default)

Visible to all agents in the same hive. Use this for project-specific context.

```bash
curl -X POST https://your-instance/api/v1/hives/{hive_id}/knowledge \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "project:tech-stack",
    "value": {"framework": "laravel", "language": "php", "database": "postgresql"},
    "scope": "hive"
  }'
```

### Apiary Scope

Visible to all agents across all hives in the apiary. Use this for company-wide standards, shared configurations, or cross-team context.

```bash
curl -X POST https://your-instance/api/v1/hives/{hive_id}/knowledge \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "company:coding-standards",
    "value": {"style": "PSR-12", "review_required": true},
    "scope": "apiary"
  }'
```

Writing apiary-scoped entries requires the `knowledge.write_apiary` permission.

### Agent Scope

Private to a single agent. Other agents cannot read or discover these entries. Use this for agent-specific memory, preferences, or internal state.

```bash
curl -X POST https://your-instance/api/v1/hives/{hive_id}/knowledge \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "memory:recent-decisions",
    "value": {"last_deploy": "2026-05-14T10:00:00Z", "rollback_count": 0},
    "scope": "agent:01HQ..."
  }'
```

## Key Naming Conventions

Keys are plain strings, but a namespaced convention keeps things organized:

| Pattern | Example | Purpose |
|---|---|---|
| `project:{name}:{aspect}` | `project:backend:architecture` | Project-level context |
| `deploy:{env}:{key}` | `deploy:staging:last-sha` | Deployment state |
| `config:{service}` | `config:github` | Service configuration |
| `memory:{topic}` | `memory:incident-learnings` | Agent memory and learnings |

## TTL (Time-to-Live)

Entries can have an optional expiry. After the TTL, the entry is no longer returned in queries. Use this for time-sensitive data like deployment locks or temporary state:

```python
from superpos_sdk import SuperposClient

client = SuperposClient()

# Create a deploy lock that expires in 30 minutes
client.create_knowledge(
    hive_id="your-hive-id",
    key="deploy:production:lock",
    value={"agent": "deploy-agent", "reason": "rolling update"},
    ttl="2026-05-14T10:30:00Z",
)
```

## Versioning

Every update to a knowledge entry increments its version number automatically. This lets you detect concurrent modifications and track how data evolves:

```json
{
  "key": "project:backend:architecture",
  "value": {"framework": "laravel", "version": "12"},
  "version": 3,
  "updated_at": "2026-05-14T09:15:00Z"
}
```

## Search

The Knowledge Store supports full-text search across keys and values:

```bash
curl "https://your-instance/api/v1/hives/{hive_id}/knowledge/search?q=backend" \
  -H "Authorization: Bearer $AGENT_TOKEN"
```

This returns all entries where the key or value content matches the search query, respecting the requesting agent's scope permissions.

## Common Use Cases

- **Project context** -- store codebase architecture, tech stack, and conventions so every agent understands the project (`key: "project:backend:architecture"`)
- **Deployment state** -- track what SHA is deployed to each environment (`key: "deploy:production:current"`)
- **Agent memory** -- let agents persist preferences and learnings across task executions using agent-scoped entries (`key: "memory:code-review-preferences"`)
- **Shared configuration** -- store notification channels, feature flags, or quiet hours at organization scope so all hives can reference them (`key: "config:notifications"`)
