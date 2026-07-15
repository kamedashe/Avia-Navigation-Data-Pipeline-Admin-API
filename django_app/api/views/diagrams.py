"""Airport Diagrams views.

Endpoint groups:

- ``/api/v1/a-big/download``        — Download full a-big.tar.gz archive
- ``/api/v1/a-big/{state}/{code}``  — Full FAA airport diagram (WebP)
- ``/api/v1/a-big/{state}``         — List available codes for a state
- ``/api/v1/a-big``                 — List available states

- ``/api/v1/a-small/download``      — Download full a-small.tar.gz archive
- ``/api/v1/a-small/{code}``        — Inverted AOPA sketch (PNG)
- ``/api/v1/a-small``               — List available sketches
"""

from django.conf import settings
from django.http import FileResponse, JsonResponse

from api.services.safety_check import check_file_safe
from api.services.task_status import task_statuses

_A_BIG_DIR = settings.DATA_DIR / "a_big"
_A_SMALL_DIR = settings.DATA_DIR / "a_small"
_DOWNLOADED_DIR = settings.DOWNLOADED_DIR


# ---------------------------------------------------------------------------
# DOWNLOAD: Tar.gz archive endpoints (legacy mobile app compatibility)
# ---------------------------------------------------------------------------
def download_a_big_archive(request):
    """Download the full a-big.tar.gz archive."""
    archive_path = _DOWNLOADED_DIR / "a-big.tar.gz"
    if not archive_path.is_file():
        return JsonResponse(
            {"detail": "a-big.tar.gz archive not found. Run sync from Server B first."},
            status=404,
        )
    blocked = check_file_safe("a_big", archive_path, task_statuses=task_statuses)
    if blocked:
        return blocked
    return FileResponse(
        open(archive_path, "rb"),
        as_attachment=True,
        filename="a-big.tar.gz",
        content_type="application/gzip",
    )


def download_a_small_archive(request):
    """Download the full a-small.tar.gz archive."""
    archive_path = _DOWNLOADED_DIR / "a-small.tar.gz"
    if not archive_path.is_file():
        return JsonResponse(
            {"detail": "a-small.tar.gz archive not found. Run sync from Server B first."},
            status=404,
        )
    blocked = check_file_safe("a_small", archive_path, task_statuses=task_statuses)
    if blocked:
        return blocked
    return FileResponse(
        open(archive_path, "rb"),
        as_attachment=True,
        filename="a-small.tar.gz",
        content_type="application/gzip",
    )


# ---------------------------------------------------------------------------
# A-BIG: FAA Airport Diagrams (WebP, organized by state)
# ---------------------------------------------------------------------------
def list_a_big_states(request):
    """List all available states that have airport diagrams."""
    if not _A_BIG_DIR.is_dir():
        return JsonResponse({"states": []})

    states = sorted(
        entry.name
        for entry in _A_BIG_DIR.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )
    return JsonResponse({"states": states, "count": len(states)})


def list_a_big_codes(request, state: str):
    """List all available airport diagram codes within a given state."""
    state_dir = _A_BIG_DIR / state.upper()
    if not state_dir.is_dir():
        return JsonResponse(
            {"detail": f"No diagrams found for state '{state}'."}, status=404
        )

    codes = sorted(f.stem for f in state_dir.glob("*.webp"))
    return JsonResponse({"state": state.upper(), "codes": codes, "count": len(codes)})


def get_a_big_diagram(request, state: str, code: str):
    """Get a specific airport diagram (WebP) by state and FAA code."""
    webp_path = _A_BIG_DIR / state.upper() / f"{code.upper()}.webp"
    if not webp_path.is_file():
        return JsonResponse(
            {"detail": f"Airport diagram not found for {code.upper()} in {state.upper()}."},
            status=404,
        )
    return FileResponse(
        open(webp_path, "rb"),
        as_attachment=True,
        filename=f"{code.upper()}_Airport_Diagram.webp",
        content_type="image/webp",
    )


# ---------------------------------------------------------------------------
# A-SMALL: AOPA Airport Sketches (Inverted PNG)
# ---------------------------------------------------------------------------
def list_a_small_codes(request):
    """List all available AOPA sketch codes with pagination."""
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.GET.get("per_page", 100))
    except (TypeError, ValueError):
        per_page = 100
    per_page = min(max(per_page, 1), 500)

    inverted_dir = _A_SMALL_DIR / "inverted"
    if not inverted_dir.is_dir():
        return JsonResponse(
            {"codes": [], "count": 0, "page": page, "per_page": per_page}
        )

    all_codes = sorted(f.stem for f in inverted_dir.glob("*.png"))
    total = len(all_codes)
    start = (page - 1) * per_page
    end = start + per_page
    page_codes = all_codes[start:end]

    return JsonResponse(
        {
            "codes": page_codes,
            "count": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }
    )


def get_a_small_sketch(request, code: str):
    """Get an airport sketch by identifier.

    By default returns the inverted (dark-mode friendly) PNG. Pass
    ``?original=true`` for the original GIF.
    """
    original = request.GET.get("original", "false").lower() in {"1", "true", "yes", "on"}

    if original:
        file_path = _A_SMALL_DIR / "original" / f"{code.upper()}.gif"
        media_type = "image/gif"
        filename = f"{code.upper()}_sketch.gif"
    else:
        file_path = _A_SMALL_DIR / "inverted" / f"{code.upper()}.png"
        media_type = "image/png"
        filename = f"{code.upper()}_sketch.png"

    if not file_path.is_file():
        return JsonResponse(
            {"detail": f"Sketch not found for airport '{code.upper()}'."}, status=404
        )
    return FileResponse(
        open(file_path, "rb"),
        as_attachment=True,
        filename=filename,
        content_type=media_type,
    )
