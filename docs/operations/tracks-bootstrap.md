# Tracks API bootstrap (Cloud / multi-tenant)

The Tracks layer ships with a `TracksBackfillSeeder` (`database/seeders/TracksBackfillSeeder.php`)
that backfills the two existing CE tracks (`k1` and `dw`) on a fresh CE deploy. It reads
`config('platform.ce.hive_id')`, resolves it to a single hard-coded hive, and bails out
otherwise — which means **it is a no-op on a Cloud / multi-tenant install** where the
hive list is provisioned by the tenant onboarding flow rather than a config key.

Cloud tenants should create the tracks through the public API instead. This runbook
covers the full set — `k1`, `dw`, **and** `reg` (the registry track, which the CE
seeder does not create) — so a Cloud hive ends up with all three.

## 1. Discover your hive slug

The Tracks API is scoped per hive (`/api/v1/hives/{hive}/tracks`), so the first step
is to find the slug of the hive you want to populate. Listing hives
(`GET /api/v1/hives`) requires the `hives.read` permission:

```bash
curl -sS https://app.example.com/api/v1/hives \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Accept: application/json"
```

The response envelope is `{ "data": [...], "meta": {...} }`. Each entry's `slug`
field is what you plug into the next step. There is also a `default` field —
`true` indicates the hive the dashboard boots into when a tenant signs in.

### Required permissions

The Tracks routes are gated on the **issue** permissions, not `hives.manage`
(`routes/api.php` — read endpoints sit under `issues.read`, mutations under
`issues.manage`, matching the issue lifecycle boundaries). The full bootstrap
flow therefore needs an agent token that carries **all** of:

- `hives.read` — to discover the hive slug via `GET /api/v1/hives` (step 1)
- `issues.manage` — to create/update tracks via `POST /api/v1/hives/{hive}/tracks`
  and `PATCH /api/v1/hives/{hive}/tracks/{slug}` (steps 2–3)
- `issues.read` — to list/verify tracks via `GET /api/v1/hives/{hive}/tracks` (step 5)

Make sure the token includes every one of these before you start — a token
scoped only to `hives.manage` will be rejected on the track mutations.

## 2. Create the three tracks

Issue three `POST` calls against the same hive. They can be run in any order;
each is independent.

Replace `$HIVE` with the slug from step 1, and `$AGENT_TOKEN` with an agent token
that has the `issues.manage` permission (see "Required permissions" above).

### k1 — Knowledge Wiki Redesign

The spec below uses the same **Status / Why / Proposal / Approach** skeleton
as the smoke-tested bodies in `TracksBackfillSeeder` (now updated to match).
The skeleton is what makes a track useful at a glance: status is the
one-line current state, why is the motivation, proposal links to the full
design doc, and approach lists the sequential phases. The **Linked
issues** list at the bottom of the show page is the live status source
once issues are linked — the spec is for context, not for status.

**The `## Proposal` line uses a `[[proposal-k1]]` wikilink**, not a GitHub
URL — wikilinks render in the dashboard and resolve to the typed
`proposal-k1` knowledge entry created in step 2.5. GitHub-hosted MD files
do not render in the dashboard, so the spec must reference the typed
proposal page directly.

```bash
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/tracks" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "slug": "k1",
    "name": "Knowledge Wiki Redesign",
    "description": "Karpathy-style typed-page knowledge wiki built on top of the existing knowledge_entries table. Replaces value-only entries with typed pages (type, slug, title, body, frontmatter, tags, source_ids).",
    "spec": "## Status\n\nActive. Phase A1 in progress (schema + indexes), A2 / A3 / A4 sequenced behind it.\n\n## Why\n\nPromote value-only `knowledge_entries` to typed wiki pages — one slug = one page, with real markdown body, frontmatter, tags, and wiki-style links between pages. The current value-only shape forces every consumer to know each entry'\''s schema and gives us no way to navigate between them.\n\n## Proposal\n\n[[proposal-k1]] — Knowledge Wiki Redesign — full design.\n\n## Approach\n\nFour sequential phases:\n\n1. **A1 — Schema:** typed columns + partial unique index on `(hive_id, slug)` where state = active + GIN trigram on title.\n2. **A2 — Dual-shape:** service writes both `value` and the typed columns in parallel; reads prefer typed.\n3. **A3 — Wiki links:** parser for inline slug references (the wiki-link syntax: an open bracket, a slug, a close bracket, with each side doubled) + a `KnowledgeLink` model to record link edges + a backlinks panel.\n4. **A4 — Dashboard:** Inertia pages for typed entries (Index, Show, Edit) + the slugMap.\n\nThe **Linked issues** list at the bottom of this page is the live status source — issue states flip as each phase lands.\n",
    "state": "active"
  }'
```

### dw — Dynamic Workflows

```bash
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/tracks" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "slug": "dw",
    "name": "Dynamic Workflows",
    "description": "Claude Code Dynamic Workflows as a first-class registry kind. Script-runtime-backed multi-step workflows with per-revision limits, checkpointing, and a per-kind payload validator.",
    "spec": "## Status\n\nActive. DW-1 in progress (kind discriminator + PayloadValidator + executor attachment). DW-2 and DW-3 are designed but unstarted.\n\n## Why\n\nPromote **dynamic workflows** to a first-class registry kind. Today every multi-step agent workflow re-implements its own dispatch, validation, and resume logic. A dedicated `dynamic_workflow` kind in `registry_items` lets the executor, the per-kind payload validator, and the per-revision limits be shared across all workflow authors.\n\n## Proposal\n\n[[proposal-dw]] — Dynamic Workflows — full design.\n\n## Approach\n\nThree beats:\n\n1. **DW-1 — Foundation:** add `registry_items.kind = '"'"'dynamic_workflow'"'"'` path, the per-kind `PayloadValidator` contract, the script-runtime executor attachment (loads `.claude/scripts/dynamic-workflow/`), draft state, and per-revision limits.\n2. **DW-2 — Orchestrator:** state machine for multi-step execution.\n3. **DW-3 — Resumability:** checkpoint + replay across runs.\n\nThe **Linked issues** list at the bottom of this page is the live status source.\n",
    "state": "active"
  }'
```

### reg — Registry skills + modules onboarding

```bash
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/tracks" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "slug": "reg",
    "name": "Registry skills + modules onboarding",
    "description": "Promote agent skills and modules to first-class registry kinds (alongside subagent and dynamic_workflow). Beats 1–4 from docs/proposals/registry-skills-modules.md; Beats 1 and 2a are shipped, 2b/3/4 are in flight.",
    "spec": "## Status\n\nActive. **Beats 1 and 2a are shipped** (PRs #798 and #799). Beats 2b, 3, and 4 are still in flight per the proposal.\n\n## Why\n\nPromote agent **skills** and **modules** to first-class registry kinds (alongside `subagent` and `dynamic_workflow`). Without a registry kind, these are read from baked-in fixtures on the agent image — no per-tenant versioning, no per-org customization, no audit trail of what an agent actually loaded.\n\n## Proposal\n\n[[proposal-reg]] — Registry: Subagents, Skills, Modules — full design.\n\n## Beats\n\n- **Beat 1** ✅ Import baked-in skill + module fixtures (PR #798).\n- **Beat 2a** ✅ Serve skill + module kinds via `/registry/resolved` (PR #799).\n- **Beat 2b** Lifecycle hooks: install-on-claim, uninstall-on-attach-remove, agent-side materializer (scripts + `claude.md` render).\n- **Beat 3** Dual-source flag flip: registry-primary serving with baked-in fallback for back-compat. Flip the default once CI fixture sync is in place.\n- **Beat 4** Drop the baked-in fallback on the agent image. **Irreversible** — gated on Beat 3 in prod + a coordinated agent-image release.\n\nBeats 1–3 are flag- or fixture-reversible. Beat 4 is the only irreversible step and the only one that needs a coordinated cross-repo release + bake period. See proposal §8 for the rollback matrix.\n",
    "state": "active"
  }'
```

## 2.5. Create the proposal knowledge entry (typed page)

The `## Proposal` line in each track spec above is a `[[proposal-<track-slug>]]`
wikilink that points at a typed `topic` knowledge entry in the same hive.
GitHub-hosted MD files do not render in the dashboard, so proposals must
be **first-class knowledge pages** rather than files in the repo. The
`[[wikilink]]` syntax resolves at render time in the wiki renderer
(`resources/js/Components/Knowledge/MarkdownBody.jsx`).

**Create the proposal entry first**, before running the spec `POST` calls
above — the spec body hard-codes the wikilink target, so a missing
`proposal-<track-slug>` entry means the link is a dead reference.

```bash
# Adjust path/title/summary/body-file/tags per track. The example is for k1.
superpos-knowledge create \
  --type topic \
  --slug proposal-k1 \
  --title "Knowledge Wiki Redesign" \
  --summary "Karpathy-style typed pages with wikilinks, value-only fallback during cutover." \
  --body-file docs/proposals/knowledge-wiki-redesign.md \
  --tags proposal,track:knowledge-wiki,architecture
```

The `superpos-knowledge` script accepts the typed `type`+`slug`+`body`
shape (do not pass the legacy `key`+`value` shape — the API rejects a
request that carries both). The validator runs the body through the
`FrontmatterSchema` for the chosen `type`; `topic` is the most permissive
type and accepts an empty `frontmatter` (its `lint_required` list is
empty). If you would rather call the REST API directly, the equivalent
shape is `POST /api/v1/hives/{hive}/knowledge` with the JSON body
`{ "type": "topic", "slug": "proposal-<track-slug>", "title": "...",
"summary": "...", "body": "<markdown>", "frontmatter": {}, "tags":
[...] }` and the `User-Agent: SuperposCodex/1.0` header (Cloudflare 1010
workaround).

If the proposal lives in the repo (as is the case for the three live
tracks), the body-file flag is the simplest path: read the proposal MD
verbatim into `body`. The `proposal-*` tag is what makes the entry
discoverable from the wiki index; the `track:<track-slug>` tag ties it
to the matching track for cross-reference.

## 3. File and link the placeholder issues

A track with a spec but no linked issues looks empty on the dashboard — the
progress column shows `0 / 0` and the issue list is blank. The five concrete
sub-tasks the specs reference (TASK-296..300) live as separate issues; file
them once, then link them to the right track.

Skip this section if you already have equivalent `TASK-XXX` issues in the
hive — in that case, jump to the link calls in step 3.2 below with the
existing issue IDs.

### 3.1 File the issues

First, discover the `task` issue type id (every hive has one):

```bash
curl -sS "https://app.example.com/api/v1/hives/$HIVE/issue-types" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Accept: application/json"
```

Pick the entry whose `key` is `task`; capture its `id` into `$TASK_TYPE_ID`.

**Search before you file — issue creation is _not_ idempotent.** The issues
endpoint has no title-uniqueness contract (`CreateIssueRequest` validates only
`required|string|max:255` on `title`, and the `issues` table has no unique index
on `(hive_id, title)`), so re-running the create calls below will produce
*duplicate* placeholder issues and publish duplicate `issue.created` events.
Before filing, search for each title and only create the ones that are missing:

```bash
# Case-insensitive substring search on title. Returns existing matches in `data`.
curl -sS "https://app.example.com/api/v1/hives/$HIVE/issues?q=TASK-296" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Accept: application/json"
```

If `data` is non-empty, the issue already exists — capture its `data[].id` for
the link step (3.2) instead of re-filing. Only run the create call for the
`TASK-XXX` titles that returned no match.

**Always set a `description` body.** A title-only issue shows up on the
dashboard as `No description / No discussion / 0 linked tasks / No attachments`
— i.e. visually indistinguishable from an issue that hasn't been started.
The bodies below are the minimum that makes each issue useful: what the
work is, where the proposal lives, which track it belongs to, and what it
blocks / depends on. They are short on purpose so you can paste them as-is
or extend them per-hive.

```bash
# k1 — Knowledge Wiki Redesign (4 issues)

# TASK-296 — schema
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/issues" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{
    \"title\": \"TASK-296 — Phase A1: schema (typed columns, partial unique indexes, GIN trigram)\",
    \"issue_type_id\": \"$TASK_TYPE_ID\",
    \"state\": \"open\",
    \"description\": \"## Phase A1: schema\n\nAdd the typed-page columns to \`knowledge_entries\` (type, slug, title, body, frontmatter, tags, source_ids), the partial unique index on (hive_id, slug) where state = 'active', and the GIN trigram index on title for fuzzy lookups.\n\n**Proposal:** docs/proposals/knowledge-wiki-redesign.md §6.1 + §6.6 (A1)\n**Spec / track:** /dashboard/tracks/k1\n**Depends on:** —\n**Blocks:** TASK-297, TASK-298, TASK-299\"
  }"

# TASK-297 — dual-shape
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/issues" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{
    \"title\": \"TASK-297 — Phase A2: dual-shape (typed ↔ value) on read/write\",
    \"issue_type_id\": \"$TASK_TYPE_ID\",
    \"state\": \"open\",
    \"description\": \"## Phase A2: dual-shape (typed ↔ value) on read/write\n\nService layer accepts the new typed-page fields but keeps writing the legacy \`value\` JSON column in parallel. Reads prefer typed columns when present, fall back to value. Reaches read- and write-parity for both shapes so the typed path can be promoted without a migration cutover.\n\n**Proposal:** docs/proposals/knowledge-wiki-redesign.md §6.1.1 / §9.1 (A2 dual-shape)\n**Spec / track:** /dashboard/tracks/k1\n**Depends on:** TASK-296\n**Blocks:** TASK-298, TASK-299\"
  }"

# TASK-298 — wiki links
# NOTE: do not put literal "[[slug]]" in the body — the issue update endpoint
# returns 500 when the body contains bare double brackets (caught in the
# smoke test for this runbook). Write it as "wiki-style double-bracket links"
# or escape the brackets.
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/issues" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{
    \"title\": \"TASK-298 — Phase A3: wiki links (wiki-style double-bracket parser, KnowledgeLink model)\",
    \"issue_type_id\": \"$TASK_TYPE_ID\",
    \"state\": \"open\",
    \"description\": \"## Phase A3: wiki links\n\nParser for wiki-style double-bracket links in body markdown. KnowledgeLink model + table to record link edges (source_entry_id, target_slug). Backlinks panel on the entry show page.\n\n**Proposal:** docs/proposals/knowledge-wiki-redesign.md §6.3 (A3 wiki links)\n**Spec / track:** /dashboard/tracks/k1\n**Depends on:** TASK-297\n**Blocks:** TASK-299\"
  }"

# TASK-299 — dashboard pages
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/issues" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{
    \"title\": \"TASK-299 — Phase A4: dashboard pages (Index, Show, Edit, slugMap)\",
    \"issue_type_id\": \"$TASK_TYPE_ID\",
    \"state\": \"open\",
    \"description\": \"## Phase A4: dashboard pages\n\nInertia pages for /dashboard/knowledge/{slug}, /dashboard/knowledge/{slug}/edit, the slugMap index. Markdown render uses the link parser from TASK-298.\n\n**Proposal:** docs/proposals/knowledge-wiki-redesign.md §10.1 / §10.2 (A4 dashboard)\n**Spec / track:** /dashboard/tracks/k1\n**Depends on:** TASK-298\"
  }"

# dw — Dynamic Workflows (1 issue)
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/issues" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{
    \"title\": \"TASK-300 — DW-1: schema (registry_items.kind = dynamic_workflow), PayloadValidator, executor attachment\",
    \"issue_type_id\": \"$TASK_TYPE_ID\",
    \"state\": \"open\",
    \"description\": \"## DW-1: schema + payload discriminator\n\nAdd \`registry_items.kind = 'dynamic_workflow'\` path, the per-kind PayloadValidator contract, executor attachment (the script-runtime attachment that loads \`.claude/scripts/dynamic-workflow/\`), draft state, and per-revision limits. Foundation beat for the dynamic-workflows kind.\n\n**Proposal:** docs/proposals/dynamic-workflows.md\n**Spec / track:** /dashboard/tracks/dw\n**Depends on:** —\n**Blocks:** DW-2 (orchestrator), DW-3 (resumability)\"
  }"
```

The `reg` track's "Registry: Skills + Modules onboarding" issue is usually
already filed on a dev hive (it's the standing issue for that beat) — skip
the `reg` step if it exists, otherwise file an equivalent one with the
beats list as the description body.

### 3.2 Link the issues to their tracks

Each `POST` returns the new issue's ULID in `data.id`. Capture those into
shell variables and link them:

```bash
# k1: link TASK-296..299
for ISSUE_ID in $K1_ISSUE_IDS ; do
  curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/tracks/k1/issues" \
    -H "Authorization: Bearer $AGENT_TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d "{\"issue_id\":\"$ISSUE_ID\"}"
  echo
done

# dw: link TASK-300
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/tracks/dw/issues" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "{\"issue_id\":\"$DW_ISSUE_ID\"}"

# reg: link the existing registry-skills-modules issue, if it exists
curl -sS -X POST "https://app.example.com/api/v1/hives/$HIVE/tracks/reg/issues" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "{\"issue_id\":\"$REG_ISSUE_ID\"}"
```

The **link** calls are safe to re-run — the link endpoint is idempotent, so a
second `POST` for an already-linked issue returns `200 OK` with the existing
link rather than creating a duplicate.

The **issue-creation** call is *not* idempotent: there is no title-uniqueness
contract, so a re-run will silently create a second issue with the same title
(and emit a second `issue.created` event). That is why step 3.1 says to search
first with `GET /api/v1/hives/{hive}/issues?q=TASK-296` and only file the titles
that have no existing match. If you do end up with duplicates, the same search
lists every matching id so you can pick the one to keep and link.

## 4. Idempotency / re-runs

`POST /api/v1/hives/{hive}/tracks` is **not** idempotent — re-running it on a hive
that already has, say, a `k1` track will return `422 Unprocessable Entity` with
the field-level error envelope:

```json
{
  "data": null,
  "meta": {},
  "errors": [
    { "message": "A track with slug [k1] already exists in this hive.", "code": "validation_error", "field": "slug" }
  ]
}
```

If you want to refresh the mutable fields (`name`, `description`, `spec`) on an
existing track, use `PATCH /api/v1/hives/{hive}/tracks/{slug}` instead. The slug
and state are immutable through that endpoint — slug never changes, and state
moves through the `/transition` endpoint rather than being patched directly.

## 5. Verify

```bash
curl -sS "https://app.example.com/api/v1/hives/$HIVE/tracks" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Accept: application/json"
```

You should see all three tracks in the `data` array (this `GET` requires the
`issues.read` permission).

In the dashboard, the same set is served at the **`/dashboard/tracks`** route
(`dashboard.tracks`). Note there is currently **no sidebar entry** for it — the
**Work** nav group only lists *Issues* and *Approvals* — so navigate to
`/dashboard/tracks` directly until a Tracks nav item is added.

## 6. Why not the seeder?

`TracksBackfillSeeder` resolves the hive via `config('platform.ce.hive_id')` —
a single hard-coded string intended for the CE docker-compose default hive.
On a multi-tenant Cloud install, that config key is unset, the seeder's
`resolveHive()` returns `null`, and `run()` exits early. There is no per-tenant
loop in the seeder because the seeder has no way to enumerate Cloud tenants
deterministically (the tenant list lives in the Cloud control plane, not the
app config). The Tracks API is the tenant-aware path; use it.
