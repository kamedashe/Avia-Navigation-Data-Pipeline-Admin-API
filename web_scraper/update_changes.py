import json
import os
import time
from pathlib import Path

from .settings import CHANGES_FILE


def get_dir_size(path) -> int:
    """Recursively sum the size (in bytes) of all files inside *path*.

    Works with both ``str`` and ``pathlib.Path`` arguments.
    Returns 0 if the directory does not exist or is empty.
    """
    path = Path(path)
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def update_file_size_only(arg, file_name=CHANGES_FILE, output_file_path=None):
    """Update only the file size in changes.json, preserving the existing timestamp.

    Use this when processing was skipped (file already exists) but the
    dashboard still needs a valid file_size entry.

    Supports both single files and directories — when *output_file_path*
    points to a directory, ``get_dir_size()`` is used instead.

    Args:
        arg: Single-character flag identifier (e.g. 'b').
        file_name: Path to the changes JSON file.
        output_file_path: Path to the output file/directory whose size should be recorded.
    """
    if not output_file_path:
        return

    output_path = Path(output_file_path)
    if not output_path.exists():
        return

    size_key = f"{arg}_size"
    try:
        with open(file_name) as f:
            changes = json.load(f)
    except FileNotFoundError:
        changes = {}

    if output_path.is_dir():
        changes[size_key] = get_dir_size(output_path)
    else:
        changes[size_key] = os.path.getsize(output_file_path)

    with open(file_name, "w") as f:
        json.dump(changes, f, indent=4)

    print(f"Updated {size_key} = {changes[size_key]} bytes (timestamp preserved).")
    return changes


def commit_changes(arg, file_name=CHANGES_FILE, output_file_path=None):
    """Update changes.json with a timestamp and optional file size for the given flag.

    Supports both single files and directories — when *output_file_path*
    points to a directory, ``get_dir_size()`` is used instead.

    Args:
        arg: Flag identifier (e.g. 'b', 'c', 'd', 'a_big', 'm_sectional').
        file_name: Path to the changes JSON file.
        output_file_path: Optional path to the generated output file/directory.
            When provided and it exists, its size in bytes is
            stored under the key ``{arg}_size``.
    """
    allowed_base = list("bcdefgnrt") + [
        "a_big", "a_small", "m_sectional",
        "a_big_archive", "a_small_archive",
    ]
    allowed_keys = set(allowed_base) | {f"{k}_size" for k in allowed_base}
    try:
        with open(file_name) as f:
            changes = json.load(f)
        # Filter existing changes to only allowed keys (timestamps + sizes)
        changes = {k: v for k, v in changes.items() if k in allowed_keys}

    except FileNotFoundError:
        changes = {k: 0 for k in allowed_base}
    finally:
        if arg in allowed_base:
            changes[arg] = int(time.time())

            # Record file/directory size when the output path is available
            if output_file_path:
                output_path = Path(output_file_path)
                if output_path.is_dir():
                    changes[f"{arg}_size"] = get_dir_size(output_path)
                elif output_path.is_file():
                    changes[f"{arg}_size"] = os.path.getsize(output_file_path)

        with open(file_name, "w") as f:
            json.dump(changes, f, indent=4)
        return changes
