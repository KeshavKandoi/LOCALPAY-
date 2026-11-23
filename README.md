# LocalPay

Break your payment integration before production does.

LocalPay is a self-hosted development tool for testing payment integrations. The current release provides the infrastructure, project data model, and test credentials for a future Razorpay-compatible simulator. LocalPay is an independent project.

## Start the development stack

Use Docker with Compose v2. From the repository root:

```sh
cp .env.example .env
docker compose up --build --detach --wait
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

The API binds to loopback on port 8000 by default. Set `LOCALPAY_API_PORT` in `.env` to change it. Set a URL-safe development value for `LOCALPAY_POSTGRES_PASSWORD` before starting a new database. The example password is for disposable local development. PostgreSQL and Redis use the Compose network and have no host port mappings.

`GET /health` reports API liveness. `GET /ready` checks PostgreSQL and Redis and returns HTTP 503 with per-dependency status when either is unavailable. Compose separately verifies that the Celery worker responds to a broker-mediated ping. A one-shot Alembic service applies the current schema migrations before the API and worker boot. PostgreSQL data persists across `docker compose down` and subsequent starts.

```sh
docker compose ps --all
docker compose logs api migrate worker
docker compose down
```

## Verify LocalPay

Run the API and integration suite against the Compose stack:

```sh
docker compose up --build --detach --wait
docker compose run --build --rm verify
```

Integration tests query the live PostgreSQL database and its Alembic revision, ping Redis, check readiness, and submit a smoke task to the real Celery worker. They also exercise credential issuance and revocation, project isolation, database constraints, transaction rollback, and reversible migrations in temporary PostgreSQL schemas.

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

## Set up a project

Generate a dedicated administration token with `openssl rand -hex 32`. Set `LOCALPAY_ADMIN_TOKEN` in the ignored `.env` file, then run `docker compose up --build --detach --wait` to apply the API configuration. Admin routes require this token in the Bearer authorization header. With the setting absent, administration is disabled.

| Method | Path | Request body |
| --- | --- | --- |
| POST | `/localpay/admin/v1/projects` | `{"slug":"my-project","name":"My project"}` |
| POST | `/localpay/admin/v1/projects/{project_id}/credentials` | `{"label":"CI"}` |
| GET | `/localpay/admin/v1/projects/{project_id}/credentials` | |
| DELETE | `/localpay/admin/v1/projects/{project_id}/credentials/{credential_id}` | |
| POST | `/localpay/admin/v1/projects/{project_id}/credentials/{credential_id}/rotate` | |

The credential creation response returns a LocalPay key ID and its secret once. Store the secret in the integration's test environment. Credential listings return metadata, including the revocation timestamp. Rotation revokes the old credential and issues a replacement with the same label in one transaction. Keep the replacement secret from the rotation response. Project creation, issuance, revocation, and rotation are audited in the same database transaction as the change.

Use the issued key ID and secret as the HTTP Basic username and password for `GET /localpay/v1/project`. The credential determines the project returned by that endpoint. LocalPay accepts only credentials issued by this installation. Configure TLS when forwarding the API beyond the local host.

Payment operations and live gateway integration are outside the current release.
