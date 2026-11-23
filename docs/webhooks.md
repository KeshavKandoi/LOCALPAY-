# Webhook testing

Configure a stable `LOCALPAY_WEBHOOK_ENCRYPTION_KEY` and a reachable receiver. Set `LOCALPAY_WEBHOOK_TARGETS` to a JSON map of exact origins and local IPs. The worker pins each request to the configured address and disables redirects and proxies.

Register the receiver in Settings or post its URL, secret, and enabled event names to `/localpay/admin/v1/projects/{project_id}/webhook-endpoints`. Registration applies to future matching events. Webhooks and delivery attempts are visible in the dashboard. Replay an event by choosing a subscribed receiver in the Webhooks page.

Verify the HMAC-SHA256 digest of the exact request bytes against `X-Razorpay-Signature` using a constant-time comparison. Deduplicate by `X-Razorpay-Event-Id` before applying business changes. An HTTP 2xx acknowledgement completes that attempt. HTTP 408, 429, 5xx, and transport failures retry within the configured budget.

The worker retries the same event bytes and identity. A lease expiry may lead to a duplicate even after a receiver has already acted. Use the [sample receivers](../examples/README.md) to see raw-body verification and idempotency.
