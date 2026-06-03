# Knowledge Explorer

The knowledge explorer page provides a browsable view of all non-expired
knowledge entries across scopes. It surfaces scope breakdown, filtering, search,
and sorting — all rendered server-side via Inertia.js.

## URL

```
GET /dashboard/knowledge
```

## Sections

### Scope Breakdown

A color-coded bar and per-scope counts showing the distribution of knowledge
entries across the three scope types:

| Scope | Color | Meaning |
|-------|-------|---------|
| Hive | Sky | Scoped to the current hive |
| Superpos | Amber | Shared across all hives in the apiary |
| Agent | Purple | Private to a specific agent (`agent:{id}`) |

### Filter Bar

Three controls for narrowing and sorting the entry list:

| Control | Type | Options |
|---------|------|---------|
| Scope filter | Dropdown | All / Hive / Superpos / Agent |
| Search | Text input | Partial match on key and value content |
| Sort | Dropdown | Newest (default) / Key / Scope |

Filters are applied via URL query parameters and trigger a server-side reload:

```
/dashboard/knowledge?scope=hive&search=config&sort=key
```

### Knowledge Table

A responsive table with the following columns:

| Column | Description |
|--------|-------------|
| **Key** | Entry key in monospace (primary column) |
| **Value** | JSON value preview, truncated to 80 chars (hidden on mobile) |
| **Scope** | Color-coded scope badge |
| **Creator** | Name of the agent that created the entry (hidden on mobile) |
| **Version** | Entry version number |
| **TTL** | Time-to-live status — relative time or "None" |
| **Updated** | Relative time since last update |

### Pagination

Server-side pagination with 20 entries per page. Previous/Next links appear
when there are multiple pages. Page info shows "Page X of Y (N entries)".

### Empty State

When no knowledge entries exist, a centered message reads "No knowledge entries
found." instead of an empty table.

## Data Flow

All data is loaded server-side in `KnowledgeDashboardController::index()` and
passed as Inertia props. No client-side API calls are made.

```
KnowledgeDashboardController::index()
  ├── entries        → paginated entry list with creator relationship
  ├── scopeBreakdown → grouped count per scope type (hive, apiary, agent)
  └── filters        → echo of current filter values { scope, search, sort }
```

## Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `scope` | string | (none) | Filter by scope type: `hive`, `apiary`, `agent` |
| `search` | string | (none) | Partial key/value search |
| `sort` | string | `updated_at` | Sort column: `updated_at`, `key`, `scope` |
| `page` | int | 1 | Pagination page number |

## Scope Visibility

In CE mode, all entries across the default apiary are visible. Expired entries
(past TTL) are excluded, consistent with the Knowledge Store API.

## Input Sanitization

Non-scalar query parameters (e.g., `?search[]=foo`) are silently rejected and
treated as if not provided. Invalid sort values fall back to `updated_at`.
Invalid scope values are ignored.
