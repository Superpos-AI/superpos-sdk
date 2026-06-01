# Real-Time Updates (WebSocket)

The Superpos dashboard receives real-time updates via WebSocket using
[Laravel Reverb](https://reverb.laravel.com). When agents create tasks,
change status, or generate activity, the dashboard reflects those changes
immediately without manual page refresh.

## Architecture

```
Agent → API → Controller → ActivityLogger → broadcast(event)
                                               ↓
                              Reverb WebSocket Server
                                               ↓
                              Dashboard (Laravel Echo) → React state update
```

All broadcast events are dispatched synchronously (`ShouldBroadcastNow`)
to avoid queue latency for dashboard updates.

## Channels

Events are broadcast on **private hive-scoped channels**:

```
private-hive.{hiveId}
```

Channel authorization ensures dashboard viewers only receive updates for
their current hive context. In CE mode, the default hive is always
authorized. Cloud mode will extend this with team membership checks
(Phase 5).

## Events

| Event | Broadcast Name | Trigger |
|-------|---------------|---------|
| `HiveActivityCreated` | `activity.created` | Every activity log entry with a hive |
| `AgentStatusChanged` | `agent.status_changed` | Agent status update API |
| `TaskStatusChanged` | `task.status_changed` | Task create/claim/progress/complete/fail |
| `KnowledgeEntryChanged` | `knowledge.changed` | Knowledge create/update/delete |

### Event Payloads

**activity.created**
```json
{
  "entry": {
    "id": "...",
    "action": "task.created",
    "agent_id": "...",
    "agent_name": "CodeBot",
    "task_id": "...",
    "task_type": "code-review",
    "details": {},
    "created_at": "2026-02-26T12:00:00+00:00"
  }
}
```

**agent.status_changed**
```json
{
  "agent": {
    "id": "...",
    "name": "CodeBot",
    "status": "online",
    "last_heartbeat": "2026-02-26T12:00:00+00:00"
  }
}
```

**task.status_changed**
```json
{
  "task": {
    "id": "...",
    "type": "code-review",
    "status": "in_progress",
    "priority": 2,
    "progress": 50,
    "claimed_by_name": "CodeBot",
    "created_at": "2026-02-26T12:00:00+00:00",
    "updated_at": "2026-02-26T12:01:00+00:00"
  }
}
```

**knowledge.changed**
```json
{
  "change_type": "created",
  "entry": {
    "id": "...",
    "namespace": null,
    "key": "config.timeout",
    "scope": "hive",
    "visibility": "public",
    "updated_at": "2026-02-26T12:00:00+00:00"
  }
}
```

## Client-Side Integration

### useHiveChannel Hook

The `useHiveChannel` React hook subscribes to the current hive's private
channel and dispatches events to handler callbacks:

```jsx
import useHiveChannel from '../Hooks/useHiveChannel';

export default function MyPage() {
    useHiveChannel({
        'activity.created': (data) => {
            console.log('New activity:', data.entry);
        },
        'task.status_changed': (data) => {
            console.log('Task update:', data.task);
        },
    });

    return <div>...</div>;
}
```

The hook automatically:
- Subscribes to the hive channel on mount
- Unsubscribes on unmount or hive change
- Uses stable refs to avoid re-subscription on handler changes

### Dashboard Pages

Each dashboard page subscribes to relevant events:

- **Dashboard home** — Live activity feed and task table updates
- **Activity feed** — New entries shown in a live banner above the table
- **Agents page** — Agent status badges update in real time
- **Tasks Kanban** — Update notification banner with refresh button

## Configuration

### Docker Compose

The Reverb container is pre-configured in `docker-compose.yml`:

```yaml
reverb:
  environment:
    REVERB_APP_ID: apiary
    REVERB_APP_KEY: apiary-key
    REVERB_APP_SECRET: apiary-secret
  ports:
    - '8081:8080'
```

The app container includes Vite env vars for the Echo client:

```yaml
app:
  environment:
    VITE_REVERB_APP_KEY: apiary-key
    VITE_REVERB_HOST: localhost
    VITE_REVERB_PORT: 8081
    VITE_REVERB_SCHEME: http
```

### Testing

Broadcasting is disabled in tests via `.env.testing`:

```
BROADCAST_CONNECTION=null
```

The channels file and broadcast routes gracefully skip registration
when the broadcast driver is null or log.

## Graceful Degradation

- If the Reverb server is unavailable, the dashboard continues to work
  normally with server-rendered data on page load
- `ShouldBroadcastNow` events fail silently when the broadcast driver
  is null (testing) or when the Reverb server is unreachable
- The `useHiveChannel` hook safely no-ops when `window.Echo` is not
  initialized
