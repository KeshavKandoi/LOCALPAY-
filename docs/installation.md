# Installation

Install Docker with Compose v2 and uv with Python 3.12 or newer. Run these commands from a copy of the LocalPay repository.

```sh
uv tool install ./packages/cli
localpay init
localpay up
localpay health
```

Initialization writes a private ignored `.env`. If you configure the environment manually, use `.env.example` as the variable reference and generate unique values for the PostgreSQL password, admin token, and webhook encryption key. A PostgreSQL password must be URL-safe for the default Compose URL.

| Setting | Purpose |
| --- | --- |
| `LOCALPAY_POSTGRES_PASSWORD` | Password for the local PostgreSQL database |
| `LOCALPAY_ADMIN_TOKEN` | A 64-character lowercase hexadecimal administration token |
| `LOCALPAY_WEBHOOK_ENCRYPTION_KEY` | URL-safe base64 encoding of 32 random bytes |
| `LOCALPAY_API_PORT`, `LOCALPAY_DASHBOARD_PORT` | Loopback ports, defaulting to 8000 and 3000 |
| `LOCALPAY_WEBHOOK_TARGETS` | JSON map of approved receiver origins to pinned local IPs |
| `LOCALPAY_VERIFICATION_TOKEN` | Bearer credential shared with the test verification endpoint |
| `LOCALPAY_DASHBOARD_SECURE_COOKIE` | Set to `true` for an HTTPS dashboard |

Use `docker compose ps --all` to inspect health and the one-shot migration. Use `localpay down` to stop services and keep the PostgreSQL volume. [Troubleshooting](troubleshooting.md)
