# Development

Install Python 3.13 for the verified development environment, uv, Node.js 22, and Docker Compose. Install dependencies from the repository root.

```sh
uv sync --locked --project apps/api --python 3.13
uv sync --locked --project packages/cli --python 3.13
uv sync --locked --project examples/fastapi-integration --python 3.13
npm ci --prefix apps/dashboard
npm ci --prefix examples/node-integration
npm exec --prefix apps/dashboard -- playwright install chromium
```

Run `bash scripts/ci.sh` for a complete local verification. The API tests use PostgreSQL schemas with isolated migrations and a real Celery worker where needed. The dashboard tests use the running API rather than fixed data.

For a quicker check, run `uv run --locked pytest -m 'not integration'` from `apps/api`. Run `ruff check`, `ruff format --check`, and `mypy` from the API project directory. Use `npm run lint` and `npm run typecheck` inside the dashboard directory.

Use Alembic for database changes and check forward migration, schema consistency, and rollback in disposable test schemas. Keep dependency locks current with the project manifests.
