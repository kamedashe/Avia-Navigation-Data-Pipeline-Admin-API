"""Human-readable API reference at ``/api/docs/``.

The project deliberately runs on plain Django views rather than DRF, so there
is no browsable API or auto-generated schema to hang Swagger off. This is a
hand-maintained page instead: every endpoint listed with live example links,
aimed at someone evaluating the API rather than integrating against it.

Counts are read from the database at request time so the page reflects what is
actually loaded, not a number baked into the markup.
"""

import logging

from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from api.models import Airport, Runway

logger = logging.getLogger(__name__)


def _dataset_summary():
    """Live counts plus a one-line coverage description.

    Degrades to placeholders if the database is unreachable — a docs page that
    500s is worse than one showing a dash.
    """
    try:
        airports = Airport.objects.count()
        runways = Runway.objects.count()
        countries = (
            Airport.objects.values_list("country", flat=True).distinct().count()
        )
        us = Airport.objects.filter(country="US").count()
    except DatabaseError as exc:
        logger.warning("docs page: database unavailable (%s)", exc)
        return {
            "airport_count": "—",
            "runway_count": "—",
            "dataset_scope": "—",
            "coverage_note": "Coverage figures are unavailable right now.",
        }

    if airports:
        pct = round(us * 100 / airports)
        coverage = (
            f"{us:,} of {airports:,} airports are in the United States "
            f"({pct}%), the rest spread over {max(countries - 1, 0)} other territories."
        )
    else:
        coverage = "No airports are loaded on this instance yet."

    return {
        "airport_count": f"{airports:,}",
        "runway_count": f"{runways:,}",
        "dataset_scope": "US / FAA",
        "coverage_note": coverage,
    }


@require_http_methods(["GET"])
def api_docs(request):
    """Render the API reference page."""
    return render(request, "api/docs.html", _dataset_summary())
