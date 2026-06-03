# TASK-274: Frontend — Components, Hooks & Superpos Branding

**Status:** done
**Branch:** `feature/rename-apiary-to-superpos`
**PR:** [#458](https://github.com/Superpos-AI/superpos-app/pull/458)
**Depends on:** TASK-271, TASK-272
**Blocks:** TASK-275

## Objective

Rename frontend code to brand-neutral internals (Organization, org) and apply
"Superpos" branding to all user-visible text. Internal JS variables and hooks
use generic names; only strings shown to users say "Superpos".

## Requirements

### Functional

- [ ] FR-1: Rename `resources/js/Hooks/useApiaryChannel.js` → `resources/js/Hooks/useOrgChannel.js`
- [ ] FR-2: Update all imports of `useApiaryChannel` to `useOrgChannel`
- [ ] FR-3: Update broadcast channel references: `apiary.{id}` → `org.{id}`
- [ ] FR-4: Replace all user-visible "Superpos" text with "Superpos" (page titles, nav, layouts, footer)
- [ ] FR-5: Update any React components with "Superpos" in their file/component name
- [ ] FR-6: Update Inertia shared data keys if they reference "apiary"
- [ ] FR-7: Update `<title>` tags and meta descriptions
- [ ] FR-8: Update any logo/brand references in layout files

### Non-Functional

- [ ] NFR-1: Internal JS variable names are brand-neutral (use `org`, `organization`, not `superpos`)
- [ ] NFR-2: Only user-visible strings say "Superpos"
- [ ] NFR-3: `npm run build` succeeds without errors

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Rename | `resources/js/Hooks/useApiaryChannel.js` → `useOrgChannel.js` | Hook rename |
| Modify | `resources/js/Pages/**/*.jsx` | Update imports, visible text |
| Modify | `resources/js/Layouts/*.jsx` | Brand name, navigation text |
| Modify | `resources/views/**/*.blade.php` | HTML titles, meta tags |

### Key Design Decisions

- **`useOrgChannel`**: Short, clear, brand-neutral
- **"Superpos" only in visible text**: If the brand changes again, only string literals need updating
- **Shared data key rename**: `$page.props.apiary` → `$page.props.organization` — coordinated with TASK-272
- **Broadcast channels**: Must match backend (`org.{id}`) — coordinated with TASK-272

## Implementation Plan

1. Rename `useApiaryChannel.js` to `useOrgChannel.js`, update hook internals
2. Find all imports of `useApiaryChannel` across React files and update
3. Update broadcast channel name strings to match backend (`org.{id}`)
4. Find all user-visible "Superpos" text in JSX/Blade files and replace with "Superpos"
5. Update page `<title>` tags in Blade layout
6. Update Inertia shared data key names in JSX
7. Update any component names or file names containing "Superpos"
8. Run `npm run build` to verify no build errors
9. Visual spot-check: boot the app and verify "Superpos" appears in nav, titles, footer

## Test Plan

### Feature Tests

- [ ] All dashboard pages render without errors
- [ ] Brand name "Superpos" appears in page title
- [ ] No visible "Superpos" text remains in the UI
- [ ] `npm run build` completes successfully
- [ ] Broadcast events received correctly on renamed channels

## Validation Checklist

- [ ] `npm run build` succeeds
- [ ] No remaining "Superpos" in user-visible UI text
- [ ] No broken React imports
- [ ] Broadcast channels work end-to-end
- [ ] PSR-12 compliant (for any PHP Blade changes)
