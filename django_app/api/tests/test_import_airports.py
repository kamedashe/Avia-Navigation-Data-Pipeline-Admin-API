"""The import_airports management command.

The real dataset (data/b.csv.gz) is gitignored, so these build a small fixture
with the same column shape: base airport fields plus inline RWY_*_N groups.
"""

import csv
import gzip
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from api.models import Airport, Runway

BASE_COLUMNS = [
    "Identifier", "City", "State", "Country", "Lat", "Long", "Elevation",
    "OWNERSHIP_TYPE_CODE", "FUEL_TYPES", "CTAF", "UNICOM", "WX", "PHONE_NO",
    "GROUND", "TOWER", "TOWER2", "CLEARANCE DELIVERY",
]
SLOTS = 3


def _header():
    cols = list(BASE_COLUMNS)
    for i in range(SLOTS):
        cols += [f"RWY_ID_{i}", f"TPA_{i}", f"Rgt_tfc_{i}", f"RWY_LEN_{i}", f"RWY_WIDTH_{i}"]
    return cols


def _row(identifier, city="ABBEVILLE", state="AL", runways=(), **over):
    row = {c: "" for c in _header()}
    row.update({
        "Identifier": identifier,
        "City": city,
        "State": state,
        "Country": "US",
        "Lat": "31.60172027",
        "Long": "-85.23854472",
        "Elevation": "468.3",
        "OWNERSHIP_TYPE_CODE": "PU",
        "CTAF": "122.8",
    })
    for i, rwy in enumerate(runways):
        row[f"RWY_ID_{i}"] = rwy.get("id", "18/36")
        row[f"TPA_{i}"] = rwy.get("tpa", "")
        row[f"Rgt_tfc_{i}"] = rwy.get("rgt", "")
        row[f"RWY_LEN_{i}"] = rwy.get("len", "5000")
        row[f"RWY_WIDTH_{i}"] = rwy.get("width", "75")
    row.update(over)
    return row


class ImportAirportsTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _write_csv(self, rows, gz=False) -> Path:
        path = self.tmp / ("b.csv.gz" if gz else "b.csv")
        opener = (lambda: gzip.open(path, "wt", encoding="utf-8", newline="")) if gz \
            else (lambda: open(path, "w", encoding="utf-8", newline=""))
        with opener() as fh:
            writer = csv.DictWriter(fh, fieldnames=_header())
            writer.writeheader()
            writer.writerows(rows)
        return path

    def _import(self, path, **opts):
        out = StringIO()
        call_command("import_airports", path=str(path), stdout=out, **opts)
        return out.getvalue()

    def test_imports_airport_fields(self):
        path = self._write_csv([_row("0J0", runways=[{"id": "18/36"}])])
        self._import(path)

        apt = Airport.objects.get(identifier="0J0")
        self.assertEqual(apt.city, "ABBEVILLE")
        self.assertEqual(apt.state, "AL")
        self.assertEqual(apt.country, "US")
        self.assertAlmostEqual(apt.lat, 31.60172027)
        self.assertAlmostEqual(apt.lon, -85.23854472)
        self.assertAlmostEqual(apt.elevation, 468.3)
        self.assertEqual(apt.ownership_type_code, "PU")
        self.assertEqual(apt.ctaf, "122.8")

    def test_unpacks_inline_runway_groups(self):
        path = self._write_csv([
            _row("MULT", runways=[
                {"id": "18/36", "len": "5000", "width": "75", "tpa": "800"},
                {"id": "09/27", "len": "2644", "width": "112", "rgt": "09R"},
            ])
        ])
        self._import(path)

        runways = list(Runway.objects.filter(airport_id="MULT").order_by("slot"))
        self.assertEqual(len(runways), 2)

        self.assertEqual(runways[0].slot, 0)
        self.assertEqual(runways[0].rwy_id, "18/36")
        self.assertEqual(runways[0].length_ft, 5000)
        self.assertEqual(runways[0].width_ft, 75)
        self.assertEqual(runways[0].tpa, 800)

        self.assertEqual(runways[1].slot, 1)
        self.assertEqual(runways[1].rwy_id, "09/27")
        self.assertEqual(runways[1].rgt_tfc, "09R")
        self.assertIsNone(runways[1].tpa)

    def test_empty_runway_slots_are_skipped(self):
        path = self._write_csv([_row("ONE", runways=[{"id": "18/36"}])])
        self._import(path)
        self.assertEqual(Runway.objects.filter(airport_id="ONE").count(), 1)

    def test_blank_numeric_fields_become_null(self):
        path = self._write_csv([
            _row("BLNK", runways=[{"id": "18/36", "len": "", "width": "", "tpa": ""}])
        ])
        self._import(path)

        rwy = Runway.objects.get(airport_id="BLNK")
        self.assertIsNone(rwy.length_ft)
        self.assertIsNone(rwy.width_ft)
        self.assertIsNone(rwy.tpa)

    def test_reads_gzipped_csv(self):
        path = self._write_csv([_row("GZIP", runways=[{"id": "18/36"}])], gz=True)
        self._import(path)
        self.assertTrue(Airport.objects.filter(identifier="GZIP").exists())

    def test_import_is_idempotent(self):
        path = self._write_csv([
            _row("A1", runways=[{"id": "18/36"}]),
            _row("A2", runways=[{"id": "09/27"}, {"id": "01/19"}]),
        ])
        for _ in range(3):
            self._import(path)

        self.assertEqual(Airport.objects.count(), 2)
        self.assertEqual(Runway.objects.count(), 3)

    def test_reimport_drops_rows_absent_from_the_new_csv(self):
        self._import(self._write_csv([_row("OLD", runways=[{"id": "18/36"}])]))
        self.assertTrue(Airport.objects.filter(identifier="OLD").exists())

        # A later scrape no longer contains OLD.
        path = self.tmp / "new.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_header())
            writer.writeheader()
            writer.writerow(_row("NEW", runways=[{"id": "18/36"}]))
        self._import(path)

        self.assertFalse(Airport.objects.filter(identifier="OLD").exists())
        self.assertTrue(Airport.objects.filter(identifier="NEW").exists())
        self.assertEqual(Runway.objects.count(), 1)

    def test_duplicate_identifiers_are_skipped(self):
        path = self._write_csv([
            _row("DUP", city="FIRST", runways=[{"id": "18/36"}]),
            _row("DUP", city="SECOND", runways=[{"id": "09/27"}]),
        ])
        output = self._import(path)

        self.assertEqual(Airport.objects.filter(identifier="DUP").count(), 1)
        self.assertEqual(Airport.objects.get(identifier="DUP").city, "FIRST")
        self.assertIn("duplicate", output.lower())

    def test_dry_run_writes_nothing(self):
        path = self._write_csv([_row("DRY", runways=[{"id": "18/36"}])])
        output = self._import(path, dry_run=True)

        self.assertEqual(Airport.objects.count(), 0)
        self.assertIn("Dry run", output)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            self._import(self.tmp / "nope.csv")

    def test_csv_without_identifier_column_raises(self):
        path = self.tmp / "bad.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("Foo,Bar\n1,2\n")
        with self.assertRaises(CommandError):
            self._import(path)
