from uuid import uuid4

import httpx
import pytest
from pytest import MonkeyPatch

from app.core.settings import Settings
from app.services.delivery import DeliveryClaim, pin_destination, send


def test_destination_is_pinned_without_dns_and_preserves_request_path() -> None:
    destination, host = pin_destination(
        "http://receiver.test:9000/webhook?q=1",
        {"http://receiver.test:9000": "127.0.0.1"},
    )
    assert str(destination) == "http://127.0.0.1:9000/webhook?q=1"
    assert host == "receiver.test:9000"


@pytest.mark.parametrize(
    "address", ["169.254.169.254", "1.1.1.1", "fe80::1", "100.100.100.200"]
)
def test_destination_blocks_unsafe_addresses(address: str) -> None:
    with pytest.raises(ValueError, match="not a local address"):
        pin_destination(
            "http://receiver.test/webhook", {"http://receiver.test": address}
        )


def test_destination_requires_explicit_port_and_origin() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        pin_destination(
            "http://receiver.test:80/webhook",
            {"http://receiver.test:9000": "127.0.0.1"},
        )
    with pytest.raises(ValueError, match="Invalid webhook target"):
        pin_destination(
            "http://user@receiver.test/webhook", {"http://receiver.test": "127.0.0.1"}
        )


@pytest.mark.parametrize(
    ("behavior", "code", "retryable"),
    [
        (400, None, False),
        (429, None, True),
        (503, None, True),
        (302, None, False),
        ("timeout", "timeout", True),
        ("refused", "connection_error", True),
    ],
)
def test_transport_classifies_responses(
    monkeypatch: MonkeyPatch, behavior: int | str, code: str | None, retryable: bool
) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if behavior == "timeout":
            raise httpx.ReadTimeout("timeout")
        if behavior == "refused":
            raise httpx.ConnectError("connection refused")
        assert isinstance(behavior, int)
        return httpx.Response(behavior, request=request)

    client_type = httpx.Client

    def make_client(**kwargs: object) -> httpx.Client:
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return client_type(transport=httpx.MockTransport(answer))

    monkeypatch.setattr("app.services.delivery.httpx.Client", make_client)
    monkeypatch.setenv(
        "LOCALPAY_DATABASE_URL", "postgresql+psycopg://localhost/localpay"
    )
    monkeypatch.setenv("LOCALPAY_REDIS_URL", "redis://localhost")
    settings = Settings(webhook_targets={"http://receiver.test": "127.0.0.1"})
    claim = DeliveryClaim(
        uuid4(), uuid4(), uuid4(), 1, "http://receiver.test/hook", b"{}", {}
    )
    result = send(claim, settings)
    assert result.error_code == code
    assert result.retryable is retryable
    if isinstance(behavior, int):
        assert result.http_status == behavior
