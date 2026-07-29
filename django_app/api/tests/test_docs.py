"""The /api/docs/ reference page.

This page is what a prospective user is pointed at, so the checks here are
about it staying truthful and reachable rather than about markup details.
"""

from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase

from api.models import Airport


class DocsPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for i, ident in enumerate(["LAX", "JFK", "0J0"]):
            Airport.objects.create(
                identifier=ident, city="X", state="CA", country="US",
                lat=33.0 + i, lon=-118.0 - i, elevation=1.0,
            )

    def test_page_renders(self):
        resp = self.client.get("/api/docs/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp["Content-Type"])

    def test_counts_come_from_the_database(self):
        body = self.client.get("/api/docs/").content.decode()
        self.assertIn("3", body)  # three airports loaded above
        self.assertIn("airports in the database", body)

    def test_documents_the_endpoints_it_claims_to(self):
        body = self.client.get("/api/docs/").content.decode()
        for path in [
            "/api/v1/airports",
            "/api/v1/airports/near",
            "/api/changes/",
            "/api/v1/maps",
        ]:
            with self.subTest(path=path):
                self.assertIn(path, body)

    def test_warns_that_identifiers_are_faa_not_icao(self):
        """The single most likely thing to trip up a first-time user."""
        body = self.client.get("/api/docs/").content.decode()
        self.assertIn("KLAX", body)
        self.assertIn("ICAO", body)

    def test_example_links_actually_resolve(self):
        """Every linked example must return a real response, not a 404."""
        for url in [
            "/api/v1/airports?city=chicago&per_page=5",
            "/api/v1/airports/LAX",
            "/api/v1/airports/near?lat=40.7128&lon=-74.0060&radius_km=30",
            "/api/changes/",
            "/api/v1/maps",
            "/api/v1/a-big",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_survives_the_database_being_down(self):
        """A docs page that 500s is worse than one showing placeholders."""
        with patch(
            "api.views.docs.Airport.objects.count", side_effect=DatabaseError("down")
        ):
            resp = self.client.get("/api/docs/")
        self.assertEqual(resp.status_code, 200)

    def test_rejects_non_get(self):
        self.assertEqual(self.client.post("/api/docs/").status_code, 405)
