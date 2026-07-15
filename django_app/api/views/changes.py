"""Changes view.

Serves ``changes.json`` enriched with dynamically computed directory sizes for
multi-file resources (airport diagrams, VFR maps).
"""

import json
import logging

from django.conf import settings
from django.http import JsonResponse

from api.services.file_handlers import enrich_changes_data

logger = logging.getLogger(__name__)

_CHANGES_FILE = settings.DATA_DIR / "changes.json"


def get_changes_file(request):
    """Return the current state of all data categories.

    Merges the static ``changes.json`` (maintained by scrapers) with
    dynamically computed directory sizes for ``a_big``, ``a_small``, and
    ``m_sectional``.
    """
    try:
        with open(_CHANGES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return JsonResponse(
            {"detail": f"changes.json not found (looked at {_CHANGES_FILE.resolve()})"},
            status=404,
        )
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Error decoding changes.json"}, status=500)

    enrich_changes_data(data)

    return JsonResponse(data)
