# Razorpay compatibility matrix

All gateway routes accept LocalPay-issued HTTP Basic credentials. Amounts use integer minor units. LocalPay-specific simulation controls live under `/localpay/v1`.

| Capability | Supported contract | Scope |
| --- | --- | --- |
| Orders | `POST /v1/orders`, `GET /v1/orders/{id}`, `GET /v1/orders` | Receipts, notes, recorded status and amounts, count and skip, receipt, date and authorization filters |
| Payments | `GET /v1/payments/{id}`, `POST /v1/payments/{id}/capture` | Core entity fields and full capture of the authorized amount |
| Refunds | Create, list by payment, fetch by payment and refund ID, and fetch by refund ID | Normal full and partial refunds, retry idempotency through `X-Refund-Idempotency` |
| Webhooks | Payment authorization, capture and failure, plus refund creation, processing and failure | Raw-body HMAC-SHA256 and stable event ID headers |
| SDKs | Razorpay Python SDK 2.0.1 order creation with explicit `base_url` | Express example uses direct HTTP requests |

Hosted Checkout, COD, offers, subscriptions, settlement, instant refunds, account-level currency controls, and related entity expansions are outside this release's scope. LocalPay includes a fixed currency allowlist and test-specific failure details.

Primary contracts are the [create order reference](https://razorpay.com/docs/api/orders/create/), [order list reference](https://razorpay.com/docs/api/orders/fetch-all/), [capture reference](https://razorpay.com/docs/api/payments/capture/), [refunds reference](https://razorpay.com/docs/api/refunds/), and [webhook verification reference](https://razorpay.com/docs/webhooks/validate-test/).
