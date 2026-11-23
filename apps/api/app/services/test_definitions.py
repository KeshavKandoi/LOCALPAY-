from typing import Annotated, Literal
from uuid import UUID

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)
from yaml.tokens import AliasToken

from app.services.payment_chaos import FAULT_CODES, PaymentChaosType
from app.services.webhook_chaos import WebhookChaos

Name = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00]+$"
    ),
]
AssertionType = Literal[
    "scenario_passed",
    "amount_paid",
    "amount_refunded",
    "received_http_status",
    "delivery_count",
    "application_event_count",
    "application_payment_count",
    "application_refund_state",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Assertion(StrictModel):
    type: AssertionType
    expected: bool | int | str

    @model_validator(mode="after")
    def validate_expected(self) -> "Assertion":
        exact_type = (
            str
            if self.type == "application_refund_state"
            else (bool if self.type == "scenario_passed" else int)
        )
        if type(self.expected) is not exact_type:
            raise ValueError("Expected value must match the assertion type")
        return self


class TestCase(StrictModel):
    name: Name
    scenario: PaymentChaosType | Literal["webhook.chaos", "webhook.duplicate"]
    amount: Annotated[int, Field(strict=True, ge=100, le=1_000_000_000)] = 600
    config: WebhookChaos | None = None
    endpoint_id: UUID | None = None
    event_ids: Annotated[set[UUID], Field(max_length=16)] = Field(default_factory=set)
    assertions: Annotated[list[Assertion], Field(min_length=1, max_length=12)]

    @model_validator(mode="after")
    def validate_scenario(self) -> "TestCase":
        if self.scenario in FAULT_CODES:
            raise ValueError(
                "Live gateway fault scenarios run through the payment chaos API"
            )
        if isinstance(self.scenario, PaymentChaosType):
            if (
                self.config is not None
                or self.endpoint_id is not None
                or self.event_ids
            ):
                raise ValueError(
                    "Payment scenarios do not accept webhook configuration"
                )
        elif self.endpoint_id is None or not self.event_ids:
            raise ValueError("Webhook scenarios require an endpoint and events")
        return self


class SuiteDefinition(StrictModel):
    name: Name
    version: Literal[1] = 1
    tests: Annotated[list[TestCase], Field(min_length=1, max_length=12)]
    verification_url: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_suite(self) -> "SuiteDefinition":
        if len({case.name for case in self.tests}) != len(self.tests):
            raise ValueError("Test names must be unique")
        if self.verification_url is not None and (
            self.verification_url.username is not None
            or self.verification_url.password is not None
            or self.verification_url.fragment is not None
        ):
            raise ValueError("Invalid verification URL")
        return self


def parse_suite_yaml(content: str) -> SuiteDefinition:
    if len(content.encode()) > 65536:
        raise ValueError("Suite file exceeds 64 KiB")
    try:
        if any(isinstance(token, AliasToken) for token in yaml.scan(content)):
            raise ValueError("YAML aliases are unsupported")
        parsed = yaml.safe_load(content)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError("Invalid YAML suite") from exc
    return SuiteDefinition.model_validate(parsed)
