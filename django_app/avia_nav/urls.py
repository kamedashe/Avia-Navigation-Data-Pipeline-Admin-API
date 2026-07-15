"""Root URL configuration.

All application routes live in ``api/urls.py`` and are mounted at the site
root so the public paths match the original FastAPI service byte-for-byte
(``/api/b/``, ``/api/v1/a-big/...``, ``/admin``, etc.).
"""

from django.urls import include, path

urlpatterns = [
    path("", include("api.urls")),
]
