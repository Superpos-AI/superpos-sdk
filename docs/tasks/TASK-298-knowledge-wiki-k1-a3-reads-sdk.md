# TASK-298: Knowledge Wiki — Phase A3 Read Paths + SDK + Routes

**Status:** pending
**Branch:** `task/298-knowledge-wiki-a3-reads-sdk`
**PR:** —
**Depends on:** TASK-296, TASK-297
**Blocks:** TASK-299

> Stub. Full implementation plan lands when this task is picked up.
> See the parent proposal
> [`docs/proposals/knowledge-wiki-redesign.md`](../proposals/knowledge-wiki-redesign.md)
> §8, §9.1 and TASK-296 / TASK-297 for the contracts this task builds
> on.

## Objective (high level)

Add the typed-page read paths, the new raw-source endpoints, and the
SDK surface. The wildcard `{entry}` route gets a `where` constraint to
defend-in-depth against future re-ordering; literal routes for
`sources`, `types`, `backlinks`, `synthesize-topic` go ABOVE the
wildcard in registration order.

## Scope summary

- `app/Http/Controllers/Api/KnowledgeSourceController.php` — new
  controller (index, show, store).
- `app/Http/Controllers/Api/KnowledgeController.php` — gain
  `listByType`, `backlinks`, `synthesizeTopic`.
- `routes/api.php` — literal-first-then-wildcard ordering with
  `where` constraint on the `{entry}` wildcard.
- `app/Services/KnowledgeGraphService.php` — extend for
  `wiki_links` + backlinks.
- `app/Http/Controllers/Api/KnowledgeSearchController.php` (or
  equivalent) — rewire `body` instead of `value::text` in search
  queries.
- `superpos-agent-core` (separate repo) — new
  `src/superpos_agent_core/knowledge.py` with 10 new methods
  (`create_page`, `update_page`, `get_backlinks`, `list_by_type`,
  `synthesize_topic`, `ingest_source`, `get_source`, `list_sources`,
  `get_wiki_index`, `get_wiki_log`).
- `superpos-agent-core` — new `wiki/AGENTS.md` (procedural schema
  for the bookkeeper).
- `tests/Feature/Knowledge/KnowledgeRouteOrderingTest.php` — hard
  gate on the route wiring.

Detailed plan, files-to-modify, and test plan go in this file when
the task is picked up.
