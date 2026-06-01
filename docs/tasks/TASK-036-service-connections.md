# TASK-036: Service Connections Migration + Model

**Phase:** 2 — Service Proxy & Security
**Status:** done
**Depends On:** TASK-006 (Superpos & Hive models)
**Branch:** `task/036-service-connections`

---

## Objective

Create the `service_connections` database table and corresponding Eloquent model. Service connections are **apiary-level** resources that store external service configuration with encrypted credentials, shared across all hives within an apiary.

## Requirements

### Migration

Create `service_connections` table with:

| Column | Type | Notes |
|--------|------|-------|
| `id` | `string(26)` PK | ULID |
| `superpos_id` | `string(26)` FK | References `apiaries(id)`, cascade delete |
| `name` | `string(255)` | Human-readable name |
| `type` | `string(100)` | Service type (e.g., `github`, `slack`, `custom`) |
| `base_url` | `string(500)` | Base URL for the service |
| `auth_type` | `string(50)` | Auth method (`token`, `oauth2`, `basic`, `api_key`, `none`) |
| `auth_config` | `text` | **Encrypted** credentials (Laravel Crypt) |
| `connector_id` | `string(26)` nullable | Future FK to connectors table (TASK-038) |
| `webhook_secret` | `text` nullable | **Encrypted** webhook verification secret |
| `is_active` | `boolean` | Default `true` |
| `created_at` | `timestamp` | |
| `updated_at` | `timestamp` | |

**Indexes:**
- `UNIQUE(superpos_id, name)` — one service name per apiary
- `index(superpos_id)` — for apiary-scoped queries
- `index(type)` — for filtering by service type

### Model

- Uses traits: `HasUlid`, `HasFactory`, `BelongsToApiary`
- `auth_config` and `webhook_secret` cast as `encrypted` (Laravel encrypted casting)
- `is_active` cast as `boolean`
- Constants for valid `auth_type` values and common `type` values
- Relationships: `apiary()` (via trait)
- Helper methods: `isActive()`, scope `active()`, scope `ofType()`

### Factory

- `ServiceConnectionFactory` with `forApiary()` state helper
- States: `active()`, `inactive()`, `ofType()`, `withAuthType()`

## Test Plan

1. ULID auto-generation
2. Fillable fields round-trip
3. `auth_config` encryption (stored encrypted, read decrypted)
4. `webhook_secret` encryption
5. `is_active` boolean cast and default
6. BelongsToApiary trait integration (CE mode auto-scoping)
7. Cloud mode creation fails without context
8. Cascade delete when apiary is deleted
9. Unique constraint on `(superpos_id, name)`
10. Relationship: `apiary()` returns parent
11. Query scopes: `active()`, `ofType()`
12. Helper: `isActive()`

## Design Decisions

- `connector_id` is nullable with no FK constraint — connectors table created in TASK-038
- Credentials encrypted with Laravel's `encrypted` cast (uses `APP_KEY`)
- Apiary-level only — no `hive_id` column; service connections are org-wide
- `auth_config` stores the full auth configuration as encrypted JSON string
- `auth_config` and `webhook_secret` are hidden from JSON serialization (`$hidden`) to prevent accidental credential exposure in API responses
- Common service types defined as model constants: `github`, `slack`, `jira`, `linear`, `custom`
- Auth type constants match the proxy's supported methods: `token`, `oauth2`, `basic`, `api_key`, `none`
- The `BelongsToApiary` trait automatically scopes all queries to the current apiary and sets `superpos_id` on creation
- In CE mode, `superpos_id` resolves to `'default'` — no multi-tenancy overhead

## Related

- **Upstream:** TASK-006 (Superpos & Hive models provide the `apiaries` table and `BelongsToApiary` trait)
- **Downstream:** TASK-037 (Credential vault uses service connections), TASK-038 (Connector interface populates `connector_id`), TASK-042 (Service proxy controller reads connection config)
- **Spec reference:** PRODUCT.md §11 (Service Proxy & Credentials Vault), §9.1 (service_connections schema)
