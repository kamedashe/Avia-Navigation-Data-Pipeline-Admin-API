import copy
import gzip
import os
import json
import shutil

import pandas as pd
import csv
from tqdm import tqdm
from alive_progress import alive_bar

from .csv_parser import get_values_list_from_csv, get_last_fields
from .pdf_parser import extracting_pdf_info
from .scraper_utils import download_file_from_url
from .settings import DOWNLOAD_DIR


def create_base_file(
    input_file: str,
    input_file2: str,
    input_file3: str,
    input_file4: str,
    input_pdf: str,
    output_file: str,
    base_url: str,
):
    output_fields = [
        "Identifier",
        "City",
        "State",
        "Country",
        "Lat",
        "Long",
        "Elevation",
        "OWNERSHIP_TYPE_CODE",
        "FUEL_TYPES",
        "CTAF",
        "UNICOM",
        "WX",
        "PHONE_NO",
        "GROUND",
        "TOWER",
        "TOWER2",
        "CLEARANCE DELIVERY",
        "RWY_ID_0",
        "TPA_0",
        "Rgt_tfc_0",
        "RWY_LEN_0",
        "RWY_WIDTH_0",
    ]

    output_rows = []

    airport_urls = []

    max_runways = 1

    arpts_list = get_values_list_from_csv(input_file, "ARPT_ID")
    arpts_dict = extracting_pdf_info(input_pdf, arpts_list)

    processed_data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "processed_data")
    os.makedirs(processed_data_dir, exist_ok=True)
    arpts_dict_path = os.path.join(processed_data_dir, "arpts_dict.json")
    f = open(arpts_dict_path, "w")
    json.dump(arpts_dict, f, indent=4)
    f.close()

    # Pre-load FRQ.csv into memory for fast lookup
    print("loading FRQ.csv into memory...")
    frq_data = {}  # {arpt_id: [CTAF, UNICOM, WX, GROUND, TOWER, TOWER2, CD]}
    with open(input_file2, "r", encoding="utf-8") as frq_file:
        frq_reader = csv.reader(frq_file)
        next(frq_reader)  # skip header
        for row in frq_reader:
            if len(row) < 20:
                continue
            arpt_id = row[7]  # SERVICED_FACILITY
            if arpt_id not in frq_data:
                frq_data[arpt_id] = {"CTAF": [], "UNICOM": [], "WX": set(), "GROUND": [], "TOWER": [], "TOWER2": [], "CD": []}
            freq_use = row[19]
            freq = row[17].strip()
            if not freq:
                continue
            if "CTAF" in freq_use:
                frq_data[arpt_id]["CTAF"].append(freq)
            elif "UNICOM" in freq_use:
                frq_data[arpt_id]["UNICOM"].append(freq)
            elif "ATIS" in freq_use or "AWOS" in freq_use or "ASOS" in freq_use:
                frq_data[arpt_id]["WX"].add(freq)
            elif "GND/P" in freq_use:
                frq_data[arpt_id]["GROUND"].append(freq)
            elif "LCL/P" in freq_use:
                frq_data[arpt_id]["TOWER"].append(freq)
            elif "LCL/S" in freq_use:
                frq_data[arpt_id]["TOWER2"].append(freq)
            elif "CD/P" in freq_use:
                frq_data[arpt_id]["CD"].append(freq)

    # Pre-load AWOS.csv into memory for fast lookup
    print("loading AWOS.csv into memory...")
    awos_data = {}  # {arpt_id: phone_no}
    with open(input_file4, "r", encoding="utf-8") as awos_file:
        awos_reader = csv.reader(awos_file)
        next(awos_reader)  # skip header
        for row in awos_reader:
            if len(row) > 20:
                awos_data[row[1]] = row[20].strip()  # ASOS_AWOS_ID -> PHONE_NO

    # Pre-load APT_RWY.csv into memory for fast lookup
    print("loading APT_RWY.csv into memory...")
    rwy_data = {}  # {arpt_id: [[rwy_id, len, width], ...]}
    with open(input_file3, "r", encoding="utf-8") as rwy_file:
        rwy_reader = csv.reader(rwy_file)
        next(rwy_reader)  # skip header
        for row in rwy_reader:
            if len(row) > 9:
                arpt_id = row[4]
                if arpt_id not in rwy_data:
                    rwy_data[arpt_id] = []
                rwy_data[arpt_id].append([row[7], row[8], row[9]])

    print("creating  base_file.csv ...")
    with open(input_file, "r", encoding="utf-8") as csv_file:
        f = csv.reader(csv_file)
        row_count = sum(1 for row in f)
        csv_file.seek(0)
        skip_first = True
        with alive_bar(row_count) as bar:
            for row in f:
                if skip_first:
                    skip_first = False
                    bar()
                    continue

                airport_url = base_url + row[4]
                airport_urls.append(airport_url)
                
                # Get frequency data from pre-loaded FRQ data
                arpt_id = row[4]
                if arpt_id in frq_data:
                    fd = frq_data[arpt_id]
                    freq_fields = [
                        " ".join(fd["CTAF"]),
                        " ".join(fd["UNICOM"]),
                        " ".join(sorted(fd["WX"])),
                    ]
                    freq_fields_after_phone = [
                        " ".join(fd["GROUND"]),
                        " ".join(fd["TOWER"]),
                        " ".join(fd["TOWER2"]),
                        " ".join(fd["CD"]),
                    ]
                else:
                    freq_fields = [""] * 3
                    freq_fields_after_phone = [""] * 4

                # Get runway data from pre-loaded RWY data
                rwy_list = rwy_data.get(arpt_id, [])
                count_runways = min(len(rwy_list), 10)
                if count_runways > max_runways:
                    max_runways = count_runways

                # Identifier, City, State, Country, Lat, Long, Elevation, OWNERSHIP_TYPE_CODE, FUEL_TYPES
                output_row = [row[4], row[5], row[3], row[6], row[19], row[24], row[26], row[13], row[64]]
                output_row.extend(freq_fields)  # CTAF, UNICOM, WX

                # Add PHONE_NO from pre-loaded AWOS data (right after WX)
                phone_no = awos_data.get(arpt_id, "")
                output_row.append(phone_no)
                
                # Add remaining frequency fields (GROUND, TOWER, TOWER2, CD)
                output_row.extend(freq_fields_after_phone)

                # Add runway data with TPA and Rgt_tfc from PDF
                for rwy_info in rwy_list[:10]:  # Limit to 10 runways
                    rwy_id_str = rwy_info[0]
                    rwy_len = rwy_info[1]
                    rwy_width = rwy_info[2]
                    rgt = ""
                    tpa = ""
                    if arpts_dict.get(arpt_id, 0):
                        rwy_id_parts = rwy_id_str.split("/")
                        for rwy in arpts_dict[arpt_id]:
                            pdf_rwy_parts = rwy.replace("-", "/").split("/")
                            if any(part in rwy_id_parts for part in pdf_rwy_parts) or rwy == rwy_id_parts[0] or rwy == rwy_id_parts[-1]:
                                r_val = arpts_dict[arpt_id][rwy].get("Rgt", "")
                                t_val = arpts_dict[arpt_id][rwy].get("TPA", "")
                                if r_val == "R":
                                    rgt = rwy + "R" if rwy[-1] != "R" else rwy
                                if t_val:
                                    tpa = t_val
                    output_row.extend([rwy_id_str, tpa, rgt, rwy_len, rwy_width])

                output_rows.append(copy.copy(output_row))
                bar()

    if max_runways > 10:
        max_runways = 10

    for i in range(1, max_runways + 1):
        output_fields.extend(
            [
                "RWY_ID_" + str(i),
                "TPA_" + str(i),
                "Rgt_tfc_" + str(i),
                "RWY_LEN_" + str(i),
                "RWY_WIDTH_" + str(i),
            ]
        )

    for row in output_rows:
        if len(row) < len(output_fields):
            row.extend([""] * (len(output_fields) - len(row)))

    with gzip.open(output_file, "wt", encoding="utf-8", newline="") as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(output_fields)
        csvwriter.writerows(output_rows)

    return airport_urls


def create_waypoint_file(input_file: str, output_file: str) -> None:
    print("creating  waypoint file.csv ...")
    output_fields = [
        "FIX_ID",
        "STATE_CODE",
        "COUNTRY_CODE",
        "LAT_DECIMAL",
        "LONG_DECIMAL",
        "FIX_USE_CODE",
    ]

    output_rows = []

    with open(input_file, "r", encoding="utf-8") as csv_file:
        f = csv.reader(csv_file)
        row_count = sum(1 for row in f)
        csv_file.seek(0)
        with alive_bar(row_count) as bar:
            for row in f:
                if row[17].strip() == "RP" or row[17].strip() == "VFR":
                    output_rows.append(
                        [row[1], row[3], row[4], row[9], row[14], row[17].strip()]
                    )
                bar()

    del output_rows[0]

    with gzip.open(output_file, "wt", encoding="utf-8", newline="") as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(output_fields)
        csvwriter.writerows(output_rows)


def create_nav_file(input_file: str, output_file: str) -> None:
    print("creating  nav.csv ...")
    output_fields = [
        "NAV_ID",
        "NAV_TYPE",
        "STATE_CODE",
        "CITY",
        "LAT_DECIMAL",
        "LONG_DECIMAL",
        "FREQ",
    ]

    output_rows = []

    with open(input_file, "r", encoding="utf-8") as csv_file:
        f = csv.reader(csv_file)
        row_count = sum(1 for row in f)
        csv_file.seek(0)
        with alive_bar(row_count) as bar:
            for row in f:
                output_rows.append(
                    [row[1], row[2], row[3], row[4], row[26], row[31], row[54]]
                )
                bar()

    del output_rows[0]

    with gzip.open(output_file, "wt", encoding="utf-8", newline="") as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(output_fields)
        csvwriter.writerows(output_rows)


def create_rwy_end(input_file: str, output_file: str) -> None:
    print("creating  RWY_END.csv ...")
    output_fields = [
        "ARPT_ID",
        "RWY_ID",
        "LAT_DECIMAL",
        "LONG_DECIMAL",
        "LAT_DECIMAL_END",
        "LONG_DECIMAL_END",
    ]

    output_rows = []

    with open(input_file, "r", encoding="utf-8", errors="replace") as csv_file:
        # Count lines directly to avoid csv.Error during sum()
        row_count = sum(1 for _ in csv_file)

    with open(input_file, "r", encoding="utf-8", errors="replace") as csv_file:
        f = csv.reader(csv_file)
        with alive_bar(row_count) as bar:
            while True:
                try:
                    row = next(f)
                except StopIteration:
                    break
                except Exception:
                    # Ignore tokenizer errors mapped to bad formatting/dirty commas
                    bar()
                    continue

                try:
                    if len(row) <= 23:
                        bar()
                        continue
                    if (
                        output_rows
                        and row[4] == output_rows[-1][0]
                        and row[7] == output_rows[-1][1]
                    ):
                        output_rows[-1][-2] = row[18]
                        output_rows[-1][-1] = row[23]
                        bar()
                        continue
                    output_rows.append([row[4], row[7], row[18], row[23], "", ""])
                    bar()
                except Exception:
                    # Ignore index errors if row is malformed
                    bar()
                    continue

    if output_rows:
        del output_rows[0]

    with gzip.open(output_file, "wt", encoding="utf-8", newline="") as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(output_fields)
        csvwriter.writerows(output_rows)


def create_daily_obstacle_file(input_file: str, output_file: str) -> None:
    print("creating  DDOF_file.csv ...")

    output_fields = ["COUNTRY", "STATE", "CITY", "LATDEC", "LONDEC", "TYPE", "AMSL"]

    # Try different encodings
    encodings = ['latin-1', 'cp1252', 'iso-8859-1', 'utf-8']
    working_encoding = None
    
    for encoding in encodings:
        try:
            with open(input_file, "r", encoding=encoding) as test_file:
                # Test if we can read the entire file
                for _ in test_file:
                    pass
            working_encoding = encoding
            print(f"Using encoding: {encoding}")
            break
        except UnicodeDecodeError:
            continue
    
    if working_encoding is None:
        raise Exception("Could not determine file encoding")
    
    # Count rows first
    with open(input_file, "r", encoding=working_encoding) as csv_file:
        row_count = sum(1 for _ in csv_file)
    
    # Process rows and write directly to output file
    with open(input_file, "r", encoding=working_encoding) as csv_file:
        with gzip.open(output_file, "wt", encoding="utf-8", newline="") as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(output_fields)
            
            f = csv.reader(csv_file)
            skip_header = True
            with alive_bar(row_count) as bar:
                for row in f:
                    if skip_header:
                        skip_header = False
                        bar()
                        continue
                    if len(row) > 12:
                        agl_str = row[11].strip()
                        try:
                            if agl_str and float(agl_str) < 300:
                                bar()
                                continue
                        except ValueError:
                            pass
                            
                        csvwriter.writerow([
                            row[2].strip(),
                            row[3].strip(),
                            row[4].strip(),
                            row[5].strip(),
                            row[6].strip(),
                            row[9].strip(),
                            row[12].strip(),
                        ])
                    bar()


def create_obstacle_file(input_files: str, input_dir: str, output_file: str) -> None:
    print("processing .DAT files ...")

    # Define the column widths based on the observed pattern
    column_widths = [
        10,  # OAS#
        2,  # V
        3,  # CO
        3,  # ST
        17,  # CITY
        3,  # LATITUDE DEG
        3,  # LATITUDE MIN
        7,  # LATITUDE SEC
        4,  # LONGITUDE DEG
        3,  # LONGITUDE MIN
        7,  # LONGITUDE SEC
        19,  # OBSTACLE TYPE
        2,  #
        6,  # AGL HT
        6,  # AMSL HT
    ]

    # Define the column names based on the header
    column_names = [
        "OAS#",
        "V",
        "COUNTRY",
        "STATE",
        "CITY",
        "LATITUDE DEG",
        "LATITUDE MIN",
        "LATITUDE SEC",
        "LONGITUDE DEG",
        "LONGITUDE MIN",
        "LONGITUDE SEC",
        "OBSTACLE TYPE",
        "0",
        "AGL HT",
        "AMSL",
    ]

    data = []
    for input_file in tqdm(input_files):
        if input_file.find(".Dat") == -1:
            continue
        
        # Try different encodings for .DAT files
        file_path = os.path.join(input_dir, input_file)
        encodings = ['latin-1', 'cp1252', 'iso-8859-1', 'utf-8']
        lines = None
        
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as file:
                    lines = file.readlines()
                break
            except UnicodeDecodeError:
                continue
        
        if lines is None:
            print(f"Warning: Could not read {input_file} with any encoding, skipping")
            continue

        # Skip the first few lines and extract the data part
        data_lines = lines[4:]

        # Parse the data using fixed column widths
        for line in data_lines:
            row = []
            start = 0
            for width in column_widths:
                end = start + width
                row.append(line[start:end].strip())
                start = end
            data.append(row)

    # Create a DataFrame
    df = pd.DataFrame(data, columns=column_names)

    lat_dec = []
    long_dec = []

    print("creating  obstacle file.csv ...")
    with alive_bar(len(data)) as bar:
        for index, row in df.iterrows():
            dec = (
                float(row["LATITUDE DEG"])
                + float(row["LATITUDE MIN"]) / 60
                + float(row["LATITUDE SEC"][:-1]) / 3600
            )
            if row["LATITUDE SEC"][-1] == "S":
                dec = -dec
            lat_dec.append(round(dec, 6))
            dec = (
                float(row["LONGITUDE DEG"])
                + float(row["LONGITUDE MIN"]) / 60
                + float(row["LONGITUDE SEC"][:-1]) / 3600
            )
            if row["LONGITUDE SEC"][-1] == "W":
                dec = -dec
            long_dec.append(round(dec, 6))
            bar()

    df.insert(5, "LATDEC", lat_dec)
    df.insert(6, "LONGDEC", long_dec)

    columns = [
        "OAS#",
        "V",
        "LATITUDE DEG",
        "LATITUDE MIN",
        "LATITUDE SEC",
        "LONGITUDE DEG",
        "LONGITUDE MIN",
        "LONGITUDE SEC",
        "0",
        "AGL HT",
    ]
    df.drop(columns, inplace=True, axis=1)
    df.to_csv(output_file, index=False)


def create_wx_file(url, output_file, base_file):
    """
    Create weather file from METAR data.
    Optimized to:
    1. Use line-by-line iteration instead of readlines() to reduce memory
    2. Pre-load base_file into dict for O(1) lookup instead of O(n*m) nested loop
    3. Write output incrementally instead of accumulating all rows in memory
    """
    metar_gz, _ = download_file_from_url(url, DOWNLOAD_DIR, check_existing=False)
    print("creating  wx_file.csv ...")
    with gzip.open(metar_gz, "rb") as f_in:
        with open(metar_gz[:-3], "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    # Write initial wx_file skipping first 5 lines (use line iteration, not readlines)
    with open(metar_gz[:-3], "r") as f_in:
        with gzip.open(output_file, "wt", encoding="utf-8") as f_out:
            for i, line in enumerate(tqdm(f_in, desc="Writing wx_file")):
                if i < 5:
                    continue
                f_out.write(line)

    # Pre-load base_file into dict for O(1) lookup (arpt_id -> city)
    print("loading base_file for city lookup...")
    arpt_city_map = {}
    with open(base_file, "r", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        next(reader)  # skip header
        for row in reader:
            if len(row) > 5:
                arpt_city_map[row[4]] = row[5]  # Identifier -> City

    print("processing wx_file.csv ...")
    # Count rows for progress bar
    with open(output_file, "r", encoding="utf-8") as csv_file:
        row_count = sum(1 for _ in csv_file)
    
    # Process and write output incrementally
    temp_output = output_file + ".tmp"
    with open(output_file, "r", encoding="utf-8") as csv_file:
        f = csv.reader(csv_file)
        with gzip.open(temp_output, "wt", encoding="utf-8", newline="") as out_file:
            csvwriter = csv.writer(out_file)
            skip_first = True
            with alive_bar(row_count) as bar:
                for row in f:
                    res_row = list(row)  # Make a copy
                    res_row.insert(2, "")
                    if skip_first:
                        res_row[2] = "city"
                        skip_first = False
                    else:
                        if len(row) > 1 and row[1] and row[1][0] == "K":
                            arpt_id = row[1][1:]
                            res_row[2] = arpt_city_map.get(arpt_id, "")
                    csvwriter.writerow(res_row)
                    bar()
    
    # Replace original with temp file
    os.replace(temp_output, output_file)
