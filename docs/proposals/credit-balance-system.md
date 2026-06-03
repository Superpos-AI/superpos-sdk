# Proposal: Credit Balance System (Usage-Based Billing)

**Task:** TASK-287
**Authoritative spec:** [`docs/tasks/TASK-287-credit-balance-system.md`](../tasks/TASK-287-credit-balance-system.md)
**Status:** design / RFC
**Edition:** cloud-only

---

## Part A — Motivation & Current State

### What exists today

Superpos Cloud uses **subscription-based billing** (Phase 6 — tasks 159-164):

- Three plans: Free ($0), Pro ($49/mo), Enterprise (custom)
- Hard caps per billing period: tasks/month, proxy calls/month, hives, members, API keys
- Usage tracked in `usage_records` table, enforced by `EnforceQuota` middleware
- Stripe handles subscriptions, trials, invoices, billing portal
- `HostedAgentUsageSampler` (TASK-244) already collects per-agent replica size/count every 5 minutes into `hosted_agent_usage_samples`

### The gap

Hosted agents consume **real compute resources** (NoVPS containers) whose cost scales
with replica size and uptime hours. The current flat-tier model cannot express this:

- A Free user running an `l` replica 24/7 costs the platform ~$X/month but pays $0
- A Pro user running 10 `xs` agents pays the same as one running 1 `l` agent
- There's no mechanism for pay-as-you-go beyond plan limits
- No top-up path for users who hit limits mid-cycle

A **credit balance** solves all four: plans grant monthly credits, compute deducts from
the balance based on actual usage, and users can top up when they need more.

### Why credits (not metered Stripe billing)

Stripe has native metered billing (`usage_record` line items) but it's invoice-at-end —
the user sees a surprise bill after the fact. Credits are **prepaid and visible**:

- Users see their balance before deploying — no bill shock
- Platform can **prevent** over-consumption in real time (hard cutoff or warning)
- Simpler mental model: "I have 50 credits ($50), an XS agent costs 1 credit/hour"
- Easier to offer promotional credits, referral bonuses, support credits
- Stripe one-time payments for top-ups are simpler than metered subscriptions

---

## Part B — Credit Model Design

### B.1 — Credit unit

**1 credit = $1.** This keeps pricing transparent — users always know the dollar cost
of their usage. One XS replica-hour costs 1 credit ($1). Larger sizes cost more per hour:

| Size | Credits / hour | Rationale |
|------|---------------|-----------|
| `xs` | 1             | Base unit |
| `s`  | 2             | ~2x compute |
| `m`  | 5             | ~5x compute |
| `l`  | 10            | ~10x compute |

These rates are **admin-configurable** in `config/plans.php` (not hardcoded) so
pricing can evolve without a code change.

Multiple replicas multiply: an `m` agent with `replicas_count: 2` costs 10 credits/hour.

### B.2 — Credit sources

| Source | Trigger | Rollover? |
|--------|---------|-----------|
| **Plan grant** | Subscription period start — see B.2a below for the two grant paths. Deduplicated by `tenant_id + billing_period_start` — a second webhook for the same period is a no-op. Free plan (0 credits) skips grant entirely. | No — unused credits expire at period end |
| **Top-up** | One-time Stripe Checkout (user action) | Manual rollover by email request (MVP) — no automatic rollover |
| **Promotional** | Admin action or coupon | Configurable per grant |
| **Refund** | Admin action (support credit) | Manual rollover by email request (MVP) |

> **Rollover policy (MVP):** Plan grants never roll over. Purchased credits (top-ups, refunds) can
> be rolled over to the next period **manually by email request** to support. Automatic rollover
> is out of scope for MVP and may be added later.

#### B.2a — Plan grant trigger paths

The live checkout flow creates subscriptions with a trial period by default
(`config/stripe.php` → `trial_days = 14`, applied in `BillingService::createCheckoutSession`).
Trialing subscriptions are treated as active (`CloudTenant::hasActiveSubscription` returns true
for `trialing` status), so users can deploy hosted agents immediately — but no invoice fires
until the trial ends.

To avoid a gap where a trialing tenant has active-subscriber access but 0 credits:

| Scenario | Webhook trigger | Action |
|----------|----------------|--------|
| **New subscription with trial** | `customer.subscription.created` (status = `trialing`) | Grant plan credits for the first period. `expires_at` = trial end date (= first invoice date). |
| **Trial converts to paid** | `invoice.payment_succeeded` (first real invoice) | Grant plan credits for the new billing period. Normal monthly grant path — deduplicated by `(tenant_id, billing_period_start)`. |
| **Subscription renewal** (no trial) | `invoice.payment_succeeded` | Same monthly grant path. |
| **Direct subscribe without trial** (`trial_days = 0`) | `invoice.payment_succeeded` | First invoice fires immediately; normal grant path handles it. No special handling needed. |

The `GrantMonthlyCreditJob` must therefore listen to **both** `customer.subscription.created`
(for the trial grant) and `invoice.payment_succeeded` (for all subsequent grants). Both paths
use the same `(tenant_id, billing_period_start)` deduplication, so overlapping events are safe.

### B.3 — Plan credit grants

| Plan | Credits / month | Equivalent runtime |
|------|----------------|-------------------|
| Free | 0 | — |
| Pro | 5,000 | ~7 months of 1 XS agent, or ~1 month of 1 M agent |
| Enterprise | configurable (default: unlimited) | — |

These go in `config/plans.php` under `limits.credits_per_month`.

### B.4 — Credit consumption

Credits are deducted **hourly** by a scheduled job (`DeductHostedAgentCreditsJob`)
that reads the latest `hosted_agent_usage_samples` and computes the cost:

```
cost = replica_count * credit_rate[replica_size] * hours_since_last_deduction
```

The sampler already runs every 5 minutes. The deduction job runs hourly and aggregates
the samples in the window. Using samples (not desired state) means we bill for actual
running replicas, not what was requested — if NoVPS is down, no billing.

### B.4a — Consumption ordering and per-grant tracking

Plan-granted credits expire at period end, while purchased credits (top-ups) survive.
To ensure `deduct()` and `processExpiredCredits()` can correctly determine how much of a
mixed balance is plan-grant vs purchased, the system uses **per-grant remaining-balance
tracking** with a **plan-credits-first** (FIFO within category) consumption order.

**Schema addition — `remaining_balance` on credit grants:**

Each positive ledger entry (grants only — `plan_grant`, `top_up`, `promo`, `refund`) carries
a `remaining_balance` column tracking how much of that specific grant has not yet been consumed:

```sql
ALTER TABLE credit_ledger ADD COLUMN remaining_balance INTEGER;
-- NULL for debit rows (type = compute_deduction, expiry)
-- Initialized to `amount` on insert for credit rows
-- Decremented by deduct() as credits are consumed
```

**Consumption order contract for `deduct()`:**

1. **Plan-grant credits first** — ordered by `expires_at ASC` (soonest-expiring first),
   then `created_at ASC` (FIFO). This ensures credits that are about to expire get used
   before longer-lived credits.
2. **Purchased credits second** — `top_up`, `promo`, `refund` grants with `expires_at IS NULL`
   (or later expiry), ordered by `created_at ASC` (FIFO).

`deduct()` iterates through grant rows with `remaining_balance > 0` in the above order,
decrementing each grant's `remaining_balance` until the requested amount is fully satisfied
(or all grants are exhausted). This is a **lot-allocation** approach.

**How `processExpiredCredits()` works with this model:**

At period end, `processExpiredCredits()` queries all `plan_grant` ledger entries where
`expires_at <= NOW()` and `remaining_balance > 0`. For each, it creates an `expiry` ledger
entry debiting the `remaining_balance` and sets `remaining_balance = 0` on the grant row.
The tenant's `credit_balances.available` is reduced by the total expired amount.

Because purchased credits have `expires_at = NULL` (or a far-future date), they are never
touched by this process — only unconsumed plan-grant credits are expired.

### B.5 — Balance enforcement

| Balance state | Behavior |
|--------------|----------|
| **Sufficient** | All actions allowed (deploy, start, restart, scale, update, env-update, rollback) |
| **Low** (< 24h of current burn rate) | Warning banner on dashboard, email notification |
| **Zero** | Deploy, start, restart, scale, update, env-update, and rollback are blocked; existing running agents get a 1-hour grace period, then auto-stopped |
| **Top-up while stopped** | User can restart agents once balance is positive |

Credit balance checks must gate **all compute-initiating actions**, not just deploy:
- `store` (create/deploy) — API + dashboard
- `start` — API + dashboard
- `restart` — API + dashboard
- `scale` — API only
- `update` (PATCH mutable fields) — API only. `HostedAgentController::update()` dispatches `DeployHostedAgentJob` when `applyMutations()` returns changes, so a zero-balance user can trigger a redeploy by patching fields like `replica_size` or `image_tag`.
- `env-update` (environment variable changes) — dashboard only. `HostedAgentDashboardController::updateEnv()` dispatches `DeployHostedAgentJob` unconditionally after merging env vars.
- `rollback` — API (`HostedAgentDeploymentController::rollback()`) + dashboard (`HostedAgentDashboardController::rollback()`). Both dispatch `DeployHostedAgentJob` to redeploy from a historical image digest.

A new `CheckCreditBalance` middleware (or an extension of `EnforceQuota`) is applied
to these routes in both `routes/api.php` and `routes/web.php` (dashboard).

---

## Part C — Schema

### C.1 — `credit_balances` table

Denormalized running balance for fast reads. Updated transactionally with every ledger entry.

```sql
CREATE TABLE credit_balances (
    cloud_tenant_id  VARCHAR(26) PRIMARY KEY REFERENCES cloud_tenants(id) ON DELETE CASCADE,
    available        INTEGER NOT NULL DEFAULT 0,   -- current spendable credits
    reserved         INTEGER NOT NULL DEFAULT 0,   -- held for running agents (soft reservation)
    lifetime_granted INTEGER NOT NULL DEFAULT 0,   -- total ever granted (audit metric)
    lifetime_spent   INTEGER NOT NULL DEFAULT 0,   -- total ever deducted (audit metric)
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### C.2 — `credit_ledger` table

Immutable append-only log of every credit movement. Source of truth for auditing and
dispute resolution. The `credit_balances` table is a materialized view of this ledger.

```sql
CREATE TABLE credit_ledger (
    id               VARCHAR(26) PRIMARY KEY,      -- ULID
    cloud_tenant_id  VARCHAR(26) NOT NULL REFERENCES cloud_tenants(id) ON DELETE CASCADE,
    amount           INTEGER NOT NULL,              -- positive = credit, negative = debit
    balance_after    INTEGER NOT NULL,              -- running balance snapshot
    type             VARCHAR(30) NOT NULL,          -- plan_grant, top_up, promo, refund, compute_deduction, expiry
    description      VARCHAR(255),                  -- human-readable ("Hourly compute: agent-xyz, m x2")
    reference_type   VARCHAR(50),                   -- polymorphic: 'hosted_agent', 'stripe_payment', etc.
    reference_id     VARCHAR(255),                  -- the related entity ID
    metadata         JSONB,                         -- extra context (rate, hours, size, etc.)
    expires_at       TIMESTAMP,                     -- null = never expires
    remaining_balance INTEGER,                      -- per-grant tracking: initialized to `amount` for credit rows, NULL for debits
    created_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_credit_ledger_tenant    ON credit_ledger (cloud_tenant_id, created_at DESC);
CREATE INDEX idx_credit_ledger_type      ON credit_ledger (type);
CREATE INDEX idx_credit_ledger_reference ON credit_ledger (reference_type, reference_id);
CREATE INDEX idx_credit_ledger_expiry    ON credit_ledger (expires_at) WHERE expires_at IS NOT NULL;
```

### C.3 — Changes to existing tables

**`cloud_tenants`**: No schema change. Balance lives in `credit_balances` (1:1 relationship).

**`config/plans.php`**: Add `credits_per_month` to each plan's `limits` block and
`credit_rates` top-level config for size-to-credits mapping.

---

## Part D — Service Layer

### D.1 — `CreditService`

Core service, singleton, cloud-only. Bound in `AppServiceProvider`.

```
CreditService
├── getBalance(tenant): CreditBalance
├── grant(tenant, amount, type, description, expiresAt?): LedgerEntry
├── deduct(tenant, amount, type, description, reference?): LedgerEntry
├── hasEnough(tenant, amount): bool
├── estimateHourlyCost(tenant): int         // based on running agents
├── hoursRemaining(tenant): ?float          // balance / hourly burn rate
├── processHourlyDeductions(): void         // called by scheduled job
├── processExpiredCredits(): void           // called by scheduled job
└── topUpViaStripe(tenant, amount, successUrl, cancelUrl): string  // returns Checkout URL
```

All mutations are **transactional**: ledger insert + balance update in one `DB::transaction()`.
Uses `lockForUpdate()` on `credit_balances` to serialize concurrent deductions (same
pattern as `UsageMeteringService::checkAndIncrement`).

**`deduct()` consumption ordering:** Plan-grant credits are consumed first (ordered by
`expires_at ASC`, then `created_at ASC`), followed by purchased credits (`top_up`, `promo`,
`refund` — ordered by `created_at ASC`). Each grant's `remaining_balance` is decremented
as credits are consumed. See B.4a for the full contract.

### D.2 — `DeductHostedAgentCreditsJob`

Scheduled hourly via `bootstrap/app.php` (`->withSchedule()`). For each tenant with running hosted agents:

1. Query `hosted_agent_usage_samples` since last deduction
2. Aggregate cost per agent: `count * rate * hours`
3. Call `CreditService::deduct()` per agent (or batched per tenant)
4. If balance hits zero: dispatch `SuspendHostedAgentsJob` after grace period

### D.3 — `GrantMonthlyCreditJob`

Triggered by **two webhook paths** (paid plans only):

1. **`customer.subscription.created`** — handles the initial grant for trialing subscriptions.
   When a new subscription starts with `status = trialing`, this webhook fires before any
   invoice. The job grants the plan's `credits_per_month` with `expires_at` set to the
   trial end date (= first invoice date). This ensures trialing tenants have credits
   immediately, since `CloudTenant::hasActiveSubscription()` returns `true` for `trialing`.

2. **`invoice.payment_succeeded`** — handles all subsequent monthly grants (and the first
   grant for non-trial subscriptions where `trial_days = 0`).

Free-plan tenants receive 0 credits and are skipped — no Stripe events required.

**Idempotency contract:** Each grant is deduplicated by `(tenant_id, billing_period_start)`.
The job stores the period start date in `credit_ledger.metadata->period_start` and checks
for an existing `plan_grant` entry for that tenant+period before inserting. A duplicate
webhook retry or re-run is a no-op. Both the `customer.subscription.created` and
`invoice.payment_succeeded` paths use this same deduplication key, so overlapping events
for the same period are safe.

Calls `CreditService::grant()` with the plan's `credits_per_month` and initializes
`remaining_balance` to the grant amount.

Also runs `CreditService::processExpiredCredits()` to zero out any non-rollover
credits from the previous period (consuming only grant rows where `remaining_balance > 0`
and `expires_at` has passed).

### D.4 — Stripe integration for top-ups

One-time Checkout Session with `mode: 'payment'` (not subscription). Pre-defined
credit packs or custom amount. On `checkout.session.completed` webhook, call
`CreditService::grant(tenant, credits, 'top_up', ...)`.

> **⚠ Checkout session type separation:** The existing `ProcessStripeWebhook::handleCheckoutCompleted()`
> handles **all** `checkout.session.completed` events and unconditionally sends
> `SubscriptionStartedMail` when a tenant ID is present. A payment-mode top-up session
> would trigger a false subscription-started email. The implementation **must** fork
> `handleCheckoutCompleted()` to inspect the session `mode`:
>
> - `mode: 'subscription'` → existing subscription sync + `SubscriptionStartedMail` path
> - `mode: 'payment'` → credit top-up grant via `CreditService::grant()`, **no** `SubscriptionStartedMail`
>
> This guard must be in place before the top-up checkout flow goes live (PR 5).

Credit packs (configurable, 1:1 dollar mapping):

| Pack | Credits | Price |
|------|---------|-------|
| Starter | 10 | $10 |
| Standard | 50 | $50 |
| Bulk | 100 | $100 |

---

## Part E — Frontend Changes

### E.1 — Credit balance widget (dashboard header)

Small persistent widget showing current balance, burn rate, and estimated hours remaining.
Color-coded: green (> 48h), yellow (< 24h), red (< 4h or zero).

### E.2 — Credit history page (`/cloud/{tenant}/billing/credits`)

Table view of the credit ledger with type filters. Shows grants, deductions, top-ups,
expiries. Pagination and date range filter.

### E.3 — Top-up flow

Button on billing page and in the low-balance warning. Opens Stripe Checkout for
a credit pack. Redirects back with success flash.

### E.4 — Deploy gate

When creating a hosted agent, show estimated hourly cost in credits. If balance is
insufficient for 1 hour of operation, show a warning with a top-up link. Block deploy
if balance is zero.

### E.5 — Admin: credit management

Admin panel page to view tenant balances, grant promotional credits, issue refund
credits, and view ledger history for any tenant.

---

## Part F — Migration Plan

| PR | Size | Description | Risk |
|----|------|-------------|------|
| 1  | S    | Schema: `credit_balances` + `credit_ledger` tables, `CreditBalance` + `CreditLedgerEntry` models | Low |
| 2  | M    | `CreditService` core: grant, deduct, getBalance, hasEnough + tests | Low |
| 3  | M    | Hourly deduction job: reads usage samples, deducts credits, handles zero-balance | Medium — touches billing |
| 4  | S    | Plan grants: hook into `customer.subscription.created` (trial) + `invoice.payment_succeeded` (renewal) webhooks, monthly grant + expiry | Low |
| 5  | M    | Stripe top-up: credit packs config, Checkout flow, webhook handler. **Must fork `handleCheckoutCompleted()` by session mode** — payment-mode (top-up) sessions must not trigger `SubscriptionStartedMail`. | Medium — Stripe integration |
| 6  | M    | Frontend: balance widget, history page, top-up button, deploy gate | Low |
| 7  | S    | Admin: tenant credit management page | Low |
| 8  | S    | Backfill: grant initial credits to existing tenants based on current plan | Low |

PRs 1-3 are the critical path. PR 4-5 can be parallelized. PR 6-7 after 5. PR 8 is a
one-time migration that can land anytime after PR 2.

---

## Part G — Security & Safety

- **No negative balances**: `deduct()` clamps at zero. Ledger entry records the actual
  amount deducted (may be less than requested).
- **Serialized mutations**: `lockForUpdate()` on balance row prevents double-spend under
  concurrent deductions (e.g., hourly job + manual admin debit).
- **Immutable ledger**: `credit_ledger` rows are never updated or deleted. Corrections
  are new entries (refunds, adjustments).
- **Audit trail**: Every credit movement is logged with type, amount, reference, and
  the resulting balance. Admin grants are activity-logged.
- **Grace period**: Zero-balance doesn't instantly kill running agents — 1-hour grace
  gives the user time to top up. Configurable via `config('platform.credits.grace_period_minutes')`.
- **Stripe webhook idempotency**: Top-up grants use the existing `processed_stripe_events`
  table to prevent double-granting on webhook retries. Monthly plan grants are additionally
  deduplicated by `(tenant_id, billing_period_start)` in the credit ledger — even if
  the Stripe event is processed twice, the grant is written at most once per period.

---

## Part H — Resolved Decisions

All open questions from the original proposal have been resolved based on review
feedback from @doxadoxa.

1. **Credit rates** — **Resolved:** Keep the proposed rates (xs=1, s=2, m=5, l=10
   credits/hour). With the 1:1 dollar mapping (1 credit = $1), these rates are
   transparent and easy to reason about. Admin-configurable if adjustments are needed.

2. **Grace period** — **Resolved:** 1 hour. On zero balance, existing agents get a
   1-hour grace period before auto-stop. New deploys are blocked immediately. This
   gives users enough time to top up without allowing extended free usage. Configurable
   via `config('platform.credits.grace_period_minutes')`.

3. **Rollover policy** — **Resolved:** Plan grants do not roll over (expire at period
   end). Purchased credits (top-ups) can be rolled over manually by email request to
   support. No automatic rollover for MVP. This keeps the system simple while still
   allowing case-by-case flexibility.

4. **Free tier credits** — **Resolved:** 0 credits for the Free plan. Free users cannot
   run hosted agents. This prevents cost exposure from free-tier usage and keeps hosted
   agents as a paid feature. Free users can still use all non-compute features.

5. **Billing granularity** — **Resolved:** Hourly deductions (confirmed). The hourly
   cadence balances precision with ledger readability. The existing 5-minute sampler
   provides the underlying data; the deduction job aggregates it into hourly entries.
   Minute-level billing may be revisited post-MVP if users request more granular control.
