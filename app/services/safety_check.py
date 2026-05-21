"""File Size Safety Check (Предохранитель).

Prevents serving anomalously large files to mobile clients.
If a file's actual size exceeds its expected (reference) size by more
than a configurable multiplier (default: 5×), the download is blocked
and the admin dashboard task status is set to ``ERROR_SIZE``.

Reference sizes are taken from production measurements (2026-05-14).
"""

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference file sizes (bytes) — measured on production 2026-05-14
# ---------------------------------------------------------------------------
EXPECTED_FILE_SIZES_BYTES: dict[str, int] = {
    "a_big":       58_867_302,   # 56.14 MB
    "a_small":     34_123_162,   # 32.54 MB
    "m_sectional": 730_101_555,  # 696.27 MB
    "b":              589_926,   # 576.1 KB
    "c":            2_034_237,   # 1.94 MB
    "d":            1_698_694,   # 1.62 MB
    "e":              520_806,   # 508.6 KB
    "f":              221_696,   # 216.5 KB
    "g":                5_325,   # 5.2 KB
    "n":               40_038,   # 39.1 KB
    "r":              135_782,   # 132.6 KB
    "t":               17_408,   # 17.0 KB
}

# How many times the actual size may exceed the expected before blocking
SAFETY_MULTIPLIER: int = 5

# Mappings of flag keys to their physical file/directory paths
# Resolved relative to project root
_BASE_DIR = Path(__file__).resolve().parent.parent.parent
TRACKED_PATHS: dict[str, Path] = {
    "a_big":       _BASE_DIR / "downloaded_data" / "a-big.tar.gz",
    "a_small":     _BASE_DIR / "downloaded_data" / "a-small.tar.gz",
    "m_sectional": _BASE_DIR / "data" / "maps" / "out_mbtiles",
    "b":           _BASE_DIR / "data" / "b.csv.gz",
    "c":           _BASE_DIR / "data" / "c.csv.gz",
    "d":           _BASE_DIR / "data" / "d.csv.gz",
    "e":           _BASE_DIR / "data" / "e.csv.gz",
    "f":           _BASE_DIR / "data" / "f.csv.gz",
    "g":           _BASE_DIR / "data" / "g.csv.gz",
    "n":           _BASE_DIR / "data" / "n.csv.gz",
    "r":           _BASE_DIR / "data" / "r.csv.gz",
    "t":           _BASE_DIR / "data" / "tfr.csv.gz",
}


def get_actual_size(path: Path) -> int:
    """Return file size or total directory size in bytes.
    Returns 0 if path does not exist.
    """
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    # Directory size calculation (recursive)
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def get_oversized_flags(multiplier: int = SAFETY_MULTIPLIER) -> list[str]:
    """Check all tracked paths and return a list of flag keys that
    exceed the safety threshold.
    """
    oversized = []
    for key, path in TRACKED_PATHS.items():
        expected = EXPECTED_FILE_SIZES_BYTES.get(key)
        if not expected:
            continue
            
        actual = get_actual_size(path)
        if actual > expected * multiplier:
            oversized.append(key)
            
    return oversized


def validate_file_size(
    file_key: str,
    file_path: str | os.PathLike,
    *,
    multiplier: int = SAFETY_MULTIPLIER,
    task_statuses: Optional[dict[str, str]] = None,
) -> bool:
    """Check whether *file_path* exceeds the safety threshold.

    Args:
        file_key: Logical identifier (e.g. ``'b'``, ``'a_big'``).
                  Must be a key in :data:`EXPECTED_FILE_SIZES_BYTES`.
        file_path: Absolute or relative path to the file on disk.
        multiplier: Maximum allowed ratio ``actual / expected``.
        task_statuses: Reference to the admin ``task_statuses`` dict.
                       When the check fails the matching key is set
                       to ``'ERROR_SIZE'`` so the dashboard shows an alert.

    Returns:
        ``True`` if the file is within acceptable limits (safe to serve).
        ``False`` if the file is anomalously large.

    Raises:
        Nothing — the caller decides how to handle a ``False`` result.
    """
    expected = EXPECTED_FILE_SIZES_BYTES.get(file_key)
    if expected is None:
        # Unknown key — skip the check, don't block untracked files
        logger.warning(
            "safety_check: no reference size for key '%s', skipping.", file_key
        )
        return True

    resolved = Path(file_path).resolve()
    if not resolved.is_file():
        # File doesn't exist yet — nothing to validate
        return True

    actual_size = resolved.stat().st_size
    threshold = expected * multiplier

    if actual_size > threshold:
        logger.critical(
            "🚨 SAFETY BLOCK: file_key='%s' path='%s' "
            "actual=%d bytes (%.2f MB) > threshold=%d bytes (expected=%d × %d). "
            "Download BLOCKED.",
            file_key,
            resolved,
            actual_size,
            actual_size / 1_048_576,
            threshold,
            expected,
            multiplier,
        )

        # Update admin dashboard status to show the alert
        if task_statuses is not None:
            status_key = f"-{file_key}" if len(file_key) == 1 else file_key
            task_statuses[status_key] = "ERROR_SIZE"

        return False

    logger.debug(
        "safety_check OK: key='%s' actual=%d expected=%d threshold=%d",
        file_key,
        actual_size,
        expected,
        threshold,
    )
    return True


def assert_file_safe(
    file_key: str,
    file_path: str | os.PathLike,
    *,
    task_statuses: Optional[dict[str, str]] = None,
) -> None:
    """Convenience wrapper: raises ``HTTPException(500)`` when the file
    exceeds the safety threshold.

    Designed as a one-liner guard before ``FileResponse`` in route handlers.
    """
    if not validate_file_size(
        file_key, file_path, task_statuses=task_statuses
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                f"Safety Block: File size anomaly detected for '{file_key}'. "
                f"The file is more than {SAFETY_MULTIPLIER}× larger than expected. "
                f"Download blocked to protect mobile clients."
            ),
        )
