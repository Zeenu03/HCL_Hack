"""Step 2: Cleanse.

Reads the canonical CSVs that ingest.py wrote to data/Landing/ (whatever the original sources were),
applies the cleansing rules from the design doc, and writes the cleaned tables to the PostgreSQL
`cleansed` schema and to data/cleansed/ as CSV. Prints how many rows each rule removed so the
cleansing is traceable. Cleansing only: all KPI logic lives in sql/.
"""

from pathlib import Path

import pandas as pd
from sqlalchemy import text

from db import get_engine

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LANDING_DIR = DATA_DIR / "Landing"
CLEANSED_DIR = DATA_DIR / "cleansed"

CHANNELS = ["Digital", "ATM", "Branch"]
CATEGORIES = ["Retail", "Travel", "Healthcare", "Utilities"]

# Per-file rules: primary key, allowed values for categorical columns, and column types.
SCHEMAS = {
    "Customers.csv": {
        "pk": "CustomerID",
        "allowed": {"Segment": ["Student", "Premium", "Standard"], "PreferredChannel": CHANNELS},
    },
    "Merchants.csv": {
        "pk": "MerchantID",
        "allowed": {"MerchantCategory": CATEGORIES, "RiskLevel": ["Low", "Medium", "High"]},
    },
    "Time.csv": {
        "pk": "TimeID",
        "dates": ["Date"],
        "ints": ["HourOfDay", "Year"],
    },
    "Transactions.csv": {
        "pk": "TransactionID",
        "allowed": {"Category": CATEGORIES, "Channel": CHANNELS},
        "floats": ["Amount"],
    },
    # Synthetic reference table (source.locations), seeded with the database.
    "Locations.csv": {
        "pk": "LocationID",
        "floats": ["Latitude", "Longitude"],
    },
}

# Foreign keys checked on Transactions after the dimension tables are cleaned.
FOREIGN_KEYS = {
    "CustomerID": "Customers.csv",
    "MerchantID": "Merchants.csv",
    "TimeID": "Time.csv",
}


class RuleLog:
    """Applies row filters and records how many rows each rule removed."""

    def __init__(self, name, rows_in):
        self.name = name
        self.rows_in = rows_in
        self.counts = {}

    def drop(self, df, rule, keep_mask):
        removed = int((~keep_mask).sum())
        self.counts[rule] = self.counts.get(rule, 0) + removed
        return df[keep_mask]

    def report(self, rows_out):
        print(f"\n[{self.name}] {self.rows_in} rows in -> {rows_out} rows out")
        for rule, n in self.counts.items():
            print(f"  - {rule:<40} removed {n}")


def trim_text(df):
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()
    return df.replace("", pd.NA)


def standardize_case(df, allowed):
    """Map values case-insensitively to their canonical form (e.g. 'digital' -> 'Digital')."""
    for col, values in allowed.items():
        canonical = {v.lower(): v for v in values}
        df[col] = df[col].str.lower().map(canonical).fillna(df[col])
    return df


def clean_table(name, df):
    schema = SCHEMAS[name]
    pk = schema["pk"]
    allowed = schema.get("allowed", {})
    log = RuleLog(name, len(df))

    df = trim_text(df)
    df = standardize_case(df, allowed)

    df = log.drop(df, "exact duplicate rows", ~df.duplicated())
    df = log.drop(df, f"missing primary key ({pk})", df[pk].notna())
    df = log.drop(df, f"duplicate primary key ({pk})", ~df[pk].duplicated(keep="first"))

    # Type conversion: values that cannot be converted become NaN and are dropped.
    for col in schema.get("floats", []):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in schema.get("ints", []):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in schema.get("dates", []):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    typed_cols = schema.get("floats", []) + schema.get("ints", []) + schema.get("dates", [])
    if typed_cols:
        df = log.drop(df, "invalid / missing typed value", df[typed_cols].notna().all(axis=1))

    if name == "Transactions.csv":
        df = log.drop(df, "Amount <= 0", df["Amount"] > 0)
    if name == "Time.csv":
        df = log.drop(df, "HourOfDay outside 0-23", df["HourOfDay"].between(0, 23))
    if name == "Locations.csv":
        in_range = df["Latitude"].between(-90, 90) & df["Longitude"].between(-180, 180)
        df = log.drop(df, "coordinates out of range", in_range)

    for col, values in allowed.items():
        df = log.drop(df, f"invalid {col}", df[col].isin(values))

    for col in schema.get("ints", []):
        df[col] = df[col].astype(int)
    for col in schema.get("dates", []):
        df[col] = df[col].dt.date

    return df, log


def check_foreign_keys(transactions, tables, log):
    for col, dim_name in FOREIGN_KEYS.items():
        dim_pk = SCHEMAS[dim_name]["pk"]
        valid_ids = tables[dim_name][dim_pk]
        transactions = log.drop(transactions, f"unknown {col}", transactions[col].isin(valid_ids))
    return transactions


def read_landing(name):
    path = LANDING_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Landing file missing: {path} (run pipeline/ingest.py first)")
    return pd.read_csv(path, dtype=str)


def write_cleansed(name, df, engine):
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    out.to_sql(name[:-4].lower(), engine, schema="cleansed", if_exists="replace", index=False)


def run():
    CLEANSED_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS cleansed"))

    tables, logs = {}, {}
    for name in SCHEMAS:
        tables[name], logs[name] = clean_table(name, read_landing(name))

    tables["Transactions.csv"] = check_foreign_keys(
        tables["Transactions.csv"], tables, logs["Transactions.csv"]
    )

    for name, df in tables.items():
        df.to_csv(CLEANSED_DIR / name, index=False)
        write_cleansed(name, df, engine)
        logs[name].report(len(df))

    print(f"\nCleansed tables written to schema `cleansed` and {CLEANSED_DIR}")
    return tables


if __name__ == "__main__":
    run()
