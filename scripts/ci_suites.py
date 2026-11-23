import argparse
import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4
from xml.etree.ElementTree import fromstring

BASE_URL = os.environ["LOCALPAY_API_URL"]
ADMIN = {"Authorization": "Bearer " + os.environ["LOCALPAY_ADMIN_TOKEN"]}
CLI = Path("packages/cli/.venv/bin/localpay").resolve()


def api(
    path: str, body: object | None = None, headers: dict[str, str] | None = None
) -> Any:
    request = Request(
        BASE_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={**(headers or ADMIN), "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def new_project() -> str:
    return str(
        api(
            "/localpay/admin/v1/projects",
            {
                "slug": "ci-" + uuid4().hex,
                "name": "CI reliability verification",
            },
        )["id"]
    )


def payment_suite(expected: int, application: bool = False) -> dict[str, Any]:
    return {
        "name": uuid4().hex,
        "tests": [
            {
                "name": "Capture accounting",
                "scenario": "payment.concurrent_capture",
                "assertions": [
                    {
                        "type": "application_event_count"
                        if application
                        else "amount_paid",
                        "expected": expected,
                    }
                ],
            }
        ],
    }


def webhook_suite(root: str) -> dict[str, Any]:
    issued = api(f"{root}/credentials", {"label": "CI receiver"})
    key = base64.b64encode(f"{issued['key_id']}:{issued['secret']}".encode()).decode()
    headers = {"Authorization": "Basic " + key}
    order = api("/v1/orders", {"amount": 600, "currency": "INR"}, headers)
    payment = api(
        "/localpay/v1/simulations/payments", {"order_id": order["id"]}, headers
    )
    api(
        f"/v1/payments/{payment['id']}/capture",
        {"amount": 600, "currency": "INR"},
        headers,
    )
    events = api(f"{root}/webhook-events")
    event_id = next(
        item["id"] for item in events if item["event_type"] == "payment.captured"
    )
    endpoint_data = {
        "url": "http://receiver:9001/webhook",
        "secret": os.environ["LOCALPAY_RECEIVER_SECRET"],
        "enabled_events": ["payment.captured"],
    }
    endpoint = api(f"{root}/webhook-endpoints", endpoint_data)
    disabled = api(
        f"{root}/webhook-endpoints",
        {
            **endpoint_data,
            "url": "http://receiver:9001/disabled",
            "enabled": False,
        },
    )
    definition = {
        "name": uuid4().hex,
        "verification_url": "http://receiver:9001/verify",
        "tests": [
            {
                "name": "Duplicate webhook processing",
                "scenario": "webhook.duplicate",
                "config": {"duplicate_count": 2},
                "endpoint_id": endpoint["id"],
                "event_ids": [event_id],
                "assertions": [
                    {"type": "delivery_count", "expected": 2},
                    {"type": "received_http_status", "expected": 200},
                    {"type": "application_event_count", "expected": 1},
                ],
            }
        ],
    }
    invalid = {
        "name": uuid4().hex,
        "tests": [{**definition["tests"][0], "endpoint_id": disabled["id"]}],
    }
    return {"passing": definition, "error": invalid}


def verify_run(
    results: Path,
    project: str,
    definition: dict[str, Any],
    expected_status: str,
    expected_code: int,
) -> None:
    root = f"/localpay/admin/v1/projects/{project}"
    suite = api(f"{root}/test-suites", definition)
    result = subprocess.run(
        [
            str(CLI),
            "--project",
            project,
            "test",
            "run",
            "--suite-id",
            suite["id"],
            "--timeout",
            "1" if expected_status == "blocked" else "55",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=70,
    )
    assert result.returncode == expected_code, (
        expected_status,
        result.returncode,
        result.stderr,
    )
    run = json.loads(result.stdout)
    assert run["status"] == expected_status, run
    output = results / f"{expected_status}-{run['id']}"
    output.with_suffix(".json").write_text(result.stdout)
    if expected_status == "blocked":
        assert run["reason"] == "timeout"
        assert api(f"{root}/test-runs/{run['id']}")["status"] == "pending"
        print("blocked: verified deadline with the reliability worker stopped")
        return
    assert api(f"{root}/test-runs/{run['id']}") == run
    for kind, suffix in (("junit", ".xml"), ("html", ".html")):
        target = output.with_suffix(suffix)
        subprocess.run(
            [
                str(CLI),
                "--project",
                project,
                "test",
                "report",
                run["id"],
                "--format",
                kind,
                "--output",
                str(target),
            ],
            check=True,
            timeout=15,
        )
    document = fromstring(output.with_suffix(".xml").read_text())
    assert document.tag == "testsuite"
    assert document.attrib["tests"] == "1"
    for tag, value in (
        ("failures", "failed"),
        ("errors", "error"),
        ("skipped", "inconclusive"),
    ):
        assert int(document.attrib[tag]) == (expected_status == value)
    print(
        f"{expected_status}: CLI exit {result.returncode}; API, HTML, and JUnit agree"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--verify-blocked", action="store_true")
    args = parser.parse_args()
    project = new_project()
    if args.verify_blocked:
        verify_run(args.results, project, payment_suite(600), "blocked", 4)
        return
    root = f"/localpay/admin/v1/projects/{project}"
    webhooks = webhook_suite(root)
    verify_run(args.results, project, webhooks["passing"], "passed", 0)
    verify_run(args.results, project, payment_suite(1), "failed", 1)
    verify_run(args.results, project, webhooks["error"], "error", 2)
    verify_run(
        args.results, project, payment_suite(1, application=True), "inconclusive", 3
    )


if __name__ == "__main__":
    main()
