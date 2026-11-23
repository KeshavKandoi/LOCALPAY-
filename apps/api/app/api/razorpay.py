from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class RazorpayError(Exception):
    def __init__(
        self, description: str, field: str | None = None, status: int = 400
    ) -> None:
        self.description = description
        self.field = field
        self.status = status

    def response(self) -> JSONResponse:
        authentication = self.status == 401
        error: dict[str, str | dict[str, str]] = {
            "code": "BAD_REQUEST_ERROR",
            "description": self.description,
            "source": "NA" if authentication else "business",
            "step": "NA" if authentication else "payment_initiation",
            "reason": "NA" if authentication else "input_validation_failed",
            "metadata": {},
        }
        if self.field is not None:
            error["field"] = self.field
        return JSONResponse(
            {"error": error}, status_code=400 if authentication else self.status
        )


class RazorpayRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RazorpayError as exc:
                return exc.response()
            except RequestValidationError as exc:
                error = exc.errors()[0]
                kind = error["type"]
                location = error["loc"]
                field = (
                    location[1]
                    if len(location) >= 2 and isinstance(location[1], str)
                    else None
                )
                if kind == "json_invalid":
                    return RazorpayError("Invalid JSON request body").response()
                if kind == "missing":
                    return RazorpayError(
                        f"The {field or 'request body'} field is required.", field
                    ).response()
                if field == "amount" and kind == "int_type":
                    return RazorpayError(
                        "The amount must be an integer.", field
                    ).response()
                if field == "amount" and kind == "greater_than_equal":
                    return RazorpayError(
                        "amount: must be no less than 0.", field
                    ).response()
                return RazorpayError(
                    f"Invalid {field or 'request body'}.", field
                ).response()
            except HTTPException as exc:
                if exc.status_code != 401:
                    raise
                return RazorpayError(
                    "The api key provided is invalid", status=401
                ).response()

        return handle
