# TASK-287: Credit Balance System (Usage-Based Billing)

**Status:** pending
**Branch:** `task/287-credit-balance-system`
**PR:** —
**Depends on:** TASK-244 (usage collection), TASK-159 (Stripe billing)
**Blocks:** —
**Edition:** cloud
**Feature doc:** [`docs/proposals/credit-balance-system.md`](../proposals/credit-balance-system.md)

## Objective

Add a credit balance system so hosted agent compute can be billed by actual usage.
Plans grant monthly credits, compute deducts hourly based on replica size/count,
and users can top up via Stripe when they need more.

## Requirements

### Functional

- [ ] FR-1: Each tenant has a credit balance (available + lifetime counters)
- [ ] FR-2: Every credit movement is recorded in an immutable append-only ledger
- [ ] FR-3: Plan subscriptions grant monthly credits on period start (non-rolling)
- [ ] FR-4: Hosted agent compute deducts credits hourly based on usage samples (size × count × hours)
- [ ] FR-5: Credit rates per replica size are admin-configurable (default: xs=1, s=2, m=5, l=10 per hour)
- [ ] FR-6: Users can purchase credit top-up packs via Stripe one-time Checkout
- [ ] FR-7: Plan-granted credits expire at period end; purchased credits can be rolled over manually by email request (MVP)
- [ ] FR-8: Deploy, start, restart, scale, update (PATCH), env-update, and rollback are blocked when balance is zero; low-balance warning at < 24h of burn rate
- [ ] FR-9: Zero-balance triggers agent auto-stop after configurable grace period (default: 1 hour)
- [ ] FR-10: Dashboard shows credit balance widget (balance, burn rate, hours remaining)
- [ ] FR-11: Credit history page shows ledger with type filters and pagination
- [ ] FR-12: Admin can grant promotional/refund credits to any tenant

### Non-Functional

- [ ] NFR-1: Credit deductions are serialized per tenant (no double-spend under concurrent jobs)
- [ ] NFR-2: Ledger rows are immutable — corrections are new entries
- [ ] NFR-3: Stripe webhook top-up grants are idempotent (use `processed_stripe_events`)
- [ ] NFR-4: Activity logging on all admin credit actions
- [ ] NFR-5: Grace period before auto-stop prevents data loss from momentary zero balance

## Architecture & Design

### Files to Create

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/cloud/..._create_credit_balances_table.php` | Per-tenant balance row |
| Create | `database/migrations/cloud/..._create_credit_ledger_table.php` | Immutable transaction log |
| Create | `app/Cloud/Models/CreditBalance.php` | Balance model (1:1 with CloudTenant) |
| Create | `app/Cloud/Models/CreditLedgerEntry.php` | Ledger entry model |
| Create | `app/Cloud/Billing/CreditService.php` | Core credit operations |
| Create | `app/Cloud/Jobs/DeductHostedAgentCreditsJob.php` | Hourly compute billing |
| Create | `app/Cloud/Jobs/GrantMonthlyCreditJob.php` | Plan credit grant on period start |
| Create | `app/Cloud/Jobs/ExpirePlanCreditsJob.php` | Zero out expired plan grants |
| Create | `app/Cloud/Jobs/SuspendLowCreditAgentsJob.php` | Auto-stop after grace period |
| Create | `resources/js/Pages/Cloud/Billing/Credits.jsx` | Credit history page |
| Create | `resources/js/Components/Cloud/CreditBalanceWidget.jsx` | Dashboard balance widget |
| Create | `resources/js/Pages/Cloud/Admin/Credits/Index.jsx` | Admin credit management |

### Files to Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `config/plans.php` | Add `credits_per_month` to each plan |
| Modify | `config/stripe.php` | Add credit pack price IDs |
| Modify | `app/Cloud/Billing/BillingService.php` | Hook credit grant into subscription sync |
| Modify | `app/Cloud/Jobs/ProcessStripeWebhook.php` | Handle top-up `checkout.session.completed` + `customer.subscription.created` for trial grant. **Fork `handleCheckoutCompleted()` by session `mode`** — payment-mode (top-up) sessions must skip `SubscriptionStartedMail` and route to `CreditService::grant()` instead. |
| Modify | `app/Cloud/Http/Middleware/EnforceQuota.php` | Check credit balance for hosted agent deploy, start, restart, scale, update (PATCH), env-update, and rollback |
| Modify | `app/Cloud/Http/Controllers/BillingController.php` | Add top-up Checkout + credit history endpoints |
| Modify | `resources/js/Layouts/Cloud/AdminLayout.jsx` | Add Credits admin nav entry |
| Modify | `routes/api.php` | Apply credit balance gate to hosted agent `store`, `start`, `restart`, `scale`, `update` (PATCH), and `rollback` API routes |
| Modify | `routes/auth.php` | Credit history + top-up routes (under `cloud/{tenant}/billing`) |
| Modify | `routes/web.php` | **Two changes:** (1) Apply `CheckCreditBalance` middleware to hosted-agent dashboard write routes — `store`, `start`, `restart`, `env-update`, and `rollback` (lines 322-326 in the `apiary.hosted.enabled` group). These are the dashboard equivalents of the API routes gated in `routes/api.php` and are required for FR-8. (2) Admin credit management routes (under `admin/`). |
| Modify | `bootstrap/app.php` | Schedule hourly deduction + expiry jobs (via `->withSchedule()`) |

### Key Design Decisions

- **Separate balance table** (not a column on `cloud_tenants`). Keeps billing concerns isolated; `lockForUpdate()` on balance doesn't block tenant reads.
- **Immutable ledger + denormalized balance**. Ledger is the audit source of truth; balance is a materialized view for fast reads. Both update in a single transaction.
- **Hourly deductions** (not per-sample). Matches the existing sampler cadence (5 min) but avoids noisy ledger entries. Cost is aggregated from samples in the hour window.
- **Plan grants don't roll over**. Prevents credit hoarding and aligns with subscription periods. Purchased top-ups can be rolled over manually by email request (MVP) — no automatic rollover. Self-service rollover may be added post-MVP.
- **Reuse existing `hosted_agent_usage_samples`**. No new data collection — the sampler (TASK-244) already records what we need. Credits are a billing layer on top.
- **Plan-credits-first consumption ordering**. `deduct()` consumes plan-grant credits (soonest-expiring first) before purchased credits. Per-grant `remaining_balance` tracking enables `processExpiredCredits()` to expire only unconsumed plan credits without touching top-ups.
- **Dual webhook grant path**. `customer.subscription.created` handles initial grant for trialing subscriptions; `invoice.payment_succeeded` handles renewals. Both deduplicated by `(tenant_id, billing_period_start)`.

## Implementation Plan

1. **PR 1 (S)**: Migrations + models for `credit_balances` and `credit_ledger`
2. **PR 2 (M)**: `CreditService` — grant, deduct, getBalance, hasEnough, estimateHourlyCost
3. **PR 3 (M)**: `DeductHostedAgentCreditsJob` — hourly compute billing from usage samples
4. **PR 4 (S)**: Plan grants — hook into `customer.subscription.created` (trial) + `invoice.payment_succeeded` (renewal) webhooks, monthly grant, expiry job
5. **PR 5 (M)**: Stripe top-up — credit packs, Checkout, webhook handler. **Must fork `handleCheckoutCompleted()` by session `mode`** to separate payment-mode top-ups from subscription sessions (prevents false `SubscriptionStartedMail`).
6. **PR 6 (M)**: Frontend — balance widget, credit history, top-up flow, deploy gate
7. **PR 7 (S)**: Admin credit management page
8. **PR 8 (S)**: Backfill — grant initial credits to existing tenants

## Database Changes

See proposal Part C for full schema. Key tables:

```sql
-- Per-tenant running balance
CREATE TABLE credit_balances (
    cloud_tenant_id  VARCHAR(26) PRIMARY KEY REFERENCES cloud_tenants(id),
    available        INTEGER NOT NULL DEFAULT 0,
    reserved         INTEGER NOT NULL DEFAULT 0,
    lifetime_granted INTEGER NOT NULL DEFAULT 0,
    lifetime_spent   INTEGER NOT NULL DEFAULT 0,
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Immutable audit ledger
CREATE TABLE credit_ledger (
    id               VARCHAR(26) PRIMARY KEY,  -- ULID
    cloud_tenant_id  VARCHAR(26) NOT NULL REFERENCES cloud_tenants(id),
    amount           INTEGER NOT NULL,          -- +credit / -debit
    balance_after    INTEGER NOT NULL,
    type             VARCHAR(30) NOT NULL,      -- plan_grant|top_up|promo|refund|compute_deduction|expiry
    description      VARCHAR(255),
    reference_type   VARCHAR(50),
    reference_id     VARCHAR(255),
    metadata         JSONB,
    expires_at       TIMESTAMP,
    remaining_balance INTEGER,                  -- per-grant lot tracking (NULL for debits, initialized to amount for credits)
    created_at       TIMESTAMP NOT NULL DEFAULT NOW()
);
```

## API Changes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/cloud/{tenant}/billing/credits` | Credit history page (Inertia) |
| GET | `/cloud/{tenant}/billing/credits/balance` | JSON balance + burn rate |
| POST | `/cloud/{tenant}/billing/credits/top-up` | Create Stripe Checkout for credit pack |
| GET | `/admin/credits` | Admin credit management (Inertia) |
| POST | `/admin/credits/{tenant}/grant` | Admin grant credits |

## Test Plan

### Unit Tests

- [ ] CreditService::grant increases balance and creates ledger entry with remaining_balance initialized
- [ ] CreditService::deduct decreases balance, clamps at zero
- [ ] CreditService::deduct under concurrent calls doesn't double-spend (lockForUpdate)
- [ ] CreditService::deduct consumes plan-grant credits before purchased credits (plan-credits-first ordering)
- [ ] CreditService::deduct decrements remaining_balance on consumed grant rows in correct order
- [ ] CreditService::deduct with mixed balance (plan + top-up) only touches top-up after plan grants exhausted
- [ ] CreditService::hasEnough returns false when balance < requested
- [ ] Plan grant calculates correct amount from config
- [ ] Expired plan credits are zeroed (remaining_balance → 0); purchased credits survive only via manual rollover request
- [ ] processExpiredCredits only expires grant rows where remaining_balance > 0 and expires_at <= now

### Feature Tests

- [ ] Hourly deduction job reads usage samples and deducts correct credits
- [ ] Zero-balance blocks new hosted agent deploy via API (422)
- [ ] Zero-balance blocks new hosted agent deploy via dashboard `store` route (422)
- [ ] Zero-balance blocks hosted agent start via API (422)
- [ ] Zero-balance blocks hosted agent start via dashboard route (422)
- [ ] Zero-balance blocks hosted agent restart via API (422)
- [ ] Zero-balance blocks hosted agent restart via dashboard route (422)
- [ ] Zero-balance blocks hosted agent scale via API (422)
- [ ] Zero-balance blocks hosted agent update (PATCH mutable fields triggering redeploy) via API (422)
- [ ] Zero-balance blocks hosted agent env-update via dashboard route (422)
- [ ] Zero-balance blocks hosted agent rollback via API (422)
- [ ] Zero-balance blocks hosted agent rollback via dashboard route (422)
- [ ] Top-up webhook grants credits idempotently
- [ ] Top-up checkout session (`mode: 'payment'`) does NOT trigger `SubscriptionStartedMail`
- [ ] Subscription checkout session (`mode: 'subscription'`) still triggers `SubscriptionStartedMail`
- [ ] Period rollover grants new credits and expires old plan grants
- [ ] Admin grant creates ledger entry with correct type
- [ ] Credit history page shows filtered ledger entries
- [ ] Trial subscription (`customer.subscription.created` with status=trialing) grants plan credits immediately
- [ ] Trial grant expires_at is set to trial end date
- [ ] Trial grant + first invoice grant are deduplicated (same period = one grant)
- [ ] Non-trial subscription (`trial_days=0`) grants credits via `invoice.payment_succeeded` on first invoice

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on admin credit actions
- [ ] API responses use `{ data, meta, errors }` envelope
- [ ] Form Request validation on all inputs
- [ ] ULIDs for primary keys
- [ ] No credentials logged in plaintext
- [ ] Stripe webhook idempotency via `processed_stripe_events`
