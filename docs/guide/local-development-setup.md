# Local Development Setup

This guide walks you through setting up Superpos for local development on Linux or
macOS. By the end you will have all six Docker services running, a seeded
database, and a passing test suite.

---

## Prerequisites

### Linux (Ubuntu / Debian / Fedora)

| Tool | Minimum version | Install |
|------|----------------|---------|
| Docker Engine | 24+ | [docs.docker.com/engine/install](https://docs.docker.com/engine/install/) |
| Docker Compose plugin | 2.20+ (bundled with Engine) | Included with Docker Engine |
| Git | 2.x | `sudo apt install git` / `sudo dnf install git` |
| `gh` CLI (optional) | 2.x | [cli.github.com](https://cli.github.com/) |

After installing Docker Engine, add your user to the `docker` group so you can
run commands without `sudo`:

```bash
sudo usermod -aG docker "$USER"
newgrp docker          # activate in current shell
docker run hello-world # verify
```

### macOS

| Tool | Minimum version | Install |
|------|----------------|---------|
| Docker Desktop | 4.25+ | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) |
| Git | 2.x | `xcode-select --install` or [git-scm.com](https://git-scm.com/) |
| `gh` CLI (optional) | 2.x | `brew install gh` |

Docker Desktop includes the Compose plugin. No group-permission steps needed.

---

## Clone the Repository

```bash
git clone https://github.com/YOUR_ORG/apiary.git
cd apiary
```

If you plan to contribute, fork first and clone your fork:

```bash
gh repo fork YOUR_ORG/apiary --clone
cd apiary
```

---

## First-Time Bootstrap

### 1. Build and start all services

```bash
docker compose up --build -d
```

This runs a multi-stage Docker build (Composer dependencies, npm/Vite frontend
build, FrankenPHP runtime) and starts six services:

| Service | Container mode | Host port | Purpose |
|---------|---------------|-----------|---------|
| **app** | `app` | `8080` | FrankenPHP web server |
| **horizon** | `horizon` | — | Laravel Horizon queue workers |
| **reverb** | `reverb` | `8081` | Laravel Reverb WebSocket server |
| **scheduler** | `scheduler` | — | Laravel cron scheduler |
| **postgres** | — | `5432` | PostgreSQL 16 database |
| **redis** | — | `6379` | Redis 7 cache / queues |

### 2. Verify the app started

```bash
docker compose logs app --tail 30
```

You should see:

```
🔄 Running migrations...
📦 Caching configuration...
✅ Superpos is ready!
🌐 Server listening on :80
```

### 3. Open in browser

- **App**: [http://localhost:8080](http://localhost:8080)
- **WebSocket**: [http://localhost:8081](http://localhost:8081)

---

## Environment Configuration

Environment variables are defined inline in `docker-compose.yml` — there is no
`.env` file to manage for Docker-based development. Key defaults:

```yaml
APP_ENV: local
APP_DEBUG: 'true'
SUPERPOS_EDITION: ce            # Community Edition (single apiary/hive)
DB_DATABASE: apiary
DB_USERNAME: apiary
DB_PASSWORD: apiary
QUEUE_CONNECTION: redis
CACHE_STORE: redis
```

### APP_KEY

The compose file ships with a placeholder `APP_KEY`. If you need to regenerate
it (e.g. for encrypted data), exec into the container:

```bash
docker compose exec app php artisan key:generate --show
```

Then paste the output into the `APP_KEY` value for every service in
`docker-compose.yml` and restart:

```bash
docker compose down && docker compose up -d
```

### Switching to Cloud edition

Set `SUPERPOS_EDITION: cloud` on every service in `docker-compose.yml`. Cloud
edition also requires Stripe keys — see `config/apiary.php` for the full list.

---

## Database

### Migrations

The `app` container runs `php artisan migrate --force` automatically on startup
(see `frankenphp/entrypoint.sh`). To re-run manually:

```bash
docker compose exec app php artisan migrate
```

### Seeding

The default seeder creates the CE apiary/hive and a test user
(`test@example.com`):

```bash
docker compose exec app php artisan db:seed
```

### Fresh reset

Drop all tables and re-run migrations + seeders:

```bash
docker compose exec app php artisan migrate:fresh --seed
```

### Direct database access

Connect from your host using any PostgreSQL client:

```
Host: localhost
Port: 5432
Database: apiary
User: apiary
Password: apiary
```

Or use `psql` inside the container:

```bash
docker compose exec postgres psql -U apiary -d apiary
```

---

## Installing Dev Dependencies

The Docker image is built with `composer install --no-dev` for a lean
production image. PHPUnit, Pint, and other dev tools are **not included** in
the running container by default. Install them before running tests or linting:

```bash
docker compose exec app composer install
```

This adds `require-dev` packages (PHPUnit, Pint, Faker, etc.) to the
container's writable layer. The installed packages persist as long as the
**same container** keeps running. Re-run the command after any of these events:

- **Image rebuild** — `docker compose up --build`
- **Container recreation** — `docker compose down && docker compose up -d`,
  `docker compose up -d --force-recreate`, or `docker compose rm app`

In short: if the `app` container is replaced (not just restarted), run
`composer install` again.

---

## Running Tests

Tests use an **in-memory SQLite** database (configured in `phpunit.xml`), so
they run independently of the PostgreSQL container.

> Requires dev dependencies — see [Installing Dev Dependencies](#installing-dev-dependencies) above.

### Full suite

```bash
docker compose exec app php artisan test
```

### Targeted runs

```bash
# Single test file
docker compose exec app php artisan test --filter=AgentAuthTest

# Single test method
docker compose exec app php artisan test --filter=AgentAuthTest::test_agent_can_register

# Only unit tests
docker compose exec app php artisan test --testsuite=Unit

# Only feature tests
docker compose exec app php artisan test --testsuite=Feature
```

### PHPUnit directly

```bash
docker compose exec app ./vendor/bin/phpunit
docker compose exec app ./vendor/bin/phpunit --filter=TaskPollingClaimingTest
```

### Test environment

Tests automatically use these settings (from `phpunit.xml` and
`.env.testing`):

| Setting | Value |
|---------|-------|
| `DB_CONNECTION` | `sqlite` |
| `DB_DATABASE` | `:memory:` |
| `CACHE_STORE` | `array` |
| `QUEUE_CONNECTION` | `sync` |
| `SESSION_DRIVER` | `array` |

---

## Docker Lifecycle Commands

```bash
# Build images (without starting)
docker compose build

# Start all services (detached)
docker compose up -d

# Start and rebuild
docker compose up --build -d

# Stop all services (preserves volumes)
docker compose down

# Stop and delete volumes (full reset)
docker compose down -v

# View logs (follow mode)
docker compose logs -f

# Logs for a single service
docker compose logs -f app
docker compose logs -f horizon

# Shell into the app container
docker compose exec app sh

# Run a one-off artisan command
docker compose exec app php artisan tinker
docker compose exec app php artisan route:list

# Restart a single service
docker compose restart horizon
```

---

## Common Developer Workflows

### Code style / linting

Superpos uses [Laravel Pint](https://laravel.com/docs/pint) (PSR-12).
Requires dev dependencies — see [Installing Dev Dependencies](#installing-dev-dependencies).

```bash
# Check style (dry run)
docker compose exec app ./vendor/bin/pint --test

# Auto-fix
docker compose exec app ./vendor/bin/pint
```

### Lint → test loop

```bash
docker compose exec app sh -c "./vendor/bin/pint --test && php artisan test"
```

### Rebuilding after dependency changes

If `composer.json` or `package.json` changes:

```bash
docker compose up --build -d
```

### Creating branches and PRs

```bash
# Create a feature branch
git checkout -b feature/my-feature main

# ... make changes, commit ...
git add -A && git commit -m "feat: description"

# Push and open PR
git push -u origin feature/my-feature
gh pr create --fill
```

### Artisan generators

```bash
docker compose exec app php artisan make:model MyModel -mf   # model + migration + factory
docker compose exec app php artisan make:controller Api/MyController
docker compose exec app php artisan make:test MyFeatureTest
```

---

## Troubleshooting

### Port conflicts

If port 8080, 8081, 5432, or 6379 is already in use:

```bash
# Find what's using a port
sudo lsof -i :8080    # macOS / Linux
ss -tlnp | grep 8080  # Linux alternative

# Option 1: stop the conflicting process
# Option 2: change the host port in docker-compose.yml
#   e.g. '9090:80' instead of '8080:80'
```

### Permission issues (Linux)

**docker.sock**: If you get `permission denied` on `/var/run/docker.sock`:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

**Volume ownership**: If the app container fails with permission errors on
`storage/` or `bootstrap/cache/`:

```bash
docker compose down -v
docker compose up --build -d
```

The Dockerfile runs `chown -R www-data:www-data storage bootstrap/cache`, so a
full rebuild resolves most ownership issues.

### Container rebuild / cache reset

When things get into a bad state:

```bash
# Nuclear option: rebuild everything from scratch
docker compose down -v
docker compose build --no-cache
docker compose up -d
```

To clear just the Laravel caches:

```bash
docker compose exec app php artisan optimize:clear
```

### Database connectivity

If the app container cannot reach PostgreSQL:

```bash
# Check postgres is running
docker compose ps postgres

# Check logs
docker compose logs postgres

# Test connectivity from app container
docker compose exec app sh -c "php -r \"new PDO('pgsql:host=postgres;dbname=apiary', 'apiary', 'apiary');\""
```

### Redis connectivity

```bash
docker compose ps redis
docker compose logs redis
docker compose exec redis redis-cli ping   # should return PONG
```

### Missing `phpunit` or `pint` binaries

If you see an error like `sh: ./vendor/bin/phpunit: not found` or
`sh: ./vendor/bin/pint: not found`, dev dependencies are not installed.
The Docker image only ships production dependencies. Run:

```bash
docker compose exec app composer install
```

This installs `require-dev` packages into the container. Re-run after every
image rebuild or container recreation (see
[Installing Dev Dependencies](#installing-dev-dependencies)).

### Migrations fail on startup

The `app` container runs migrations automatically. If they fail:

```bash
# Check the app logs for the error
docker compose logs app

# Run manually to see full output
docker compose exec app php artisan migrate --force

# If the schema is corrupt, reset
docker compose exec app php artisan migrate:fresh --seed
```

---

## Performance Tips

### macOS — Docker Desktop file sync

Docker Desktop's default file sharing can be slow. For better performance:

1. In Docker Desktop → Settings → General, enable **VirtioFS** (or
   **gRPC FUSE**) for file sharing.
2. Avoid mounting your entire home directory; the default project bind mount
   via Docker Compose volumes is already scoped.

### Reduce build time

The multi-stage Dockerfile caches Composer and npm installs in separate layers.
If only PHP code changed (not `composer.json`), rebuilds skip the vendor stage.
To take advantage of this:

```bash
docker compose up --build -d   # uses layer cache automatically
```

### Resource limits

If your laptop struggles with six containers, stop services you don't
actively need:

```bash
# Stop WebSocket + scheduler if you're only testing API
docker compose stop reverb scheduler

# Restart when needed
docker compose start reverb scheduler
```

### Allocated resources (macOS)

In Docker Desktop → Settings → Resources, allocate at least:
- **CPU**: 4 cores
- **Memory**: 4 GB
- **Disk**: 20 GB

---

## Safety Notes

- **Never commit secrets.** The `docker-compose.yml` ships with development-only
  credentials (`apiary`/`apiary`). Never reuse these in production or commit
  real API keys, Stripe secrets, or passwords.
- **Use feature branches.** Always branch from `main` for your work. Never push
  directly to `main`.
- **Open PRs for review.** All changes go through pull requests.
- **Check `.gitignore`** before committing. Files like `.env`, `vendor/`, and
  `node_modules/` are excluded by default — keep it that way.

---

## Quick Reference

| Task | Command |
|------|---------|
| Start everything | `docker compose up --build -d` |
| Stop everything | `docker compose down` |
| Full reset | `docker compose down -v && docker compose up --build -d` |
| Run tests | `docker compose exec app php artisan test` |
| Run single test | `docker compose exec app php artisan test --filter=TestName` |
| Lint check | `docker compose exec app ./vendor/bin/pint --test` |
| Lint fix | `docker compose exec app ./vendor/bin/pint` |
| Shell access | `docker compose exec app sh` |
| DB console | `docker compose exec postgres psql -U apiary -d apiary` |
| View logs | `docker compose logs -f` |
| Fresh DB | `docker compose exec app php artisan migrate:fresh --seed` |
