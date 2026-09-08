"""
Global exception handlers.

Converts every EWMPException subclass into a consistent JSON error response.
Also handles Pydantic ValidationError and unhandled exceptions.

Error response shape:
    {
        "error": "PERMISSION_DENIED",
        "message": "You do not have permission to perform this action",
        "detail": null,
        "request_id": "abc-123"
    }
"""

import logging
import traceback
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.exceptions import EWMPException

logger = logging.getLogger("ewmp.errors")


def _error_response(
    request: Request,
    status_code: int,
    error_code: str,
    message: str,
    detail: Any = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error_code,
            "message": message,
            "detail": detail,
            "request_id": request_id,
        },
    )


async def ewmp_exception_handler(request: Request, exc: EWMPException) -> JSONResponse:
    """Handle all application-defined exceptions."""
    return _error_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        message=exc.message,
        detail=exc.detail,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic request body validation failures."""
    errors = []
    for error in exc.errors():
        field = " → ".join(str(loc) for loc in error["loc"])
        errors.append({"field": field, "message": error["msg"], "type": error["type"]})

    return _error_response(
        request,
        status_code=422,
        error_code="VALIDATION_ERROR",
        message="Request validation failed",
        detail=errors,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unexpected exceptions. Logs full traceback."""
    logger.error(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        exc_info=True,
    )
    return _error_response(
        request,
        status_code=500,
        error_code="INTERNAL_ERROR",
        message="An unexpected error occurred. Our team has been notified.",
        detail=None,
    )


def register_exception_handlers(app: Any) -> None:
    """Register all exception handlers on the FastAPI app instance."""
    app.add_exception_handler(EWMPException, ewmp_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
