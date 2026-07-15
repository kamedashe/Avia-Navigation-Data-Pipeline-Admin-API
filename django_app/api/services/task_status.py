"""Shared task status registry.

Centralizes the in-memory task status dict so that both the admin dashboard
(reads/writes) and download views (writes on safety block) can reference it.

NOTE: this state is per-process. Under a multi-worker gunicorn deployment each
worker keeps its own copy — same behaviour as the original FastAPI app. The
real-time ERROR_SIZE override in :func:`get_calculated_statuses` reads the disk
directly, so size alerts are consistent across workers regardless.
"""

# All scraper flags that are tracked
ALLOWED_FLAGS: list[str] = list("bcdefgnrt") + ["a_big", "a_small", "m_sectional"]


def _status_key(flag: str) -> str:
    """Return the task_statuses dict key for a given flag.

    Single-char flags -> ``'-b'``; multi-char flags -> ``'a_big'``.
    """
    return f"-{flag}" if len(flag) == 1 else flag


# Global task status tracker — values: 'idle' | 'running' | 'ERROR_SIZE'
task_statuses: dict[str, str] = {
    _status_key(flag): "idle" for flag in ALLOWED_FLAGS
}


def get_calculated_statuses() -> dict[str, str]:
    """Return a copy of task statuses merged with real-time disk-size checks.

    If a file on disk exceeds the safety limit (x5), its status is strictly
    overridden as 'ERROR_SIZE'. This ensures the alert persists even if a
    background worker resets the volatile in-memory state to 'idle'.
    """
    from api.services.safety_check import get_oversized_flags

    # 1. Get base statuses (volatile in-memory state)
    result = task_statuses.copy()

    # 2. Get real-time overrides from disk
    oversized = get_oversized_flags()

    # 3. Apply overrides
    for flag in oversized:
        key = _status_key(flag)
        result[key] = "ERROR_SIZE"

    return result
