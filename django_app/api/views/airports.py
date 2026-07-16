"""Database-backed airport endpoints (Postgres via the ORM).

These are additive: the legacy file-download routes (``/api/b/`` etc.) are
untouched, since mobile clients depend on them.

- ``GET /api/v1/airports``              — paginated list, filterable
- ``GET /api/v1/airports/{identifier}`` — single airport with its runways
"""

from django.http import JsonResponse

from api.models import Airport

MAX_PER_PAGE = 500
DEFAULT_PER_PAGE = 100


def _runway_dict(rwy) -> dict:
    return {
        "slot": rwy.slot,
        "rwy_id": rwy.rwy_id,
        "tpa": rwy.tpa,
        "rgt_tfc": rwy.rgt_tfc or None,
        "length_ft": rwy.length_ft,
        "width_ft": rwy.width_ft,
    }


def _airport_dict(apt: Airport, *, runways: bool = False) -> dict:
    data = {
        "identifier": apt.identifier,
        "city": apt.city,
        "state": apt.state or None,
        "country": apt.country,
        "lat": apt.lat,
        "lon": apt.lon,
        "elevation": apt.elevation,
        "ownership_type_code": apt.ownership_type_code or None,
        "fuel_types": apt.fuel_types or None,
        "ctaf": apt.ctaf or None,
        "unicom": apt.unicom or None,
        "wx": apt.wx or None,
        "phone_no": apt.phone_no or None,
        "ground": apt.ground or None,
        "tower": apt.tower or None,
        "tower2": apt.tower2 or None,
        "clearance_delivery": apt.clearance_delivery or None,
    }
    if runways:
        data["runways"] = [_runway_dict(r) for r in apt.runways.all()]
    return data


def list_airports(request):
    """List airports with pagination and optional filters.

    Query params:
      ``page``, ``per_page`` — pagination (per_page capped at 500)
      ``state``, ``country`` — exact match (case-insensitive)
      ``city``               — case-insensitive contains
      ``q``                  — identifier starts-with (case-insensitive)
    """
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.GET.get("per_page", DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE
    per_page = min(max(per_page, 1), MAX_PER_PAGE)

    qs = Airport.objects.all()
    state = request.GET.get("state")
    if state:
        qs = qs.filter(state__iexact=state)
    country = request.GET.get("country")
    if country:
        qs = qs.filter(country__iexact=country)
    city = request.GET.get("city")
    if city:
        qs = qs.filter(city__icontains=city)
    q = request.GET.get("q")
    if q:
        qs = qs.filter(identifier__istartswith=q)

    total = qs.count()
    start = (page - 1) * per_page
    rows = qs[start:start + per_page]

    return JsonResponse(
        {
            "airports": [_airport_dict(a) for a in rows],
            "count": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }
    )


def get_airport(request, identifier: str):
    """Return one airport (with its runways) by FAA identifier."""
    ident = identifier.upper()
    try:
        apt = Airport.objects.prefetch_related("runways").get(identifier=ident)
    except Airport.DoesNotExist:
        return JsonResponse(
            {"detail": f"Airport '{ident}' not found."}, status=404
        )
    return JsonResponse(_airport_dict(apt, runways=True))
