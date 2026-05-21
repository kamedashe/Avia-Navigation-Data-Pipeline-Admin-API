import os
import time
from typing import Dict, List
import urllib.request
import requests
from tqdm import tqdm

from . import scraper_utils
from .settings import HEADERS


def download_offline_maps(
    url: str, output_path: str, headers: Dict[str, str] = HEADERS
) -> None:
    links = list(set(scraper_utils.get_links(url, headers, condition="/PDFs/")))
    print("downloading Offline maps ...")

    for link in tqdm(links):
        while True:
            try:
                urllib.request.urlretrieve(
                    link, os.path.join(output_path, link[(link.rfind("/") + 1) :])
                )
                break
            except Exception as e:
                print(e)
                time.sleep(10)
                continue


def download_airport_diagrams(
    urls: List[str], output_path: str, headers: Dict[str, str] = HEADERS
) -> None:
    print("downloading Airport diagrams ...")
    for airport_id in tqdm(urls):
        id = airport_id[(airport_id.rfind("/") + 1) :]
        flag = False
        while True:
            try:
                img_url = (
                    "https://www.aopa.org/ustprocs/airportgraphics/gif/tn_"
                    + id
                    + "_tif.gif"
                )
                response = requests.get(img_url, headers)
                response.raise_for_status()
                flag = True
                break
            except Exception as e:
                print(e)
                img_url = (
                    "https://www.aopa.org/ustprocs/airportgraphics/gif/tn_"
                    + id[1:]
                    + "_tif.gif"
                )
                try:
                    response = requests.get(img_url)
                    response.raise_for_status()
                    flag = True
                    break
                except Exception as e:
                    print(e)
                    break
        if flag:
            while True:
                try:
                    img_data = response.content
                    img_name = os.path.join(
                        output_path,
                        airport_id[(airport_id.rfind("/") + 1) :] + "_diagram.png",
                    )
                    with open(img_name, "wb") as handler:
                        handler.write(img_data)
                    break
                except Exception as e:
                    print(e)
                    break
