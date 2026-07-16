"""Public, unauthenticated routes.

These lock in the contract the mobile clients depend on: the exact paths, the
file streaming behaviour, and the "empty rather than error" responses the
listing endpoints give when a data directory has not been synced yet.
"""

import gzip
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings


class RootTests(TestCase):
    def test_root_returns_probe_payload(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"Privet": "Mir"})


class FileDownloadTests(TestCase):
    """The /api/<flag>/ gzip downloads."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)

    def _write_gz(self, name: str, payload: bytes = b"header\nrow\n") -> Path:
        path = self.data_dir / name
        with gzip.open(path, "wb") as fh:
            fh.write(payload)
        return path

    def _get(self, url: str):
        with override_settings(DATA_DIR=self.data_dir):
            return self.client.get(url)

    def test_serves_gzip_as_attachment(self):
        self._write_gz("b.csv.gz")
        resp = self._get("/api/b/")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.streaming)
        self.assertEqual(resp["Content-Type"], "application/gzip")
        self.assertIn('filename="b.csv.gz"', resp["Content-Disposition"])
        b"".join(resp.streaming_content)  # drain so the file handle closes

    def test_t_flag_maps_to_tfr_filename(self):
        """/api/t/ is the one flag whose file is not named after it."""
        self._write_gz("tfr.csv.gz")
        resp = self._get("/api/t/")

        self.assertEqual(resp.status_code, 200)
        self.assertIn('filename="tfr.csv.gz"', resp["Content-Disposition"])
        b"".join(resp.streaming_content)

    def test_missing_file_returns_404(self):
        resp = self._get("/api/c/")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"detail": "File not found"})

    def test_every_flag_is_routed(self):
        for flag, filename in [
            ("b", "b.csv.gz"), ("c", "c.csv.gz"), ("d", "d.csv.gz"),
            ("e", "e.csv.gz"), ("f", "f.csv.gz"), ("g", "g.csv.gz"),
            ("n", "n.csv.gz"), ("r", "r.csv.gz"), ("t", "tfr.csv.gz"),
        ]:
            with self.subTest(flag=flag):
                self._write_gz(filename)
                resp = self._get(f"/api/{flag}/")
                self.assertEqual(resp.status_code, 200)
                b"".join(resp.streaming_content)


class MapsListingTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)

    def test_missing_dir_lists_empty_rather_than_erroring(self):
        resp = self.client.get("/api/v1/maps")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json()), {"files", "count"})

    def test_rejects_non_mbtiles_extension(self):
        resp = self.client.get("/api/v1/maps/evil.exe")
        self.assertEqual(resp.status_code, 400)

    def test_rejects_path_traversal(self):
        # A filename that does not survive sanitization must be refused.
        resp = self.client.get("/api/v1/maps/info/..%2Fsettings.json")
        self.assertIn(resp.status_code, (400, 404))

    def test_info_route_is_not_swallowed_by_filename_route(self):
        """'/maps/info' must hit the listing view, not get(filename='info')."""
        resp = self.client.get("/api/v1/maps/info")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json()), {"files", "count"})


class DiagramListingTests(TestCase):
    def test_a_big_lists_states(self):
        resp = self.client.get("/api/v1/a-big")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("states", resp.json())

    def test_a_small_pagination_defaults(self):
        resp = self.client.get("/api/v1/a-small")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["per_page"], 100)

    def test_a_small_per_page_is_capped(self):
        resp = self.client.get("/api/v1/a-small", {"per_page": 9999})
        self.assertEqual(resp.json()["per_page"], 500)

    def test_unknown_state_returns_404(self):
        resp = self.client.get("/api/v1/a-big/ZZ")
        self.assertEqual(resp.status_code, 404)

    def test_download_route_is_not_swallowed_by_state_route(self):
        """'/a-big/download' must hit the archive view, not list_a_big_codes."""
        resp = self.client.get("/api/v1/a-big/download")
        # No archive synced in tests -> the archive view's own 404 message.
        self.assertEqual(resp.status_code, 404)
        self.assertIn("a-big.tar.gz", resp.json()["detail"])
