# Proposal: Issues Concept (management layer alongside Tasks)

Status: Draft for review
Owner: Product
Scope: Adds a management/operational layer (Issues) alongside the existing execution layer (Tasks). No breaking changes.

---

## 1. Problem

Managers using Superpos today have no durable, structured place to plan, track, and hand off work. Channels (`app/Models/Channel.php`) are conversational by design — discussion of record, not state of record — and don't express dependencies, blocking, or assignment in a queryable way. Tasks (`app/Models/Task.php`) are one-shot execution units optimized for agents: they start, run, end, and are gone from the active workspace. Nothing survives across multiple agents or human/agent handoffs as a single, addressable unit of intent. Dependencies between pieces of work, "blocked on human" states, and recommended actions cannot be modeled without overloading either Channels (wrong shape) or Tasks (wrong lifecycle). Issues fills this gap.

## 2. Goals / Non-goals

**Goals**
- Introduce Issues as the primary noun managers see in the UI for "what is the system working on."
- Strictly separate planning (Issue) from execution (Task). One Issue can trigger many Task runs over time.
- Express blocking, dependencies, and ownership in a first-class, queryable way.
- Provide a Paperclip-style "blocked on human" card that resumes work automatically on approval.
- Establish a per-IssueType trust model so some issues auto-close by agent and others require human sign-off.
- Reuse existing infrastructure: Thread for discussion, ApprovalRequest for human gates, Channel as linked discussion-of-record, Task as the execution mechanism.

**Non-goals (V1)**
- Replacing Channels, Tasks, or Schedules. All continue to exist unchanged.
- Cross-hive issues, GitHub-issue linking, SLAs, due dates, custom fields, board view, human-readable IDs.
- A workflow engine — Issue state is intentionally small.

## 3. Concepts

**Issue** — A planned, addressable unit of intent that lives across multiple Task runs and human/agent handoffs. Has a type, state, assignee, dependencies, and a linked discussion. Owns *planning state*.

**IssueType** — A configurable kind of work (e.g. `bug`, `release`, `customer_request`, `ops_followup`). Carries the trust policy that governs how its issues close.

**Trust resolution** — When an agent attempts to close an issue, three values compose: Hive policy (most authoritative), IssueType default, Agent trust modifier. The most restrictive wins.

**Operational vs execution coupling** — Crisp separation, no overlap:

| Concern | Owned by Issue | Owned by Task |
|---|---|---|
| Intent / goal statement | yes | no |
| State machine for *planning* (open, blocked, done) | yes | no |
| State machine for *execution* (pending, running, completed, failed) | no | yes |
| Assignee (human or agent) | yes | no |
| Dependencies on other work | yes | no |
| Per-run logs, retries, idempotency, dead-letter | no | yes |
| Approval gates for state transitions | yes (via ApprovalRequest) | no |
| Inbox routing, claim/poll mechanics | no | yes |
| Discussion of record | linked Channel + Thread | no |

A Task may carry an optional `issue_id` FK; it remains fully self-contained otherwise. An Issue may have zero or many associated Tasks ("Runs" tab in UI). **`tasks.issue_id` is the single canonical link between a Task and an Issue** — the `issue_links` polymorphic table is *not* used for Tasks (see §4 for details).

## 4. Data model

All IDs are ULIDs per Superpos convention (Task already uses `HasUlids`).

```text
issues
  id (ulid, pk)
  hive_id (ulid, fk -> hives.id, indexed)
  issue_type_id (ulid, fk -> issue_types.id)
  title (string, required)
  description (text, nullable)
  state (enum: open|in_progress|blocked|awaiting_review|done|cancelled, default open, indexed)
  assignee_type (enum: agent|user|null)
  assignee_id (ulid, nullable, polymorphic)
  created_by_type (enum: agent|user|system)
  created_by_id (ulid, nullable)
  thread_id (ulid, fk -> threads.id, nullable)         # discussion log (reuse Thread)
  channel_id (ulid, fk -> channels.id, nullable)       # optional linked Channel
  closed_by_type (enum: agent|user|system, nullable)
  closed_by_id (ulid, nullable)
  closed_at (timestamp, nullable)
  closure_reason (string, nullable)
  metadata (json, nullable)                            # free-form, e.g. {summary, risks}
  created_at, updated_at

issue_types
  id (ulid, pk)
  hive_id (ulid, fk -> hives.id, indexed)
  key (string, unique per hive, e.g. "bug")
  label (string)
  closure_policy (enum: agent_self_close|human_required|gated_by_approval)
  default_assignee_type, default_assignee_id (nullable)
  config (json, nullable)
  created_at, updated_at

issue_dependencies
  id (ulid, pk)
  issue_id (ulid, fk -> issues.id, cascade)
  depends_on_issue_id (ulid, fk -> issues.id)
  kind (enum: blocks|related, default blocks)
  unique(issue_id, depends_on_issue_id)

issue_links                                            # polymorphic junction (NOT used for Tasks — see below)
  id (ulid, pk)
  issue_id (ulid, fk -> issues.id, cascade)
  linkable_type (string)                               # Channel | KnowledgeEntry
  linkable_id (ulid)
  role (string, nullable)                              # e.g. "discussion", "approval", "reference"
  created_at
  index(linkable_type, linkable_id)
```

**Canonical linkage: Tasks → Issues**

Task-to-Issue linkage uses **one source of truth: `tasks.issue_id`** (a direct FK on the tasks table). The `issue_links` polymorphic junction table is explicitly *not* used for Tasks. Rationale:

- Tasks already follow the direct-FK pattern for related entities (`channel_id`, `thread_id`, `schedule_id`, etc.).
- A direct FK is simpler to query, eager-load, and enforce referentially than a polymorphic junction row.
- The `POST /{issue}/link-task` endpoint sets `tasks.issue_id` on the target task. Unlinking sets it to `null`.
- The "Runs" tab on the issue detail view queries `Task::where('issue_id', $issue->id)`.

The `issue_links` table handles the remaining polymorphic relationships (Channel, KnowledgeEntry) where a direct FK on the linked model would be inappropriate or where multiple links of the same type are needed. ApprovalRequests are **not** stored in `issue_links` — they use the existing `approvable` morph on `ApprovalRequest` (`approvable_type=Issue`, `approvable_id=issue.id`) as the single source of truth (see §7 and §9).

**Reused models:**
- `app/Models/Thread.php` — discussion log; one Thread per Issue, lazy-created. No changes.
- `app/Models/ApprovalRequest.php` — polymorphic human gate; `approvable_type=Issue`. No model changes.
- `app/Http/Controllers/Api/ApprovalController.php` — **minor change**: add optional `hive_id` query parameter to `index()` for hive-scoped filtering (see §9 approval scoping note).
- `app/Models/Channel.php` — optional discussion-of-record link. No changes.
- `app/Models/Task.php` (line 62, `$fillable`) — add nullable `issue_id` column + FK + `issue()` BelongsTo relation.

**Schema additions to existing tables:**
- `tasks.issue_id` (ulid, nullable, fk -> issues.id, indexed) — set when a task is enqueued in service of an issue.

## 5. State machine

Issue states: `open`, `in_progress`, `blocked`, `awaiting_review`, `done`, `cancelled`.

| From → To | Trigger | Allowed actor |
|---|---|---|
| open → in_progress | first Task starts, or manual claim | agent / system |
| open → cancelled | manual cancel | human |
| in_progress → blocked | agent emits "blocked-on-human" w/ ApprovalRequest | agent / system |
| in_progress → awaiting_review | agent claims work is done, policy != self_close | agent |
| in_progress → done | agent closes & policy = agent_self_close & trust allows | agent (gated) |
| in_progress → cancelled | manual cancel | human |
| blocked → in_progress | ApprovalRequest approved (auto-resume) | system |
| blocked → cancelled | ApprovalRequest rejected with `cancel_issue: true` in deny payload (see §7), or manual cancel | human |
| awaiting_review → done | human marks reviewed | human |
| awaiting_review → in_progress | human requests changes | human |
| done → open | reopen | human (audit-logged, decays agent trust) |
| cancelled → open | reopen | human |

Invalid transitions return 422. All transitions emit an `ActivityLog` entry with actor, from-state, to-state, reason.

## 6. Trust model

`IssueType.closure_policy`:
- `agent_self_close` — agent may close without human, subject to agent trust modifier and hive policy.
- `human_required` — only a human can transition issue to `done`. Agent moves to `awaiting_review`.
- `gated_by_approval` — closure creates an ApprovalRequest; approval transitions to `done`.

**Agent trust modifier** — integer 0–100 on `agents` (new column `issue_trust_score`, default 50). Rules:
- +N (small, e.g. +2) when an agent-closed issue is *not* reopened within a configurable window (default 7 days). Computed by a scheduled task.
- −M (larger, e.g. −10) on each human reopen of an agent-closed issue.
- Threshold to permit `agent_self_close`: trust ≥ 60 (configurable per hive).

**Most-restrictive-wins resolution** for "may agent close this issue?":

| Hive policy | IssueType policy | Agent trust | Result |
|---|---|---|---|
| allow_self_close | agent_self_close | ≥ threshold | allow |
| allow_self_close | agent_self_close | < threshold | block → awaiting_review |
| allow_self_close | human_required | any | block → awaiting_review |
| allow_self_close | gated_by_approval | any | create ApprovalRequest |
| require_approval (hive-wide) | any | any | create ApprovalRequest |
| disallow_self_close (hive-wide) | any | any | block → awaiting_review |

Every auto-close emits an `issue.closed.auto` audit event including resolved policy, agent trust, and rule path used. This is the primary signal for trust-model debugging.

## 7. Blocked-on-human flow

When an agent cannot proceed without a human decision:

1. Agent calls `POST /issues/{id}/request-approval` with payload:
   ```json
   {
     "summary": "Customer's bank requires manual KYC verification before retry.",
     "recommended_action": "Approve to re-run with manual_kyc=true",
     "risks": ["Will charge the customer a second time on retry."],
     "linked_issue_ids": ["01J…"]
   }
   ```
2. System transitions Issue `in_progress → blocked`, creates an `ApprovalRequest` (`approvable_type=Issue`, `approvable_id=issue.id`) with the structured payload stored on the request.
3. UI renders a Paperclip-style card on the issue detail and in the manager's **hive-scoped** approval queue (using the hive-scoped approval routes): summary, recommended action, risks, links to dependent issues. Three actions: **Approve**, **Reject** (keeps issue blocked), and **Reject & Cancel** (terminates the issue). All reject actions require a reason.
4. **On Approve** — system: (a) transitions Issue `blocked → in_progress`; (b) optionally enqueues a "resume" Task whose payload is templated from the ApprovalRequest payload (resume task creation is opt-in per issue type).
5. **On Reject** — two behaviors depending on the `cancel_issue` flag in the deny payload:
   - **Reject (keep blocked):** `POST /hives/{hive}/approvals/{approval}/deny` with payload `{ "reason": "...", "cancel_issue": false }` (or `cancel_issue` omitted — defaults to `false`). Issue stays `blocked`; rejection reason recorded on the ApprovalRequest and as a Thread message. Manager can later amend and re-approve, or manually cancel the issue via the issue transition endpoint.
   - **Reject and cancel:** `POST /hives/{hive}/approvals/{approval}/deny` with payload `{ "reason": "...", "cancel_issue": true }`. System: (a) records the rejection reason on the ApprovalRequest and as a Thread message; (b) transitions the Issue `blocked → cancelled` with the denial reason as the cancellation reason. This is the mechanism behind the `blocked → cancelled` state transition in §5.
   
   The UI renders both options: a **Reject** button (keeps issue blocked for further discussion) and a **Reject & Cancel** button (terminates the issue). Both require a reason.

Multiple sequential approvals on the same issue are supported — each is its own `ApprovalRequest` row with `approvable_type=Issue` and `approvable_id` set to the issue's ID. All approvals for an issue are discoverable via the `approvable` morph (`ApprovalRequest::where('approvable_type', Issue::class)->where('approvable_id', $issue->id)`). No `issue_links` row is created — the polymorphic `approvable` relationship is the single canonical linkage, consistent with how approvals already work for other approvable types.

## 8. UI

**Sidebar nav (manager view):**
- **Work** (new top section)
  - **Issues** (primary — list view, default landing)
  - Approvals (existing, now shows issue-linked ApprovalRequests prominently)
- **Discuss**
  - Channels (existing, unchanged)
- **Automations** (renamed from Build — verb form, parallel to Discuss)
  - **Runs** (UI rename of standalone Tasks list — see *Naming* note below)
  - Schedules (existing, kept distinct — a Schedule is a recipe that produces Runs, not a Run itself)
  - Triggers (Webhooks — existing, possibly unified UI later)
  - Workflows (existing)
- **Knowledge**, **Agents**, **Settings** (existing)

**Naming — Task → Run (UI label only):** the `Task` model, `tasks` table, `/tasks` URL routes, and agent SDK contracts stay unchanged. Only UI labels change to "Run/Runs": sidebar entry, page titles, breadcrumbs, table headers. The **global Runs page under Automations** continues to show **all** tasks (regardless of `issue_id`) so the existing operational view is fully preserved. The **Runs tab inside an Issue detail** is a new filtered view showing only tasks linked to that issue (`issue_id = <this issue>`). This is a behavior **addition** (new scoped view inside the issue detail), not a change to the existing global task board.

**Issue list view** — table; filters: status (multi), type, assignee, has-open-approval. Default sort: updated_at desc. Quick actions: assign, change state.

**Issue detail view** — header (title, state pill, type, assignee, created-by). Tabs:
- **Overview** — description, metadata, dependency graph (simple list V1), linked Channel, open ApprovalRequests rendered as cards.
- **Runs** — list of linked Tasks (formerly the primary view of work). Click → existing Task detail.
- **Discussion** — Thread messages; reuse existing Thread UI components.
- **Dependencies** — blocks / blocked-by list, add/remove.

**Create issue** — modal: title, description, type, assignee, optional linked Channel.

**Board view** (kanban by status) — deferred to V2.

## 9. API surface

All endpoints under `/api/v1/hives/{hive}/issues`, following the conventions of `app/Http/Controllers/Api/TaskController.php`. Uses the same auth middleware, error format, and ULID route binding.

| Method | Path | Purpose |
|---|---|---|
| GET    | `/` | List (filters: state, type, assignee, q) |
| POST   | `/` | Create |
| GET    | `/{issue}` | Show (eager-loads type, thread, recent tasks, open approvals) |
| PATCH  | `/{issue}` | Update (assignee, title, description, metadata) |
| POST   | `/{issue}/transition` | Generic state transition `{to: "blocked", reason?: "..."}` |
| POST   | `/{issue}/close` | Convenience: transition to done (runs trust resolution) |
| POST   | `/{issue}/reopen` | **Dashboard-only** (human-only per §5; not exposed on agent API) |
| POST   | `/{issue}/link-task` | Set `tasks.issue_id` on target Task; **rejects with 422 if `task.hive_id ≠ issue.hive_id`** (canonical FK, not `issue_links`) |
| POST   | `/{issue}/link-channel` | Set or replace linked Channel |
| POST   | `/{issue}/request-approval` | Blocked-on-human flow (creates ApprovalRequest, transitions to blocked) |
| POST   | `/{issue}/dependencies` | Add dependency |
| DELETE | `/{issue}/dependencies/{dep}` | Remove dependency |
| GET    | `/issue-types` | List types for hive |
| POST   | `/issue-types` | Create type (admin) |
| PATCH  | `/issue-types/{type}` | Update type (admin) |

**Cross-hive task linking:** Tasks support cross-hive dispatch (`Task.$allowCrossHiveAssignment`, `source_hive_id`), but Issues are strictly hive-scoped. `POST /{issue}/link-task` validates that the target task's `hive_id` matches the issue's `hive_id` and returns 422 if they differ. This prevents a hive-scoped Issue from owning a Task executing in another hive, which would break hive-level permission boundaries for the Issue's Runs tab and approval flow. Cross-hive task linking is deferred alongside cross-hive issues (§11).

**Approval scoping note:** The `approval_requests` table already carries a `hive_id` column (added in its original migration, included in the model's `$fillable`), and the **dashboard** controller (`ApprovalController` under `Dashboard/`) already scopes every operation — index, approve, deny — by `hive_id`. The **API** controller (`Api/ApprovalController`), however, currently authorizes on `organization_id` only, creating an inconsistency: the dashboard enforces hive isolation while the API does not.

Phase 1 closes this gap by introducing **hive-scoped approval routes** alongside the existing org-scoped routes:

**New routes (hive-scoped):**

| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/hives/{hive}/approvals` | List approvals scoped to hive (replaces `?hive_id=` query param approach) |
| GET    | `/api/v1/hives/{hive}/approvals/{approval}` | Show single approval; validates `approval.hive_id` matches `{hive}` |
| POST   | `/api/v1/hives/{hive}/approvals/{approval}/approve` | Approve; validates `approval.hive_id` matches `{hive}` |
| POST   | `/api/v1/hives/{hive}/approvals/{approval}/deny` | Deny; validates `approval.hive_id` matches `{hive}` |

**Contract details:**
- All four hive-scoped endpoints enforce `approval_request.hive_id = {hive}` and return 404 if the approval does not belong to the hive. This matches the dashboard controller behavior.
- The existing org-scoped routes (`/api/v1/approvals/*`) remain unchanged for backward compatibility. `index()` gains an **optional `hive_id` query parameter** for callers that prefer the flat route.
- Cross-hive-capable agents **must** use the hive-scoped routes when acting on Issue-linked approvals, since Issues are strictly hive-scoped. The `{hive}` path segment makes hive context unambiguous — no query parameter or body field required.
- The Issue detail view and the sidebar "Approvals" section under **Work** use the hive-scoped routes exclusively.
- ApprovalRequest polymorphic dispatch (`approvable_type=Issue`) works on approve/reject without new endpoints.

## 10. Migration / rollout

- V1 is **additive only**. New tables: `issues`, `issue_types`, `issue_dependencies`, `issue_links`. One new column: `tasks.issue_id` (nullable).
- Minor change to existing code: `ApprovalController::index()` gains an optional `hive_id` filter parameter (backward-compatible — existing callers unaffected).
- Seeded default IssueTypes per hive: `task` (agent_self_close), `bug` (human_required), `release` (gated_by_approval). Configurable post-seed.
- Optional backfill (V2+): convert Channels of type=planning into Issues, preserving messages via existing Thread.
- Feature flag: `features.issues_enabled` (per hive). When off, sidebar still shows old layout; API endpoints 404.
- Rollback: drop new tables + `tasks.issue_id` column. No data loss for existing flows since Tasks/Channels/Approvals are unchanged.

## 11. Out of scope (V1)

- Human-readable IDs (`BLA-6`) — deferred until per-hive vs per-project namespacing is decided.
- Cross-hive issues / linking (includes cross-hive task-to-issue linking — see §9 cross-hive task linking note).
- SLA, due dates, time tracking.
- Custom fields per IssueType.
- GitHub / Linear / Jira issue linking.
- Board (kanban) view.
- Saved filters, bulk actions, full-text search.
- Notifications beyond what existing ApprovalRequest already triggers.

## 12. Risks

- **UX confusion between Issues / Channels / Tasks.** Three things that all look like "work." *Mitigation:* single primary nav ("Issues" under Work) for everything the manager tracks; in-product decision tree in empty states ("Need to plan something? → Issue. Need to chat with the team? → Channel. Need to run automation? → Build › Automations."); Tasks demoted to "Runs" tab inside issues.
- **Trust-model bugs causing silent bad auto-closes.** Wrong policy resolution would let agents close work they shouldn't. *Mitigation:* every auto-close emits `issue.closed.auto` audit event with full rule path; reopen counter per agent surfaces drift; conservative defaults (new IssueTypes default to `human_required`; threshold = 60); admin-visible "recently auto-closed" feed.
- **Duplication with Channels.** Tempting to recreate chat inside Issues. *Mitigation:* Issues link a Channel rather than re-implementing — message composition uses the existing Channel UI when a Channel is linked, falls back to plain Thread otherwise.
- **Scope creep into a full project tracker.** *Mitigation:* explicit out-of-scope list above; V1 has no due dates, custom fields, or board view.
- **State-machine churn.** Adding more states (e.g. `triage`) later is cheap; removing is hard. *Mitigation:* start with 6 states, no triage state in V1.

## 13. Implementation plan — phased

### Phase 1 — Data model + REST API + Task.issue_id (no UI)
**Deliverables:** migrations, Eloquent models, controllers, policies, feature tests covering all endpoints + state transitions.
**Key files / migrations:**
- `database/migrations/*_create_issue_types_table.php`
- `database/migrations/*_create_issues_table.php`
- `database/migrations/*_create_issue_dependencies_table.php`
- `database/migrations/*_create_issue_links_table.php`
- `database/migrations/*_add_issue_id_to_tasks_table.php`
- `app/Models/Issue.php`, `IssueType.php`, `IssueDependency.php`, `IssueLink.php`
- `app/Http/Controllers/Api/IssueController.php`, `IssueTypeController.php`, `IssueTransitionController.php`
- `app/Policies/IssuePolicy.php`
- `routes/api.php` (new resource group under `/api/v1/hives/{hive}/issues`)
- Update `app/Models/Task.php` line 62 `$fillable` to include `issue_id`; add `issue()` relation.
- Update `app/Http/Controllers/Api/ApprovalController.php` — add optional `hive_id` filter to `index()` (backward-compatible); add `hive_id` validation to `show()`, `approve()`, and `deny()` for the hive-scoped routes.
- `routes/api.php` — register hive-scoped approval routes under `/api/v1/hives/{hive}/approvals` (index, show, approve, deny) pointing to `ApprovalController` with hive context.

**Acceptance:** all REST endpoints green; can create issue, link task (via `tasks.issue_id` FK), transition through full state machine via API; ApprovalRequest polymorphic dispatch works for `approvable_type=Issue`; approval list filterable by `hive_id`; hive-scoped approval routes (`show`, `approve`, `deny` under `/hives/{hive}/approvals/`) enforce `hive_id` match and return 404 for cross-hive access.
**Size:** L.

### Phase 2 — Manager UI (list, detail, create, sidebar)
**Deliverables:** Inertia pages + React components for Issue list, detail (Overview, Runs, Discussion, Dependencies tabs), create modal. Sidebar nav restructured: Work / Discuss / Automations; rename `Build` group → `Automations`, rename `Tasks` UI label → `Runs` (UI-only, model unchanged), keep Schedules / Triggers / Workflows distinct under Automations.
**Key files:** `resources/js/Pages/Issues/Index.tsx`, `Show.tsx`, `Create.tsx`; components under `resources/js/Components/Issues/`; sidebar component update.
**Acceptance:** manager can create, view, assign, transition issues end-to-end through UI; Runs tab links to existing Task detail.
**Size:** L.

### Phase 3 — Blocked-on-human flow (approval card + auto-resume)
**Deliverables:** `request-approval` endpoint, structured payload schema, Paperclip-style approval card component, auto-resume wiring (state transition + optional resume Task enqueue).
**Key files:** `app/Http/Controllers/Api/IssueController.php` (request-approval action), extend `ApprovalController.php` for Issue dispatch, `resources/js/Components/Issues/BlockedCard.tsx`, `app/Listeners/ResumeBlockedIssue.php`.
**Acceptance:** agent SDK can call request-approval; UI shows card; approve → issue transitions back to in_progress and (if configured) enqueues resume Task; reject without `cancel_issue` → reason recorded, issue stays blocked; reject with `cancel_issue: true` → issue transitions `blocked → cancelled` with reason.
**Size:** M.

### Phase 4 — Trust + auto-close (IssueType policies, agent trust, audit)
**Deliverables:** closure_policy enforcement in `close` endpoint, `agents.issue_trust_score` column + migration, trust decay job, audit events on every auto-close, admin "recently auto-closed" view.
**Key files:** `database/migrations/*_add_issue_trust_score_to_agents.php`, `app/Services/IssueClosureResolver.php`, `app/Jobs/DecayAgentIssueTrust.php`, `app/Events/IssueClosedAuto.php`, `app/Listeners/LogIssueAutoClose.php`.
**Acceptance:** all three closure policies enforced; resolver returns documented matrix outputs; reopens decay trust; audit event present for every auto-close with rule path.
**Size:** M.

### Phase 5 — Polish (board view, bulk actions, search, optional Channel backfill)
**Deliverables:** kanban board view by state; bulk transition / assign; basic full-text search across title + description; optional CLI/job to backfill Issues from planning-type Channels.
**Key files:** `resources/js/Pages/Issues/Board.tsx`, search scope on `Issue` model, `app/Console/Commands/BackfillIssuesFromChannels.php`.
**Acceptance:** board view ships behind flag; backfill is opt-in per hive, dry-run capable, idempotent.
**Size:** M.
