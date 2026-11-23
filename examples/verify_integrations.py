import json
import os
import socket
import subprocess
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
API = os.environ.get("LOCALPAY_API_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN = {"Authorization": f"Bearer {os.environ['LOCALPAY_ADMIN_TOKEN']}"}


def request(
    url: str,
    body: object | bytes | None = None,
    headers: dict[str, str] | None = None,
    expected: int = 200,
) -> tuple[Any, dict[str, str]]:
    data = (
        body
        if isinstance(body, bytes)
        else json.dumps(body).encode()
        if body is not None
        else None
    )
    with_request = Request(
        url, data=data, headers={"Content-Type": "application/json", **(headers or {})}
    )
    try:
        with urlopen(with_request, timeout=8) as response:
            assert response.status == expected, response.status
            payload = response.read()
            return payload, {
                key.lower(): value for key, value in response.headers.items()
            }
    except HTTPError as exc:
        assert exc.code == expected, (url, exc.code)
        return b"", {}


def decode(payload: tuple[Any, dict[str, str]]) -> Any:
    return json.loads(payload[0])


def reserve_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def verify(directory: str, command: list[str]) -> None:
    project = decode(
        request(
            f"{API}/localpay/admin/v1/projects",
            {
                "slug": "example-" + uuid4().hex,
                "name": directory,
            },
            ADMIN,
            expected=201,
        )
    )
    root = f"{API}/localpay/admin/v1/projects/{project['id']}"
    credential = decode(
        request(f"{root}/credentials", {"label": directory}, ADMIN, expected=201)
    )
    secret = token_hex(32)
    verify_token = token_hex(32)
    port = reserve_port()
    origin = f"http://127.0.0.1:{port}"
    with TemporaryDirectory() as scratch:
        env = {
            **os.environ,
            "PORT": str(port),
            "LOCALPAY_API_URL": API,
            "LOCALPAY_KEY_ID": credential["key_id"],
            "LOCALPAY_KEY_SECRET": credential["secret"],
            "LOCALPAY_RECEIVER_SECRET": secret,
            "LOCALPAY_VERIFICATION_TOKEN": verify_token,
            "LOCALPAY_EXAMPLE_DATABASE": str(Path(scratch) / "events.db"),
        }
        with subprocess.Popen(
            [piece.replace("{port}", str(port)) for piece in command],
            cwd=ROOT / directory,
            env=env,
        ) as server:
            try:
                deadline = monotonic() + 12
                while monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError(
                            f"{directory} exited with code {server.returncode}"
                        )
                    try:
                        request(f"{origin}/health")
                        break
                    except (URLError, OSError):
                        sleep(0.1)
                else:
                    raise TimeoutError("Example failed to start")
                success = decode(
                    request(
                        f"{origin}/checkout",
                        {
                            "amount": 600,
                            "outcome": "success",
                            "refund_amount": 200,
                        },
                    )
                )
                assert success["order"]["entity"] == "order"
                assert success["payment"]["status"] == "captured"
                assert success["refund"]["amount"] == 200
                failed = decode(
                    request(f"{origin}/checkout", {"amount": 600, "outcome": "failed"})
                )
                assert failed["payment"]["status"] == "failed"
                endpoint = decode(
                    request(
                        f"{root}/webhook-endpoints",
                        {
                            "url": f"{origin}/webhook",
                            "secret": secret,
                            "enabled_events": ["payment.captured"],
                        },
                        ADMIN,
                        expected=201,
                    )
                )
                events = decode(request(f"{root}/webhook-events", headers=ADMIN))
                event_id = next(
                    item["id"]
                    for item in events
                    if item["event_type"] == "payment.captured"
                )
                payload, signed = request(
                    f"{root}/webhook-events/{event_id}/signed/{endpoint['id']}",
                    headers=ADMIN,
                )
                execution = uuid4().hex
                delivery = {
                    "X-Razorpay-Event-Id": signed["x-razorpay-event-id"],
                    "X-Razorpay-Signature": signed["x-razorpay-signature"],
                    "X-LocalPay-Scenario-Execution": execution,
                }
                request(f"{origin}/webhook", payload + b" ", delivery, expected=401)
                assert decode(request(f"{origin}/webhook", payload, delivery))[
                    "processed"
                ]
                assert not decode(request(f"{origin}/webhook", payload, delivery))[
                    "processed"
                ]
                endpoint_url = f"{origin}/verify?scenario_execution_id={execution}"
                request(
                    endpoint_url,
                    headers={"Authorization": "Bearer incorrect"},
                    expected=401,
                )
                observed = decode(
                    request(
                        endpoint_url,
                        headers={"Authorization": f"Bearer {verify_token}"},
                    )
                )
                assert observed == {"application_event_count": 1}
                print(
                    f"{directory}: checkout, failed payment, capture, refund, signature, and deduplication passed"
                )
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    verify(
        "fastapi-integration",
        [".venv/bin/uvicorn", "app:app", "--host", "127.0.0.1", "--port", "{port}"],
    )
    verify("node-integration", ["node", "app.mjs"])
