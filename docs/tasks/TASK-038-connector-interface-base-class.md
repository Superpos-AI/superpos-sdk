# TASK-038 — Connector Interface + Base Class

**Status:** In Progress
**Branch:** `task/038-connector-interface-base-class`
**Depends On:** TASK-036 (Service Connections)

---

## Objective

Define a `ConnectorInterface` contract and a reusable `BaseConnector` abstract class that all connectors (GitHub, Slack, agent-writable, etc.) will implement. Also create the `Connector` Eloquent model and `connectors` migration per PRODUCT.md schema.

## Requirements

### 1. ConnectorInterface (`app/Contracts/ConnectorInterface.php`)

- `type(): string` — unique connector type slug (e.g., `github`, `slack`)
- `name(): string` — human-readable display name
- `validateWebhook(Request $request, ServiceConnection $connection): bool` — verify webhook signature
- `parseWebhook(Request $request): array` — extract normalized payload from incoming webhook
- `supportsWebhooks(): bool` — whether this connector handles inbound webhooks
- `configurationRules(): array` — Laravel validation rules for `auth_config` shape

### 2. BaseConnector (`app/Connectors/BaseConnector.php`)

- Abstract class implementing `ConnectorInterface`
- Implements `supportsWebhooks()` → `true` (default, overridable)
- Implements `configurationRules()` → `[]` (default, overridable)
- Provides `resolveConnection(string $connectionId): ServiceConnection` helper
- Provides `extractHeader(Request $request, string $header): ?string` helper

### 3. Connector Model (`app/Models/Connector.php`)

- Uses `BelongsToApiary` + `HasUlid` + `HasFactory` traits
- Fields: `superpos_id`, `type`, `name`, `class_path`, `is_builtin`, `created_by`
- Constants for built-in types
- Relations: `apiary()`, `serviceConnections()`
- Scopes: `builtin()`, `custom()`, `ofType()`
- Unique constraint: `(superpos_id, type)`

### 4. Migration (`create_connectors_table`)

Schema from PRODUCT.md section 9.1:
```sql
CREATE TABLE connectors (
    id              VARCHAR(26) PRIMARY KEY,
    superpos_id       VARCHAR(26) NOT NULL REFERENCES apiaries(id) ON DELETE CASCADE,
    type            VARCHAR(100) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    class_path      VARCHAR(500) NOT NULL,
    is_builtin      BOOLEAN DEFAULT FALSE,
    created_by      VARCHAR(26),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(superpos_id, type)
);
```

### 5. ServiceConnection Updates

- Add `connector()` BelongsTo relationship on ServiceConnection model
- Add FK migration: `connector_id` references `connectors(id)` SET NULL on delete

### 6. Superpos Model Update

- Add `connectors()` HasMany relationship

### 7. Factory

- `ConnectorFactory` with `forApiary()`, `builtin()`, `custom()`, `ofType()` states

## Test Plan

- Connector model ULID generation
- BelongsToApiary trait integration (CE auto-set, cloud fail-closed)
- Unique constraint `(superpos_id, type)` enforcement
- Cascade delete: apiary deletion cascades to connectors
- Relationships: `connector.apiary()`, `connector.serviceConnections()`, `apiary.connectors()`
- ServiceConnection → Connector relationship (nullable FK)
- BaseConnector default implementations
- ConnectorInterface contract methods exist

## Files Changed

- `app/Contracts/ConnectorInterface.php` (new)
- `app/Connectors/BaseConnector.php` (new)
- `app/Models/Connector.php` (new)
- `database/migrations/..._create_connectors_table.php` (new)
- `database/migrations/..._add_connector_fk_to_service_connections.php` (new)
- `database/factories/ConnectorFactory.php` (new)
- `app/Models/ServiceConnection.php` (edit — add connector relationship)
- `app/Models/Superpos.php` (edit — add connectors relationship)
- `tests/Feature/ConnectorModelTest.php` (new)
- `tests/Unit/BaseConnectorTest.php` (new)
