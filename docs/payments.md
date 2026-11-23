# Payments and refunds

Create an order through the gateway API. Submit the order ID to the local simulation control.

```http
POST /localpay/v1/simulations/payments

{"order_id":"<order_id>","method":"upi","scenario":"payment.success"}
```

A success scenario authorizes the payment. Capture it with `POST /v1/payments/{payment_id}/capture` and the authorized amount and currency. A project Basic credential is required on both endpoints. The capture transaction updates the payment and its order.

Available outcomes include failure, insufficient funds, authorization rejection, capture failure, timeout, and network interruption. Timeout and interruption keep a recorded payment in `created`. Use `X-LocalPay-Idempotency-Key` to safely repeat a payment simulation with the same request.

Send `POST /v1/payments/{payment_id}/refund` with `{"amount":200}` for a partial refund or `{}` for the remaining balance. Use the same `X-Refund-Idempotency` key and body to retry a request. Full refunds mark the payment refunded and preserve the order's paid state.

For pending or failed outcomes, use `POST /localpay/v1/simulations/payments/{payment_id}/refunds` with an outcome. A pending refund reserves balance. Finish it at `POST /localpay/v1/simulations/refunds/{refund_id}/resolve` with `{"outcome":"processed"}` or `{"outcome":"failed"}`.
