# Proposal: Hive Templates (composable hive setups)

**Status:** draft — design review
**Edition:** community + cloud (system templates are cloud-seeded but the apply engine ships in core)
**Authors:** platform team
**Related precedents:**
  - PR #495 — workflow templates (`workflow_templates`)
  - PR #553 / #575 — marketplace personas (`marketplace_personas`)
  - TASK-254 — admin hosted-agent presets (`hosted_agent_presets`)

---

## Part A — Why

Today a freshly-created hive is empty. The user has to create agents one by one, write personas, wire workflows, register webhooks, attach service connections, seed knowledge — and only then can they trigger their first task. The result is **empty-hive paralysis** and a multi-hour time-to-value. Hive Templates collapse that into one click: pick "Engineering Team", connect GitHub + Slack, and you have a coding agent, a reviewer, a PR-review workflow, a webhook route for `pull_request` events, and seed knowledge entries — all coherent and immediately runnable. This is the same product surface that made Notion and Airtable defensible (templates → network effect → marketplace). It is also our most concrete differentiator vs. Hyperagent and Mirage, neither of which ship composable workspace templates.

---

## Part B — Architecture audit

What we already have, and what's missing. Every column in column 3 cites a real precedent in the repo.

| Templatable entity | Existing template support | File / line precedent |
|---|---|---|
| **Workflows** | Yes — `workflow_templates` table; deep-copy fork via `WorkflowTemplateDashboardController::apply` | `database/migrations/2026_04_25_102246_create_workflow_templates_table.php`, `app/Http/Controllers/Dashboard/WorkflowTemplateDashboardController.php:100-187`, `database/seeders/WorkflowTemplateSeeder.php:20-218` |
| **Marketplace personas** | Yes — `marketplace_personas` table; install via `MarketplacePersonaService` | `database/migrations/2026_04_03_100000_create_marketplace_personas_table.php`, `app/Models/MarketplacePersona.php:60-94` (reserved `superpos-` prefix + slug aliases) |
| **Sub-agent definitions** | No template surface today; instances live per-hive | `database/migrations/2026_04_21_100000_create_sub_agent_definitions_table.php:18-71` |
| **Agents** | No template surface; created ad hoc through `/dashboard/agents` | `database/migrations/0001_01_01_000012_create_agents_table.php:14-39` |
| **Agent permissions** | No template surface; granted manually | same migration, `agent_permissions` block lines 41-53 |
| **Webhook routes** | No template surface | `database/migrations/2026_03_01_100000_create_webhook_routes_table.php:14-63` |
| **Task schedules** | No template surface | `database/migrations/2026_03_08_100000_create_task_schedules_table.php:12-89` |
| **Knowledge entries** | No template surface | `database/migrations/0001_01_01_000016_create_knowledge_entries_table.php:15-56` |
| **Service connections** | Created at apply-time from collected credentials via `CredentialVault` | `app/Services/CredentialVault.php:18-31`, `database/migrations/0001_01_01_000017_create_service_connections_table.php:14-35` |

**Pattern conclusion.** We already have **two distinct template idioms** in the codebase that we will unify:

1. **Static seed** (workflow templates, marketplace personas) — a separate immutable catalog table that callers fork into mutable rows. No FK from the forked row back to the template. `firstOrCreate` keyed on `slug` keeps re-seeding additive (see `MarketplacePersonaSeeder:47-64`).
2. **Registry-with-fallback** (hosted agent presets) — DB-backed catalog; a config fallback during bootstrap; cache invalidated via a model observer (`HostedAgentPresetRegistry:50-58`).

Hive Templates use **idiom 1** for the manifest catalog (templates are forked into hives, not linked) and borrow the slug-prefix convention from `marketplace_personas` (`superpos-` reserved for system templates).

**What's truly missing:** a single manifest format that bundles personas + sub-agent definitions + agents + permissions + workflows + webhook routes + schedules + knowledge into one apply operation, plus an apply engine that executes the bundle transactionally and an audit table that records every apply for future upgrade / uninstall flows.

---

## Part C — Manifest format

JSON, versioned by `schemaVersion`. Stored in `hive_templates.manifest` as `jsonb`. Validated on insert by a Form Request that owns the schema contract (same shape as `HostedAgentPreset::fromConfig()` validation in `app/Cloud/Models/HostedAgentPreset.php`).

### Schema

```jsonc
{
  "schemaVersion": 1,
  "metadata": {
    "name": "string, required",
    "slug": "string, required, kebab-case, reserved 'superpos-' prefix for system templates",
    "version": "semver, required",
    "author": "string, optional",
    "description": "string, required",
    "category": "engineering | marketing | operations | research | support | custom",
    "tags": ["string"],
    "icon_url": "url, optional",
    "screenshots": ["url"]
  },
  "requires": {
    "platform": ["cloud-only" | "hosted-agents" | "pgvector"],
    "service_types": ["github", "slack", "linear", ...],
    "min_schema_version": 1
  },
  "credentials": [
    {
      "id": "github_main",
      "type": "github",
      "role": "main",
      "label": "GitHub account",
      "help": "We use this to read PRs and post review comments.",
      "scope": "hive",
      "required": true
    }
  ],
  "personas": [
    { "id": "coding", "from_marketplace": "superpos-coding-engineer" },
    { "id": "reviewer", "from_marketplace": "superpos-code-reviewer" },
    {
      "id": "pm",
      "inline": {
        "name": "Product Manager",
        "slug": "pm-template",
        "description": "...",
        "documents": { "system_prompt": "..." },
        "config": {},
        "capabilities": ["plan", "summarize"],
        "category": "product"
      }
    }
  ],
  "sub_agent_definitions": [
    {
      "id": "code_reviewer",
      "slug": "code-reviewer",
      "name": "Code Reviewer",
      "description": "...",
      "model": "claude-sonnet-4",
      "documents": { "system_prompt": "..." },
      "config": {},
      "allowed_tools": ["read_file", "search_code"]
    }
  ],
  "agents": [
    {
      "id": "coder_agent",
      "name": "Coding Engineer",
      "type": "hosted",
      "capabilities": ["coding", "build"],
      "persona": { "ref": "coding" },
      "permissions": [
        "tasks:create",
        "tasks:claim",
        "services:*",
        "knowledge:read",
        "knowledge:write"
      ],
      "metadata": {}
    }
  ],
  "workflows": [
    {
      "slug": "pr-review",
      "name": "PR Review",
      "description": "...",
      "trigger_config": { "type": "webhook", "event_type": "pull_request.opened", "credential_ref": "github_main" },
      "steps": { /* same shape as workflow_templates.steps */ },
      "settings": {}
    }
  ],
  "webhook_routes": [
    {
      "name": "GitHub PR opened",
      "service": { "credential_ref": "github_main" },
      "event_type": "pull_request.opened",
      "field_filters": [],
      "action_type": "create_task",
      "action_config": { "task_type": "default", "prompt": "Review PR: {{event.pull_request.title}}" },
      "priority": 10
    }
  ],
  "schedules": [
    {
      "name": "Daily standup digest",
      "trigger_type": "cron",
      "cron_expression": "0 9 * * 1-5",
      "task_type": "default",
      "task_payload": { "prompt": "..." },
      "task_target_capability": "summarize",
      "task_timeout_seconds": 1800,
      "overlap_policy": "skip"
    }
  ],
  "knowledge_entries": [
    {
      "key": "team.coding_conventions",
      "scope": "hive",
      "visibility": "public",
      "value": { "language": "php", "style": "PSR-12" }
    }
  ],
  "defaults": {
    "activate_workflows": false
  }
}
```

> **Note:** The manifest schema no longer contains a `conflict_strategy` default.
> v1 blocks apply on non-empty hives (Part J #1), so conflict resolution is not needed.

### Full worked example — "Engineering Team" template

```json
{
  "schemaVersion": 1,
  "metadata": {
    "name": "Engineering Team",
    "slug": "superpos-engineering-team",
    "version": "1.0.0",
    "author": "Superpos",
    "description": "A coding engineer plus a code-reviewer agent, wired to a PR-review workflow that fires on GitHub pull_request webhooks. Includes seed knowledge for repo conventions and a daily standup-digest schedule.",
    "category": "engineering",
    "tags": ["github", "code-review", "ci"],
    "icon_url": "https://cdn.superpos.ai/templates/engineering-team.svg",
    "screenshots": [
      "https://cdn.superpos.ai/templates/engineering-team/01-overview.png",
      "https://cdn.superpos.ai/templates/engineering-team/02-pr-review.png"
    ]
  },
  "requires": {
    "platform": ["hosted-agents"],
    "service_types": ["github", "slack"],
    "min_schema_version": 1
  },
  "credentials": [
    {
      "id": "github_main",
      "type": "github",
      "role": "main",
      "label": "GitHub account",
      "help": "Used to read pull requests and post review comments. Scope: repo, read:org.",
      "scope": "hive",
      "required": true
    },
    {
      "id": "slack_notify",
      "type": "slack",
      "role": "notify",
      "label": "Slack workspace (optional)",
      "help": "Used for daily standup digests. Skip if you only want PR review.",
      "scope": "hive",
      "required": false
    }
  ],
  "personas": [
    { "id": "coding", "from_marketplace": "superpos-coding-engineer" },
    { "id": "reviewer", "from_marketplace": "superpos-code-reviewer" },
    { "id": "qa_eval", "from_marketplace": "superpos-tester" }
  ],
  "sub_agent_definitions": [
    {
      "id": "code_reviewer",
      "slug": "code-reviewer",
      "name": "Code Reviewer",
      "description": "Reviews a diff and emits per-file inline comments classified by severity.",
      "model": "claude-sonnet-4",
      "documents": {
        "system_prompt": "You are a senior code reviewer. Walk the diff, classify each finding by severity (Bug, Security, Performance, Style, Suggestion), and return strict JSON."
      },
      "config": {},
      "allowed_tools": ["read_file", "search_code", "git_blame"]
    },
    {
      "id": "qa_evaluator",
      "slug": "qa-evaluator",
      "name": "QA Evaluator",
      "description": "Scores a work product on a 0-10 rubric and decides approve/reject.",
      "model": "claude-sonnet-4",
      "documents": {
        "system_prompt": "You are a QA evaluator. Score the work product 0-10 on correctness, completeness, and safety. Return strict JSON: {score, approved, feedback}."
      },
      "config": {},
      "allowed_tools": []
    }
  ],
  "agents": [
    {
      "id": "coder_agent",
      "name": "Coding Engineer",
      "type": "hosted",
      "capabilities": ["coding", "build", "planning"],
      "persona": { "ref": "coding" },
      "permissions": [
        "tasks:create",
        "tasks:claim",
        "tasks:update",
        "services:read",
        "services:*",
        "knowledge:read",
        "knowledge:write"
      ],
      "metadata": { "preset_key": "claude-sdk" }
    },
    {
      "id": "reviewer_agent",
      "name": "Code Reviewer",
      "type": "hosted",
      "capabilities": ["review-code", "evaluate"],
      "persona": { "ref": "reviewer" },
      "permissions": [
        "tasks:create",
        "tasks:claim",
        "tasks:update",
        "services:read",
        "services:*",
        "knowledge:read"
      ],
      "metadata": { "preset_key": "claude-sdk" }
    }
  ],
  "workflows": [
    {
      "slug": "pr-review",
      "name": "PR Review",
      "description": "Review a pull request diff and emit per-file comments, then run a final QA-evaluator pass to approve or reject.",
      "trigger_config": { "type": "webhook", "event_type": "pull_request.opened", "credential_ref": "github_main" },
      "settings": {},
      "steps": {
        "review": {
          "type": "agent",
          "name": "Review diff",
          "target_capability": "review-code",
          "sub_agent_definition_slug": "code-reviewer",
          "prompt": "Walk the diff below and produce inline comments classified by severity (Bug, Security, Performance, Style, Suggestion). Return JSON: {comments: [{file, line, severity, body}], summary: string}.\n\nDiff:\n{{trigger.input}}",
          "next": "approve_or_reject"
        },
        "approve_or_reject": {
          "type": "agent",
          "name": "Approve or reject",
          "target_capability": "evaluate",
          "sub_agent_definition_slug": "qa-evaluator",
          "prompt": "Score the review below on a 0-10 rubric. Return strict JSON {score, approved, feedback}.\n\nReview:\n{{steps.review.result}}"
        }
      }
    },
    {
      "slug": "plan-build-qa",
      "name": "Plan -> Build -> QA",
      "description": "Three-stage delivery loop with QA-evaluator feedback.",
      "trigger_config": {},
      "settings": {},
      "steps": {
        "plan": {
          "type": "agent",
          "name": "Plan",
          "target_capability": "planning",
          "prompt": "Read the user request below and produce a concise implementation plan.\n\nRequest:\n{{trigger.input}}",
          "next": "build_with_qa"
        },
        "build_with_qa": {
          "type": "loop",
          "name": "Build with QA loop",
          "generator_capability": "coding",
          "generator_prompt": "Implement the plan below. If feedback from the previous iteration is provided, incorporate it.\n\nPlan:\n{{steps.plan.result}}\n\nFeedback:\n{{loop.feedback}}",
          "evaluator_capability": "evaluate",
          "evaluator_sub_agent_definition_slug": "qa-evaluator",
          "evaluator_prompt": "Evaluate the work product against the plan. Score 0-10 and return JSON {score, approved, feedback}.\n\nPlan:\n{{steps.plan.result}}\n\nWork product:\n{{loop.generator_output}}",
          "max_iterations": 3,
          "exit_condition": "approved"
        }
      }
    }
  ],
  "webhook_routes": [
    {
      "name": "GitHub PR opened",
      "service": { "credential_ref": "github_main" },
      "event_type": "pull_request.opened",
      "field_filters": [],
      "action_type": "create_task",
      "action_config": { "task_type": "default", "prompt": "PR opened: {{event.pull_request.title}}" },
      "priority": 10
    },
    {
      "name": "GitHub PR ready_for_review",
      "service": { "credential_ref": "github_main" },
      "event_type": "pull_request.ready_for_review",
      "field_filters": [],
      "action_type": "create_task",
      "action_config": { "task_type": "default", "prompt": "PR ready for review: {{event.pull_request.title}}" },
      "priority": 10
    }
  ],
  "schedules": [
    {
      "name": "Daily standup digest",
      "description": "Summarize yesterday's merged PRs and post to Slack each weekday at 09:00.",
      "trigger_type": "cron",
      "cron_expression": "0 9 * * 1-5",
      "task_type": "default",
      "task_payload": { "prompt": "Summarize all PRs merged in the last 24h. Post to #engineering." },
      "task_target_capability": "summarize",
      "task_timeout_seconds": 1800,
      "overlap_policy": "skip"
    }
  ],
  "knowledge_entries": [
    {
      "key": "team.coding_conventions",
      "scope": "hive",
      "visibility": "public",
      "value": {
        "languages": ["php", "javascript"],
        "style": "PSR-12 for PHP; eslint --fix for JS",
        "test_framework": "phpunit, vitest"
      }
    },
    {
      "key": "team.review_checklist",
      "scope": "hive",
      "visibility": "public",
      "value": {
        "must_check": ["sql injection", "n+1 queries", "test coverage", "activity log entries"]
      }
    }
  ],
  "defaults": {
    "activate_workflows": false
  }
}
```

This is the canonical reference example. Marketing-Team and Operations-Coordination templates follow the same shape; the seeder ships three out of the box.

---

## Part D — Apply engine

`HiveTemplateApplyService::apply(HiveTemplate $template, Hive $target, ApplyContext $ctx): TemplateApplication`

### 1. Pre-flight validation

- Validate manifest against the v1 JSON schema (Form Request handles structural validity at upload time; the apply path re-validates the snapshot in case of a stored bad row).
- Check `requires.platform` against the running edition (e.g. `hosted-agents` requires cloud edition — `config('platform.is_cloud')`, see `config/platform.php:23`).
- Check `requires.service_types` against the platform connector registry.
- Verify the user is the tenant owner or org admin (existing `CloudTenant::roleFor()` check — see Part J, decision 7). No dedicated `template:apply` permission in v1.
- Verify every `required: true` credential has been supplied in the `ApplyContext.credentials` map.

If any check fails, abort with a structured error — no partial state.

### 2. Empty-hive gate

**v1 does not implement conflict detection or resolution.** Instead, the eligibility checker (`HiveTemplateEligibility`) rejects any hive that already contains agents, sub-agent definitions, workflows, webhook routes, schedules, or knowledge entries (see `app/Cloud/Services/HiveTemplateEligibility.php:46-58`). The user must create a new empty hive to apply a template.

This decision (locked in Part J #1) eliminates the need for skip/rename/replace/abort strategies and keeps the apply engine straightforward. Conflict resolution may be revisited in v2 if customer feedback warrants applying templates to existing hives.

### 3. Transaction boundary

The entire apply runs in a single `DB::transaction(function () { ... })` block. Mirror the pattern from `WorkflowTemplateDashboardController::apply` lines 144-167. Any exception rolls back every row that was created in this apply. The encrypted credentials, however, are committed **before** the transaction opens (see step 4 step c) because they are durable artifacts the user might want to keep even if the apply fails — they only need to be entered once.

### 4. Order of operations

Strictly ordered so foreign keys are always satisfied:

1. **Personas** —
   - For each `from_marketplace` entry, look up the persona in `marketplace_personas` by slug. If missing, error.
   - For each `inline` entry, create a `marketplace_personas` row (visibility `private`, scoped to the target hive's organization). Prefix the slug with the organization's slug to guarantee global uniqueness (`{org_slug}-{persona_slug}`). Use `firstOrCreate` on the prefixed slug to be additive.
   - Record `{template_local_id => marketplace_persona_id}` map.
2. **Sub-agent definitions** — Insert rows in `sub_agent_definitions`. The `created_by_type` is `human`, `created_by_id` is the applying user.
3. **Service connections** — For each declared credential the user supplied, call `CredentialVault::encryptArray($auth_config)` (`app/Services/CredentialVault.php:36-39`) and insert a `service_connections` row. Names are scoped per organization (see unique index in `create_service_connections_table.php:32`).
4. **Agents** — Insert `agents` rows, referencing personas through the local-id map. Capabilities + metadata are copied verbatim.
5. **Agent permissions** — For each agent, insert rows in `agent_permissions` (composite PK `(agent_id, permission)` per `0001_01_01_000012_create_agents_table.php:47`).
6. **Workflows** — Deep-copy steps and trigger_config (use `WorkflowTemplateDashboardController::deepCopyArray` lines 236-239 as the reference helper, or extract it to a shared trait). Replace `sub_agent_definition_slug` references with slugs that now exist in the hive (the apply just created them so this is a no-op for templated slugs, but the safety check is the same as `stripUnresolvedSubAgentSlugs`). If `trigger_config` contains a `credential_ref` key, resolve it to the `service_connections.id` created in step 3 and write the result as `trigger_config.service_connection_id`; remove the `credential_ref` key from the stored config. This binding is required for `WebhookTriggerService` to match incoming webhooks to the workflow (see `app/Services/WebhookTriggerService.php:64-75`). If the `credential_ref` cannot be resolved (e.g. the user skipped that credential), error. Call `snapshotVersion()` to seed v1.
7. **Webhook routes** — Resolve each route's `credential_ref` to the `service_connections.id` created in step 3. Insert with the correct `action_type` and `action_config`.
8. **Schedules** — Insert into `task_schedules` with `next_run_at` precomputed from the cron expression (or `run_at` for `once` triggers). `status = 'active'` unless the manifest specifies otherwise.
9. **Knowledge entries** — Insert into `knowledge_entries`. For `value` blobs we copy as-is (jsonb).

### 5. Activity log

Inside the transaction, append **one** `activity_log` entry with action `hive_template.applied`:

```json
{
  "hive_template_id": "01HABC...",
  "template_slug": "superpos-engineering-team",
  "template_version": "1.0.0",
  "application_id": "01HABD...",
  "entities_created": {
    "personas": 0,
    "marketplace_personas_referenced": 3,
    "sub_agent_definitions": 2,
    "service_connections": 2,
    "agents": 2,
    "agent_permissions": 14,
    "workflows": 2,
    "webhook_routes": 2,
    "schedules": 1,
    "knowledge_entries": 2
  }
}
```

`ActivityLogger` is the same writer used by `WorkflowTemplateDashboardController::logActivity` (line 178); use it directly.

### 6. Idempotency

Each apply produces a `template_applications` row that snapshots the manifest. Re-applying the **same template version to the same hive** must be detected and short-circuited with a warning ("This template is already applied; choose another action or upgrade"). Re-applying a **newer version** is the v2 upgrade path (Part H).

### 7. Rollback / uninstall

Every row created by the apply carries `applied_from_template_application_id` (nullable FK to `template_applications.id`) — see Part E. v1 surfaces a read-only list of "entities created by this template" in the application detail view; bulk delete is a v2 follow-up.

**Decision locked (Part J #4):** yes — the `applied_from_template_application_id` FK column has been added to all 8 entity tables in PR 1. Retrofitting later would require a backfill that is impossible to reconstruct correctly.

---

## Part E — Schema

### `hive_templates` (catalog)

| Column | Type | Notes |
|---|---|---|
| `id` | `ulid` PK | `Str::ulid()` |
| `slug` | `string(120)` unique | `superpos-` prefix reserved for system templates (model `saving` hook, same idiom as `MarketplacePersona:72-88`) |
| `name` | `string(255)` | |
| `description` | `text` nullable | |
| `schema_version` | `unsignedInteger` | manifest schema version (`1`) |
| `manifest` | `jsonb` | full manifest body |
| `visibility` | `string(20)` | `system` \| `private` \| `public` (mirrors `marketplace_personas.visibility`) |
| `organization_id` | `ulid` nullable | null for system templates |
| `category` | `string(50)` nullable | |
| `tags` | `jsonb` | `[]` default |
| `icon_url` | `string(500)` nullable | |
| `screenshots` | `jsonb` | `[]` default |
| `version` | `string(20)` | semver |
| `is_seeded` | `boolean` | true for `superpos-` rows |
| `is_featured` | `boolean` indexed | same as `workflow_templates.is_featured` |
| `created_by_user_id` | `foreignId` nullable FK | null on seeded rows; uses Laravel `foreignId` (bigint) constrained to `users` with `nullOnDelete` |
| `created_at`, `updated_at` | timestamps | |

Indexes: `(visibility, organization_id)`, `is_featured`.

### `template_applications` (audit log)

| Column | Type | Notes |
|---|---|---|
| `id` | `ulid` PK | |
| `hive_id` | `ulid` FK `hives.id` cascadeOnDelete | |
| `organization_id` | `ulid` FK | denormalized for tenant scoping |
| `hive_template_id` | `ulid` FK `hive_templates.id` nullOnDelete | nullable so a deleted catalog row doesn't break audit history |
| `template_slug` | `string(120)` | denormalized for human-readable audit |
| `template_version` | `string(20)` | denormalized — the version at apply time |
| `manifest_snapshot` | `jsonb` | full manifest body at apply time (immutable) |
| `applied_by_user_id` | `foreignId` nullable FK `users.id` nullOnDelete | |
| `entities_created` | `jsonb` | counts + IDs by entity type; default `{}` |
| `conflict_strategies` | `jsonb` | `{[entityRef]: strategy}`; default `{}` (unused in v1 — hives must be empty) |
| `credentials_used` | `jsonb` | type + role only (never plaintext); default `[]` |
| `applied_at` | `timestamp` | |
| `created_at`, `updated_at` | timestamps | Laravel timestamps |

Indexes: `(hive_id, applied_at)`, `(hive_template_id, applied_at)`, `organization_id`.

### Per-entity foreign keys

Add a **nullable** `applied_from_template_application_id` column (ulid, FK `template_applications.id` `nullOnDelete`) to every entity table that templates touch:

- `agents`
- `agent_permissions` (via the agent — no direct column needed)
- `sub_agent_definitions`
- `workflows`
- `webhook_routes`
- `task_schedules`
- `knowledge_entries`
- `service_connections`
- `marketplace_personas` (only for **inline** personas created by an apply; references stay untagged)

Decided: columns added in PR 1 alongside the catalog and audit tables. See Part J #4.

---

## Part F — Wizard UX

Five steps. Inertia + React, same patterns as `WorkflowBuilder`'s `TemplatePickerModal` (`resources/js/Pages/WorkflowBuilder.jsx:2271+`). (v1 has no conflict-resolution step because templates can only be applied to empty hives — see Part J #1.)

### 1. Browse

Route: `/dashboard/hive-templates`. Grid view of cards. Each card: icon, name, category, short description, "X agents · Y workflows · Z webhooks" stat row, "Featured" badge. Filter sidebar: category, tags, visibility (system / your org / public). Search by name.

### 2. Preview

Route: `/dashboard/hive-templates/{slug}`. Full screenshot carousel + a "What will be created" accordion that lists every entity:

```
PERSONAS (3)
  Coding Engineer (from marketplace)
  Code Reviewer (from marketplace)
  Tester (from marketplace)

SUB-AGENT DEFINITIONS (2)
  code-reviewer
  qa-evaluator

AGENTS (2)
  Coding Engineer  - hosted preset claude-sdk - 7 permissions
  Code Reviewer    - hosted preset claude-sdk - 6 permissions

WORKFLOWS (2)
  pr-review     - webhook trigger pull_request.opened
  plan-build-qa - manual trigger

WEBHOOK ROUTES (2) ...
SCHEDULES (1) ...
KNOWLEDGE ENTRIES (2) ...
```

Primary CTA: **Apply to this hive** (current hive resolved from `platform.current_hive_id`, same as `WorkflowTemplateDashboardController::resolveCurrentHiveId` lines 251-281).

### 3. Configure credentials

A form, one section per declared credential. Each section:

- Header with `label` + `help` text from the manifest.
- Radio: "Use existing service connection" (dropdown of all `service_connections` rows matching `type` for this organization) **OR** "Create new" (renders the standard `ServiceConnectionForm` inline).
- Inline validation (Form Request on submit).
- Optional credentials show a "Skip" toggle.

### 4. Confirm + apply

A summary screen ("You are about to create 2 agents, 2 workflows, 2 webhook routes...") with a final **Apply** button. On submit the request opens a streaming progress endpoint (Server-Sent Events on the same connection Laravel Reverb already serves). The frontend renders a checklist:

```
✓ Personas (3 referenced, 0 created)
✓ Sub-agent definitions (2)
✓ Service connections (2)
✓ Agents (2)
  Permissions (14)
… Workflows (1/2)
  Webhook routes (-)
  Schedules (-)
  Knowledge entries (-)
```

### 5. Success

Redirect to `/dashboard/hive-templates/applications/{id}` with a 200ms success animation. Links to each created agent and workflow. A "Trigger your first task" CTA opens the task-create modal pre-filled with the first workflow's trigger shape.

---

## Part G — Authorship and visibility

Three visibility classes, mirroring `marketplace_personas.visibility`:

- **System** (`visibility = 'system'`) — seeded by `HiveTemplateSeeder`. Slug prefixed `superpos-`. Reserved-prefix enforcement in the model's `saving` hook (same defense-in-depth as `MarketplacePersona::booted()` lines 62-88). `organization_id` is null.
- **Org-private** (`visibility = 'private'`) — created via an admin action **"Export this hive as a template"**. The exporter walks the hive's entities and emits a manifest (essentially the inverse of the apply engine). Visibility is scoped to the org via `BelongsToOrganization`. Useful for orgs that run many similar hives (e.g. one per customer).
- **Public** (`visibility = 'public'`) — opt-in published from an org-private row. Subject to **automated checks only (no manual review)** (see Part J #2 for the decision). Public templates show in the global marketplace alongside `superpos-` system templates but with a "Community" badge.

The `MarketplacePersona::scopeVisibleTo` pattern (`app/Models/MarketplacePersona.php:146-155`) gives us the query shape verbatim — copy it into `HiveTemplate::scopeVisibleTo`.

---

## Part H — Live link vs. static seed (the "no tradeoffs" decision)

User instruction: no tradeoffs. So:

- **Pure static seed (v1 ship)** — apply copies the template into the hive. Afterwards the entities are regular hive content; the template version stamped on each row is informational only.
- **Pure live link (v2+)** — risky: requires diffing user-edited entities against new template versions and choosing how to merge. We will not do this; users edit their workflows freely and a forced sync would clobber that work.
- **Hybrid (the production-grade path)** — applied entities carry both `applied_from_template_application_id` AND `template_version_at_apply`. Template **updates do not auto-apply**. Instead, the catalog page surfaces a banner: "A new version (1.1.0) of Engineering Team is available. View changes." Clicking opens a **diff preview** (added entities, removed entities, modified field-level changes per entity). The user opts in to an upgrade. The upgrade flow runs the apply engine again but with a diff-merge strategy: new entities are created, removed entities are flagged for manual deletion, modified entities are renamed `entity-v2` so the user can compare and migrate manually.

**Recommendation:** ship v1 as static seed with the version stamp **and** the per-row FK from Part E. That is the only mandatory v1 work to keep the upgrade path open. Upgrade UI is v2 after we see how customers actually use templates. This is what TASK-254 did with `hosted_agent_presets` (stamp the source, defer the upgrade UX).

---

## Part I — Incremental delivery plan

| # | Size | PR title | Scope |
|---|---|---|---|
| 1 | S | `feat: hive_templates schema + Eloquent model + manifest validator` | `hive_templates` + `template_applications` table migrations; 8 FK-stamping migrations adding `applied_from_template_application_id` to all entity tables; `HiveTemplate` + `TemplateApplication` models; manifest validator; eligibility checker; reserved-slug hook. No UI. |
| 2 | M | `feat: hive template apply engine` | `HiveTemplateApplyService` (the algorithm in Part D). Pre-flight validation, empty-hive gate, transactional apply, activity logging, snapshot. Unit + feature tests. No UI. No conflict resolution (v1 blocks non-empty hives). |
| 3 | S | `feat: hive template eligibility + plan-gate` | Plan-gate enforcement for template apply. Eligibility checker refinements from production feedback. The FK-stamping migrations originally planned for this PR landed in PR 1. |
| 4 | M | `feat: hive template wizard UI` | Inertia pages for browse / preview / configure-credentials / confirm + apply progress / success. No conflict-resolution step (v1 blocks non-empty hives). Reuses the `TemplatePickerModal` patterns. |
| 5 | S | `feat: seed system hive templates (engineering / marketing / operations)` | `HiveTemplateSeeder` with the three starter manifests; cloud one-shot migration to run it on every deploy (same idiom as `2026_05_07_120000_seed_starter_marketplace_personas.php`). |
| 6 | S | `feat: export hive as template` | "Export this hive" admin action that walks the hive and emits a manifest. Saves as `visibility = private` for the org. |
| 7 | M | `feat: public marketplace for hive templates` | Public listing UI, "Publish" workflow with automated checks (no manual review — decision locked in Part J #2). Out of v1 if scope is tight; can ship in v2. |

v1 ship = PRs 1-5 (one S + one M + one S + one M + one S = roughly 4 weeks at one engineer). PRs 6 and 7 follow once we have customer signal.

---

## Part J — Product decisions (locked)

These strategic decisions have been locked in PR 1. The chosen option is in **bold**.

1. **Conflict resolution** — v1 **blocks apply if the hive is non-empty**. No rename/skip/replace logic; the user must start from an empty hive. Simplifies the apply engine and avoids all conflict-resolution edge cases.
2. **Public-marketplace review** — **auto-listed with automated checks only** (no manual review queue). Takedown on report. Maximizes network effect.
3. **Who can apply a template** — **tenant owner or org admin**, using the existing `CloudTenant::roleFor()` check. No new permission introduced.
4. **v1 entity stamping** — **yes**. All 8 entity tables carry `applied_from_template_application_id` (FK to `template_applications`). Migrations shipped in PR 1.
5. **Credentials collection timing** — **wizard time**. Apply is blocked until all required credentials are supplied. Recorded as type+role only (never plaintext).
6. **Pricing gate** — **deferred**. No v1 gate. TODO comment in the eligibility checker for PR 3 to wire plan-based restrictions if needed.
7. **Permission model** — **reuse existing role check** (owner/admin). No new `template:apply` permission in v1. Revisit if granular delegation is requested.

---

## Appendix — files referenced

- `database/migrations/2026_04_25_102246_create_workflow_templates_table.php` — pattern for catalog table
- `database/migrations/2026_04_03_100000_create_marketplace_personas_table.php` — pattern for visibility / slug reservation
- `database/migrations/cloud/2026_04_30_120000_create_hosted_agent_presets_table.php` — pattern for registry-with-cache (not used directly here, but instructive)
- `database/seeders/WorkflowTemplateSeeder.php` — pattern for idempotent `updateOrCreate` seeding
- `database/seeders/MarketplacePersonaSeeder.php` lines 47-95 — pattern for additive `firstOrCreate` + reserved-prefix
- `database/migrations/cloud/2026_05_07_120000_seed_starter_marketplace_personas.php` — pattern for cloud one-shot seed migration on deploy
- `app/Http/Controllers/Dashboard/WorkflowTemplateDashboardController.php` lines 100-187 — pattern for transactional apply + activity log
- `app/Models/MarketplacePersona.php` lines 60-94, 146-155 — pattern for reserved-prefix + `scopeVisibleTo`
- `app/Services/CredentialVault.php` — credential encryption used at apply time
- `resources/js/Pages/WorkflowBuilder.jsx` lines 1819-2330 — pattern for template picker modal
- `database/migrations/0001_01_01_000012_create_agents_table.php` — agents + agent_permissions schema
- `database/migrations/2026_03_01_100000_create_webhook_routes_table.php` — webhook_routes schema
- `database/migrations/2026_03_08_100000_create_task_schedules_table.php` — task_schedules schema
- `database/migrations/2026_04_21_100000_create_sub_agent_definitions_table.php` — sub_agent_definitions schema
- `database/migrations/0001_01_01_000016_create_knowledge_entries_table.php` — knowledge_entries schema
