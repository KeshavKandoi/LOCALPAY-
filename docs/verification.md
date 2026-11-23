# LocalPay release verification

## Phase results

Counts for the Python column are cumulative test cases in the verified Compose suite unless noted. The test images used `pytest -W error`.

| Phase | Verified capability | Python tests passed | Other verification | Commit |
| --- | --- | ---: | --- | --- |
| 1 | Startup, health, configuration, PostgreSQL, Redis, Alembic, real Celery task | 16 original | Docker health and static checks | `c8f0900` |
| 2 | Models, project authentication, credential rotation, migration of existing rows | 33 | Revoked secrets, rollback, and tenant isolation | `ddf9d67`, `a5328f9` |
| 3 | Order contracts, persistence, filters, and pagination | 35 | Scoped access and duplicate receipts | `3f351e0` |
| 4 | Payment transitions, deterministic outcomes, and capture | 62 | Concurrent capture and rollback | `08bbc8a` |
| 5 | Refund reservations, idempotency, and refund events | 66 | Concurrent refund balance enforcement | `258d016` |
| 6 | Webhook encryption, signatures, and immutable events | 68 | HMAC test vector and stable signed bytes | `839db2d` |
| 7 | Leased outbox, controlled egress, and bounded retries | 83 | Real worker kill and restart, then five infrastructure tests after Redis restart | `58a9320` |
| 8 | Delays, duplicates, reordering, signature faults, and saved webhook runs | 90 | Retry exhaustion and persistent delivery ordering | `e48f158` |
| 9 | Payment concurrency, project-scoped gateway faults, and cancellation | 102 | Bounded 429 and 503 responses | `78f9d79` |
| 10 | Persisted suites, runner, and protected verification adapter | 113 | Passed, failed, error, and inconclusive states | `96f5583` |
| 11 | JSON and HTML reports with timelines and diagnostics | 116 | Escaping, latency, and evidence correlation | `95d410a` |
| 12 | Next.js dashboard | 116 | Three Playwright tests, production build, ESLint, and TypeScript | `b24b9f4` |
| 13 | Installed CLI and Python and Express integrations | 116 | Three CLI tests, three Playwright tests, and both live examples | `132f167` |
| 14 | Isolated CI and JUnit export | 116 | Five real CLI exit states, Actionlint, and disposable cleanup | `4234e6a` |
| 15 | Security hardening, recovery, and measured workload | 119 | Four Playwright tests, three CLI tests, both examples, dependency audits, and Gitleaks | `00a1eb9` |

## Commands used

Early implementation phases used `docker compose up --build -d --wait`, `docker compose run --build --rm verify pytest -W error`, and `docker compose exec -T api alembic check` against an isolated Compose project. Static checks used `ruff check`, `ruff format --check`, `mypy`, and locked dependency validation.

Dashboard and CLI verification used `npm run lint`, `npm run typecheck`, `npm test`, `python -m unittest discover -s packages/cli/tests`, and `python3 examples/verify_integrations.py`. Hosted workflow configuration passed `actionlint .github/workflows/verify.yml`. CI execution used the local workflow script.

Phase 15 used `LOCALPAY_EXTENDED_VERIFY=1 bash scripts/ci.sh`, `pip-audit --disable-pip --require-hashes` with requirements exported from the Python locks, `npm audit` for both JavaScript locks, and `gitleaks git --redact --log-opts=--all`. The workload and container observations are in [Measured performance](performance.md).

## Issues resolved

- Fixed initial Ruff and Mypy failures in the foundation and integration test types.
- Switched the Starlette test dependency to `httpx2` and reran with warnings treated as errors.
- Fixed dashboard sign-out by keeping the session observer while clearing project data. The browser suite also disambiguated the application's error alerts from the Next.js route announcer.
- Replaced the affected `cryptography` 49.0.0 dependency with 50.0.2 after the audit flagged PYSEC-2026-3552. The repeat scan reported no known vulnerabilities.
- Repeated the hardening verification from a fixed checkout after changes during earlier runs mixed old and new network configuration.

## Security and compatibility scope

LocalPay uses project-scoped credentials and a separate administrator token. Webhook requests use exact-origin allowlists and pinned local addresses. PostgreSQL and Redis reside on an internal Compose network. Application containers use non-root accounts. The source and history scans covered the LocalPay repository. Dependency scans covered the locked Python and JavaScript packages.

Compatibility covers the core Razorpay paths listed in the [matrix](compatibility.md). Release verification ran locally with Docker and Chromium. The GitHub-hosted runner and distribution channels remain release operations. Benchmark values describe the recorded local workload and hardware. [Security policy](../SECURITY.md)

## Phase 16 clean-clone result

**PASS**

The fresh local clone installed the API, CLI, and Python example with `uv sync --locked --python 3.13`, and installed the dashboard and Express example with `npm ci`. The installed CLI generated a private environment file. `docker compose config --quiet` validated the configuration using that file.

The following command executed the release verification from the clone.

```sh
LOCALPAY_EXTENDED_VERIFY=1 LOCALPAY_CI_API_PORT=8007 LOCALPAY_CI_DASHBOARD_PORT=3007 \
  LOCALPAY_CI_RESULTS=/tmp/localpay-p16-results bash scripts/ci.sh
```

- Pytest passed 119 tests with zero failures or skips and warnings treated as errors.
- Playwright passed four tests with zero failures or skips.
- The CLI unit suite passed three tests. The live workflow also verified CLI exits 0 through 4 and report agreement with the API.
- The FastAPI and Express examples passed live checkout, refund, HMAC, and deduplication checks.
- Docker services became healthy and Alembic detected no schema drift. Absent evidence produced the expected inconclusive status. The outbox recovered after worker and Redis interruption, and a paid order remained readable after PostgreSQL restart.
- Ruff, Mypy, TypeScript, ESLint, Actionlint, the no-comments audit, and relative documentation links passed. The pinned ESLint 9 install emits an npm deprecation notice because the Next.js lint plugins currently require that major.
- PyPI and npm dependency audits reported no known vulnerabilities in the scanned locks. Gitleaks reported no detected secrets in the checked source and history. The isolated verification project removed its disposable database volume and networks.

The clean-clone workload observed 177.59 orders per second, 110.71 captures per second, and 12.36 delivered webhooks per second in this environment. Aggregate measured API latency was 59.09 ms p50 and 145.53 ms p95. [Clean-clone measurements](release-performance.json)
