# Security policy

LocalPay is designed for developer and CI environments. The administration token grants access to every project on an installation. Give it only to trusted operators. Project API credentials authenticate a single project and can be revoked or rotated.

Store the administration token, webhook encryption key, and receiver secrets outside version control. Keep a stable encryption key for each database. If an administration token is exposed, replace it in both API and dashboard configuration and recreate those services. If a project credential is exposed, rotate or revoke it.

Keep the API, dashboard, PostgreSQL, and Redis inside the intended local trust boundary. Compose binds the public-facing services to loopback and isolates the datastores on an internal network. Use HTTPS and `LOCALPAY_DASHBOARD_SECURE_COOKIE=true` when placing the dashboard behind a trusted reverse proxy. Configure receiver destinations by exact origin and local IP.

Report vulnerabilities privately through the repository host's private security advisory feature when available, or contact the repository maintainer through a private channel already established with them. Include affected revisions, the observed impact, and concise reproduction conditions with test data. Share tokens, database snapshots, and sensitive customer data only through an agreed private channel.
