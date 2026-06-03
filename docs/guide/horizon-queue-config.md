# Horizon & Queue Configuration

This guide covers Laravel Horizon setup, queue configuration, and Redis
database isolation in Superpos.

---

## Overview

Superpos uses [Laravel Horizon](https://laravel.com/docs/horizon) to supervise
Redis-backed queue workers. Horizon provides a dashboard for monitoring queues,
failed jobs, and throughput metrics.

The queue infrastructure is designed around four named queues:

| Queue | Purpose |
|-------|---------|
| `default` | General-purpose jobs |
| `superpos-tasks` | Agent task orchestration |
| `apiary-webhooks` | Inbound webhook processing |
| `apiary-notifications` | Notification delivery |

Queue names are configured in `config/apiary.php` under `queue.queues` and
referenced by the Horizon supervisor in `config/horizon.php`.

---

## Horizon Configuration

The Horizon config lives at `config/horizon.php`. Key settings:

### Supervisors

A single `supervisor-default` processes all four queues with auto-balancing:

```php
'defaults' => [
    'supervisor-default' => [
        'connection' => 'redis',
        'queue' => ['default', 'superpos-tasks', 'apiary-webhooks', 'apiary-notifications'],
        'balance' => 'auto',
        'autoScalingStrategy' => 'time',
        'tries' => 3,
        'timeout' => 60,
    ],
],
```

### Environments

| Environment | Max Workers |
|------------|-------------|
| `local` | 3 |
| `production` | 10 (with balance cooldown) |

### Wait-Time Thresholds

The `waits` config fires a `LongWaitDetected` event when any queue exceeds its
threshold:

```php
'waits' => [
    'redis:default' => 60,
    'redis:superpos-tasks' => 30,
    'redis:apiary-webhooks' => 30,
    'redis:apiary-notifications' => 60,
],
```

---

## Queue Connection

The Redis queue connection (`config/queue.php`) uses these important settings:

| Setting | Value | Why |
|---------|-------|-----|
| `connection` | `queue` | Dedicated Redis DB (see below) |
| `after_commit` | `true` | Jobs only dispatch after the DB transaction commits |
| `retry_after` | `90` | Seconds before a job is retried if the worker dies |

### Batching & Failed Jobs

Both `queue.batching.database` and `queue.failed.database` default to `pgsql`
to match the application's primary database.

---

## Redis Database Isolation

Each Redis concern uses a separate database number to prevent key collisions:

| Redis Connection | DB | Purpose |
|-----------------|-----|---------|
| `default` | 0 | General (sessions, misc) |
| `cache` | 1 | Application cache |
| `queue` | 2 | Queue jobs (Horizon) |

These are configured in `config/database.php` under `redis`. The env vars
`REDIS_DB`, `REDIS_CACHE_DB`, and `REDIS_QUEUE_DB` can override the defaults.

---

## Horizon Dashboard

The Horizon web dashboard is available at `/horizon`. Access is controlled by
the `viewHorizon` gate:

- **Local environment**: open to all visitors (no auth required).
- **Production**: denied by default. A future admin authentication system will
  extend the gate to allow authorized users.

The gate is defined in `AppServiceProvider::configureHorizonGate()`.

---

## Docker Setup

The `docker-compose.yml` includes a dedicated `horizon` service:

```yaml
horizon:
  environment:
    CONTAINER_MODE: horizon
    QUEUE_CONNECTION: redis
```

The `frankenphp/entrypoint.sh` runs `php artisan horizon` when
`CONTAINER_MODE=horizon`.

### Common Commands

```bash
# View Horizon status
docker compose exec app php artisan horizon:status

# Pause all workers
docker compose exec app php artisan horizon:pause

# Resume workers
docker compose exec app php artisan horizon:continue

# Terminate (graceful restart)
docker compose exec app php artisan horizon:terminate

# View Horizon logs
docker compose logs -f horizon
```

---

## Testing

```bash
# Run Horizon + queue config tests
php artisan test --filter="HorizonQueueInfraTest|ConfigQueueTest"
```

Test coverage includes:

- Config wiring (Horizon supervisors, queue connection, Redis DB isolation)
- Artisan command registration (horizon, horizon:list, horizon:status, etc.)
- Gate behavior (local allows, production denies)
- Raw config defaults (unit tests without Laravel bootstrap)
