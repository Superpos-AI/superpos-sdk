# CI/CD Pipeline

Superpos uses GitHub Actions for continuous integration. The pipeline runs on
every push to `main` and on every pull request targeting `main`.

## Workflow Overview

The CI workflow (`.github/workflows/ci.yml`) runs four parallel jobs:

| Job | What it does | Runtime |
|-----|-------------|---------|
| **PHP Lint** | Runs [Laravel Pint](https://laravel.com/docs/pint) in check mode | ~30s |
| **PHP Tests** | Runs the full PHPUnit suite (Unit + Feature) with SQLite in-memory | ~1-2 min |
| **Frontend Build** | Installs npm deps and runs `vite build` | ~30-60s |
| **Python SDK** | Runs Ruff lint/format checks and pytest for `sdk/python` | ~20s |

All jobs run in parallel. If any job fails, the PR shows a failing status check.

## Triggers

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

Concurrent runs on the same branch are automatically cancelled so only the
latest push is tested.

## What Each Job Does

### PHP Lint (Pint)

Checks that all PHP code follows PSR-12 formatting via Laravel Pint:

```bash
vendor/bin/pint --test
```

If Pint reports formatting issues, fix them locally:

```bash
vendor/bin/pint
```

### PHP Tests

Runs the full test suite using SQLite in-memory (matching `phpunit.xml` and
`.env.testing`):

```bash
php artisan test
```

On failure, the Laravel log (`storage/logs/laravel.log`) is uploaded as a
GitHub Actions artifact for debugging.

### Frontend Build

Verifies that the React + Vite frontend compiles without errors:

```bash
npm ci
npm run build
```

### Python SDK

Checks code quality and runs tests for the Python SDK:

```bash
cd sdk/python
ruff check .          # lint
ruff format --check . # format
pytest -v             # tests
```

## Caching

The workflow caches dependencies for faster re-runs:

- **Composer** — cached by `composer.lock` hash
- **npm** — cached by `package-lock.json` hash (built-in `setup-node` cache)
- **pip** — cached by `pyproject.toml` hash (built-in `setup-python` cache)

## Running Locally

You can run the same checks locally before pushing:

```bash
# PHP lint
vendor/bin/pint --test

# PHP tests
php artisan config:clear && php artisan test

# Frontend build
npm ci && npm run build

# Python SDK
cd sdk/python && pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest -v
```

## Container Image Build

A separate workflow (`.github/workflows/build-image.yml`) builds and pushes the
production Docker image to GitHub Container Registry on every push to `main`.
Pull requests trigger a build-only check (no push) to validate the Dockerfile.

### Image Tags

| Tag | When | Example |
|-----|------|---------|
| `latest` | Every push to `main` | `ghcr.io/apiary-ai/apiary-saas:latest` |
| `main` | Every push to `main` | `ghcr.io/apiary-ai/apiary-saas:main` |
| `sha-<short>` | Every push to `main` | `ghcr.io/apiary-ai/apiary-saas:sha-a1b2c3d` |

### Authentication

The container image is hosted on GitHub Container Registry (GHCR). If the
repository is private (or the package visibility is private), you must
authenticate before pulling.

#### Personal Access Tokens (PAT) — for local Docker CLI or external CI

Create a classic PAT at <https://github.com/settings/tokens> with the
appropriate **token scope**:

| Scope | Use case |
|-------|----------|
| `read:packages` | Pulling images |
| `write:packages` | Pushing images |

```bash
export CR_PAT=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
echo "$CR_PAT" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

#### `GITHUB_TOKEN` — for GitHub Actions workflows

Inside a GitHub Actions workflow the automatic `GITHUB_TOKEN` is used instead of
a PAT. Grant access via the **workflow `permissions` block** (not token scopes):

```yaml
permissions:
  packages: read    # pulling images
  # packages: write # pushing images (used in the push job)
```

> **Key distinction**: PAT *scopes* (e.g. `read:packages`) are set when you
> create the token. `GITHUB_TOKEN` *permissions* (e.g. `packages: write`) are
> set in the workflow YAML — they are not the same mechanism.

### Pulling the Image

```bash
docker pull ghcr.io/apiary-ai/apiary-saas:latest
```

Pin a specific commit for reproducible deployments:

```bash
docker pull ghcr.io/apiary-ai/apiary-saas:sha-a1b2c3d
```

### Running the Image

The image uses `CONTAINER_MODE` to select the service role:

```bash
# Web server
docker run -e CONTAINER_MODE=app ghcr.io/apiary-ai/apiary-saas:latest

# Queue worker
docker run -e CONTAINER_MODE=horizon ghcr.io/apiary-ai/apiary-saas:latest

# WebSocket server
docker run -e CONTAINER_MODE=reverb ghcr.io/apiary-ai/apiary-saas:latest

# Scheduler
docker run -e CONTAINER_MODE=scheduler ghcr.io/apiary-ai/apiary-saas:latest
```

See the [Docker Services table](../../README.md#docker-services) for the full
list of services and ports.

## Adding New Checks

To add a new CI job, edit `.github/workflows/ci.yml` and add a new entry under
`jobs:`. Follow the existing pattern of:

1. `actions/checkout@<sha>` (see [Action Pinning](#action-pinning) below)
2. Language/tool setup action
3. Dependency install with caching
4. Run checks

Keep jobs independent so they run in parallel.

### Action Pinning

Always pin third-party GitHub Actions to an **immutable full-length commit SHA**
instead of a mutable tag like `@v4`. Mutable tags can be moved after the fact,
which is a supply-chain risk.

```yaml
# Good — immutable SHA pin with a comment showing the human-readable tag:
- uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4

# Bad — mutable tag that can be force-pushed to a different commit:
- uses: actions/checkout@v4
```

To find the full SHA for a tag, run:

```bash
# For any action, resolve the tag to a commit SHA:
gh api repos/actions/checkout/git/ref/tags/v4 --jq '.object.sha'
```

The `build-image.yml` workflow already follows this practice. When updating
`ci.yml` or adding new workflows, apply the same SHA-pinning convention.
