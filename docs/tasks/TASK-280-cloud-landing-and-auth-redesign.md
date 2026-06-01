---
name: TASK-280 cloud landing page + auth redesign
description: Build the public marketing landing page at / and restyle Login/Register to match the new airy, storytelling-first tone. No new backend — flip the root route and add copy/motion.
type: project
---

# TASK-280: Cloud landing page + auth redesign

**Status:** pending
**Branch:** `task/280-cloud-landing-and-auth-redesign`
**PR:** —
**Depends on:** — (all existing; uses shipped Breeze auth)
**Blocks:** Cloud production launch
**Edition:** shared (landing is visible in CE and Cloud; "Sign up" CTA is gated to Cloud — see FR-4)
**Feature doc:** none yet — this task is the feature doc.

## Objective

Cloud edition is moving to production. There is no public marketing page — `/` is an auth-gated dashboard. Ship a public landing page at `/` that tells the Superpos story and restyle the existing Breeze Login / Register pages to match the new tone (airy, minimal, borderless, content floats). No new backend. No waitlist. No team section.

## Background

- `/` is currently `IndexController` → `Pages/Index.jsx` (authenticated dashboard).
- Auth pages exist (`Pages/Auth/Login.jsx`, `Pages/Auth/Register.jsx`) using `GuestLayout` + Breeze controllers.
- Brand assets live in `public/images/brand/`. Tailwind tokens in `resources/css/app.css` (oklch primary, dark-mode parity).
- The investor deck (internal doc, not for the site) carries the canonical problem/solution language. **Do not port pricing, MRR projections, funding asks, or any investor-facing financials.** This is a product site.

## Design Philosophy (non-negotiable)

From the product brief:

- **Storytelling over utility.** No "B2B SaaS template" tropes — no stat-grids of logos, no row-of-three-benefits. Content should make a visitor *think*, not skim.
- **Breathable layout.** No borders, no hard dividers, no unnecessary chrome. Content floats on generous whitespace.
- **Prototype in code.** Motion and interactivity that *drive the narrative* — not decoration. Animate the transformation, not the header.
- **Minimal hero with no CTA.** The hero sells the idea; the CTA lives at the bottom after the story lands.

## Scope

### Public landing page at `/`

Four sections (team section intentionally dropped):

1. **Hero — the hook**
   - Copy: "The operational environment for agentic systems." + "One agent is an API call. A system of agents is Superpos."
   - No CTA button.
   - Minimal top nav: logo left; `Docs` / `GitHub` / `Log in` right. Nav blends into page — no bar, no border.
   - Subtle animation: either the tagline's key words (`system`, `agents`, `Superpos`) fade in sequentially, or a faint animated diagram of nodes/edges in the background. Pick one — do not do both.

2. **Transformation — before / after**
   - "This could be me" framed for the developer audience: *your stack today* vs. *your stack on Superpos*.
   - Left (before): five labeled boxes glued with messy lines — Inngest (workflows) + E2B (sandboxes) + Supabase (state) + Railway (hosting) + "custom glue". Framed as "you own the maintenance."
   - Right (after): one Superpos box with the same six concerns listed inside (lifecycle · orchestration · state · governance · compute · any model).
   - Animate the morph on scroll: the five boxes slide in, then collapse together into the Superpos box as the user scrolls past. Use `framer-motion` (already plausible in the stack — check `package.json`; if absent, add).
   - Caption: "Big tech built this internally with teams of 15–20 engineers over a year. You shouldn't have to."

3. **Social proof — dogfood**
   - Header: "Superpos is built using Superpos."
   - Three short beats side-by-side (no card borders, floating text):
     - "Agents review our pull requests."
     - "Agents run our tests."
     - "Agents ship our code."
   - Hover on each beat reveals a real artifact screenshot — e.g. a GitHub PR comment from a Superpos agent, a test-run log snippet, a deploy event. Use placeholder assets (`public/images/landing/proof-*.png`) committed as stubs; real captures can land in a follow-up.
   - No customer logos. No fake quotes. If we add real quotes later, they go here.

4. **Final CTA — combat hesitation**
   - Headline copy: **"You don't need a platform team to run agents in production."**
     - Chosen for concreteness — names the barrier (platform team) and dismisses it. No abstraction, no cutesy riff.
     - Sub-line below (smaller, supporting): "Superpos is the platform. Start today."
   - Primary button: `Start building →` linking to `route('register')`.
   - Secondary link (plain text, no button chrome): `Or run it yourself — docker compose up` linking to the CE README on GitHub.
   - Minimal footer below: `© Superpos {year}` · `GitHub` · `Docs` · `Privacy`. Borderless.

### Routing changes

- `/` → new public controller `MarketingLandingController@show` rendering `Pages/Marketing/Landing.jsx`.
  - If the request is authenticated, **redirect to `/dashboard`** (new route) instead of rendering the landing page.
- `/dashboard` → rename the current `IndexController` mount. Existing authenticated users and all internal dashboard links that used `route('home')` continue to work — add a `dashboard` route name alias and update `route('home')` callers in the JSX codebase (grep first; it's widely used).
- Login / Register routes (`/login`, `/register`) unchanged at the URL level. Only visual redesign.

### Auth redesign

- **Login.jsx** and **Register.jsx**: keep the existing forms + Breeze controller wiring. Restyle only:
  - Remove the card, the border, the shadow. Form floats on the page — same feeling as the landing.
  - Left-align everything. Large typography on the heading ("Welcome back." / "Start building with Superpos.").
  - Inputs: underline-style or ghost-border, no filled boxes. Match Tailwind tokens already defined.
  - Retain all existing fields, validation messaging, OAuth buttons (Google / GitHub — `routes/auth.php:38-48`).
  - Dark-mode parity must not regress.
  - Add a subtle link back to `/` in the top-left (logo mark only, no text).

### Nav / footer

- Reused across the landing, auth pages, and any future marketing routes.
- Extract as `resources/js/Layouts/MarketingLayout.jsx` with `<Header />` and `<Footer />` sub-components.
- `GuestLayout.jsx` (currently wrapping auth) should either extend `MarketingLayout` or be replaced by it — pick the cleaner option; don't duplicate chrome.

## Requirements

### Functional

- [ ] FR-1: `GET /` renders `Pages/Marketing/Landing.jsx` for guests; redirects to `/dashboard` for authenticated users.
- [ ] FR-2: `/dashboard` renders what `/` used to render. All internal `route('home')` references updated or aliased so no dashboard link breaks.
- [ ] FR-3: Landing page contains the four sections above in order, matches the design philosophy (no borders, airy spacing), and uses the exact hero + transformation copy from the spec.
- [ ] FR-4: CTA "Start building" links to `route('register')`. If `config('platform.is_cloud')` is false, the "Start building" button is suppressed (CE users already running it self-hosted don't need a signup) and the secondary `docker compose up` link becomes primary.
- [ ] FR-5: Login and Register pages restyled per the spec — no card, no filled-box inputs, left-aligned large typography. Forms still submit to existing Breeze endpoints. OAuth buttons retained.
- [ ] FR-6: Transformation section animates on scroll — stack-of-five-services morphs into the Superpos box. Works on mobile (can degrade to a static side-by-side if animation would thrash small screens).
- [ ] FR-7: Social-proof hover reveals placeholder artifact images. Stub assets committed at `public/images/landing/proof-{prs,tests,ships}.png` (1× 16:9 each). Swapping real captures later is a content-only change.
- [ ] FR-8: Responsive — landing works down to 375px width. No horizontal scroll at any breakpoint.
- [ ] FR-9: Dark-mode parity — every section renders correctly in both themes using existing `--primary` / `--background` tokens.

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean on backend changes.
- [ ] NFR-2: Lighthouse Performance ≥ 85 on the landing page (no heavy above-the-fold images; motion uses `framer-motion` with `whileInView` so off-screen sections are idle).
- [ ] NFR-3: No new PHP dependencies. If `framer-motion` is not yet in `package.json`, add it (one npm dep, acceptable).
- [ ] NFR-4: No tracking scripts, no analytics, no third-party embeds in this task. Analytics lands in a follow-up if/when product decides the vendor.
- [ ] NFR-5: CE/Cloud parity for the landing itself — it renders identically in both editions. Only the CTA wiring differs per FR-4.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Http/Controllers/MarketingLandingController.php` | Public landing controller |
| Modify | `routes/web.php` | `/` → landing (guest) or redirect to /dashboard (auth); `/dashboard` → old IndexController |
| Modify | `app/Http/Controllers/Dashboard/IndexController.php` | Route name updated if it was `home`; behavior unchanged |
| Create | `resources/js/Pages/Marketing/Landing.jsx` | Landing page |
| Create | `resources/js/Pages/Marketing/sections/Hero.jsx` | Section 1 |
| Create | `resources/js/Pages/Marketing/sections/Transformation.jsx` | Section 2 (framer-motion) |
| Create | `resources/js/Pages/Marketing/sections/SocialProof.jsx` | Section 3 |
| Create | `resources/js/Pages/Marketing/sections/FinalCta.jsx` | Section 4 |
| Create | `resources/js/Layouts/MarketingLayout.jsx` | Header + Footer + `<main>` |
| Modify | `resources/js/Layouts/GuestLayout.jsx` | Replace card chrome with MarketingLayout, or delete if redundant |
| Modify | `resources/js/Pages/Auth/Login.jsx` | Visual redesign, same form logic |
| Modify | `resources/js/Pages/Auth/Register.jsx` | Visual redesign, same form logic |
| Modify | `resources/js/app.jsx` or wherever `route('home')` is imported | Update dashboard link references |
| Create | `public/images/landing/proof-prs.png` | Stub (can be a simple placeholder for now) |
| Create | `public/images/landing/proof-tests.png` | Stub |
| Create | `public/images/landing/proof-ships.png` | Stub |
| Modify | `package.json` | Add `framer-motion` if missing |
| Create | `tests/Feature/MarketingLandingTest.php` | Route + auth-redirect tests |
| Create | `resources/js/Pages/Marketing/__tests__/Landing.test.jsx` | Render + section presence |
| Create | `resources/js/Pages/Auth/__tests__/Login.test.jsx` (if absent) | Render smoke test after restyle |

### Key Design Decisions

- **No waitlist.** Cloud is going to production — signup is the CTA. Waitlist would be a false step.
- **No team section.** Defer until founder photos and bios are ready; a placeholder section would violate the "no faces means no faces, not stock photos" principle.
- **No customer logos, no fake quotes.** Dogfood proof is the honest story right now. Real quotes land as a content update later.
- **Dashboard moves, landing takes `/`.** Every marketing convention expects `/` to be public. Auth users land on `/dashboard` — one redirect, no flicker.
- **Four sections, not five.** Cleaner. Each section does one narrative job.
- **One motion library.** `framer-motion` for scroll-morph + hover reveals. No GSAP, no Lottie, no other libs.
- **Reuse `MarketingLayout` for auth pages.** The auth redesign isn't a separate aesthetic — it's the landing's chrome with a form inside.

## Implementation Plan

1. **Routing flip** — add the new controller, add `/dashboard`, update `/`, alias `home` → `dashboard` route name, grep the JSX codebase for `route('home')` and update. Verify existing dashboard tests still pass.
2. **MarketingLayout** — build Header + Footer. Borderless. Logo + three links.
3. **Landing sections** — Hero first (static, no motion). Then Transformation (framer-motion scroll). Then Social Proof (hover reveals). Then Final CTA.
4. **Auth restyle** — Login + Register. Remove card chrome. Left-align. Ghost inputs. Retain every form behavior.
5. **Tests** — backend route test (auth-redirect), JSX render tests for landing sections and auth pages.
6. **Lighthouse pass** — run against a local build; confirm ≥ 85 Performance; tune image sizes / defer anything under the fold.

## Test Plan

### Feature Tests
- [ ] `GET /` as guest renders `Marketing/Landing` Inertia page
- [ ] `GET /` as authenticated user redirects (302) to `/dashboard`
- [ ] `GET /dashboard` renders the old Index page (authenticated)
- [ ] `GET /login`, `/register` still render (no regression in Breeze flow)
- [ ] CTA target differs by edition: in CE build, `Start building` is hidden or replaced (per FR-4)

### JSX Tests
- [ ] Landing renders Hero / Transformation / SocialProof / FinalCta in order
- [ ] Hero contains the exact tagline copy
- [ ] Final CTA's primary button links to `/register`
- [ ] Social proof renders three beats and reveals the image on hover (simulated via test-id + hover event)
- [ ] Login / Register render all form fields after restyle (smoke test — no regression)

## Open Content Decisions (implementer picks and documents in PR)

- **Hero motion** — word-by-word fade vs. faint background node-graph. Pick one. If the background graph would pull focus from the tagline, don't do it.
- **Footer links** — `Privacy` page may not exist yet. If so, link to a stub page that says "coming soon" rather than a 404.

## Validation Checklist

- [ ] All tests pass
- [ ] Pint clean on backend
- [ ] Lighthouse ≥ 85 on landing (mobile + desktop)
- [ ] Dark-mode parity verified
- [ ] Responsive at 375px / 768px / 1280px
- [ ] No references to pricing, funding, MRR, or investor-deck content
- [ ] Authenticated users never see the landing at `/`
- [ ] Every existing dashboard link still works after the route rename
