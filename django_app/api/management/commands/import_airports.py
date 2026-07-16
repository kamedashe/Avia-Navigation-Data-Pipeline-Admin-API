"""Import the scraper's base airport dataset (``data/b.csv.gz``) into Postgres.

The CSV is denormalized: one row per airport with up to 11 inline runway
groups (``RWY_ID_N``, ``TPA_N``, ``Rgt_tfc_N``, ``RWY_LEN_N``, ``RWY_WIDTH_N``).
This command unpacks those into ``Runway`` rows.

The import is idempotent: it replaces the airport table contents wholesale,
mirroring how the scraper regenerates the CSV each cycle.

Usage::

    python manage.py import_airports                  # uses data/b.csv.gz
    python manage.py import_airports --path other.csv.gz
    python manage.py import_airports --dry-run
"""

import csv
import gzip
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import Airport, Runway

# Maximum runway group index present in the CSV header (RWY_ID_0 .. RWY_ID_10)
_RUNWAY_SLOT_RE = re.compile(r"^RWY_ID_(\d+)$")

BATCH_SIZE = 2000


def _clean(value: str) -> str:
    return (value or "").strip()


def _to_float(value: str):
    value = _clean(value)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str):
    value = _clean(value)
    if not value:
        return None
    try:
        # Some numeric columns arrive as "5000.0"
        return int(float(value))
    except ValueError:
        return None


def _open_csv(path: Path):
    """Open a plain or gzipped CSV as text."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
    return open(path, "r", encoding="utf-8", errors="replace", newline="")


class Command(BaseCommand):
    help = "Import base airports + runways from the scraper's b.csv.gz into Postgres."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=None,
            help="Path to the CSV (.csv or .csv.gz). Defaults to <project>/data/b.csv.gz",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report counts without writing to the database.",
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"]) if opts["path"] else settings.DATA_DIR / "b.csv.gz"
        if not path.is_file():
            raise CommandError(f"CSV not found: {path}")

        self.stdout.write(f"Reading {path} …")
        with _open_csv(path) as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            slots = sorted(
                int(m.group(1))
                for h in header
                for m in [_RUNWAY_SLOT_RE.match(h)]
                if m
            )
            if "Identifier" not in header:
                raise CommandError(
                    f"Unexpected CSV header (no 'Identifier' column): {header[:5]}"
                )

            airports: list[Airport] = []
            runways: list[Runway] = []
            seen: set[str] = set()
            skipped_dupes = 0

            for row in reader:
                ident = _clean(row.get("Identifier"))
                if not ident:
                    continue
                if ident in seen:
                    skipped_dupes += 1
                    continue
                seen.add(ident)

                airports.append(
                    Airport(
                        identifier=ident,
                        city=_clean(row.get("City"))[:64],
                        state=_clean(row.get("State"))[:8],
                        country=_clean(row.get("Country"))[:8],
                        lat=_to_float(row.get("Lat")) or 0.0,
                        lon=_to_float(row.get("Long")) or 0.0,
                        elevation=_to_float(row.get("Elevation")),
                        ownership_type_code=_clean(row.get("OWNERSHIP_TYPE_CODE"))[:4],
                        fuel_types=_clean(row.get("FUEL_TYPES"))[:64],
                        ctaf=_clean(row.get("CTAF"))[:32],
                        unicom=_clean(row.get("UNICOM"))[:32],
                        wx=_clean(row.get("WX"))[:64],
                        phone_no=_clean(row.get("PHONE_NO"))[:32],
                        ground=_clean(row.get("GROUND"))[:128],
                        tower=_clean(row.get("TOWER"))[:128],
                        tower2=_clean(row.get("TOWER2"))[:128],
                        clearance_delivery=_clean(row.get("CLEARANCE DELIVERY"))[:128],
                    )
                )

                for i in slots:
                    rwy_id = _clean(row.get(f"RWY_ID_{i}"))
                    if not rwy_id:
                        continue  # empty slot
                    runways.append(
                        Runway(
                            airport_id=ident,
                            slot=i,
                            rwy_id=rwy_id[:16],
                            tpa=_to_int(row.get(f"TPA_{i}")),
                            rgt_tfc=_clean(row.get(f"Rgt_tfc_{i}"))[:16],
                            length_ft=_to_int(row.get(f"RWY_LEN_{i}")),
                            width_ft=_to_int(row.get(f"RWY_WIDTH_{i}")),
                        )
                    )

        self.stdout.write(
            f"Parsed {len(airports)} airports and {len(runways)} runways "
            f"(runway slots present in header: {slots})."
        )
        if skipped_dupes:
            self.stdout.write(
                self.style.WARNING(f"Skipped {skipped_dupes} duplicate identifier(s).")
            )

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — nothing written."))
            return

        with transaction.atomic():
            # Runways cascade with their airports.
            deleted, _ = Airport.objects.all().delete()
            Airport.objects.bulk_create(airports, batch_size=BATCH_SIZE)
            Runway.objects.bulk_create(runways, batch_size=BATCH_SIZE)

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {Airport.objects.count()} airports, "
                f"{Runway.objects.count()} runways."
            )
        )
