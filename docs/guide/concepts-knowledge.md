# Knowledge Store

The Knowledge Store is a shared context system that lets agents read and write structured data. Each entry is a typed page — a `type` plus a namespaced `slug`, with optional title, body, summary, frontmatter, and tags — scoped to a hive, an entire apiary, or a single agent. This enables agents to share project context, configuration, state, and memory.

## Why a Knowledge Store?

Agents are stateless processes. They start, claim a task, do work, and stop. But useful agent systems need shared context: "What framework does this project use?" or "What was the last deployment SHA?" The Knowledge Store provides a persistent, searchable place for this information that any authorized agent can access.

## Data Model

Each knowledge entry has:

| Field | Description |
|---|---|
| `type` | Page type — one of `entity`, `topic`, `trend`, `source_page`, `log`, `procedure` (required) |
| `slug` | A namespaced identifier (e.g., `project:backend:architecture`); max 500 chars, matching `^[A-Za-z0-9:_\-\.]+$` (required) |
| `title` | Optional human-readable title (max 255 chars) |
| `body` | Optional Markdown/text body |
| `summary` | Optional short summary (max 500 chars) |
| `frontmatter` | Optional structured metadata map (object) |
| `tags` | Optional array of tag strings (max 50 items, each max 100 chars) |
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
    "type": "topic",
    "slug": "project:tech-stack",
    "title": "Project Tech Stack",
    "body": "The project runs on Laravel (PHP) with a PostgreSQL database.",
    "frontmatter": {"framework": "laravel", "language": "php", "database": "postgresql"},
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
    "type": "procedure",
    "slug": "company:coding-standards",
    "title": "Coding Standards",
    "body": "All PHP follows PSR-12. Every change requires review.",
    "frontmatter": {"style": "PSR-12", "review_required": true},
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
    "type": "log",
    "slug": "memory:recent-decisions",
    "title": "Recent Decisions",
    "body": "Last deploy on 2026-05-14; no rollbacks since.",
    "frontmatter": {"last_deploy": "2026-05-14T10:00:00Z", "rollback_count": 0},
    "scope": "agent:01HQ..."
  }'
```

## Slug Naming Conventions

A page's `slug` must match `^[A-Za-z0-9:_\-\.]+$`, but a namespaced convention keeps things organized. Pair each slug with the `type` that best describes the page:

| Pattern | Example | Suggested type | Purpose |
|---|---|---|---|
| `project:{name}:{aspect}` | `project:backend:architecture` | `topic` | Project-level context |
| `deploy:{env}:{key}` | `deploy:staging:last-sha` | `log` | Deployment state |
| `config:{service}` | `config:github` | `entity` | Service configuration |
| `memory:{topic}` | `memory:incident-learnings` | `log` | Agent memory and learnings |

## TTL (Time-to-Live)

Entries can have an optional expiry. After the TTL, the entry is no longer returned in queries. Use this for time-sensitive data like deployment locks or temporary state:

```python
from superpos_sdk import SuperposClient

client = SuperposClient()

# Create a deploy lock that expires in 30 minutes
client.create_knowledge(
    hive_id="your-hive-id",
    type="log",
    slug="deploy:production:lock",
    title="Production deploy lock",
    body="Held by deploy-agent for a rolling update.",
    frontmatter={"agent": "deploy-agent", "reason": "rolling update"},
    ttl="2026-05-14T10:30:00Z",
)
```

## Versioning

Every update to a knowledge entry increments its version number automatically. This lets you detect concurrent modifications and track how data evolves:

```json
{
  "type": "topic",
  "slug": "project:backend:architecture",
  "title": "Backend Architecture",
  "body": "The backend runs on Laravel 12 with a PostgreSQL JSONB store.",
  "frontmatter": {"framework": "laravel", "version": "12"},
  "version": 3,
  "updated_at": "2026-05-14T09:15:00Z"
}
```

## Search

The Knowledge Store supports full-text search across the typed page columns:

```bash
curl "https://your-instance/api/v1/hives/{hive_id}/knowledge/search?q=backend" \
  -H "Authorization: Bearer $AGENT_TOKEN"
```

This returns all entries where the typed page content matches the search query. The term is matched across the typed columns — `title`, `body`, `summary`, `tags`, and `frontmatter` — respecting the requesting agent's scope permissions.

## Common Use Cases

- **Project context** -- store codebase architecture, tech stack, and conventions so every agent understands the project (`type: "topic"`, `slug: "project:backend:architecture"`)
- **Deployment state** -- track what SHA is deployed to each environment (`type: "log"`, `slug: "deploy:production:current"`)
- **Agent memory** -- let agents persist preferences and learnings across task executions using agent-scoped entries (`type: "log"`, `slug: "memory:code-review-preferences"`)
- **Shared configuration** -- store notification channels, feature flags, or quiet hours at organization scope so all hives can reference them (`type: "entity"`, `slug: "config:notifications"`)
