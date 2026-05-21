import urllib.request
import requests
import os
from bs4 import BeautifulSoup
from datetime import datetime
import time
from tqdm import tqdm
import shutil
import gzip
import json
import calendar
import zipfile
import psycopg2
import csv
from threading import Thread

def get_today_date_str(dm1='', dm2='', d=True, t=True):
    if d and not(t):
        return datetime.now().strftime('%Y'+dm1+'%m'+dm1+'%d')
    if t and not(d):
        return datetime.now().strftime('%H'+dm2+'%M'+dm2+'%S')
    return datetime.now().strftime('%Y'+dm1+'%m'+dm1+'%d' + '_' + '%H'+dm2+'%M'+dm2+'%S')

base_dir = '/home/mb/script/auto/'
download_dir = '/home/mb/script/downloaded_data/'    #+download_data_' + get_today_date_str('.') + '/'
os.makedirs(download_dir, exist_ok=True)
output_dir = '/home/mb/processed_data/'
os.makedirs(output_dir, exist_ok=True)

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36'}

data_link = 'https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/'

f = open(os.path.join(base_dir[:(base_dir.rfind('/', 0, -2)+1)], 'db_config.json'))
db_params = json.load(f)
f.close()

def create_content_dir(arg):
    dir = os.path.join(output_dir, get_today_date_str(dm1='.',t=False) + arg + '-content/')
    os.makedirs(dir, exist_ok=True)
    return dir

def commit_changes(arg, file_name='changes.json'):
    try:
        f = open(file_name)
        changes = json.load(f)
        f.close()
    except:
        changes = {
            'b': 0,
            'f': 0,
            'o': 0,
            'd': 0,
            'w': 0,
            't': 0,
            's': 0,
            'm': 0,
            'n': 0,
            'r': 0,
        }
    finally:
        changes[arg] = int(time.time())    
        f = open(file_name, 'w')
        json.dump(changes, f, indent = 4)
        f.close()


def find_file(file_name, root_dir='.'):
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if file_name in filenames:
            return os.path.join(dirpath, file_name)
    return False

def download_file_from_url(url, filename='', check_existing=True):
    filename += url[(url.rfind('/')+1):]
    print('downloading ' +  filename + ' ...')
    if not(check_existing) or not(os.path.isfile(filename)):
        for i in tqdm(range(1)):
            while True:
                try:
                    urllib.request.urlretrieve(url, filename)
                    break
                except:
                    time.sleep(10)
                    continue
    else:
        print('file already exists!')

    return filename


def get_value_type(val):
    try:
        int(val)
        if val < 2147483647:
            return ['INTEGER', 0]
        else:
            return ['BIGINT', 0]
    except:
        try:
            float(val)
            return ['REAL', 1]
        except:
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return ['TIMESTAMP', 2]
            except:
                if val.lower() == 'true' or val.lower() == 'false':
                    return ['BOOLEAN', 3]
                else:
                    return ['TEXT', 4]
                
def get_unique_headers(headers):
    for i in range(len(headers)):
        count = 0
        for j in range(i+1, len(headers)):
            if headers[i] == headers[j]:
                count += 1
                headers[j] += '_' + str(count)



def create_table_from_csv(table_name, csv_file_path):
    res = f"CREATE TABLE {table_name} ("
    with open(csv_file_path, 'r', encoding="utf-8") as csv_file:
        f = csv.reader(csv_file)
        for row in f:
            headers = row
            break
        get_unique_headers(headers)
        for i in tqdm(range(len(headers))):
            res += headers[i] + ' '
            csv_file.seek(0)
            value_type = ['', -1]
            skip_first = True
            for row in f:
                if skip_first:
                    skip_first = False
                    continue
                if row[i]:
                    tmp_value_type = get_value_type(row[i].strip())
                    if value_type[1] < tmp_value_type[1]:
                        value_type = tmp_value_type
                if value_type[0] == 'TEXT':
                    break
            if not(value_type[0]):
                value_type[0] = 'TEXT'
            res += value_type[0] + ','

    res = res[:(res.rfind(','))] + res[(res.rfind(',')+1):] + ");"
    #print(res)
    return res



def equal_columns(input_file):
    with open(input_file, 'r') as infile:
        reader = csv.reader(infile)
        
        # Read all rows and find the longest row
        rows = list(reader)
        max_columns = max(len(row) for row in rows)
        
        # Adjust headers to match the longest row
        headers = rows[0]
        if len(headers) < max_columns:
            headers.extend(f"extra_col_{i+1}" for i in range(len(headers), max_columns))
        
    # Write updated CSV to the output file
    with open(input_file, 'w', newline='') as outfile:
        writer = csv.writer(outfile)
        writer.writerow(headers)  # Write adjusted headers
        writer.writerows(rows[1:])  # Write the rest of the data



def update_table_from_csv(table_name, csv_file_path, column_config=''):
    print('addding content to the database ...')
    while True:
        try:
            conn = psycopg2.connect(**db_params)
            break
        except:
            time.sleep(5)

    cur = conn.cursor()
    conn.autocommit = True

    try:
        cur.execute("""SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = 'postgres'
                AND state = 'idle in transaction'
                AND pid <> pg_backend_pid();
                """)
    except Exception as e:
        print(e)
        conn.commit()
    finally:
        try:
            cur.execute(f"DROP TABLE IF EXISTS {table_name};")
        except Exception as e:
            print(e)
            conn.commit()
        finally:
            try:
                equal_columns(csv_file_path)
                exec_str = create_table_from_csv(table_name, csv_file_path)
                #print('HERE IS EXEC STR', exec_str)
                cur.execute(exec_str)
            except Exception as e:
                print(e)
                conn.commit()
            finally:
                try:
                    #cur.execute(f"COPY {table_name} FROM '{csv_file_path}' WITH CSV HEADER NULL '';")
                    with open(csv_file_path, 'r') as f:
                        cur.copy_expert(f"COPY {table_name} FROM STDIN WITH CSV HEADER NULL ''", f)
                    if conn:
                        conn.commit()
                        cur.close()
                        conn.close()
                except Exception as e:
                    print(e)
                    cur.close()
                    conn.close()



def get_links(url, condition=''):
    # Fetch the HTML content of the page
    print('fetching links ...')
    while True:
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status() 
            break
        except Exception as e:
            print(e)
            #print('bad response')
            time.sleep(10)
            continue

    # Parse the HTML content
    soup = BeautifulSoup(response.text, 'html.parser')

    # Find all links that end with .TXT
    #links = [url + a['href'] for a in soup.find_all('a', href=True) if a['href'].endswith('.TXT')]
    all_links = soup.find_all('a', href=True)

    links = [a['href'] for a in tqdm(all_links) if condition in a['href']]

    return links
    

def create_wx_file(url, output_file, base_file):
    metar_gz = download_file_from_url(url, download_dir, check_existing=False)
    print('creating  wx_file.csv ...')
    with gzip.open(metar_gz, 'rb') as f_in:
        with open(metar_gz[:-3], 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    f = open(metar_gz[:-3], 'r')
    g = open(output_file, 'w')
    f_lines = f.readlines()
    i = 0
    for line in tqdm(f_lines):
        if i < 5:
            i += 1
            continue
        g.write(line)
    f.close()
    g.close()

    print('processing wx_file.csv ...')
    output_rows = []
    with open(output_file, 'r', encoding="utf-8") as csv_file:
        f = csv.reader(csv_file)
        row_count = sum(1 for row in f)
        csv_file.seek(0)
        skip_first = True
        for row in f:
            res_row = row
            res_row.insert(2, '')
            if skip_first:
                skip_first = False
            else:
                if row[1][0] == 'K':
                    with open(base_file, 'r', encoding="utf-8") as csv_file2:
                        g = csv.reader(csv_file2)
                        for row2 in g:
                            if row2[4] == row[1][1:]:
                                res_row[2] = row2[5]
                                break
            output_rows.append(res_row)

    output_rows[0][2] = 'city'

    with open(output_file, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerows(output_rows)


def delete_previous_content(arg):
    content_dirs = os.listdir(output_dir)
    dirs = []
    for dir in content_dirs:
        if len(dir) > 10 and dir[10] == arg:
            dirs.append(dir)

    for i in range(len(dirs)-1):
        shutil.rmtree(os.path.join(output_dir, dirs[i]))

    last_dir = os.path.join(output_dir, dirs[-1])
    files = os.listdir(os.path.join(last_dir))
    for i in range(len(files)-1):
        os.remove(os.path.join(last_dir, files[i]))

def get_link_to_current_data(url, file):
    current = get_links(url, '/NASR_Subscription/')
    #data = get_links(url + current[-1][-10:], file)
    #return data[0]
    return 'https://nfdc.faa.gov/webContent/28DaySub/28DaySubscription_Effective_' + current[-1][(current[-1].rfind('/')+1):] + '.zip'


def get_name_of_csv_zip(zip_name):
    #16_May_2024_CSV.zip
    day = zip_name[-6:-4]
    month = zip_name[-9:-7]
    year = zip_name[-14:-10]
    return day + '_' + str(calendar.month_name[int(month)])[:3] + '_' + year + '_CSV.zip'


def extract_file_from_nested_zip(outer_zip_path, inner_zip_name, file_to_extract, output_dir):
    # Step 1: Open the outer zip file
    print('extracting ' + file_to_extract + ' ...')
    for i in tqdm(range(1)):
        with zipfile.ZipFile(outer_zip_path, 'r') as outer_zip:
            # Step 2: Open the inner zip file directly from the outer zip
            with outer_zip.open(inner_zip_name) as inner_zip_file:
                with zipfile.ZipFile(inner_zip_file) as inner_zip:
                    # Step 3: Extract the specific file from the inner zip
                    with inner_zip.open(file_to_extract) as target_file:                  
                        # Write the contents to the output file
                        output_file_path = os.path.join(output_dir, file_to_extract)
                        with open(output_file_path, 'wb') as output_file:
                            output_file.write(target_file.read())
    return output_file_path
    

def get_zip_file(name):
    files = os.listdir(download_dir)
    zip_files = []
    for f in files:
        if name in f:
            zip_files.append(f)
    if zip_files:
        return os.path.join(download_dir, zip_files[-1])
    return False


def step_w():
    file_name_of_28dayNASR_zip = get_zip_file('28DaySubscription_Effective')
    if not file_name_of_28dayNASR_zip:
        print('\nstep 0 (downloading 28dayNASR_zip) start ', datetime.now())
        #file_name_of_28dayNASR_zip = download_28dayNASR_zip('https://nfdc.faa.gov/webContent/28DaySub/28DaySubscription_Effective_')
        #file_name_of_28dayNASR_zip = "downloaded_data/28DaySubscription_Effective_2024-10-31.zip"
        #"""
        file_name_of_28dayNASR_zip = download_file_from_url(
                get_link_to_current_data(data_link, '/28DaySub/28DaySubscription_Effective_'),
                download_dir
                )#"""
        print('step 0 (downloading 28dayNASR_zip) finish ', datetime.now())
    path_to_file_to_extract = 'CSV_Data/' + get_name_of_csv_zip(file_name_of_28dayNASR_zip)
    
    # step -w
    arg = 'w'
    print('step (-', arg, ') start ', datetime.now())
    delete_previous_content(arg)
    dir = create_content_dir(arg)
    file_name = 'wx_file'
    file_path = os.path.join(dir, file_name + '_' + get_today_date_str(d=False) + '.csv')    
    file_to_extract = 'APT_BASE.csv'
    file_name_of_extracted_file = extract_file_from_nested_zip(file_name_of_28dayNASR_zip,
                                                                path_to_file_to_extract,
                                                                file_to_extract,
                                                                download_dir)
    create_wx_file(
        "https://aviationweather.gov/data/cache/metars.cache.csv.gz",
        file_path,
        file_name_of_extracted_file
        )
    update_table_from_csv(file_name, file_path)
    print('step (-', arg, ') finish ', datetime.now())
    commit_changes(arg, '/home/mb/script/changes.json')


def check_mutex(file_name):
    try:
        f = open(file_name)
        m = f.read()
        f.close()
    except:
        f = open(file_name, 'w')
        f.write('0')
        f.close()
        return True
    else:
        if int(m):
            f = open(file_name, 'w')
            f.write('0')
            f.close()
            return True
        return False

start_time = datetime.now()
start_t = int(time.time())
finish = True

def program_log():
    while finish:
        f = open(os.path.join(base_dir, 'auto_w.log'), 'w')
        f.write('start ' + str(start_time) + '\nsript is working ' + str(datetime.now()) + '\n')
        f.close()
        time.sleep(10)


def terminate_program():
    global finish
    while finish:
        time.sleep(10)
        if int(time.time()) - start_t > 300:
            f = open(file_name, 'w')
            f.write('1')
            f.close()
            #print('sys exit')
            finish = False
            os._exit(0)


file_name = os.path.join(base_dir, 'mutex.txt')

def main():
    global finish

    thr_program_log = Thread(target = program_log)
    thr_program_log.start()

    thr_terminate_program = Thread(target = terminate_program)
    thr_terminate_program.start()
   
    if check_mutex(file_name):
        try:
            step_w()
        except Exception as e:
            print(e)
        finally:
            f = open(file_name, 'w')
            f.write('1')
            f.close()
    
    finish = False

    return

if __name__ == "__main__":
    main()
