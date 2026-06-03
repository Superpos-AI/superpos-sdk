# Task Timeout & Retry Scheduler

TASK-019 adds automatic timeout detection and retry scheduling for
in-progress tasks. A periodic scheduler scans for tasks that have exceeded
their `timeout_seconds` deadline and either retries them (with exponential
backoff) or permanently fails them when retries are exhausted.

## How It Works

```text
in_progress ──timeout──> pending   (retry_count < max_retries)
in_progress ──timeout──> failed    (retry_count >= max_retries)
```

The `apiary:check-task-timeouts` command runs every minute via Laravel's
scheduler. It finds all `in_progress` tasks where:

```
claimed_at + timeout_seconds < NOW()
```

For each timed-out task it checks whether retries remain.

### Retry Path

When `retry_count < max_retries`:

1. Increment `retry_count`
2. Reset `status` to `pending`
3. Clear `claimed_by`, `claimed_at`, `progress`, `status_message`, `result`
4. Compute `retry_after` using exponential backoff
5. Log `task.timed_out` and `task.retried` activity entries

The task re-enters the queue but is hidden from poll results until
`retry_after` has passed.

### Terminal Failure Path

When `retry_count >= max_retries`:

1. Set `status` to `failed`
2. Set `completed_at`
3. Store timeout metadata in `result`
4. Log `task.timed_out` and `task.max_retries_exceeded` activity entries

## Exponential Backoff

The delay before a retried task becomes available again follows:

```
delay = base * 2^(retry_count - 1)
```

Where `base` is `config('apiary.task.retry_backoff')` (default 30 seconds).

| Retry | Delay |
|-------|-------|
| 1st   | 30s   |
| 2nd   | 60s   |
| 3rd   | 120s  |
| 4th   | 240s  |

## Configuration

| Key | Env Variable | Default | Description |
|-----|-------------|---------|-------------|
| `apiary.task.default_timeout` | `SUPERPOS_TASK_TIMEOUT` | `1800` | Default timeout in seconds (30 min) |
| `apiary.task.max_retries` | `SUPERPOS_TASK_MAX_RETRIES` | `3` | Default max retry attempts |
| `apiary.task.retry_backoff` | `SUPERPOS_TASK_RETRY_BACKOFF` | `30` | Base backoff in seconds |

Tasks can override `timeout_seconds` and `max_retries` at creation time.
Setting `timeout_seconds` to `0` disables timeout detection for that task.

## Poll Behaviour

The task poll endpoint (`GET /api/v1/hives/{hive}/tasks/poll`) automatically
excludes tasks whose `retry_after` timestamp is in the future. No agent-side
changes are required.

## API Response Fields

Two fields were added to the task representation:

| Field | Type | Description |
|-------|------|-------------|
| `retry_count` | integer | Current retry attempt (starts at 0) |
| `retry_after` | ISO 8601 / null | Earliest time this task can be polled again |

## Activity Log Events

| Action | When |
|--------|------|
| `task.timed_out` | Task exceeded its timeout deadline |
| `task.retried` | Task reset to pending for retry |
| `task.max_retries_exceeded` | Task permanently failed after all retries |

All entries include the task's `superpos_id`, `hive_id`, and `task_id` for
filtering and auditing.

## Running Manually

```bash
php artisan apiary:check-task-timeouts
```

Output reports the number of retried and failed tasks.

## Scheduler Setup

The command is wired in `bootstrap/app.php` and runs every minute with
overlap protection:

```php
$schedule->command('apiary:check-task-timeouts')
    ->everyMinute()
    ->withoutOverlapping()
    ->runInBackground();
```

Ensure the Laravel scheduler is running:

```bash
php artisan schedule:work   # development
# or
* * * * * cd /path-to-project && php artisan schedule:run >> /dev/null 2>&1
```
