# TASK-301 — Tracks layer (process tooling)

**Status:** ⬜ pending
**Owner:** platform
**Track:** meta / process tooling
**Blocked by:** —
**Blocks:** —
**Proposal:** [`docs/proposals/tracks.md`](../proposals/tracks.md)

## Why

We have two in-flight "tracks" of work (knowledge-wiki k1,
dynamic-workflows dw) but the concept of *Track* is implicit —
a `Phase N` section in `TASKS.md`, a `docs/proposals/*.md`
file, and a convention in the agent's head. When the agent
context-switches, "what's the active work" is hard to answer
from a single query.

Promote Track to a first-class object with:
- a `tracks` table
- a `spec` field (native markdown, not a knowledge entry)
- `has_many :issues` (issues already exist; just add a FK)
- a state machine: `planning → active → paused → done → archived`
- dashboard pages (index, show, create)
- the existing role-handoff sequence re-anchored to "pick the
  next unblocked issue in the active track"

## Scope (in)

1. **Schema**
   - `tracks` table: id, organization_id, hive_id, slug, name,
     description, spec (text/markdown nullable), state
     (planning|active|paused|done|archived), created_by_type/id
     (polymorphic), created_at, updated_at
   - `add_track_id_to_issues_table`: nullable FK + index
2. **Model**: `App\Models\Track` (BelongsToOrganization,
   BelongsToHive, HasUlid)
3. **Service**: `App\Services\TrackService` — createTrack,
   updateTrack, transitionState, linkIssue, unlinkIssue
4. **Form requests**: `StoreTrackRequest`, `UpdateTrackRequest`
5. **API**: `App\Http\Controllers\Api\TrackController` (index,
   show, store, update, transition)
6. **Dashboard controller**: `App\Http\Controllers\Dashboard\TrackDashboardController`
   (index, create, store, show, edit, update, transition,
   linkIssue, unlinkIssue)
7. **Routes**: web.php + api.php
8. **UI pages**:
   - `resources/js/Pages/Tracks/Index.jsx` (list, state pills,
     progress bars)
   - `resources/js/Pages/Tracks/Show.jsx` (spec render, issues
     list, state controls, linked PRs as plain text for v1)
   - `resources/js/Pages/Tracks/Create.jsx`
9. **UI components** (3): `TrackHeader`, `TrackStatePill`,
   `TrackIssueList`
10. **Issue form**: add a Track picker to `IssueCreateForm.jsx`
11. **Backfill**: seed 2 rows for knowledge-wiki (k1) and
    dynamic-workflows (dw); link the existing TASK-296, 297,
    298, 299 (k1) and TASK-300 (dw) to them via a
    seeder/migration
12. **Tests** (4 files):
    - `TrackServiceTest`
    - `TrackDashboardIndexTest`
    - `TrackDashboardShowTest`
    - `TrackIssueLinkingTest`
13. **Doc**: `docs/proposals/tracks.md` (short, ~150 lines)
14. **TASKS.md**: Phase 17 + TASK-301 row
15. **Workflow doc update**: small edit to
    `docs/process/CLAUDE-CODE-WORKFLOW.md` so the role handoff
    references Track

## Out of scope (deferred)

- Track edit page (use the existing `update` endpoint from the
  show page in v1; dedicated `Edit.jsx` is a v2 polish)
- Track comments / discussion thread (use the existing Issues
  thread for any back-and-forth)
- Track-to-track dependencies (a `depends_on_track_id` column
  is straightforward but not needed yet)
- Track marketplace / templates
- Auto-PR-link via GitHub webhook (for v1, PRs are a plain
  text field on the track; v2 can scrape from GitHub)
- Track events / activity log entries beyond what
  `ActivityLogger` already records

## Files touched

### New (≈18 files)
- `database/migrations/2026_06_11_100000_create_tracks_table.php`
- `database/migrations/2026_06_11_100001_add_track_id_to_issues_table.php`
- `database/seeders/TracksBackfillSeeder.php`
- `app/Models/Track.php`
- `app/Services/TrackService.php`
- `app/Http/Requests/StoreTrackRequest.php`
- `app/Http/Requests/UpdateTrackRequest.php`
- `app/Http/Controllers/Api/TrackController.php`
- `app/Http/Controllers/Dashboard/TrackDashboardController.php`
- `resources/js/Pages/Tracks/Index.jsx`
- `resources/js/Pages/Tracks/Show.jsx`
- `resources/js/Pages/Tracks/Create.jsx`
- `resources/js/Components/Tracks/TrackHeader.jsx`
- `resources/js/Components/Tracks/TrackStatePill.jsx`
- `resources/js/Components/Tracks/TrackIssueList.jsx`
- `tests/Feature/Track/TrackServiceTest.php`
- `tests/Feature/Track/TrackDashboardIndexTest.php`
- `tests/Feature/Track/TrackDashboardShowTest.php`
- `tests/Feature/Track/TrackIssueLinkingTest.php`
- `docs/proposals/tracks.md`
- `docs/tasks/TASK-301-tracks-layer.md` (this file)

### Modified (≈3 files)
- `app/Models/Issue.php` (add `track_id` to fillable, `track()`
  relation)
- `routes/web.php` (add dashboard routes)
- `routes/api.php` (add API routes)
- `resources/js/Components/Issues/IssueCreateForm.jsx` (add
  Track picker)
- `TASKS.md` (Phase 17 + row)
- `docs/process/CLAUDE-CODE-WORKFLOW.md` (mention Track in
  the role handoff)

## Definition of done

- Migrations apply cleanly on PG and SQLite
- All 4 test files pass
- Dashboard pages render in the existing Inertia + React
  layout (no new global CSS)
- `vendor/bin/pint --test` clean
- No regression in `IssueDashboardIndexTest` /
  `IssueDashboardCreateTest`
- PR opened, reviewed, merged
- TASKS.md row flipped to ✅
- The 2 backfilled tracks (`k1`, `dw`) are visible on
  `/dashboard/tracks` with their in-flight issues linked
