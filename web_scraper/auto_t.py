import urllib.request
import requests
import os
import sys
from bs4 import BeautifulSoup
from datetime import datetime
import re
import time
from tqdm import tqdm
import shutil
import json
import geopandas as gpd
import zipfile

# Add the parent directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_scraper.shp_optimizer import optimize_shape_trf_file
from web_scraper.settings import (
    DOWNLOAD_DIR,
    OUTPUT_DIR,
    HEADERS,
    TFR_FILES_URL,
)


def get_today_date_str(dm1="", dm2="", d=True, t=True):
    if d and not (t):
        return datetime.now().strftime("%Y" + dm1 + "%m" + dm1 + "%d")
    if t and not (d):
        return datetime.now().strftime("%H" + dm2 + "%M" + dm2 + "%S")
    return datetime.now().strftime(
        "%Y" + dm1 + "%m" + dm1 + "%d" + "_" + "%H" + dm2 + "%M" + dm2 + "%S"
    )


os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def create_content_dir(arg):
    dir = OUTPUT_DIR
    os.makedirs(dir, exist_ok=True)
    return str(dir)


def commit_changes(arg, file_name="changes.json"):
    try:
        f = open(file_name)
        changes = json.load(f)
        f.close()
    except:
        changes = {}
    finally:
        changes[arg] = int(time.time())
        f = open(file_name, "w")
        json.dump(changes, f, indent=4)
        f.close()


def find_file(file_name, root_dir="."):
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if file_name in filenames:
            return os.path.join(dirpath, file_name)
    return False


def download_file_from_url(url, filename="", check_existing=True):
    filename += url[(url.rfind("/") + 1) :]
    print("downloading " + filename + " ...")
    if not (check_existing) or not (os.path.isfile(filename)):
        for i in tqdm(range(1)):
            while True:
                try:
                    urllib.request.urlretrieve(url, filename)
                    break
                except:
                    time.sleep(10)
                    continue
    else:
        print("file already exists!")

    return filename


def get_links(url, condition=""):
    # Fetch the HTML content of the page
    print("fetching links ...")
    while True:
        try:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            break
        except Exception as e:
            print(e)
            # print('bad response')
            time.sleep(10)
            continue

    # Parse the HTML content
    soup = BeautifulSoup(response.text, "html.parser")

    # Find all links that end with .TXT
    # links = [url + a['href'] for a in soup.find_all('a', href=True) if a['href'].endswith('.TXT')]
    all_links = soup.find_all("a", href=True)

    links = [a["href"] for a in tqdm(all_links) if condition in a["href"]]

    return links


def download_tfr_files(url, output_path):
    links = list(set(get_links(url, "save_pages/detail_")))
    print("downloading TFR files ...")
    flag = False
    files_list = []
    dates_list = []
    for link in tqdm(links):
        digits = re.findall(r"\d+", link)
        shp_link = url[:20] + link[3:14] + digits[0] + "_" + digits[1] + ".shp.zip"
        page_link = (
            url[:20] + link[3:14] + "detail_" + digits[0] + "_" + digits[1] + ".html"
        )
        while True:
            try:
                file_name = os.path.join(
                    output_path, shp_link[(shp_link.rfind("/") + 1) :]
                )
                urllib.request.urlretrieve(shp_link, file_name)
                files_list.append(file_name)
                # break
            except Exception as e:
                if e.code == 404:
                    flag = True
                    break
                time.sleep(10)
                continue
            else:
                while True:
                    try:
                        response = requests.get(page_link, headers=HEADERS)
                        response.raise_for_status()
                        soup = BeautifulSoup(response.text, "html.parser")
                        # dates = [font.get_text(strip=True) for font in soup.find_all('font')
                        #         if ('From ' in font.text or 'To ' in font.text or 'to ' in font.text) and 'UTC' in font.text]
                        dates = []
                        for tr in soup.find_all("tr"):
                            cells = tr.find_all("font")
                            if len(cells) > 1:
                                label = cells[0].get_text(strip=True)
                                if "Beginning Date and Time" in label:
                                    dates.append(cells[1].get_text(strip=True))
                                elif "Ending Date and Time" in label:
                                    dates.append(cells[1].get_text(strip=True))
                        date_time = ""
                        count = 0
                        for d in dates:
                            count += 1
                            if count > 2:
                                break
                            if count == 1:
                                date_time += "From " + d
                            else:
                                date_time += " to " + d
                        dates_list.append(date_time)
                        break
                    except:
                        time.sleep(10)
                        continue
                break

        if flag:
            flag = False
            continue

    return [files_list, dates_list]


def delete_previous_content(arg):
    pass


def extract_all_files(path, output_path="", bprint=True):
    if bprint:
        print("extracting  " + path + " ...")
        for i in tqdm(range(1)):
            with zipfile.ZipFile(path, "r") as zip:
                zip.extractall(output_path)
    else:
        with zipfile.ZipFile(path, "r") as zip:
            zip.extractall(output_path)
    return zip.namelist()


def convert_shp_to_csv(files_date_list, download_dir, output_path):
    print("converting shp to csv ...")
    files_list = files_date_list[0]
    for file in tqdm(files_list):
        with zipfile.ZipFile(file, "r") as _zip:
            files = extract_all_files(file, download_dir, False)
            for f in files:
                if f.endswith(".shp"):
                    file_name = os.path.join(download_dir, f)
                    gdf = gpd.read_file(file_name)
                    gdf["EFFECTIVE"] = files_date_list[1][files_list.index(file)]
                    file_path = os.path.join(output_path, "tfr.csv.gz")
                    gdf = optimize_shape_trf_file(gdf, file_path)
                    print(f"GDF head: {gdf.head()}")


def step_t():
    # step -t
    arg = "t"
    print("step (-", arg, ") start ", datetime.now())
    delete_previous_content(arg)
    files_list = download_tfr_files(TFR_FILES_URL, DOWNLOAD_DIR)
    dir = create_content_dir(arg)
    convert_shp_to_csv(files_list, DOWNLOAD_DIR, dir)
    print("step (-", arg, ") finish ", datetime.now())
    commit_changes(arg)


def main():
    step_t()

    return


if __name__ == "__main__":
    main()
