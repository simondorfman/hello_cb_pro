import csv
from datetime import datetime
import logging
import os
from time import sleep

import public

import psycopg2
import requests

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)

if __name__ == "__main__":

    rest_url = os.getenv("CB_REST_URL")
    product_id = os.getenv("PRODUCT_ID")
    lookback = int(os.getenv("LOOKBACK", 10))
    granularity = int(os.getenv("GRANULARITY", 60))
    host = os.getenv("PG_HOST")
    database = os.getenv("PG_DATABASE")
    user = os.getenv("PG_USER")
    password = os.getenv("PG_PASSWORD")
    port = int(os.getenv("PG_PORT", 25060))

    now = datetime.utcnow()
    data_file_name = f"/tmp/candles_{int(now.timestamp())}.csv"
    with open(data_file_name, "w") as f:
        writer = csv.writer(f, delimiter="|")
        for start_time, end_time in public.yield_batch(now, lookback, granularity):
            logging.info(f"Getting data for interval {start_time} to {end_time}...")
            response = requests.get(
                f"https://api-public.sandbox.pro.coinbase.com/products/{product_id}/candles",
                params={
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat(),
                    "granularity": granularity,
                },
            )
            data = response.json()
            for row in data:
                writer.writerow([product_id] + row + [int(now.timestamp())])

            # sleeping to avoid hitting the rate limit
            sleep(0.1)

    conn = psycopg2.connect(
        host=host, database=database, user=user, password=password, port=port
    )

    logging.info("Creating database objects...")
    with open("/app/sql/create_objects.sql") as f:
        with conn:
            with conn.cursor() as curs:
                curs.execute(f.read())

    logging.info("Copying data to landing...")
    with open(data_file_name) as f:
        with conn:
            with conn.cursor() as curs:
                curs.copy_from(f, "landing.candles", sep="|")

    logging.info("Loading ODS...")
    with open("/app/sql/load_ods_candles.sql") as f:
        with conn:
            with conn.cursor() as curs:
                curs.execute(f.read())

    # leaving contexts doesn't close the connection
    # https://www.psycopg.org/docs/connection.html
    conn.close()
