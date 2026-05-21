import calendar
import os

import zipfile
from tqdm import tqdm


def extract_file_from_nested_zip(
    outer_zip_path, inner_zip_name, file_to_extract, output_dir
):
    # Step 1: Open the outer zip file
    print("extracting " + file_to_extract + " ...")
    for i in tqdm(range(1)):
        with zipfile.ZipFile(outer_zip_path, "r") as outer_zip:
            # Step 2: Open the inner zip file directly from the outer zip
            with outer_zip.open(inner_zip_name) as inner_zip_file:
                with zipfile.ZipFile(inner_zip_file) as inner_zip:
                    # Step 3: Extract the specific file from the inner zip
                    with inner_zip.open(file_to_extract) as target_file:
                        # Write the contents to the output file
                        output_file_path = os.path.join(output_dir, file_to_extract)
                        with open(output_file_path, "wb") as output_file:
                            output_file.write(target_file.read())
    return output_file_path


def extract_single_file(path, file_to_extract, output_path):
    print("extracting  " + file_to_extract + " ...")
    for i in tqdm(range(1)):
        with zipfile.ZipFile(path, "r") as zip_file:
            zip_file.extract(file_to_extract, output_path)
    return os.path.join(output_path, file_to_extract)


def extract_all_files(path, output_path="", bprint=True):
    if bprint:
        print("extracting  " + path + " ...")
        for i in tqdm(range(1)):
            with zipfile.ZipFile(path, "r") as zip_file:
                zip_file.extractall(output_path)
    else:
        with zipfile.ZipFile(path, "r") as zip_file:
            zip_file.extractall(output_path)
    return zip_file.namelist()


def get_name_of_csv_zip(zip_name):
    # 16_May_2024_CSV.zip
    day = zip_name[-6:-4]
    month = zip_name[-9:-7]
    year = zip_name[-14:-10]
    return (
        day + "_" + str(calendar.month_name[int(month)])[:3] + "_" + year + "_CSV.zip"
    )
