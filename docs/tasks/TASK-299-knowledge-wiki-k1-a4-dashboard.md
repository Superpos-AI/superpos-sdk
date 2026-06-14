# TASK-299: Knowledge Wiki — Phase A4 Dashboard UI

**Status:** pending
**Branch:** `task/299-knowledge-wiki-a4-dashboard`
**PR:** —
**Depends on:** TASK-296, TASK-297, TASK-298
**Blocks:** —

> Stub. Full implementation plan lands when this task is picked up.
> See the parent proposal
> [`docs/proposals/knowledge-wiki-redesign.md`](../proposals/knowledge-wiki-redesign.md)
> §10 and TASK-296 / TASK-297 / TASK-298 for the contracts this task
> builds on.

## Objective (high level)

Rewrite the dashboard `Show.jsx` to render typed markdown pages (the
`JSON.stringify(entry.value, null, 2)` dump stays for Phase A as a
sanity check, drops in Phase E). Add the Backlinks, Sources,
Frontmatter, and Edit History panels. Add the wiki catalog index
page. Add the raw-sources dashboard pages.

## Scope summary

- `resources/js/Pages/Knowledge/Show.jsx` — markdown-rendered body,
  Frontmatter panel, Sources panel, Backlinks panel, Edit History
  panel. JSON dump retained for Phase A, removed in Phase E.
- `resources/js/Pages/Knowledge/Index.jsx` — new wiki catalog
  page (replaces `KnowledgeIndexService` blob output for
  read-side rendering).
- `resources/js/Pages/Knowledge/Source/Show.jsx`,
  `resources/js/Pages/Knowledge/Source/Index.jsx` — new raw-sources
  dashboard pages.
- `resources/js/Components/Knowledge/BacklinksPanel.jsx`,
  `FrontmatterPanel.jsx`, `SourcesPanel.jsx`,
  `EditHistoryPanel.jsx` — new shared components.
- `resources/js/Components/Knowledge/per-type/` — per-type render
  templates (entity, topic, trend, source, log, procedure).
- `routes/web.php` — literal-then-wildcard ordering for
  `/knowledge/wiki` and `/knowledge/sources/{id}`.

Detailed plan, files-to-modify, and test plan go in this file when
the task is picked up.
