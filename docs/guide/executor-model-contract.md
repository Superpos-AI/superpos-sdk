# Executor Model Contract — Event Payload

Events published through the Superpos Event Bus can carry **execution-ready** payloads so the daemon can process them without follow-up API fetches.

## Execution-Ready Event Shape

When an event carries `invoke` fields, the poll response promotes them to the top level:

```json
{
  "id": "01J...",
  "type": "task.assigned",
  "payload": {
    "task_id": "T001",
    "invoke": {
      "instructions": "Handle this PR comment",
      "context": { "repo": "my-repo", "pr": 42 }
    }
  },
  "invoke": {
    "instructions": "Handle this PR comment",
    "context": { "repo": "my-repo", "pr": 42 }
  },
  "source_agent_id": "...",
  "hive_id": "...",
  "superpos_id": "...",
  "is_cross_hive": false,
  "seq": 1,
  "created_at": "2026-03-12T00:00:00+00:00"
}
```

## Publishing with Invoke

The publish endpoint accepts `invoke` at the top level (canonical) or nested in `payload.invoke` (legacy). Top-level fields take precedence per key.

```bash
# Canonical (top-level invoke)
curl -X POST /api/v1/hives/{hive}/events \
  -d '{"type":"task.assigned","payload":{"task_id":"T1"},"invoke":{"instructions":"Review code"}}'

# Legacy (payload.invoke)
curl -X POST /api/v1/hives/{hive}/events \
  -d '{"type":"task.assigned","payload":{"task_id":"T1","invoke":{"instructions":"Review code"}}}'
```

## Daemon Behavior

The daemon classifies each polled event:

| Event has `invoke.instructions`? | Daemon action |
|---|---|
| Yes (non-empty string) | **Exec-ready**: dispatches inline with invoke data, skips pending file save |
| No / null / empty | **Fallback**: saves to `pending/events/`, dispatches reference only |

On dispatch failure, exec-ready events are saved to pending for retry (no data loss).

## Backward Compatibility

Older events without `invoke` in the payload work unchanged. The poll response simply omits the top-level `invoke` key, and the daemon falls back to the reference-only dispatch path with pending file persistence.

## Invoke Field Contract

| Field | Type | Description |
|---|---|---|
| `invoke.instructions` | `string \| null` | Control-plane instructions for the executor |
| `invoke.context` | `object \| null` | Structured context (repo, PR, priority, etc.) |

Both fields mirror the task invoke contract defined in `CreateTaskRequest`. The normalization rules (top-level overrides payload-level per key) are identical.
