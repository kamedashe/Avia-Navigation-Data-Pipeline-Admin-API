from pathlib import Path
import os
import datetime
import csv
import json

from fastapi import HTTPException, status


BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = os.path.join(BASE_DIR, "processed_data")
CHANGES_FILE = os.path.join(BASE_DIR, "data/changes.json")
AIRPORTS_FILE = os.path.join(BASE_DIR, "processed_data/arpts_dict.json")


# FILES TREE STRUCTURE


def get_latest_dir(arg, previous=True):
    list_dir = os.listdir(OUTPUT_DIR)
    # print('list_dir = ', list_dir)
    dir_dates = []
    for dir in list_dir:
        if dir.find("-content") == -1:
            dir_dates.append(datetime.datetime(1, 1, 1))
            continue
        if dir[10] == arg:
            ddl = [s for s in dir if s.isdigit()]
            dir_date = datetime.datetime(
                int(ddl[0] + ddl[1] + ddl[2] + ddl[3]),
                int(ddl[4] + ddl[5]),
                int(ddl[6] + ddl[7]),
            )
            dir_dates.append(dir_date)
        else:
            dir_dates.append(datetime.datetime(1, 1, 1))
    latest_dir = list_dir[dir_dates.index(max(dir_dates))]
    path_to_latest_dir = os.path.join(OUTPUT_DIR, latest_dir)
    while not (os.listdir(path_to_latest_dir)) and len(list_dir) > 1:
        del list_dir[dir_dates.index(max(dir_dates))]
        del dir_dates[dir_dates.index(max(dir_dates))]
        latest_dir = list_dir[dir_dates.index(max(dir_dates))]
        path_to_latest_dir = os.path.join(OUTPUT_DIR, latest_dir)

    return path_to_latest_dir


def get_latest_file(arg):
    latest_dir = get_latest_dir(arg)

    list_files = os.listdir(latest_dir)
    if not (list_files):
        return "This file doesn't exist"
    file_times = []
    for f in list_files:
        ddl = [s for s in f if s.isdigit()]
        f_time = datetime.time(
            int(ddl[0] + ddl[1]),
            int(ddl[2] + ddl[3]),
            int(ddl[4] + ddl[5]),
        )
        file_times.append(f_time)
    latest_file = list_files[file_times.index(max(file_times))]

    return os.path.join(latest_dir, latest_file)


def csv_to_json(csvFilePath, arr=False, limit: int = None):
    """
    Convert CSV file to JSON format.
    
    Args:
        csvFilePath: Path to CSV file
        arr: If True, return list of lists; if False, return list of dicts
        limit: Optional limit on number of rows to return (for memory safety)
    
    Returns:
        List of rows as dicts or lists
    """
    data = []
    with open(csvFilePath, encoding="unicode_escape") as csvf:
        if arr:
            csvReader = csv.reader(csvf)
        else:
            csvReader = csv.DictReader(csvf)
        for i, row in enumerate(csvReader):
            if limit is not None and i >= limit:
                break
            data.append(row)
    return data


def csv_to_json_generator(csvFilePath, arr=False):
    """
    Generator version of csv_to_json for streaming large files.
    Yields rows one at a time to reduce memory usage.
    
    Args:
        csvFilePath: Path to CSV file
        arr: If True, yield lists; if False, yield dicts
    
    Yields:
        Individual rows as dicts or lists
    """
    with open(csvFilePath, encoding="unicode_escape") as csvf:
        if arr:
            csvReader = csv.reader(csvf)
        else:
            csvReader = csv.DictReader(csvf)
        for row in csvReader:
            yield row


def get_file_content(json_file):
    with open(json_file) as f:
        data = json.load(f)
    return data


def get_changes_content():
    try:
        with open(CHANGES_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Changes file not found"
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error decoding JSON",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


def get_list_files_for_arg(arg):
    latest_dir = get_latest_dir(arg)
    list_files = os.listdir(latest_dir)
    return list_files


# ---------------------------------------------------------------------------
# Directory-size & mtime helpers (used by changes_router, admin_router)
# ---------------------------------------------------------------------------
_A_BIG_DIR = BASE_DIR / "data" / "a_big"
_A_SMALL_DIR = BASE_DIR / "data" / "a_small"
_MBTILES_DIR = BASE_DIR / "data" / "maps" / "out_mbtiles"

# Tar archives synced from Server B via rsync
_DOWNLOADED_DIR = BASE_DIR / "downloaded_data"
_A_BIG_ARCHIVE = _DOWNLOADED_DIR / "a-big.tar.gz"
_A_SMALL_ARCHIVE = _DOWNLOADED_DIR / "a-small.tar.gz"

import logging as _logging
_fh_logger = _logging.getLogger(__name__)


def get_dir_size(path: Path) -> int:
    """Recursively sum the size (in bytes) of all files inside *path*.

    Returns 0 if the directory does not exist or is empty.
    Uses absolute path resolution to avoid Docker working-dir issues.
    """
    path = Path(path).resolve()
    if not path.is_dir():
        _fh_logger.debug("get_dir_size: path does not exist: %s", path)
        return 0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    _fh_logger.debug("get_dir_size(%s) = %d bytes", path, total)
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
    """Add dynamically computed sizes and mtime for a_big, a_small,
    and m_sectional to an existing changes dict.

    For ``a_big`` and ``a_small`` the size is taken from the ``.tar.gz``
    archives in ``downloaded_data/`` (synced from Server B via rsync).
    The timestamp is also derived from the archive mtime so the
    dashboard reflects the last successful sync.

    Called by both ``/changes/`` and ``/api/status`` so the
    response is always consistent regardless of the endpoint used.
    """
    # a_big / a_small — measured by .tar.gz archive weight
    data["a_big_size"] = _get_file_size(_A_BIG_ARCHIVE)
    data["a_small_size"] = _get_file_size(_A_SMALL_ARCHIVE)

    # Overwrite timestamps with archive mtime (last sync from Server B)
    a_big_mtime = _get_file_mtime(_A_BIG_ARCHIVE)
    a_small_mtime = _get_file_mtime(_A_SMALL_ARCHIVE)

    if a_big_mtime:
        data["a_big"] = a_big_mtime
    if a_small_mtime:
        data["a_small"] = a_small_mtime

    # m_sectional — directory-based (shows progress as files arrive)
    data["m_sectional_size"] = get_dir_size(_MBTILES_DIR)
    data["m_sectional"] = get_latest_mtime(_MBTILES_DIR, "*.mbtiles")

    _fh_logger.info(
        "enrich_changes_data: a_big_size=%d  a_small_size=%d  m_sectional_size=%d  m_sectional=%d  "
        "[a_big_archive=%s  a_small_archive=%s  mbtiles_dir=%s]",
        data["a_big_size"], data["a_small_size"],
        data["m_sectional_size"], data["m_sectional"],
        _A_BIG_ARCHIVE.resolve(), _A_SMALL_ARCHIVE.resolve(), _MBTILES_DIR.resolve(),
    )

    # 4. Add safety status (ERROR_SIZE detection)
    from app.services.safety_check import get_oversized_flags
    oversized = get_oversized_flags()
    for flag in oversized:
        data[f"{flag}_error"] = True

    return data


if __name__ == "__main__":
    print(f"BASE_DIR: {BASE_DIR}")
    print(f"OUTPUT_DIR: {OUTPUT_DIR}")
    print(f"CHANGES_FILE: {CHANGES_FILE}")
    print(f"AIRPORTS_FILE: {AIRPORTS_FILE}")
