"""Step 1: Ingest (collect + map).

Collects data from every configured source and maps it to the canonical schema, writing one CSV per table to
data/Landing/. clean.py then reads only those CSVs, so the rest of the pipeline never needs to know where the data
came from.

A table can have several sources (their rows are concatenated). Each source is a dict:
    {"type": "csv",      "path": <file>,                      "columns": {source column: canonical column}}
    {"type": "database", "url": <SQLAlchemy URL>, "query": <SQL>, "columns": {...}}   # Postgres, MySQL, SQL Server, ...
`columns` is optional when the source already uses the canonical names.

To add a source: append a dict to SOURCES below. To support a new kind of source (API, JSON, ...), add an entry to
READERS with a `read` and a `signature` function.
"""

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from db import DATABASE_URL

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW_DIR = DATA_DIR / "raw"          # the CSV source files as delivered
LANDING_DIR = DATA_DIR / "Landing"  # output: canonical CSVs, one per table
SOURCE_DB_URL = os.getenv("SOURCE_DATABASE_URL", DATABASE_URL)

CANONICAL = {
    "Transactions": ["TransactionID", "CustomerID", "MerchantID", "TimeID", "LocationID", "Amount", "Category", "Channel"],
    "Time": ["TimeID", "Date", "DayOfWeek", "Month", "Year", "HourOfDay"],
    "Customers": ["CustomerID", "CustomerName", "Segment", "HomeLocationID", "PreferredChannel"],
    "Merchants": ["MerchantID", "MerchantName", "MerchantCategory", "RiskLevel"],
    "Locations": ["LocationID", "City", "Latitude", "Longitude"],
}


def db_source(table, schema_table):
    """A PostgreSQL source table whose lowercase columns map to the canonical names."""
    columns = {c.lower(): c for c in CANONICAL[table]}
    return {
        "type": "database",
        "url": SOURCE_DB_URL,
        "query": f"SELECT {', '.join(columns)} FROM {schema_table}",
        "columns": columns,
    }


SOURCES = {
    "Transactions": [{"type": "csv", "path": RAW_DIR / "Transactions.csv"}],
    "Time": [{"type": "csv", "path": RAW_DIR / "Time.csv"}],
    "Customers": [db_source("Customers", "source.customers")],
    "Merchants": [db_source("Merchants", "source.merchants")],
    "Locations": [db_source("Locations", "source.locations")],
}

_engines = {}


def _engine(url):
    if url not in _engines:
        _engines[url] = create_engine(url, pool_pre_ping=True)
    return _engines[url]


def _read_csv(src):
    return pd.read_csv(src["path"], dtype=str)


def _read_database(src):
    return pd.read_sql(text(src["query"]), _engine(src["url"]))


def _signature_csv(src):
    return Path(src["path"]).stat().st_mtime


def _signature_database(src):
    with _engine(src["url"]).connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM ({src['query']}) q")).scalar()


# type -> (read, signature). The signature changes whenever the source's data changes (used for live refresh).
READERS = {
    "csv": (_read_csv, _signature_csv),
    "database": (_read_database, _signature_database),
}


def collect(table, src):
    """Read one source and map it to the canonical columns of `table`."""
    read, _ = READERS[src["type"]]
    df = read(src).rename(columns=src.get("columns", {}))
    missing = [c for c in CANONICAL[table] if c not in df.columns]
    if missing:
        raise ValueError(f"{table}: source {src.get('path') or src.get('query')} is missing columns {missing}")
    return df[CANONICAL[table]]


def signature():
    """One value covering every source; it changes when any source gains, loses or changes rows."""
    return tuple(READERS[s["type"]][1](s) for sources in SOURCES.values() for s in sources)


def run():
    LANDING_DIR.mkdir(parents=True, exist_ok=True)
    print("[ingest] collecting sources")
    for table, sources in SOURCES.items():
        parts = [collect(table, s) for s in sources]
        out = pd.concat(parts, ignore_index=True)
        out.to_csv(LANDING_DIR / f"{table}.csv", index=False)
        detail = " + ".join(f"{s['type']} {len(p)}" for s, p in zip(sources, parts))
        print(f"  - {table:<13} {len(out):>4} rows ({detail}) -> {LANDING_DIR.name}/{table}.csv")
    return LANDING_DIR


if __name__ == "__main__":
    run()
