"""Directory-size & mtime helpers used by the changes and admin views.

Ported from the FastAPI app. The legacy CSV-conversion helpers
(``csv_to_json``, ``get_latest_dir`` …) were unused by any endpoint and are
intentionally dropped.
"""

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


def _dirs():
    data = settings.DATA_DIR
    downloaded = settings.DOWNLOADED_DIR
    return {
        "a_big_dir": data / "a_big",
        "a_small_dir": data / "a_small",
        "mbtiles_dir": data / "maps" / "out_mbtiles",
        "a_big_archive": downloaded / "a-big.tar.gz",
        "a_small_archive": downloaded / "a-small.tar.gz",
    }


def get_dir_size(path: Path) -> int:
    """Recursively sum the size (in bytes) of all files inside *path*.

    Returns 0 if the directory does not exist or is empty.
    """
    path = Path(path).resolve()
    if not path.is_dir():
        logger.debug("get_dir_size: path does not exist: %s", path)
        return 0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    logger.debug("get_dir_size(%s) = %d bytes", path, total)
    return total


def _get_file_size(path: Path) -> int:
    """Return file size in bytes, or 0 if the file does not exist."""
    path = Path(path).resolve()
    if path.is_file():
        return path.stat().st_size
    return 0


def _get_file_mtime(path: Path) -> int:
    """Return file mtime as Unix timestamp, or 0 if the file does not exist."""
    path = Path(path).resolve()
    if path.is_file():
        return int(path.stat().st_mtime)
    return 0


def get_latest_mtime(directory: Path, glob_pattern: str = "*") -> int:
    """Return the Unix mtime of the most recently modified file matching
    *glob_pattern* inside *directory*.

    Falls back to the directory's own mtime, then to ``0``.
    """
    directory = Path(directory).resolve()
    if not directory.is_dir():
        return 0

    files = [f for f in directory.glob(glob_pattern) if f.is_file()]
    if files:
        return int(max(f.stat().st_mtime for f in files))

    # No matching files — use the directory mtime itself
    return int(directory.stat().st_mtime)


def enrich_changes_data(data: dict) -> dict:
    """Add dynamically computed sizes and mtime for a_big, a_small, and
    m_sectional to an existing changes dict.

    For ``a_big`` and ``a_small`` the size is taken from the ``.tar.gz``
    archives in ``downloaded_data/`` (synced from Server B via rsync). The
    timestamp is also derived from the archive mtime so the dashboard reflects
    the last successful sync.

    Called by both ``/api/changes/`` and ``/api/status`` so the response is
    always consistent regardless of the endpoint used.
    """
    d = _dirs()

    # a_big / a_small — measured by .tar.gz archive weight
    data["a_big_size"] = _get_file_size(d["a_big_archive"])
    data["a_small_size"] = _get_file_size(d["a_small_archive"])

    # Overwrite timestamps with archive mtime (last sync from Server B)
    a_big_mtime = _get_file_mtime(d["a_big_archive"])
    a_small_mtime = _get_file_mtime(d["a_small_archive"])

    if a_big_mtime:
        data["a_big"] = a_big_mtime
    if a_small_mtime:
        data["a_small"] = a_small_mtime

    # m_sectional — directory-based (shows progress as files arrive)
    data["m_sectional_size"] = get_dir_size(d["mbtiles_dir"])
    data["m_sectional"] = get_latest_mtime(d["mbtiles_dir"], "*.mbtiles")

    logger.info(
        "enrich_changes_data: a_big_size=%d  a_small_size=%d  m_sectional_size=%d  m_sectional=%d",
        data["a_big_size"], data["a_small_size"],
        data["m_sectional_size"], data["m_sectional"],
    )

    # Add safety status (ERROR_SIZE detection)
    from api.services.safety_check import get_oversized_flags

    oversized = get_oversized_flags()
    for flag in oversized:
        data[f"{flag}_error"] = True

    return data
