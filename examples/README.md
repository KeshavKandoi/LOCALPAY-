# LocalPay integration examples

The FastAPI and Express applications have three test surfaces.

- `POST /checkout` creates a test order, simulates the requested outcome, and captures successful payments. Pass `refund_amount` to make a partial refund after capture.
- `POST /webhook` verifies the HMAC over the raw request bytes and deduplicates the Razorpay event ID.
- `GET /verify?scenario_execution_id=...` returns the count of processed events for that execution to an authenticated reliability runner.

Start LocalPay, create a project and issue a test credential. Set `LOCALPAY_API_URL`, `LOCALPAY_KEY_ID`, `LOCALPAY_KEY_SECRET`, `LOCALPAY_RECEIVER_SECRET`, and `LOCALPAY_VERIFICATION_TOKEN` for each example process. The verification token must match the worker configuration when running application assertions. Configure an allowlisted receiver origin and register the example's `/webhook` path in LocalPay. The Compose worker must be able to reach the configured address.

## Python and FastAPI

Set `LOCALPAY_EXAMPLE_DATABASE` to a writable SQLite file for the receipt log.

```sh
cd examples/fastapi-integration
uv sync --locked
uv run --locked uvicorn app:app --host 127.0.0.1 --port 9000
```

This example was verified with Razorpay Python SDK 2.0.1 using `razorpay.Client(auth=(key_id, key_secret), base_url=localpay_origin)` for order creation. It uses HTTPX for LocalPay simulation controls. [Python SDK client](https://github.com/razorpay/razorpay-python/blob/master/razorpay/client.py)

## Node.js and Express

```sh
cd examples/node-integration
npm ci
npm start
```

Express listens on `127.0.0.1:9001` by default and keeps an in-process receipt log. This example uses Node's native `fetch`. The official Node SDK constructor currently fixes the gateway origin, so the example uses explicit LocalPay URLs for every request. [Node SDK constructor](https://github.com/razorpay/razorpay-node/blob/master/lib/razorpay.js)

## Run the integration checks

With both examples' dependencies installed and an isolated LocalPay instance running, set `LOCALPAY_API_URL` and `LOCALPAY_ADMIN_TOKEN`, then run `python3 examples/verify_integrations.py` from the repository root. The check creates isolated projects, launches both receivers, runs success and failure checkouts, verifies signed payloads, and checks duplicate handling.
