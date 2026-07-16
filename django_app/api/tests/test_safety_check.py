"""File-size safety check (Предохранитель).

Guards mobile clients against a scraper run that produces an absurdly large
file. Patches the reference sizes so the tests stay fast instead of writing
multi-megabyte fixtures.
"""

import gzip
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from api.services import safety_check
from api.services.safety_check import (
    SAFETY_MULTIPLIER,
    get_oversized_flags,
    validate_file_size,
)
from api.services.task_status import task_statuses

# 100-byte reference => anything over 500 bytes is "oversized"
TINY_REFERENCE = {"b": 100}


class ValidateFileSizeTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        for key in list(task_statuses):
            task_statuses[key] = "idle"

    def _write(self, name: str, size: int) -> Path:
        path = self.data_dir / name
        path.write_bytes(b"x" * size)
        return path

    def test_file_within_limit_is_allowed(self):
        path = self._write("b.csv.gz", 100 * SAFETY_MULTIPLIER)
        with patch.dict(safety_check.EXPECTED_FILE_SIZES_BYTES, TINY_REFERENCE):
            self.assertTrue(validate_file_size("b", path))

    def test_oversized_file_is_blocked_and_flagged(self):
        path = self._write("b.csv.gz", 100 * SAFETY_MULTIPLIER + 1)
        with patch.dict(safety_check.EXPECTED_FILE_SIZES_BYTES, TINY_REFERENCE):
            allowed = validate_file_size("b", path, task_statuses=task_statuses)

        self.assertFalse(allowed)
        self.assertEqual(task_statuses["-b"], "ERROR_SIZE")

    def test_missing_file_is_not_treated_as_anomaly(self):
        with patch.dict(safety_check.EXPECTED_FILE_SIZES_BYTES, TINY_REFERENCE):
            self.assertTrue(validate_file_size("b", self.data_dir / "nope.gz"))

    def test_untracked_key_is_not_blocked(self):
        path = self._write("weird.gz", 10_000)
        self.assertTrue(validate_file_size("totally-unknown-key", path))


class OversizedFlagDetectionTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)

    def test_reports_flag_whose_file_exceeds_threshold(self):
        (self.data_dir / "b.csv.gz").write_bytes(b"x" * (100 * SAFETY_MULTIPLIER + 1))
        with override_settings(DATA_DIR=self.data_dir, DOWNLOADED_DIR=self.data_dir), \
             patch.dict(safety_check.EXPECTED_FILE_SIZES_BYTES, TINY_REFERENCE, clear=True):
            self.assertIn("b", get_oversized_flags())

    def test_reports_nothing_when_files_are_sane(self):
        (self.data_dir / "b.csv.gz").write_bytes(b"x" * 100)
        with override_settings(DATA_DIR=self.data_dir, DOWNLOADED_DIR=self.data_dir), \
             patch.dict(safety_check.EXPECTED_FILE_SIZES_BYTES, TINY_REFERENCE, clear=True):
            self.assertEqual(get_oversized_flags(), [])


class SafetyBlockOnDownloadTests(TestCase):
    """An oversized file must be refused by the download endpoint itself."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        for key in list(task_statuses):
            task_statuses[key] = "idle"

    def test_download_blocked_with_500(self):
        path = self.data_dir / "b.csv.gz"
        with gzip.open(path, "wb") as fh:
            fh.write(b"x" * 5000)
        # Force the file over the limit regardless of its compressed size.
        with override_settings(DATA_DIR=self.data_dir), \
             patch.dict(safety_check.EXPECTED_FILE_SIZES_BYTES, {"b": 1}):
            resp = self.client.get("/api/b/")

        self.assertEqual(resp.status_code, 500)
        self.assertIn("Safety Block", resp.json()["detail"])
