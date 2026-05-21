import os
import sys
from dotenv import load_dotenv
from typing import List

import psycopg2
from psycopg2 import sql

# Add the parent directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_scraper.csv_parser import get_headers_from_csv
from web_scraper.settings import BASE_DIR


# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env")

PGHOST = os.getenv("PGHOST", "localhost")
PGUSER = os.getenv("PGUSER", "postgres")
PGPORT = int(os.getenv("PGPORT", 5432))
PGPASSWORD = os.getenv("PGPASSWORD", "")
PGDATABASE = os.getenv("PGDATABASE", "postgres")


class TableRepository:
    def __init__(self):
        self.connection = psycopg2.connect(
            host=PGHOST or "localhost",
            port=PGPORT or 5432,
            dbname=PGDATABASE,
            user=PGUSER,
            password=PGPASSWORD,
        )
        print("Database connection established")

    def create_table(self, table_name: str, columns: List[str]):
        query = sql.SQL("""
        CREATE TABLE IF NOT EXISTS {table_name} (
            {columns}
        );
        """).format(
            table_name=sql.Identifier(table_name),
            columns=sql.SQL(",\n").join(map(sql.SQL, columns)),
        )
        with self.connection.cursor() as cur:
            cur.execute(query)
            self.connection.commit()

    def drop_table(self, table_name: str):
        query = sql.SQL("DROP TABLE IF EXISTS {table_name};").format(
            table_name=sql.Identifier(table_name)
        )
        with self.connection.cursor() as cur:
            cur.execute(query)
            self.connection.commit()

    def insert_into_table_from_csv(self, table_name: str, csv_file: str):
        query = sql.SQL("""
        COPY {table_name} FROM STDIN WITH CSV HEADER;
        """).format(table_name=sql.Identifier(table_name))
        with self.connection.cursor() as cur:
            with open(csv_file, "r", encoding="utf-8") as f:
                cur.copy_expert(query.as_string(self.connection), f)
            self.connection.commit()

    def close_connection(self):
        if self.connection:
            self.connection.close()
            print("Database connection closed")


def update_table_from_csv(
    table_name: str, csv_file: str, column_config: str = ""
) -> None:
    table_repo = TableRepository()
    try:
        # Drop table if it exists
        table_repo.drop_table(table_name)
        print(f"Table {table_name} dropped")
    except psycopg2.errors.UndefinedTable:
        print(f"Table {table_name} does not exist, will create")
    
    try:
        # Get headers and data types from CSV file
        headers_str = get_headers_from_csv(csv_file)
        # Split string into list of column definitions
        headers = [h.strip() for h in headers_str.split(",") if h.strip()]
        # Create table with headers and data types
        table_repo.create_table(table_name, columns=headers)
        print(f"Table {table_name} created")
    except psycopg2.errors.DuplicateTable:
        print(f"Table {table_name} already exists")
    
    # Insert data into table from CSV file
    table_repo.insert_into_table_from_csv(table_name, csv_file)
    print(f"Data inserted into table {table_name} from {csv_file}")
    table_repo.close_connection()


if __name__ == "__main__":
    # Check connection and create tables
    table_repo = TableRepository()
    table_repo.create_table(
        "airports",
        [
            "icao_code VARCHAR(4) PRIMARY KEY",
            "iata_code VARCHAR(3)",
            "name VARCHAR(255)",
            "city VARCHAR(255)",
            "country VARCHAR(255)",
            "latitude FLOAT",
            "longitude FLOAT",
            "elevation FLOAT",
            "timezone VARCHAR(255)",
        ],
    )
    print("Table airports created")
    table_repo.drop_table("airports")
    print("Table airports dropped")
    table_repo.close_connection()
