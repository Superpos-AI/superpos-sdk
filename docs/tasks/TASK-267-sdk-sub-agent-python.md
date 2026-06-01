# TASK-267: Python SDK sub-agent methods

**Status:** pending
**Branch:** `task/267-sdk-sub-agent-python`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/473
**Depends on:** TASK-261, TASK-263
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §11.1

## Objective

Add sub-agent definition methods to the Python SDK, allowing agents to list, fetch, and assemble sub-agent definitions via the agent-facing API (TASK-261). Also update task claim response parsing to include the `sub_agent` block delivered at claim time (TASK-263).

## Background

The Python SDK (`sdk/python/src/superpos_sdk/`) provides the `SuperposClient` class for agent-server communication. With sub-agent definitions now available via the API (TASK-261) and included in task delivery (TASK-263), the SDK needs methods to:
1. Discover available sub-agent definitions (list, fetch by slug)
2. Get assembled prompts (by slug or by ID for version-stable access)
3. Parse the `sub_agent` block from task claim responses

SDK source: `sdk/python/src/superpos_sdk/client.py`
Models: `sdk/python/src/superpos_sdk/models.py`

## Requirements

### Functional

- [ ] FR-1: `client.get_sub_agent_definitions()` — calls `GET /api/v1/sub-agents`, returns list of sub-agent definition summaries (id, slug, name, description, model, version, document_count)
- [ ] FR-2: `client.get_sub_agent_definition(slug: str)` — calls `GET /api/v1/sub-agents/{slug}`, returns full definition with documents, config, allowed_tools. Returns the current active version.
- [ ] FR-3: `client.get_sub_agent_assembled(slug: str)` — calls `GET /api/v1/sub-agents/{slug}/assembled`, returns assembled prompt string for current active version
- [ ] FR-4: `client.get_sub_agent_definition_by_id(id: str)` — calls `GET /api/v1/sub-agents/by-id/{id}`, returns version-stable definition by ULID. Used when re-fetching a pinned definition from a task's `sub_agent.id`.
- [ ] FR-5: `client.get_sub_agent_assembled_by_id(id: str)` — calls `GET /api/v1/sub-agents/by-id/{id}/assembled`, returns version-stable assembled prompt by ULID
- [ ] FR-6: Parse `sub_agent` block from task claim responses — when `client.claim_task()` returns a task with a `sub_agent` field, parse it into a `SubAgent` data object with attributes: `id`, `slug`, `name`, `model`, `version`, `prompt`, `config`, `allowed_tools`. The task object should expose `task.sub_agent` as this typed object (or None if no sub-agent).
- [ ] FR-7: Update `create_task()` in `client.py`, `async_client.py`, and the `agent.py` helper to accept an optional `sub_agent_definition_slug: Optional[str] = None` parameter. When provided, include `"sub_agent_definition_slug": slug` in the task-creation request body sent to `POST /api/v1/hives/{hive_id}/tasks`. This aligns with the task-creation contract defined in TASK-263 and the existing hive-scoped endpoint used by `create_task()`.

### Non-Functional

- [ ] NFR-1: Follow existing SDK patterns for error handling, HTTP calls, and response parsing (reference: `client.py` existing methods)
- [ ] NFR-2: Backward compatible — existing agents that don't use sub-agent methods continue to work unchanged
- [ ] NFR-3: Add type hints for all new methods and data classes
- [ ] NFR-4: Include docstrings for all public methods

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `sdk/python/src/superpos_sdk/client.py` | Add sub-agent methods to SuperposClient |
| Modify | `sdk/python/src/superpos_sdk/models.py` | Add SubAgent and SubAgentDefinition data classes |
| Modify | `sdk/python/src/superpos_sdk/async_client.py` | Add async versions of sub-agent methods (if async client exists) |
| Modify | `sdk/python/src/superpos_sdk/agent.py` | Forward `sub_agent_definition_slug` in agent-level task-creation helper |
| Create | `sdk/python/tests/test_sub_agent.py` | SDK tests |

### Key Design Decisions

- **Typed data classes** — sub-agent responses are parsed into typed Python objects (dataclass or similar) rather than raw dicts. This matches the existing SDK pattern for tasks and other entities.
- **Slug-based vs ID-based methods** — both are provided. Slug-based methods are for discovery (what sub-agents are available?). ID-based methods are for version-stable re-fetch (the agent has a pinned ID from a claimed task and needs to re-fetch the exact version).
- **Task claim integration** — the `sub_agent` block from claim responses is automatically parsed and attached to the task object. No additional API call needed at claim time.

## Implementation Plan

1. Add data classes to `models.py`:
   ```python
   @dataclass
   class SubAgentSummary:
       """Lightweight sub-agent definition (from list endpoint)."""
       id: str
       slug: str
       name: str
       description: Optional[str]
       model: Optional[str]
       version: int
       document_count: int

   @dataclass
   class SubAgentDefinition:
       """Full sub-agent definition with documents."""
       id: str
       slug: str
       name: str
       description: Optional[str]
       model: Optional[str]
       version: int
       documents: Dict[str, str]
       config: Dict[str, Any]
       allowed_tools: Optional[List[str]]

   @dataclass
   class SubAgent:
       """Sub-agent info attached to a claimed task."""
       id: str
       slug: str
       name: Optional[str]
       model: Optional[str]
       version: int
       prompt: Optional[str]
       config: Optional[Dict[str, Any]]
       allowed_tools: Optional[List[str]]
   ```

2. Add methods to `client.py`:
   ```python
   def get_sub_agent_definitions(self) -> List[SubAgentSummary]:
       """List all active sub-agent definitions in the agent's hive."""
       response = self._get("/api/v1/sub-agents")
       return [SubAgentSummary(**item) for item in response["data"]]

   def get_sub_agent_definition(self, slug: str) -> SubAgentDefinition:
       """Get a specific sub-agent definition by slug (current active version)."""
       response = self._get(f"/api/v1/sub-agents/{slug}")
       return SubAgentDefinition(**response["data"])

   def get_sub_agent_assembled(self, slug: str) -> str:
       """Get the assembled system prompt for a sub-agent by slug."""
       response = self._get(f"/api/v1/sub-agents/{slug}/assembled")
       return response["data"]["prompt"]

   def get_sub_agent_definition_by_id(self, id: str) -> SubAgentDefinition:
       """Get a specific sub-agent definition by ID (version-stable)."""
       response = self._get(f"/api/v1/sub-agents/by-id/{id}")
       return SubAgentDefinition(**response["data"])

   def get_sub_agent_assembled_by_id(self, id: str) -> str:
       """Get the assembled system prompt for a sub-agent by ID (version-stable)."""
       response = self._get(f"/api/v1/sub-agents/by-id/{id}/assembled")
       return response["data"]["prompt"]
   ```

3. Update task claim response parsing:
   - In the task parsing logic (wherever `claim_task()` parses the response), check for `sub_agent` field
   - If present, parse it into a `SubAgent` object and attach to the task
   - If absent, set `task.sub_agent = None`

4. If `async_client.py` exists with async variants of client methods, add async versions of all new methods.

5. Update `create_task()` in `client.py` (and `async_client.py` / `agent.py` equivalents):
   - Add `sub_agent_definition_slug: Optional[str] = None` parameter
   - When set, include `"sub_agent_definition_slug": slug` in the request body
   ```python
   def create_task(
       self,
       prompt: str,
       ...,
       sub_agent_definition_slug: Optional[str] = None,
   ) -> Task:
       body = {... existing fields ...}
       if sub_agent_definition_slug is not None:
           body["sub_agent_definition_slug"] = sub_agent_definition_slug
       return self._post(f"/api/v1/hives/{hive_id}/tasks", body)
   ```

6. Write tests covering all new methods

## Test Plan

### Unit Tests

- [ ] `get_sub_agent_definitions()` calls correct endpoint and returns list of SubAgentSummary
- [ ] `get_sub_agent_definition(slug)` calls correct endpoint and returns SubAgentDefinition
- [ ] `get_sub_agent_assembled(slug)` calls correct endpoint and returns prompt string
- [ ] `get_sub_agent_definition_by_id(id)` calls correct endpoint and returns SubAgentDefinition
- [ ] `get_sub_agent_assembled_by_id(id)` calls correct endpoint and returns prompt string
- [ ] Task claim response with `sub_agent` block is parsed into SubAgent object
- [ ] Task claim response without `sub_agent` block sets task.sub_agent to None
- [ ] SubAgentSummary, SubAgentDefinition, SubAgent data classes have correct fields
- [ ] Error handling follows existing SDK patterns (404 → appropriate exception)
- [ ] `create_task()` without `sub_agent_definition_slug` does not include the field in the request body (backward compatible)
- [ ] `create_task()` with `sub_agent_definition_slug="coder"` includes the slug in the request body
- [ ] Async and agent.py variants of `create_task()` also forward `sub_agent_definition_slug`
- [ ] All methods have correct type hints and docstrings

## Validation Checklist

- [ ] All tests pass
- [ ] Follows existing SDK patterns (error handling, HTTP calls, response parsing)
- [ ] Backward compatible — no breaking changes to existing SDK API
- [ ] Type hints on all new methods
- [ ] Docstrings on all public methods
- [ ] Data classes for all response types
- [ ] Both slug-based and ID-based methods available
