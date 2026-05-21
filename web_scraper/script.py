import argparse
import csv
from datetime import datetime
import json
import logging
import os
import sys
import re
import shutil
import time
import traceback
from typing import List
import zipfile

import geopandas as gpd
import pandas as pd
import requests
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()


# ---------------------
# Logging configuration
# ---------------------
logger = logging.getLogger("web_scraper")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(_handler)

# -------------------------
# Telegram Alert Variables
# -------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Add the parent directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from web_scraper.scraper_utils import (
    get_links,
    get_link_to_current_data,
    download_tfr_files,
    download_file_from_url,
)

from web_scraper.file_creator import (
    create_base_file,
    create_waypoint_file,
    create_nav_file,
    create_rwy_end,
    create_daily_obstacle_file,
)
from web_scraper.update_changes import commit_changes, update_file_size_only
from web_scraper.zip_utils import (
    extract_file_from_nested_zip,
    extract_single_file,
    extract_all_files,
    get_name_of_csv_zip,
)
from web_scraper.settings import (
    DOWNLOAD_DIR,
    OUTPUT_DIR,
    HEADERS,
    BASE_AIRPORT_URL,
    DATA_LINK,
    SHAPE_FILE_PATH,
)
from web_scraper.shp_optimizer import (
    create_class_airspace,
    optimize_shape_trf_file,
    read_shp,
    optimize_geometry,
)


download_dir = DOWNLOAD_DIR
output_dir = OUTPUT_DIR
headers = HEADERS
base_airpot_url = BASE_AIRPORT_URL
data_link = DATA_LINK


def send_telegram_alert(message: str) -> None:
    """Send an error alert message to the configured Telegram chat.

    Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment variables.
    Silently fails if credentials are missing or the request errors out,
    so it never masks the original exception.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set. "
            "Skipping Telegram alert."
        )
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(
                "Telegram API responded with %s: %s",
                resp.status_code,
                resp.text,
            )
    except Exception as tg_err:
        logger.error("Failed to send Telegram alert: %s", tg_err)


def cleanup_old_files(
    directory_path: str,
    extension: str = ".zip",
    keep_count: int = 2,
) -> None:
    """Remove old files from a directory, keeping only the newest ones.

    Finds all files matching the given extension in ``directory_path``,
    sorts them by modification time (newest first), and deletes
    everything beyond ``keep_count``.  Each deletion is wrapped in its
    own try/except so a single locked file never crashes the scraper.

    Args:
        directory_path: Absolute path to scan for files.
        extension: File extension filter (e.g. ".zip", ".csv").
        keep_count: How many newest files to keep.
    """
    import glob

    pattern = os.path.join(directory_path, f"*{extension}")
    files = glob.glob(pattern)

    if not files:
        logger.info("cleanup_old_files: no %s files found in %s", extension, directory_path)
        return

    # Sort by modification time, newest first
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

    files_to_delete = files[keep_count:]
    if not files_to_delete:
        logger.info(
            "cleanup_old_files: %d %s file(s) found, nothing to delete (keep_count=%d)",
            len(files), extension, keep_count,
        )
        return

    logger.info(
        "cleanup_old_files: %d %s file(s) found, deleting %d oldest",
        len(files), extension, len(files_to_delete),
    )

    for filepath in files_to_delete:
        try:
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            os.remove(filepath)
            logger.info("Deleted: %s (%.1f MB)", os.path.basename(filepath), size_mb)
        except Exception as e:
            logger.error("Failed to delete %s: %s", filepath, e)
            send_telegram_alert(
                f"⚠️ <b>Cleanup Warning</b>\n"
                f"<b>File:</b> <code>{os.path.basename(filepath)}</code>\n"
                f"<b>Error:</b> <code>{e}</code>"
            )


def get_today_date_str(dm1="", dm2="", d=True, t=True):
    if d and not (t):
        return datetime.now().strftime("%Y" + dm1 + "%m" + dm1 + "%d")
    if t and not (d):
        return datetime.now().strftime("%H" + dm2 + "%M" + dm2 + "%S")
    return datetime.now().strftime(
        "%Y" + dm1 + "%m" + dm1 + "%d" + "_" + "%H" + dm2 + "%M" + dm2 + "%S"
    )


def create_content_dir(arg) -> str:
    dir = output_dir
    os.makedirs(dir, exist_ok=True)
    return str(dir)


def find_file(file_name, root_dir="."):
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if file_name in filenames:
            return os.path.join(dirpath, file_name)
    return False


def process_text_for_wx_file(text):
    try:
        datetime_object = datetime.strptime(
            text[: text.find("\n")] + ":00", "%Y/%m/%d %H:%M:%S"
        )
        if datetime_object.hour < 12:
            datetime_object = str(datetime_object).replace(" ", ", ") + " AM"
        else:
            datetime_object = str(datetime_object).replace(" ", ", ") + " PM"
        text = datetime_object + ", " + text[(text.find("\n") + 1) :].replace(" ", ", ")
    except ValueError:
        pass
    finally:
        return text[: ((re.search(r"([a-zA-Z])([^a-zA-Z]*)$", text)).end(1))] + "\n"


def convert_shp_to_csv(
    files_date_list: List[List[str]], download_dir: str, output_path: str
) -> None:
    """Convert shapefiles to CSV files."""
    print("converting shp to csv ...")
    files_list = files_date_list[0]
    date_list = files_date_list[1]
    files_dict = dict(zip(date_list, files_list))
    all_gdfs = []
    for k, v in files_dict.items():
        if v.endswith(".zip"):
            if not os.path.isfile(v):
                logger.warning("TFR file not found, skipping: %s", v)
                continue
            try:
                with zipfile.ZipFile(v, "r"):
                    files = extract_all_files(v, download_dir, False)
                    for f in files:
                        if f.endswith(".shp"):
                            file_name = os.path.join(download_dir, f)
                            gdf = read_shp(file_name)
                            gdf["EFFECTIVE"] = k
                            all_gdfs.append(gdf)
                            break
            except (zipfile.BadZipFile, OSError) as e:
                logger.warning("Skipping invalid/missing TFR file %s: %s", v, e)
                continue
    if all_gdfs:
        final_gdf = pd.concat(all_gdfs, ignore_index=True)
        file_path = os.path.join(output_path, "tfr.csv.gz")
        optimize_shape_trf_file(gdf=final_gdf, output_csv=file_path)


def create_sua(url, geometry=False):
    print("creating csv file ...")
    for _ in tqdm(range(1)):
        while True:
            try:
                response = requests.get(url, headers=HEADERS)
                response.raise_for_status()
                break
            except Exception as e:
                print(e)
                time.sleep(10)

        data = json.loads(response.text)["features"]
        pdata = []
        if not geometry:
            for d in data:
                pdata.append(d["attributes"])
        else:
            from shapely.geometry import Polygon, MultiPolygon, Point
            from shapely.geometry.polygon import orient

            def _signed_area(ring):
                """Return signed area of a ring (list of [x,y] pairs).

                Positive  → counter-clockwise (exterior in GeoJSON / Shapely).
                Negative  → clockwise (hole).
                ArcGIS convention is the opposite (CW = exterior), so the
                caller should treat *negative* signed-area as exterior.
                """
                area = 0.0
                n = len(ring)
                for i in range(n):
                    x1, y1 = ring[i][0], ring[i][1]
                    x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
                    area += x1 * y2 - x2 * y1
                return area / 2.0

            for d in data:
                attrs = d["attributes"].copy()
                # Convert ArcGIS rings format to WKT polygon / multipolygon
                if "geometry" in d:
                    if "rings" in d["geometry"]:
                        rings = d["geometry"]["rings"]
                        if rings and len(rings) > 0:
                            try:
                                # ArcGIS convention: clockwise ring (negative
                                # signed area) is an exterior ring; counter-
                                # clockwise (positive) is a hole.
                                # Group rings: each exterior starts a new
                                # polygon, subsequent holes attach to it.
                                polygon_parts = []  # list of (exterior, [holes])
                                for ring in rings:
                                    sa = _signed_area(ring)
                                    if sa <= 0:
                                        # Exterior ring → start new polygon part
                                        polygon_parts.append((ring, []))
                                    else:
                                        # Hole → attach to the last exterior
                                        if polygon_parts:
                                            polygon_parts[-1][1].append(ring)
                                        else:
                                            # Fallback: no exterior seen yet;
                                            # treat as exterior
                                            polygon_parts.append((ring, []))

                                polys = []
                                for ext, holes in polygon_parts:
                                    polys.append(Polygon(ext, holes))

                                if len(polys) == 1:
                                    geom = polys[0]
                                else:
                                    geom = MultiPolygon(polys)

                                # Apply optimization (Simplify and Round)
                                geom = optimize_geometry(geom, tolerance=0.00001, precision=5)
                                attrs["geometry"] = geom.wkt if geom else None
                            except Exception as e:
                                print(f"Warning: Failed to create polygon for {attrs.get('NAME', 'unknown')}: {e}")
                                attrs["geometry"] = None
                        else:
                            attrs["geometry"] = None
                    elif "x" in d["geometry"] and "y" in d["geometry"]:
                        try:
                            pt = Point(d["geometry"]["x"], d["geometry"]["y"])
                            # Apply optimization (Round)
                            pt = optimize_geometry(pt, tolerance=0.00001, precision=5)
                            attrs["geometry"] = pt.wkt if pt else None
                            attrs["LONG"] = pt.x if pt else d["geometry"]["x"]
                            attrs["LAT"] = pt.y if pt else d["geometry"]["y"]
                        except Exception as e:
                            print(f"Warning: Failed to create point for {attrs.get('NAME', 'unknown')}: {e}")
                            attrs["geometry"] = None
                            attrs["LONG"] = None
                            attrs["LAT"] = None
                    else:
                        attrs["geometry"] = None
                else:
                    attrs["geometry"] = None
                pdata.append(attrs)

        file_path = os.path.join(download_dir, "edata.json")
        f = open(file_path, "w")
        json.dump(pdata, f, default=str)
        f.close()

    return file_path


def delete_previous_content(arg):
    pass


def check_all_args(b, f, d, t, c, e, g, n, r):
    return b or f or d or t or c or e or g or n or r


# ---------------
# MAIN FUNCTION
# ---------------


def main():
    parser = argparse.ArgumentParser(description="Process some arguments.")
    parser.add_argument("-b", action="store_true")
    parser.add_argument("-f", action="store_true")
    parser.add_argument("-d", action="store_true")
    parser.add_argument("-t", action="store_true")
    parser.add_argument("-c", action="store_true")
    parser.add_argument("-e", action="store_true")
    parser.add_argument("-g", action="store_true")
    parser.add_argument("-n", action="store_true")
    parser.add_argument("-r", action="store_true")

    args = parser.parse_args()

    skip_b = False  # Will be set True if 28Day zip already exists

    if (
        args.b
        or args.f
        or args.c
        or args.n
        or args.r
        or not (
            check_all_args(
                args.b,
                args.f,
                args.d,
                args.t,
                args.c,
                args.e,
                args.g,
                args.n,
                args.r,
            )
        )
    ):
        # step 0
        try:
            print("\nstep 0 (downloading 28dayNASR_zip) start ", datetime.now())
            file_name_of_28dayNASR_zip, is_new_28day = download_file_from_url(
                get_link_to_current_data(
                    data_link, "/28DaySub/28DaySubscription_Effective_"
                ),
                download_dir,
            )

            # If the zip already existed locally, skip -b processing but let other flags continue
            if not is_new_28day:
                print("No new 28Day file. Skipping -b processing.")
                skip_b = True

                # Even though we skip processing, update the file size in
                # changes.json so the dashboard doesn't show a dash ("—").
                existing_output = os.path.join(str(output_dir), "b.csv.gz")
                if os.path.isfile(existing_output):
                    update_file_size_only("b", output_file_path=existing_output)
                else:
                    print(f"Warning: expected output {existing_output} not found, cannot update file size.")
            else:
                skip_b = False

            path_to_file_to_extract = "CSV_Data/" + get_name_of_csv_zip(
                file_name_of_28dayNASR_zip
            )

            # Validate the downloaded zip — if corrupted, delete and re-download
            if not zipfile.is_zipfile(file_name_of_28dayNASR_zip):
                logger.warning(
                    "28DayNASR zip is corrupted/incomplete, re-downloading: %s",
                    file_name_of_28dayNASR_zip,
                )
                os.remove(file_name_of_28dayNASR_zip)
                file_name_of_28dayNASR_zip, is_new_28day = download_file_from_url(
                    get_link_to_current_data(
                        data_link, "/28DaySub/28DaySubscription_Effective_"
                    ),
                    download_dir,
                    check_existing=False,
                )
                skip_b = False
                path_to_file_to_extract = "CSV_Data/" + get_name_of_csv_zip(
                    file_name_of_28dayNASR_zip
                )
                if not zipfile.is_zipfile(file_name_of_28dayNASR_zip):
                    raise Exception(
                        f"28DayNASR zip still invalid after re-download: "
                        f"{file_name_of_28dayNASR_zip}"
                    )

            print("step 0 (downloading 28dayNASR_zip) finish ", datetime.now())
        except Exception as e:
            logger.exception("Error during step 0 (downloading 28dayNASR_zip): %s", e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Stage:</b> step 0 (28dayNASR_zip download)\n"
                f"<b>Error:</b> <code>{e}</code>"
            )
            raise

    if not skip_b and (
        args.b or not (
            check_all_args(
                args.b,
                args.f,
                args.d,
                args.t,
                args.c,
                args.e,
                args.g,
                args.n,
                args.r,
            )
        )
    ):
        # step -b
        arg = "b"
        try:
            print("step (-", arg, ") start ", datetime.now())
            file_to_extract = "APT_BASE.csv"
            file_name_of_extracted_file1 = extract_file_from_nested_zip(
                file_name_of_28dayNASR_zip,
                path_to_file_to_extract,
                file_to_extract,
                download_dir,
            )
            file_to_extract = "FRQ.csv"
            file_name_of_extracted_file2 = extract_file_from_nested_zip(
                file_name_of_28dayNASR_zip,
                path_to_file_to_extract,
                file_to_extract,
                download_dir,
            )
            file_to_extract = "APT_RWY.csv"
            file_name_of_extracted_file3 = extract_file_from_nested_zip(
                file_name_of_28dayNASR_zip,
                path_to_file_to_extract,
                file_to_extract,
                download_dir,
            )
            file_to_extract = "AWOS.csv"
            file_name_of_extracted_file4 = extract_file_from_nested_zip(
                file_name_of_28dayNASR_zip,
                path_to_file_to_extract,
                file_to_extract,
                download_dir,
            )

            # Download CS_ALL PDF archive - check for existing file first
            import glob
            existing_cs_all = sorted(glob.glob(os.path.join(download_dir, "CS_ALL_*.zip")))
            if existing_cs_all and os.path.getsize(existing_cs_all[-1]) > 200_000_000:
                # Use existing file if it's > 200MB (complete download)
                file_name_of_cs_all = existing_cs_all[-1]
                print(f"Using existing CS_ALL file: {file_name_of_cs_all}")
            else:
                cs_all_links = get_links(
                    "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dafd/",
                    "CS_ALL_",
                )
                cs_all_links = [l for l in cs_all_links if l.endswith('.zip') and 'CS_ALL_' in l]
                if cs_all_links:
                    file_name_of_cs_all, _ = download_file_from_url(cs_all_links[0], download_dir)
                else:
                    raise Exception("Could not find CS_ALL zip file")
            cs_pdfs = extract_all_files(file_name_of_cs_all, download_dir)

            dir = create_content_dir(arg)
            file_path = os.path.join(dir, "b.csv.gz")
            airport_urls = create_base_file(
                file_name_of_extracted_file1,
                file_name_of_extracted_file2,
                file_name_of_extracted_file3,
                file_name_of_extracted_file4,  # AWOS.csv
                cs_pdfs,
                file_path,
                base_airpot_url,
            )
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=file_path)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )

    if args.f or not (
        check_all_args(
            args.b,
            args.f,
            args.d,
            args.t,
            args.c,
            args.e,
            args.g,
            args.n,
            args.r,
        )
    ):
        # step -f
        arg = "f"
        try:
            print("step (-", arg, ") start ", datetime.now())
            file_to_extract = "FIX_BASE.csv"
            file_name_of_extracted_file = extract_file_from_nested_zip(
                file_name_of_28dayNASR_zip,
                path_to_file_to_extract,
                file_to_extract,
                download_dir,
            )

            dir = create_content_dir(arg)
            file_path = os.path.join(dir, "f.csv.gz")
            create_waypoint_file(file_name_of_extracted_file, file_path)
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=file_path)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )



    if args.d or not (
        check_all_args(
            args.b,
            args.f,
            args.d,
            args.t,
            args.c,
            args.e,
            args.g,
            args.n,
            args.r,
        )
    ):
        # step -d
        arg = "d"
        try:
            print("step (-", arg, ") start ", datetime.now())
            file_name_of_DAILY_DOF_DAT_zip, _ = download_file_from_url(
                "https://aeronav.faa.gov/Obst_Data/DAILY_DOF_CSV.ZIP", download_dir
            )
            DOF_file = "DOF.CSV"  # Fixed: uppercase CSV extension
            # print('extracting  ' + DOF_file + ' ...')
            file_name_of_extracted_file = extract_single_file(
                file_name_of_DAILY_DOF_DAT_zip, DOF_file, download_dir
            )

            dir = create_content_dir(arg)
            file_path = os.path.join(dir, "d.csv.gz")
            create_daily_obstacle_file(file_name_of_extracted_file, file_path)
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=file_path)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )



    if args.t or not (
        check_all_args(
            args.b,
            args.f,
            args.d,
            args.t,
            args.c,
            args.e,
            args.g,
            args.n,
            args.r,
        )
    ):
        # step -t
        arg = "t"
        try:
            print("step (-", arg, ") start ", datetime.now())
            delete_previous_content(arg)
            # Use new WFS API method for TFR download
            from .scraper_utils import download_tfr_files_wfs
            files_list = download_tfr_files_wfs(download_dir)
            dir = create_content_dir(arg)
            convert_shp_to_csv(files_list, download_dir, dir)
            tfr_file_path = os.path.join(dir, "tfr.csv.gz")
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=tfr_file_path)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )

    if args.c or not (
        check_all_args(
            args.b,
            args.f,
            args.d,
            args.t,
            args.c,
            args.e,
            args.g,
            args.n,
            args.r,
        )
    ):
        # step -c
        arg = "c"
        try:
            print("step (-", arg, ") start ", datetime.now())
            dir = create_content_dir(arg)

            shape_file_path = SHAPE_FILE_PATH
            extract_single_file(
                file_name_of_28dayNASR_zip,
                shape_file_path.replace(".shp", ".dbf"),
                download_dir,
            )
            extract_single_file(
                file_name_of_28dayNASR_zip,
                shape_file_path.replace(".shp", ".prj"),
                download_dir,
            )
            extract_single_file(file_name_of_28dayNASR_zip, shape_file_path, download_dir)
            extract_single_file(
                file_name_of_28dayNASR_zip,
                shape_file_path.replace(".shp", ".shx"),
                download_dir,
            )

            file_path = create_class_airspace(shape_file_path, download_dir, dir)
            file_name = "Class_Airspace"

            # Skip DB import for airspace - geometry fields are too large for PostgreSQL
            # update_table_from_csv(file_name, file_path)
            print(f"Airspace CSV created: {file_path}")
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=file_path)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )

    if args.e or not (
        check_all_args(
            args.b,
            args.f,
            args.d,
            args.t,
            args.c,
            args.e,
            args.g,
            args.n,
            args.r,
        )
    ):
        # step -e
        arg = "e"
        try:
            print("step (-", arg, ") start ", datetime.now())
            dir = create_content_dir(arg)

            # Include geometry (polygons) in SUA data - returnGeometry=true
            url = "https://services6.arcgis.com/ssFJjBXIUyZDrSYZ/arcgis/rest/services/Special_Use_Airspace/FeatureServer/0/query?where=1%3D1&outFields=NAME,TYPE_CODE,UPPER_VAL,UPPER_UOM,LOWER_VAL,LOWER_UOM,CITY,TIMESOFUSE&returnGeometry=true&outSR=4326&f=json"

            file_path = create_sua(url, geometry=True)

            file = os.path.join(dir, "e.csv.gz")
            df = pd.read_json(file_path, orient='records')
            df.to_csv(file, index=False, quoting=csv.QUOTE_MINIMAL, quotechar='"')
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=file)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )

    if args.g or not (
        check_all_args(
            args.b,
            args.f,
            args.d,
            args.t,
            args.c,
            args.e,
            args.g,
            args.n,
            args.r,
        )
    ):
        # step -g
        arg = "g"
        try:
            print("step (-", arg, ") start ", datetime.now())
            dir = create_content_dir(arg)

            url = "https://services6.arcgis.com/ssFJjBXIUyZDrSYZ/arcgis/rest/services/Stadiums/FeatureServer/0/query?where=1%3D1&outFields=NAME,CITY,STATE&returnGeometry=true&outSR=4326&f=json"

            file_path = create_sua(url, True)

            file = os.path.join(dir, "g.csv.gz")
            df = pd.read_json(file_path)

            # Explicitly include the newly mapped coordinate columns
            columns_to_export = ["NAME", "CITY", "STATE", "LONG", "LAT"]
            existing_cols = [c for c in columns_to_export if c in df.columns]
            df = df[existing_cols]

            df.to_csv(file, index=False)
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=file)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )





    if args.n or not (
        check_all_args(
            args.b,
            args.f,
            args.d,
            args.t,
            args.c,
            args.e,
            args.g,
            args.n,
            args.r,
        )
    ):
        # step -n
        arg = "n"
        try:
            print("step (-", arg, ") start ", datetime.now())
            file_to_extract = "NAV_BASE.csv"
            file_name_of_extracted_file = extract_file_from_nested_zip(
                file_name_of_28dayNASR_zip,
                path_to_file_to_extract,
                file_to_extract,
                download_dir,
            )

            dir = create_content_dir(arg)
            file_path = os.path.join(dir, "n.csv.gz")
            create_nav_file(file_name_of_extracted_file, file_path)
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=file_path)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )

    if args.r or not (
        check_all_args(
            args.b,
            args.f,
            args.d,
            args.t,
            args.c,
            args.e,
            args.g,
            args.n,
            args.r,
        )
    ):
        # step -r
        arg = "r"
        try:
            print("step (-", arg, ") start ", datetime.now())
            file_to_extract = "APT_RWY_END.csv"
            file_name_of_extracted_file = extract_file_from_nested_zip(
                file_name_of_28dayNASR_zip,
                path_to_file_to_extract,
                file_to_extract,
                download_dir,
            )
            dir = create_content_dir(arg)
            file_path = os.path.join(dir, "r.csv.gz")
            create_rwy_end(file_name_of_extracted_file, file_path)
            print("step (-", arg, ") finish ", datetime.now())
            commit_changes(arg, output_file_path=file_path)
        except Exception as e:
            logger.exception("Error during step (-%s): %s", arg, e)
            send_telegram_alert(
                f"🚨 <b>Scraper Error</b>\n"
                f"<b>Flag:</b> -{arg}\n"
                f"<b>Error:</b> <code>{e}</code>"
            )

    # ---------------------------
    # Cleanup old downloaded files
    # ---------------------------
    logger.info("Starting cleanup of old files in %s", download_dir)
    cleanup_old_files(download_dir, extension=".zip", keep_count=2)
    cleanup_old_files(download_dir, extension=".shp.zip", keep_count=5)

    return


if __name__ == "__main__":
    main()
    # files_date_list = [
    #     [
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_9417.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_8064.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_7707.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_1327.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_5389.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_6232.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_5568.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_5434.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_6042.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_6669.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_6206.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_6443.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_5561.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_6240.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_2903.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_9433.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_8063.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_6193.shp.zip",
    #         "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data/4_4803.shp.zip",
    #         ...,
    #     ],
    #     [
    #         "From June 01, 2024 at 0359 UTC to June 01, 2025 at 0359 UTC",
    #         "From November 03, 2024 UTC 1000-1200 Tuesday, Thursday, Saturday to March 09, 2025 UTC",
    #         "From May 21, 2024 at 2359 UTC to May 22, 2025 at 0001 UTC",
    #         "From June 02, 2024 at 0000 UTC to December 31, 2024 at 2359 UTC",
    #         "From November 23, 2024 at 0045 UTC to November 23, 2024 at 0600 UTC",
    #         "From November 22, 2024 at 1430 UTC to November 22, 2024 at 2230 UTC",
    #         "From November 21, 2024 at 1543 UTC to November 21, 2024 at 2024 UTC",
    #         "From November 23, 2024 at 0130 UTC to November 23, 2024 at 0759 UTC",
    #         "From November 24, 2024 at 0000 UTC to November 24, 2024 at 0500 UTC",
    #         "From November 24, 2024 at 0300 UTC to November 24, 2024 at 0730 UTC",
    #         "From November 20, 2024 at 1730 UTC to November 20, 2024 at 1930 UTC",
    #         "",
    #         "From July 22, 2024 at 1600 UTC to December 31, 2024 at 2359 UTC",
    #         "From November 24, 2024 at 1430 UTC to November 24, 2024 at 2230 UTC",
    #         "From January 11, 2024 at 1800 UTC to December 20, 2024 at 2200 UTC",
    #         "From Effective Immediately to Permanent",
    #         "From November 03, 2024 at 0201 UTC to March 09, 2025 at 0300 UTC",
    #         "From November 20, 2024 UTC 1100-2200 Daily to November 22, 2024 UTC",
    #         "From November 21, 2024 at 0045 UTC to November 21, 2024 at 0600 UTC",
    #         ...,
    #     ],
    # ]
    # convert_shp_to_csv(
    #     files_date_list,
    #     "/home/kostiantyn/projects/aviation-navigation-server/downloaded_data",
    #     "/home/kostiantyn/projects/aviation-navigation-server/output/2024.11.24-t-content/",
    # )
