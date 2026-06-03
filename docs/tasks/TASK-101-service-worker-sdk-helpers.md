# TASK-101: Service worker SDK conventions & helpers

**Status:** Done
**Branch:** `task/101-service-worker-sdk-helpers`
**Depends On:** 032 (Python SDK), 033 (Shell SDK)

## Objective

Add standardized service worker patterns and helpers to the Python and Shell
SDKs so that developers can build service workers with minimal boilerplate.

A **service worker** is a regular agent with a `data:<service>` capability that
polls for `data_request` tasks, dispatches each request to a named operation
handler, and returns structured results via `complete_task` / `fail_task`.

## What Was Built

### Python SDK additions

#### `ServiceWorker` base class (`sdk/python/src/superpos_sdk/service_worker.py`)

- Inherit from `ServiceWorker`, declare `CAPABILITY`, implement operation methods
- Operation routing: method name or `register_operation()` (composition pattern)
- Hyphen-to-underscore operation name normalization (`fetch-emails` → `fetch_emails`)
- `OperationNotFoundError` for unknown operations (fails task gracefully)
- Blocking poll loop: `worker.run()` — installs SIGINT/SIGTERM handlers
- `worker.stop()` for thread-safe shutdown
- `setup()` / `teardown()` hooks for one-time init and cleanup
- Auto-authentication: register by name+secret, or login by agent_id+secret
- Pre-supplied token support (skips auth)
- Publishes `supported_operations` metadata on registration
- Graceful shutdown: status → offline, logout, close

#### `SuperposClient.data_request()` convenience method

- Creates a `data_request` task targeting a `data:<service>` capability
- Supports `operation`, `params`, `delivery`, `result_format`, `continuation_of`
- Fire-and-forget (returns task ID immediately, agent does not block)

#### `SuperposClient.discover_services()`

- Lists service workers in a hive by capability prefix (default `"data:"`)
- Returns agent records including `metadata.supported_operations`

#### Exports

- `ServiceWorker` and `OperationNotFoundError` added to `superpos_sdk.__init__`

### Shell SDK additions (`sdk/shell/src/superpos-sdk.sh`)

#### `superpos_data_request HIVE_ID [options]`

- `-c CAPABILITY` (required) — target capability
- `-o OPERATION` (required) — operation name
- `-p PARAMS_JSON` — operation parameters as JSON object
- `-d DELIVERY` — delivery mode (default: `task_result`)
- `-f FORMAT` — result_format hint
- `-C TASK_ID` — continuation_of for pagination/resumable operations
- `-t TIMEOUT` — timeout in seconds
- `-k KEY` — idempotency key

#### `superpos_discover_services HIVE_ID [options]`

- `-p PREFIX` — capability prefix to filter on (default: `data:`)

### Examples

- `sdk/python/examples/service_worker_example.py` — Python subclass + composition patterns + data_request usage
- `sdk/shell/examples/service_worker_example.sh` — Shell poll loop + operation dispatcher + error handling

### Tests

- `sdk/python/tests/test_service_worker.py` — 26 tests covering:
  - `handle()` dispatch (method, registered, hyphen-to-underscore, unknown operation, private method guard)
  - `_supported_operations()` discovery
  - Authentication (register, login, pre-supplied token, missing credentials)
  - `_process()` lifecycle (success, unknown op → fail, handler error → fail, claim conflict → skip)
  - `stop()` flag
  - `data_request()` (creates task, correct payload fields, defaults)
  - `discover_services()` (filters by prefix, empty list, custom prefix, non-list response)

- `sdk/shell/tests/test_service_worker.sh` — 20 tests covering `superpos_data_request` and `superpos_discover_services`

## Conventions Established

- Service worker capabilities use `data:<service>` prefix (e.g. `data:gmail`)
- Task type for data requests is `data_request`
- Payload schema: `{ operation, params, delivery, result_format, continuation_of }`
- Workers declare `metadata.supported_operations` for service catalog discovery
- Agent type for workers is `service_worker`

## Files Changed

- `sdk/python/src/superpos_sdk/__init__.py` — export ServiceWorker, OperationNotFoundError
- `sdk/python/src/superpos_sdk/client.py` — add data_request(), discover_services()
- `sdk/python/src/superpos_sdk/service_worker.py` — new ServiceWorker base class
- `sdk/python/tests/test_service_worker.py` — 26 tests
- `sdk/python/examples/service_worker_example.py` — example
- `sdk/shell/src/superpos-sdk.sh` — add superpos_data_request(), superpos_discover_services()
- `sdk/shell/tests/test_service_worker.sh` — 20 tests
- `sdk/shell/tests/run_tests.sh` — add service_worker suite
- `sdk/shell/examples/service_worker_example.sh` — example

## Definition of Done

- [x] ServiceWorker base class with operation routing, poll loop, graceful shutdown
- [x] data_request() and discover_services() on SuperposClient
- [x] Shell superpos_data_request() and superpos_discover_services() helpers
- [x] 26 Python tests pass
- [x] Shell tests structurally correct (jq unavailable in CI environment)
- [x] Examples demonstrate both subclass and composition patterns
- [ ] PR merged to `main`
- [ ] TASKS.md updated to `✅`
