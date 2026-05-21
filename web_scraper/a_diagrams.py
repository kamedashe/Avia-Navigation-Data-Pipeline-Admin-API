"""Airport Diagram Scrapers.

Provides two independent pipelines:

1. **A-Big** — Full FAA d-TPP airport diagrams (PDF → WebP at 150 DPI).
   Source: https://aeronav.faa.gov/upload_313-d/terminal/
   Organized by state → ``{FAA_CODE}_Airport_Diagram.webp``

2. **A-Small** — AOPA thumbnail airport sketches (GIF → inverted PNG).
   Source: https://www.aopa.org/ustprocs/airportgraphics/gif/
   Needs ``b.csv`` identifiers from the base airports dataset.

Both pipelines write output into ``data/a_big/`` and ``data/a_small/``
respectively, and record timestamps in ``changes.json`` via
:func:`web_scraper.update_changes.commit_changes`.
"""

import csv
import io
import json
import logging
import os
import random
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

from .settings import (
    BASE_DIR,
    DOWNLOAD_DIR,
    HEADERS,
    OUTPUT_DIR,
)
from .update_changes import commit_changes

logger = logging.getLogger("web_scraper.a_diagrams")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(_handler)


# ---------------------------------------------------------------------------
# Telegram helper (same pattern as script.py)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def _send_telegram_alert(message: str) -> None:
    """Send an alert to Telegram. Silently fails if not configured."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as exc:
        logger.error("Failed to send Telegram alert: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════
# A-BIG: FAA d-TPP Airport Diagrams → WebP
# ═══════════════════════════════════════════════════════════════════════════

# FAA URLs
_DTPP_BASE_URL = "https://aeronav.faa.gov/upload_313-d/terminal/"
_DTPP_PAGE_URL = (
    "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dtpp/"
)

# Output directories
A_BIG_OUTPUT_DIR = OUTPUT_DIR / "a_big"
_DTPP_ZIP_DIR = DOWNLOAD_DIR / "d_tpp_zips"

WEBP_DPI = 150
_DELAY_BETWEEN_REQUESTS = 1.5
_MAX_RETRIES = 3
_TIMEOUT = 60

_session = requests.Session()
_session.headers.update(
    {"User-Agent": "Mozilla/5.0 (compatible; FAA-dTPP-Downloader/2.2)"}
)
_last_request = 0.0


def _rate_limited_get(url: str, **kwargs) -> requests.Response:
    """GET with rate limiting and automatic retries."""
    global _last_request
    now = time.time()
    if now - _last_request < _DELAY_BETWEEN_REQUESTS:
        time.sleep(_DELAY_BETWEEN_REQUESTS - (now - _last_request))

    for attempt in range(_MAX_RETRIES):
        try:
            resp = _session.get(url, timeout=_TIMEOUT, **kwargs)
            _last_request = time.time()
            resp.raise_for_status()
            return resp
        except Exception:
            if attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(3**attempt)
    raise RuntimeError(f"Failed to fetch {url}")


def _get_latest_cycle() -> str:
    """Detect the latest d-TPP cycle from the FAA website."""
    logger.info("Detecting latest d-TPP cycle from FAA website...")
    try:
        resp = _rate_limited_get(_DTPP_PAGE_URL)
        matches = re.findall(r"(26\d{2})", resp.text)
        if matches:
            latest = max(matches)
            logger.info("Latest cycle detected: %s", latest)
            return latest
    except Exception as exc:
        logger.warning("Cycle detection failed: %s", exc)

    fallback = "2604"
    logger.info("Using fallback cycle: %s", fallback)
    return fallback


def _download_dtpp_file(url: str, filepath: Path) -> bool:
    """Download a single d-TPP volume ZIP."""
    if filepath.exists() and filepath.stat().st_size > 100_000_000:
        logger.info("%s already exists, skipping download.", filepath.name)
        return True

    logger.info("Downloading %s ...", filepath.name)
    try:
        resp = _rate_limited_get(url, stream=True)
        total = int(resp.headers.get("content-length", 0))

        with open(filepath, "wb") as f, tqdm(
            total=total, unit="iB", unit_scale=True, desc=filepath.name[:25]
        ) as bar:
            for chunk in resp.iter_content(chunk_size=8192):
                size = f.write(chunk)
                bar.update(size)
        logger.info("Downloaded %s", filepath.name)
        return True
    except Exception as exc:
        logger.error("Failed to download %s: %s", filepath.name, exc)
        return False


def _parse_metafile(xml_path: Path) -> dict:
    """Parse d-tpp_Metafile.xml to map PDF filenames → (state, faa_code, airport_name).

    Only entries with ``chartseq == 70000`` (Airport Diagram) are included.
    """
    logger.info("Parsing d-tpp_Metafile.xml ...")
    mapping: dict[str, tuple[str, str, str]] = {}
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for state in root.findall(".//state_code"):
            state_code = state.get("ID")
            for airport in state.findall(".//airport_name"):
                faa_code = airport.get("apt_ident")
                airport_name = airport.get("ID", "")
                if not faa_code:
                    continue
                for record in airport.findall("record"):
                    chart_seq_el = record.find("chartseq")
                    if chart_seq_el is not None and chart_seq_el.text == "70000":
                        pdf_name_el = record.find("pdf_name")
                        if pdf_name_el is not None and pdf_name_el.text:
                            mapping[pdf_name_el.text] = (
                                state_code,
                                faa_code.upper(),
                                airport_name,
                            )
        logger.info("Mapped %d airport diagrams from metafile.", len(mapping))
    except Exception as exc:
        logger.error("Error parsing metafile: %s", exc)
    return mapping


def _pdf_to_webp(pdf_path: Path, output_path: Path, dpi: int = 150) -> bool:
    """Convert a single-page PDF to WebP using PyMuPDF."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        page = doc[0]
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        if Image is None:
            raise ImportError("Pillow (PIL) is required for WebP conversion.")
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.save(output_path, "WEBP", quality=85, method=6)
        doc.close()
        return True
    except ImportError:
        logger.error("PyMuPDF (fitz) or Pillow not installed.")
        return False
    except Exception as exc:
        logger.error("Error converting %s: %s", pdf_path.name, exc)
        return False


def run_a_big(cycle: Optional[str] = None) -> None:
    """Full pipeline: download d-TPP volumes → extract diagrams → convert to WebP.

    Results are saved in ``data/a_big/{STATE}/{FAA_CODE}.webp``.

    Wrapped in try/except: on any uncaught exception the error is logged,
    a Telegram alert is sent, and the exception is re-raised so the
    subprocess exits with a non-zero code (which resets the admin status).
    """
    logger.info("=== A-Big pipeline start ===")

    try:
        cycle = cycle or _get_latest_cycle()
        logger.info("Using cycle: %s", cycle)

        os.makedirs(_DTPP_ZIP_DIR, exist_ok=True)
        os.makedirs(A_BIG_OUTPUT_DIR, exist_ok=True)

        # Step 1: Download volumes
        volumes = ["DDTPPA", "DDTPPB", "DDTPPC", "DDTPPD", "DDTPPE"]
        for vol in volumes:
            filename = f"{vol}_{cycle}16.zip"
            url = _DTPP_BASE_URL + filename
            filepath = _DTPP_ZIP_DIR / filename
            _download_dtpp_file(url, filepath)

        # Step 2: Extract metafile from DDTPPE
        metafile_xml: Optional[Path] = None
        metafile_zip = _DTPP_ZIP_DIR / f"DDTPPE_{cycle}16.zip"
        if metafile_zip.exists():
            try:
                with zipfile.ZipFile(metafile_zip, "r") as z:
                    for name in z.namelist():
                        if "Metafile.xml" in name:
                            z.extract(name, _DTPP_ZIP_DIR)
                            metafile_xml = _DTPP_ZIP_DIR / Path(name).name
                            break
            except Exception as exc:
                logger.warning("Could not extract metafile: %s", exc)

        mapping = _parse_metafile(metafile_xml) if metafile_xml and metafile_xml.exists() else {}

        # Step 3: Extract diagram PDFs and convert to WebP
        total_converted = 0
        total_failed = 0
        stats: dict[str, int] = defaultdict(int)

        zip_files = sorted(_DTPP_ZIP_DIR.glob(f"*_{cycle}16.zip"))
        for zip_path in zip_files:
            logger.info("Processing %s ...", zip_path.name)
            try:
                with zipfile.ZipFile(zip_path, "r") as z:
                    for file_info in tqdm(z.infolist(), desc=f"Scanning {zip_path.name}", leave=False):
                        if not file_info.filename.lower().endswith(".pdf"):
                            continue

                        pdf_name = Path(file_info.filename).name
                        if pdf_name not in mapping:
                            continue

                        state, faa_code, _ = mapping[pdf_name]
                        state_dir = A_BIG_OUTPUT_DIR / state
                        state_dir.mkdir(parents=True, exist_ok=True)
                        webp_target = state_dir / f"{faa_code}.webp"

                        # Skip if already converted
                        if webp_target.exists():
                            stats[state] += 1
                            total_converted += 1
                            continue

                        # Extract PDF to temp, convert, delete
                        z.extract(file_info, _DTPP_ZIP_DIR)
                        extracted_pdf = _DTPP_ZIP_DIR / file_info.filename

                        if _pdf_to_webp(extracted_pdf, webp_target, WEBP_DPI):
                            total_converted += 1
                            stats[state] += 1
                        else:
                            total_failed += 1

                        # Cleanup extracted PDF
                        try:
                            extracted_pdf.unlink()
                        except OSError:
                            pass

            except Exception as exc:
                logger.error("Error processing %s: %s", zip_path.name, exc)

        logger.info(
            "A-Big complete: %d converted, %d failed, %d states.",
            total_converted,
            total_failed,
            len(stats),
        )

        # Record in changes.json (directory size is computed recursively)
        commit_changes("a_big", output_file_path=str(A_BIG_OUTPUT_DIR))

        _send_telegram_alert(
            f"✅ <b>A-Big Diagrams Updated</b>\n"
            f"<b>Cycle:</b> {cycle}\n"
            f"<b>Converted:</b> {total_converted}\n"
            f"<b>Failed:</b> {total_failed}"
        )

    except Exception as exc:
        logger.exception("A-Big pipeline crashed: %s", exc)
        _send_telegram_alert(
            f"🚨 <b>A-Big Pipeline CRASHED</b>\n"
            f"<b>Error:</b> <code>{exc}</code>"
        )
        raise  # Re-raise so subprocess returns non-zero exit code


# ═══════════════════════════════════════════════════════════════════════════
# A-SMALL: AOPA Airport Sketches → Inverted PNG
# ═══════════════════════════════════════════════════════════════════════════

_AOPA_BASE_URL = "https://www.aopa.org/ustprocs/airportgraphics/gif/tn_{id}_tif.gif"
A_SMALL_OUTPUT_DIR = OUTPUT_DIR / "a_small"


def _get_airport_identifiers() -> list[str]:
    """Read airport identifiers from the base airports CSV (b.csv.gz or b.csv).

    The b.csv.gz file is produced by ``file_creator.create_base_file`` and
    is always gzip-compressed on production.  The first column is
    ``Identifier`` (the FAA airport code, e.g. ``LAX``, ``JFK``).

    Falls back to an empty list if no source file is found.
    """
    import gzip as _gzip

    candidates = [
        BASE_DIR / "data" / "b.csv.gz",
        OUTPUT_DIR / "b.csv.gz",
        BASE_DIR / "data" / "b.csv",
        OUTPUT_DIR / "b.csv",
    ]

    for csv_path in candidates:
        if not csv_path.exists():
            continue

        logger.info("Trying to read identifiers from %s ...", csv_path)
        try:
            opener = _gzip.open if str(csv_path).endswith(".gz") else open
            identifiers: list[str] = []

            with opener(csv_path, "rt", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)

                # Log discovered column names for debugging
                if reader.fieldnames:
                    logger.info(
                        "CSV columns (%d): %s",
                        len(reader.fieldnames),
                        ", ".join(reader.fieldnames[:10]),
                    )
                else:
                    logger.warning("CSV has no header row, falling back to index-based read.")
                    # Rewind and try index-based approach
                    f.seek(0)
                    idx_reader = csv.reader(f)
                    next(idx_reader, None)  # skip header line
                    for row in idx_reader:
                        if row and row[0].strip():
                            identifiers.append(row[0].strip())
                    if identifiers:
                        logger.info(
                            "Loaded %d identifiers (index-based) from %s",
                            len(identifiers),
                            csv_path.name,
                        )
                        return identifiers
                    continue

                for row in reader:
                    # Try known column names: Identifier (from file_creator) → ARPT_ID (raw FAA)
                    ident = (
                        row.get("Identifier", "")
                        or row.get("ARPT_ID", "")
                        or row.get("identifier", "")
                    ).strip()
                    if ident:
                        identifiers.append(ident)

            if identifiers:
                logger.info(
                    "Loaded %d airport identifiers from %s",
                    len(identifiers),
                    csv_path.name,
                )
                return identifiers

            logger.warning("File %s exists but yielded 0 identifiers.", csv_path.name)

        except Exception as exc:
            logger.error(
                "Failed to read %s: %s\n"
                "Make sure the file is a valid gzip-compressed CSV "
                "with an 'Identifier' column.",
                csv_path,
                exc,
                exc_info=True,
            )

    logger.error(
        "No base airports CSV found in any of: %s. "
        "A-Small pipeline cannot proceed without airport identifiers. "
        "Run the -b scraper first to generate data/b.csv.gz.",
        [str(p) for p in candidates],
    )
    return []


def _download_sketch(identifier: str, original_dir: Path, inverted_dir: Path) -> bool:
    """Download a single AOPA sketch and produce an inverted PNG.

    Tries stripped ID first (e.g. TCY), then with K prefix (KTCY).
    Returns True on success.
    """
    stripped = identifier[1:] if identifier.upper().startswith("K") and len(identifier) > 1 else identifier
    with_k = identifier if identifier.upper().startswith("K") else "K" + identifier
    candidates = [stripped, with_k]

    for try_id in candidates:
        url = _AOPA_BASE_URL.format(id=try_id)
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 200 and len(response.content) > 500:
                # Save original GIF
                orig_path = original_dir / f"{identifier}.gif"
                with open(orig_path, "wb") as f:
                    f.write(response.content)

                # Save inverted PNG
                if Image is not None and ImageOps is not None:
                    img = Image.open(io.BytesIO(response.content)).convert("RGB")
                    inverted = ImageOps.invert(img)
                    inv_path = inverted_dir / f"{identifier}.png"
                    inverted.save(inv_path)

                return True
        except requests.RequestException:
            continue
    return False


def run_a_small() -> None:
    """Full pipeline: read identifiers → download AOPA sketches → invert.

    Results are saved in ``data/a_small/original/`` and ``data/a_small/inverted/``.

    Wrapped in try/except: on any uncaught exception the error is logged,
    a Telegram alert is sent, and the exception is re-raised so the
    subprocess exits with a non-zero code (which resets the admin status).
    """
    logger.info("=== A-Small pipeline start ===")

    try:
        original_dir = A_SMALL_OUTPUT_DIR / "original"
        inverted_dir = A_SMALL_OUTPUT_DIR / "inverted"
        os.makedirs(original_dir, exist_ok=True)
        os.makedirs(inverted_dir, exist_ok=True)

        identifiers = _get_airport_identifiers()
        if not identifiers:
            logger.error(
                "No identifiers found. Cannot proceed with A-Small. "
                "Ensure data/b.csv.gz exists (run -b scraper first)."
            )
            _send_telegram_alert(
                "🚨 <b>A-Small Failed</b>\n"
                "<b>Reason:</b> No airport identifiers found in data/b.csv.gz.\n"
                "Run the -b scraper first."
            )
            return

        total = len(identifiers)
        success = 0
        failed_list: list[str] = []

        for ident in tqdm(identifiers, desc="Downloading sketches"):
            orig_path = original_dir / f"{ident}.gif"
            inv_path = inverted_dir / f"{ident}.png"

            # Skip already downloaded
            if orig_path.exists() and inv_path.exists():
                success += 1
                continue

            if _download_sketch(ident, original_dir, inverted_dir):
                success += 1
            else:
                failed_list.append(ident)

            time.sleep(random.uniform(0.5, 1.5))

        logger.info("A-Small complete: %d/%d downloaded.", success, total)

        if failed_list:
            failed_file = A_SMALL_OUTPUT_DIR / "failed_sketches.txt"
            with open(failed_file, "w") as f:
                f.write("\n".join(failed_list))
            logger.info("%d failed. List saved to %s", len(failed_list), failed_file)

        # Record in changes.json (directory size is computed recursively)
        commit_changes("a_small", output_file_path=str(A_SMALL_OUTPUT_DIR))

        _send_telegram_alert(
            f"✅ <b>A-Small Sketches Updated</b>\n"
            f"<b>Success:</b> {success}/{total}\n"
            f"<b>Failed:</b> {len(failed_list)}"
        )

    except Exception as exc:
        logger.exception("A-Small pipeline crashed: %s", exc)
        _send_telegram_alert(
            f"🚨 <b>A-Small Pipeline CRASHED</b>\n"
            f"<b>Error:</b> <code>{exc}</code>"
        )
        raise  # Re-raise so subprocess returns non-zero exit code


# ═══════════════════════════════════════════════════════════════════════════
# CLI entry point (for direct invocation)
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Airport Diagrams Downloader (A-Big & A-Small)"
    )
    parser.add_argument(
        "--a-big", action="store_true", help="Run FAA Airport Diagrams (big) pipeline"
    )
    parser.add_argument(
        "--a-small", action="store_true", help="Run AOPA Sketches (small) pipeline"
    )
    parser.add_argument(
        "--cycle", type=str, default=None, help="Force specific d-TPP cycle for A-Big"
    )
    args = parser.parse_args()

    if args.a_big or not (args.a_big or args.a_small):
        run_a_big(cycle=args.cycle)
    if args.a_small or not (args.a_big or args.a_small):
        run_a_small()
