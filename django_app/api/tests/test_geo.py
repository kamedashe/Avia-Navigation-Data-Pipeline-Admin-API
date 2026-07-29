"""Radius search at /api/v1/airports/near.

Fixtures sit at known offsets from a reference point so the assertions are
about real distances, not whatever the implementation happens to return:
one degree of latitude is ~111.32 km, so 0.09 deg north is ~10 km and
0.45 deg north is ~50 km.
"""

from django.test import TestCase

from api.models import Airport

REF_LAT, REF_LON = 40.0, -74.0


def make_airport(identifier, lat, lon, **over):
    fields = {
        "city": "TESTVILLE",
        "state": "NJ",
        "country": "US",
        "lat": lat,
        "lon": lon,
        "elevation": 10.0,
    }
    fields.update(over)
    return Airport.objects.create(identifier=identifier, **fields)


class RadiusSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_airport("HERE", REF_LAT, REF_LON)                 # 0 km
        make_airport("TEN", REF_LAT + 0.09, REF_LON)           # ~10 km
        make_airport("FIFTY", REF_LAT + 0.45, REF_LON)         # ~50 km
        make_airport("FARAWAY", REF_LAT + 5.0, REF_LON)        # ~557 km

    def _near(self, **params):
        params.setdefault("lat", REF_LAT)
        params.setdefault("lon", REF_LON)
        return self.client.get("/api/v1/airports/near", params)

    def test_returns_only_airports_inside_the_radius(self):
        body = self._near(radius_km=30).json()
        ids = [a["identifier"] for a in body["airports"]]

        self.assertIn("HERE", ids)
        self.assertIn("TEN", ids)
        self.assertNotIn("FIFTY", ids)
        self.assertNotIn("FARAWAY", ids)

    def test_results_are_ordered_nearest_first(self):
        body = self._near(radius_km=100).json()
        ids = [a["identifier"] for a in body["airports"]]
        self.assertEqual(ids[:3], ["HERE", "TEN", "FIFTY"])

    def test_distance_is_reported_and_roughly_correct(self):
        body = self._near(radius_km=100).json()
        by_id = {a["identifier"]: a["distance_km"] for a in body["airports"]}

        self.assertAlmostEqual(by_id["HERE"], 0.0, places=1)
        self.assertAlmostEqual(by_id["TEN"], 10.0, delta=0.5)
        self.assertAlmostEqual(by_id["FIFTY"], 50.0, delta=1.0)

    def test_widening_the_radius_reaches_further(self):
        self.assertNotIn(
            "FARAWAY", [a["identifier"] for a in self._near(radius_km=100).json()["airports"]]
        )
        self.assertIn(
            "FARAWAY", [a["identifier"] for a in self._near(radius_km=600).json()["airports"]]
        )

    def test_limit_truncates_results_but_total_still_reported(self):
        body = self._near(radius_km=600, limit=2).json()
        self.assertEqual(len(body["airports"]), 2)
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["total_within_radius"], 4)

    def test_radius_and_limit_are_capped(self):
        body = self._near(radius_km=99999, limit=99999).json()
        self.assertEqual(body["query"]["radius_km"], 500.0)
        self.assertEqual(body["query"]["limit"], 200)

    def test_empty_result_is_not_an_error(self):
        resp = self.client.get(
            "/api/v1/airports/near", {"lat": -33.9, "lon": 151.2, "radius_km": 5}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["airports"], [])

    def test_garbage_radius_falls_back_to_the_default(self):
        body = self._near(radius_km="abc").json()
        self.assertEqual(body["query"]["radius_km"], 50.0)


class ParameterValidationTests(TestCase):
    def test_missing_coordinates_are_rejected(self):
        for params in ({}, {"lat": 40.0}, {"lon": -74.0}):
            with self.subTest(params=params):
                resp = self.client.get("/api/v1/airports/near", params)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("detail", resp.json())

    def test_non_numeric_coordinates_are_rejected(self):
        resp = self.client.get("/api/v1/airports/near", {"lat": "north", "lon": "-74"})
        self.assertEqual(resp.status_code, 400)

    def test_out_of_range_coordinates_are_rejected(self):
        for lat, lon in ((91, 0), (-91, 0), (0, 181), (0, -181)):
            with self.subTest(lat=lat, lon=lon):
                resp = self.client.get("/api/v1/airports/near", {"lat": lat, "lon": lon})
                self.assertEqual(resp.status_code, 400)


class AntimeridianTests(TestCase):
    """A box spanning +/-180 must not silently return nothing."""

    @classmethod
    def setUpTestData(cls):
        make_airport("WESTSIDE", 51.9, 179.9)
        make_airport("EASTSIDE", 51.9, -179.9)

    def test_search_across_the_seam_finds_both_sides(self):
        body = self.client.get(
            "/api/v1/airports/near", {"lat": 51.9, "lon": 179.99, "radius_km": 40}
        ).json()
        ids = {a["identifier"] for a in body["airports"]}
        self.assertEqual(ids, {"WESTSIDE", "EASTSIDE"})


class RouteOrderingTests(TestCase):
    """'near' must hit the search view, not be read as an airport identifier."""

    def test_near_is_not_captured_by_the_identifier_route(self):
        resp = self.client.get("/api/v1/airports/near", {"lat": 40, "lon": -74})
        self.assertEqual(resp.status_code, 200)
        # The identifier view would answer 404 "Airport 'NEAR' not found".
        self.assertIn("query", resp.json())

    def test_a_real_identifier_still_resolves(self):
        make_airport("0J0", 31.6, -85.2)
        resp = self.client.get("/api/v1/airports/0J0")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["identifier"], "0J0")
