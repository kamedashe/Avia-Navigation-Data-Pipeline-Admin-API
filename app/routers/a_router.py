"""Airport Diagrams Router.

Provides two endpoint groups:

- ``/api/v1/a-big/download``        — Download full a-big.tar.gz archive
- ``/api/v1/a-big/{state}/{code}``  — Full FAA airport diagram (WebP)
- ``/api/v1/a-big/{state}``         — List available codes for a state
- ``/api/v1/a-big``                 — List available states

- ``/api/v1/a-small/download``      — Download full a-small.tar.gz archive
- ``/api/v1/a-small/{code}``        — Inverted AOPA sketch (PNG)
- ``/api/v1/a-small``               — List available sketches
"""

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse

from app.services.task_status import task_statuses
from app.services.safety_check import assert_file_safe

router = APIRouter(prefix="/api/v1", tags=["Airport Diagrams"])

# Base directories — resolved relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_A_BIG_DIR = _PROJECT_ROOT / "data" / "a_big"
_A_SMALL_DIR = _PROJECT_ROOT / "data" / "a_small"
_DOWNLOADED_DIR = _PROJECT_ROOT / "downloaded_data"


# ═══════════════════════════════════════════════════════════════════════════
# DOWNLOAD: Tar.gz archive endpoints (legacy mobile app compatibility)
# ── Must be declared BEFORE parametrized /{state} and /{code} routes ──
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/a-big/download")
def download_a_big_archive():
    """Download the full a-big.tar.gz archive.

    Legacy endpoint used by the mobile app to fetch the complete
    airport diagrams bundle synced from Server B.

    Example: ``GET /api/v1/a-big/download``
    """
    archive_path = _DOWNLOADED_DIR / "a-big.tar.gz"
    if not archive_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="a-big.tar.gz archive not found. Run sync from Server B first.",
        )
    assert_file_safe("a_big", archive_path, task_statuses=task_statuses)
    return FileResponse(
        path=str(archive_path),
        filename="a-big.tar.gz",
        media_type="application/gzip",
    )


@router.get("/a-small/download")
def download_a_small_archive():
    """Download the full a-small.tar.gz archive.

    Legacy endpoint used by the mobile app to fetch the complete
    airport sketches bundle synced from Server B.

    Example: ``GET /api/v1/a-small/download``
    """
    archive_path = _DOWNLOADED_DIR / "a-small.tar.gz"
    if not archive_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="a-small.tar.gz archive not found. Run sync from Server B first.",
        )
    assert_file_safe("a_small", archive_path, task_statuses=task_statuses)
    return FileResponse(
        path=str(archive_path),
        filename="a-small.tar.gz",
        media_type="application/gzip",
    )


# ═══════════════════════════════════════════════════════════════════════════
# A-BIG: FAA Airport Diagrams (WebP, organized by state)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/a-big", response_class=JSONResponse)
def list_a_big_states():
    """List all available states that have airport diagrams."""
    if not _A_BIG_DIR.is_dir():
        return JSONResponse(content={"states": []}, status_code=200)

    states = sorted(
        entry.name
        for entry in _A_BIG_DIR.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )
    return JSONResponse(
        content={"states": states, "count": len(states)},
        status_code=200,
    )


@router.get("/a-big/{state}", response_class=JSONResponse)
def list_a_big_codes(state: str):
    """List all available airport diagram codes within a given state."""
    state_dir = _A_BIG_DIR / state.upper()
    if not state_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No diagrams found for state '{state}'.",
        )

    codes = sorted(
        f.stem for f in state_dir.glob("*.webp")
    )
    return JSONResponse(
        content={"state": state.upper(), "codes": codes, "count": len(codes)},
        status_code=200,
    )


@router.get("/a-big/{state}/{code}")
def get_a_big_diagram(state: str, code: str):
    """Get a specific airport diagram (WebP) by state and FAA code.

    Example: ``GET /api/v1/a-big/CA/LAX``
    """
    webp_path = _A_BIG_DIR / state.upper() / f"{code.upper()}.webp"
    if not webp_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Airport diagram not found for {code.upper()} in {state.upper()}.",
        )
    return FileResponse(
        path=str(webp_path),
        filename=f"{code.upper()}_Airport_Diagram.webp",
        media_type="image/webp",
    )


# ═══════════════════════════════════════════════════════════════════════════
# A-SMALL: AOPA Airport Sketches (Inverted PNG)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/a-small", response_class=JSONResponse)
def list_a_small_codes(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(100, ge=1, le=500, description="Items per page"),
):
    """List all available AOPA sketch codes with pagination."""
    inverted_dir = _A_SMALL_DIR / "inverted"
    if not inverted_dir.is_dir():
        return JSONResponse(
            content={"codes": [], "count": 0, "page": page, "per_page": per_page},
            status_code=200,
        )

    all_codes = sorted(f.stem for f in inverted_dir.glob("*.png"))
    total = len(all_codes)
    start = (page - 1) * per_page
    end = start + per_page
    page_codes = all_codes[start:end]

    return JSONResponse(
        content={
            "codes": page_codes,
            "count": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        },
        status_code=200,
    )


@router.get("/a-small/{code}")
def get_a_small_sketch(code: str, original: bool = Query(False, description="Return original GIF instead of inverted PNG")):
    """Get an airport sketch by identifier.

    By default returns the inverted (dark-mode friendly) PNG.
    Pass ``?original=true`` for the original GIF.

    Example: ``GET /api/v1/a-small/KLAX``
    """
    if original:
        file_path = _A_SMALL_DIR / "original" / f"{code.upper()}.gif"
        media_type = "image/gif"
        filename = f"{code.upper()}_sketch.gif"
    else:
        file_path = _A_SMALL_DIR / "inverted" / f"{code.upper()}.png"
        media_type = "image/png"
        filename = f"{code.upper()}_sketch.png"

    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sketch not found for airport '{code.upper()}'.",
        )
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )
