import logging
from collections.abc import Mapping
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("localpay.errors")


def error_response(
    code: str, status: int, headers: Mapping[str, str] | None = None
) -> Response:
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=headers)


async def http_error(request: Request, exc: Exception) -> Response:
    error = cast(HTTPException, exc)
    return error_response("http_error", error.status_code, error.headers)


async def validation_error(request: Request, exc: Exception) -> Response:
    return error_response("invalid_request", 422)


class ServerErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def track_response(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except Exception as exc:
            if response_started:
                raise
            incident = str(uuid4())
            logger.error(
                "Request failed incident=%s type=%s", incident, type(exc).__name__
            )
            response = error_response(
                "internal_error", 500, {"X-Incident-ID": incident}
            )
            await response(scope, receive, send)


def install_error_handling(app: FastAPI) -> None:
    app.add_middleware(ServerErrorMiddleware)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
