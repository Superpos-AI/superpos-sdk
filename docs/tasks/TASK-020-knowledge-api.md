# TASK-020: Knowledge Store API (CRUD + Search)

**Status:** done
**Branch:** `task/020-knowledge-api`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/22
**Depends On:** TASK-003 (API Envelope), TASK-009 (Knowledge Model), TASK-011 (ActivityLogger), TASK-012 (Agent Auth), TASK-013 (Permission Middleware)
**Blocked By:** —

## Requirements

### Endpoints

| Method | URI | Permission | Description |
|--------|-----|------------|-------------|
| `GET` | `/api/v1/hives/{hive}/knowledge` | `knowledge.read` | List/filter entries by key pattern and scope |
| `POST` | `/api/v1/hives/{hive}/knowledge` | `knowledge.write` | Create a new knowledge entry |
| `GET` | `/api/v1/hives/{hive}/knowledge/{entry}` | `knowledge.read` | Get a single entry by ID |
| `PUT` | `/api/v1/hives/{hive}/knowledge/{entry}` | `knowledge.write` | Update an existing entry (increments version) |
| `DELETE` | `/api/v1/hives/{hive}/knowledge/{entry}` | `knowledge.write` | Delete an entry |
| `GET` | `/api/v1/hives/{hive}/knowledge/search` | `knowledge.read` | Search entries by key pattern or value content |

### Scope Model

Three scope levels for knowledge entries:

| Scope | Visibility | Write Permission |
|-------|-----------|-----------------|
| `hive` (default) | Agents in same hive | `knowledge.write` |
| `apiary` | All agents across all hives | `knowledge.write_apiary` |
| `agent:{id}` | Only the creating agent | `knowledge.write` |

### Scope Access Rules

- **Hive-scoped entries**: visible only to agents in the same hive
- **Apiary-scoped entries**: visible to all agents in the apiary; require `knowledge.write_apiary` to create/update
- **Agent-scoped entries**: visible only to the owning agent; only the owning agent can update/delete
- Expired entries (past TTL) are excluded from all read/search queries

### Write Rules

- **Create**: Agent becomes `created_by`; `version` starts at 1
- **Update**: Only the creator can update (unless agent has `knowledge.manage`); `version` increments
- **Delete**: Only the creator can delete (unless agent has `knowledge.manage`)
- **Superpos scope**: Requires `knowledge.write_apiary` permission for create/update

### Activity Logging

- `knowledge.created` — on successful create
- `knowledge.updated` — on successful update (includes old/new version)
- `knowledge.deleted` — on successful delete

## Implementation Plan

### Files to Create

1. **`app/Http/Controllers/Api/KnowledgeController.php`** — CRUD + search endpoints
2. **`app/Http/Requests/CreateKnowledgeRequest.php`** — Validation for POST
3. **`app/Http/Requests/UpdateKnowledgeRequest.php`** — Validation for PUT
4. **`tests/Feature/KnowledgeApiTest.php`** — Comprehensive test suite
5. **`docs/guide/knowledge-api.md`** — VitePress public guide

### Files to Modify

1. **`routes/api.php`** — Register knowledge API routes
2. **`TASKS.md`** — Mark TASK-019 as done
3. **`docs/index.md`** — Link to knowledge API guide
4. **`docs/tasks/TASK-019-task-timeout-retry.md`** — Status to done

### Key Design Decisions

- All endpoints are hive-scoped (`/hives/{hive}/knowledge`)
- Controller follows established TaskController pattern (thin, delegates to service helpers)
- Scope visibility enforced in controller (not middleware) for granularity
- Version incremented atomically on update
- Search supports key pattern (LIKE) and optional scope filter
- Expired entries filtered via `notExpired()` scope on all reads

## Test Plan

1. Create entry with minimal payload (key + value)
2. Create entry with full payload (scope, visibility, ttl)
3. Read single entry by ID
4. List entries with key pattern filter
5. List entries with scope filter
6. Update entry (version increments)
7. Delete entry
8. Search by key pattern
9. Search with scope filter
10. Scope isolation: hive-scoped entries invisible across hives
11. Scope isolation: apiary-scoped entries visible across hives
12. Scope isolation: agent-scoped entries visible only to owner
13. Permission: 401 without token
14. Permission: 403 without knowledge.read
15. Permission: 403 without knowledge.write
16. Permission: 403 for apiary scope without knowledge.write_apiary
17. Ownership: only creator can update (without manage permission)
18. Ownership: knowledge.manage bypasses creator check
19. TTL: expired entries excluded from list/search
20. Activity logging for create/update/delete
21. Validation: required fields, max lengths, valid scope values
22. Envelope compliance on all responses
23. Cross-apiary rejection (403)
24. Nonexistent hive (404), nonexistent entry (404)
