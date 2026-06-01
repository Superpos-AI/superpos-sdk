---
name: TASK-279 workflow pin step to prior agent
description: Allow a workflow step to declare "pin to step X's agent" so the same Agent claims the downstream task that ran the upstream one.
type: project
---

# TASK-279: Pin workflow step to a prior step's agent

**Status:** pending
**Branch:** `task/279-workflow-pin-step-to-prior-agent`
**PR:** —
**Depends on:** TASK-177 (workflow engine), TASK-184 (workflow runs)
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_WORKFLOWS.md](../features/list-1/FEATURE_WORKFLOWS.md)

## Objective

Today, every workflow step's task is open-claim — whichever eligible agent polls first wins. Some workflows benefit from continuity: the agent that built a code patch in step `build` should also run step `test`, because it has warm context, local files, or specific tooling. Add a per-step `pin_to_step: <stepKey>` config that, when set, populates the new task's `target_agent_id` with the agent that processed the referenced upstream step.

## Background

- `tasks.target_agent_id` already exists and is honored by `TaskController::poll()` (matching agents claim, others skip — `app/Http/Controllers/Api/TaskController.php:293,317,329`).
- `WorkflowExecutionService::createStepTask()` (`app/Services/WorkflowExecutionService.php:1301-1369`) is the single point where a step's task is constructed. It already reads `target_agent_id` from the step definition (line 1335) — but no workflow surface lets users wire it dynamically.
- Per-step agent assignment is recoverable today via `Task::where('workflow_run_id', $runId)->where('workflow_step_key', $key)->first()->claimed_by`. No new column needed.

## Requirements

### Functional

- [ ] FR-1: Workflow step config accepts an optional `pin_to_step: <upstreamStepKey>` string. When present:
  - The referenced upstream step must exist in the same workflow definition.
  - The referenced upstream step must complete **before** this step in DAG order (validated at workflow save time, not at run time).
- [ ] FR-2: At task-creation time (`WorkflowExecutionService::createStepTask`), if the step has `pin_to_step`, look up the prior step's task in the same `workflow_run_id`, read its `claimed_by` agent id, and set the new task's `target_agent_id` to that value.
- [ ] FR-3: If the upstream task has no `claimed_by` (shouldn't happen — `advanceWorkflow` only fires after completion — but defensively handle it): log a warning, skip the pin, fall back to open-claim. Do not fail the run.
- [ ] FR-4: An explicit `target_agent_id` on the step config takes precedence over `pin_to_step` — explicit beats inherited. Document this in code.
- [ ] FR-5: Workflow-save validation (`UpdateWorkflowRequest::rules()` and `withValidator()`):
  - `pin_to_step` is a string when present.
  - The referenced step key exists.
  - The referenced step appears earlier in the topological order (no forward / self / cyclic pinning).
- [ ] FR-6: Workflow builder UI surfaces a per-step "Pin agent to step…" dropdown listing earlier steps. Empty = no pin.
- [ ] FR-7: Activity log entry on each pinned task creation: `workflow.step.pinned_agent` with `{workflow_run_id, step_key, pinned_to_step, agent_id}` (or just attach to the existing step-task-created event with extra fields — match precedent in the file).

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean.
- [ ] NFR-2: No new migrations, no new tables. The pin is config-only; the assignment uses the existing `target_agent_id` column.
- [ ] NFR-3: Save-time validation rejects pin cycles or forward references — runtime should never see an invalid pin.
- [ ] NFR-4: Backward-compat — existing workflows without `pin_to_step` are unaffected.
- [ ] NFR-5: Hive isolation unchanged — `target_agent_id` is in the same hive by construction (the upstream step's claimer was a hive-scoped agent).

## Architecture & Design

### Files to Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Services/WorkflowExecutionService.php` | `createStepTask()` resolves `pin_to_step` → upstream `claimed_by` → new task's `target_agent_id` |
| Modify | `app/Http/Requests/UpdateWorkflowRequest.php` | Validate `pin_to_step` field + DAG-order check in `withValidator()` |
| Modify | `resources/js/Pages/WorkflowBuilder.jsx` | Per-step "Pin agent to step…" dropdown |
| Modify | `tests/Feature/WorkflowExecutionServiceTest.php` (or create `WorkflowPinAgentTest.php`) | Pin propagation, fallback, precedence |
| Modify | `tests/Feature/Dashboard/WorkflowSaveValidationTest.php` (or wherever step-config validation tests live) | Pin validation: forward ref, cycle, missing step |
| Modify | `resources/js/Pages/__tests__/WorkflowBuilder.test.jsx` | Pin dropdown render + selection |

### Key Design Decisions

- **Reuse `target_agent_id`** — the dispatch primitive already exists. The "pin" is just deferred-resolution sugar over an existing field.
- **Resolve pins at task-creation, not at run start** — early steps may complete on any agent; the pin can only resolve when the upstream actually finishes. `createStepTask` already runs at the right moment (called from `advanceWorkflow` after upstream completion).
- **Validate at save time, run defensively at runtime** — most failures (cycles, missing refs) are caught at workflow save. Runtime fallback (no `claimed_by`) is a guardrail, not the primary safety net.
- **Explicit beats implicit** — if the step config has both `target_agent_id` (hard-coded) and `pin_to_step` (dynamic), `target_agent_id` wins. This matches how `target_agent_id` already overrides `target_capability`.
- **No new column on `workflow_runs` or `tasks`** — `Task.claimed_by` is authoritative for "which agent ran step X". Don't duplicate.

## Implementation Plan

1. **Validation** — extend `UpdateWorkflowRequest` to validate `pin_to_step` field + add a `withValidator` block that checks: target step exists, target step appears earlier in the steps array (or in topological order if branching is supported), no self-reference. Fail with a clear message: `"steps.{key}.pin_to_step references unknown or downstream step: {ref}"`.
2. **Runtime resolution** — in `WorkflowExecutionService::createStepTask`, after the existing `target_agent_id` resolution block (line ~1334), if `target_agent_id` is still null and `pin_to_step` is set:
   - Query: `Task::where('workflow_run_id', $run->id)->where('workflow_step_key', $stepDef['pin_to_step'])->whereNotNull('claimed_by')->first()`
   - If found, set `target_agent_id = $upstreamTask->claimed_by`. Log success.
   - If not found, log a warning and proceed with open-claim.
3. **Builder UI** — add a "Pin to step" dropdown next to existing target_agent_id / target_capability inputs. Lists earlier steps only. Empty option = no pin.
4. **Activity log** — extend the existing step-task-created event payload (whatever the file currently emits) with `pinned_to_step` and `pinned_agent_id` when pinning resolved.
5. **Tests** — see Test Plan.

## Test Plan

### Feature Tests
- [ ] Step with `pin_to_step` referring to a completed upstream step: new task's `target_agent_id` matches that step's `claimed_by`
- [ ] Multiple pinned steps in a chain (A → B pin A → C pin B): all three resolve to the same agent
- [ ] Step with both `target_agent_id` (explicit) and `pin_to_step`: `target_agent_id` wins
- [ ] Workflow-save validation rejects `pin_to_step` referring to:
  - A non-existent step key (404-style validation error)
  - A step that comes after the current step in DAG order
  - The current step itself (self-pin)
- [ ] Defensive runtime: if upstream task somehow has no `claimed_by`, log warning and fall back to open-claim (do not throw)
- [ ] Workflow without any `pin_to_step` field works exactly as before (regression guard)
- [ ] Activity log records `pinned_to_step` + `pinned_agent_id` on pinned task creation

### JSX Tests
- [ ] Step builder renders "Pin to step" dropdown listing only earlier steps
- [ ] Selecting a step writes `pin_to_step` into the step config payload sent on save
- [ ] Editing a step that comes first in the workflow shows an empty (or disabled) pin dropdown — nothing earlier to pin to

## Validation Checklist

- [ ] All tests pass
- [ ] Pint clean
- [ ] No new migrations
- [ ] Save-time DAG-order validation prevents forward / cyclic pins
- [ ] Runtime fallback never breaks a run
- [ ] Backward-compat — workflows without `pin_to_step` produce identical task payloads to current behavior

## Notes for Implementer

- The existing `target_capability` and `target_agent_id` resolution already lives in `createStepTask` lines ~1330-1356. Add the pin resolution as a third branch in the same block — keep the dispatch logic centralized.
- For DAG-order validation: if branching is currently topologically ordered via `next_steps` arrays in the step definitions, walk the graph from each step and assert the pin target is reachable upstream. If steps are a flat ordered list, simple index comparison works. Look at how `WorkflowExecutionService::resolveNextSteps` walks the graph and reuse that logic.
- Consider documenting the failure mode in the workflow builder UI: "If the pinned agent is offline when this step runs, the task waits in the queue until that agent comes back online or you manually re-target." — operators need to know this isn't free.
