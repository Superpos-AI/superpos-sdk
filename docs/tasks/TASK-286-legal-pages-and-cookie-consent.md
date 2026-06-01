---
name: TASK-286 legal pages + cookie consent
description: Real Privacy + Terms pages (replacing footer stubs), GDPR-compatible cookie consent banner, consent persistence, and analytics gating.
type: project
---

# TASK-286: Legal pages + cookie consent

**Status:** pending
**Branch:** `task/286-legal-pages-and-cookie-consent`
**PR:** —
**Depends on:** —
**Blocks:** Cloud public launch
**Edition:** shared (legal pages visible in CE + Cloud; cookie banner only on Cloud because CE has no analytics to gate)
**Feature doc:** this task.

## Objective

Footer currently links to stubs. Before public launch: ship real Privacy + Terms pages, a GDPR-compatible cookie consent banner, and a simple gate so any future analytics can only run post-consent.

## Requirements

### Functional

- [ ] FR-1: `resources/js/Pages/Marketing/Legal/Privacy.jsx` — full Privacy Policy, readable typography, matches MarketingLayout (borderless, airy). Section anchors with sticky table of contents on desktop.
- [ ] FR-2: `resources/js/Pages/Marketing/Legal/Terms.jsx` — full Terms of Service with same layout.
- [ ] FR-3: Routes — `/privacy` and `/terms` render the pages. Both public. Retire the `coming soon` stub from TASK-280.
- [ ] FR-4: **Placeholder copy, not final legalese.** Ship the draft content from the **Content** section below. Add a prominent banner at the top of each page (dev-only via env, OR a comment in the source) saying "REVIEW BY COUNSEL BEFORE PUBLIC LAUNCH". The operator is expected to replace the copy with counsel-approved text before going live.
- [ ] FR-5: Cookie consent banner on Cloud only (`config('platform.is_cloud')`). Renders on first visit. Three buttons: **Accept all**, **Reject all**, **Manage**. "Manage" opens a modal with toggles for Essential (always on, disabled), Analytics, Marketing.
- [ ] FR-6: Consent persisted in `localStorage` as `cookieConsent: {version: 1, acceptedAt: ISO, categories: {essential: true, analytics: bool, marketing: bool}}`. Version bump re-prompts.
- [ ] FR-7: No analytics or tracking script fires pre-consent. Wire a simple `window.hasConsent('analytics')` gate that anything future checks before firing. No analytics vendor is wired in this task — just the gate.
- [ ] FR-8: Consent record — each first-time consent also POSTs to `/api/consent` which appends to `activity_log` with action `user.consent_recorded` and the chosen categories. Anonymous visitors (no session) record to a `cookie_consents` table keyed on a random UUID stored in the same localStorage blob.
- [ ] FR-9: Banner dismiss without choice — if the user closes the banner without clicking, treat as "Reject all" (GDPR default). Banner re-shows next visit until a choice is made.
- [ ] FR-10: Footer links updated — `Privacy` and `Terms` point to the new routes; add `Cookie preferences` link that re-opens the banner on click.

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean.
- [ ] NFR-2: Pages render server-side via Inertia — full SEO-indexable HTML, no blank-until-hydration.
- [ ] NFR-3: Banner does NOT block the page — rendered as a bottom sheet, non-modal, keyboard-accessible.
- [ ] NFR-4: `cookieConsent` localStorage key version `1` — if we bump schema later, versioning re-prompts cleanly.
- [ ] NFR-5: All links have real `href`s including the legal-page anchors (no `href="#"` scroll-hijacks).

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Http/Controllers/LegalController.php` | Renders Privacy + Terms |
| Modify | `routes/web.php` | `/privacy`, `/terms`, `/api/consent` |
| Create | `resources/js/Pages/Marketing/Legal/Privacy.jsx` | Page |
| Create | `resources/js/Pages/Marketing/Legal/Terms.jsx` | Page |
| Create | `resources/js/Components/Legal/LegalPageLayout.jsx` | ToC + article shell |
| Create | `resources/js/Components/CookieConsent/Banner.jsx` | Bottom sheet |
| Create | `resources/js/Components/CookieConsent/Manager.jsx` | Preferences modal |
| Create | `resources/js/lib/consent.js` | `getConsent`, `setConsent`, `hasConsent(category)`, `showBanner()` |
| Modify | `resources/js/Layouts/MarketingLayout.jsx` | Mount Banner + replace footer stub links; add "Cookie preferences" link that calls `showBanner()` |
| Create | `app/Http/Controllers/ConsentController.php` | POST /api/consent |
| Create | `database/migrations/YYYY_MM_DD_HHMMSS_create_cookie_consents_table.php` | Anonymous consent records |
| Create | `tests/Feature/LegalPagesTest.php` | Routes render, content present |
| Create | `tests/Feature/ConsentRecordTest.php` | POST endpoint stores row / writes activity_log |
| Create | `resources/js/Components/CookieConsent/__tests__/Banner.test.jsx` | Render + button wiring |
| Create | `resources/js/Components/CookieConsent/__tests__/Manager.test.jsx` | Toggles + localStorage persistence |
| Create | `resources/js/lib/__tests__/consent.test.js` | hasConsent contract |

### Key Design Decisions

- **localStorage, not a cookie.** Ironic — but cookies for consent create a chicken-and-egg problem and localStorage doesn't count as tracking for GDPR purposes when used for the consent record itself.
- **Essential category is always true, toggle disabled.** Login session cookies, CSRF tokens, etc. — required for the app to function.
- **Close-without-choice = reject.** GDPR-compliant default.
- **Version bump re-prompts.** If policy changes categories, bumping `version` from 1 → 2 invalidates old consent and re-shows the banner.
- **Server-side consent log is informational.** Anonymous UUIDs in `cookie_consents`; authenticated users also record to `activity_log`. We're not aiming for audit-perfect proof of consent — that's a counsel question. We're aiming for "can we answer 'did this user consent?' in a support ticket."
- **Placeholder legal copy, clearly marked.** The engineer isn't a lawyer; ship structure + prose as a working draft; block launch on counsel review.

## Content — placeholder draft

Ship these verbatim as the page content. Mark **"DRAFT — REQUIRES LEGAL REVIEW"** as a callout at the top of each page (visible in dev, hidden in production via `config('app.env') === 'production'`).

### Privacy Policy (draft)

Sections (implementer writes reasonable 1-3 paragraph copy for each):

1. **Who we are** — Superpos provides an agent orchestration platform. This policy covers data we process as part of the hosted Cloud service.
2. **What we collect** — Account info (email, name), service data (agents, tasks, workflows you create), usage metrics, billing info (via Stripe — we never see card numbers), device/browser metadata, IP address.
3. **How we use it** — Providing the service, billing, product improvement, security / abuse detection, transactional emails.
4. **Sharing** — Stripe (billing), our email provider (transactional mail), infrastructure providers (hosting). No advertisers. No data brokers.
5. **Retention** — Active account data kept until deletion. Deleted accounts: logs retained 90 days for abuse investigation; billing records retained 7 years as required by tax law.
6. **Your rights** (GDPR / CCPA) — Access, deletion, portability, correction, objection. How to request: email privacy@superpos.ai.
7. **Cookies** — Essential cookies for login. Analytics / marketing cookies only with consent. See our cookie preferences.
8. **Children** — Service not intended for under 16.
9. **Changes** — We notify material changes via email + dashboard banner.
10. **Contact** — privacy@superpos.ai.

### Terms of Service (draft)

1. **Acceptance** — Using Superpos Cloud = accepting these terms.
2. **Service** — What Superpos provides; may evolve.
3. **Accounts** — Accurate info required; you're responsible for keeping credentials secure; one person / org per account.
4. **Acceptable use** — No malware, no spam, no abuse, no circumvention of rate limits, no illegal use, no running agents that violate third-party terms.
5. **Subscription & billing** — Monthly/annual plans billed in advance; auto-renew unless canceled; no refunds on partial periods; price changes with 30 days notice.
6. **Content & data** — You own your data; you grant us the license to host it for the purpose of providing the service; you represent you have the right to upload it.
7. **IP** — We own the platform; you own your configuration + your outputs.
8. **Termination** — Either side may terminate; we may suspend for terms violations or non-payment; on termination you have 30 days to export data.
9. **Warranties & disclaimers** — Service "as is"; no warranty of fitness for any particular purpose; no uptime guarantee outside written SLAs.
10. **Limitation of liability** — Our aggregate liability capped at fees paid in the prior 12 months.
11. **Indemnification** — You indemnify us for claims arising from your use.
12. **Governing law** — [placeholder — jurisdiction to be set by operator].
13. **Changes** — We may update terms; material changes notified 30 days in advance; continued use = acceptance.
14. **Contact** — legal@superpos.ai.

## Implementation Plan

1. Migration + ConsentController + legal controller + routes.
2. MarketingLayout update: mount Banner (Cloud-only), rewire footer.
3. Banner + Manager components + `consent.js` lib.
4. Draft Privacy + Terms pages with the content above. DRAFT callout at top.
5. Footer "Cookie preferences" link re-opens banner.
6. Tests.

## Test Plan

- [ ] `/privacy` renders with all 10 sections + DRAFT callout in non-production env
- [ ] `/terms` renders with all 14 sections + DRAFT callout in non-production env
- [ ] Banner shows on first visit to Cloud; does not show on CE
- [ ] "Accept all" sets `cookieConsent.categories.analytics = true` in localStorage + POSTs `/api/consent`
- [ ] "Reject all" sets both analytics and marketing to false
- [ ] "Manage" opens modal, toggling analytics saves, closing banner without choice = reject
- [ ] `window.hasConsent('analytics')` returns the stored value
- [ ] Footer "Cookie preferences" re-opens banner
- [ ] Version bump invalidates old consent (unit test on consent.js)
- [ ] Activity log records `user.consent_recorded` for authenticated users
- [ ] Anonymous user consent goes to `cookie_consents` table with a random UUID

## Validation Checklist

- [ ] All tests pass
- [ ] Pint clean
- [ ] DRAFT callout visible in dev, hidden in production
- [ ] Banner keyboard-accessible (tab order, Escape closes)
- [ ] No analytics vendor wired yet (just the gate)
- [ ] Footer links live, no 404s, no anchor-hijacks
- [ ] Cloud-only banner enforcement verified (CE build: banner hidden)

## Notes for Implementer

- The DRAFT callout must be prominently visible to the operator in any non-production env. Suggested: a yellow pill "DRAFT — REQUIRES LEGAL REVIEW" at the top of each page. Hide via `config('app.env') === 'production'` check.
- This task does NOT wire any actual analytics vendor (Plausible / PostHog / GA). Only the gate. A follow-up task can pick a vendor and respect `hasConsent('analytics')`.
- Sticky table of contents: use CSS `position: sticky` on desktop breakpoints, hide on mobile.
- The `cookie_consents` table is intentionally simple — `{id, consent_uuid, categories_json, ip_hash, user_agent, created_at}`. No FK to users; authenticated users' consent lives in activity_log.
