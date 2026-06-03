# Claude Code Operational Workflow

> How Claude Code manages tasks, delegates to subagents, and keeps
> project state consistent.

## 1. Source-of-Truth Hierarchy

| Priority | Source | What It Decides |
|----------|--------|-----------------|
| 1 | **Merged PRs on `main`** | What code actually exists — the ultimate truth. |
| 2 | **`TASKS.md`** (repo root) | Authoritative task status index (done / pending). |
| 3 | **Task files** (`docs/tasks/TASK-NNN-*.md`) | Requirements, design, test plan for each task. |
| 4 | **`CLAUDE.md`** | Coding standards, architecture constraints, conventions. |

When sources conflict, higher-priority sources win. For example, if a PR
for TASK-010 is merged but TASKS.md still shows it as pending, the merged
PR is truth — TASKS.md must be updated to match.

## 2. Status Policy

TASKS.md uses **binary statuses only**:

| Symbol | Meaning |
|--------|---------|
| `✅` | **Done** — PR merged to `main`. |
| `⬜` | **Pending** — everything else (not started, in progress, blocked). |

Rationale: in-progress and blocked are transient states that become stale
quickly. A task is either shipped or it isn't. Finer-grained status lives
in the individual task file's `Status:` field and in open PRs/branches.

### Sync Rule

After every PR merge, update TASKS.md so every merged task shows `✅`
and every unmerged task shows `⬜`. No other statuses are allowed in
TASKS.md.

## 3. Determining Blocked vs. Unblocked

A pending task is **unblocked** when every task listed in its `Depends On`
column has status `✅` (i.e., its PR is merged to `main`).

A pending task is **blocked** when at least one dependency is still `⬜`.

### Example: TASK-009 (Knowledge Entries)

```
TASK-009 depends on: 005, 006
TASK-005 status: ✅ (merged)
TASK-006 status: ✅ (merged)
→ TASK-009 is UNBLOCKED and ready to work.
```

Downstream impact — tasks that depend on TASK-009:

```
TASK-020 (Knowledge store API)    — depends on 009 → blocked until 009 merges
TASK-021 (Knowledge TTL cleanup)  — depends on 009 → blocked until 009 merges
TASK-069 (Org-scoped knowledge) — depends on 009 → blocked until 009 merges
```

### Picking the Next Task

1. Filter TASKS.md for `⬜` tasks whose **all** dependencies are `✅`.
2. Prefer lower task numbers (earlier in the plan) unless the user directs
   otherwise.
3. If multiple tasks are unblocked at the same level, they can be worked
   in parallel on separate branches.

## 4. Subagent Roles

Claude Code delegates work through five specialised subagent roles.
Each role has a clear scope, entry condition, and exit criteria.

### 4.1 PM (Project Manager)

**Purpose:** Owns the task lifecycle — picks tasks, tracks status, ensures
the handoff sequence runs to completion.

| Aspect | Detail |
|--------|--------|
| Entry | User request or start of session |
| Responsibilities | Determine next unblocked task(s); read task file; assign to Architect; track handoffs; update TASKS.md after merge |
| Exit criteria | TASKS.md is up-to-date and matches merged PRs |
| Tools | TASKS.md, task files, `git log`, `gh pr list` |

### 4.2 Architect / Planner

**Purpose:** Designs the implementation approach before any code is written.

| Aspect | Detail |
|--------|--------|
| Entry | PM assigns an unblocked task |
| Responsibilities | Read task file requirements; explore codebase for existing patterns; produce an implementation plan with file list, key decisions, and migration SQL if needed |
| Exit criteria | Plan approved by user (via `ExitPlanMode`) |
| Tools | Glob, Grep, Read (read-only exploration) |

### 4.3 Developer

**Purpose:** Writes the code according to the approved plan.

| Aspect | Detail |
|--------|--------|
| Entry | User-approved plan from Architect |
| Responsibilities | Create branch; implement migrations, models, controllers, services, routes; follow CLAUDE.md coding standards; keep changes minimal and focused |
| Exit criteria | All code written, no known gaps vs. the plan |
| Tools | Edit, Write, Bash (artisan commands) |

### 4.4 Tester

**Purpose:** Writes and runs tests, verifies the implementation.

| Aspect | Detail |
|--------|--------|
| Entry | Developer signals implementation complete |
| Responsibilities | Write unit + feature tests per the task file's Test Plan; run `php artisan test`; ensure zero failures; check PSR-12 compliance |
| Exit criteria | All tests pass, validation checklist items satisfied |
| Tools | Write, Edit, Bash (`php artisan test`) |

### 4.5 Critic / Reviewer

**Purpose:** Reviews the full changeset for correctness, security, and
standards compliance before PR creation.

| Aspect | Detail |
|--------|--------|
| Entry | Tester confirms all tests pass |
| Responsibilities | Review diff against task requirements; check for security issues (OWASP top 10); verify activity logging on state changes; confirm API envelope format; flag anything missed |
| Exit criteria | No blocking issues found, or issues fixed and re-verified |
| Tools | Read, Grep, `git diff` (read-only review) |

## 5. Handoff Sequence

```
PM → Architect → [user approval] → Developer → Tester → Critic → PM
 │                                                              │
 └──────────── (update TASKS.md, open PR) ◄─────────────────────┘
```

1. **PM** identifies the next unblocked task and hands off to Architect.
2. **Architect** explores the codebase and presents a plan.
3. **User** approves (or iterates on) the plan.
4. **Developer** implements the approved plan on a feature branch.
5. **Tester** writes tests and runs the full suite.
6. **Critic** reviews the diff for correctness and standards.
7. **PM** commits, opens the PR, and updates TASKS.md after merge.

If any role finds a blocking issue, it loops back to the appropriate
earlier role (e.g., Critic → Developer for a code fix, then back to
Tester → Critic).

## 6. Definition of Done

A task is **done** when all of the following are true:

- [ ] Code implements all requirements from the task file
- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on relevant state changes
- [ ] API responses use `{ data, meta, errors }` envelope (if API task)
- [ ] Form Request validation on all inputs (if API task)
- [ ] Critic review passed with no blocking issues
- [ ] PR opened and merged to `main`
- [ ] TASKS.md updated: task status set to `✅`, PR link added

## 7. TASKS.md Sync Protocol

Run this check after every merge to `main`:

1. List all merged PRs: `gh pr list --state merged --base main`
2. For each merged PR linked to a TASK-NNN, ensure TASKS.md shows `✅`.
3. For each task without a merged PR, ensure TASKS.md shows `⬜`.
4. If any mismatch is found, create a sync commit on the current task branch
   (before opening the PR). If syncing between tasks (no active task branch),
   use the current working branch (typically `main` or a dedicated `docs/sync-tasks` branch).

## 8. Branch and PR Conventions

| Item | Convention |
|------|-----------|
| Feature branch | `task/NNN-feature-name` |
| Docs-only branch | `docs/description` |
| Fix branch | `fix/NNN-description` |
| PR title | Short, imperative: `feat: add knowledge entries model (TASK-009)` |
| PR body | Summary, test plan, link to task file |
| Commit style | Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:` |
