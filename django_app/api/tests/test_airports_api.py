"""The Postgres-backed /api/v1/airports endpoints."""

from django.test import TestCase

from api.models import Airport, Runway


def make_airport(identifier, **over):
    fields = {
        "city": "ABBEVILLE",
        "state": "AL",
        "country": "US",
        "lat": 31.6,
        "lon": -85.2,
        "elevation": 468.3,
        "ownership_type_code": "PU",
        "ctaf": "122.8",
    }
    fields.update(over)
    return Airport.objects.create(identifier=identifier, **fields)


class AirportListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_airport("0J0", city="ABBEVILLE", state="AL")
        make_airport("2A8", city="ADDISON", state="AL")
        make_airport("KLAX", city="LOS ANGELES", state="CA")

    def test_lists_all_with_pagination_envelope(self):
        body = self.client.get("/api/v1/airports").json()

        self.assertEqual(body["count"], 3)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["per_page"], 100)
        self.assertEqual(body["total_pages"], 1)
        self.assertEqual(len(body["airports"]), 3)

    def test_filter_by_state_is_case_insensitive(self):
        self.assertEqual(self.client.get("/api/v1/airports", {"state": "al"}).json()["count"], 2)
        self.assertEqual(self.client.get("/api/v1/airports", {"state": "CA"}).json()["count"], 1)

    def test_filter_by_country(self):
        self.assertEqual(self.client.get("/api/v1/airports", {"country": "us"}).json()["count"], 3)

    def test_filter_by_city_substring(self):
        body = self.client.get("/api/v1/airports", {"city": "angel"}).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["airports"][0]["identifier"], "KLAX")

    def test_q_matches_identifier_prefix(self):
        body = self.client.get("/api/v1/airports", {"q": "0j"}).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["airports"][0]["identifier"], "0J0")

    def test_pagination_splits_results(self):
        page1 = self.client.get("/api/v1/airports", {"per_page": 2, "page": 1}).json()
        page2 = self.client.get("/api/v1/airports", {"per_page": 2, "page": 2}).json()

        self.assertEqual(page1["total_pages"], 2)
        self.assertEqual(len(page1["airports"]), 2)
        self.assertEqual(len(page2["airports"]), 1)
        ids = {a["identifier"] for a in page1["airports"] + page2["airports"]}
        self.assertEqual(ids, {"0J0", "2A8", "KLAX"})

    def test_per_page_is_capped(self):
        self.assertEqual(
            self.client.get("/api/v1/airports", {"per_page": 9999}).json()["per_page"], 500
        )

    def test_garbage_pagination_falls_back_to_defaults(self):
        body = self.client.get("/api/v1/airports", {"page": "abc", "per_page": "xyz"}).json()
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["per_page"], 100)

    def test_list_omits_runways(self):
        body = self.client.get("/api/v1/airports").json()
        self.assertNotIn("runways", body["airports"][0])


class AirportDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        apt = make_airport("0J0", fuel_types="", unicom="122.8")
        Runway.objects.create(
            airport=apt, slot=0, rwy_id="18/36", length_ft=5000, width_ft=75, tpa=800
        )
        Runway.objects.create(
            airport=apt, slot=1, rwy_id="09/27", length_ft=2644, width_ft=112
        )

    def test_returns_airport_with_runways(self):
        body = self.client.get("/api/v1/airports/0J0").json()

        self.assertEqual(body["identifier"], "0J0")
        self.assertEqual(body["city"], "ABBEVILLE")
        self.assertEqual(len(body["runways"]), 2)
        self.assertEqual(body["runways"][0]["rwy_id"], "18/36")
        self.assertEqual(body["runways"][0]["length_ft"], 5000)
        self.assertEqual(body["runways"][1]["slot"], 1)

    def test_identifier_lookup_is_case_insensitive(self):
        self.assertEqual(self.client.get("/api/v1/airports/0j0").status_code, 200)

    def test_blank_fields_serialize_as_null(self):
        body = self.client.get("/api/v1/airports/0J0").json()
        self.assertIsNone(body["fuel_types"])
        self.assertEqual(body["unicom"], "122.8")

    def test_unknown_identifier_returns_404(self):
        resp = self.client.get("/api/v1/airports/ZZZZ")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json()["detail"])


class RunwayCascadeTests(TestCase):
    def test_runways_are_deleted_with_their_airport(self):
        apt = make_airport("DEL")
        Runway.objects.create(airport=apt, slot=0, rwy_id="18/36")

        apt.delete()

        self.assertEqual(Runway.objects.count(), 0)
