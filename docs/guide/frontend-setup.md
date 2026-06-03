# Frontend Setup (Inertia.js + React)

Superpos's dashboard is built with [Inertia.js](https://inertiajs.com/) and
[React](https://react.dev/), served through Laravel's Blade template engine.
This guide covers the frontend architecture and how to add new dashboard pages.

## Stack

| Layer | Technology |
|-------|-----------|
| Server adapter | `inertiajs/inertia-laravel` v2 |
| Client adapter | `@inertiajs/react` |
| UI framework | React 19 |
| Build tool | Vite 7 with `@vitejs/plugin-react` |
| CSS | Tailwind CSS 4 via `@tailwindcss/vite` |

## Architecture

```
Browser request
  → Laravel route (routes/web.php)
    → Controller returns Inertia::render('PageName', [...props])
      → HandleInertiaRequests middleware merges shared props
        → Blade template (resources/views/app.blade.php) boots React
          → React renders resources/js/Pages/PageName.jsx
```

On subsequent navigations Inertia makes XHR requests and swaps the page
component without a full reload.

## Directory Layout

```
resources/
├── css/
│   └── app.css          ← Tailwind entry (scans .blade.php, .js, .jsx)
├── js/
│   ├── app.jsx          ← Inertia/React entry point
│   ├── bootstrap.js     ← Axios defaults
│   ├── Layouts/
│   │   └── AppLayout.jsx  ← Shared sidebar + header layout
│   └── Pages/
│       └── Dashboard.jsx  ← Dashboard home page
└── views/
    └── app.blade.php     ← Inertia root template
```

## Shared Props

The `HandleInertiaRequests` middleware (`app/Http/Middleware/HandleInertiaRequests.php`)
shares these props on every Inertia response:

| Prop | Type | Description |
|------|------|-------------|
| `apiary.name` | string | Current apiary name |
| `apiary.edition` | string | `"ce"` or `"cloud"` |
| `hive.id` | string | Current hive ULID |
| `hive.name` | string | Current hive display name |

Access them in any component with `usePage().props`.

## Adding a New Page

1. **Create the controller method** — return `Inertia::render('Folder/PageName', [...])`.
2. **Add the route** — in `routes/web.php` under the `dashboard` prefix.
3. **Create the React component** — `resources/js/Pages/Folder/PageName.jsx`.
4. **Use AppLayout** — wrap your page content with `<AppLayout>`.

Example:

```php
// app/Http/Controllers/Dashboard/AgentController.php
public function index(): Response
{
    return Inertia::render('Agents/Index', [
        'agents' => Agent::all(),
    ]);
}
```

```jsx
// resources/js/Pages/Agents/Index.jsx
import { Head } from '@inertiajs/react';
import AppLayout from '../../Layouts/AppLayout';

export default function AgentsIndex({ agents }) {
    return (
        <AppLayout>
            <Head title="Agents" />
            {/* ... */}
        </AppLayout>
    );
}
```

## Development

```bash
npm run dev    # Start Vite dev server with HMR
npm run build  # Production build to public/build/
```

The Vite dev server provides hot module replacement for React components.
The Laravel Vite plugin handles asset versioning in production.

## AppLayout

The shared `AppLayout` component provides:

- **Sidebar** — navigation links (Dashboard, Agents, Tasks, Knowledge, Activity)
- **Hive indicator** — shows the current hive name
- **Top bar** — apiary name, responsive hamburger menu
- **Edition badge** — "Community Edition" or "Cloud"
- **Dark theme** — slate/navy palette matching the landing page

The sidebar is responsive: full width on desktop (`lg:pl-64`), collapsible
overlay on mobile.
