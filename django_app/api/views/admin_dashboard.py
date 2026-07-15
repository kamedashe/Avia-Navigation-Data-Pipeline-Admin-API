"""Admin Dashboard views.

Provides:
- GET  /admin           → HTML dashboard with glassmorphism UI (Basic auth)
- GET  /api/status      → JSON contents of changes.json (Bearer auth)
- GET  /api/task-status → per-flag running/idle/ERROR_SIZE status (Bearer auth)
- POST /api/run/{flag}  → trigger scraper flag in background (Bearer auth)
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from api.auth import require_basic, require_bearer
from api.services.file_handlers import enrich_changes_data
from api.services.task_status import (
    ALLOWED_FLAGS,
    _status_key,
    get_calculated_statuses,
    task_statuses,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT: Path = settings.PROJECT_ROOT
CHANGES_FILE = settings.DATA_DIR / "changes.json"
_DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "dashboard.html"

# Flags that use the dedicated diagram/map sync (rsync from Server B)
_DIAGRAM_FLAGS = {"a_big", "a_small", "m_sectional"}

# Human-readable labels for each scraper flag
FLAG_LABELS: dict[str, str] = {
    "b": "Base Airports",
    "c": "Class Airspace",
    "d": "Daily Obstacles",
    "e": "Special Use Airspace",
    "f": "Fixes / Waypoints",
    "g": "Stadiums",
    "n": "NAV Aids",
    "r": "Runway Ends",
    "t": "TFR",
    "a_big": "Airport Diagrams (Big)",
    "a_small": "Airport Sketches (Small)",
    "m_sectional": "VFR Sectional Maps",
}

# Sync status for rsync from Server B
_sync_status: dict[str, str] = {"diagrams": "idle"}

_DEST_DIR = str(settings.DOWNLOADED_DIR)


# ---------------------------------------------------------------------------
# Background process launcher (non-blocking)
# ---------------------------------------------------------------------------
def _monitor_process(proc: subprocess.Popen, flag: str, cmd_str: str) -> None:
    """Wait for a subprocess to finish and reset the task status.

    Runs in a daemon thread so it never blocks a worker. Logs stdout/stderr
    tails on completion for diagnostics.
    """
    key = _status_key(flag)
    try:
        stdout, stderr = proc.communicate()  # blocks THIS thread only
        rc = proc.returncode
        if rc == 0:
            logger.info(
                "Scraper %s finished OK (pid=%d).\nstdout(tail): %s",
                flag, proc.pid, (stdout or "")[-500:],
            )
        else:
            logger.error(
                "Scraper %s failed (pid=%d, rc=%d).\nstderr(tail): %s",
                flag, proc.pid, rc, (stderr or "")[-1000:],
            )
    except Exception as exc:
        logger.exception("Monitor thread for %s crashed: %s", flag, exc)
    finally:
        task_statuses[key] = "idle"
        logger.info("Scraper %s status reset to idle.", flag)


def _launch_scraper(flag: str) -> int:
    """Launch ``python -m web_scraper.script -{flag}`` as a detached process."""
    cmd = [sys.executable, "-u", "-m", "web_scraper.script", f"-{flag}"]
    logger.info("Launching scraper: %s  (cwd=%s)", " ".join(cmd), _PROJECT_ROOT)

    proc = subprocess.Popen(
        cmd,
        cwd=str(_PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    watcher = threading.Thread(
        target=_monitor_process,
        args=(proc, flag, " ".join(cmd)),
        name=f"scraper-{flag}-{proc.pid}",
        daemon=True,
    )
    watcher.start()
    logger.info("Scraper -%s launched (pid=%d), watcher thread started.", flag, proc.pid)
    return proc.pid


def _sync_archives_from_server_b() -> None:
    """Pull a-big.tar.gz and a-small.tar.gz from Server B via rsync.

    Runs inside a daemon thread so the HTTP response returns immediately while
    the transfer (~50-100 MB) completes in the background.
    """
    try:
        logger.info("rsync: starting diagram/map sync from Server B…")

        if shutil.which("rsync") is None:
            logger.error(
                "rsync command not found. Please install rsync on the host or in the container."
            )
            return

        # 1. Sync archives (a_big, a_small)
        rsync_source = getattr(
            settings, "RSYNC_SOURCE", os.getenv("RSYNC_SOURCE", "mb@127.0.0.1:/home/mb/faa_vfr")
        )
        for archive in ["a-big.tar.gz", "a-small.tar.gz"]:
            cmd = [
                "rsync", "-avz", "--timeout=120", "-e", "ssh -p 464 -o StrictHostKeyChecking=no",
                f"{rsync_source}/{archive}",
                _DEST_DIR,
            ]
            logger.info("rsync archive cmd: %s", " ".join(cmd))
            subprocess.run(cmd, capture_output=True, text=True)

        # 2. Sync sectional maps directory (more efficient for 56+ files)
        maps_dest = str(_PROJECT_ROOT / "data" / "maps" / "out_mbtiles")
        os.makedirs(maps_dest, exist_ok=True)
        cmd_maps = [
            "rsync", "-avz", "--delete", "--timeout=120", "-e", "ssh -p 464 -o StrictHostKeyChecking=no",
            f"{rsync_source}/out_mbtiles/",
            maps_dest,
        ]
        logger.info("rsync maps cmd: %s", " ".join(cmd_maps))
        subprocess.run(cmd_maps, capture_output=True, text=True)

        logger.info("rsync: sync finished.")
    except Exception as exc:
        logger.exception("rsync sync failed: %s", exc)
    finally:
        _sync_status["diagrams"] = "idle"
        # Reset Update button statuses so they unlock in the dashboard
        for flag in ["a_big", "a_small", "m_sectional"]:
            task_statuses[flag] = "idle"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@require_bearer
@require_http_methods(["GET"])
def get_status(request):
    """Return the current contents of ``changes.json``."""
    if not CHANGES_FILE.is_file():
        return JsonResponse({})
    try:
        with open(CHANGES_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        enrich_changes_data(data)
        return JsonResponse(data)
    except (json.JSONDecodeError, OSError) as exc:
        return JsonResponse(
            {"detail": f"Failed to read changes.json: {exc}"}, status=500
        )


@require_bearer
@require_http_methods(["GET"])
def get_task_status(request):
    """Return the current running/idle status for every scraper flag.

    Includes real-time disk-size validation (ERROR_SIZE) that overrides the
    volatile in-memory state.
    """
    return JsonResponse(get_calculated_statuses())


@require_bearer
@require_POST
def run_scraper(request, flag: str):
    """Launch a scraper for the given flag as a detached background process.

    For ``a_big``, ``a_small`` and ``m_sectional``, triggers rsync from Server
    B instead of running a scraper locally.
    """
    flag = flag.lower().strip()
    if flag not in ALLOWED_FLAGS:
        return JsonResponse(
            {"detail": f"Invalid flag '{flag}'. Allowed: {ALLOWED_FLAGS}"},
            status=400,
        )
    key = _status_key(flag)
    if task_statuses.get(key) == "running":
        return JsonResponse(
            {"detail": f"Task {flag} is already running."}, status=409
        )

    # a_big / a_small / m_sectional → rsync archives from Server B
    if flag in _DIAGRAM_FLAGS:
        if _sync_status["diagrams"] == "running":
            return JsonResponse(
                {"detail": "Diagram sync is already running."}, status=409
            )
        task_statuses[key] = "running"
        _sync_status["diagrams"] = "running"
        threading.Thread(
            target=_sync_archives_from_server_b,
            name="rsync-diagrams",
            daemon=True,
        ).start()
        return JsonResponse(
            {
                "status": "ok",
                "message": f"Syncing diagram archives from Server B (triggered by {flag}).",
            }
        )

    # All other flags → local scraper subprocess
    task_statuses[key] = "running"
    pid = _launch_scraper(flag)
    return JsonResponse(
        {"status": "ok", "message": f"Task {flag} started in background", "pid": pid}
    )


# ---------------------------------------------------------------------------
# Admin HTML dashboard
# ---------------------------------------------------------------------------
@require_basic
@require_http_methods(["GET"])
def admin_dashboard(request):
    """Serve the admin dashboard as a single-page HTML response."""
    auth_token = settings.ADMIN_AUTH_TOKEN or ""
    with open(_DASHBOARD_HTML, "r", encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace("AUTH_TOKEN_PLACEHOLDER", auth_token)
    return HttpResponse(html)
