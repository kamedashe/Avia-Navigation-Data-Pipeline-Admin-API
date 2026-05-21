from typing import List
import csv
import re
from datetime import datetime
from tqdm import tqdm
import pandas as pd

# Increase CSV field size limit for large geometry fields
csv.field_size_limit(10 * 1024 * 1024)  # 10 MB


# CSV handling functions
# ------------------------
def get_value_type(val) -> List[str | int]:
    """Returns the type of the value"""
    try:
        int_val = int(val)
        if int_val < 2147483647:
            return ["INTEGER", 0]
        else:
            return ["BIGINT", 0]
    except ValueError:
        try:
            float(val)
            return ["REAL", 1]
        except ValueError:
            try:
                _ = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return ["TIMESTAMP", 2]
            except ValueError:
                if val.lower() == "true" or val.lower() == "false":
                    return ["BOOLEAN", 3]
                else:
                    return ["TEXT", 4]


def sanitize_column_name(name: str) -> str:
    """Sanitize column name for PostgreSQL - remove special chars, replace spaces"""
    import re
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    # Remove any characters that aren't alphanumeric or underscore
    name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    # Ensure it doesn't start with a number
    if name and name[0].isdigit():
        name = '_' + name
    return name.lower() if name else 'column'


def get_unique_headers(headers: List[str]) -> None:
    """Handles duplicate headers in CSV files after sanitization"""
    # First sanitize all headers
    for i in range(len(headers)):
        headers[i] = sanitize_column_name(headers[i])
    # Then handle duplicates
    seen = {}
    for i in range(len(headers)):
        if headers[i] in seen:
            seen[headers[i]] += 1
            headers[i] = headers[i] + "_" + str(seen[headers[i]])
        else:
            seen[headers[i]] = 0


def get_headers_from_csv(csv_file_path: str, sample_size: int = 1000) -> List[str]:
    """
    Parse CSV headers and determine column types.
    Uses sampling (first sample_size rows) to determine types instead of reading entire file.
    This reduces memory usage and improves performance for large files.
    """
    res = ""
    with open(csv_file_path, "r", encoding="utf-8") as csv_file:
        f = csv.reader(csv_file)
        # Read header row
        headers = next(f)
        get_unique_headers(headers)
        num_cols = len(headers)
        
        # Initialize type tracking for each column: [type_name, priority]
        # Priority: INTEGER=0, REAL=1, TIMESTAMP=2, BOOLEAN=3, TEXT=4
        column_types = [["", -1] for _ in range(num_cols)]
        
        # Sample rows to determine types (single pass through file)
        rows_sampled = 0
        all_text = [False] * num_cols  # Track if column is already determined as TEXT
        
        for row in f:
            if rows_sampled >= sample_size:
                # Check if all columns are determined
                if all(all_text):
                    break
            
            for i in range(min(len(row), num_cols)):
                if all_text[i]:
                    continue  # Skip columns already determined as TEXT
                if row[i]:
                    tmp_value_type = get_value_type(row[i].strip())
                    if column_types[i][1] < tmp_value_type[1]:
                        column_types[i] = tmp_value_type
                    if column_types[i][0] == "TEXT":
                        all_text[i] = True
            
            rows_sampled += 1
        
        # Build result string
        for i in tqdm(range(num_cols)):
            col_name = headers[i]
            col_type = column_types[i][0] if column_types[i][0] else "TEXT"
            res += col_name + " " + col_type + ","

    res = res[: (res.rfind(","))] + res[(res.rfind(",") + 1) :]
    return res


def get_values_list_from_csv(csv_file, column, chunk_size: int = 10000):
    """
    Read a single column from CSV file using chunked reading to reduce memory usage.
    Returns a list of values from the specified column.
    """
    values = []
    for chunk in pd.read_csv(csv_file, usecols=[column], chunksize=chunk_size):
        values.extend(chunk[column].tolist())
    return values


def get_last_fields(input_file, arpt_id):
    with open(input_file, "r", encoding="utf-8") as csv_file3:
        h = csv.reader(csv_file3)
        # values: [CTAF, UNICOM, WX, GROUND, TOWER, TOWER2, CD]
        values = [""] * 7
        wx_freqs = set()  # Use set to store unique WX frequencies
        flag = False
        for row in h:
            if len(row) < 20:
                continue
            if row[7] == arpt_id:  # SERVICED_FACILITY is index 7
                flag = True
                freq_use = row[19]  # FREQ_USE
                freq = row[17].strip()  # FREQ
                if not freq:
                    continue
                if "CTAF" in freq_use:
                    if values[0]:
                        values[0] += " " + freq
                    else:
                        values[0] = freq
                elif "UNICOM" in freq_use:
                    if values[1]:
                        values[1] += " " + freq
                    else:
                        values[1] = freq
                elif "ATIS" in freq_use or "AWOS" in freq_use or "ASOS" in freq_use:
                    wx_freqs.add(freq)  # Add to set for unique values
                elif "GND/P" in freq_use:
                    if values[3]:
                        values[3] += " " + freq
                    else:
                        values[3] = freq
                elif "LCL/P" in freq_use:
                    if values[4]:
                        values[4] += " " + freq
                    else:
                        values[4] = freq
                elif "LCL/S" in freq_use:
                    if values[5]:
                        values[5] += " " + freq
                    else:
                        values[5] = freq
                elif "CD/P" in freq_use:
                    if values[6]:
                        values[6] += " " + freq
                    else:
                        values[6] = freq
            else:
                if flag:
                    break

        # Convert WX frequencies set to string
        values[2] = " ".join(sorted(wx_freqs))

    return values
