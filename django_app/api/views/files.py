"""Single-file download views (flags b, c, d, e, f, g, n, r, t).

Each serves one gzip-compressed CSV from ``data/`` after a size safety check,
mirroring the original per-flag FastAPI routers.
"""

from django.conf import settings
from django.http import FileResponse, JsonResponse

from api.services.safety_check import check_file_safe
from api.services.task_status import task_statuses

# flag -> (filename on disk / download name)
_FILES = {
    "b": "b.csv.gz",
    "c": "c.csv.gz",
    "d": "d.csv.gz",
    "e": "e.csv.gz",
    "f": "f.csv.gz",
    "g": "g.csv.gz",
    "n": "n.csv.gz",
    "r": "r.csv.gz",
    "t": "tfr.csv.gz",
}


def _serve_flag_file(flag: str) -> "JsonResponse | FileResponse":
    filename = _FILES[flag]
    file_path = settings.DATA_DIR / filename

    if file_path.is_file():
        blocked = check_file_safe(flag, file_path, task_statuses=task_statuses)
        if blocked:
            return blocked
        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=filename,
            content_type="application/gzip",
        )

    return JsonResponse({"detail": "File not found"}, status=404)


# Explicit per-flag views keep the URLconf readable and 1:1 with the API.
def get_b_file(request):
    """Get the latest base file."""
    return _serve_flag_file("b")


def get_c_file(request):
    return _serve_flag_file("c")


def get_d_file(request):
    return _serve_flag_file("d")


def get_e_file(request):
    return _serve_flag_file("e")


def get_f_file(request):
    return _serve_flag_file("f")


def get_g_file(request):
    return _serve_flag_file("g")


def get_n_file(request):
    return _serve_flag_file("n")


def get_r_file(request):
    return _serve_flag_file("r")


def get_t_file(request):
    return _serve_flag_file("t")
