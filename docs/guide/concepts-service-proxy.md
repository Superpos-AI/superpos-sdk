# Service Proxy

Superpos agents never see credentials. Instead, they access external services
through a **service proxy** that injects credentials on their behalf. This
zero-trust design means a compromised or misbehaving agent cannot leak tokens,
API keys, or passwords.

## How It Works

When an agent needs to call an external service (GitHub, Slack, Sentry, etc.),
it sends a request to the Superpos proxy endpoint rather than calling the
service directly:

```
Agent → POST /api/v1/proxy/{service_connection_name}/{path}
         │
         ▼
   Superpos evaluates action policies
         │
         ▼
   Credentials injected from service connection
         │
         ▼
   Request forwarded to external service
         │
         ▼
   Response returned to agent
```

The agent never constructs an `Authorization` header or handles secrets. It
simply describes *what* it wants to do, and Superpos handles the *how*.

## Service Connections

Service connections are created at the **organization level**. A single GitHub
token, for example, is configured once and shared across all hives in the
organization. Agents in any hive can use it (subject to policies).

Each connection stores:

- The target service base URL
- Encrypted credentials
- The authentication method

### Supported Auth Types

| Auth Type     | How Superpos Injects It                        |
|---------------|------------------------------------------------|
| Bearer token  | `Authorization: Bearer {token}` header         |
| Basic auth    | `Authorization: Basic {base64}` header         |
| API key       | Configurable header (e.g., `X-API-Key: {key}`) |
| OAuth         | Manages token refresh automatically             |

## Example: Creating a GitHub Issue

An agent wants to create an issue in the `acme/backend` repository.

**1. Agent sends request to the proxy:**

```http
POST /api/v1/proxy/github/repos/acme/backend/issues
Content-Type: application/json
# "github" here is the name given to the service connection, not the connector type.
# If your connection is named "gh-acme", the path would be /api/v1/proxy/gh-acme/...

{
  "title": "Fix login timeout",
  "body": "Users report session expires after 5 minutes"
}
```

**2. Superpos evaluates policies:**

The policy engine checks whether this agent is allowed to `POST` to
`/repos/acme/backend/issues` on the GitHub service. If the policy says
`require_approval`, the request is queued for human review. If it says `deny`,
the agent gets a 403.

**3. Credentials injected:**

Superpos retrieves the GitHub token from the service connection and adds:

```
Authorization: Bearer ghp_xxxxxxxxxxxxxxxxxxxx
```

**4. Request forwarded:**

The request goes to `https://api.github.com/repos/acme/backend/issues` with
the injected auth header.

**5. Response returned:**

The GitHub API response is passed back to the agent as-is.

## Audit Trail

Every proxied request is recorded in the **proxy log** with:

- Timestamp
- Agent ID
- Service and path
- HTTP method and status code
- Policy decision (allowed, denied, or approval-required)

This gives you a complete record of every external action your agents take.

## Built-in Connectors

Superpos ships with connectors for common services:

| Connector | Service URL                    |
|-----------|--------------------------------|
| GitHub    | `https://api.github.com`       |
| Slack     | `https://slack.com/api`        |
| Sentry    | `https://sentry.io/api`        |
| Gmail     | `https://gmail.googleapis.com` |
| Custom    | Any URL you configure          |

The **Custom** connector lets you connect agents to internal APIs, third-party
SaaS tools, or any HTTP service that accepts standard authentication.

## Key Takeaways

- Agents call `/api/v1/proxy/{connection_name}/{path}` -- `{connection_name}` is the
  name assigned to the service connection, not the connector type. They never handle credentials.
- Policies control what each agent can do on each service.
- Service connections are organization-wide; configure once, use everywhere.
- Every proxied request is logged for audit and debugging.
