# TASK-029 — Horizon Integration & Queue Config

| Field        | Value                                         |
|-------------|-----------------------------------------------|
| **Status**  | Review                                        |
| **Priority**| High                                          |
| **Depends** | —                                             |
| **Branch**  | `task/029-horizon-queue-infra`                |
| **PR**      | https://github.com/Superpos-AI/superpos-app/pull/35 |

## Objective

Install Laravel Horizon, configure supervisors to process all Superpos queue
names, harden queue config defaults (after_commit, batching DB), and isolate
Redis databases so queues, cache, and default do not share a DB.

## Scope

1. **Install `laravel/horizon`** — add to `composer.json` `require`.
2. **`config/horizon.php`** — custom config with:
   - Supervisors covering `default`, `superpos-tasks`, `apiary-webhooks`,
     `apiary-notifications`.
   - `local` environment (3 workers) and `production` environment (10 workers,
     auto-balance).
   - Wait-time thresholds per queue.
3. **Horizon auth gate** — `viewHorizon` gate in `AppServiceProvider`:
   - Open in `local` environment.
   - Denied by default in production (future admin auth will extend).
4. **Queue config updates** (`config/queue.php`):
   - Redis connection: `after_commit: true` for transactional safety.
   - Redis connection: use `queue` Redis DB (not `default`).
   - Batching + failed-jobs database: default to `pgsql` instead of `sqlite`.
5. **Redis DB isolation** (`config/database.php`):
   - `default` → DB 0, `cache` → DB 1, `queue` → DB 2 (new).
6. **Tests** — unit + feature tests covering config wiring, artisan command
   availability, and gate behavior.
7. **Docs** — task doc, VitePress guide, docs/index link.

## Files Changed

| File | Change |
|------|--------|
| `composer.json` / `composer.lock` | Add `laravel/horizon` |
| `config/horizon.php` | New — Horizon supervisor & environment config |
| `config/queue.php` | `after_commit: true`, `connection: queue`, batching/failed → `pgsql` |
| `config/database.php` | Add `queue` Redis connection (DB 2) |
| `app/Providers/AppServiceProvider.php` | `viewHorizon` gate + `Horizon::auth()` |
| `tests/Feature/HorizonQueueInfraTest.php` | Feature tests |
| `tests/Unit/ConfigQueueTest.php` | Unit tests for raw config defaults |
| `docs/tasks/TASK-029-horizon-queues.md` | This task doc |
| `docs/guide/horizon-queue-config.md` | VitePress guide |
| `docs/index.md` | Link to new guide |

## Acceptance Criteria

- [x] `laravel/horizon` is in `composer.json` require
- [x] `config/horizon.php` exists with supervisors covering all Superpos queues
- [x] `viewHorizon` gate allows local, denies production
- [x] Redis queue uses `after_commit: true`
- [x] Redis queue uses dedicated `queue` Redis connection (DB 2)
- [x] Batching and failed-jobs DB defaults to `pgsql`
- [x] All new tests pass; no regressions in full suite
- [x] Docs: task file, VitePress guide, index link

## Testing

```bash
php artisan test --filter="HorizonQueueInfraTest|ConfigQueueTest"
```
