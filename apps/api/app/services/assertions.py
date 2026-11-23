import json
from uuid import UUID

import httpx

from app.core.settings import Settings
from app.models import JsonObject
from app.services.delivery import pin_destination
from app.services.test_definitions import Assertion


def evaluate(assertions: list[Assertion], evidence: JsonObject) -> list[JsonObject]:
    outcomes = []
    for assertion in assertions:
        value = evidence.get(assertion.type)
        if value is None or type(value) is not type(assertion.expected):
            status = "inconclusive"
        else:
            status = "passed" if value == assertion.expected else "failed"
        outcomes.append(
            {
                "type": assertion.type,
                "expected": assertion.expected,
                "observed": value,
                "status": status,
            }
        )
    return outcomes


def verify_application(
    url: str | None,
    settings: Settings,
    run_id: UUID,
    case: str,
    scenario_evidence: JsonObject,
) -> JsonObject:
    if url is None or settings.verification_token is None:
        return {}
    try:
        destination, host = pin_destination(url, settings.webhook_targets)
        request_data: dict[str, str] = {
            "run_id": str(run_id),
            "case": case,
            **{
                name: str(scenario_evidence[name])
                for name in ("order_id", "scenario_execution_id")
                if name in scenario_evidence
            },
        }
        original_query = destination.params.merge(request_data)
        with (
            httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client,
            client.stream(
                "GET",
                destination.copy_with(params=original_query),
                headers={
                    "Host": host,
                    "Authorization": f"Bearer {settings.verification_token.get_secret_value()}",
                },
                extensions={"sni_hostname": httpx.URL(url).host},
            ) as response,
        ):
            response.raise_for_status()
            chunks = bytearray()
            for chunk in response.iter_bytes():
                if len(chunks) + len(chunk) > 16384:
                    return {}
                chunks.extend(chunk)
        parsed = json.loads(chunks)
    except (ValueError, httpx.HTTPError, httpx.InvalidURL):
        return {}
    observations: JsonObject = {}
    if isinstance(parsed, dict):
        for name in (
            "application_event_count",
            "application_payment_count",
            "application_refund_state",
        ):
            value = parsed.get(name)
            if (name.endswith("_count") and type(value) is int and value >= 0) or (
                name.endswith("_state") and isinstance(value, str) and len(value) <= 32
            ):
                observations[name] = value
    return observations
