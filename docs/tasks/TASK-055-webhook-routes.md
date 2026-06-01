# TASK-055: Webhook Routes Migration + Model

## Status
In Progress

## Depends On
- TASK-006 (Superpos & Hive models) — done

## Downstream
- TASK-056 (Webhook field filters) — depends on 055
- TASK-057 (Webhook receiver controller) — depends on 055, 056
- TASK-058 (Webhook route evaluator + async processing) — depends on 057
- TASK-059 (Dashboard: webhook monitor) — depends on 057
- TASK-060 (Dashboard: route builder) — depends on 055, 056

## Requirements

1. **Migration** — Create `webhook_routes` table per PRODUCT.md schema (section 9.2)
2. **Model** — `WebhookRoute` Eloquent model with `BelongsToHive` trait, relationships, scopes, constants
3. **Factory** — `WebhookRouteFactory` with cloud/CE context resolution
4. **Reverse relationships** — Add `webhookRoutes()` HasMany on Hive and Agent models
5. **Tests** — Full model test suite covering ULID, fillables, casts, scopes, relationships, tenant safety, cascade deletes, FK integrity

## Schema

```sql
CREATE TABLE webhook_routes (
    id              VARCHAR(26) PRIMARY KEY,
    superpos_id       VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id),
    name            VARCHAR(255) NOT NULL,
    service_id      VARCHAR(26) NOT NULL REFERENCES service_connections(id),
    event_type      VARCHAR(100) NOT NULL,
    field_filters   JSONB NOT NULL DEFAULT '[]',
    action_type     VARCHAR(20) NOT NULL,
    action_config   JSONB NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    priority        SMALLINT DEFAULT 0,
    created_by      VARCHAR(26) REFERENCES agents(id),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
```

## Test Plan

- ULID auto-generation and non-incrementing key
- Fillable fields round-trip
- JSONB casts (field_filters, action_config)
- Boolean cast (is_active) and default value
- Integer cast (priority) and default value
- `isActive()` helper method
- BelongsToHive trait: CE auto-set, cloud fail-without-context
- Cascade deletes: hive deletion, apiary deletion
- Relationships: service(), creator(), hive()
- Reverse relationships: Hive->webhookRoutes(), Agent->webhookRoutes()
- Query scopes: active(), forService(), forEventType(), byPriority()
- Cross-apiary FK integrity enforcement
- Constants (ACTION_TYPES)
- Factory fluent methods
