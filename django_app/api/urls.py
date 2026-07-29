"""URL routes — 1:1 with the original FastAPI paths.

Route ordering matters: literal segments (``download``, ``info``) are declared
before the parametrized ``<str:...>`` routes that would otherwise capture them,
since Django resolves patterns top-to-bottom.
"""

from django.urls import path

from api.views import (
    admin_dashboard,
    airports,
    changes,
    diagrams,
    docs,
    files,
    geo,
    maps,
    root,
)

urlpatterns = [
    # Root test endpoint
    path("", root.read_root),

    # ── Human-readable API reference ─────────────────────────────────
    path("api/docs/", docs.api_docs),

    # ── Admin dashboard + control API ────────────────────────────────
    path("admin", admin_dashboard.admin_dashboard),
    path("api/status", admin_dashboard.get_status),
    path("api/task-status", admin_dashboard.get_task_status),
    path("api/run/<str:flag>", admin_dashboard.run_scraper),

    # ── Single-file downloads (b, c, d, e, f, g, n, r, t) ────────────
    path("api/b/", files.get_b_file),
    path("api/c/", files.get_c_file),
    path("api/d/", files.get_d_file),
    path("api/e/", files.get_e_file),
    path("api/f/", files.get_f_file),
    path("api/g/", files.get_g_file),
    path("api/n/", files.get_n_file),
    path("api/r/", files.get_r_file),
    path("api/t/", files.get_t_file),

    # ── Changes metadata ─────────────────────────────────────────────
    path("api/changes/", changes.get_changes_file),

    # ── Airport diagrams (a-big / a-small) ───────────────────────────
    path("api/v1/a-big/download", diagrams.download_a_big_archive),
    path("api/v1/a-big", diagrams.list_a_big_states),
    path("api/v1/a-big/<str:state>/<str:code>", diagrams.get_a_big_diagram),
    path("api/v1/a-big/<str:state>", diagrams.list_a_big_codes),
    path("api/v1/a-small/download", diagrams.download_a_small_archive),
    path("api/v1/a-small", diagrams.list_a_small_codes),
    path("api/v1/a-small/<str:code>", diagrams.get_a_small_sketch),

    # ── Airports from Postgres (ORM-backed; additive to /api/b/) ─────
    # "near" must precede <identifier>, or it gets read as an airport code.
    path("api/v1/airports", airports.list_airports),
    path("api/v1/airports/near", geo.airports_near),
    path("api/v1/airports/<str:identifier>", airports.get_airport),

    # ── Offline maps (.mbtiles + JSON metadata) ──────────────────────
    path("api/v1/maps", maps.list_mbtiles),
    path("api/v1/maps/info", maps.list_map_info_files),
    path("api/v1/maps/info/<str:filename>", maps.get_map_info),
    path("api/v1/maps/<str:filename>", maps.get_mbtiles),
]
