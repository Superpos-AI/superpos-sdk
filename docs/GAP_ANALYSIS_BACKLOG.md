# Gap Analysis Backlog

> Generated 2026-04-03 from analysis of PRs 53-353 (~300 merged PRs).
> These are **integration gaps** — features that are partially implemented,
> missing their UI/API/SDK counterpart, or architecturally incomplete.
> Each item has a short spec describing what's needed.

---

## P1 — SDK & API Coverage (Systemic)

### GAP-001: Python/Shell SDK missing methods for core features

**Problem:** The SDKs have no methods for many features shipped in the last month.
Agents using these features must make raw HTTP calls, defeating the SDK's purpose.

**Missing from Python SDK (`SuperposClient`):**

| Category | Methods needed |
|----------|---------------|
| Workflows | `list_workflows`, `run_workflow`, `get_workflow_run`, `cancel_workflow_run` |
| Templates | `list_agent_templates`, `install_agent_template` |
| Threads | `create_thread`, `append_thread_message`, `get_thread` |
| Experiments | `create_experiment`, `get_experiment_results` |
| Approvals | `list_approvals`, `approve`, `deny` |
| Service proxy | `proxy_request(service_id, method, path, body)` |
| Events | `publish_event`, `poll_events`, `subscribe`, `list_subscriptions` |
| Inboxes | `list_inboxes`, `create_inbox`, `update_inbox` |
| Dead letter | `list_dead_letter`, `requeue_task` |
| Attachments | `upload_attachment`, `download_attachment`, `list_attachments` |
| Fan-out | `create_task` with `completion_policy` + `children` params |
| Dependencies | `add_dependency`, `remove_dependency` |

Shell SDK: same gaps. OpenClaw SDK: even further behind (no persona, threads, events).

All API endpoints already exist — this is purely SDK client code.

---

### GAP-002: Expose marketplace at `/api/v1/agent-templates/`

**Problem:** Agent templates are dashboard-only. Agents can't browse or install programmatically.

**Spec:**
```
GET    /api/v1/hives/{hive}/agent-templates             # list (marketplace.read)
GET    /api/v1/hives/{hive}/agent-templates/{id}         # details (marketplace.read)
POST   /api/v1/hives/{hive}/agent-templates/{id}/install # install (marketplace.install)
```

---

## P2 — Missing Dashboard UI

### GAP-003: Dead letter queue dashboard

**Problem:** Dead letter tasks are invisible in the dashboard. Operators can't see stuck tasks without calling the API directly.

**Spec:** New page at `/dashboard/dead-letter`:
- Table: task type, error, failed_at, retry count, agent
- "Requeue" button per task (calls `POST /tasks/{task}/requeue`)
- Bulk requeue checkbox
- Filter by task type, age
- Link from task board sidebar or nav

**API exists:** `GET /hives/{hive}/tasks/dead-letter`, `POST /hives/{hive}/tasks/{task}/requeue`

---

### GAP-004: Task replay button in dashboard

**Problem:** Task replay API exists, Python SDK has methods, but no dashboard UI. Operators must use API/SDK directly.

**Spec:** Add to task detail page (`Tasks/Show.jsx`):
- "Replay" button (visible for completed/failed/dead_letter/expired tasks)
- Confirmation modal: "Replay this task with same payload?"
- Optional: payload override textarea
- Calls `POST /hives/{hive}/tasks/{task}/replay`
- Shows link to the new replayed task

**API exists:** `POST /hives/{hive}/tasks/{task}/replay`, `GET /hives/{hive}/tasks/{task}/trace`

---

### GAP-005: Schedule edit from dashboard

**Problem:** Can create and delete schedules from dashboard, but can't edit. Must use API.

**Spec:**
- Add route: `GET /dashboard/schedules/{schedule}/edit`
- Reuse `Schedules/Create.jsx` form with pre-filled data
- Add "Edit" button to schedule show page
- Controller: `ScheduleDashboardController::edit()` + `::update()`

**API exists:** `PUT /api/v1/hives/{hive}/schedules/{schedule}`

---

### GAP-006: Events dashboard page

**Problem:** Event bus API exists but no dashboard page to view published events or subscriptions.

**Spec:** New page at `/dashboard/events`:
- List recent events (type, payload preview, hive, timestamp)
- Show subscriptions per agent
- Filter by event type, hive
- Cross-hive events highlighted

**API exists:** `GET /hives/{hive}/events/poll`, `GET /agents/subscriptions`

---

### GAP-007: Attachment management UI

**Problem:** File attachment API exists (upload/download/list/delete) but no dashboard page.

**Spec:** Add to task detail page + standalone page:
- Task detail: "Attachments" section listing files linked to this task
- Upload button on task detail
- Standalone page `/dashboard/attachments`: browse all hive attachments
- Download button, delete button, file size/type display

**API exists:** Full CRUD at `/hives/{hive}/attachments`

---

### GAP-008: Persona performance dashboard page

**Problem:** Route and controller exist (`/dashboard/agents/{agent}/persona/performance`) but React page component is missing.

**Spec:** Page showing per persona version:
- Task count, success rate, avg duration
- Chart: performance over versions
- Compare two versions side-by-side
- Link from persona editor page

**API exists:** Controller method returns data, page component needs to be built.

---

### GAP-009: Stream delivery monitoring

**Problem:** Stream delivery API exists but no UI to view streaming task chunks.

**Spec:** In task detail view, when `delivery_mode = 'stream'`:
- "Stream Chunks" section
- List chunks (index, size, created_at)
- Stream status (in-progress / finalized)
- Download assembled result

**API exists:** `POST /tasks/{task}/stream-chunk`, `GET /tasks/{task}/stream-chunks`

---

## P2 — Incomplete Feature Wiring

### GAP-010: Knowledge references CRUD API + builder UI (TASK-192)

**Status:** **RESOLVED** — shipped in commit `40ec333b` ("feat: add knowledge references to workflow steps [TASK-192]"). `WorkflowStepKnowledgeController` provides `index/store/destroy`, `KnowledgeReferencesSection` is wired into the agent-step panel in `resources/js/Pages/WorkflowBuilder.jsx`, and feature coverage lives in `tests/Feature/WorkflowStepKnowledgeTest.php`. Follow-ups `71a2f90f` (snapshot refs in workflow versions + migrate on step rename) and `df4ad42a` refined edge cases.

**Problem:** `WorkflowStepKnowledge` model exists, no API or builder integration.

**Spec:**
- API: `POST/GET/DELETE /workflows/{workflow}/steps/{step}/knowledge`
- Builder: "Knowledge Context" section in step panel — pick knowledge entries by role

---

### GAP-011: Built-in workflow templates (TASK-193)

**Problem:** Workflow engine + loop step ready, but no starter templates.

**Spec:** Seed 4 templates:
1. Plan-Build-QA (3 agents + condition for retry)
2. Code Review Pipeline (webhook → fan_out → aggregate)
3. Generator-Evaluator Loop (loop step)
4. Data Pipeline (schedule → fetch → transform → validate → load)

UI: "Start from template" button on workflow list, template picker modal.

---

### GAP-012: QA evaluator persona template (TASK-194)

**Status:** **RESOLVED** — shipped in PR [#477](https://github.com/Superpos-AI/superpos-app/pull/477) ("feat: QA evaluator persona template [TASK-194]"). PersonaTemplateSeeder includes the QA Evaluator template with SOUL, EXAMPLES, and RULES sections returning `{score, pass, feedback}` JSON.

**Problem:** Loop step enables gen-eval patterns but no skeptical evaluator persona template.

**Spec:** Add to PersonaTemplateSeeder:
- Name: "QA Evaluator"
- SOUL: rigorous reviewer, honest scoring
- EXAMPLES: 3-5 calibrated grading samples
- RULES: return `{score, pass, feedback}` JSON, threshold 7/10

---

### GAP-013: Verify workflow cost dashboard (TASK-196)

**Problem:** Routes exist, UI may not render correctly.

**Spec:** Verify and fix `/dashboard/workflows/{workflow}/cost`:
- Per-step cost breakdown table
- Historical cost chart
- Average cost per run

---

## P3 — Polish & Discoverability

### GAP-014: Reaction router dashboard config

**Problem:** Event reaction router is code-level config only. No dashboard UI.

**Spec:** Page at `/dashboard/reactions`:
- List reaction rules (event pattern → action)
- Create/edit/delete rules
- Actions: wake_session, notify, react

---

### GAP-015: Service catalog real-time health

**Problem:** Service catalog page exists but may lack live worker status.

**Spec:** Enhance `ServiceCatalog.jsx`:
- Per-worker online dot (green/red from heartbeat)
- Requests/min, error rate
- Auto-refresh or WebSocket

---

### GAP-016: Navigation link to workflow cost

**Problem:** Only accessible from workflow detail view.

**Spec:** Add cost icon button (DollarSign) to workflow list rows.

---

### GAP-017: Dream history view

**Problem:** Dream toggle exists on agent page but no history of past dream tasks.

**Spec:** In agent detail, "Dream History" section:
- Last 5 dream tasks with status, date, summary excerpt
- Link to full dream task detail

---

### GAP-018: Cross-hive monitor actions

**Problem:** Cross-hive monitor is read-only. Can't cancel tasks or revoke permissions.

**Spec:** Add action buttons:
- "Cancel" on cross-hive tasks
- "Revoke" on cross-hive permissions
- Confirmation modals

---

### GAP-019: TASKS.md status sync

**Problem:** Several tasks marked ⬜ have merged code, or ✅ without PR links.

**Spec:** Cross-reference `git log` with TASKS.md and update statuses/links.

---

## Summary

| # | Gap | Priority | Effort | Category |
|---|-----|----------|--------|----------|
| GAP-001 | SDK methods for 12+ feature areas | P1 | 3-5 days | SDK |
| GAP-002 | Marketplace agent API | P1 | 1 day | API |
| GAP-003 | Dead letter queue dashboard | P2 | 1 day | UI |
| GAP-004 | Task replay button in dashboard | P2 | 0.5 day | UI |
| GAP-005 | Schedule edit dashboard | P2 | 0.5 day | UI |
| GAP-006 | Events dashboard page | P2 | 1 day | UI |
| GAP-007 | Attachment management UI | P2 | 1 day | UI |
| GAP-008 | Persona performance page | P2 | 0.5 day | UI |
| GAP-009 | Stream delivery monitoring | P2 | 0.5 day | UI |
| GAP-010 | Knowledge refs CRUD + builder (192) ✅ shipped in `40ec333b` | P2 | 1-2 days | Feature |
| GAP-011 | Workflow templates (193) | P2 | 1 day | Feature |
| GAP-012 | QA evaluator persona (194) ✅ shipped in PR [#477](https://github.com/Superpos-AI/superpos-app/pull/477) | P2 | 0.5 day | Feature |
| GAP-013 | Workflow cost dashboard (196) | P2 | 0.5 day | Verify |
| GAP-014 | Reaction router dashboard | P3 | 1 day | UI |
| GAP-015 | Service catalog live health | P3 | 1 day | UI |
| GAP-016 | Workflow cost nav link | P3 | 0.5 hour | UI |
| GAP-017 | Dream history view | P3 | 0.5 day | UI |
| GAP-018 | Cross-hive monitor actions | P3 | 0.5 day | UI |
| GAP-019 | TASKS.md status sync | P3 | 0.5 hour | Docs |

**Total estimated effort:** ~15-20 days of work across all priorities.
