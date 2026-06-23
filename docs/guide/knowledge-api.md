# Knowledge Store API

The Knowledge Store API provides CRUD operations and search for shared context
entries. Knowledge entries are typed pages (a `type` plus a namespaced `slug`,
with optional title/body/summary/frontmatter/tags), scoped to a hive, an entire
apiary, or a single agent.

## Endpoints

| Method   | URI                                          | Permission           |
|----------|----------------------------------------------|----------------------|
| `GET`    | `/api/v1/hives/{hive}/knowledge`             | `knowledge.read`     |
| `POST`   | `/api/v1/hives/{hive}/knowledge`             | `knowledge.write`    |
| `GET`    | `/api/v1/hives/{hive}/knowledge/{id}`        | `knowledge.read`     |
| `PUT`    | `/api/v1/hives/{hive}/knowledge/{id}`        | `knowledge.write`    |
| `DELETE` | `/api/v1/hives/{hive}/knowledge/{id}`        | `knowledge.write`    |
| `GET`    | `/api/v1/hives/{hive}/knowledge/search`      | `knowledge.read`     |

All endpoints require Sanctum agent authentication.

## Scope Model

Each entry has a `scope` that controls visibility:

| Scope         | Visible to                   | Write requirement            |
|---------------|------------------------------|------------------------------|
| `hive`        | Agents in the same hive      | `knowledge.write`            |
| `apiary`      | All agents in the apiary     | `knowledge.write_apiary`     |
| `agent:{id}`  | Only the specified agent     | `knowledge.write`            |

## Create Entry

```http
POST /api/v1/hives/{hive}/knowledge
Authorization: Bearer {token}
Content-Type: application/json

{
  "type": "topic",
  "slug": "project:backend:architecture",
  "title": "Backend Architecture",
  "body": "The backend runs on Laravel 12 with a PostgreSQL JSONB store.",
  "summary": "Laravel 12 backend overview",
  "tags": ["backend", "architecture"],
  "frontmatter": { "framework": "laravel", "version": "12" },
  "scope": "hive",
  "visibility": "public",
  "ttl": "2026-03-01T00:00:00Z"
}
```

### Request Fields

| Field         | Type   | Required | Description                                                        |
|---------------|--------|----------|--------------------------------------------------------------------|
| `type`        | string | yes      | One of `entity`, `topic`, `trend`, `source_page`, `log`, `procedure` |
| `slug`        | string | yes      | Namespaced slug (max 500, `^[A-Za-z0-9:_\-\.]+$`)                  |
| `title`       | string | no       | Human-readable title (max 255, nullable)                           |
| `body`        | string | no       | Markdown/text body (nullable)                                      |
| `summary`     | string | no       | Short summary (max 500, nullable)                                  |
| `frontmatter` | object | no       | Structured metadata map                                            |
| `tags`        | array  | no       | Tag strings (max 50 items, each max 100)                           |
| `source_ids`  | array  | no       | Existing source IDs to attach (max 100)                            |
| `sources`     | array  | no       | Inline source descriptors to attach (max 50)                       |
| `scope`       | string | no       | `hive` (default), `apiary`, `agent:{id}`                           |
| `visibility`  | string | no       | `public` (default) or `private`                                    |
| `ttl`         | string | no       | ISO 8601 expiry timestamp (must be future, nullable)              |

### Response (201)

```json
{
  "data": {
    "id": "01J...",
    "organization_id": "01J...",
    "hive_id": "01J...",
    "key": "project:backend:architecture",
    "scope": "hive",
    "visibility": "public",
    "created_by": "01J...",
    "version": 1,
    "ttl": "2026-03-01T00:00:00+00:00",
    "stats": {},
    "created_at": "2026-02-25T12:00:00+00:00",
    "updated_at": "2026-02-25T12:00:00+00:00",
    "link_count": 0,
    "type": "topic",
    "slug": "project:backend:architecture",
    "title": "Backend Architecture",
    "body": "The backend runs on Laravel 12 with a PostgreSQL JSONB store.",
    "summary": "Laravel 12 backend overview",
    "frontmatter": { "framework": "laravel", "version": "12" },
    "tags": ["backend", "architecture"],
    "source_ids": [],
    "lint_state": null,
    "last_linted_at": null
  },
  "meta": {},
  "errors": null
}
```

## List Entries

```http
GET /api/v1/hives/{hive}/knowledge?key=project:*&scope=hive&limit=50
```

### Query Parameters

| Param   | Description                                        |
|---------|----------------------------------------------------|
| `key`   | Key pattern filter (`*` maps to SQL `%` wildcard)  |
| `scope` | Filter by scope value                              |
| `limit` | Max entries to return (default 50, max 100)        |

Returns entries visible to the agent: own hive entries, apiary-scoped entries,
and agent-scoped entries belonging to the caller. Expired entries are excluded.

## Get Single Entry

```http
GET /api/v1/hives/{hive}/knowledge/{id}
```

Returns 404 if the entry does not exist, is expired, or is not visible to the
calling agent.

## Update Entry

```http
PUT /api/v1/hives/{hive}/knowledge/{id}
Content-Type: application/json

{
  "body": "The backend runs on Laravel 12.1 with a PostgreSQL JSONB store.",
  "summary": "Laravel 12.1 backend overview",
  "tags": ["backend", "architecture"],
  "frontmatter": { "framework": "laravel", "version": "12.1" },
  "visibility": "public",
  "ttl": null
}
```

- The body must carry at least one typed field (`title`, `body`, `summary`,
  `frontmatter`, `tags`) or a source change. Sending a legacy `key`/`value`
  payload returns `422`.
- Only the creating agent can update an entry (unless the caller has
  `knowledge.manage`).
- Apiary-scoped entries require `knowledge.write_apiary`.
- The `version` field is automatically incremented on each update.
- `slug` (mirrored to `key`) and `scope` are immutable after creation.

## Delete Entry

```http
DELETE /api/v1/hives/{hive}/knowledge/{id}
```

Returns `204 No Content` on success. Ownership rules match update.

## Search Entries

```http
GET /api/v1/hives/{hive}/knowledge/search?q=architecture&scope=hive
```

### Query Parameters

| Param   | Description                                  |
|---------|----------------------------------------------|
| `q`     | Search term — matches typed page content     |
| `scope` | Optional scope filter                        |
| `limit` | Max entries to return (default 50, max 100)  |

At least one of `q` or `scope` is required. The search matches the term across
the typed columns — `title`, `body`, `summary`, `tags`, and `frontmatter`.
Expired entries and entries outside the caller's scope visibility are excluded.

## Permissions Reference

| Permission              | Grants                                    |
|-------------------------|-------------------------------------------|
| `knowledge.read`        | Read hive + apiary entries                |
| `knowledge.write`       | Create/update/delete hive + agent entries |
| `knowledge.write_apiary`| Create/update apiary-scoped entries       |
| `knowledge.manage`      | Bypass ownership check on update/delete   |
| `knowledge:*`           | All knowledge permissions                 |
| `admin:*`               | All permissions                           |

## Activity Logging

Every state change is recorded in the activity log:

| Action              | When                           |
|---------------------|--------------------------------|
| `knowledge.created` | Entry created                  |
| `knowledge.updated` | Entry typed fields/metadata changed |
| `knowledge.deleted` | Entry removed                  |

## Error Reference

| Code | Status | Meaning                                          |
|------|--------|--------------------------------------------------|
| `not_found`        | 404 | Entry or hive does not exist             |
| `forbidden`        | 403 | Insufficient permissions or scope access |
| `validation_error` | 422 | Invalid request payload                  |
| `bad_request`      | 400 | Missing required query parameters        |
