# Database Factories

Laravel model factories for all core Superpos models. Use these in tests to
create valid model instances with sensible defaults and chainable state
methods for lifecycle, status, and scope permutations.

## Quick start

```php
use App\Models\{Superpos, Hive, Agent, Task};

// Full chain — factory auto-creates parent models
$agent = Agent::factory()->create();

// Explicit parent — share apiary/hive across models
$apiary = Superpos::factory()->create();
$hive   = Hive::factory()->create(['superpos_id' => $apiary->id]);
$agent  = Agent::factory()->forHive($hive)->create();
$task   = Task::factory()->forHive($hive)->create();
```

## Available factories

### ApiaryFactory

```php
Superpos::factory()->create();                           // free plan
Superpos::factory()->pro()->create();                    // pro plan
Superpos::factory()->cloud()->create();                  // cloud plan
Superpos::factory()->withOwner()->create();              // creates User owner
Superpos::factory()->onTrial()->create();                // 14-day trial
Superpos::factory()->withSettings(['k' => 'v'])->create();
```

### HiveFactory

```php
Hive::factory()->create();                             // active, auto-creates Superpos
Hive::factory()->inactive()->create();                 // is_active = false
Hive::factory()->withDescription('My hive')->create();
Hive::factory()->withSettings(['k' => 'v'])->create();
```

### AgentFactory

The `forHive()` method binds the agent to a hive and derives `superpos_id`
automatically.

```php
Agent::factory()->create();                            // auto-creates Hive + Superpos
Agent::factory()->forHive($hive)->create();            // bound to existing hive
Agent::factory()->forHive($hive)->online()->create();  // status=online + heartbeat
Agent::factory()->forHive($hive)->offline()->create();
Agent::factory()->forHive($hive)->idle()->create();
Agent::factory()->forHive($hive)->busy()->create();
Agent::factory()->forHive($hive)->error()->create();
Agent::factory()->forHive($hive)->stale()->create();   // active but old heartbeat
Agent::factory()->withCapabilities(['code_review', 'testing'])->create();
Agent::factory()->ofType('openclaw')->create();
```

### TaskFactory

```php
Task::factory()->create();                             // pending, priority 2
Task::factory()->forHive($hive)->create();
Task::factory()->forHive($hive)->pending()->create();
Task::factory()->forHive($hive)->inProgress($agent)->create();
Task::factory()->forHive($hive)->completed($agent)->create();
Task::factory()->forHive($hive)->failed($agent)->create();
Task::factory()->forHive($hive)->cancelled()->create();
Task::factory()->critical()->create();                 // priority 0
Task::factory()->highPriority()->create();             // priority 1
Task::factory()->lowPriority()->create();              // priority 3
Task::factory()->crossHive($sourceHive)->create();     // cross-hive task
Task::factory()->timedOut(60)->create();               // expired timeout
Task::factory()->targeting('code_review')->create();   // target_capability
Task::factory()->withPayload(['k' => 'v'])->create();
```

### ActivityLogFactory

```php
ActivityLog::factory()->forHive($hive)->create();
ActivityLog::factory()->forAgent($agent)->create();    // sets superpos_id + agent_id
ActivityLog::factory()->forTask($task)->create();      // sets superpos_id + task_id
ActivityLog::factory()->apiaryLevel()->create(['superpos_id' => $apiary->id]);
ActivityLog::factory()->action('task.completed')->create(['superpos_id' => $apiary->id]);
ActivityLog::factory()->withDetails(['ms' => 42])->create(['superpos_id' => $apiary->id]);
```

### KnowledgeEntryFactory

```php
KnowledgeEntry::factory()->create();                   // hive-scoped, public
KnowledgeEntry::factory()->forHive($hive)->create();
KnowledgeEntry::factory()->forHive($hive)->apiaryScoped()->create();
KnowledgeEntry::factory()->forHive($hive)->agentScoped($agent)->create();
KnowledgeEntry::factory()->private()->create();
KnowledgeEntry::factory()->expired()->create();        // ttl in the past
KnowledgeEntry::factory()->expiring()->create();       // ttl 1 hour from now
KnowledgeEntry::factory()->createdBy($agent)->create();
```

## Batch creation

All factories support `count()` for batch creation:

```php
$agents = Agent::factory()->forHive($hive)->count(5)->create();
$tasks  = Task::factory()->forHive($hive)->count(10)->create();
```

## When NOT to use factories

Keep raw `DB::table()` inserts for tests that verify:

- **Database triggers** (e.g., activity log immutability trigger)
- **Race conditions** (e.g., atomic task claiming with `UPDATE ... WHERE`)
- **Constraint enforcement** (e.g., composite FK violations, partial index behavior)

These tests need precise control over SQL execution that bypasses model events.

## No AgentPermission factory

`AgentPermission` uses a composite primary key and does not include the
`HasFactory` trait. Use the model's built-in method instead:

```php
$agent->grantPermission('tasks:create', 'admin');
```
