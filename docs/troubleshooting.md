# Troubleshooting

| Symptom | Check |
| --- | --- |
| Compose refuses to start | Run `localpay init` or populate `.env` with generated settings. Check for loopback port conflicts. |
| `/health` works and `/ready` returns 503 | Inspect the PostgreSQL and Redis dependency fields and `docker compose ps --all`. |
| Migration service exits with an error | Inspect `docker compose logs migrate`. Confirm the database credentials and revision with `docker compose exec api alembic current`. |
| Dashboard sign-in fails | Verify that the API and dashboard share the same administration token and use the configured loopback or HTTPS origin. |
| Webhook deliveries show `unsafe_destination` | Match scheme, host, and port in `LOCALPAY_WEBHOOK_TARGETS`. Pin to a local address reachable from the worker. |
| Receiver reports a bad signature | Verify raw request bytes, match the registered secret, and check whether an invalid-signature scenario was configured. |
| Suite returns inconclusive | Inspect the case evidence and the protected application verification endpoint. Check token, address, expected types, and observation window. |
| A local process already uses a default port | Set alternate API and dashboard ports before starting the stack. |

For local logs use `docker compose logs api worker scheduler reliability-worker`. Keep test credentials and receiver secrets out of shared diagnostics. [Security policy](../SECURITY.md)
