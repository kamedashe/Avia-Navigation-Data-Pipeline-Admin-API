"""Geographic airport lookup.

``GET /api/v1/airports/near`` — airports around a point, nearest first.

There is no PostGIS in this stack, so the search is done in two steps: a cheap
bounding-box filter in SQL to cut 19k rows down to a handful, then an exact
haversine distance in Python over that subset. For the radii this endpoint
allows, the box is small enough that the Python pass is negligible.
"""

import math

from django.db.models import Q
from django.http import JsonResponse

from api.models import Airport
from api.views.airports import _airport_dict

# Mean Earth radius (km) — the usual haversine constant.
EARTH_RADIUS_KM = 6371.0088

# One degree of latitude is ~111.32 km anywhere; longitude shrinks with cos(lat).
KM_PER_DEG_LAT = 111.32

DEFAULT_RADIUS_KM = 50.0
MAX_RADIUS_KM = 500.0
DEFAULT_LIMIT = 20
MAX_LIMIT = 200


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _bounding_box_filter(lat: float, lon: float, radius_km: float) -> Q:
    """A Q object selecting everything within the lat/lon box around a point.

    Deliberately generous — it over-selects, and the exact haversine pass
    afterwards discards the corners. Handles the antimeridian by splitting the
    longitude range in two, and gives up on narrowing longitude near the poles
    where the cosine collapses.
    """
    lat_delta = radius_km / KM_PER_DEG_LAT
    lat_min = max(lat - lat_delta, -90.0)
    lat_max = min(lat + lat_delta, 90.0)

    box = Q(lat__gte=lat_min, lat__lte=lat_max)

    # Near the poles a small distance spans nearly every longitude; skip the
    # longitude narrowing entirely rather than dividing by ~0.
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 0.01:
        return box

    lon_delta = radius_km / (KM_PER_DEG_LAT * cos_lat)
    if lon_delta >= 180:
        return box

    lon_min = lon - lon_delta
    lon_max = lon + lon_delta

    if lon_min < -180 or lon_max > 180:
        # The box wraps the antimeridian: match either side of the seam.
        lon_min = (lon_min + 540) % 360 - 180
        lon_max = (lon_max + 540) % 360 - 180
        return box & (Q(lon__gte=lon_min) | Q(lon__lte=lon_max))

    return box & Q(lon__gte=lon_min, lon__lte=lon_max)


def _float_param(request, name):
    """Parse a required float query parameter. Returns (value, error_response)."""
    raw = request.GET.get(name)
    if raw is None or raw.strip() == "":
        return None, JsonResponse(
            {"detail": f"Missing required query parameter '{name}'."}, status=400
        )
    try:
        return float(raw), None
    except ValueError:
        return None, JsonResponse(
            {"detail": f"Query parameter '{name}' must be a number, got '{raw}'."},
            status=400,
        )


def airports_near(request):
    """Airports within a radius of a point, nearest first.

    Query params:
      ``lat``, ``lon``    — required, decimal degrees
      ``radius_km``       — optional, default 50, capped at 500
      ``limit``           — optional, default 20, capped at 200

    Each result carries a ``distance_km`` field.
    """
    lat, err = _float_param(request, "lat")
    if err:
        return err
    lon, err = _float_param(request, "lon")
    if err:
        return err

    if not -90 <= lat <= 90:
        return JsonResponse(
            {"detail": f"'lat' must be between -90 and 90, got {lat}."}, status=400
        )
    if not -180 <= lon <= 180:
        return JsonResponse(
            {"detail": f"'lon' must be between -180 and 180, got {lon}."}, status=400
        )

    try:
        radius_km = float(request.GET.get("radius_km", DEFAULT_RADIUS_KM))
    except ValueError:
        radius_km = DEFAULT_RADIUS_KM
    radius_km = min(max(radius_km, 0.1), MAX_RADIUS_KM)

    try:
        limit = int(request.GET.get("limit", DEFAULT_LIMIT))
    except ValueError:
        limit = DEFAULT_LIMIT
    limit = min(max(limit, 1), MAX_LIMIT)

    candidates = Airport.objects.filter(_bounding_box_filter(lat, lon, radius_km))

    within = []
    for apt in candidates:
        d = _haversine_km(lat, lon, apt.lat, apt.lon)
        if d <= radius_km:
            within.append((d, apt))
    within.sort(key=lambda pair: pair[0])

    results = []
    for d, apt in within[:limit]:
        item = _airport_dict(apt)
        item["distance_km"] = round(d, 2)
        results.append(item)

    return JsonResponse(
        {
            "airports": results,
            "count": len(results),
            "total_within_radius": len(within),
            "query": {
                "lat": lat,
                "lon": lon,
                "radius_km": radius_km,
                "limit": limit,
            },
        }
    )
