# LocalPay

Break your payment integration before production does.

LocalPay is a self-hosted payment integration simulator. It lets you reproduce failed payments, duplicate webhooks, gateway outages, and capture or refund races under controlled conditions. Use it to check whether an integration preserves financial state and processes events correctly before deploying it.

LocalPay is an independent project. The gateway API models a documented subset of Razorpay using local test credentials and simulated money.

## Quick start

Use Docker Compose and uv with Python 3.12 or newer. From your checkout:

```sh
uv tool install ./packages/cli
localpay init
localpay up
localpay health
```

Open `http://127.0.0.1:3000` and create a username-and-password account. Create a project in the dashboard and issue a test credential from Settings. Existing installations can assign legacy projects through the account operator command. [Account guide](docs/accounts.md) The API is available at `http://127.0.0.1:8000`.

The [installation guide](docs/installation.md) covers local configuration. The [quick start](docs/quick-start.md) walks through a payment and a reliability run.

## What you can test

- Send authenticated LocalPay requests, inspect responses, and save request templates in the dashboard. [API Workspace guide](docs/api-workspace.md)
- Create orders, simulate authorization or failure, capture payments, and issue full or partial refunds in integer minor units. [Payment guide](docs/payments.md)
- Register a local receiver, validate signed webhook bytes, inspect attempts, and replay events. [Webhook guide](docs/webhooks.md)
- Inject delay, duplicates, reordering, bad signatures, retryable errors, and project-scoped gateway outages. [Chaos guide](docs/chaos.md)
- Run suites against observable application state and export JSON, HTML, or JUnit results. [Test suites](docs/reliability.md) · [Reports](docs/reporting.md)
- Inspect real activity in the dashboard or run the same checks from the terminal and CI. [CLI](docs/cli.md) · [CI](docs/ci.md) · [Integration examples](examples/README.md)

## Architecture and scope

FastAPI handles gateway and administration requests. PostgreSQL commits financial state together with webhook events and outbox jobs. Redis and Celery deliver work, with separate workers for delivery and reliability suites. The Next.js dashboard reads recorded state through an authenticated API proxy. [Architecture](docs/architecture.md)

The current release covers core Razorpay Orders, Payments, Refunds, and webhook signing behavior. Hosted checkout, settlement, recurring payment products, and account-specific Razorpay settings are outside the compatibility scope. [Compatibility matrix](docs/compatibility.md)

The API and dashboard bind to loopback by default. Workers deliver webhooks only to explicitly pinned local destinations. Store configuration and secrets in your test environment. [Security policy](SECURITY.md)

## Verification and contribution

Run `bash scripts/ci.sh` to exercise the disposable integration environment. Set `LOCALPAY_EXTENDED_VERIFY=1` to include restart recovery and the local workload measurement. [Development guide](docs/development.md) · [Verification report](docs/verification.md) · [Measured performance](docs/performance.md)

See [Contributing](CONTRIBUTING.md), [Troubleshooting](docs/troubleshooting.md), and the [Changelog](CHANGELOG.md). Original LocalPay code is distributed under the [Apache License 2.0](LICENSE).
