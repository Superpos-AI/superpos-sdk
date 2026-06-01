# TASK-043: Action Policies Migration + Model

**Phase:** 2 — Service Proxy & Security
**Status:** in progress
**Depends On:** TASK-006 (Superpos & Hive models), TASK-007 (Agent model)
**Branch:** `task/043-action-policies`

---

## Objective

Create the `action_policies` database table and corresponding Eloquent model. Action policies are **hive-scoped** per-agent per-service firewall rules that control what HTTP methods and paths an agent may access on a given service connection.

## Requirements

### Migration

Create `action_policies` table with:

| Column | Type | Notes |
|--------|------|-------|
| `id` | `string(26)` PK | ULID |
| `superpos_id` | `string(26)` FK | References `apiaries(id)`, cascade delete |
| `hive_id` | `string(26)` FK | References `hives(id)`, cascade delete |
| `agent_id` | `string(26)` FK | References `agents(id)`, cascade delete |
| `service_id` | `string(26)` FK | References `service_connections(id)`, cascade delete |
| `rules` | `jsonb` | Policy rules: `{ allow: [], deny: [], require_approval: [] }` |
| `is_active` | `boolean` | Default `true` |
| `created_at` | `timestamp` | |
| `updated_at` | `timestamp` | |

**Indexes:**
- `UNIQUE(agent_id, service_id)` — one policy per agent per service
- `index(superpos_id)` — for apiary-scoped queries
- `index(hive_id)` — for hive-scoped queries
- `index(agent_id)` — for agent lookups
- `index(service_id)` — for service lookups

### Model

- Uses traits: `HasUlid`, `HasFactory`, `BelongsToHive`
- `rules` cast as `array`
- `is_active` cast as `boolean`
- Constants for rule actions: `ACTIONS = ['allow', 'deny', 'require_approval']`
- Relationships: `agent()`, `service()`, `hive()` (via trait), `apiary()` (via trait)
- Query scopes: `active()`, `forAgent()`, `forService()`
- Helper methods: `isActive()`

### Rules Format

```json
{
  "allow": [
    { "method": "GET", "path": "/repos/*/pulls/*" }
  ],
  "deny": [
    { "method": "DELETE", "path": "*" }
  ],
  "require_approval": [
    { "method": "PUT", "path": "*/merge" }
  ]
}
```

Evaluation order (handled by TASK-044 PolicyEngine): deny → require_approval → allow → default deny.

### Factory

- `ActionPolicyFactory` with hive/apiary resolution (matching existing patterns)
- States: `active()`, `inactive()`, `forHive()`, `forAgent()`, `forService()`, `withRules()`

### Relationships on Existing Models

- Add `actionPolicies(): HasMany` to `Agent` model
- Add `actionPolicies(): HasMany` to `Hive` model

## Test Plan

1. ULID auto-generation
2. Non-auto-incrementing key
3. Fillable fields round-trip
4. `rules` array cast
5. `is_active` boolean cast and default
6. BelongsToHive trait integration (CE mode auto-scoping)
7. Cloud mode creation fails without context
8. Cascade delete when agent is deleted
9. Cascade delete when hive is deleted
10. Unique constraint on `(agent_id, service_id)`
11. Same agent+service allowed in different policies if different agents
12. Relationship: `agent()` returns parent
13. Relationship: `service()` returns parent
14. Relationship: `hive()` returns parent (via trait)
15. Agent model: `actionPolicies()` returns children
16. Hive model: `actionPolicies()` returns children
17. Query scope: `active()`
18. Query scope: `forAgent()`
19. Query scope: `forService()`
20. Helper: `isActive()`
21. Constants: `ACTIONS`

## Design Decisions

- Hive-scoped (uses `BelongsToHive` trait which includes `BelongsToApiary`)
- Service connections are apiary-level but policies are hive-level, allowing different hives to have different access rules to the same service
- `rules` stored as JSONB with three top-level keys: `allow`, `deny`, `require_approval`
- Each rule entry has `method` (HTTP method) and `path` (glob pattern)
- Policy evaluation logic lives in TASK-044 (PolicyEngine service) — this task only creates the data model
- `UNIQUE(agent_id, service_id)` enforces one policy per agent per service connection
- Foreign keys cascade on delete for all references

## Related

- **Upstream:** TASK-006 (Superpos & Hive models), TASK-007 (Agent model + permissions)
- **Downstream:** TASK-044 (Policy engine evaluates rules), TASK-045 (Approval requests reference policies), TASK-050 (Dashboard policy editor)
- **Spec reference:** PRODUCT.md §6.8 (Action Policy), §9.2 (action_policies schema)
