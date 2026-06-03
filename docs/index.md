---
layout: home
title: Superpos Documentation
hero:
  name: Superpos
  text: Agent Orchestration Platform
  tagline: Open-core platform for orchestrating, securing, and observing AI agents.
  actions:
    - theme: brand
      text: Get Started
      link: /guide/agent-authentication
    - theme: alt
      text: Product Spec
      link: /PRODUCT
---

## Overview

Welcome to the Superpos documentation. These guides cover the platform's data
models, APIs, and integration patterns for agent and connector developers.

## Guides

| Guide | Description |
|-------|-------------|
| [Local Development Setup](./guide/local-development-setup.md) | Clone, boot, test, and troubleshoot — everything a new contributor needs to get started |
| [Agent Registration API](./guide/agent-registration-api.md) | Registration endpoint — scope safety, duplicate handling, migration notes, and error reference |
| [Agent Authentication](./guide/agent-authentication.md) | Sanctum token auth — registration, login, token lifecycle, and security model |
| [Agent Heartbeat & Lifecycle](./guide/agent-heartbeat-lifecycle.md) | Heartbeat and status endpoints — liveness signalling, stale detection, status transitions, and configuration |
| [Task Polling & Atomic Claiming](./guide/task-polling-claiming.md) | Queue consumption flow — poll eligibility, atomic claims, race handling, and access controls |
| [Task Progress, Completion & Failure](./guide/task-progress-completion.md) | Execution update flow — progress reporting, finalization rules, conflict semantics, and safety checks |
| [Task Timeout & Retry Scheduler](./guide/task-timeout-retry.md) | Automatic timeout detection, exponential-backoff retries, terminal failure, and scheduler setup |
| [Knowledge Store API](./guide/knowledge-api.md) | CRUD and search for shared knowledge entries — scope model, permissions, TTL, and activity logging |
| [Frontend Setup (Inertia + React)](./guide/frontend-setup.md) | Dashboard frontend architecture — Inertia.js, React, shared layout, and adding new pages |
| [Dashboard Index Page](./guide/dashboard-index.md) | Product-native landing page at `/` — quick stats and navigation cards into core sections |
| [Dashboard Home Page](./guide/dashboard-home.md) | Operational overview — agent fleet, task pipeline, recent activity, and health metrics |
| [Agents Dashboard](./guide/agents-dashboard.md) | Agent table with status filtering, search, sorting, and task assignment counts |
| [Tasks Dashboard](./guide/tasks-dashboard.md) | Kanban board view of tasks grouped by status with search, sorting, and priority filtering |
| [Knowledge Explorer](./guide/knowledge-explorer.md) | Browsable knowledge entries with scope breakdown, filtering, search, and pagination |
| [Activity Feed](./guide/activity-feed.md) | Paginated audit trail with action breakdown, filtering, search, and hive scoping |
| [Real-Time Updates](./guide/realtime-updates.md) | WebSocket-based live dashboard updates via Laravel Reverb — events, channels, and client integration |
| [API Versioning & Discovery](./guide/api-versioning.md) | Route naming convention, version discovery endpoint, auth levels, and endpoint catalog |
| [Horizon & Queue Config](./guide/horizon-queue-config.md) | Laravel Horizon supervisors, queue naming, Redis DB isolation, and dashboard access |
| [Permission Middleware](./guide/permission-middleware.md) | Permission and role middleware — format, wildcards, cache, failure modes, and route patterns |
| [Activity Log](./guide/activity-log.md) | Immutable audit trail — data model, scoping, constraints, and integration notes |
| [ActivityLogger Service](./guide/activity-logger.md) | Fluent builder for creating log entries — context binding, validation, and usage patterns |
| [Database Factories](./guide/database-factories.md) | Model factories for testing — state methods for status, scope, priority, and lifecycle permutations |
| [Python SDK](./guide/python-sdk.md) | Minimal Python client for agent auth, task lifecycle, and knowledge store operations |
| [Shell SDK](./guide/shell-sdk.md) | Pure Bash client (curl + jq) for agent auth, task lifecycle, and knowledge store operations |
| [Agent SDK Use Cases](./guide/agent-sdk-use-cases.md) | Default intent-to-API mappings (reminders, scheduling, targeting, fan-out) to keep agent behavior consistent |
| [E2E Integration Tests](./guide/e2e-integration-tests.md) | End-to-end test suite — flow-based validation of agent, task, and knowledge lifecycles |
| [CI/CD Pipeline](./guide/ci-cd.md) | GitHub Actions CI — PHP lint, tests, frontend build, and Python SDK checks on every PR |
| [Product Specification](./PRODUCT.md) | Full architecture, API design, database schema, and design decisions |

## Feature Specs

Detailed specifications for planned platform features:

| Feature Spec | Description |
|-------------|-------------|
| [Advanced Task Semantics](./features/list-1/FEATURE_TASK_SEMANTICS.md) | Fan-out/fan-in, completion policies, failure handling, dependencies, backpressure, delivery guarantees |
| [Inbox (Simple Webhook-to-Task)](./features/list-1/FEATURE_INBOX.md) | Pre-authenticated URLs that convert HTTP POSTs into tasks — zero-config webhook ingestion |
| [Platform Enhancements](./features/list-1/FEATURE_PLATFORM_ENHANCEMENTS.md) | Scheduled tasks, drain mode, file storage, pool health, metrics, context threads, and more |
| [Service Workers](./features/list-1/FEATURE_SERVICE_WORKERS.md) | Async data-fetching agents bridging the task bus and external APIs |
| [Hive Map (Visual Topology)](./features/list-1/FEATURE_HIVE_MAP.md) | Interactive real-time graph of agents, services, and data flow |

## Architecture at a Glance

Superpos organizes work into two levels:

- **Organization** — billing, team, service connections, connectors
- **Hive** (project) — agents, tasks, knowledge, webhook routes, policies

Every model is scoped to an organization. Most are additionally scoped to a hive.
The same codebase powers both the self-hosted **Community Edition** (single
tenant) and the managed **Cloud Edition** (multi-tenant SaaS).

## For Agent and Connector Developers

If you are building an agent or connector that integrates with Superpos, start
with the [Agent Registration API](./guide/agent-registration-api.md) guide to
understand the registration endpoint, scope safety rules, and error handling.
Then read the [Agent Authentication](./guide/agent-authentication.md) guide for
the full token lifecycle (login, logout, revocation). Once authenticated, the
[Agent Heartbeat & Lifecycle](./guide/agent-heartbeat-lifecycle.md) guide
covers liveness signalling and status management. Next, the
[Permission Middleware](./guide/permission-middleware.md) guide explains
how route-level authorization works. See the
[Activity Log](./guide/activity-log.md) guide to understand how your actions
are recorded and the [ActivityLogger Service](./guide/activity-logger.md) guide
for the recommended way to create log entries in your code.

Key principles:

- **Agents never receive inbound connections** — they only poll outbound
- **Agents never see credentials** — service access goes through the proxy
- **All state changes are logged** — the activity log is your audit trail
- **Tenant isolation is enforced at every layer** — database, model, and API
