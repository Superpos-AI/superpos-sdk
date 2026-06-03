---
name: TASK-281 platform admin dashboard
description: Cloud-only platform-operator admin surface at /admin for managing users, organizations, hives, activity, and the DLQ. Includes suspend/impersonate/force-verify, a system health widget, and audited admin actions.
type: project
---

# TASK-281: Platform admin dashboard

**Status:** pending
**Branch:** `task/281-platform-admin-dashboard`
**PR:** —
**Depends on:** — (uses existing User/Organization/Hive/ActivityLog/CloudTenant/DLQ infra)
**Blocks:** Cloud production launch readiness
**Edition:** **cloud-only** (routes + pages gated behind `config('platform.is_cloud')`)
**Feature doc:** this task.

## Objective

Cloud is going to production. There is no platform-operator admin surface today — no way to suspend a user, toggle a hive, inspect the DLQ across hives, or see "is Cloud healthy right now?" at a glance. Ship a Cloud-only `/admin` dashboard with the six pages listed below, gated behind a new `is_platform_admin` flag on the User model. Every admin write-action is audited to `activity_log` with `actor_user_id = the admin`.

## Background

- No platform-admin role exists today. `User` has no `is_admin` / `suspended_at` columns. `Organization` and `CloudTenant` have no suspension fields. Hives have `is_active` (already there — reuse it).
- Cloud already has `CloudTenant` (Stripe-linked) + `cloud_tenant_users` pivot (roles `owner|admin|member|viewer`). Those are **per-org** roles. Platform admin is **above** all orgs.
- `ActivityLog` is the standard audit record. Reuse it; do not invent a new admin-audit table.
- DLQ dashboard already shipped (GAP-003). This task adds a cross-hive view at `/admin/dlq`, reusing the same service / query layer. Do not reimplement DLQ logic.
- Horizon is at `/horizon`. The admin system-health widget surfaces a subset of Horizon's data inline; it does not replace Horizon.

## Access Model

- **New column:** `users.is_platform_admin boolean default false, not null`.
- **Bootstrapping:** env var `PLATFORM_ADMIN_EMAILS` (comma-separated). On every login + on Cloud tenant provisioning, any user whose email is in that list gets promoted (`is_platform_admin = true`) idempotently. This lets the operator seed themselves as admin without DB access.
- **Middleware:** `app/Cloud/Http/Middleware/EnsurePlatformAdmin.php`. 404s (not 403 — don't advertise admin exists) for anyone without `is_platform_admin=true`. Also 404s in CE builds regardless of flag.
- **Gate alias:** `Gate::define('platform-admin', fn(User $u) => $u->is_platform_admin)` so Inertia props / Blade can cheaply check.
- All `/admin/*` routes live behind the middleware + `auth` + `verified`.

## Suspension Semantics

- **User suspended** (`users.suspended_at` nullable timestamp):
  - Cannot log in (login fails with "Your account has been suspended. Contact support.").
  - Existing sessions are revoked on suspend (`DB::table('sessions')->where('user_id', …)->delete()` + `Auth::logoutOtherDevices()` equivalent; check the session driver in use and pick the correct purge).
  - API tokens / OAuth-issued tokens are revoked.
- **Organization (CloudTenant) suspended** (`cloud_tenants.suspended_at` nullable):
  - All org members blocked from switching into the org (the tenant-switch endpoint 403s).
  - Running tasks are NOT killed (same default as hive toggle).
  - New tasks cannot be created (webhook routes + dashboard task-create endpoints check the flag and refuse with a clear error).
- **Hive `is_active=false`** (existing field — default behavior unchanged):
  - Blocks new task creation and claim polls to that hive.
  - Does not stop running tasks.

## Pages

All under `/admin`. Routes registered in `routes/cloud.php` (or equivalent Cloud-only route file — find the one webhook/billing routes use).

### 1. `/admin` — Landing / System Health

- **System health widget** (top of page):
  - Total queue depth across all hives (one query on `tasks.status='pending'`).
  - Horizon workers online (reach into Horizon's `MasterSupervisorRepository` or call its API internally — if expensive, cache for 30s).
  - Redis reachable (`Redis::ping()`).
  - DB reachable (always true if the request got here, but include for symmetry).
  - Error count in the last 15 minutes (activity_log entries where `action` ends in `.failed` or `.error`).
  - Each tile is a colored dot (green / amber / red) + a number.
- **Recent admin actions** (strip): last 20 `activity_log` entries where `actor_user_id` is a platform admin, across any org/hive. Who did what, when.

### 2. `/admin/users` — Users

- **List** — paginated (25/page). Columns: name, email (+ verified badge), primary org, created, last_login_at, status (active/suspended). Search by email/name. Filter: all / verified / suspended.
- **Detail** — `/admin/users/{user}`:
  - Profile: name, email, email_verified_at, created_at, provider (Google/GitHub/local).
  - Orgs table: every `CloudTenant` they belong to with role and join date.
  - Recent activity (last 50 from activity_log where `actor_user_id = this user`).
  - Actions (buttons, each confirms before POSTing):
    - **Suspend** / **Reactivate** (toggles `users.suspended_at`, revokes sessions on suspend).
    - **Force-verify email** (sets `email_verified_at = now()` if null).
    - **Send password reset** (fires Laravel's password-reset mail).
    - **Impersonate** (see §Impersonation below).
  - Every action writes an activity_log entry: action name `admin.user.{suspended,reactivated,verified,password_reset_sent,impersonated}`, `actor_user_id = admin`, `entity_type = User`, `entity_id = target`.

### 3. `/admin/organizations` — Organizations (CloudTenants)

- **List** — paginated. Columns: name, slug, plan, owner email, member count, trial_ends_at, stripe_subscription_status, created_at, status. Search by name/slug/owner-email. Filter: by plan, by status.
- **Detail** — `/admin/organizations/{tenant}`:
  - Tenant data (name, slug, plan, Stripe customer/subscription ids as links to Stripe dashboard, trial dates).
  - Usage this period (reuse `UsageMeteringService` — do NOT re-implement).
  - Members list (from `cloud_tenant_users`).
  - Hives list (all hives owned by this tenant's organization).
  - Actions:
    - **Suspend** / **Reactivate** (toggles `cloud_tenants.suspended_at`).
    - **Change plan** (dropdown: free / pro / team / enterprise — writes `plan` column only; does NOT talk to Stripe. Note in UI: "Stripe subscription must be adjusted separately — this only updates internal plan limits.").
  - Activity log filtered to this tenant.
  - Audit: `admin.organization.{suspended,reactivated,plan_changed}`.

### 4. `/admin/hives` — Hives

- **List** — cross-tenant. Columns: name, slug, tenant, agents count, pending tasks, queue depth, `is_active`, created_at. Search by name/slug/tenant.
- **Detail** — `/admin/hives/{hive}`:
  - Name, slug, description, tenant, counts (agents, tasks by status), recent activity.
  - Actions:
    - **Toggle active** (existing `is_active` field — default semantics: blocks new task creation + polls, leaves running tasks alone).
  - Audit: `admin.hive.{activated,deactivated}`.

### 5. `/admin/activity` — Activity Log Viewer

- Cross-org, cross-hive activity log browser.
- Filters: user (actor_user_id), org (tenant), hive, action (substring match), date range.
- Columns: timestamp, actor, action, entity_type + entity_id, hive/org.
- Click a row to see the raw JSON payload.
- Paginated; no export in v1 (defer).

### 6. `/admin/dlq` — DLQ Browser (cross-hive)

- List of dead-lettered tasks from all hives.
- Columns: task id, hive, queue, failed_at, last exception (truncated), retry count.
- Row actions (per task): Retry, Replay, Delete. Each action reuses the existing DLQ service (GAP-003) — do NOT re-implement.
- Bulk-select + bulk-retry is a nice-to-have; include it only if trivially cheap to add on top of the existing DLQ service. Otherwise defer.
- Audit: `admin.dlq.{retried,replayed,deleted}`.

## Impersonation

- **View-only mode** — admin cannot *write* as the impersonated user; they can only see the user's dashboard as the user sees it.
  - Implementation: when admin clicks **Impersonate**, a `laravel_impersonate` session entry (or a simple session key) records `{impersonated_user_id, admin_user_id, read_only: true}`. A middleware on dashboard write endpoints (task create, workflow edit, knowledge edit, etc.) refuses with 403 + "Impersonation is view-only" when impersonation is active.
  - A global red banner renders at the top of every page while impersonating: `You are viewing <Name> as admin <AdminName>. Click to exit.`. Clicking the banner ends impersonation.
  - Attempting to impersonate another admin user is refused (symmetric — admins can't impersonate each other).
  - Every impersonation start/end writes activity_log: `admin.user.impersonated` / `admin.user.impersonation_ended`.
- **Library choice:** prefer the `lab404/laravel-impersonate` package if it composes cleanly with the Inertia stack. If it fights with the stack, write a minimal custom middleware (≤60 lines). Do NOT adopt a package that introduces new auth concepts.

## Requirements

### Functional

- [ ] FR-1: Migration adds `users.is_platform_admin` (boolean, default false, indexed) and `users.suspended_at` (nullable timestamp).
- [ ] FR-2: Migration adds `cloud_tenants.suspended_at` (nullable timestamp).
- [ ] FR-3: `EnsurePlatformAdmin` middleware gates all `/admin/*` routes. 404 for non-admins and for CE builds.
- [ ] FR-4: `PLATFORM_ADMIN_EMAILS` env var — on login (via a listener on the `Login` event or in `AuthenticatedSessionController::store`), any user whose email matches promotes to `is_platform_admin=true` idempotently.
- [ ] FR-5: Login rejects suspended users. Existing sessions revoked on suspend. OAuth / API tokens revoked on suspend.
- [ ] FR-6: Tenant-switch endpoint + task-create endpoints refuse when the target `cloud_tenants.suspended_at` is set.
- [ ] FR-7: The six pages above render with the specified columns, search, filters, and actions. All actions audit to `activity_log` with `actor_user_id = admin`.
- [ ] FR-8: Impersonation works per §Impersonation. Red banner visible on every page during impersonation. Admin-on-admin impersonation refused.
- [ ] FR-9: DLQ page reuses the existing DLQ service (GAP-003 shipped). No duplicate logic.
- [ ] FR-10: `AdminLayout` is visually distinct from `AppLayout` — a red accent stripe or different top-bar color so an admin always knows they're in admin mode.

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean.
- [ ] NFR-2: Migrations reversible.
- [ ] NFR-3: Cloud-only. All new code under `app/Cloud/` namespace (routes, controllers, middleware). JSX under `resources/js/Pages/Cloud/Admin/`. In CE builds, `/admin` 404s and none of the new PHP classes load beyond the route definition.
- [ ] NFR-4: System health widget makes at most 4 queries + 1 Redis ping. Cache the Horizon check for 30s.
- [ ] NFR-5: No bulk destructive actions without a typed-confirmation step (e.g., "type DELETE to confirm"). Not required in v1 because v1 has no bulk destructive action except DLQ delete — which affects one task at a time unless we add the bulk option.
- [ ] NFR-6: Every admin write-endpoint is rate-limited (throttle:60,1 or tighter) to prevent runaway scripts.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/YYYY_MM_DD_HHMMSS_add_platform_admin_and_suspended_at_to_users.php` | Two columns on users |
| Create | `database/migrations/cloud/YYYY_MM_DD_HHMMSS_add_suspended_at_to_cloud_tenants.php` | One column on cloud_tenants |
| Modify | `app/Models/User.php` | Casts + `$fillable` + `isPlatformAdmin()` helper |
| Modify | `app/Cloud/CloudTenant.php` | Casts + `$fillable` + `isSuspended()` helper |
| Create | `app/Cloud/Http/Middleware/EnsurePlatformAdmin.php` | 404-gate for /admin |
| Modify | `app/Providers/AppServiceProvider.php` | Register `platform-admin` gate |
| Modify | `app/Http/Controllers/Auth/AuthenticatedSessionController.php` (or a listener) | Auto-promote PLATFORM_ADMIN_EMAILS on login; reject suspended |
| Create | `app/Cloud/Http/Controllers/Admin/AdminDashboardController.php` | Landing + system health |
| Create | `app/Cloud/Http/Controllers/Admin/AdminUserController.php` | Users list / detail / actions |
| Create | `app/Cloud/Http/Controllers/Admin/AdminOrganizationController.php` | CloudTenants list / detail / actions |
| Create | `app/Cloud/Http/Controllers/Admin/AdminHiveController.php` | Hives list / detail / toggle |
| Create | `app/Cloud/Http/Controllers/Admin/AdminActivityController.php` | Activity log browser |
| Create | `app/Cloud/Http/Controllers/Admin/AdminDlqController.php` | Cross-hive DLQ browser (wraps existing DLQ service) |
| Create | `app/Cloud/Http/Controllers/Admin/AdminImpersonationController.php` | start/stop impersonation |
| Create | `app/Cloud/Http/Middleware/BlockWritesWhileImpersonating.php` | 403 write-endpoints when impersonating |
| Create | `app/Cloud/Services/SystemHealthService.php` | Collects health tiles |
| Create | `app/Cloud/Services/AdminActionAuditor.php` | Thin helper that writes activity_log entries with a consistent shape |
| Modify | `routes/cloud.php` (or whatever the Cloud-only route file is) | `/admin/*` routes |
| Create | `resources/js/Layouts/Cloud/AdminLayout.jsx` | Distinct layout with red accent + impersonation banner slot |
| Create | `resources/js/Pages/Cloud/Admin/Index.jsx` | Landing |
| Create | `resources/js/Pages/Cloud/Admin/Users/Index.jsx` + `Show.jsx` | Users list + detail |
| Create | `resources/js/Pages/Cloud/Admin/Organizations/Index.jsx` + `Show.jsx` | Orgs list + detail |
| Create | `resources/js/Pages/Cloud/Admin/Hives/Index.jsx` + `Show.jsx` | Hives list + detail |
| Create | `resources/js/Pages/Cloud/Admin/Activity/Index.jsx` | Activity log browser |
| Create | `resources/js/Pages/Cloud/Admin/Dlq/Index.jsx` | DLQ browser |
| Create | `resources/js/Components/Cloud/ImpersonationBanner.jsx` | Red top banner, shared |
| Create | `tests/Cloud/Feature/AdminAccessTest.php` | Middleware + gate + CE-404 + env-promotion |
| Create | `tests/Cloud/Feature/AdminUserActionsTest.php` | Suspend / reactivate / verify / reset / impersonate |
| Create | `tests/Cloud/Feature/AdminOrganizationActionsTest.php` | Suspend / reactivate / plan change |
| Create | `tests/Cloud/Feature/AdminHiveActionsTest.php` | Toggle active |
| Create | `tests/Cloud/Feature/AdminDlqTest.php` | Cross-hive browse + retry/replay/delete |
| Create | `tests/Cloud/Feature/AdminImpersonationTest.php` | Read-only enforcement + admin-on-admin blocked |
| Create | `tests/Cloud/Feature/SystemHealthTest.php` | Tile shape + caching |
| Create | `resources/js/Pages/Cloud/Admin/__tests__/Index.test.jsx` | Smoke |
| Create | `resources/js/Pages/Cloud/Admin/Users/__tests__/Show.test.jsx` | Actions render |

### Key Design Decisions

- **Single flag on users, not a `roles` table.** We have one role above tenants — "platform admin". A full RBAC system is premature.
- **Env-seeded admins.** Operator seeds themselves via `PLATFORM_ADMIN_EMAILS` without DB access. Promotion happens on login so it survives fresh deploys.
- **Cloud-only everything.** `/admin` does not exist in CE. CE is single-org / single-hive and doesn't need a platform admin. All code under `app/Cloud/` + `resources/js/Pages/Cloud/Admin/`.
- **Reuse, don't duplicate.** DLQ already shipped; admin wraps the same service. `UsageMeteringService` already exists; admin org page reads from it. `activity_log` is the audit record — no new audit table.
- **Impersonation is view-only.** Write-blocking middleware is simpler than "did the admin really mean to do this." If we ever need write-impersonation for support, it's a clear later delta.
- **Plan change does not touch Stripe.** Operator's responsibility to reconcile; we surface the internal plan flag. The alternative (auto-Stripe-sync) is an entire feature of its own.
- **404, not 403, on non-admin hits to /admin.** Don't advertise admin exists. Same pattern as Horizon's gate.
- **AdminLayout has a red accent.** Visual affordance — you always know you're in admin mode. Prevents "wait, which user is this?" moments.

## Implementation Plan

1. **Migrations + model changes** — `is_platform_admin`, `suspended_at` on users; `suspended_at` on `cloud_tenants`. Update fillables + casts.
2. **Access control** — `EnsurePlatformAdmin` middleware (404 on fail), `platform-admin` gate, auto-promotion listener reading `PLATFORM_ADMIN_EMAILS`, login-refusal for suspended users + session/token revoke.
3. **Tenant / hive enforcement** — wire `cloud_tenants.suspended_at` into the tenant-switch endpoint and the task-create path. Hive `is_active` already enforces.
4. **Impersonation** — pick the library or write the minimal custom middleware. Build start/stop endpoints + banner + write-block middleware + admin-on-admin guard.
5. **Pages** — build in the order: Dashboard → Users → Organizations → Hives → Activity → DLQ. Each page lands behind a feature test before moving on.
6. **Tests** — see table. Aim for "every admin action is covered by one feature test plus one audit-log assertion."

## Test Plan

### Feature Tests (Cloud namespace — tests/Cloud/Feature)

- [ ] Non-admin hitting `/admin` gets 404
- [ ] Admin hitting `/admin` gets 200
- [ ] CE build hitting `/admin` gets 404 regardless of flag
- [ ] `PLATFORM_ADMIN_EMAILS` auto-promotes on login (idempotent across logins)
- [ ] Suspended user login fails with the suspension message
- [ ] Suspended user's existing sessions are revoked
- [ ] Suspended tenant blocks tenant-switch (403)
- [ ] Suspended tenant blocks new-task creation
- [ ] Toggle hive inactive: new task creation refused; already-running task continues
- [ ] User suspend / reactivate / force-verify / password-reset each writes the right activity_log entry with `actor_user_id = admin`
- [ ] Impersonation: admin writes from the impersonated session are blocked (403)
- [ ] Impersonation: admin cannot impersonate another admin
- [ ] Impersonation start + stop each write an audit entry
- [ ] DLQ retry / replay / delete via admin wraps the existing DLQ service (no new SQL)
- [ ] SystemHealthService returns the expected tile shape; Horizon check is cached for 30s

### JSX Tests

- [ ] `AdminLayout` renders the red accent stripe
- [ ] `ImpersonationBanner` renders when impersonation session is active and hides otherwise
- [ ] Users/Show renders all action buttons and gates them correctly (admin-on-admin impersonate button disabled)
- [ ] Activity browser's filters round-trip through the URL (so deep links work)

## Validation Checklist

- [ ] All tests pass
- [ ] Pint clean
- [ ] Migrations reversible (both directions tested)
- [ ] CE build: `/admin/*` all 404
- [ ] Operator can seed themselves via env var without DB access
- [ ] Every admin action in v1 produces an activity_log entry with actor = admin
- [ ] Impersonation write-block verified end-to-end
- [ ] Admin landing system-health widget renders with no N+1
- [ ] No duplication of DLQ / UsageMetering logic

## Out of Scope (explicit)

- Billing write actions (refunds, credits) — Stripe dashboard for now.
- Bulk destructive operations.
- Cross-hive task monitor (GAP-018 — separate task).
- Error log viewer (activity_log + DLQ cover it).
- Admin-of-admin role hierarchy (one flag, one role).
- Export / CSV of activity log.

## Notes for Implementer

- When implementing suspension on users, the **session revoke** step is driver-dependent (database vs. redis vs. cookie). Pick the right purge per `config('session.driver')`. Don't leave a user able to use an old cookie after being suspended.
- For the `PLATFORM_ADMIN_EMAILS` listener, use Laravel's `Login` event — simpler than modifying `AuthenticatedSessionController` and composes with OAuth providers that bypass the classic login controller.
- The admin audit helper (`AdminActionAuditor`) should be dumb — one method `record(string $action, Model $target, array $extras = [])`. Don't overbuild it.
- `AdminLayout`'s red accent: a top border stripe (2px) or a small pill in the header — subtle, not garish. The point is "you'd notice if you were in admin mode by accident."
