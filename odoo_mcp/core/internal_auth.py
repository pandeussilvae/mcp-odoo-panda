"""Service-to-service auth for the HTTP sidecar (integrator hop).

Standalone: no Odward domain imports. When enabled, every HTTP request
(including /health and /mcp) must present ``X-Odward-Internal-Token``.

The expected secret comes only from env ``ODWARD_INTERNAL_TOKEN``.
There is no built-in production default. Comparison is constant-time.
The secret must never appear in logs or HTTP response bodies.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

HEADER_INTERNAL_TOKEN = "X-Odward-Internal-Token"
ENV_INTERNAL_TOKEN = "ODWARD_INTERNAL_TOKEN"
ENV_REQUIRE_INTERNAL_AUTH = "ODWARD_REQUIRE_INTERNAL_AUTH"
_MIN_TOKEN_LEN = 32


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def deployment_is_production() -> bool:
    return os.getenv("ODWARD_DEPLOYMENT", "").strip().lower() in {"production", "prod"}


def configured_internal_token() -> Optional[str]:
    """Return the configured token, or None if unset/blank."""
    raw = os.getenv(ENV_INTERNAL_TOKEN)
    if raw is None:
        return None
    token = raw.strip()
    return token or None


def internal_auth_required() -> bool:
    """True when the process must enforce the internal token (fail-closed)."""
    if _env_flag(ENV_REQUIRE_INTERNAL_AUTH):
        return True
    if deployment_is_production():
        return True
    return configured_internal_token() is not None


def assert_internal_auth_boot(*, require: bool = False) -> str:
    """Fail-closed at process start when auth is required.

    Returns the configured token. Never logs the secret value.
    """
    must = bool(require) or internal_auth_required()
    token = configured_internal_token()
    if not must:
        if token is None:
            raise RuntimeError("internal auth misconfigured")
        return token
    if token is None:
        logger.error("internal auth fail-closed: %s missing or empty", ENV_INTERNAL_TOKEN)
        raise RuntimeError("internal auth misconfigured")
    if len(token) < _MIN_TOKEN_LEN:
        logger.error("internal auth fail-closed: %s entropy too low", ENV_INTERNAL_TOKEN)
        raise RuntimeError("internal auth misconfigured")
    return token


def verify_internal_token(provided: Optional[str], expected: str) -> bool:
    """Constant-time compare; never log either value."""
    if not provided or not expected:
        return False
    try:
        return secrets.compare_digest(
            provided.encode("utf-8"),
            expected.encode("utf-8"),
        )
    except (TypeError, ValueError):
        return False


def extract_internal_token(headers) -> Optional[str]:  # noqa: ANN001 — Starlette Headers
    get = headers.get if hasattr(headers, "get") else lambda _k, d=None: d
    raw = get(HEADER_INTERNAL_TOKEN) or get(HEADER_INTERNAL_TOKEN.lower())
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """Reject every HTTP request without a valid internal token (entire surface)."""

    def __init__(self, app, *, expected_token: str):  # noqa: ANN001
        super().__init__(app)
        self._expected = expected_token

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        provided = extract_internal_token(request.headers)
        if not verify_internal_token(provided, self._expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
