"""Synthetic data: appends more rows to the existing sources, never changes a column.

Transactions and Time rows are appended to the CSVs in data/raw/; new Customers and Merchants rows are
inserted into the PostgreSQL `source` schema. Sampling mirrors the distributions in the current data;
--anomaly-rate makes a share of the transactions deliberately anomalous so the KPI flags have something to find.

    python pipeline/generate_synthetic.py --rows 50
    python pipeline/generate_synthetic.py --interval 5          # one row every 5 s until Ctrl-C
"""

import argparse
import csv
import re
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from db import get_engine
from ingest import RAW_DIR
ANOMALIES = ["night", "far_location", "high_amount", "high_risk_merchant", "channel_shift"]
FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Vivaan", "Anaya", "Arjun", "Sara"]
LAST = ["Sharma", "Patel", "Iyer", "Khan", "Singh", "Reddy", "Das", "Nair", "Mehta", "Gupta"]
SUFFIX = ["Group", "Traders", "and Sons", "Ltd", "Stores", "Services"]


class Ids:
    """Hands out sequential IDs that continue the existing numbering (e.g. T100 -> T101)."""

    def __init__(self, series, prefix, width):
        self.prefix, self.width = prefix, width
        self.n = int(series.str.extract(r"(\d+)")[0].astype(int).max())

    def next(self):
        self.n += 1
        return f"{self.prefix}{self.n:0{self.width}d}"


def haversine_km(lat1, lon1, lat2, lon2):
    a = np.sin(np.radians(lat2 - lat1) / 2) ** 2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(
        np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(np.minimum(1, a)))


def append_csv_row(path, row):
    """Append one row with a single write so a reader never sees a half-written line."""
    with open(path, newline="") as f:
        header = next(csv.reader(f))
    needs_newline = Path(path).read_bytes()[-1:] not in (b"\n", b"")
    with open(path, "a", newline="") as f:
        if needs_newline:
            f.write("\n")
        f.write(",".join(_quote(row[c]) for c in header) + "\n")


def _quote(value):
    value = str(value)
    return f'"{value}"' if re.search(r'[",\n]', value) else value


def insert_db(engine, table, row):
    cols = ", ".join(row)
    params = ", ".join(f":{c}" for c in row)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO source.{table} ({cols}) VALUES ({params})"), row)


class Generator:
    def __init__(self, engine, rng, anomaly_rate):
        self.engine, self.rng, self.anomaly_rate = engine, rng, anomaly_rate
        self.customers = pd.read_sql("SELECT * FROM source.customers", engine)
        self.merchants = pd.read_sql("SELECT * FROM source.merchants", engine)
        self.locations = pd.read_sql("SELECT * FROM source.locations", engine)
        self.locations[["latitude", "longitude"]] = self.locations[["latitude", "longitude"]].astype(float)
        self.txn = pd.read_csv(RAW_DIR / "Transactions.csv", dtype={"Amount": float})
        self.time = pd.read_csv(RAW_DIR / "Time.csv")

        self.txn_ids = Ids(self.txn["TransactionID"], "T", 3)
        self.time_ids = Ids(self.time["TimeID"], "T", 4)
        self.customer_ids = Ids(self.customers["customerid"], "C", 3)
        self.merchant_ids = Ids(self.merchants["merchantid"], "M", 3)

        self.categories = self.txn["Category"].value_counts(normalize=True)
        self.channels = self.txn["Channel"].value_counts(normalize=True)
        self.amount_stats = self.txn.groupby("Category")["Amount"].agg(["mean", "std"]).fillna(0)
        self.min_amount = float(self.txn["Amount"].min())
        self.last_date = pd.to_datetime(self.time["Date"]).max().date()

    def new_customer(self):
        row = {
            "customerid": self.customer_ids.next(),
            "customername": f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}",
            "segment": self.rng.choice(self.customers["segment"].unique()),
            "homelocationid": self.rng.choice(self.locations["locationid"]),
            "preferredchannel": self.rng.choice(self.channels.index),
        }
        insert_db(self.engine, "customers", row)
        self.customers = pd.concat([self.customers, pd.DataFrame([row])], ignore_index=True)
        return row

    def new_merchant(self):
        row = {
            "merchantid": self.merchant_ids.next(),
            "merchantname": f"{self.rng.choice(LAST)} {self.rng.choice(SUFFIX)}",
            "merchantcategory": self.rng.choice(self.categories.index),
            "risklevel": self.rng.choice(["Low", "Medium", "High"], p=[0.5, 0.3, 0.2]),
        }
        insert_db(self.engine, "merchants", row)
        self.merchants = pd.concat([self.merchants, pd.DataFrame([row])], ignore_index=True)
        return row

    def new_transaction(self):
        rng = self.rng
        customer = self.customers.iloc[rng.integers(len(self.customers))]
        merchant = self.merchants.iloc[rng.integers(len(self.merchants))]
        category = rng.choice(self.categories.index, p=self.categories.values)
        # The preferred channel is favoured so KPI 5 has a baseline to compare against.
        if rng.random() < 0.7:
            channel = customer["preferredchannel"]
        else:
            channel = rng.choice(self.channels.index, p=self.channels.values)
        location = self.locations.iloc[rng.integers(len(self.locations))]["locationid"]
        stats = self.amount_stats.loc[category]
        amount = max(self.min_amount, rng.normal(stats["mean"], stats["std"]))
        hour = int(rng.integers(6, 24))

        if rng.random() < self.anomaly_rate:
            kind = rng.choice(ANOMALIES)
            if kind == "night":
                hour = int(rng.integers(0, 6))
            elif kind == "far_location":
                home = self.locations[self.locations["locationid"] == customer["homelocationid"]]
                if not home.empty:
                    dist = haversine_km(home["latitude"].iloc[0], home["longitude"].iloc[0],
                                        self.locations["latitude"], self.locations["longitude"])
                    location = self.locations.iloc[int(np.argmax(dist.values))]["locationid"]
            elif kind == "high_amount":
                amount = stats["mean"] + 4 * max(stats["std"], 1)
            elif kind == "high_risk_merchant":
                high = self.merchants[self.merchants["risklevel"] == "High"]
                if not high.empty:
                    merchant = high.iloc[rng.integers(len(high))]
            elif kind == "channel_shift":
                others = [c for c in self.channels.index if c != customer["preferredchannel"]]
                channel = rng.choice(others)

        day = self.last_date + timedelta(days=int(rng.integers(1, 31)))
        time_row = {
            "TimeID": self.time_ids.next(), "Date": day.isoformat(), "DayOfWeek": day.strftime("%A"),
            "Month": day.strftime("%b"), "Year": day.year, "HourOfDay": hour,
        }
        txn_row = {
            "TransactionID": self.txn_ids.next(), "CustomerID": customer["customerid"],
            "MerchantID": merchant["merchantid"], "TimeID": time_row["TimeID"], "LocationID": location,
            "Amount": f"{amount:.2f}", "Category": category, "Channel": channel,
        }
        return time_row, txn_row

    def write_transaction(self):
        time_row, txn_row = self.new_transaction()
        # Time first, so the transaction's TimeID always resolves when the pipeline picks it up.
        append_csv_row(RAW_DIR / "Time.csv", time_row)
        append_csv_row(RAW_DIR / "Transactions.csv", txn_row)
        return txn_row


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rows", type=int, default=50, help="transactions to append in one go (default 50)")
    p.add_argument("--interval", type=float, help="append one transaction every S seconds until Ctrl-C")
    p.add_argument("--anomaly-rate", type=float, default=0.05, help="share of deliberately anomalous rows")
    p.add_argument("--seed", type=int, help="random seed for reproducible data")
    p.add_argument("--new-customers", type=int, default=0, help="Customers rows to insert first")
    p.add_argument("--new-merchants", type=int, default=0, help="Merchants rows to insert first")
    args = p.parse_args()

    gen = Generator(get_engine(), np.random.default_rng(args.seed), args.anomaly_rate)
    for _ in range(args.new_customers):
        print("customer", gen.new_customer()["customerid"])
    for _ in range(args.new_merchants):
        print("merchant", gen.new_merchant()["merchantid"])

    if args.interval:
        try:
            while True:
                row = gen.write_transaction()
                print(f"{row['TransactionID']} {row['CustomerID']} {row['Amount']} {row['Category']} {row['Channel']}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("stopped")
    else:
        for _ in range(args.rows):
            gen.write_transaction()
        print(f"appended {args.rows} transactions to {RAW_DIR}")


if __name__ == "__main__":
    main()
