# Tracks: First-Class Container for Multi-Issue Work

Status: Approved for implementation (TASK-301)
Owner: platform
Scope: Adds a `tracks` table that groups `issues` rows, holds
the spec, and gives the dashboard / agent a single query
("list open tracks, pick the next unblocked issue") instead of
the current "scan `TASKS.md` + `docs/proposals/*.md` + `docs/tasks/*.md`"
pattern.

## 1. Why

We have two in-flight multi-issue tracks (knowledge-wiki k1
with TASK-296/297/298/299; dynamic-workflows dw with
TASK-300+). The "Track" concept is implicit — a `Phase N`
section in `TASKS.md`, a `docs/proposals/*.md` file, and a
convention in the agent's head. When the agent (human or AI)
context-switches, "what's the active work" is hard to answer
from a single query. The role handoff
([`docs/process/CLAUDE-CODE-WORKFLOW.md`](../process/CLAUDE-CODE-WORKFLOW.md))
says "PM picks the next unblocked task" but doesn't say
"from which track" or "how to enumerate".

Promoting Track to a first-class object fixes three real
problems:

1. **Agent handoff**: a new session can list tracks, pick one,
   see its spec + open issues + linked PRs, claim an unblocked
   issue, and go — without grepping the docs tree.
2. **Spec drift**: the spec lives in `docs/proposals/*.md` and
   the work lives in `TASKS.md` and the task files. The
   proposal-to-task breakdown is loose. Tying the spec to a
   track object means one home for "what we're trying to
   build" and one home for "what's the next chunk".
3. **Cross-track coordination**: if knowledge-wiki is blocked
   on registry work, it's a track dependency — a first-class
   relation, not a sentence in a doc.

## 2. Naming

**Track.** Initiative sounds corporate, Program implies
multi-team, Epic is already narrow in Scrum. "Track" is
short, scannable, doesn't overload an existing term, and
matches the way the team already talks about this work
("the knowledge-wiki track", "the dynamic-workflows track").

Tracks live *under* the existing `Phase N` sections in
`TASKS.md`. The platform roadmap stays; tracks are the
working units within it.

## 3. Data model

### 3.1 `tracks` table

```
Track
  id                  ulid
  organization_id     ulid
  hive_id             ulid
  slug                string(100)      # per-hive unique
  name                string(255)
  description         text | null
  spec                text | null      # native markdown; canonical
  state               enum { planning, active, paused,
                              done, archived }
  created_by_type     string(20)       # 'user' | 'agent'
  created_by_id       ulid
  created_at          timestamp
  updated_at          timestamp
```

`spec` is **native**, not a knowledge entry. The spec *is* the
source of truth for the track, not a citation. Knowledge
entries *describe* things; a track spec *defines* them. Three
reasons to keep them separate:

- Agents have to glob/find a file to use a doc-attached spec.
- A spec is an instruction, not a citation — it doesn't have
  the multi-hive / private / org-scope semantics knowledge
  entries do.
- The proposal-to-track is 1:1; there is no fan-out that
  would benefit from the knowledge wiki's `[[…]]` link model.

For very long specs, an optional `spec_url` field can point to
the full `docs/proposals/*.md` for human readers — but the
canonical spec is on the row.

### 3.2 `issues.track_id`

`add_track_id_to_issues_table.php`: nullable FK, indexed.
Issues without a track are still valid (many issues are
incidental and don't belong to a track).

### 3.3 `slug` uniqueness

Per-hive unique among non-archived tracks, like the registry
items. Soft-collision: a new track with the same slug as a
deleted one requires the deleted track to have no live issues.

## 4. State machine

```
planning → active, archived
active   → paused, done, archived
paused   → active, done, archived
done     → archived, active (reopen)
archived → (terminal)
```

State transitions are gated by `TrackService::transitionState`
and logged to `activity_log`. Only `created_by` (or an org
admin) can transition; v1 has no separate "track manager" role.

## 5. API surface

```
GET    /api/v1/hives/{hive}/tracks                          # list (hive-scoped)
GET    /api/v1/hives/{hive}/tracks/{slug}                   # read one
POST   /api/v1/hives/{hive}/tracks                          # create
PATCH  /api/v1/hives/{hive}/tracks/{slug}                   # update name/description/spec
POST   /api/v1/hives/{hive}/tracks/{slug}/transition        # state transition
POST   /api/v1/hives/{hive}/tracks/{slug}/issues            # link an issue
DELETE /api/v1/hives/{hive}/tracks/{slug}/issues/{issue_id} # unlink
```

`{slug}` is unique-per-hive, so the URL pattern matches the
existing `/{kind}/{slug}` convention from the registry.

## 6. Dashboard

- **`/dashboard/tracks`** — index with progress bars
  (open issues / total issues), state pills, last-updated
- **`/dashboard/tracks/create`** — new track form (name,
  slug, description, spec, initial state)
- **`/dashboard/tracks/{slug}`** — show page with:
  - Spec rendered as markdown (use the same `MarkdownBody.jsx`
    component the knowledge-wiki pages use)
  - Issues list (filtered by `track_id`), with state pills
  - State transition controls (gated on permissions)
  - Linked PRs as a plain text field (URLs, one per line —
    v1; v2 scrapes from GitHub)
  - Add-issue / remove-issue controls

## 7. Out of scope (v1)

- Track edit page (use the show page's update form)
- Track comments / discussion (use the existing Issues thread)
- Track-to-track dependencies
- Track marketplace / templates
- Auto-PR-link via GitHub webhook
- Track-level permissions (uses org admin in v1)

## 8. Backfill

A seeder creates two tracks and links the existing in-flight
tasks:

| Track | State | Linked tasks |
|---|---|---|
| `k1` (Knowledge Wiki Redesign) | active | TASK-296, 297, 298, 299 |
| `dw` (Dynamic Workflows) | active | TASK-300 |

The seeder is idempotent (`firstOrCreate` keyed on
`(hive_id, slug)`) so re-runs are safe.
