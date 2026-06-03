---
name: TASK-194 QA evaluator persona template
description: Enrich the seeded "QA Evaluator" marketplace persona with the rigorous documents + config needed for use as a loop-step evaluator.
type: project
---

# TASK-194: QA evaluator persona template

**Status:** done
**Branch:** `task/194-qa-evaluator-persona-template`
**PR:** [#477](https://github.com/Superpos-AI/superpos-app/pull/477)
**Depends on:** TASK-133 (persona template system), TASK-191 (loop step engine)
**Blocks:** TASK-193 (Plan-Build-QA template wants this persona slug to exist)
**Edition:** shared
**Feature doc:** [FEATURE_WORKFLOWS.md](../features/list-1/FEATURE_WORKFLOWS.md) §3.2 (loop step)

## Objective

The marketplace already seeds a persona with slug `qa-evaluator`, but its content is skeletal — only a SOUL document, no AGENT/RULES/EXAMPLES, no calibrated scoring guidance. Enrich it so it works as a real loop-step evaluator (TASK-191) returning structured `{score, pass, feedback}` JSON that workflow loops can read for retry decisions.

## Background

- TASK-191 added a `loop` step type to the workflow engine. The loop body re-runs N times until an evaluator step returns `pass: true` (or N exhausted).
- TASK-133 / `MarketplacePersonaTemplateSeeder.php` seeds the persona catalog. The current `qa-evaluator` entry (lines ~323–338) has only a brief SOUL string. Built-in workflow templates (TASK-193) will reference `qa-evaluator` as the evaluator persona for Plan-Build-QA — that contract requires structured output, not a freeform SOUL.

## Requirements

### Functional

- [ ] FR-1: The seeded `qa-evaluator` entry in `MarketplacePersonaTemplateSeeder` has all five document slots populated:
  - `SOUL` — identity / purpose (one paragraph max)
  - `AGENT` — step-by-step evaluation procedure: read the work product → check against rubric → produce JSON → stop. Must explicitly state the JSON output contract.
  - `RULES` — scoring discipline (no flattery, no reasoning beyond rubric, threshold enforcement, what to do on ambiguous cases)
  - `STYLE` — terse, structured, no preamble
  - `EXAMPLES` — 3 calibrated samples (one clear pass, one clear fail, one borderline) showing the exact JSON shape and the scoring rationale
- [ ] FR-2: Output contract — the persona must instruct the model to return **only** valid JSON of shape:
  ```json
  {
    "score": 0-10,
    "pass": true|false,
    "feedback": "one-paragraph rationale + concrete next-step suggestions"
  }
  ```
  `pass` is `true` iff `score >= 7`. The threshold value is documented in RULES so workflow authors know how to tune it (and so the loop step's evaluator-result parser knows what shape to expect).
- [ ] FR-3: `config` block:
  - `model`: `claude-sonnet-4-6` (cheaper than Opus, sufficient for evaluation)
  - `temperature`: `0.0` (deterministic; evaluators must not hallucinate scores)
  - `max_tokens`: small enough to discourage rambling, large enough for the JSON + feedback (~500)
  - `claim_type`: `evaluate`
  - `capabilities`: `["evaluate", "qa"]`
- [ ] FR-4: Marketplace surface — entry is `is_featured: true`, `visibility: 'public'`, with a description that explicitly says "designed for use as the evaluator step in a loop workflow."
- [ ] FR-5: Idempotent — re-running the seeder updates the existing `qa-evaluator` row in place (current seeder uses `updateOrCreate(['slug' => …])`; preserve that).

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean.
- [ ] NFR-2: No new tables, no migration, no controller changes — pure seeder content.
- [ ] NFR-3: Existing personas in the seeder are untouched.
- [ ] NFR-4: Backward compatible — existing installs that already have a `qa-evaluator` row pick up the enriched content on the next seeder run.

## Architecture & Design

### Files to Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `database/seeders/MarketplacePersonaTemplateSeeder.php` | Replace the skeletal `qa-evaluator` block (~lines 323–338) with the rich version |
| Modify | `tests/Feature/MarketplacePersonaTemplateSeederTest.php` (or create one if absent) | Assert the enriched contract: all 5 documents present, JSON-shape language present in AGENT, threshold present in RULES |

### Key Design Decisions

- **No new file** — the persona slot exists; we are enriching content, not building infra.
- **Threshold (7/10) hard-coded in the persona docs**, not in the seeder's `config` block. Workflow authors can override at workflow-step config time, but the persona's *default* contract is documented with one threshold so the loop step's evaluator-result parser has a stable expectation.
- **Three calibrated examples**, not more. Each example is short. The goal is consistency, not coverage of every edge case.

## Implementation Plan

1. Read the current `qa-evaluator` block in `MarketplacePersonaTemplateSeeder::agentTemplates()` (~lines 323–338) and a richer reference (e.g. `code-review-bot` ~lines 143–175) for the document/config shape.
2. Draft the five documents (SOUL/AGENT/RULES/STYLE/EXAMPLES) per FR-1 / FR-2.
3. Replace the skeletal block in the seeder with the enriched one. Bump `is_featured` to `true`, set `temperature: 0.0`, set `model: claude-sonnet-4-6`, expand `description`.
4. Run `php artisan db:seed --class=MarketplacePersonaTemplateSeeder` against a fresh SQLite to confirm idempotency (run twice, expect no duplicate, content updated).
5. Add/extend a test asserting:
   - Persona row exists with slug `qa-evaluator`.
   - All five document keys present and non-empty.
   - AGENT document mentions the JSON output shape (`score`, `pass`, `feedback`).
   - RULES document mentions the threshold (e.g. contains the substring `7`).
   - `config.temperature === 0.0`.
   - `config.model === 'claude-sonnet-4-6'`.

## Test Plan

- [ ] Seeder run creates the enriched persona with all five documents.
- [ ] Re-running the seeder is idempotent — no duplicate row, content updated in place.
- [ ] AGENT document contains the strings `score`, `pass`, `feedback` (the JSON output contract).
- [ ] RULES document mentions the threshold value (`7`).
- [ ] `config.temperature` is `0.0`.
- [ ] `config.model` is `claude-sonnet-4-6`.
- [ ] EXAMPLES section contains 3 calibrated samples (parseable as JSON or clearly fenced).

## Validation Checklist

- [ ] Tests pass
- [ ] Pint clean
- [ ] Idempotency verified (run seeder twice on a fresh DB)
- [ ] Persona discoverable in marketplace UI under the `evaluate` capability
- [ ] Output contract documented in persona description so workflow authors know what JSON shape to expect when wiring the loop evaluator
