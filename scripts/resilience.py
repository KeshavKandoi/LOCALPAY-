import argparse
import base64
import json
import os
import subprocess
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from ci_suites import BASE_URL, api, new_project

COMPOSE = ("docker", "compose", "-f", "compose.yaml", "-f", "infra/ci.compose.yaml")


def compose(*args: str) -> str:
    return subprocess.run(
        [*COMPOSE, *args], capture_output=True, text=True, check=True, timeout=90
    ).stdout


def ready_code() -> tuple[int, dict[str, Any]]:
    try:
        with urlopen(BASE_URL + "/ready", timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def wait_ready() -> None:
    deadline = monotonic() + 30
    while monotonic() < deadline:
        try:
            if ready_code()[0] == 200:
                return
        except (URLError, TimeoutError):
            sleep(0.2)
            continue
        sleep(0.2)
    raise TimeoutError("Readiness did not recover")


def setup() -> tuple[str, dict[str, str]]:
    root = f"/localpay/admin/v1/projects/{new_project()}"
    key = api(f"{root}/credentials", {"label": "Resilience measurement"})
    basic = base64.b64encode(f"{key['key_id']}:{key['secret']}".encode()).decode()
    api(
        f"{root}/webhook-endpoints",
        {
            "url": "http://receiver:9001/webhook",
            "secret": os.environ["LOCALPAY_RECEIVER_SECRET"],
            "enabled_events": ["payment.captured"],
        },
    )
    return root, {"Authorization": "Basic " + basic}


def captured(auth: dict[str, str]) -> str:
    order = api("/v1/orders", {"amount": 600, "currency": "INR"}, auth)
    payment = api("/localpay/v1/simulations/payments", {"order_id": order["id"]}, auth)
    api(
        f"/v1/payments/{payment['id']}/capture",
        {"amount": 600, "currency": "INR"},
        auth,
    )
    return str(order["id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root, auth = setup()
    compose("stop", "worker", "redis")
    try:
        code, response = ready_code()
        assert code == 503 and response["dependencies"] == {
            "postgres": "up",
            "redis": "down",
        }
        assert api("/health")["status"] == "ok"
        order_id = captured(auth)
        [before] = api(root + "/webhook-deliveries")
        assert before["status"] == "pending"
    finally:
        compose("start", "redis", "worker")
    wait_ready()
    deadline = monotonic() + 40
    while monotonic() < deadline:
        [recovered] = api(root + "/webhook-deliveries")
        if recovered["status"] == "delivered":
            break
        sleep(0.25)
    else:
        raise TimeoutError("Persisted delivery did not recover")
    assert recovered["id"] == before["id"]
    [attempt] = api(root + "/webhook-deliveries/" + recovered["id"] + "/attempts")
    assert attempt["http_status"] == 200
    compose("stop", "postgres")
    try:
        code, response = ready_code()
        assert code == 503 and response["dependencies"]["postgres"] == "down"
        assert api("/health")["status"] == "ok"
    finally:
        compose("start", "postgres")
    wait_ready()
    assert api(f"/v1/orders/{order_id}", headers=auth)["status"] == "paid"
    users = {}
    for service in (
        "api",
        "worker",
        "scheduler",
        "reliability-worker",
        "dashboard",
        "receiver",
    ):
        user = int(compose("exec", "-T", service, "id", "-u").strip())
        assert user != 0
        users[service] = user
    result = {
        "redis_and_worker_restart": "outbox delivered after recovery",
        "postgres_restart": "saved order visible after recovery",
        "container_users": users,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
