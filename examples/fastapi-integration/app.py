import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from hmac import compare_digest, new
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
import razorpay
import requests
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI(title="LocalPay FastAPI example")


class LocalSession(requests.Session):
    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        kwargs.update(allow_redirects=False, timeout=5)
        return super().request(method, url, **kwargs)


def local_origin() -> str:
    value = os.environ.get("LOCALPAY_API_URL", "http://127.0.0.1:8000")
    url = urlsplit(value)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "::1", "localhost", "api"}
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise RuntimeError("Set LOCALPAY_API_URL to the local simulator origin")
    return value.rstrip("/")


def auth() -> tuple[str, str]:
    key_id = os.environ["LOCALPAY_KEY_ID"]
    key_secret = os.environ["LOCALPAY_KEY_SECRET"]
    if not key_id.startswith("lp_test_") or not key_secret.startswith("lp_secret_"):
        raise RuntimeError("Use credentials issued by LocalPay")
    return key_id, key_secret


@contextmanager
def state() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(os.environ["LOCALPAY_EXAMPLE_DATABASE"])
    try:
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS received (id TEXT PRIMARY KEY, execution TEXT, event_type TEXT NOT NULL)"
            )
            yield connection
    finally:
        connection.close()


class Checkout(BaseModel):
    amount: Annotated[int, Field(strict=True, ge=100, le=1_000_000_000)] = 600
    outcome: Literal["success", "failed"] = "success"
    refund_amount: Annotated[int, Field(strict=True, ge=100)] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/checkout")
def checkout(body: Checkout) -> dict[str, object]:
    origin = local_origin()
    credentials = auth()
    with LocalSession() as transport:
        transport.trust_env = False
        sdk = razorpay.Client(session=transport, auth=credentials, base_url=origin)
        order = sdk.order.create({"amount": body.amount, "currency": "INR"})
    with httpx.Client(
        base_url=origin, auth=credentials, trust_env=False, timeout=5
    ) as api:
        response = api.post(
            "/localpay/v1/simulations/payments",
            json={"order_id": order["id"], "scenario": f"payment.{body.outcome}"},
        )
        response.raise_for_status()
        payment = response.json()
        result = {"order": order, "payment": payment}
        if body.outcome == "success":
            response = api.post(
                f"/v1/payments/{payment['id']}/capture",
                json={"amount": body.amount, "currency": "INR"},
            )
            response.raise_for_status()
            result["payment"] = response.json()
            if body.refund_amount is not None:
                response = api.post(
                    f"/v1/payments/{payment['id']}/refund",
                    json={"amount": body.refund_amount},
                )
                response.raise_for_status()
                result["refund"] = response.json()
        return result


@app.post("/webhook")
async def webhook(
    request: Request,
    signature: Annotated[str, Header(alias="X-Razorpay-Signature")],
    event_id: Annotated[str, Header(alias="X-Razorpay-Event-Id", max_length=128)],
    execution: Annotated[
        str | None, Header(alias="X-LocalPay-Scenario-Execution", max_length=128)
    ] = None,
) -> dict[str, bool]:
    payload = await request.body()
    if len(payload) > 65536:
        raise HTTPException(413)
    expected = new(
        os.environ["LOCALPAY_RECEIVER_SECRET"].encode(), payload, sha256
    ).hexdigest()
    if not signature.isascii() or not compare_digest(signature, expected):
        raise HTTPException(401)
    try:
        event = json.loads(payload)["event"]
        if not isinstance(event, str):
            raise TypeError("Invalid event")
    except (TypeError, KeyError, ValueError) as exc:
        raise HTTPException(400) from exc
    with state() as database:
        cursor = database.execute(
            "INSERT OR IGNORE INTO received VALUES (?, ?, ?)",
            (event_id, execution, event),
        )
        return {"processed": cursor.rowcount == 1}


@app.get("/verify")
def verify(
    scenario_execution_id: str, authorization: Annotated[str, Header()]
) -> dict[str, int]:
    expected = "Bearer " + os.environ["LOCALPAY_VERIFICATION_TOKEN"]
    if not authorization.isascii() or not compare_digest(authorization, expected):
        raise HTTPException(401)
    with state() as database:
        count = database.execute(
            "SELECT COUNT(*) FROM received WHERE execution = ?",
            (scenario_execution_id,),
        ).fetchone()[0]
    return {"application_event_count": int(count)}
