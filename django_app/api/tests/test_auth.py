"""Admin authentication.

The FastAPI original sent a Bearer token but never verified it server-side.
These tests pin the enforcement down so that regression cannot come back
unnoticed, and cover the deliberate "no token configured -> auth disabled"
escape hatch.
"""

import base64
from unittest.mock import patch

from django.test import TestCase, override_settings

from api.services.task_status import task_statuses

TOKEN = "s3cret-token"
BEARER = f"Bearer {TOKEN}"
BASIC = "Basic " + base64.b64encode(f"admin:{TOKEN}".encode()).decode()

ADMIN_API_ROUTES = ["/api/status", "/api/task-status"]


@override_settings(ADMIN_AUTH_TOKEN=TOKEN)
class AuthEnforcedTests(TestCase):
    def test_admin_api_rejects_missing_token(self):
        for url in ADMIN_API_ROUTES:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 401)

    def test_admin_api_rejects_wrong_token(self):
        for url in ADMIN_API_ROUTES:
            with self.subTest(url=url):
                resp = self.client.get(url, HTTP_AUTHORIZATION="Bearer nope")
                self.assertEqual(resp.status_code, 401)

    def test_admin_api_accepts_bearer_token(self):
        for url in ADMIN_API_ROUTES:
            with self.subTest(url=url):
                resp = self.client.get(url, HTTP_AUTHORIZATION=BEARER)
                self.assertEqual(resp.status_code, 200)

    def test_basic_credentials_are_not_accepted_on_the_json_api(self):
        resp = self.client.get("/api/status", HTTP_AUTHORIZATION=BASIC)
        self.assertEqual(resp.status_code, 401)

    def test_dashboard_challenges_browser_with_basic(self):
        resp = self.client.get("/admin")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Basic", resp["WWW-Authenticate"])

    def test_dashboard_accepts_basic_and_injects_token(self):
        resp = self.client.get("/admin", HTTP_AUTHORIZATION=BASIC)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("<!DOCTYPE html>", body)
        # The dashboard JS needs the real token to call the Bearer endpoints.
        self.assertIn(TOKEN, body)
        self.assertNotIn("AUTH_TOKEN_PLACEHOLDER", body)

    def test_dashboard_rejects_wrong_basic_password(self):
        wrong = "Basic " + base64.b64encode(b"admin:wrong").decode()
        resp = self.client.get("/admin", HTTP_AUTHORIZATION=wrong)
        self.assertEqual(resp.status_code, 401)

    def test_public_file_routes_stay_open(self):
        """Auth must never leak onto the endpoints mobile clients call."""
        for url in ["/", "/api/v1/maps", "/api/v1/a-big", "/api/v1/airports"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


@override_settings(ADMIN_AUTH_TOKEN=TOKEN)
class RunScraperTests(TestCase):
    """/api/run/<flag> — never let a test actually spawn a scraper."""

    def tearDown(self):
        for key in list(task_statuses):
            task_statuses[key] = "idle"

    def test_requires_token(self):
        resp = self.client.post("/api/run/b")
        self.assertEqual(resp.status_code, 401)

    def test_rejects_get(self):
        resp = self.client.get("/api/run/b", HTTP_AUTHORIZATION=BEARER)
        self.assertEqual(resp.status_code, 405)

    def test_rejects_unknown_flag(self):
        resp = self.client.post("/api/run/zzz", HTTP_AUTHORIZATION=BEARER)
        self.assertEqual(resp.status_code, 400)

    def test_conflicts_when_already_running(self):
        task_statuses["-b"] = "running"
        resp = self.client.post("/api/run/b", HTTP_AUTHORIZATION=BEARER)
        self.assertEqual(resp.status_code, 409)

    def test_launches_scraper_and_marks_running(self):
        with patch(
            "api.views.admin_dashboard._launch_scraper", return_value=4242
        ) as launch:
            resp = self.client.post("/api/run/b", HTTP_AUTHORIZATION=BEARER)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["pid"], 4242)
        launch.assert_called_once_with("b")
        self.assertEqual(task_statuses["-b"], "running")

    def test_diagram_flags_trigger_sync_not_scraper(self):
        with patch("api.views.admin_dashboard.threading.Thread") as thread, \
             patch("api.views.admin_dashboard._launch_scraper") as launch:
            resp = self.client.post("/api/run/a_big", HTTP_AUTHORIZATION=BEARER)

        self.assertEqual(resp.status_code, 200)
        launch.assert_not_called()
        thread.assert_called_once()
        self.assertIn("Server B", resp.json()["message"])


@override_settings(ADMIN_AUTH_TOKEN="")
class AuthDisabledTests(TestCase):
    """An unset AUTH_TOKEN disables the checks (documented dev behaviour)."""

    def test_admin_api_open_when_token_unset(self):
        for url in ADMIN_API_ROUTES:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_dashboard_open_when_token_unset(self):
        resp = self.client.get("/admin")
        self.assertEqual(resp.status_code, 200)
