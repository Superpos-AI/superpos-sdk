# TASK-291: Sidebar restructure (Work / Discuss / Automations)

**Status:** pending
**Branch:** `task/291-sidebar-restructure`
**PR:** —
**Depends on:** TASK-290 (issues REST API)
**Blocks:** TASK-292 (which transitively blocks TASK-293, TASK-294)
**Edition:** shared
**Feature doc:** [`docs/proposals/issues-concept.md`](../proposals/issues-concept.md) (§8 UI, sidebar nav)

## Objective

Restructure the dashboard sidebar to introduce the new top-level grouping
required by Phase 2 of the Issues rollout (spec §8):

- New **Work** group with `Issues` (placeholder route — fills in
  TASK-292) and the existing **Approvals** entry moved underneath it;
- New **Discuss** group containing existing **Channels**;
- Rename `Build` group → **Automations**;
- Rename the **Tasks** UI label → **Runs** (UI-only — the model, table
  `tasks`, URL `/dashboard/tasks`, and SDK contracts stay unchanged);
- Keep `Schedules`, `Triggers` (Webhooks), and `Workflows` distinct under
  Automations.

This is a **navigation- and labelling-focused** change. No new feature
pages or controllers are introduced — the only new render surface is a
minimal Inertia stub for the `Issues` sidebar entry (see FR-5 and the
file list below), which lands on a "coming soon" panel until TASK-292
ships. The Task → Run UI rename covers the sidebar label **and** all
page-level copy (titles, breadcrumbs, headings, button labels) per the
proposal §8 *Naming* paragraph.

## Requirements

### Functional

- [ ] FR-1: `resources/js/Layouts/AppLayout.jsx` exposes the new
      grouped sections in this order: *(ungrouped)*, `Agents`, `Work`,
      `Discuss`, `Automations`, `Connect`, `Observe`, `Govern` —
      replacing the current `Build` grouping while preserving all
      existing sidebar entries.
- [ ] FR-2: `Work` group contains: `Issues` (new), `Approvals` (moved
      from Govern).
- [ ] FR-3: `Discuss` group contains: `Channels` (moved from Connect).
- [ ] FR-4: `Automations` group contains: `Runs` (label rename of
      Tasks, href stays `/dashboard/tasks`), `Workflows`, `Schedules`,
      `Knowledge`, `Events`, and `Triggers` (label for Webhooks, href
      stays `/dashboard/webhooks`). This carries over all entries from
      the old `Build` group except Tasks (renamed), and additionally
      pulls `Webhooks` in from `Connect` under the new `Triggers`
      label per the proposal (`docs/proposals/issues-concept.md` §8,
      sidebar nav). **Deviation from proposal §8:** the proposal lists
      Automations as `Runs`, `Schedules`, `Triggers`, `Workflows` only
      and keeps `Knowledge` (and implicitly `Events`) as separate
      top-level entries. This task intentionally keeps `Knowledge` and
      `Events` under `Automations` to preserve the existing `Build`
      grouping (no entry silently dropped — see the mapping table
      below). Reconciling the proposal text with this placement is
      tracked separately and out of scope for this ticket.
- [ ] FR-5: `Issues` href points to `/dashboard/issues` (route is added
      with a placeholder Inertia render returning a "coming soon" panel
      until TASK-292 lands). Route is registered in `routes/web.php`
      under the same auth middleware group as other dashboard pages.
- [ ] FR-6: Existing `/dashboard/tasks` route and Tasks pages continue
      to work. The sidebar label, page titles, breadcrumbs, and table
      headers are renamed from "Task(s)" to "Run(s)" per the proposal
      (§8, *Naming* paragraph). The URL `/dashboard/tasks` is unchanged.
- [ ] FR-7: All other existing sidebar groups and entries remain
      unchanged (see target mapping below).
- [ ] FR-8: The Task → Run UI copy rename covers the following pages
      (labels only — no URL, model, or API changes):
      - `Tasks.jsx` — `<Head title>`, `<h1>`, status header ("Task
        Pipeline"), "Create Task" button label, **and the Bulk
        Cancel dialog surface**: the `<DialogTitle>` "Bulk Cancel
        Tasks" → "Bulk Cancel Runs" (`Tasks.jsx:127`), the
        in-dialog `Task Type` field label → `Run Type`
        (`Tasks.jsx:159`), and the prose "Cancel all tasks matching
        the filters below" → "Cancel all runs matching the filters
        below" (`Tasks.jsx:141`) plus the result line "tasks
        cancelled" → "runs cancelled" (`Tasks.jsx:134`). The
        `Bulk Cancel` button label itself (`Tasks.jsx:181, 440`) is
        verb-only and stays as-is.
      - `Tasks/Create.jsx` — `<Head title>`, "Back to Tasks" link
        label, `<h1>` heading, and the submit button label:
        `Create Task` → `Create Run` (and the in-flight
        `Creating...` label stays as-is since it is verb-only).
        The button is rendered around `Tasks/Create.jsx:906-913`.
      - `Tasks/Show.jsx` — `<Head title>`, "Back to Tasks" link label,
        the two action button labels at the top of the page
        (`Cancel Task` → `Cancel Run` at `Tasks/Show.jsx:397`,
        `Restart Task` → `Restart Run` at `Tasks/Show.jsx:409`),
        **and the remaining `Task`-labelled headings/labels on the
        detail page**: `Scheduled Task` → `Scheduled Run`
        (`Tasks/Show.jsx:427`), `Task Timeout` → `Run Timeout`
        (`Tasks/Show.jsx:477`), and `Parent Task` → `Parent Run`
        (`Tasks/Show.jsx:563`, `CardTitle`). **Plus two additional
        `Task`-labelled surfaces on the same page that must move with
        the rename:** the On-Complete section field label
        `Spawn Task Type` → `Spawn Run Type` (`Tasks/Show.jsx:137`,
        rendered inside `OnCompleteSection`) and the failure-policy
        labels map entry `task_timeout: 'Task Timeout'` →
        `task_timeout: 'Run Timeout'` (`Tasks/Show.jsx:176`, inside
        the `labels` object in `FailurePolicySection`). The
        underlying object key `task_timeout` (and the matching key in
        the `formatValue` switch at `Tasks/Show.jsx:184`) is part of
        the failure-policy payload contract and stays as-is — only
        the displayed label string changes. The in-flight
        `Cancelling…` / `Restarting…` labels are verb-only and stay
        as-is.

### Target Sidebar Mapping

The table below maps **every** existing sidebar entry (from the live
`AppLayout.jsx` on `main`) to its new location. No entry may be
silently dropped.

| Current Group  | Entry          | Href                           | New Group       | Notes                                  |
|----------------|----------------|--------------------------------|-----------------|----------------------------------------|
| *(ungrouped)*  | Dashboard      | `/dashboard`                   | *(ungrouped)*   | Unchanged                              |
| *(ungrouped)*  | Getting Started| `/dashboard/getting-started`   | *(ungrouped)*   | Unchanged                              |
| Agents         | Agents         | `/dashboard/agents`            | Agents          | Unchanged                              |
| Agents         | Sub-Agents     | `/dashboard/sub-agents`        | Agents          | Unchanged                              |
| Agents         | Hosted         | `/dashboard/hosted-agents`     | Agents          | Unchanged (feature-flagged)            |
| Agents         | Marketplace    | `/dashboard/marketplace/personas`| Agents        | Unchanged                              |
| Build          | Tasks          | `/dashboard/tasks`             | Automations     | **Renamed to "Runs"** (URL unchanged)  |
| Build          | Workflows      | `/dashboard/workflows`         | Automations     | Unchanged                              |
| Build          | Schedules      | `/dashboard/schedules`         | Automations     | Unchanged                              |
| Build          | Knowledge      | `/dashboard/knowledge`         | Automations     | Unchanged                              |
| Build          | Events         | `/dashboard/events`            | Automations     | Unchanged                              |
| Connect        | Services       | `/dashboard/services`          | Connect         | Unchanged                              |
| Connect        | Inboxes        | `/dashboard/inboxes`           | Connect         | Unchanged                              |
| Connect        | Webhooks       | `/dashboard/webhooks`          | **Automations** | **Moved** from Connect, **renamed to "Triggers"** (URL unchanged) |
| Connect        | Channels       | `/dashboard/channels`          | **Discuss**     | **Moved** from Connect                 |
| Observe        | Activity       | `/dashboard/activity`          | Observe         | Unchanged                              |
| Observe        | Proxy          | `/dashboard/proxy`             | Observe         | Unchanged                              |
| Observe        | Dead Letter    | `/dashboard/dead-letter`       | Observe         | Unchanged                              |
| Observe        | Hive Map       | `/dashboard/hive-map`          | Observe         | Unchanged                              |
| Observe        | LLM Usage      | `/dashboard/llm-usage`         | Observe         | Unchanged                              |
| Govern         | Policies       | `/dashboard/policies`          | Govern          | Unchanged                              |
| Govern         | Approvals      | `/dashboard/approvals`         | **Work**        | **Moved** from Govern                  |
| Govern         | Orchestration  | `/dashboard/orchestration`     | Govern          | Unchanged                              |
| Govern         | Experiments    | `/dashboard/experiments`       | Govern          | Unchanged                              |
| Govern         | Cross-Hive     | `/dashboard/cross-hive`        | Govern          | Unchanged                              |
| *(new)*        | Issues         | `/dashboard/issues`            | **Work**        | **New** — placeholder until TASK-292   |

### Non-Functional

- [ ] NFR-1: All existing AppLayout snapshot/render tests still pass
      after the restructure (update them where assertions reference
      `Build` or `Tasks`).
- [ ] NFR-2: PSR-12 + Pint clean on any PHP touched (route file).
- [ ] NFR-3: ESLint clean on the React layout file.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docs/tasks/TASK-291-sidebar-restructure.md` | This file |
| Modify | `resources/js/Layouts/AppLayout.jsx` | Regroup nav into Work / Discuss / Automations |
| Modify | `resources/js/Layouts/__tests__/*` | Update assertions for new group labels |
| Modify | `resources/js/Pages/Tasks.jsx` | Rename "Tasks" → "Runs" in page title, h1, status header, CTA button. Additionally rename the Bulk Cancel dialog surface: `<DialogTitle>` "Bulk Cancel Tasks" → "Bulk Cancel Runs" (line 127), in-dialog field label "Task Type" → "Run Type" (line 159), prose "Cancel all tasks matching the filters below" → "Cancel all runs matching the filters below" (line 141), result line "tasks cancelled" → "runs cancelled" (line 134). Leave the verb-only `Bulk Cancel` button (lines 181, 440) as-is. |
| Modify | `resources/js/Pages/Tasks/Create.jsx` | Rename "Back to Tasks" → "Back to Runs", `<h1>` and `<Head title>` heading, and the submit button label "Create Task" → "Create Run" (button at lines 906-913) |
| Modify | `resources/js/Pages/Tasks/Show.jsx` | Rename "Task:" → "Run:" in title, "Back to Tasks" → "Back to Runs", the two action button labels at the top of the page: "Cancel Task" → "Cancel Run" (line 397) and "Restart Task" → "Restart Run" (line 409). Additionally rename the remaining `Task`-labelled headings/labels on the detail page: "Scheduled Task" → "Scheduled Run" (line 427), "Task Timeout" → "Run Timeout" (line 477 — the action-button surface), and the `<CardTitle>` "Parent Task" → "Parent Run" (line 563). **Plus two additional surfaces:** the `OnCompleteSection` field label "Spawn Task Type" → "Spawn Run Type" (line 137) and the `FailurePolicySection` labels-map entry `task_timeout: 'Task Timeout'` → `task_timeout: 'Run Timeout'` (line 176). The underlying `task_timeout` object key in both the `labels` map (line 176) and the `formatValue` switch (line 184) is part of the failure-policy payload contract and must NOT be renamed — only the displayed string changes. |
| Create | `resources/js/Pages/Issues/Placeholder.jsx` | Stub "Issues — coming soon" page |
| Modify | `routes/web.php` | Register `/dashboard/issues` → placeholder |

### Decisions (locked in)

1. **UI-only rename for Tasks → Runs.** The `Task` model, `tasks`
   table, `/api/v1/.../tasks` routes, `/dashboard/tasks` URL, and SDK
   contracts stay untouched. The sidebar label, page titles,
   breadcrumbs, headings, and button labels are all renamed from
   "Task(s)" to "Run(s)" (see FR-6/FR-8). The dashboard task URL
   keeps its name to avoid breaking deep links; renaming the URL is
   out of scope.
2. **Issues placeholder ships in this task.** This keeps the sidebar
   functional after merge — clicking `Issues` lands on a friendly
   stub rather than a 404. TASK-292 replaces the stub.
3. **Approvals is moved, not duplicated.** The old position is removed
   and the entry now lives under `Work` alongside `Issues`.

## Test Plan

### Component / render tests

- Sidebar renders the three new groups in the documented order.
- `Issues` link is present and points to `/dashboard/issues`.
- `Approvals` link is present under `Work`.
- `Runs` label appears in the `Automations` group; the underlying href
  is still `/dashboard/tasks`.

### Feature tests

- Visiting `/dashboard/issues` returns 200 and renders the placeholder
  page (Inertia component name `Issues/Placeholder`).
- Visiting `/dashboard/tasks` still returns 200 with the existing
  Tasks page (regression check).

### Page copy rename verification

- `Tasks.jsx`: page title is "Runs", `<h1>` reads "Runs", status
  header reads "Run Pipeline", CTA button reads "Create Run". The
  Bulk Cancel dialog title reads "Bulk Cancel Runs", its in-dialog
  field label reads "Run Type", its descriptive prose reads "Cancel
  all runs matching the filters below", and the result line reads
  "runs cancelled". The standalone `Bulk Cancel` trigger/submit
  button stays as "Bulk Cancel" (verb-only, intentional).
- `Tasks/Create.jsx`: page title is "Create Run", breadcrumb link
  reads "Back to Runs", `<h1>` reads "Create Run", and the submit
  button reads "Create Run" (no remaining "Create Task" string in
  the file).
- `Tasks/Show.jsx`: page title reads "Run: {type}", breadcrumb link
  reads "Back to Runs", the cancel action button reads "Cancel Run"
  (no remaining "Cancel Task" string), and the restart action button
  reads "Restart Run" (no remaining "Restart Task" string). The
  scheduled-task callout heading reads "Scheduled Run", the timeout
  metadata card label reads "Run Timeout" (in the scheduled branch),
  and the parent-task `<CardTitle>` reads "Parent Run". The
  On-Complete section field label reads "Spawn Run Type" (no
  remaining "Spawn Task Type" string), and the failure-policy
  labels-map entry for `task_timeout` renders as "Run Timeout" (no
  remaining "Task Timeout" string anywhere in the file). The
  underlying `task_timeout` object key in the labels map and the
  `formatValue` switch is unchanged — failure-policy payload keys
  are part of the API contract, not user-visible copy.

## Out of Scope (deferred)

- The actual Issues Index / Show / Create pages (TASK-292, 293, 294).
- Renaming the `Task` model, `tasks` table, or API paths.
- Renaming `Webhooks` route/URL to `Triggers` (label-only change is
  acceptable for this task; URL rename is deferred).

## Validation Checklist

- [ ] Sidebar groups appear as: Work, Discuss, Automations.
- [ ] `Issues` placeholder route returns 200.
- [ ] `Tasks` page still renders under `Runs` label.
- [ ] Task page titles, headings, breadcrumbs, and button labels all
      say "Run(s)" instead of "Task(s)" (Tasks.jsx, Create.jsx,
      Show.jsx). Specifically: `Create Task` → `Create Run`
      (Create.jsx submit button), `Cancel Task` → `Cancel Run`
      (Show.jsx action button), `Restart Task` → `Restart Run`
      (Show.jsx action button), `Bulk Cancel Tasks` → `Bulk Cancel
      Runs` (Tasks.jsx dialog title), `Task Type` → `Run Type`
      (Tasks.jsx in-dialog field label), `Scheduled Task` →
      `Scheduled Run` (Show.jsx callout heading), `Task Timeout` →
      `Run Timeout` (Show.jsx scheduled-branch metadata card),
      `Parent Task` → `Parent Run` (Show.jsx `<CardTitle>`),
      `Spawn Task Type` → `Spawn Run Type` (Show.jsx
      `OnCompleteSection` field label), and the failure-policy
      labels-map entry `task_timeout: 'Task Timeout'` →
      `task_timeout: 'Run Timeout'` (Show.jsx `FailurePolicySection`
      — note the object key `task_timeout` stays as-is, only the
      displayed string changes). The standalone `Bulk Cancel` button
      label (Tasks.jsx) remains `Bulk Cancel` — verb-only, no noun
      to rename. A grep for
      `Create Task|Cancel Task|Restart Task|Bulk Cancel Tasks|Scheduled Task|Task Timeout|Parent Task|Spawn Task Type`
      across `resources/js/Pages/Tasks.jsx` and
      `resources/js/Pages/Tasks/` returns no matches after this
      task. (The grep token `Task Timeout` covers both the
      action-button surface at line 477 and the failure-policy
      labels-map entry at line 176 — both must be renamed for the
      grep to return clean.)
- [ ] Existing AppLayout tests updated and green.
- [ ] PSR-12 / Pint clean on touched PHP.
- [ ] Full suite green (`php artisan test`, `npm test`).
