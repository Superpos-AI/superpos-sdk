# TASK-116: Dashboard Authentication (Laravel Breeze)

**Status:** in-progress
**Branch:** `task/116-dashboard-auth`
**PR:** —
**Depends on:** TASK-022, TASK-023
**Blocks:** —

## Objective

Add human-user authentication to the web dashboard using Laravel Breeze (Inertia/React stack). All `/dashboard/*` routes require login; the `/` landing page remains public but redirects authenticated users to `/dashboard`.

## Requirements

### Functional

- [x] FR-1: Install Laravel Breeze with React/Inertia scaffold
- [x] FR-2: Protect all `/dashboard/*` routes with `auth` middleware
- [x] FR-3: Keep `/` public; redirect authenticated users to `/dashboard`
- [x] FR-4: User dropdown in AppLayout with Profile link and Logout
- [x] FR-5: Profile page (edit name/email, change password, delete account)
- [x] FR-6: Auth pages (login, register, forgot/reset password) styled to dark Superpos theme
- [x] FR-7: All existing dashboard tests updated with `actingAs()`

### Non-Functional

- [x] NFR-1: No email verification required (can be enabled later)
- [x] NFR-2: Auth pages use GuestLayout; dashboard pages use AppLayout
- [x] NFR-3: Breeze's AuthenticatedLayout deleted (not needed)

## Architecture & Design

### Files Created

| Path | Purpose |
|------|---------|
| `app/Http/Controllers/Auth/*` | Breeze auth controllers (9 files) |
| `app/Http/Controllers/ProfileController.php` | Profile CRUD |
| `app/Http/Requests/Auth/LoginRequest.php` | Login validation |
| `app/Http/Requests/ProfileUpdateRequest.php` | Profile validation |
| `routes/auth.php` | Auth route definitions |
| `resources/js/Pages/Auth/*.jsx` | Login, Register, ForgotPassword, ResetPassword, VerifyEmail, ConfirmPassword |
| `resources/js/Pages/Profile/**/*.jsx` | Profile edit + partials |
| `resources/js/Components/*.jsx` | Breeze UI components (TextInput, InputError, etc.) |
| `resources/js/Layouts/GuestLayout.jsx` | Auth page layout (dark themed) |
| `tests/Feature/Auth/*.php` | Breeze auth tests |
| `tests/Feature/ProfileTest.php` | Profile tests |

### Files Modified

| Path | Change |
|------|--------|
| `app/Http/Middleware/HandleInertiaRequests.php` | Added `auth.user` to shared props |
| `bootstrap/app.php` | Added `AddLinkHeadersForPreloadedAssets` middleware |
| `routes/web.php` | Wrapped dashboard in `auth` middleware; added profile routes; require auth.php |
| `app/Http/Controllers/Dashboard/IndexController.php` | Redirect authenticated users to dashboard |
| `resources/js/Layouts/AppLayout.jsx` | Added user dropdown menu |
| `resources/views/app.blade.php` | Added `@routes` for Ziggy |
| `composer.json` | Added `laravel/breeze`, `tightenco/ziggy` |
| `package.json` | Added `@headlessui/react` |
| `tests/Feature/Dashboard/*.php` (6 files) | Added `actingAs()` in setUp |
| `tests/Feature/WelcomePageTest.php` | Added `actingAs()` to dashboard test; new auth redirect tests |

## Verification

```bash
docker compose exec app php artisan test
```

1. Visit `/` — landing page (guest)
2. Visit `/dashboard` — redirects to `/login`
3. Register → redirects to `/dashboard`
4. User dropdown → Profile, Logout
5. Logout → returns to `/login`
6. Login → returns to `/dashboard`
