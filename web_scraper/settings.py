from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = BASE_DIR / "downloaded_data"
OUTPUT_DIR = BASE_DIR / "data"
AIRPORTS_FILE = os.path.join(BASE_DIR, "processed_data/arpts_dict.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36"
}
BASE_AIRPORT_URL = "https://airnav.com/airport/"
DATA_LINK = (
    "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/"
)
TOLERANCE = 0.005
SHAPE_FILE_PATH = "Additional_Data/Shape_Files/Class_Airspace.shp"
CHANGES_FILE = BASE_DIR / "data" / "changes.json"
TFR_FILES_URL = "https://tfr.faa.gov/tfr2/list.html"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
print(BASE_DIR, "\n", DOWNLOAD_DIR, "\n", OUTPUT_DIR, "\n")
