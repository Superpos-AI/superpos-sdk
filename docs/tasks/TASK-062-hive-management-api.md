# TASK-062: Hive Management API

**Status:** In Progress
**Depends On:** 006 (Hive model), 012 (Agent auth)
**Branch:** `task/062-hive-management-api`

## Summary

Add a CRUD API for managing hives (projects) within an apiary. This is an org-level (apiary-scoped) API that allows agents with appropriate permissions to list, create, update, and delete hives.

## Endpoints

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/api/v1/hives` | `hives.read` | List hives in agent's apiary |
| POST | `/api/v1/hives` | `hives.manage` | Create a new hive |
| GET | `/api/v1/hives/{hive}` | `hives.read` | Show single hive |
| PUT | `/api/v1/hives/{hive}` | `hives.manage` | Update hive |
| DELETE | `/api/v1/hives/{hive}` | `hives.manage` | Delete hive |

## Requirements

1. All endpoints require `auth:sanctum-agent` authentication
2. Read endpoints require `hives.read` permission
3. Write endpoints require `hives.manage` permission
4. Superpos isolation: agents can only see/modify hives in their own apiary
5. CE mode: block creating additional hives and deleting the singleton
6. Delete safety: refuse deletion if hive has active agents or pending tasks
7. Slug uniqueness enforced per apiary (409 on duplicate)
8. Activity logging on all state changes
9. Standard API envelope format on all responses

## Test Plan

- CRUD happy paths (list, create, show, update, delete)
- Permission enforcement (403 without required permissions)
- Authentication enforcement (401 without token)
- Tenant isolation (cross-apiary access blocked)
- CE mode protections (no create, no delete of singleton)
- Delete safety checks (active agents, pending tasks)
- Validation errors (missing fields, invalid slug format)
- Duplicate slug conflict (409)
- Activity log verification
- API envelope compliance

## Files

- `app/Http/Controllers/Api/HiveController.php`
- `app/Http/Requests/StoreHiveRequest.php`
- `app/Http/Requests/UpdateHiveRequest.php`
- `routes/api.php` (modified)
- `tests/Feature/HiveApiTest.php`
