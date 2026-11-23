# Chaos testing

Use Chaos Lab to create webhook scenarios and run an existing case. Select an enabled receiver and archived events from the same project. Webhook options include delay, duplicate count, reverse ordering, burst spacing, failure mode, and retry budget.

```json
{"delay_ms":1000,"duplicate_count":3,"failure_mode":"http_500","failure_attempts":1,"retry_limit":3}
```

The run stores its schedule and each attempt. Deliberate transport failures receive synthetic error codes. Invalid signatures and duplicates retain the original event identity. A simulated worker interruption leaves a short lease that can expire and be recovered.

Payment scenarios cover concurrent captures and refunds, duplicate requests, interrupted transactions, ambiguous retries, and delayed authorization. Transaction scenarios keep their test order and observed results for inspection. Outage and rate-limit scenarios apply to a bounded number of authenticated gateway requests in one project. Cancel an active fault from Chaos Lab or the run's administrative `/cancel` route.
