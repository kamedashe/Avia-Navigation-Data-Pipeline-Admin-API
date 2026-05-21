"""Changes Router.

Serves ``changes.json`` enriched with dynamically computed directory sizes
for multi-file resources (airport diagrams, VFR maps).

- ``GET /changes/`` — Full metadata JSON used by mobile clients to decide
  whether a re-download is needed.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.services.file_handlers import enrich_changes_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/changes", tags=["Changes File"])

# Resolved relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CHANGES_FILE = _PROJECT_ROOT / "data" / "changes.json"


@router.get("/")
def get_changes_file():
    """Return the current state of all data categories.

    Merges the static ``changes.json`` (maintained by scrapers) with
    dynamically computed directory sizes for ``a_big``, ``a_small``,
    and ``m_sectional``.
    """
    # 1. Load base data from changes.json
    try:
        with open(_CHANGES_FILE, "r", encoding="utf-8") as f:
            data: dict = json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"changes.json not found (looked at {_CHANGES_FILE.resolve()})",
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error decoding changes.json",
        )

    # 2. Dynamically enrich with directory sizes and mtime
    enrich_changes_data(data)

    return JSONResponse(content=data)
