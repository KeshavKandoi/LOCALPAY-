# LocalPay

Break your payment integration before production does.

LocalPay is a self-hosted development tool for testing payment integrations. The current release provides the infrastructure, project data model, and test credentials for a Razorpay-compatible simulator. LocalPay is an independent project.

## Start the development stack

Use Docker with Compose v2. From the repository root:

```sh
uv tool install ./packages/cli
localpay init
docker compose up --build --detach --wait
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

The API binds to loopback on port 8000 by default. Set `LOCALPAY_API_PORT` in `.env` to change it. Set a URL-safe development value for `LOCALPAY_POSTGRES_PASSWORD` before starting a new database. The CLI generates a unique password and keeps it in the ignored local environment file. PostgreSQL and Redis share a private Compose network and have no host port mappings.

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

## Create and inspect orders

Use the LocalPay Basic credentials with `POST /v1/orders`, `GET /v1/orders/{order_id}`, or `GET /v1/orders`. Amounts are integers in the requested currency’s smallest unit. Each project has its own receipt namespace. Listing supports `count`, `skip`, `receipt`, `from`, `to`, and `authorized`.

This order API covers the core create, fetch, and list contract. The currency allowlist is fixed for the simulator. Optional Razorpay features such as offer processing, COD, partial-payment configuration, token creation, and related-entity expansion are outside the current scope. LocalPay makes no requests to live gateways.

## Simulate and capture payments

Send `POST /localpay/v1/simulations/payments` with a LocalPay Basic credential and a body such as `{"order_id":"order_…","scenario":"payment.success","method":"upi"}`. Fetch the result with `GET /v1/payments/{payment_id}`. Capture an authorized payment through `POST /v1/payments/{payment_id}/capture` with the authorized amount and matching currency.

The simulation also supports `payment.failed`, `payment.insufficient_funds`, `payment.authorization_failed`, `payment.capture_failed`, `payment.timeout`, and `payment.network_interruption`. The last two leave a persisted payment in `created` and return a synthetic HTTP 504 or 503. Capturing a payment updates its order in the same transaction. The API covers the core payment fields and simulates full capture of the authorized amount.

## Simulate refunds

Use `POST /v1/payments/{payment_id}/refund` with an integer `amount` for a partial refund or an empty object for the remaining balance. Normal refunds complete immediately in the simulation. Reuse the documented `X-Refund-Idempotency` header and the same body to retry without another refund. Fetch a refund at `GET /v1/refunds/{refund_id}` or list a payment’s refunds at `GET /v1/payments/{payment_id}/refunds`.

For explicit pending or failed outcomes, use `POST /localpay/v1/simulations/payments/{payment_id}/refunds` with `outcome` and an optional `reason`. Resolve a pending refund at `POST /localpay/v1/simulations/refunds/{refund_id}/resolve` with `{"outcome":"processed"}` or `{"outcome":"failed"}`. Pending refunds reserve the requested balance until resolved. Refund events are recorded in the same transaction as each change.

## Register and inspect webhooks

Set `LOCALPAY_WEBHOOK_ENCRYPTION_KEY` in the ignored `.env` file to a URL-safe base64 encoding of 32 random bytes. You can generate the value with `python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'`. Keep this key stable for the database containing the encrypted webhook secrets.

With the admin token, register an endpoint at `POST /localpay/admin/v1/projects/{project_id}/webhook-endpoints` using `url`, `secret`, and `enabled_events`. Supported events include payment authorization, capture, and failure, plus refund creation, completion, and failure. List events at `GET /localpay/admin/v1/projects/{project_id}/webhook-events` and inspect a signed body at `GET /localpay/admin/v1/projects/{project_id}/webhook-events/{event_id}/signed/{endpoint_id}`. The signature uses HMAC-SHA256 over the stored bytes and the response includes the event ID and signature headers.

## Deliver webhooks to a local receiver

Configure `LOCALPAY_WEBHOOK_TARGETS` as JSON mapping an allowed receiver origin to its local IP address. For example, `{"http://receiver:9000":"172.20.0.10"}` allows that exact scheme, host, and port and pins transport to that IP. From within Compose, use the receiver's address on a shared network. The transport runs without proxies or redirects. Public and link-local addresses are rejected.

Restart Compose after changing the environment. The scheduler finds committed outbox rows and the Celery worker claims and delivers them. HTTP 408, 429, 5xx, and transport failures retry with bounded exponential backoff. A lease lets another worker recover an interrupted delivery. The receiver should deduplicate using `X-Razorpay-Event-Id`. List deliveries and their attempts under the project's `/webhook-deliveries` administrative API.

## Run webhook chaos scenarios

Create a scenario at `POST /localpay/admin/v1/projects/{project_id}/webhook-scenarios` with a name and a config such as `{"delay_ms":1000,"duplicate_count":3,"failure_mode":"http_500","failure_attempts":1}`. Start a run at the scenario's `/runs` endpoint with an `endpoint_id` and `event_ids` from that project.

Runs can schedule delays and bursts, send duplicate events with stable IDs, reverse selected events, and simulate HTTP 500, rate limiting, timeout, reset, temporary unavailability, invalid signatures, or worker interruption. Simulated failures are labeled in the attempt records. Inspect a run and its scheduled jobs under `/webhook-runs/{execution_id}`.

## Run payment chaos scenarios

List payment scenarios under the project's `/payment-chaos/scenarios` admin route. Start a run with `POST /localpay/admin/v1/projects/{project_id}/payment-chaos/runs`, passing a scenario `type`. Transaction scenarios create their own orders and retain the resulting records for inspection. The run records the actual capture and refund outcomes and the balance left after a simulated interruption.

Outage and rate-limit scenarios affect only the project's next configured number of authenticated gateway requests. Their run record shows the status codes returned. Cancel an active gateway fault at `/payment-chaos/runs/{execution_id}/cancel`. Use `X-LocalPay-Idempotency-Key` on payment simulation requests to replay the same operation.

## Execute reliability suites

Create a suite at `POST /localpay/admin/v1/projects/{project_id}/test-suites` with a JSON definition or `{"yaml":"<suite contents>"}`. Each named case selects a payment or webhook scenario and one or more assertions. Start a run under `/test-suites/{suite_id}/runs`, then read `/test-runs/{run_id}` or download `/test-runs/{run_id}/json`. The scheduler dispatches runs to a dedicated worker queue so webhook delivery can continue while tests wait for evidence.

For business-state assertions, set the suite's `verification_url` to an allowlisted, test-only receiver and set `LOCALPAY_VERIFICATION_TOKEN` on the worker. Its protected GET endpoint receives `run_id`, `case`, and available order or scenario IDs. Return values such as `{"application_event_count":1}` based on observed application state. Missing or invalid evidence produces an inconclusive assertion.

## Export reliability reports

Open the run's `/report/json` or `/report/html` administrative route for a report with assertion totals, payment transitions, webhook attempts, recorded latency, and diagnostics. A diagnostic identifies confirmed findings only when the recorded scenario and observations establish them. Missing latency and unavailable evidence remain visible in the export.

## Use the dashboard

Run Compose with the same `LOCALPAY_ADMIN_TOKEN` for the API and dashboard, then open `http://127.0.0.1:3000`. Use `LOCALPAY_DASHBOARD_PORT` to override the port. Sign in with the administration token, select a project, and inspect its activity, payment records, webhook attempts, chaos runs, and reports. The dashboard session uses an HttpOnly cookie. Set `LOCALPAY_DASHBOARD_SECURE_COOKIE=true` when serving it through HTTPS.

To check the dashboard locally, run `npm ci`, `npm run lint`, and `npm run typecheck` in `apps/dashboard`. Run `npm test` against an isolated Compose project with `LOCALPAY_E2E_TOKEN` set to that project's dashboard token, and with `LOCALPAY_E2E_API_URL` and `LOCALPAY_E2E_DASHBOARD_URL` set when using custom ports.

## Use the CLI

Install the package from the checkout with `uv tool install ./packages/cli`. From the repository root, `localpay init` can create a private `.env` and `localpay up` builds and starts the stack. Check services with `localpay health` and stop the stack with `localpay down`.

Set `LOCALPAY_PROJECT_ID` or use `--project PROJECT_ID` before an administration subcommand. Use `localpay scenarios list`, `localpay scenarios run payment.concurrent_capture`, `localpay test run --file suite.yaml`, or `localpay test report RUN_ID --format html`. Run a saved webhook scenario with `localpay scenarios run webhook.chaos --scenario-id ID --endpoint-id ID --event-id ID`. Run a saved definition again with `localpay test run --suite-id SUITE_ID`.

The Python, FastAPI, Node.js, and Express sample applications demonstrate checkout simulation, refunds, and verified duplicate-safe webhook handling. See [the integration examples](examples/README.md).

## Run in CI

The GitHub Actions workflow runs `bash scripts/ci.sh` in a disposable Compose project. It starts a real Express receiver, verifies duplicate webhook delivery and the receiver's independent event count, runs both sample apps, and executes the backend and browser regressions. The script removes its isolated database and network on exit.

`localpay test run` prints JSON and exits with 0 for passed, 1 for failed, 2 for error, 3 for inconclusive, and 4 when its wait deadline is blocked. A blocked result includes the run ID for later inspection. Export completed results with `localpay test report RUN_ID --format junit`, `--format json`, or `--format html`. JUnit exports represent inconclusive cases as skipped.

## Verify resilience and performance

Set `LOCALPAY_EXTENDED_VERIFY=1` when invoking `bash scripts/ci.sh` to exercise PostgreSQL, Redis, and worker interruption in the disposable environment and collect a load report. The report captures stage throughput, API latency, queue latency, PostgreSQL query timing, and container resource samples. These measurements describe the test environment and its configured workload.

Application containers run without added Linux capabilities and expose the API and dashboard through loopback. The gateway limits request size, the dashboard bounds authentication requests, and webhook delivery is restricted to explicitly pinned local destinations.
