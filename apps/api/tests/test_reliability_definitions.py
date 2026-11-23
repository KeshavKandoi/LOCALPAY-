import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.settings import Settings
from app.services.assertions import evaluate, verify_application
from app.services.test_definitions import parse_suite_yaml

SUITE = """
name: smoke
version: 1
tests:
  - name: race
    scenario: payment.concurrent_capture
    assertions:
      - type: scenario_passed
        expected: true
"""


def test_yaml_and_assertions_are_typed() -> None:
    suite = parse_suite_yaml(SUITE)
    [case] = suite.tests
    assert evaluate(case.assertions, {"scenario_passed": True})[0]["status"] == "passed"
    assert (
        evaluate(case.assertions, {"scenario_passed": False})[0]["status"] == "failed"
    )
    assert (
        evaluate(case.assertions, {"scenario_passed": 1})[0]["status"] == "inconclusive"
    )
    assert evaluate(case.assertions, {})[0]["status"] == "inconclusive"


@pytest.mark.parametrize(
    "content",
    [
        "value: &x [*x]",
        "name: [",
        SUITE.replace("true", "1"),
        SUITE.replace("payment.concurrent_capture", "payment.gateway_outage"),
        " " * 65537,
    ],
)
def test_invalid_yaml_suites_are_rejected(content: str) -> None:
    with pytest.raises(ValueError):
        parse_suite_yaml(content)


@pytest.mark.integration
def test_protected_application_verification_reads_actual_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LOCALPAY_DATABASE_URL", "postgresql+psycopg://localhost/localpay"
    )
    monkeypatch.setenv("LOCALPAY_REDIS_URL", "redis://localhost")
    token = uuid4().hex
    run = uuid4()

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if (
                self.headers.get("Authorization") != f"Bearer {token}"
                or str(run) not in self.path
            ):
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps(
                {"application_event_count": 1, "application_payment_count": True}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        config = Settings(
            verification_token=SecretStr(token), webhook_targets={origin: "127.0.0.1"}
        )
        assert verify_application(
            f"{origin}/evidence", config, run, "duplicate", {}
        ) == {"application_event_count": 1}
        assert (
            verify_application(f"{origin}/evidence", config, uuid4(), "duplicate", {})
            == {}
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
