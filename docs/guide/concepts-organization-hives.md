# Organizations & Hives

Superpos uses a two-level hierarchy to organize your work: **organizations** at the top, and **hives** inside them. This page explains what each level does and how they relate.

## Organizations

An organization is your top-level workspace. It represents your company, team, or individual account. Everything in Superpos lives inside an organization.

An organization owns:

- **Team members** -- the people who can access the dashboard and manage resources
- **Billing** -- subscription plan, usage, invoices (Cloud edition)
- **Service connections** -- credentials for external services (GitHub, Slack, cloud providers, etc.)
- **Connectors** -- integrations that map external events into Superpos tasks

Think of the organization as the administrative boundary. Billing is per-org, team membership is per-org, and service credentials are shared across the org.

## Hives

A hive is a project within an organization. It is the primary unit of isolation -- agents, tasks, knowledge, and policies are all scoped to a single hive.

Each hive has its own:

- **Task queue** -- pending work items that agents poll and claim
- **Agents** -- autonomous processes registered to this hive
- **Knowledge store** -- shared context entries (key-value with JSONB values)
- **Policies** -- rules governing what agents can do
- **Webhook routes** -- mappings from external events to tasks
- **Activity log** -- audit trail of everything that happens

## How They Relate

```
Organization ("Acme Corp")
  |
  +-- Hive: "Backend"         (API agents, deployment tasks)
  +-- Hive: "Mobile"          (iOS/Android build agents)
  +-- Hive: "Infrastructure"  (monitoring, provisioning agents)
```

One organization can contain many hives. Hives are fully isolated by default:

- An agent registered in the "Backend" hive cannot see or claim tasks in the "Mobile" hive.
- Knowledge entries scoped to a hive are invisible to agents in other hives.
- Activity logs are per-hive.

This isolation is enforced at the database level, not just in the API layer.

### Cross-Hive Communication

When you need agents in different hives to coordinate, Superpos supports explicit cross-hive permissions. An agent with the right permissions can:

- Create tasks in another hive (the task carries a `source_hive_id` for traceability)
- Publish events with a `platform.*` prefix that are broadcast across the entire organization
- Read organization-scoped knowledge entries

Cross-hive access is opt-in and audited. See [Events](./concepts-events.md) and [Knowledge Store](./concepts-knowledge.md) for details.

## CE vs Cloud

Superpos ships as two editions from the same codebase:

| | Community Edition (CE) | Cloud Edition |
|---|---|---|
| **Organizations** | One (implicit) | Multiple |
| **Hives** | One (implicit) | Unlimited |
| **Hosting** | Self-hosted | Managed SaaS |
| **Billing** | Free | Per-organization |

In CE, the organization and hive are created automatically. You never need to think about multi-tenancy -- just start registering agents and creating tasks. If you later migrate to Cloud, your existing hive becomes one of many.

In Cloud, you can create multiple organizations (e.g., one per client or department) and multiple hives within each.

## Switching Hives in the Dashboard

The Superpos dashboard shows a hive selector in the top navigation. Switching hives changes the context for everything you see -- task queues, agent lists, knowledge entries, and activity logs all update to reflect the selected hive.

In CE, the selector is hidden since there is only one hive.

## Example: Setting Up a Multi-Hive Organization

A company called "Acme" runs three engineering teams. Each team gets its own hive:

| Hive | Purpose | Agents |
|---|---|---|
| **Backend** | API development, deployments, code review | `code-review-agent`, `deploy-agent` |
| **Mobile** | iOS and Android builds, integration tests | `build-agent`, `test-agent` |
| **Infrastructure** | Monitoring, scaling, incident response | `monitor-agent`, `incident-agent` |

Each hive operates independently. The `deploy-agent` in Backend cannot accidentally claim a build task from Mobile. When a backend deployment completes and Mobile needs to run integration tests, the deploy agent publishes a cross-hive event that the Mobile test agent subscribes to.

This structure gives each team autonomy while keeping coordination explicit and auditable.
