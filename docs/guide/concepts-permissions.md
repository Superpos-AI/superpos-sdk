# Permissions

Superpos uses a granular, string-based permission model to control what agents
can do. Every API call is checked against the agent's permissions -- if the
required permission is missing, the request is denied with a 403.

## Permission Format

Permissions are simple strings in `category.action` format:

```
tasks.create
knowledge.read
admin:*
```

**Dots and colons are interchangeable** -- `tasks.create` and `tasks:create`
are equivalent. Superpos normalizes them internally.

## Wildcards

Wildcards grant all permissions within a category:

| Permission    | Grants                                  |
|---------------|-----------------------------------------|
| `tasks.*`     | All task permissions (create, claim, read, update, manage) |
| `knowledge.*` | All knowledge permissions               |
| `services:*`  | Access to all service proxy connections  |
| `cross_hive:*`| Cross-hive access to all hives          |
| `admin:*`     | Full superuser access (all permissions) |

The `admin:*` wildcard bypasses all permission checks. Use it sparingly.

## Default Agent Permissions

Agents registered via the **API** (`POST /api/v1/agents/register`) start with
**no permissions**. An administrator must grant the required permissions before
the agent can call any privileged endpoint.

Agents created through the **dashboard UI** receive a set of defaults
(unless the operator unchecks "Grant default permissions"):

| Permission         | Purpose                            |
|--------------------|------------------------------------|
| `tasks.claim`      | Claim tasks from the queue         |
| `tasks.update`     | Update task status and progress    |
| `tasks.create`     | Create new tasks                   |
| `tasks.read`       | Read task details                  |
| `knowledge.read`   | Read knowledge entries             |
| `knowledge.write`  | Write knowledge entries            |
| `events.publish`   | Publish events                     |
| `events.poll`      | Poll for events                    |

API-registered agents must have these permissions granted explicitly via the
dashboard before they can participate in the standard task loop.

## Full Permission Reference

### Tasks

| Permission      | Description                                    |
|-----------------|------------------------------------------------|
| `tasks.create`  | Create new tasks in the hive                   |
| `tasks.claim`   | Claim pending tasks from the queue             |
| `tasks.read`    | Read task details and list tasks               |
| `tasks.update`  | Update task status, progress, and result       |
| `tasks.manage`  | Administrative task operations (delete, reassign) |

### Knowledge

| Permission              | Description                              |
|-------------------------|------------------------------------------|
| `knowledge.read`        | Read knowledge entries                   |
| `knowledge.write`       | Create and update hive-scoped entries    |
| `knowledge.write_apiary`| Write organization-scoped entries        |
| `knowledge.manage`      | Delete entries and manage settings       |

### Events

| Permission       | Description                              |
|------------------|------------------------------------------|
| `events.publish` | Publish events to the hive stream        |
| `events.poll`    | Poll for events                          |

### Services (Proxy)

| Permission         | Description                                |
|--------------------|--------------------------------------------|
| `services:{id}`    | Access a specific service connection       |
| `services:*`       | Access all service connections              |

Service permissions control which proxy connections an agent can use.
Fine-grained access control within a service is handled by
[action policies](./concepts-policies.md).

### Webhooks

| Permission       | Description                                |
|------------------|--------------------------------------------|
| `webhooks:manage`| Create, update, and delete webhook routes  |
| `webhooks:*`     | All webhook permissions                    |

### Connectors

| Permission          | Description                              |
|---------------------|------------------------------------------|
| `manage:connectors` | Create, update, and delete connectors    |

### Cross-Hive

| Permission              | Description                            |
|-------------------------|----------------------------------------|
| `cross_hive:{hive_id}`  | Operate in a specific target hive      |
| `cross_hive:*`          | Operate in any hive in the organization|

See [Cross-Hive Communication](./concepts-cross-hive.md) for details.

### Admin

| Permission | Description                                       |
|------------|---------------------------------------------------|
| `admin:*`  | Full superuser access; bypasses all checks        |

## Granting Permissions

Permissions are managed through the **dashboard UI**.

Navigate to your hive, select an agent, and manage permissions from the agent's
permission list. You can grant or revoke individual permissions, or use the
"Grant default permissions" option when creating an agent to assign the standard
set listed above.

Event subscriptions (`/api/v1/agents/subscriptions`) do not require a specific
permission -- any authenticated agent can manage its own hive-scoped subscriptions.
However, creating an apiary-scoped subscription (`scope="apiary"`) requires
`cross_hive:*` or `cross_hive:{hive_id}` permission.

## Fail-Closed Design

The permission system is **fail-closed**: if a required permission is not
found in the agent's permission set, the request is denied.

Evaluation order: `admin:*` check, then exact match, then category wildcard
(e.g., `tasks.*`), then deny with 403.

## Key Takeaways

- Permissions are simple strings: `category.action`.
- Dots and colons are interchangeable separators.
- Wildcards (`tasks.*`, `admin:*`) grant broad access within a category.
- Dashboard-created agents get sensible defaults; API-registered agents start with none.
- Missing permission = 403. Always fail-closed.
