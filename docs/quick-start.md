# Quick start

Start the stack using the [installation guide](installation.md). Open `http://127.0.0.1:3000`, create an account or sign in, and create a project. Issue a test credential in Settings and save the one-time secret in your local test environment.

Open **Payment Simulator** to create an order, simulate authorization, capture the payment, and issue a refund. Open **API Workspace** to edit and send the same gateway requests and inspect their responses. [API Workspace and simulator](api-workspace.md)

From a terminal, create an order using the issued values as `LOCALPAY_KEY_ID` and `LOCALPAY_KEY_SECRET`.

```sh
curl -fsS -u "$LOCALPAY_KEY_ID:$LOCALPAY_KEY_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"amount":600,"currency":"INR","receipt":"quick-start"}' \
  http://127.0.0.1:8000/v1/orders
```

Use the returned order ID to [simulate and capture a payment](payments.md). After capture, the Dashboard's Payments page shows the attempt, and its Orders page shows the updated balance.

To run a reliability check, open Test Runner and paste the [sample suite](reliability.md). Save the suite, run it, and open Reports after it reaches a terminal status.
