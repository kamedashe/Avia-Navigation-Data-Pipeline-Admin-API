"""Maps views.

Serves offline map tiles and metadata:

- ``GET /api/v1/maps/{filename}``      — Download an .mbtiles tile file
- ``GET /api/v1/maps``                 — List available .mbtiles files
- ``GET /api/v1/maps/info/{filename}`` — Get a JSON metadata file
- ``GET /api/v1/maps/info``            — List available JSON info files
"""

import logging
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, JsonResponse

logger = logging.getLogger(__name__)

_MBTILES_DIR = settings.DATA_DIR / "maps" / "out_mbtiles"
_MAPS_JSON_DIR = settings.DATA_DIR / "maps"


class _BadFilename(Exception):
    """Raised when a supplied filename fails sanitization."""


def _safe_filename(filename: str) -> str:
    """Sanitize a filename to prevent path-traversal attacks."""
    clean = Path(filename).name
    if not clean or clean != filename:
        raise _BadFilename()
    return clean


# ---------------------------------------------------------------------------
# .mbtiles endpoints
# ---------------------------------------------------------------------------
def list_mbtiles(request):
    """List all available .mbtiles files."""
    if not _MBTILES_DIR.is_dir():
        return JsonResponse({"files": [], "count": 0})

    files = sorted(f.name for f in _MBTILES_DIR.glob("*.mbtiles"))
    return JsonResponse({"files": files, "count": len(files)})


def list_map_info_files(request):
    """List all available JSON metadata files in data/maps/."""
    if not _MAPS_JSON_DIR.is_dir():
        return JsonResponse({"files": [], "count": 0})

    files = sorted(f.name for f in _MAPS_JSON_DIR.glob("*.json"))
    return JsonResponse({"files": files, "count": len(files)})


def get_map_info(request, filename: str):
    """Get a JSON metadata file from data/maps/."""
    try:
        clean_name = _safe_filename(filename)
    except _BadFilename:
        return JsonResponse({"detail": "Invalid filename."}, status=400)

    if not clean_name.endswith(".json"):
        return JsonResponse(
            {"detail": "Only .json files are served from this endpoint."},
            status=400,
        )

    file_path = _MAPS_JSON_DIR / clean_name
    if not file_path.is_file():
        return JsonResponse(
            {"detail": f"Info file '{clean_name}' not found."}, status=404
        )

    logger.info("Serving map info file: %s", clean_name)
    return FileResponse(
        open(file_path, "rb"),
        as_attachment=True,
        filename=clean_name,
        content_type="application/json",
    )


def get_mbtiles(request, filename: str):
    """Download an .mbtiles tile file from data/maps/out_mbtiles/."""
    try:
        clean_name = _safe_filename(filename)
    except _BadFilename:
        return JsonResponse({"detail": "Invalid filename."}, status=400)

    if not clean_name.endswith(".mbtiles"):
        return JsonResponse(
            {"detail": "Only .mbtiles files are served from this endpoint."},
            status=400,
        )

    file_path = _MBTILES_DIR / clean_name
    if not file_path.is_file():
        return JsonResponse(
            {"detail": f"Tile file '{clean_name}' not found."}, status=404
        )

    logger.info("Serving mbtiles file: %s", clean_name)
    return FileResponse(
        open(file_path, "rb"),
        as_attachment=True,
        filename=clean_name,
        content_type="application/octet-stream",
    )
