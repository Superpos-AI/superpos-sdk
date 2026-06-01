# Superpos — Agent Orchestration Platform

## Product Document v4.0

---

## 1. Vision

Superpos — open-source платформа оркестрации AI-агентов с event-driven архитектурой.
Предоставляет единую точку управления, коммуникации и наблюдаемости для автономных агентов (Claude Code, OpenClaw, custom agents), работающих на разных серверах и в разных контейнерах.

Доступна как **self-hosted open-source (Community Edition)** и как **managed SaaS (Cloud)**.

### Core Principles
- **Agents are autonomous** — агенты сами забирают задачи, оркестратор не push'ит
- **Loose coupling** — агенты не знают друг о друге напрямую, общаются через bus
- **Transparency first** — всё логируется, весь прогресс виден в реалтайме
- **Security by design** — агенты никогда не принимают входящих соединений
- **Zero-trust credentials** — агенты никогда не видят credentials к внешним сервисам
- **Self-configurable** — агенты с нужными permissions могут настраивать свою инфраструктуру
- **Open-core** — community edition genuinely useful, not crippled

---

## 2. Hierarchy Model

```
🏢 Organization
│   Billing, team members, service connections, connectors
│
├── 🐝 Hive "Backend" (project)
│   ├── Agents: code-reviewer, deployer, test-runner
│   ├── Task Queue
│   ├── Knowledge Store
│   ├── Webhook Routes
│   ├── Action Policies
│   └── Activity Log
│
├── 🐝 Hive "Mobile App"
│   ├── Agents: ui-tester, build-agent
│   ├── Task Queue
│   ├── Knowledge Store
│   ├── Webhook Routes
│   └── ...
│
├── 🐝 Hive "Infrastructure"
│   ├── Agents: monitor, alerter
│   └── ...
│
└── 🌐 Cross-Hive Event Bus
    └── Agents with cross_hive permission can communicate across hives
```

### What lives where

| Resource             | Level      | Rationale                                          |
|---------------------|------------|---------------------------------------------------|
| **Billing & plan**  | Organization | One bill per organization                          |
| **Team members**    | Organization | Users belong to org, access specific hives         |
| **Service connections** | Organization | GitHub token is org-level, shared across projects  |
| **Connectors**      | Organization | GitHub connector works the same for all hives      |
| **Agents**          | Hive       | Code reviewer for backend ≠ code reviewer for mobile |
| **Tasks**           | Hive       | Task queue is project-scoped                       |
| **Knowledge Store** | Hive (+ org scope) | Project context is isolated; some knowledge is org-wide |
| **Webhook Routes**  | Hive       | repo X → backend hive, repo Y → mobile hive       |
| **Action Policies** | Hive       | Agent permissions are project-specific             |
| **Events**          | Hive (+ cross-hive bus) | Local by default, cross-hive opt-in      |
| **Activity Log**    | Hive       | Per-project audit trail                            |
| **Proxy Log**       | Organization | Org-wide view of all service access                |

### CE vs Cloud

| Aspect          | Community Edition        | Cloud                          |
|----------------|--------------------------|--------------------------------|
| Organizations  | 1 (implicit)             | 1 per account (multi-org roadmap) |
| Hives          | 1 (implicit)             | Multiple per plan tier          |
| Team members   | N/A (single user)        | Multiple with roles             |
| Billing        | N/A                      | Stripe                          |

CE code never thinks about organizations or hives — `BelongsToOrganization` and `BelongsToHive` traits resolve to constants.

---

## 3. Editions & Feature Matrix

### 3.1 Community Edition (CE) — Open Source, MIT License

Full-featured single-tenant, single-project orchestration:
- ✅ Task queue + agent communication
- ✅ Service Proxy + Credentials Vault
- ✅ Action Policies (agent firewall)
- ✅ Approval flow
- ✅ Webhook routing with configurable filters
- ✅ Agent-writable connectors
- ✅ Knowledge Store
- ✅ Real-time dashboard
- ✅ Event bus
- ✅ Agent permission system
- ✅ Activity log + proxy log
- ✅ Horizon queue monitoring
- ✅ Docker Compose deployment
- ✅ Python, Node.js, shell SDKs
- ✅ Built-in connectors (GitHub, Slack)
- ✅ Workflow engine (Phase 4)

### 3.2 Cloud Edition — Managed SaaS

Everything in CE, plus:

| Category               | Feature                                   |
|------------------------|------------------------------------------|
| **Hosting**            | Fully managed, auto-scaling, backups, 99.9% SLA |
| **Multi-project**      | Multiple Hives per Organization            |
|                        | Cross-hive agent communication            |
| **Multi-tenancy**      | Organization isolation, per-org encryption keys |
| **Team Management**    | Multiple users, role-based (Owner/Admin/Member/Viewer) |
|                        | Per-hive access control                   |
|                        | SSO (SAML 2.0, OIDC)                     |
| **Billing & Quotas**   | Usage-based billing (Stripe), plan limits |
| **Onboarding**         | Guided wizard, templates, one-click OAuth |
| **Marketplace**        | Community connector marketplace           |
| **Compliance**         | Data residency (EU, US), audit export, SOC 2 (roadmap) |
| **Support**            | Priority support, dedicated channel       |

### 3.3 Pricing Tiers (Cloud)

| Feature                | Free              | Pro                | Enterprise         |
|------------------------|-------------------|--------------------|-------------------|
| **Hives**              | 1                 | 10                 | Unlimited         |
| Agents (total)         | 3                 | 30                 | Unlimited         |
| Tasks / month          | 1,000             | 50,000             | Unlimited         |
| Proxy requests / month | 5,000             | 100,000            | Unlimited         |
| Knowledge entries      | 500               | 10,000             | Unlimited         |
| Webhook routes (total) | 5                 | 100                | Unlimited         |
| Service connections    | 3                 | 20                 | Unlimited         |
| Team members           | 1                 | 10                 | Unlimited         |
| Cross-hive comms       | —                 | ✅                 | ✅                |
| SSO                    | —                 | —                  | ✅                |
| Data residency         | US                | US / EU            | Custom            |
| Support                | Community         | Email              | Dedicated         |
| Audit log retention    | 7 days            | 90 days            | Custom            |
| Price                  | $0                | $49/mo             | Custom            |

---

## 4. Architecture Overview

### 4.1 Core Architecture

```
┌─────────────────┐    webhooks       ┌──────────────────────────────────────────────┐
│  External World  │ ───────────────▸ │             Superpos Core                     │
│  (GitHub, Slack, │                  │             (Laravel App)                     │
│   CI/CD, APIs)   │ ◂──── proxy ──  │                                               │
└─────────────────┘                  │  ┌───────────┐ ┌──────────┐ ┌─────────────┐   │
                                      │  │ REST API   │ │ Webhook  │ │  Service    │   │
         ┌──── realtime ─────────────│──│ Gateway    │ │ Receiver │ │  Proxy      │   │
         │     (Reverb WS)           │  └─────┬─────┘ └────┬─────┘ └──────┬──────┘   │
         ▼                           │        │             │              │           │
┌─────────────────┐                  │  ┌─────▼─────────────▼──────────────▼───────┐   │
│   Web Dashboard  │                  │  │          Router + Policy Engine           │   │
│  (React/Inertia) │                  │  │  (Hive routing, Action Policies,         │   │
│                   │                  │  │   Approval Flow, Permission checks)      │   │
│  - Hive selector  │                  │  └──┬──────────────┬───────────────┬───────┘   │
│  - Agent overview │                  │     │              │               │           │
│  - Task board     │                  │  ┌──▼────────┐ ┌──▼────────┐ ┌───▼────────┐  │
│  - Approval queue │                  │  │ Per-Hive   │ │  Event    │ │ Credential │  │
│  - Cross-hive     │                  │  │ Task Queues│ │  Bus      │ │ Vault      │  │
│    monitor        │                  │  │  (Redis)   │ │ (hive +   │ │ (per-org)  │  │
└─────────────────┘                  │  │            │ │ cross-hive)│ │            │  │
                                      │  └──────┬─────┘ └────┬──────┘ └────────────┘  │
                                      │         │              │                       │
                                      │  ┌──────▼──────────────▼──────────────┐        │
                                      │  │        Knowledge Store              │        │
                                      │  │   (hive-scoped + org-scoped)        │        │
                                      │  └─────────────────────────────────────┘        │
                                      └──────────────────────────────────────────────────┘
                                           │          │            │
                          ┌── poll (Hive A)┘          │            └── poll (Hive B)──┐
                          │                           │                               │
                   ┌──────▼──────┐             ┌──────▼──────┐                 ┌──────▼──────┐
                   │   Agent A    │             │   Agent C    │                 │   Agent D    │
                   │ (Hive:Backend)│             │(Hive:Backend)│                 │(Hive:Mobile) │
                   └──────────────┘             └──────────────┘                 └──────────────┘
```

### 4.2 Cloud Architecture (SaaS additions)

```
              ┌─────────────────────────────────────────────────────┐
              │                   Superpos Cloud                    │
              │                                                     │
              │  ┌──────────────┐  ┌────────────┐  ┌────────────┐  │
              │  │  Org/Hive     │  │  Auth /     │  │  Billing   │  │
              │  │  Router       │  │  SSO        │  │  Service   │  │
              │  │  (middleware) │  │             │  │  (Stripe)  │  │
              │  └──────┬───────┘  └──────┬──────┘  └─────┬──────┘  │
              │         │                 │               │          │
              │  ┌──────▼─────────────────▼───────────────▼───────┐  │
              │  │             Superpos Core                       │  │
              │  │    (same codebase as CE, tenant+hive aware)     │  │
              │  └────────────────────────────────────────────────┘  │
              │                                                     │
              │  ┌──────────────┐  ┌────────────┐  ┌────────────┐  │
              │  │  Usage        │  │  Onboarding│  │ Connector  │  │
              │  │  Metering     │  │  Service   │  │ Marketplace│  │
              │  └──────────────┘  └────────────┘  └────────────┘  │
              └─────────────────────────────────────────────────────┘
```

---

## 5. Tech Stack

| Layer              | Technology                     | CE        | Cloud     |
|--------------------|--------------------------------|-----------|-----------|
| **Framework**      | Laravel 11+                    | ✅        | ✅        |
| **Queue/Bus**      | Redis + Laravel Horizon        | ✅        | ✅ (cluster) |
| **Database**       | PostgreSQL 16+                 | ✅        | ✅ (managed) |
| **Realtime (UI)**  | Laravel Reverb                 | ✅        | ✅        |
| **Frontend**       | Inertia.js + React             | ✅        | ✅        |
| **Agent Protocol** | REST API over HTTPS            | ✅        | ✅        |
| **Agent Auth**     | Sanctum (API tokens)           | ✅        | ✅ (hive-scoped) |
| **User Auth**      | Laravel Breeze                 | ✅        | + SSO (Socialite) |
| **Credentials**    | Laravel Encryption (AES-256)   | ✅        | ✅ (per-org key) |
| **Billing**        | —                              | —         | Stripe + Cashier |
| **Deployment**     | Docker Compose                 | ✅        | Kubernetes |

---

## 6. Core Concepts

### 6.1 Organization

The top-level container. An organization is the workspace where all hives operate.

- `id` — ULID
- `name` — "Acme Corp Engineering"
- `slug` — "acme-eng"
- `plan` — free / pro / enterprise
- `owner_id` — user who created it
- `encryption_key` — per-org key for vault
- `region` — data residency: `us`, `eu`
- `settings` — JSONB (quota overrides, feature flags)

**Owns:** team members, service connections, connectors, billing, proxy log.
**CE:** single implicit organization, hardcoded ID.

### 6.2 Hive (Project)

A self-contained project environment within an Organization. Each hive has its own agents, tasks, knowledge, and configuration.

- `id` — ULID
- `organization_id` — parent organization
- `name` — "Backend", "Mobile App", "Infrastructure"
- `slug` — "backend"
- `description` — optional
- `settings` — JSONB (per-hive config overrides)
- `is_active` — can be paused

**Owns:** agents, tasks, events, event subscriptions, knowledge entries (hive-scoped), webhook routes, action policies, activity log.
**CE:** single implicit hive, hardcoded ID.

### 6.3 Agent

An autonomous process registered to a **specific hive**:
- Registers with organization_id + hive_id
- Polls its **hive's** task queue
- Reads/writes its **hive's** knowledge store
- Can access **org-level** service connections through proxy
- With `cross_hive` permission, can interact with other hives

Three axes of configuration:
- **Capabilities** — what tasks: `["code_review", "refactoring"]`
- **Permissions** — what system resources: `["manage:webhook_routes", "services:github"]`
- **Cross-hive permissions** — which other hives: `["cross_hive:hive_mobile", "cross_hive:*"]`

### 6.4 Task

A unit of work **within a hive**:
- `hive_id` — which hive this task belongs to
- `type`, `priority`, `status`, `payload`, `result`, `progress`
- `source_agent_id`, `target_agent_id`, `target_capability`
- `source_hive_id` — if created by cross-hive agent, tracks origin
- `timeout_seconds`, `retry_count`, `max_retries`
- `parent_task_id` — for chains

### 6.5 Event

Events exist at **two levels**:

**Hive events** — local to a hive, e.g. `task.completed`, `agent.online`:
- Only agents within the same hive see these
- Default behavior, no special permissions needed

**Cross-hive events** — broadcast across the organization:
- Event type prefixed with `platform.` (e.g., `platform.deploy.completed`; legacy `apiary.*` prefix also accepted)
- Only agents with `cross_hive` permission can emit or subscribe
- Visible in cross-hive monitor on dashboard

### 6.6 Knowledge Entry

Shared context with **three scope levels**:

| Scope                 | Visible to                     | Example                           |
|----------------------|--------------------------------|-----------------------------------|
| `hive` (default)     | Agents in same hive            | `project:backend:architecture`    |
| `organization`       | All agents in all hives        | `org:coding-standards`            |
| `agent:{id}`         | Only that specific agent       | `agent:reviewer-1:preferences`    |

Cross-hive agents can read organization-scoped knowledge from any hive.
Hive-scoped knowledge is invisible to agents in other hives (even with cross_hive permission — they must use organization scope to share).

### 6.7 Service Connection (Organization-level)

External service with encrypted credentials, shared across all hives:
- One GitHub token serves all hives (same org)
- Action policies are **per-agent per-service** (hive-level), so different hives can have different access rules to the same GitHub connection

### 6.8 Action Policy (Hive-level)

Per-agent firewall for service access. Evaluation: deny → require_approval → allow → default deny.

### 6.9 Webhook Route (Hive-level)

Routes incoming webhooks to tasks in a **specific hive**:
- Webhook arrives at org-level endpoint
- Route config says "repo myorg/backend → create task in Hive:Backend"
- Route config says "repo myorg/mobile → create task in Hive:Mobile"

### 6.10 Connector (Organization-level)

Webhook parsing adapter. Shared across hives (a GitHub connector works the same everywhere).

---

## 7. Cross-Hive Communication

### 7.1 Why

Real scenario: backend agent deploys a new API version → mobile agent needs to know to run integration tests. Without cross-hive, you'd need external glue.

### 7.2 Mechanisms

**Cross-Hive Tasks:**
An agent in Hive A creates a task in Hive B.

```json
POST /api/v1/tasks
{
  "type": "run_integration_tests",
  "target_hive_id": "hive_mobile_abc",      // ← cross-hive
  "target_capability": "testing",
  "payload": {
    "api_version": "2.5.0",
    "changelog": "New auth endpoint",
    "source_hive": "backend"
  }
}
```

Requirements:
- Agent must have permission: `cross_hive:hive_mobile_abc` or `cross_hive:*`
- Task is created **in Hive B's queue** — Hive B agents pick it up normally
- Task carries `source_hive_id` for traceability

**Cross-Hive Events:**
Broadcast events that all subscribed agents across all hives can see.

```json
POST /api/v1/events
{
  "type": "platform.deploy.completed",       // ← platform. prefix = cross-hive
  "payload": {
    "service": "backend-api",
    "version": "2.5.0",
    "environment": "production"
  }
}
```

Any agent in any hive can subscribe to `platform.deploy.*` if they have `cross_hive` permission.

**Organization-Scoped Knowledge:**
Write knowledge that's visible across all hives.

```json
POST /api/v1/knowledge
{
  "key": "api:backend:current_version",
  "value": { "version": "2.5.0", "deployed_at": "2025-02-19T10:00:00Z" },
  "scope": "organization"                    // ← visible to all hives
}
```

### 7.3 Security Model

```
┌─────────────────────────────────────────────────┐
│ Organization                                    │
│                                                 │
│  Cross-Hive Event Bus (platform.* events)       │
│  Org-scoped Knowledge Store                     │
│                                                 │
│  ┌─────────────┐     ┌─────────────┐           │
│  │  Hive A      │────▸│  Hive B      │          │
│  │              │     │              │          │
│  │  Agent 1 ────┼──task──▸ Agent 3   │          │
│  │  (cross_hive │     │              │          │
│  │   permission)│     │  Agent 4     │          │
│  │              │     │  (no cross   │          │
│  │  Agent 2     │     │   permission)│          │
│  │  (no cross   │     └─────────────┘          │
│  │   permission)│                               │
│  └─────────────┘                               │
│                                                 │
│  Agent 1: CAN create tasks in Hive B            │
│  Agent 2: CANNOT (no cross_hive permission)     │
│  Agent 4: CANNOT see cross-hive events          │
└─────────────────────────────────────────────────┘
```

### 7.4 Dashboard: Cross-Hive Monitor

Dedicated view showing:
- Cross-hive tasks: which hive → which hive, agent, status
- Cross-hive events: timeline across all hives
- Organization-scoped knowledge entries
- Visual map of inter-hive dependencies (which hives talk to each other)

---

## 8. Multi-Tenancy (Cloud)

### 8.1 Strategy: Shared Database + Row-Level Isolation

Two levels of scoping:
- `organization_id` — on org-level tables (service_connections, connectors, users, proxy_log)
- `organization_id` + `hive_id` — on project-level tables (agents, tasks, knowledge, etc.)

### 8.2 Resolution

```
Request → OrgMiddleware → resolves organization from:
  1. Agent token → agent.organization_id (API requests)
  2. Session → user.current_org_id (Dashboard)
  3. Subdomain → organizations.slug (acme-eng.superpos.ai)

→ HiveMiddleware → resolves hive from:
  1. Agent token → agent.hive_id (API requests)
  2. Session → user.current_hive_id (Dashboard hive selector)
  3. URL path → /hives/{slug}/... (explicit)

→ Sets context globally for the request
→ All queries auto-scoped via BelongsToOrganization / BelongsToHive traits
```

### 8.3 Traits

```php
// Organization-level resources (service_connections, connectors, etc.)
trait BelongsToOrganization
{
    protected static function booted()
    {
        static::addGlobalScope('organization', function (Builder $builder) {
            if (config('platform.features.multi_tenancy')) {
                $builder->where('organization_id', organization()->id);
            }
        });

        static::creating(function ($model) {
            $model->organization_id = config('platform.features.multi_tenancy')
                ? organization()->id
                : 'default';
        });
    }
}

// Hive-level resources (agents, tasks, knowledge, etc.)
trait BelongsToHive
{
    use BelongsToOrganization; // hive resources also scoped to organization

    protected static function booted()
    {
        parent::booted();

        static::addGlobalScope('hive', function (Builder $builder) {
            if (config('platform.features.multi_hive')) {
                $builder->where('hive_id', hive()->id);
            }
        });

        static::creating(function ($model) {
            $model->hive_id = config('platform.features.multi_hive')
                ? hive()->id
                : 'default';
        });
    }
}
```

CE: both traits resolve to `'default'` constants. Zero overhead, zero awareness.
Cloud Free: single hive, `BelongsToHive` still scopes correctly.
Cloud Pro+: multiple hives, full scoping active.

### 8.4 Users & Team Management

```sql
CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password        VARCHAR(255),
    provider        VARCHAR(50),
    provider_id     VARCHAR(255),
    email_verified_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Organization membership (org-level)
CREATE TABLE organization_members (
    organization_id VARCHAR(26) NOT NULL REFERENCES organizations(id),
    user_id         BIGINT NOT NULL REFERENCES users(id),
    role            VARCHAR(20) NOT NULL DEFAULT 'member',
    invited_by      BIGINT REFERENCES users(id),
    created_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (organization_id, user_id)
);

-- Hive access (project-level)
CREATE TABLE hive_access (
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id),
    user_id         BIGINT NOT NULL REFERENCES users(id),
    role            VARCHAR(20) NOT NULL DEFAULT 'member',
    created_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (hive_id, user_id)
);
```

Roles cascade: Org Owner/Admin → access to all hives. Member → access only to assigned hives. Viewer → read-only.

---

## 9. Database Schema

### 9.1 Organization Layer

```sql
-- Organizations
CREATE TABLE organizations (
    id                VARCHAR(26) PRIMARY KEY,
    name              VARCHAR(255) NOT NULL,
    slug              VARCHAR(100) NOT NULL UNIQUE,
    plan              VARCHAR(20) DEFAULT 'free',
    owner_id          BIGINT NOT NULL REFERENCES users(id),
    encryption_key    TEXT NOT NULL,
    region            VARCHAR(10) DEFAULT 'us',
    settings          JSONB DEFAULT '{}',
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),
    trial_ends_at     TIMESTAMP,
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW()
);

-- Hives (projects)
CREATE TABLE hives (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL,
    description     TEXT,
    settings        JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(organization_id, slug)
);

-- Service Connections (org-level)
CREATE TABLE service_connections (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    type            VARCHAR(100) NOT NULL,
    base_url        VARCHAR(500) NOT NULL,
    auth_type       VARCHAR(50) NOT NULL,
    auth_config     TEXT NOT NULL,                -- encrypted with org key
    connector_id    VARCHAR(26) REFERENCES connectors(id),
    webhook_secret  TEXT,                          -- encrypted
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(organization_id, name)
);

-- Connectors (org-level)
CREATE TABLE connectors (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    type            VARCHAR(100) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    class_path      VARCHAR(500) NOT NULL,
    is_builtin      BOOLEAN DEFAULT FALSE,
    created_by      VARCHAR(26),
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(organization_id, type)
);

-- Proxy Log (org-level — org-wide view of all service access)
CREATE TABLE proxy_log (
    id              BIGSERIAL PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26),
    agent_id        VARCHAR(26) NOT NULL,
    service_id      VARCHAR(26) NOT NULL,
    method          VARCHAR(10) NOT NULL,
    path            TEXT NOT NULL,
    status_code     SMALLINT,
    response_time_ms INTEGER,
    policy_result   VARCHAR(20),
    approval_id     VARCHAR(26),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_proxy_log_org ON proxy_log (organization_id, created_at DESC);
CREATE INDEX idx_proxy_log_hive ON proxy_log (hive_id, created_at DESC);
```

### 9.2 Hive Layer

```sql
-- Agents (hive-scoped)
CREATE TABLE agents (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL REFERENCES organizations(id),
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    type            VARCHAR(100) NOT NULL,
    capabilities    JSONB NOT NULL DEFAULT '[]',
    status          VARCHAR(20) DEFAULT 'offline',
    api_token_hash  VARCHAR(255) NOT NULL,
    metadata        JSONB DEFAULT '{}',
    last_heartbeat  TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Agent Permissions (includes cross_hive permissions)
CREATE TABLE agent_permissions (
    agent_id        VARCHAR(26) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    permission      VARCHAR(100) NOT NULL,
    granted_by      VARCHAR(255),
    created_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (agent_id, permission)
);

-- Tasks (hive-scoped)
CREATE TABLE tasks (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id),
    source_hive_id  VARCHAR(26) REFERENCES hives(id),  -- non-null if cross-hive
    type            VARCHAR(100) NOT NULL,
    source_agent_id VARCHAR(26) REFERENCES agents(id),
    target_agent_id VARCHAR(26) REFERENCES agents(id),
    target_capability VARCHAR(100),
    claimed_by      VARCHAR(26) REFERENCES agents(id),
    priority        SMALLINT DEFAULT 2,
    status          VARCHAR(20) DEFAULT 'pending',
    payload         JSONB NOT NULL DEFAULT '{}',
    result          JSONB,
    progress        SMALLINT DEFAULT 0,
    status_message  TEXT,
    timeout_seconds INTEGER DEFAULT 300,
    retry_count     SMALLINT DEFAULT 0,
    max_retries     SMALLINT DEFAULT 3,
    parent_task_id  VARCHAR(26) REFERENCES tasks(id),
    context_refs    JSONB DEFAULT '[]',
    created_at      TIMESTAMP DEFAULT NOW(),
    claimed_at      TIMESTAMP,
    completed_at    TIMESTAMP
);

CREATE INDEX idx_tasks_poll ON tasks (hive_id, status, priority, target_capability, created_at)
    WHERE status = 'pending';
CREATE INDEX idx_tasks_agent ON tasks (claimed_by, status);
CREATE INDEX idx_tasks_cross_hive ON tasks (source_hive_id) WHERE source_hive_id IS NOT NULL;

-- Events (hive-scoped + cross-hive)
CREATE TABLE events (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) REFERENCES hives(id),  -- NULL for cross-hive (platform.*) events
    type            VARCHAR(100) NOT NULL,
    source_agent_id VARCHAR(26),
    payload         JSONB NOT NULL DEFAULT '{}',
    is_cross_hive   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_events_hive ON events (hive_id, type, created_at);
CREATE INDEX idx_events_cross_hive ON events (organization_id, created_at) WHERE is_cross_hive = TRUE;

-- Event Subscriptions
CREATE TABLE event_subscriptions (
    agent_id        VARCHAR(26) REFERENCES agents(id) ON DELETE CASCADE,
    event_type      VARCHAR(100) NOT NULL,
    scope           VARCHAR(20) DEFAULT 'hive',  -- 'hive' or 'organization'
    PRIMARY KEY (agent_id, event_type)
);

-- Cross-hive event filtering:
-- Cross-hive events (platform.*) have hive_id = NULL and is_cross_hive = TRUE.
-- Agents receive cross-hive events via subscriptions with scope = 'organization'.
-- The event poll endpoint filters by subscription scope:
--   scope='hive'         → events WHERE hive_id = agent's hive_id
--   scope='organization' → events WHERE is_cross_hive = TRUE AND organization_id = agent's organization_id
-- Agents never filter by hive_id directly for cross-hive events.

-- Knowledge Store (hive-scoped with org scope option)
CREATE TABLE knowledge_entries (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) REFERENCES hives(id), -- NULL for org-scoped
    key             VARCHAR(500) NOT NULL,
    value           JSONB NOT NULL,
    scope           VARCHAR(255) DEFAULT 'hive',       -- 'hive', 'organization', 'agent:{id}'
    visibility      VARCHAR(20) DEFAULT 'public',
    created_by      VARCHAR(26) REFERENCES agents(id),
    version         INTEGER DEFAULT 1,
    ttl             TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_knowledge_key_scope ON knowledge_entries (organization_id, hive_id, key, scope);
CREATE INDEX idx_knowledge_search ON knowledge_entries USING gin (value jsonb_path_ops);
CREATE INDEX idx_knowledge_org_scope ON knowledge_entries (organization_id, scope) WHERE scope = 'organization';

-- Knowledge scope permission rules:
--   knowledge:read          → read hive-scoped AND org-scoped entries
--   knowledge:write         → write hive-scoped entries only
--   knowledge:write_apiary  → write org-scoped entries (org-level permission)
--   agent:{id} scope        → readable/writable only by that specific agent

-- Webhook Routes (hive-scoped)
CREATE TABLE webhook_routes (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id),
    name            VARCHAR(255) NOT NULL,
    service_id      VARCHAR(26) NOT NULL REFERENCES service_connections(id),
    event_type      VARCHAR(100) NOT NULL,
    field_filters   JSONB NOT NULL DEFAULT '[]',
    action_type     VARCHAR(20) NOT NULL,
    action_config   JSONB NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    priority        SMALLINT DEFAULT 0,
    created_by      VARCHAR(26) REFERENCES agents(id),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Action Policies (hive-scoped: per-agent per-service)
CREATE TABLE action_policies (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL,
    agent_id        VARCHAR(26) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    service_id      VARCHAR(26) NOT NULL REFERENCES service_connections(id),
    rules           JSONB NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(agent_id, service_id)
);

-- Approval Requests
CREATE TABLE approval_requests (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL,
    agent_id        VARCHAR(26) NOT NULL REFERENCES agents(id),
    service_id      VARCHAR(26) NOT NULL REFERENCES service_connections(id),
    task_id         VARCHAR(26) REFERENCES tasks(id),
    request_method  VARCHAR(10) NOT NULL,
    request_path    TEXT NOT NULL,
    request_body    JSONB,
    reason          TEXT,
    status          VARCHAR(20) DEFAULT 'pending',
    decided_by      VARCHAR(255),
    decided_at      TIMESTAMP,
    expires_at      TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_approvals_pending ON approval_requests (organization_id, status, created_at)
    WHERE status = 'pending';

-- Activity Log (hive-scoped)
CREATE TABLE activity_log (
    id              BIGSERIAL PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26),
    agent_id        VARCHAR(26),
    task_id         VARCHAR(26),
    action          VARCHAR(100) NOT NULL,
    details         JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_activity_hive ON activity_log (hive_id, created_at DESC);
CREATE INDEX idx_activity_org ON activity_log (organization_id, created_at DESC);

-- Usage Metering (Cloud, org-level)
CREATE TABLE usage_records (
    id              BIGSERIAL PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL REFERENCES organizations(id),
    resource        VARCHAR(50) NOT NULL,
    count           INTEGER NOT NULL DEFAULT 0,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(organization_id, resource, period_start)
);

-- Workflows (Phase 4, hive-scoped)
CREATE TABLE workflows (
    id              VARCHAR(26) PRIMARY KEY,
    organization_id VARCHAR(26) NOT NULL,
    hive_id         VARCHAR(26) NOT NULL REFERENCES hives(id),
    name            VARCHAR(255) NOT NULL,
    trigger_config  JSONB NOT NULL,
    steps           JSONB NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

---

## 10. API Design

Base URL:
- CE: `https://your-server.com/api/v1`
- Cloud: `https://acme-eng.superpos.ai/api/v1`

Agent token is scoped to a specific hive. All queries auto-scoped.

### 10.1 Agent Lifecycle
```
POST   /agents/register           — Register to specific hive
POST   /agents/heartbeat
GET    /agents                    — List agents in current hive
GET    /agents/{id}
DELETE /agents/{id}
```

#### Register Agent
```json
POST /agents/register
{
  "name": "code-reviewer-1",
  "type": "openclaw",
  "hive": "backend",                           // ← hive slug
  "capabilities": ["code_review", "refactoring"],
  "requested_permissions": ["services:github-myorg", "cross_hive:mobile"],
  "metadata": {
    "model": "claude-sonnet-4-5",
    "max_concurrent_tasks": 3
  }
}

Response:
{
  "agent_id": "agt_abc123",
  "organization_id": "org_xyz",
  "hive_id": "hiv_backend",
  "token": "tok_xxxxx",
  "granted_permissions": ["services:github-myorg", "cross_hive:mobile", "knowledge:read", "knowledge:write"],
  "poll_interval_ms": 3000,
  "endpoints": {
    "tasks": "/api/v1/tasks/poll",
    "events": "/api/v1/events/poll",
    "knowledge": "/api/v1/knowledge",
    "proxy": "/api/v1/proxy/{service_name}",
    "cross_hive_tasks": "/api/v1/cross/tasks"
  }
}
```

### 10.2 Tasks
```
GET    /tasks/poll                — Poll current hive's queue
POST   /tasks                    — Create task in current hive
POST   /cross/tasks              — Create task in another hive (requires cross_hive)
PATCH  /tasks/{id}/claim
PATCH  /tasks/{id}/progress
PATCH  /tasks/{id}/complete      — Supports knowledge_entries + spawn_tasks (same or cross-hive)
PATCH  /tasks/{id}/fail
GET    /tasks
GET    /tasks/{id}
```

#### Cross-Hive Task
```json
POST /cross/tasks
{
  "target_hive": "mobile",                     // ← target hive slug
  "type": "run_integration_tests",
  "target_capability": "testing",
  "payload": {
    "api_version": "2.5.0",
    "source_hive": "backend"
  },
  "priority": "high"
}
```

### 10.3 Events
```
GET    /events/poll               — Poll hive events + subscribed cross-hive events
POST   /events                    — Emit hive event or cross-hive event (platform.* prefix)
PUT    /events/subscriptions
```

### 10.4 Knowledge Store
```
GET    /knowledge?key={pattern}&scope={scope}  — scope: hive (default), organization
POST   /knowledge
PUT    /knowledge/{id}
DELETE /knowledge/{id}
GET    /knowledge/search?q=...
```

### 10.5 Service Proxy
```
ANY    /proxy/{service_name}/**
POST   /proxy/{service_name}/token
```

### 10.6 Webhooks
```
POST   /webhooks/{service_name}   — Org-level endpoint, routes to correct hive
```

### 10.7 Configuration
```
GET|POST|PUT|DELETE  /config/webhook-routes     — Hive-scoped
GET|POST             /config/connectors         — Org-scoped
GET|POST             /config/services           — Org-scoped
GET|POST             /config/policies           — Hive-scoped
GET|POST             /approvals/{id}/(approve|deny)
```

### 10.8 Hive Management (Cloud)
```
GET    /hives                     — List hives in current organization
POST   /hives                     — Create new hive
PATCH  /hives/{slug}              — Update hive settings
DELETE /hives/{slug}              — Deactivate hive
```

### 10.9 Cloud-only APIs
```
GET    /organizations/current      — Current organization info + usage
PATCH  /organizations/current      — Update settings
GET|POST|PATCH|DELETE /organizations/current/members
GET    /billing
POST   /billing/portal
GET    /usage
```

(See v2 doc for detailed request/response examples.)

---

## 11. Service Proxy & Credentials Vault

Unchanged from v2/v3 — see previous doc sections.
Key addition: service connections are **org-level** but action policies are **hive-level (per-agent)**.

---

## 12. Connectors

A **Connector** is an org-level webhook parsing adapter. Each connector knows how to validate incoming webhook signatures and parse raw HTTP payloads into structured events that the platform can route.

Connectors implement `ConnectorInterface` (see `app/Contracts/ConnectorInterface.php`):
- `validateSignature(Request $request, string $secret): bool` — verify the webhook is authentic
- `parsePayload(Request $request): WebhookEvent` — extract event type and structured data from the raw request
- `supportedEvents(): array` — list of event types this connector emits (e.g., `push`, `pull_request.opened`)

Built-in connectors (`app/Connectors/`): `GitHubConnector`, `SlackConnector`. Agents with `manage:connectors` permission can register custom connectors at runtime. Connectors are shared across all hives — a GitHub connector works the same everywhere.

---

## 13. Webhook Routes

Same mechanics as v2/v3, with one key addition: each route targets a **specific hive**.

Webhook arrives at org-level endpoint `/webhooks/github`, the route evaluator:
1. Connector parses webhook → structured event
2. Evaluates routes across ALL hives in the organization
3. Route matches → creates task in the route's designated hive
4. Multiple routes can match → tasks created in multiple hives simultaneously

Example: push to `main` creates deploy task in Backend hive AND notification task in Infrastructure hive.

---

## 14. Dashboard Features

### 14.1 Hive Selector
- Dropdown/sidebar to switch between hives
- "All Hives" view for cross-hive monitoring
- Quick stats per hive (active agents, pending tasks, recent activity)

### 14.2 Per-Hive Views
- Agent Overview (hive-scoped)
- Task Board (Kanban, hive-scoped)
- Knowledge Explorer (hive-scoped + org-scoped entries highlighted)
- Webhook Monitor (hive-scoped routes)
- Activity Feed (hive-scoped)

### 14.3 Organization-Wide Views
- **Cross-Hive Monitor** — inter-hive tasks, cross-hive events, dependency map
- **Service Proxy Monitor** — all proxy requests across all hives
- **Approval Queue** — pending approvals from all hives
- **Team Management** — members, roles, hive access

### 14.4 Cloud-only
- Workspace/Organization Settings
- Hive Management (create, rename, deactivate)
- Billing & Usage
- Onboarding Wizard
- Connector Marketplace

---

## 15. Agent Permission System

| Permission                | Level   | What it allows                            |
|--------------------------|---------|-------------------------------------------|
| `tasks:create`           | Hive    | Create tasks in own hive                   |
| `tasks:manage`           | Hive    | Cancel/reassign any task in own hive       |
| `knowledge:read`         | Hive    | Read hive + org knowledge                  |
| `knowledge:write`        | Hive    | Write hive knowledge                       |
| `knowledge:write_apiary` | Org     | Write org-scoped knowledge                 |
| `knowledge:manage`       | Hive    | Delete/modify any entry in own hive        |
| `manage:webhook_routes`  | Hive    | CRUD webhook routes for own hive           |
| `manage:connectors`      | Org     | Register new connectors                    |
| `manage:agents`          | Hive    | Register/deregister agents in own hive     |
| `manage:policies`        | Hive    | Edit action policies in own hive           |
| `services:{service_id}`  | Org     | Access specific service via proxy           |
| `services:*`             | Org     | Access all services                        |
| `cross_hive:{hive_slug}` | Org     | Create tasks + emit events to target hive  |
| `cross_hive:*`           | Org     | Cross-hive access to all hives             |
| `admin:*`                | Org     | Full system access                         |

---

## 16. Project Structure (Laravel)

```
superpos/
├── app/
│   ├── Http/
│   │   ├── Controllers/
│   │   │   ├── Api/
│   │   │   │   ├── AgentController.php
│   │   │   │   ├── TaskController.php
│   │   │   │   ├── CrossHiveTaskController.php  ← new
│   │   │   │   ├── EventController.php
│   │   │   │   ├── KnowledgeController.php
│   │   │   │   ├── WebhookController.php
│   │   │   │   ├── ProxyController.php
│   │   │   │   ├── ApprovalController.php
│   │   │   │   └── ConfigController.php
│   │   │   └── Dashboard/
│   │   │       ├── DashboardController.php
│   │   │       ├── HiveController.php           ← new
│   │   │       ├── AgentViewController.php
│   │   │       ├── TaskViewController.php
│   │   │       ├── CrossHiveMonitorController.php ← new
│   │   │       ├── ApprovalViewController.php
│   │   │       └── ConfigViewController.php
│   │   ├── Middleware/
│   │   │   ├── ResolveOrganization.php           ← new
│   │   │   ├── ResolveHive.php                  ← new
│   │   │   ├── AgentAuth.php
│   │   │   ├── CheckPermission.php
│   │   │   ├── CheckCrossHivePermission.php     ← new
│   │   │   └── WebhookSignature.php
│   │   └── Requests/
│   │       └── ...
│   ├── Models/
│   │   ├── Organization.php                      ← new
│   │   ├── Hive.php                             ← new
│   │   ├── Agent.php
│   │   ├── AgentPermission.php
│   │   ├── Task.php
│   │   ├── Event.php
│   │   ├── EventSubscription.php
│   │   ├── KnowledgeEntry.php
│   │   ├── Connector.php
│   │   ├── ServiceConnection.php
│   │   ├── ActionPolicy.php
│   │   ├── ApprovalRequest.php
│   │   ├── WebhookRoute.php
│   │   ├── ActivityLog.php
│   │   ├── ProxyLog.php
│   │   └── Workflow.php
│   ├── Services/
│   │   ├── TaskRouter.php
│   │   ├── CrossHiveRouter.php                  ← new
│   │   ├── EventBus.php                         — updated: hive + cross-hive
│   │   ├── KnowledgeStore.php                   — updated: scope awareness
│   │   ├── AgentMonitor.php
│   │   ├── WebhookProcessor.php
│   │   ├── WebhookRouteEvaluator.php            — updated: multi-hive evaluation
│   │   ├── ServiceProxy.php
│   │   ├── CredentialVault.php
│   │   ├── PolicyEngine.php
│   │   ├── ApprovalManager.php
│   │   ├── ConnectorManager.php
│   │   └── WorkflowEngine.php
│   ├── Connectors/
│   │   ├── GitHubConnector.php
│   │   ├── SlackConnector.php
│   │   └── ...
│   ├── Contracts/
│   │   └── ConnectorInterface.php
│   ├── Traits/
│   │   ├── BelongsToOrganization.php             ← new
│   │   └── BelongsToHive.php                    ← new
│   ├── Cloud/
│   │   ├── Http/Controllers/
│   │   │   ├── BillingController.php
│   │   │   ├── OrgSettingsController.php
│   │   │   ├── HiveManagementController.php
│   │   │   ├── TeamController.php
│   │   │   ├── OnboardingController.php
│   │   │   └── MarketplaceController.php
│   │   ├── Http/Middleware/
│   │   │   ├── CheckQuota.php
│   │   │   └── RequireSSO.php
│   │   ├── Services/
│   │   │   ├── UsageMeter.php
│   │   │   ├── PlanLimits.php
│   │   │   └── MarketplaceService.php
│   │   ├── Jobs/
│   │   │   ├── FlushUsageCounters.php
│   │   │   ├── SyncStripeUsage.php
│   │   │   └── CleanupTrialWorkspaces.php
│   │   └── Providers/
│   │       ├── TenancyServiceProvider.php
│   │       ├── BillingServiceProvider.php
│   │       └── MarketplaceServiceProvider.php
│   └── Jobs/
│       ├── ProcessWebhook.php
│       ├── ExecuteProxyRequest.php
│       ├── CheckTaskTimeouts.php
│       ├── CheckAgentLiveness.php
│       ├── CleanupExpiredKnowledge.php
│       └── ExpireApprovalRequests.php
├── database/migrations/
│   ├── 0001_create_organizations_table.php
│   ├── 0002_create_hives_table.php
│   ├── 0003_create_agents_table.php
│   ├── 0004_create_agent_permissions_table.php
│   ├── 0005_create_tasks_table.php
│   ├── 0006_create_events_table.php
│   ├── 0007_create_event_subscriptions_table.php
│   ├── 0008_create_knowledge_entries_table.php
│   ├── 0009_create_connectors_table.php
│   ├── 0010_create_service_connections_table.php
│   ├── 0011_create_action_policies_table.php
│   ├── 0012_create_approval_requests_table.php
│   ├── 0013_create_webhook_routes_table.php
│   ├── 0014_create_activity_log_table.php
│   ├── 0015_create_proxy_log_table.php
│   ├── 0016_create_workflows_table.php
│   └── cloud/
│       ├── 0101_create_users_table.php
│       ├── 0102_create_org_members_table.php
│       ├── 0103_create_hive_access_table.php
│       └── 0104_create_usage_records_table.php
├── routes/
│   ├── api.php
│   ├── api_cloud.php
│   ├── web.php
│   ├── web_cloud.php
│   └── channels.php
├── resources/js/
│   ├── Pages/
│   │   ├── Dashboard.jsx
│   │   ├── Hives/
│   │   │   ├── Selector.jsx
│   │   │   └── Settings.jsx
│   │   ├── Agents/
│   │   ├── Tasks/
│   │   ├── CrossHive/
│   │   │   └── Monitor.jsx
│   │   ├── Approvals/
│   │   ├── Services/
│   │   ├── Knowledge/
│   │   ├── Webhooks/
│   │   ├── Config/
│   │   ├── Activity/
│   │   └── Cloud/
│   │       ├── Billing/
│   │       ├── Organization/
│   │       ├── Onboarding/
│   │       └── Marketplace/
│   ├── Components/
│   │   ├── HiveSelector.jsx
│   │   ├── AgentCard.jsx
│   │   ├── TaskKanban.jsx
│   │   ├── CrossHiveMap.jsx
│   │   └── ...
│   └── Layouts/
│       └── AppLayout.jsx
├── config/
│   ├── platform.php
│   ├── plans.php
│   ├── horizon.php
│   └── reverb.php
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── ...
├── sdk/
│   ├── python/
│   ├── node/
│   └── shell/
├── tests/
│   ├── Feature/
│   │   ├── Api/
│   │   │   ├── TaskLifecycleTest.php
│   │   │   ├── CrossHiveTaskTest.php
│   │   │   ├── HiveScopingTest.php
│   │   │   └── ...
│   │   └── ...
│   └── Unit/
│       └── ...
├── CLAUDE.md
├── .env.example
├── composer.json
└── package.json
```

---

## 17. Implementation Phases

### Phase 1: Core MVP — ~2-3 weeks
**Tasks flow between agents in a single hive, dashboard shows state.**

1. Laravel scaffold + Docker Compose (CE mode — implicit organization + hive)
2. Core migrations: agents, permissions, tasks, knowledge, activity_log
3. Agent API: register, heartbeat, task CRUD, poll, claim, complete
4. Task router by agent_id or capability
5. Atomic claiming + timeout/retry scheduler
6. Knowledge Store with hive scope
7. Agent liveness monitoring
8. Dashboard: agent list, task board, activity feed
9. Reverb WebSocket
10. Horizon integration
11. Python SDK + shell client

### Phase 2: Service Proxy & Security — ~2-3 weeks
**Secure credential-free service access.**

1. Credential vault + service connections
2. Service proxy with auth injection
3. Action policies (policy engine)
4. Approval flow
5. Proxy logging
6. Connectors: interface + GitHub + Slack
7. Agent-writable connectors
8. Dashboard: proxy monitor, approval queue, policy editor

### Phase 3: Webhooks & Events — ~1-2 weeks
**External world triggers agents.**

1. Webhook receiver with connector validation
2. Webhook routes with field filters
3. Event model + subscriptions + poll
4. Dashboard: webhook monitor, route builder

### Phase 4: Multi-Hive — ~2 weeks
**Multiple projects within one installation.**

1. Hive model + BelongsToHive trait
2. Hive-scoped queries on all core resources
3. Hive selector in dashboard
4. Cross-hive task creation + permission check
5. Cross-hive events (platform.* prefix)
6. Organization-scoped knowledge
7. Cross-hive monitor dashboard
8. Webhook routes targeting specific hives

### Phase 5: Cloud Foundation — ~2-3 weeks
**Multi-tenant SaaS running.**

1. Organization model + BelongsToOrganization trait
2. Tenant resolution middleware
3. User auth (Breeze + Socialite)
4. Team management + hive access control
5. Per-org credential encryption

### Phase 6: Billing & Onboarding — ~2 weeks
**Users can sign up, pay, get started.**

1. Stripe integration (Cashier)
2. Plan limits + quota enforcement
3. Usage metering
4. Onboarding wizard
5. Dashboard: billing, usage

### Phase 7: Marketplace & Workflows — ~2-3 weeks
1. Connector marketplace
2. Workflow engine (YAML → trigger → steps)
3. Dashboard: marketplace, workflow designer

### Phase 8: Enterprise — ongoing
1. SSO, audit export, data residency, rate limiting, SOC 2

> Phases 1B–5B run in parallel with Phases 5–8. They extend the core platform
> with advanced task semantics, inboxes, observability, and visual tooling.

### Phase 1B: Task System Hardening
**Reliable task processing and operational safety.**

1. Task failure policies & progress/task timeouts (§23)
2. Dead letter queue & requeue API
3. Idempotency keys (dedup)
4. Retry with exponential backoff
5. Scheduled/recurring tasks (§25)
6. Agent drain mode (§25)
7. API key rotation with grace period
8. Per-agent rate limiting
9. Best-effort tasks & expiry
10. Agent pool health metrics (§25)

### Phase 2B: Data & Inbound
**Simple inbound webhooks and file handling.**

1. Inbox model + receiver controller (§22)
2. Inbox management API + security (HMAC, IP allowlist)
3. Inbox rate limiting, deduplication, payload transform
4. Inbox request logging + dashboard page
5. File attachments: migration, API, storage backend (§25)

### Phase 3B: Advanced Orchestration
**Composable multi-agent task patterns.**

1. Fan-out child tasks & completion policies (§23)
2. Fan-in result aggregation
3. Task dependencies (depends_on + waiting status)
4. Backpressure & queue depth limits
5. Task contracts (JSON Schema validation) (§25)
6. Service Worker SDK conventions & service catalog (§24)

### Phase 4B: Observability & DevEx
**Monitoring, debugging, and visual topology.**

1. Prometheus metrics endpoint (§25)
2. System event webhooks (§25)
3. Agent context threads (§25)
4. Sandbox / dry-run mode (§25)
5. Hive Map: topology API + React Flow graph (§26)
6. Hive Map: node panels, live WebSocket, organization view

### Phase 5B: Intelligence
**LLM awareness, replay, and marketplace.**

1. LLM usage tracking & cost dashboard (§25)
2. Task replay / time travel (§25)
3. Agent template marketplace (§25)

---

## 18. Coding Standards & Project Setup

See [CLAUDE.md](../CLAUDE.md) for coding standards, project structure, testing, and local development setup.

---

## 19. Environment Variables

```env
# === Core ===
APP_NAME=Superpos
APP_URL=http://localhost:8000
APP_KEY=

SUPERPOS_EDITION=ce                        # 'ce' or 'cloud'

DB_CONNECTION=pgsql
DB_HOST=postgres
DB_PORT=5432
DB_DATABASE=platform
DB_USERNAME=platform
DB_PASSWORD=secret

REDIS_HOST=redis
REDIS_PORT=6379

QUEUE_CONNECTION=redis
HORIZON_PREFIX=platform_horizon:

REVERB_APP_ID=platform
REVERB_APP_KEY=platform-key
REVERB_APP_SECRET=platform-secret

SUPERPOS_HEARTBEAT_TIMEOUT=30
SUPERPOS_HEARTBEAT_DEAD=60
SUPERPOS_DEFAULT_TASK_TIMEOUT=300
SUPERPOS_DEFAULT_POLL_INTERVAL=3000
SUPERPOS_IDLE_POLL_INTERVAL=5000
SUPERPOS_DEEP_IDLE_POLL_INTERVAL=10000
SUPERPOS_APPROVAL_EXPIRY=3600
SUPERPOS_SHORT_TOKEN_TTL=900

# === Cloud-only ===
STRIPE_KEY=
STRIPE_SECRET=
STRIPE_WEBHOOK_SECRET=

GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GOOGLE_SSO_CLIENT_ID=
GOOGLE_SSO_CLIENT_SECRET=

SUPERPOS_MASTER_ENCRYPTION_KEY=
SUPERPOS_DEFAULT_REGION=us
```

---

## 20. Security Considerations

1. **Credential isolation** — encrypted at rest; Cloud: per-org keys
2. **Agent tokens** — hashed (Sanctum), scoped to hive
3. **Hive isolation** — BelongsToHive global scope prevents cross-hive data leaks
4. **Cross-hive control** — explicit permission required, all cross-hive activity logged
5. **Action policies** — per-agent firewall: deny > approval > allow > deny
6. **Approval flow** — dangerous ops need human confirmation
7. **Webhook signatures** — validated per connector
8. **No inbound to agents** — outbound poll only
9. **Proxy logging** — every request logged at org level
10. **Connector sandboxing** — validated before activation
11. **Rate limiting** — per-agent + per-org (Cloud)
12. **Tenant isolation** — BelongsToOrganization global scope (Cloud)
13. **HTTPS only** in production
14. **Input validation** — Form Requests everywhere

---

## 21. Open Source Strategy

### Repository
- Main repo (public, MIT): full CE + Cloud code
- Transparency builds trust; enterprises can self-host Cloud features

### Community
1. Connector contributions — lowest barrier, highest value
2. SDK contributions — Go, Rust, Java, etc.
3. Templates — pre-built workflows for common use cases
4. Documentation — guides for different agent platforms
5. Discord community

### Monetization
1. Free Cloud tier → onboards users
2. Pro Cloud → teams with real usage
3. Enterprise → SSO, compliance, support
4. Marketplace fees → premium connectors (future)
5. Managed agents → hosted agents in Superpos cloud (future)

---

## 22. Inbox (Simple Webhook-to-Task)

> Full spec: [docs/features/list-1/FEATURE_INBOX.md](features/list-1/FEATURE_INBOX.md)

An **Inbox** is a pre-authenticated URL that converts any HTTP POST into a task — no connector, no route config, no signature validation required. Just URL → task.

```
POST https://acme.superpos.ai/inbox/inb_k7Xm9pQ2
{ "server": "web-03", "alert": "CPU > 95%" }
→ Task created in target hive, agent picks it up
```

### Key Features

- **Zero-config start** — create an inbox, get a URL, paste it anywhere (CI, Zapier, monitoring)
- **Optional payload transform** — JSONPath extraction maps webhook fields to task fields
- **Deduplication** — configurable field-based dedup with time window (reuses idempotency key infra)
- **Rate limiting** — per-inbox request rate and payload size limits

### Security Tiers

| Tier | Mechanism | Use Case |
|------|-----------|----------|
| 1 | URL-only (random slug) | Internal tools, prototyping |
| 2 | HMAC shared secret | GitHub/Stripe-style webhook sources |
| 3 | Secret + IP allowlist | Production services with known IP ranges |

### Relationship to Webhook Routes

Inbox is the **simple path**; Webhook Routes (§13) are the **powerful path**. Both create tasks in the same queue. Start with Inbox (5 seconds to set up), graduate to Webhook Routes as needs grow.

### Schema

New tables: `inboxes` (config, security, limits, transform) and `inbox_log` (request audit trail). Both scoped via `BelongsToOrganization` + `BelongsToHive`.

### API

- `POST/GET/PATCH/DELETE /api/v1/inboxes` — CRUD management
- `POST /api/v1/inboxes/{id}/rotate` — rotate slug (new URL)
- `GET /api/v1/inboxes/{id}/log` — request log
- `POST /inbox/{slug}` — public receiver endpoint (no auth token needed)

---

## 23. Advanced Task Semantics

> Full spec: [docs/features/list-1/FEATURE_TASK_SEMANTICS.md](features/list-1/FEATURE_TASK_SEMANTICS.md)

Extensions to the core task system that enable reliable, composable multi-agent workflows.

### Fan-Out / Fan-In

A parent task spawns N child tasks. Children enter the queue independently — different agents claim them. Parent tracks aggregate completion via **completion policies**.

| Policy | Parent completes when... |
|--------|-------------------------|
| `all` (default) | Every child completed |
| `any` | First child completed |
| `count(n)` | N children completed |
| `ratio(0.8)` | 80% of children completed |
| `custom` | External aggregator agent decides |

Options: `fail_fast` (cancel siblings on first failure), `cancel_remaining` (stop others once policy is met).

### Failure Policies

Per-task failure configuration with two timeout clocks:

- **`progress_timeout`** — resets on every heartbeat/progress update; detects dead/stuck agents
- **`task_timeout`** — absolute deadline; catches infinite-loop agents

On timeout actions: `reassign`, `fail`, `retry`, `notify`. Retry supports exponential backoff with configurable base/max delays. After `max_retries` exceeded: `fail`, `dead_letter`, or `notify`.

### Idempotency Keys

System-level deduplication: `idempotency_key` → `task_id` mapping prevents duplicate task creation. Keys expire after configurable TTL (default 24h). Complements agent-side idempotency for side-effect safety.

### Task Dependencies

Declarative `depends_on` with auto-trigger:

1. Task created with status `waiting`
2. System monitors dependency tasks
3. When all dependencies complete → task moves to `pending` with results injected into payload
4. Agent claims task with all dependency data ready

Supports dynamic dependency addition while task is in `waiting` status.

### Backpressure & Queue Depth Limits

Per-hive and per-task-type queue limits stored in `hives.settings`:

| Action | Behavior |
|--------|----------|
| `accept_warn` | Accept task, return warning header |
| `throttle` | Accept task, increase `next_poll_ms` |
| `reject` | Return 429 with `retry_after` |
| `queue` | Accept into overflow queue at lower priority |

Enhanced poll response includes `queue_status` with pressure indicator (`low` → `normal` → `high` → `critical`).

### Guaranteed vs Best-Effort Delivery

| Aspect | `at_least_once` | `best_effort` |
|--------|-----------------|---------------|
| On timeout | Always retry/reassign | May drop |
| Max retries | Respected, then dead_letter | Respected, then fail |
| Expiry | No auto-expire | Optional `expires_at` |

### Updated Task State Machine

New statuses: `waiting` (unmet dependencies), `awaiting_children` (parent waiting for completion policy), `expired` (best-effort task unclaimed past deadline), `dead_letter` (failed after all retries, needs manual attention).

### Schema Changes

- `tasks` table additions: `failure_policy`, `completion_policy`, `guarantee`, `last_progress_at`, `retry_after`, `expires_at`, `children_summary`, `on_complete` (all JSONB/columns)
- New tables: `task_dependencies` (DAG edges), `task_idempotency` (dedup keys with TTL)

---

## 24. Service Workers (Async Data Fetching)

> Full spec: [docs/features/list-1/FEATURE_SERVICE_WORKERS.md](features/list-1/FEATURE_SERVICE_WORKERS.md)

**Service Workers** are lightweight agents that bridge the task bus and external APIs for complex, async data operations. They are regular agents registered with `data:*` capabilities (e.g., `data:gmail`, `data:jira`, `data:sheets`).

### How It Differs from Service Proxy

| Aspect | Service Proxy | Service Worker |
|--------|--------------|----------------|
| Complexity | Single HTTP request | Multi-step operations |
| Blocking | Sync (agent waits) | Fully async (fire and forget) |
| Pagination | Not supported | Handled by worker |
| Transformation | Raw API response | Structured, filtered, cleaned |

### Data Request Protocol

1. AI agent creates `data_request` task targeting a `data:*` capability
2. Agent continues working (does **not** block)
3. Service Worker claims task, paginates/filters/transforms data
4. Worker completes task with structured result
5. AI agent retrieves result on next poll cycle

### Delivery Modes

| Mode | When to use |
|------|-------------|
| `task_result` | Small results (<1MB) — data in task result JSONB |
| `knowledge` | Large results — worker writes to Knowledge Store |
| `stream` | Ongoing data — worker creates child tasks per batch |

### Service Catalog Discovery

Agents discover available data services via `GET /api/v1/agents?capability=data:*`. Each worker publishes `supported_operations` in its metadata with parameter schemas.

### Built-in Workers

Gmail, Google Sheets, Jira, Slack, GitHub, generic HTTP, and SQL workers — each a standalone script (~30 lines) using the Superpos SDK.

### Implementation Notes

No new tables needed — uses existing `agents` (with `type: service_worker`), `tasks` (with `type: data_request`), `knowledge_entries`, and `action_policies`. New SDK convenience methods: `client.data_request()`, `client.discover_services()`.

---

## 25. Platform Enhancements

> Full spec: [docs/features/list-1/FEATURE_PLATFORM_ENHANCEMENTS.md](features/list-1/FEATURE_PLATFORM_ENHANCEMENTS.md)

Thirteen platform improvements grouped by implementation phase.

### Phase 1 Enhancements (MVP-critical)

**Scheduled / Recurring Tasks** — A `Schedule` model creates tasks on cron, interval, or one-shot triggers. Supports overlap policies (`skip`, `allow`, `cancel`). New tables: `schedules`, `schedule_log`. API: full CRUD + manual trigger/pause/resume. Permission: `manage:schedules`.

**Agent Drain Mode** — Graceful shutdown protocol: agent calls `POST /agents/drain`, status → `draining`, poll returns empty, agent finishes current tasks, exits cleanly. Prevents wasted retries during deploys. Schema: `drain_deadline` + `drain_reason` on agents table.

**File / Blob Storage** — `Attachments` stored in object storage (local disk for CE, S3 for Cloud), referenced from tasks and knowledge entries. API: upload, download, metadata, per-task listing. New table: `attachments`. Configurable max size, allowed types, retention.

**Agent Pool Health** — Derived concept (no new tables): agents sharing a capability in a hive = pool. Health metrics API returns agent counts, queue depth, avg wait/completion times, and health status (`healthy`/`busy`/`overloaded`/`degraded`/`critical`).

### Phase 2-3 Enhancements

**Observability & Metrics Export** — Prometheus endpoint (`GET /metrics`) exposing task counts, durations, agent status, proxy requests, dead letter depth. System event webhooks (agent.offline, task.dead_letter, pool.overloaded) to Slack/Discord/PagerDuty.

**Agent Context Threads** — Conversation chains between agents. A `Thread` accumulates messages across related tasks. Agent claiming a task with `thread_id` receives full history. New tables: `threads`, `thread_messages`.

**Task Contracts (JSON Schema)** — Optional payload/result schemas per task type. Validation on create (payload) and complete (result). New table: `task_types`. Doubles as task catalog for discovery.

**API Key Rotation** — `POST /agents/{id}/rotate-token` with grace period — both old and new tokens valid during overlap. Schema: `previous_token_hash` + `previous_token_expires_at`.

**Per-Agent Rate Limiting** — Redis sliding window counters per agent per action (`tasks_create`, `proxy_requests`, `knowledge_writes`). Defaults from hive settings, overridable per agent.

### Phase 4+ Enhancements (Competitive Advantages)

**Sandbox / Dry-Run Mode** — Hive-level sandbox flag: tasks processed normally, proxy returns mocks, approvals auto-approve, no usage metering. Dry-run APIs for policies and webhook routes.

**LLM-Aware Features** — Token usage reporting in heartbeat and task completion. Dashboard: per-agent/per-task-type cost tracking, budget alerts. Model routing hints in task payload. New table: `llm_usage`.

**Task Replay / Time Travel** — Full execution trace assembled from activity_log + proxy_log + knowledge_entries. Replay creates sandbox task with same inputs and recorded proxy responses. Run comparison API.

**Agent Template Marketplace** — YAML manifests bundling agent registration, service connections, inboxes, action policies, and task type schemas. One-click install from marketplace. New table: `agent_templates`.

---

## 26. Hive Map (Visual Topology)

> Full spec: [docs/features/list-1/FEATURE_HIVE_MAP.md](features/list-1/FEATURE_HIVE_MAP.md)

An interactive, real-time graph showing every node (agent, service, inbox, schedule, hive) and every connection (task flow, proxy access, webhook routes, cross-hive links) in the system.

### Three Zoom Levels

**Organization View** — All hives as cards with summary stats (agent count, task count, health), service connections shared at top, cross-hive edges with volume indicators. Click hive → zoom in.

**Hive View** — Full internal topology: agents as nodes with status/task badges, inboxes on the left (triggers in), services on the right (proxy out), task-flow edges between agents, cross-hive outbound links, schedule and knowledge panels. Click node → detail panel.

**Agent View** — Slide-out detail panel: status, capabilities, permissions, current tasks with progress bars, inbound/outbound connections with daily volumes, LLM cost summary.

### Live Data Flow Animation

Edges show live data flowing — pulse dots travel along connections on each webhook, task creation, or proxy request. Edge thickness scales with volume. Error indication: red pulses for failures, red glow for dead letter tasks.

### Interactive Features

- **Drag & rearrange** — force-directed layout with user-saved positions
- **Click node** → detail panel (agent, service, inbox, schedule, hive)
- **Click edge** → flow detail (volume, completion stats, recent tasks)
- **Filter & highlight** — by status, activity, connectivity path
- **Time slider** — scrub through historical topology for post-mortems
- **Quick actions** — right-click context menu (drain agent, test connection, copy inbox URL)

### Frontend Implementation

Built with **React Flow** (reactflow.dev). Custom node types (AgentNode, ServiceNode, InboxNode, ScheduleNode, HiveCard) and custom animated edge types. Layout via dagre/elkjs. Live updates via Laravel Reverb WebSocket channels (`hive.{id}.topology`, `org.{id}.topology`).

### Data Sources

Assembled from existing tables — no new infrastructure:

| Map Element | Source |
|-------------|--------|
| Agent nodes | `agents` table |
| Service nodes | `service_connections` table |
| Inbox nodes | `inboxes` table |
| Schedule nodes | `schedules` table |
| Edges (task flow) | `tasks` aggregated by source/target agent |
| Edges (proxy) | `proxy_log` aggregated by agent + service |
| Live updates | Activity events via Reverb |

### API

- `GET /api/v1/hives/{slug}/topology?timeframe=24h` — hive-level graph (nodes + edges)
- `GET /api/v1/topology?timeframe=24h` — org-level graph (hive cards + cross-hive edges)

---

*Document version: 4.2*
*Last updated: 2026-02-27*
