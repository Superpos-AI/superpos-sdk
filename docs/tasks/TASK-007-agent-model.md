# TASK-007 — Agent Migration + Model + Permissions

| Field       | Value                                    |
|-------------|------------------------------------------|
| **ID**      | 007                                      |
| **Title**   | Agent migration + model + permissions    |
| **Status**  | done                                     |
| **Depends** | 005 (migrations), 006 (Superpos/Hive models) |
| **Branch**  | `task/007-agent-model`                   |

---

## Objective

Create the `agents` and `agent_permissions` database tables and their
corresponding Eloquent models. Agents are the primary actors in the system —
all API interactions, task claiming, knowledge access, and service proxy
calls are performed by agents.

## Schema

### `agents` table

| Column              | Type         | Constraints                          |
|---------------------|--------------|--------------------------------------|
| id                  | CHAR(26)     | PRIMARY KEY (ULID)                   |
| superpos_id           | CHAR(26)     | FK → apiaries, CASCADE DELETE        |
| hive_id             | CHAR(26)     | FK → hives, CASCADE DELETE           |
| name                | VARCHAR(255) | NOT NULL                             |
| type                | VARCHAR(100) | NOT NULL, DEFAULT 'custom'           |
| capabilities        | JSONB        | DEFAULT '[]'                         |
| status              | VARCHAR(20)  | DEFAULT 'offline'                    |
| api_token_hash      | VARCHAR(255) | NULLABLE                             |
| metadata            | JSONB        | DEFAULT '{}'                         |
| last_heartbeat      | TIMESTAMP    | NULLABLE                             |
| created_at          | TIMESTAMP    |                                      |
| updated_at          | TIMESTAMP    |                                      |

Indexes: `(hive_id, status)`, `(superpos_id)`.

### `agent_permissions` table

| Column     | Type         | Constraints                          |
|------------|--------------|--------------------------------------|
| agent_id   | CHAR(26)     | FK → agents, CASCADE DELETE          |
| permission | VARCHAR(100) | NOT NULL                             |
| granted_by | VARCHAR(255) | NULLABLE                             |
| created_at | TIMESTAMP    |                                      |

Composite primary key: `(agent_id, permission)`.

## Models

### `App\Models\Agent`

- Traits: `HasFactory`, `HasUlid`, `BelongsToHive`
- Fillable: name, type, capabilities, status, api_token_hash, metadata,
  last_heartbeat, superpos_id, hive_id
- Casts: capabilities → array, metadata → array, last_heartbeat → datetime
- Relationships:
  - `hive()` — via BelongsToHive trait
  - `apiary()` — via BelongsToHive trait
  - `permissions()` — HasMany → AgentPermission
- Helper methods:
  - `isOnline(): bool` — status === 'online'
  - `hasPermission(string $permission): bool` — checks permission or wildcard
  - `grantPermission(string $permission, ?string $grantedBy): void`
  - `revokePermission(string $permission): void`

### `App\Models\AgentPermission`

- Traits: `HasUlid` not needed (composite PK)
- No incrementing, no auto-ID
- Table: `agent_permissions`
- Fillable: agent_id, permission, granted_by
- Relationships:
  - `agent()` — BelongsTo → Agent

## Permission Strings

Per PRODUCT.md, the valid permission strings are:
- `tasks:create`, `tasks:manage`
- `knowledge:read`, `knowledge:write`, `knowledge:write_apiary`, `knowledge:manage`
- `manage:webhook_routes`, `manage:connectors`, `manage:agents`, `manage:policies`
- `services:{service_id}`, `services:*`
- `cross_hive:{hive_slug}`, `cross_hive:*`
- `admin:*`

## Tests

- Agent ULID generation and key type
- Fillable fields
- Casts (capabilities, metadata, last_heartbeat)
- BelongsToHive auto-scoping (CE mode)
- Relationship: agent → hive, agent → apiary, agent → permissions
- Permission grant/revoke/check (including wildcard matching)
- AgentPermission composite key behavior
- Cascade delete: deleting hive deletes agents, deleting agent deletes permissions

## Acceptance Criteria

- [ ] Migration creates `agents` and `agent_permissions` tables
- [ ] Agent model uses HasUlid + BelongsToHive traits
- [ ] Permission helper methods support wildcard matching
- [ ] All tests pass
- [ ] No regressions in existing test suite
