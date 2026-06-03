---
name: TASK-282 CI Tier-1 optimizations
description: Cut CI wall time with parallel PHPUnit, artifact reuse for the Vite manifest, JSX test coverage in CI, and a node_modules cache.
type: project
---

# TASK-282: CI Tier-1 optimizations

**Status:** pending
**Branch:** `task/282-ci-tier-1-optimizations`
**PR:** —
**Depends on:** —
**Blocks:** —
**Edition:** shared
**Feature doc:** this task.

## Objective

With ~6k PHP tests, CI wall time is becoming a bottleneck. The existing pipeline already splits jobs and caches composer, but leaves three obvious wins on the table: PHPUnit runs single-threaded, `php-tests` duplicates the Vite build that `frontend-build` already did, and JSX tests don't run in CI at all. Fix those without adding new infrastructure or changing test coverage.

## Background

Current `/.github/workflows/ci.yml` jobs (all parallel, `self-hosted, linux`):
- `php-lint` — composer install + `pint --test`
- `php-tests` — composer install + `npm ci` + `npm run build` + `php artisan test`  ← does Vite build even though `frontend-build` does the same
- `frontend-build` — `npm ci` + `npm run build`  ← discards output
- `python-sdk` — ruff + pytest
- `cloud-boundary` — grep-based boundary checks

## Scope

Five changes, all in `.github/workflows/ci.yml`:

1. **Parallel PHPUnit.** Change `php artisan test --ansi` to `php artisan test --ansi --parallel`. Don't pin `--processes=N` — let Laravel default to core count. Pinning is only needed if the runner OOMs; verify during implementation and add `--processes=4` only if required.
2. **Share the Vite manifest between `frontend-build` and `php-tests`.**
   - `frontend-build` uploads `public/build/` as an artifact via `actions/upload-artifact@v4`.
   - `php-tests` depends on `frontend-build` (`needs: frontend-build`) and downloads the artifact instead of re-running `npm ci` + `npm run build`. Drop the node setup + npm install + build steps from `php-tests`.
   - Add `needs: frontend-build` to `php-tests` only — other jobs stay independent.
3. **Add JSX tests.** In `frontend-build`, after `npm ci` and before `npm run build` (or as a sibling step), run `npm run test -- --run` (Vitest's non-watch mode; verify actual command from `package.json`). If the command is different, use the right one.
4. **Cache `node_modules`.** Add an `actions/cache@v4` step for `node_modules` keyed on `hashFiles('package-lock.json')` in both `frontend-build` and any other job that still installs node (ideally only `frontend-build` after change 2). This makes `npm ci` effectively no-op on cache hit.
5. **Parallel pytest for Python SDK.** Add `pytest-xdist` to the Python SDK's dev dependencies and run `pytest -n auto -v`. Small SDK, small win, but trivial to ship while we're here.

## Non-goals (explicit)

- Path-based job skipping (Tier 2 — separate task if needed).
- Change-aware test selection (Tier 3, not doing).
- "Fast suite on PR, full suite on merge" (Tier 3, not doing).
- Moving to GitHub-hosted runners from self-hosted.
- Rewriting any test to be parallel-safe. If a test fails under `--parallel`, that's a real bug to fix — do not revert to serial.

## Requirements

### Functional

- [ ] FR-1: `php-tests` job runs `php artisan test --ansi --parallel`.
- [ ] FR-2: `frontend-build` uploads `public/build/` as an artifact named `vite-build`.
- [ ] FR-3: `php-tests` depends on `frontend-build` via `needs:`, downloads the `vite-build` artifact into `public/build/`, and no longer installs node or runs `npm ci` / `npm run build`.
- [ ] FR-4: `frontend-build` runs `npm run test -- --run` (or the equivalent JSX test command from `package.json`) and fails the job on any test failure.
- [ ] FR-5: `node_modules` is cached in `frontend-build` keyed on `package-lock.json`. Cache hit makes `npm ci` skip actual install.
- [ ] FR-6: `python-sdk` job runs `pytest -n auto -v`. `pytest-xdist` added to `sdk/python/pyproject.toml` under dev dependencies.

### Non-Functional

- [ ] NFR-1: No regression in CI coverage — every test that runs today still runs.
- [ ] NFR-2: Measurable wall-time reduction. Baseline current green CI run, note PHP-tests duration before and after in the PR body.
- [ ] NFR-3: Idempotent re-runs — artifact download must not fail a re-run on the same SHA. Use `download-artifact@v4` default behavior.
- [ ] NFR-4: No new infra dependencies (no external cache, no Docker layer cache tricks).
- [ ] NFR-5: Revert is a one-commit change — don't refactor the workflow's structure while here.

## Architecture & Design

### Files to Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `.github/workflows/ci.yml` | The five changes above |
| Modify | `sdk/python/pyproject.toml` | Add `pytest-xdist` to `[project.optional-dependencies].dev` |

### Key Design Decisions

- **No `--processes=N` pin up front.** Paratest / Laravel parallel defaults to CPU count. Self-hosted runner specs vary; let it auto-pick. Pin only if OOM shows up.
- **Artifact, not cache, for the Vite build.** The build output is tied to the exact SHA; an artifact is the right primitive. Cache would need a content-hash key and is error-prone.
- **JSX tests land in `frontend-build`, not a separate job.** The npm install is already paid for there. A separate job doubles setup cost for no parallelism benefit.
- **`node_modules` cache is additive.** `actions/setup-node@v4` with `cache: npm` caches the *registry cache* (speeds up `npm ci`'s download step), not the installed `node_modules`. Adding an explicit `node_modules` cache avoids the linking pass too.
- **`needs: frontend-build` couples two jobs that were previously independent.** Acceptable — `php-tests` was silently re-doing `frontend-build`'s work already; we're making the dependency explicit and saving the duplicate. If `frontend-build` fails, there's no point running the PHP suite anyway since the Inertia tests need the manifest.

## Implementation Plan

1. Baseline three recent green CI runs — note PHP-tests duration, frontend-build duration, total wall time. Put in the PR body.
2. Add `--parallel` to `php artisan test`. Push and observe; fix any newly-red tests as real parallel-safety bugs (not by opting out).
3. Add `upload-artifact` in `frontend-build`, `download-artifact` + `needs:` in `php-tests`, drop the node steps from `php-tests`. Verify Inertia tests still pass.
4. Add `npm run test -- --run` to `frontend-build`.
5. Add `node_modules` cache to `frontend-build`.
6. Update `sdk/python/pyproject.toml`; switch `pytest -v` → `pytest -n auto -v`.
7. Compare new CI timings against baseline; record delta in the PR body.

## Test Plan

This is infra-only. No new PHP/JSX tests. Validation is observational:

- [ ] CI passes on the PR itself
- [ ] `php-tests` job log shows parallel workers starting
- [ ] `php-tests` job log does NOT run `npm ci` or `npm run build`
- [ ] `frontend-build` log shows both Vitest and Vite build steps
- [ ] `frontend-build` log shows `node_modules` cache hit on the second CI run on this branch
- [ ] Second run on this branch has measurably lower wall time than the first (cache cold → warm)
- [ ] `python-sdk` log shows pytest-xdist workers (`[gw0]`, `[gw1]`, …)

## Validation Checklist

- [ ] CI green on the PR
- [ ] Wall-time delta documented in PR body with baseline numbers
- [ ] No test was opted out of parallel execution
- [ ] `php-tests` no longer installs node
- [ ] JSX tests actually fail CI when broken (add a temporary red test, confirm the job fails, revert before merge — optional but worth doing once)

## Notes for Implementer

- If `php artisan test --parallel` reveals tests that assume a single DB (e.g. using hard-coded connection `testing`), the fix is to make them use `$this->connection()` or rely on Laravel's paratest DB-per-process mechanism — don't mark them `->group('serial')` and opt out. Fix the root cause.
- If a JSX test fails under the new step but was "passing" locally, it's likely relying on DOM timing that Vitest's default reporter hid. Not a regression introduced here; fix the test.
- SQLite in-memory DBs: Laravel's parallel runner handles them per-process. No config changes needed if the suite is already `:memory:`.
- If the Vitest command in `package.json` isn't `npm run test`, use whatever's defined (common alternates: `npm run test:unit`, `npx vitest run`). Whatever you pick, document it in the PR body.
