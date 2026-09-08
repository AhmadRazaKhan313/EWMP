"""
Request logging middleware.

Attaches a unique request_id to every request (X-Request-ID header).
Logs method, path, status code, and duration for every request.
The request_id flows into AuditLog entries for full traceability.
"""

import time
import uuid
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("ewmp.http")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request with timing and injects X-Request-ID."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else None,
        }

        if response.status_code >= 500:
            logger.error("HTTP request error", extra=log_data)
        elif response.status_code >= 400:
            logger.warning("HTTP client error", extra=log_data)
        else:
            logger.info("HTTP request", extra=log_data)

        return response
