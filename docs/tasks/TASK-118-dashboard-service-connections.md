# TASK-118: Dashboard — Service Connections Manager

**Priority:** High (blocks usability of Policies, Webhook Routes, and Proxy)
**Phase:** 2 — Service Proxy & Security
**Depends On:** 036 (service connections model), 038 (connector interface), 022 (Inertia/React)
**Blocked By:** None of the dependencies are pending — 036 is done, 038 code exists on main

## Problem

There is no dashboard UI for managing service connections. Users can only create
them via the agent-facing API (`POST /api/v1/connectors`), which requires an
agent token and API knowledge. This makes the Policies, Webhook Routes, and
Proxy pages unusable for new installs — all show empty service dropdowns.

## Goal

Add a full-featured **Service Connections** dashboard page where users can:

1. **List** all service connections for the current apiary (name, type, status, connector)
2. **Create** a new service connection with a guided setup flow
3. **Edit** an existing service connection (name, credentials, base URL, active toggle)
4. **Delete** a service connection (with confirmation)
5. **Test** a connection (optional, if feasible — e.g., ping the base_url)

## Data Model (already exists)

```
ServiceConnection:
  id, superpos_id, name, type, base_url, auth_type, auth_config (encrypted),
  connector_id (FK), webhook_secret (encrypted), is_active

  AUTH_TYPES = ['token', 'oauth2', 'basic', 'api_key', 'none']
  TYPES      = ['github', 'slack', 'jira', 'linear', 'custom']

Connector:
  id, superpos_id, type, name, class_path, is_builtin, config, created_by
  BUILTIN_TYPES = ['github', 'slack']
```

## UI Design

### Page: `/dashboard/services`

**Sidebar entry:** "Services" — placed between "Proxy" and "Webhooks" in the nav.

**Empty state:** Illustrated card with "No services connected yet" and two CTAs:
- "Connect a Service" — opens the setup dialog
- "Set up with Claude Code" — shows a copyable CC prompt snippet

**List view (when services exist):**

| Name | Type | Auth | Status | Created | Actions |
|------|------|------|--------|---------|---------|
| GitHub Production | github | token | Active | 2d ago | Edit · Delete |
| Slack Workspace | slack | oauth2 | Active | 5d ago | Edit · Delete |

- Badge for type (color-coded: github=gray, slack=purple, custom=blue)
- Toggle switch for is_active in the row
- Click row to edit

### Dialog: "Connect a Service"

**Step 1 — Choose type:**
Cards/buttons for each supported type:
- GitHub (built-in) — icon + "Connect GitHub"
- Slack (built-in) — icon + "Connect Slack"
- Custom — icon + "Custom Service"

**Step 2 — Configure (varies by type):**

For **GitHub**:
- Name (pre-filled: "GitHub")
- Base URL (pre-filled: "https://api.github.com")
- Personal Access Token (password input)
- Webhook Secret (optional, password input)

For **Slack**:
- Name (pre-filled: "Slack")
- Bot Token (password input, starts with xoxb-)
- Signing Secret (password input)

For **Custom**:
- Name (required)
- Type slug (required, lowercase alphanumeric + hyphens)
- Base URL (required)
- Auth Type (select: token / oauth2 / basic / api_key / none)
- Auth credentials (dynamic fields based on auth_type):
  - token: single token field
  - basic: username + password
  - api_key: key name + key value
  - oauth2: client_id + client_secret + token_url
  - none: no fields
- Webhook Secret (optional)

**Step 3 — Confirmation:**
- Summary of what was created
- "You can now use this service in Policies, Webhook Routes, and Proxy"

### Claude Code Integration

On the empty state and in the "Connect a Service" dialog header, show a
collapsible section: **"Set up with Claude Code"** containing:

```
To connect a service, paste this in Claude Code:

> Add a GitHub service connection to Superpos with my token.
> Repository: owner/repo, Token: ghp_xxx

Or for Slack:

> Add a Slack service connection to Superpos.
> Bot Token: xoxb-xxx, Signing Secret: xxx
```

This is informational — CC can already create connections via `artisan tinker`
or the API. The snippets just make it easy for users to ask CC.

## Backend

### Controller: `ServiceConnectionDashboardController`

```
GET    /dashboard/services                → index()
GET    /dashboard/services/create         → create()
POST   /dashboard/services                → store()
GET    /dashboard/services/{id}/edit      → edit()
PATCH  /dashboard/services/{id}           → update()
DELETE /dashboard/services/{id}           → destroy()
POST   /dashboard/services/{id}/toggle    → toggle()
```

**index():** Paginated list with search, type filter, status filter.
Pass `services`, `typeBreakdown`, `filters` to Inertia.

**create():** Render form with available connectors and type options.

**store():** Validate, create ServiceConnection with encrypted auth_config,
auto-link to connector if type matches a builtin. Log activity.

**edit():** Load service (decrypt auth_config for form, mask sensitive fields).

**update():** Validate, update. If auth_config fields are blank, keep existing
(don't overwrite with empty). Log activity.

**destroy():** Check no active policies/routes reference this service, or warn.
Soft-confirm via request param. Log activity.

**toggle():** Flip is_active. Log activity.

### Validation Rules

```php
'name'           => ['required', 'string', 'max:255', Rule::unique('service_connections', 'name')->where('superpos_id', $apiaryId)],
'type'           => ['required', 'string', 'max:100', Rule::in(ServiceConnection::TYPES)],
'base_url'       => ['required_unless:type,slack', 'nullable', 'url', 'max:500'],
'auth_type'      => ['required', Rule::in(ServiceConnection::AUTH_TYPES)],
'auth_config'    => ['required_unless:auth_type,none', 'array'],
'webhook_secret' => ['nullable', 'string', 'max:500'],
'is_active'      => ['sometimes', 'boolean'],
```

## Sidebar Nav Update

In `AppLayout.jsx`, add "Services" entry between "Proxy" and "Webhooks":

```jsx
{ name: 'Services', href: '/dashboard/services', icon: Plug }
```

## Files to Create / Modify

### Create:
- `app/Http/Controllers/Dashboard/ServiceConnectionDashboardController.php`
- `resources/js/Pages/Services.jsx` (list page)
- `resources/js/Pages/ServiceForm.jsx` (create/edit form)
- `tests/Feature/Dashboard/ServiceConnectionDashboardTest.php`

### Modify:
- `routes/web.php` — add service connection routes
- `resources/js/Layouts/AppLayout.jsx` — add sidebar entry
- `resources/js/Pages/PolicyForm.jsx` — link to services page from empty state
- `resources/js/Pages/WebhookRouteForm.jsx` — link to services page from empty state

## Test Plan

- [ ] Index page renders with 0 services (empty state)
- [ ] Index page renders with services (list view)
- [ ] Create flow: GitHub type pre-fills fields correctly
- [ ] Create flow: Slack type pre-fills fields correctly
- [ ] Create flow: Custom type shows dynamic auth fields
- [ ] Store validates unique name per apiary
- [ ] Store encrypts auth_config and webhook_secret
- [ ] Edit loads service with masked credentials
- [ ] Update preserves credentials when fields left blank
- [ ] Delete with confirmation
- [ ] Toggle is_active via PATCH
- [ ] Sidebar shows "Services" link
- [ ] Service count matches type filter
- [ ] Search by name works
- [ ] After creating a service, Policy/WebhookRoute forms show it in dropdown

## Definition of Done

- [ ] CRUD operations work end-to-end
- [ ] Credentials are never exposed in plaintext (masked in UI, encrypted in DB)
- [ ] Empty states on PolicyForm and WebhookRouteForm link to `/dashboard/services`
- [ ] Tests pass
- [ ] PSR-12 compliant
- [ ] Activity logged on create/update/delete/toggle
