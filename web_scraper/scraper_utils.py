import time
import os
import re
import csv
from datetime import datetime

from tqdm import tqdm
from bs4 import BeautifulSoup
import requests
import urllib.request
from alive_progress import alive_bar

from .settings import HEADERS, DOWNLOAD_DIR


def get_links(url, headers=HEADERS, condition=""):
    """Fetch all links from a given URL that end with a specific condition."""
    print("fetching links ...")
    t = 10
    while True:
        try:
            response = requests.get(url, headers)
            response.raise_for_status()
            break
        except Exception as e:
            print(e)
            time.sleep(t)
            t += 10
            continue

    # Parse the HTML content
    soup = BeautifulSoup(response.text, "html.parser")

    # Find all links that end with .TXT
    # links = [url + a['href'] for a in soup.find_all('a', href=True) if a['href'].endswith('.TXT')]
    all_links = soup.find_all("a", href=True)

    # Filter links that contain the condition (works with both partial paths and full URLs)
    links = [a["href"] for a in tqdm(all_links) if condition in a["href"] and not a["href"].startswith('#')]

    return links


def download_tfr_files_wfs(output_path):
    """Download TFR files using FAA WFS API (new method).
    
    Returns list of downloaded shape-zip files and their metadata.
    """
    import xml.etree.ElementTree as ET
    
    print("Fetching TFR list from WFS API...")
    
    # Get all TFR features from WFS
    wfs_url = "http://tfr.faa.gov/geoserver/TFR/ows"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "TFR:V_TFR_LOC",
        "outputFormat": "application/json"
    }
    
    files_list = []
    dates_list = []
    
    try:
        # First try JSON format
        response = requests.get(wfs_url, params=params, headers=HEADERS, timeout=60)
        response.raise_for_status()
        
        try:
            data = response.json()
            features = data.get("features", [])
        except:
            # Fallback to XML parsing
            params["outputFormat"] = "GML2"
            response = requests.get(wfs_url, params=params, headers=HEADERS, timeout=60)
            # Parse XML to extract notam IDs
            features = []
            root = ET.fromstring(response.text)
            for member in root.findall(".//{tfr}V_TFR_LOC"):
                gid = member.attrib.get("{http://www.opengis.net/gml/3.2}id", "")
                if gid:
                    notam_id = gid.replace("V_TFR_LOC.", "")
                    features.append({"id": notam_id})
        
        print(f"Found {len(features)} TFR records")
        
        # Download shape-zip for each TFR
        for feature in tqdm(features, desc="Downloading TFR shapefiles"):
            if isinstance(feature, dict):
                # JSON format
                notam_id = feature.get("id", "").replace("V_TFR_LOC.", "")
                props = feature.get("properties", {})
                title = props.get("TITLE", "")
            else:
                notam_id = feature
                title = ""
            
            if not notam_id:
                continue
                
            # Download shape-zip
            shp_url = f"http://tfr.faa.gov/geoserver/TFR/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=TFR:V_TFR_LOC&featureID=V_TFR_LOC.{notam_id}&outputFormat=shape-zip"
            
            file_name = os.path.join(output_path, f"tfr_{notam_id.replace('/', '_')}.shp.zip")
            
            try:
                r = requests.get(shp_url, headers=HEADERS, timeout=30)
                if r.status_code == 200 and len(r.content) > 100:
                    with open(file_name, 'wb') as f:
                        f.write(r.content)
                    # Validate that the downloaded file is actually a zip
                    import zipfile
                    if zipfile.is_zipfile(file_name):
                        files_list.append(file_name)
                        dates_list.append(title)
                    else:
                        print(f"TFR {notam_id}: downloaded file is not a valid zip, removing")
                        os.remove(file_name)
            except Exception as e:
                print(f"Failed to download TFR {notam_id}: {e}")
                continue
                
    except Exception as e:
        print(f"Error fetching TFR list: {e}")
        
    print(f"Downloaded {len(files_list)} TFR shapefiles")
    return [files_list, dates_list]


def download_tfr_files(url, output_path):
    """Download TFR files (legacy method - kept for compatibility)."""
    links = list(set(get_links(url, condition="save_pages/detail_")))
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
                    except Exception as e:
                        print(e)
                        time.sleep(10)
                        continue
                break

        if flag:
            flag = False
            continue

    return [files_list, dates_list]


def get_link_to_current_data(url, file):
    """Get link to current 28 Day NASR Subscription data."""
    current = get_links(url, "/NASR_Subscription/")
    # Filter only date-formatted links (YYYY-MM-DD)
    date_links = [link for link in current if re.match(r'.*/\d{4}-\d{2}-\d{2}/?$', link)]
    if not date_links:
        raise Exception("No valid NASR subscription links found")
    # Get the latest (last) date link
    latest_link = sorted(date_links)[-1]
    date_str = latest_link.rstrip('/').split('/')[-1]
    # New FAA URL format
    return f"https://nfdc.faa.gov/webContent/28DaySub/28DaySubscription_Effective_{date_str}.zip"


def get_airport_urls(base_url, file_name_of_extracted_file):
    print("getting Airport urls ...")

    airport_urls = []

    with open(file_name_of_extracted_file, "r", encoding="utf-8") as csv_file:
        f = csv.reader(csv_file)
        row_count = sum(1 for row in f)
        csv_file.seek(0)
        with alive_bar(row_count) as bar:
            for row in f:
                airport_url = base_url + row[4]
                airport_urls.append(airport_url)
                bar()

    del airport_urls[0]

    return airport_urls


def download_file_from_url(url, filename="", check_existing=True):
    """Download a file from *url* into directory *filename*.

    Returns:
        tuple: (local_path: str, is_new: bool)
            *is_new* is True when the file was freshly downloaded, False when
            it already existed locally and *check_existing* was True.
    """
    filename = os.path.join(filename, url[(url.rfind("/") + 1) :])
    print("downloading " + filename + " ...")
    is_new = True
    if not (check_existing) or not (os.path.isfile(filename)):
        for i in tqdm(range(1)):
            t = 10
            while True:
                try:
                    res = urllib.request.urlretrieve(url, filename)
                    # Check if file was downloaded successfully
                    if os.path.exists(filename) and os.path.getsize(filename) > 0:
                        break
                except Exception as e:
                    print(e)
                    time.sleep(t)
                    t += 10
                    if t > 60:
                        raise Exception(f"Failed to download {url} after multiple retries")
                    continue
    else:
        print("file already exists!")
        is_new = False

    return filename, is_new


def download_28dayNASR_zip(url):
    flag = 2
    y = datetime.now().year
    m = datetime.now().month
    d = datetime.now().day
    while True:
        try:
            file_name_of_28dayNASR_zip, _ = download_file_from_url(
                url + str(y) + "-" + str(m).zfill(2) + "-" + str(d).zfill(2) + ".zip",
                DOWNLOAD_DIR,
            )
            break
        except Exception as e:
            print(e)
            d -= 1
            if d <= 0:
                d = 31
                m -= 1
                flag -= 1
                if not (flag):
                    break
                if m <= 0:
                    m = 12
                    y -= 1
    if not (flag):
        file_name_of_28dayNASR_zip, _ = download_file_from_url(
            get_link_to_current_data(
                DOWNLOAD_DIR, "/28DaySub/28DaySubscription_Effective_"
            ),
            DOWNLOAD_DIR,
        )
    return file_name_of_28dayNASR_zip
