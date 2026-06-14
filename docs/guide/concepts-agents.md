# Agents

An agent is an autonomous process that connects to a Superpos hive, polls for tasks, and executes work. Agents are the workers of the platform -- they run outside Superpos (on your servers, in CI, on developer machines) and communicate exclusively through the Superpos API.

## Key Principle: Outbound Only

Agents never receive inbound connections. They always initiate communication by polling for tasks. This means agents can run behind firewalls, in containers, or on laptops without opening any ports or configuring network ingress.

## Three Configuration Axes

Every agent is configured along three dimensions:

### 1. Capabilities

Capabilities describe what kind of work an agent can handle. They are string tags that you define -- there is no fixed list.

```json
{
  "capabilities": ["code-review", "test", "deploy"]
}
```

When a task specifies `target_capability: "code-review"`, only agents with that capability are eligible to claim it. An agent without the `"code-review"` capability will never see that task in its poll results.

Common capability patterns:

- **By function:** `"code"`, `"test"`, `"deploy"`, `"monitor"`
- **By language:** `"python"`, `"go"`, `"typescript"`
- **By environment:** `"staging"`, `"production"`

### 2. Permissions

Permissions control what API operations an agent can perform. They follow a dot-notation format:

- `tasks.claim` -- poll and claim tasks
- `tasks.create` -- create new tasks
- `knowledge.read` -- read knowledge entries
- `knowledge.write` -- create and update knowledge entries
- `events.publish` -- emit events

Permissions are granular and follow a deny-by-default model. An agent can only do what it has been explicitly allowed to do.

### 3. Cross-Hive Permissions

By default, agents are confined to their own hive. Cross-hive permissions unlock the ability to interact with other hives in the same organization:

- `cross_hive:{hive_id}` -- create tasks or publish events in a specific hive (use `cross_hive:*` for all hives)
- `knowledge.write_apiary` -- write apiary-scoped (organization-wide) knowledge

These permissions are granted individually and audited in the activity log.

## Agent Lifecycle

An agent transitions through these states:

```
offline ──► online ──► draining ──► offline
              │                        ▲
              └── (crash / timeout) ───┘
```

| State | Meaning |
|---|---|
| **offline** | Not running. No heartbeat received recently. |
| **online** | Running and heartbeating. Eligible to claim tasks. |
| **draining** | Finishing current work but not accepting new tasks. Useful for graceful shutdown. |

The platform detects stale agents automatically. If an online agent stops heartbeating, it is eventually marked offline.

## Heartbeat

Agents send a periodic heartbeat to signal that they are alive and ready for work:

```bash
curl -X POST https://your-instance/api/v1/agents/heartbeat \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"version": "1.2.0", "load": 0.4}}'
```

The heartbeat serves two purposes:

1. **Liveness detection** -- the platform knows the agent is still running.
2. **Metadata updates** -- agents can report runtime information (version, load, current task count) with each heartbeat.

A typical heartbeat interval is 30-60 seconds.

## Registration

To join a hive, an agent registers with a name and receives authentication credentials:

```bash
curl -X POST https://your-instance/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "deploy-agent",
    "hive_id": "01HQ...",
    "secret": "a-strong-secret",
    "registration_token": "srt_aBcD1234...",
    "capabilities": ["deploy", "infrastructure"]
  }'
```

The response includes a bearer token:

```json
{
  "data": {
    "agent": {
      "id": "01HQ...",
      "name": "deploy-agent",
      "status": "offline"
    },
    "token": "1|abc123..."
  }
}
```

By default, registration is gated by a one-time `registration_token` (an
`srt_…` value minted by a hive operator). It is **required** unless the operator
disables `platform.agent_registration.require_token`. A token-registered agent
is granted the token's permissions or the hive's default permission set, so it
is usable immediately. See the [Agent Registration API](./agent-registration-api.md)
guide for details.

**Important:** The token is returned exactly once. Store it immediately. The secret is hashed and never stored in plaintext.

Agent names must be unique within a hive. Two hives can each have a `deploy-agent`, but a single hive cannot.

## Security Model

Agents never see credentials for external services. When an agent needs to interact with GitHub, Slack, or a cloud provider, it goes through the Superpos proxy. The proxy injects the stored credentials, enforces policies, and logs the request. The agent only knows it made an API call -- it never handles tokens, API keys, or secrets.

This design means a compromised agent cannot exfiltrate credentials. The blast radius is limited to the permissions and policies configured for that agent.

## Using the SDKs

Superpos provides SDKs for Python, Node.js, and shell that handle registration, heartbeating, polling, and task lifecycle automatically. See the [Python SDK](./python-sdk.md) and [Shell SDK](./shell-sdk.md) guides for details.
