# Agent SDK Use Cases (Default Scenarios)

This guide standardizes common agent intents into correct Superpos SDK/API calls.

Goal: reduce ambiguity, prevent routing mistakes, and keep routing metadata canonical (`target_agent_id`, `task_target_agent_id`, `run_at`) instead of hiding control fields in payload.

## Core Rules

1. **Use canonical top-level routing fields**
   - Task API: `target_agent_id`
   - Schedule API: `task_target_agent_id`
   - Scheduled execution time: `run_at` on **schedule resources**

2. **Use the correct API surface**
   - Delayed/recurring execution → **Schedules API** (`/api/v1/schedules`)
   - Immediate work unit execution → **Tasks API** (`/api/v1/tasks`)

3. **Treat payload as business data**, not control-plane metadata.

4. **Invoke control-plane contract for task creation**
   - Canonical: top-level `invoke.instructions` / `invoke.context`
   - Legacy compatibility: `payload.invoke.instructions` / `payload.invoke.context`
   - Mixed mode precedence: top-level `invoke.*` wins per field when both are present

5. **Use idempotency keys** for retryable create writes.

6. **Store time in UTC** and include source timezone only for presentation/context.

---

## Scenario 1 — “Remind me in 2 hours”

### Intent
Create a scheduled reminder executed by a specific agent at a future time.

### Mapping (current contract)
- API: `POST /api/v1/schedules`
- `trigger_type`: `once`
- `run_at`: now + 2h (UTC)
- `task_target_agent_id`: current/selected agent
- `task_payload`: reminder content only
- Idempotency: send `Idempotency-Key` header (for safe retries)

### Example payload (schedule create)

```json
{
  "name": "Reminder: Prepare bio for Kirill",
  "trigger_type": "once",
  "run_at": "2026-03-10T20:58:12Z",
  "task_type": "reminder",
  "task_payload": {
    "message": "Prepare bio for Kirill",
    "channel": "telegram",
    "target": "94650650",
    "timezone": "UTC"
  },
  "task_target_agent_id": "01kka18n2gyrj3asy5tmp8yws5"
}
```

### Expected outcome
- Schedule is persisted and visible in schedules UI/API.
- At due time, dispatcher creates runtime task from schedule.
- Dispatched task has canonical target metadata set.
- Dashboard reflects planned execution time clearly.

---

## Scenario 2 — Recurring reminder

### Intent
Run reminder repeatedly (daily/weekly).

### Mapping
- Create/update **schedule** recurrence config.
- Keep next execution timestamp explicit (`run_at` / recurrence cursor).
- Preserve canonical `task_target_agent_id`.

### Rule
If update payload carries alias-style targeting fields, normalize to canonical schedule target field before validation.

---

## Scenario 3 — Delayed follow-up check

### Intent
"Check CI in 15 minutes."

### Mapping
- Create one-time schedule (`trigger_type=once`) with `run_at = now+15m`.
- Put check context in `task_payload` (repo/PR/branch).
- Pin responsible executor with `task_target_agent_id`.

---

## Scenario 4 — Immediate work vs delayed work

- **Immediate action needed now** → Tasks API (`pending` task)
- **Time-based execution** → Schedules API (`run_at` + trigger config)

Do not emulate delayed behavior via timeout-only fields.

---

## Scenario 5 — Fan-out with explicit ownership

### Intent
Parent task spawns child tasks to multiple agents.

### Mapping
- Parent uses completion policy (`all`/`any`/`count`/`ratio`/`custom`).
- Each child has explicit target metadata and sanitized failure policy.
- Parent completion evaluation should run post-commit to avoid lock inversions/deadlocks.

---

## Validation Checklist (before create)

- [ ] Correct API selected (Tasks vs Schedules).
- [ ] Target field is canonical (`target_agent_id` or `task_target_agent_id`).
- [ ] `run_at` is valid ISO-8601 UTC for schedule resources.
- [ ] Idempotency key/header is present for retryable writes.
- [ ] Policy/failure-policy fields are sanitized (no internal flags injection).
- [ ] Payload carries business data; routing data stays canonical.

---

## Anti-Patterns

1. Putting routing fields only in payload (`payload.target_agent_id`) and expecting scheduler/claiming to honor them.
2. Creating delayed reminders through Tasks API when schedule semantics are required.
3. Emitting realtime side effects before DB commit.
4. Allowing cross-hive references (task/agent IDs) without scoped validation.

---

## Error Code Conventions (current API)

Prefer existing envelope/code conventions:
- `validation_error` (field-level 422)
- `forbidden` (403)
- `not_found` (404)
- `conflict` (409)

Domain-specific retryable contention codes (when implemented by endpoint) may include:
- `quota_lock_contention`
- `dedup_lock_contention`

Keep client branching anchored to documented, actually-emitted codes.
