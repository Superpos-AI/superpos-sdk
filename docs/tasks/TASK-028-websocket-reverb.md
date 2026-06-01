# TASK-028: WebSocket Real-Time Updates (Reverb)

**Status:** Review
**Branch:** `task/028-websocket-reverb`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/33
**Depends On:** TASK-022 (Inertia + React), TASK-023 (Dashboard home)

## Summary

Add real-time dashboard updates via Laravel Reverb WebSockets. When agents
create tasks, change status, or generate activity, the dashboard reflects
those changes immediately without manual page refresh.

## Requirements

1. **Server-side broadcasting** — Install Laravel Reverb, configure
   `config/broadcasting.php` and `config/reverb.php`, register broadcast
   auth routes.
2. **Broadcast events** — Create four events scoped to private hive
   channels: `HiveActivityCreated`, `AgentStatusChanged`,
   `TaskStatusChanged`, `KnowledgeEntryChanged`.
3. **ActivityLogger integration** — Dispatch `HiveActivityCreated` from
   `ActivityLogger::log()` for every hive-scoped activity entry.
4. **API controller integration** — Dispatch specific model events from
   API controllers after state changes (agent status, task lifecycle,
   knowledge CRUD).
5. **Channel authorization** — Private `hive.{hiveId}` channel; CE mode
   authorizes the default hive, Cloud mode denies (placeholder for Phase 5).
6. **Client-side Echo** — Initialize Laravel Echo with Reverb in
   `bootstrap.js`, create `useHiveChannel` React hook.
7. **Dashboard page updates** — Dashboard home (live activity + tasks),
   Activity feed (live entry banner), Agents page (live status), Tasks
   Kanban (live update banner).
8. **Graceful degradation** — Broadcasting skipped when driver is
   null/log (testing, CLI). Pages work normally without WebSocket.

## Files Changed

### New Files
- `config/broadcasting.php` — Laravel broadcasting config
- `config/reverb.php` — Reverb server config (vendor-published)
- `routes/channels.php` — Hive channel authorization
- `app/Events/HiveActivityCreated.php`
- `app/Events/AgentStatusChanged.php`
- `app/Events/TaskStatusChanged.php`
- `app/Events/KnowledgeEntryChanged.php`
- `resources/js/Hooks/useHiveChannel.js`
- `tests/Feature/Broadcasting/BroadcastEventTest.php`
- `tests/Feature/Broadcasting/ChannelAuthTest.php`
- `tests/Feature/Broadcasting/ActivityLoggerBroadcastTest.php`
- `docs/guide/realtime-updates.md`

### Modified Files
- `composer.json` / `composer.lock` — Added `laravel/reverb`
- `package.json` / `package-lock.json` — Added `laravel-echo`, `pusher-js`
- `bootstrap/app.php` — Removed duplicate broadcasting setup
- `app/Providers/AppServiceProvider.php` — Conditional broadcast routes
- `app/Services/ActivityLogger.php` — Dispatch HiveActivityCreated
- `app/Http/Controllers/Api/AgentLifecycleController.php` — Dispatch AgentStatusChanged
- `app/Http/Controllers/Api/TaskController.php` — Dispatch TaskStatusChanged
- `app/Http/Controllers/Api/KnowledgeController.php` — Dispatch KnowledgeEntryChanged
- `docker-compose.yml` — Added VITE_REVERB_* and REVERB_APP_* env vars
- `resources/js/bootstrap.js` — Echo/Reverb client initialization
- `resources/js/Pages/Dashboard.jsx` — Live activity and task updates
- `resources/js/Pages/Activity.jsx` — Live entry banner
- `resources/js/Pages/Agents.jsx` — Live agent status
- `resources/js/Pages/Tasks.jsx` — Live task update banner

## Test Plan

- [x] Broadcast events use private hive channels
- [x] Event payloads contain expected data
- [x] All events implement ShouldBroadcastNow
- [x] Channel auth allows CE default hive
- [x] Channel auth denies wrong hive IDs
- [x] Channel auth denies in Cloud mode
- [x] ActivityLogger dispatches broadcast for hive-scoped entries
- [x] ActivityLogger skips broadcast without hive context
- [x] Full test suite passes (no regressions)

## Validation Checklist

- [x] PSR-12 compliant
- [x] Activity logging on state changes (unchanged from existing)
- [x] Hive-scoped channel isolation
- [x] Graceful degradation when broadcasting disabled
- [x] No breaking changes to existing API or dashboard
