# TASK-216: Knowledge links migration + model + CRUD API

**Status:** done
**Branch:** `task/216-knowledge-links`
**Depends on:** TASK-009
**Blocks:** TASK-217, TASK-218, TASK-219, TASK-220, TASK-221, TASK-224, TASK-225
**Edition:** shared
**Feature doc:** [FEATURE_KNOWLEDGE_GRAPH.md](../features/list-1/FEATURE_KNOWLEDGE_GRAPH.md) §3 Layer 2

## Objective

Create the knowledge_links table that connects entries to each other and to other Superpos entities (tasks, channels, agents). This is the core graph infrastructure — entries become nodes, links become edges.

## Requirements

### Functional

- [ ] FR-1: `knowledge_links` table: id (bigserial), source_id (FK to knowledge_entries), target_id (FK to knowledge_entries, nullable), target_type (knowledge/task/channel/agent), target_ref (ID of non-knowledge target), link_type, metadata (JSONB), created_by, created_at
- [ ] FR-2: Link types: relates_to, depends_on, supersedes, derived_from, decided_in, implemented_by, authored_by, part_of
- [ ] FR-3: `POST /api/v1/hives/{hive}/knowledge/{id}/links` — create a link from this entry
- [ ] FR-4: `DELETE /api/v1/hives/{hive}/knowledge/links/{link_id}` — remove a link
- [ ] FR-5: `GET /api/v1/hives/{hive}/knowledge/links?source={id}` — list links from an entry
- [ ] FR-6: `GET /api/v1/hives/{hive}/knowledge/links?target_ref={id}&target_type={type}` — list links TO an entity
- [ ] FR-7: KnowledgeLink model with relationships
- [ ] FR-8: Indexes on source_id, target_id, and (target_type, target_ref)
- [ ] FR-9: Cascade delete: when a knowledge entry is deleted, its links are removed
- [ ] FR-10: `link_count` accessible on knowledge entry (count of outgoing + incoming links)
- [ ] FR-11: Activity log on link create/delete
