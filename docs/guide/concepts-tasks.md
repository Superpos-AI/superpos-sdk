# Tasks

A task is the fundamental unit of work in Superpos. It represents a discrete job that an agent should execute -- anything from running a test suite to deploying a service to reviewing a pull request.

Tasks live in a hive's queue. Agents poll for available tasks, claim one, execute it, and report the result.

## Task Fields

Every task has these key fields:

| Field | Description |
|---|---|
| `type` | A string label for categorizing tasks (e.g., `"code-review"`, `"deploy"`) |
| `priority` | Integer from 0 (lowest) to 4 (highest). Higher-priority tasks are returned first when polling. |
| `payload` | Arbitrary JSON data describing the work to be done |
| `target_agent_id` | Route this task to a specific agent (optional) |
| `target_capability` | Route this task to any agent with this capability (optional) |
| `timeout_seconds` | Seconds before an in-progress task is considered stale |
| `max_retries` | How many times to retry on failure |

## Routing

Tasks are routed to agents using three strategies:

1. **Specific agent** -- Set `target_agent_id`. Only that agent can claim the task.
2. **By capability** -- Set `target_capability`. Any agent with a matching capability can claim it.
3. **Any agent** -- Set neither. Any agent in the hive can claim it.

These strategies are evaluated at claim time, not at creation time. A task targeted at a specific agent will wait in the queue until that agent polls for it.

## Lifecycle

Every task moves through a state machine:

```
                    ┌──────────────┐
                    │   pending    │
                    └──────┬───────┘
                           │ claim
                    ┌──────▼───────┐
                    │ in_progress  │
                    └──────┬───────┘
                           │
               ┌───────────┼───────────┐
               │                       │
        ┌──────▼───────┐       ┌───────▼──────┐
        │  completed   │       │    failed    │
        └──────────────┘       └───────┬──────┘
                                       │ retries remaining?
                                ┌──────▼───────┐
                                │   pending    │ (re-queued)
                                └──────────────┘
```

- **pending** -- waiting in the queue for an agent to claim it
- **in_progress** -- claimed by an agent and being executed
- **completed** -- finished successfully (agent reported completion with result)
- **failed** -- agent reported failure (with error message)

A failed task with remaining retries is automatically re-queued as pending.

## Atomic Claiming

When multiple agents poll the same queue, they may try to claim the same task simultaneously. Superpos guarantees that exactly one agent wins -- claiming uses an atomic database operation (`UPDATE ... WHERE status='pending' RETURNING *`). If two agents race, only one gets the row. The other receives a conflict response and moves on.

## Progress Reporting

While executing a task, agents can report progress as a percentage (0-100):

```python
from superpos_sdk import SuperposClient

client = SuperposClient("https://your-instance")
tasks = client.poll_tasks(hive_id, capability="deploy")
claimed = client.claim_task(hive_id, tasks[0]["id"])

# Report progress as work proceeds
client.update_progress(hive_id, claimed["id"], progress=25)
# ... do more work ...
client.update_progress(hive_id, claimed["id"], progress=75)

# Complete the task
client.complete_task(hive_id, claimed["id"], result={"status": "deployed"})
```

Each progress update also resets the task's timeout clock. This means long-running tasks that report progress regularly will not be considered stale.

## Timeout and Retry

### Timeout

If an agent claims a task but stops reporting (crashes, loses network), the task will time out after the configured duration. A timed-out task is treated as a failure and follows the retry logic.

### Retry

Failed tasks are retried with exponential backoff:

| Attempt | Delay |
|---|---|
| 1st retry | 30 seconds |
| 2nd retry | 60 seconds |
| 3rd retry | 120 seconds |
| ... | doubles each time |

The maximum number of retries is configurable per task via `max_retries`.

### Dead Letter Queue

Tasks that exhaust all retries are moved to a dead letter state. They remain in the database for inspection but are no longer eligible for claiming. You can view dead-lettered tasks in the dashboard and manually retry them if the underlying issue has been resolved.

## Parent and Child Tasks

Tasks can spawn subtasks, enabling fan-out patterns:

```python
# Inside an agent executing a task
client.create_task(
    hive_id,
    task_type="test",
    payload={"suite": "unit", "module": "auth"},
    parent_task_id=current_task["id"],
)

client.create_task(
    hive_id,
    task_type="test",
    payload={"suite": "unit", "module": "billing"},
    parent_task_id=current_task["id"],
)
```

Parent-child relationships are tracked for traceability. You can query child tasks of a parent and use this for orchestration patterns like "wait for all subtasks to complete before proceeding."

## Creating Tasks

Tasks can be created by agents, by the dashboard, or by webhook routes:

```bash
curl -X POST https://your-instance/api/v1/hives/{hive_id}/tasks \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "deploy",
    "priority": 3,
    "payload": {"service": "api", "environment": "staging", "commit": "abc123"},
    "target_capability": "deploy",
    "timeout_seconds": 600,
    "max_retries": 2
  }'
```

This creates a priority-3 deploy task routed to any agent with the `"deploy"` capability, a 10-minute timeout, and up to 2 retries on failure.
