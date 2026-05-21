"""Maps Router.

Serves offline map tiles and metadata:

- ``GET /api/v1/maps/{filename}``           — Download an .mbtiles tile file
- ``GET /api/v1/maps``                       — List available .mbtiles files
- ``GET /api/v1/maps/info/{filename}``       — Get a JSON metadata file
- ``GET /api/v1/maps/info``                  — List available JSON info files
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/maps", tags=["Maps"])

# Base directories — resolved relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MBTILES_DIR = _PROJECT_ROOT / "data" / "maps" / "out_mbtiles"
_MAPS_JSON_DIR = _PROJECT_ROOT / "data" / "maps"


def _safe_filename(filename: str) -> str:
    """Sanitize filename to prevent path-traversal attacks.

    Strips any directory components and returns the bare filename.
    Raises HTTP 400 if the result is empty or suspicious.
    """
    clean = Path(filename).name
    if not clean or clean != filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )
    return clean


# ═══════════════════════════════════════════════════════════════════════════
# .mbtiles endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.get("", response_class=JSONResponse)
def list_mbtiles():
    """List all available .mbtiles files."""
    if not _MBTILES_DIR.is_dir():
        return JSONResponse(
            content={"files": [], "count": 0},
            status_code=200,
        )

    files = sorted(f.name for f in _MBTILES_DIR.glob("*.mbtiles"))
    return JSONResponse(
        content={"files": files, "count": len(files)},
        status_code=200,
    )


@router.get("/info", response_class=JSONResponse)
def list_map_info_files():
    """List all available JSON metadata files in data/maps/."""
    if not _MAPS_JSON_DIR.is_dir():
        return JSONResponse(
            content={"files": [], "count": 0},
            status_code=200,
        )

    files = sorted(f.name for f in _MAPS_JSON_DIR.glob("*.json"))
    return JSONResponse(
        content={"files": files, "count": len(files)},
        status_code=200,
    )


@router.get("/info/{filename}")
def get_map_info(filename: str):
    """Get a JSON metadata file from data/maps/.

    Example: ``GET /api/v1/maps/info/cycle_info.json``
    """
    clean_name = _safe_filename(filename)

    if not clean_name.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .json files are served from this endpoint.",
        )

    file_path = _MAPS_JSON_DIR / clean_name
    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Info file '{clean_name}' not found.",
        )

    logger.info("Serving map info file: %s", clean_name)
    return FileResponse(
        path=str(file_path),
        filename=clean_name,
        media_type="application/json",
    )


@router.get("/{filename}")
def get_mbtiles(filename: str):
    """Download an .mbtiles tile file from data/maps/out_mbtiles/.

    Example: ``GET /api/v1/maps/world.mbtiles``
    """
    clean_name = _safe_filename(filename)

    if not clean_name.endswith(".mbtiles"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .mbtiles files are served from this endpoint.",
        )

    file_path = _MBTILES_DIR / clean_name
    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tile file '{clean_name}' not found.",
        )

    logger.info("Serving mbtiles file: %s", clean_name)
    return FileResponse(
        path=str(file_path),
        filename=clean_name,
        media_type="application/octet-stream",
    )
