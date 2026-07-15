"""Admin token authentication.

The original FastAPI app *sent* a Bearer token from the dashboard but never
verified it server-side. This port makes the check real:

- API data/action endpoints (``/api/status``, ``/api/task-status``,
  ``/api/run/<flag>``) require ``Authorization: Bearer <AUTH_TOKEN>`` — which
  is exactly what the dashboard JavaScript already sends.
- The ``/admin`` HTML page uses HTTP Basic auth so it can be gated on a plain
  browser navigation (no way to set an Authorization header otherwise). Any
  username is accepted; the password must equal ``AUTH_TOKEN``.

If ``AUTH_TOKEN`` is empty the checks are skipped (dev convenience) and a
warning is logged, mirroring the original app's tolerance of an unset token.
Public file endpoints (b/c/d/.../maps/diagrams/changes) stay open, as before.
"""

import base64
import hmac
import logging
from functools import wraps

from django.conf import settings
from django.http import HttpResponse, JsonResponse

logger = logging.getLogger(__name__)


def _configured_token() -> str:
    return settings.ADMIN_AUTH_TOKEN or ""


def _token_matches(candidate: str) -> bool:
    """Constant-time compare of a candidate token against the configured one."""
    token = _configured_token()
    if not token:
        # Auth disabled — accept everything.
        return True
    return hmac.compare_digest(candidate or "", token)


def require_bearer(view_func):
    """Require ``Authorization: Bearer <AUTH_TOKEN>`` on the request."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _configured_token():
            logger.warning(
                "AUTH_TOKEN is not set — admin endpoint '%s' is UNPROTECTED.",
                request.path,
            )
            return view_func(request, *args, **kwargs)

        header = request.headers.get("Authorization", "")
        candidate = header[7:] if header.startswith("Bearer ") else ""
        if not _token_matches(candidate):
            return JsonResponse(
                {"detail": "Unauthorized: missing or invalid admin token."},
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped


def require_basic(view_func):
    """Gate a browser-facing page behind HTTP Basic auth (password = token)."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _configured_token():
            logger.warning(
                "AUTH_TOKEN is not set — admin page '%s' is UNPROTECTED.",
                request.path,
            )
            return view_func(request, *args, **kwargs)

        header = request.headers.get("Authorization", "")
        authorized = False
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8", "ignore")
                _, _, password = decoded.partition(":")
                authorized = _token_matches(password)
            except Exception:  # malformed header
                authorized = False

        if not authorized:
            resp = HttpResponse("Unauthorized", status=401)
            resp["WWW-Authenticate"] = 'Basic realm="Avia Navigation Admin"'
            return resp
        return view_func(request, *args, **kwargs)

    return _wrapped
