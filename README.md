# LocalPay

Break your payment integration before production does.

LocalPay is a self-hosted development tool for testing payment integrations. Phase 1 provides the infrastructure for a future Razorpay-compatible simulator. LocalPay is an independent project.

## Start the development stack

Use Docker with Compose v2. From the repository root:

```sh
cp .env.example .env
docker compose up --build --detach --wait
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

The API binds to loopback on port 8000 by default. Set `LOCALPAY_API_PORT` in `.env` to change it. Set a URL-safe development value for `LOCALPAY_POSTGRES_PASSWORD` before starting a new database. The example password is for disposable local development. PostgreSQL and Redis use the Compose network and have no host port mappings.

`GET /health` reports API liveness. `GET /ready` checks PostgreSQL and Redis and returns HTTP 503 with per-dependency status when either is unavailable. Compose separately verifies that the Celery worker responds to a broker-mediated ping. A one-shot Alembic service applies the baseline revision before the API and worker boot. PostgreSQL data persists across `docker compose down` and subsequent starts.

```sh
docker compose ps --all
docker compose logs api migrate worker
docker compose down
```

## Verify Phase 1

Run the API and integration suite against the Compose stack:

```sh
docker compose up --build --detach --wait
docker compose run --build --rm verify
```

Integration tests query the live PostgreSQL database and its Alembic revision, ping Redis, check readiness, and submit a smoke task to the real Celery worker.

For local static analysis and tests that need no running services, install Python 3.12 or newer and uv:

```sh
cd apps/api
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest -m 'not integration'
```

The API and worker take `LOCALPAY_DATABASE_URL` and `LOCALPAY_REDIS_URL` from their environment when run outside Compose. The optional `LOCALPAY_DEPENDENCY_TIMEOUT_SECONDS` sets connection and Redis socket timeouts and defaults to two seconds.

The current API exposes health and readiness only. It has no payment operations or live gateway integration.
