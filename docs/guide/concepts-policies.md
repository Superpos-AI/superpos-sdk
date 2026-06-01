# Policies & Approvals

Action policies are firewall rules that control what each agent can do through
the [service proxy](./concepts-service-proxy.md). Policies are defined per
agent, per service, within each hive -- giving you fine-grained control over
external actions.

## Rule Evaluation

When an agent makes a proxy request, the policy engine evaluates rules in a
strict order. **The first matching rule wins:**

```
1. Deny rules        → block immediately (403)
2. Approval rules    → queue for human review
3. Allow rules       → forward the request
4. Default           → deny (fail-closed)
```

If no rule matches, the request is denied. This fail-closed design means agents
can only access services you explicitly permit.

## Rule Matching

Each rule specifies conditions that a proxy request must match:

| Field        | Description                              | Example                       |
|--------------|------------------------------------------|-------------------------------|
| HTTP method  | GET, POST, PUT, PATCH, DELETE, or `*`    | `POST`                        |
| URL pattern  | Path pattern (supports `*` wildcards)    | `/repos/*/issues`             |
| Body fields  | Optional JSON body field constraints     | `action = "opened"`           |

Rules are evaluated top-to-bottom within each priority tier (deny first, then
approval, then allow).

## Example Policies

### Allow read-only GitHub access

```json
{
  "effect": "allow",
  "method": "GET",
  "path": "*"
}
```

All GET requests to GitHub are permitted. The agent can list repos, read
issues, and fetch pull requests.

### Allow creating issues only

```json
{
  "effect": "allow",
  "method": "POST",
  "path": "/repos/*/issues"
}
```

The agent can create issues in any repository but cannot create pull requests,
comments, or modify repository settings.

### Require approval for destructive operations

```json
{
  "effect": "require_approval",
  "method": "DELETE",
  "path": "*"
}
```

Any DELETE request triggers the approval workflow. The request is paused until
a human reviews and approves it.

### Deny access to repository settings

```json
{
  "effect": "deny",
  "method": "*",
  "path": "/repos/*/settings"
}
```

No requests to repository settings are allowed, regardless of HTTP method.
Because deny rules are evaluated first, this takes precedence over any allow
rules that might also match.

## Combining Rules

A typical policy set for a CI agent might look like:

| Priority | Effect           | Method   | Path                   |
|----------|------------------|----------|------------------------|
| deny     | deny             | `*`      | `/repos/*/settings`    |
| approval | require_approval | `DELETE` | `*`                    |
| allow    | allow            | `GET`    | `*`                    |
| allow    | allow            | `POST`   | `/repos/*/issues`      |
| allow    | allow            | `POST`   | `/repos/*/pulls`       |
| default  | deny             | --       | --                     |

This agent can read anything, create issues and PRs, but needs human approval
to delete anything and is completely blocked from changing repository settings.

## Approval Workflow

When a policy evaluates to `require_approval`:

1. The proxy request is **paused** and an approval request is created.
2. The request appears in the **Approvals** section of the dashboard.
3. A team member reviews the request details (agent, service, method, path,
   body).
4. The reviewer **approves** or **denies** the request.
5. If approved, the original request is forwarded to the external service.
   If denied, the agent receives a 403.

### Approval Expiry

Pending approvals expire after a configurable timeout. If no one reviews the
request before it expires, it is automatically denied. This prevents stale
requests from being approved long after the original context has changed.

## Managing Policies

Policies are configured in the **Hive Settings** section of the dashboard.
Each hive maintains its own set of policies per agent and per service. You
can also manage policies through the API.

## Key Takeaways

- Policies follow a strict evaluation order: deny, then approval, then allow,
  then default deny.
- The first matching rule wins -- order your rules intentionally.
- Use `require_approval` for sensitive operations to keep a human in the loop.
- Every hive manages its own policies independently.
