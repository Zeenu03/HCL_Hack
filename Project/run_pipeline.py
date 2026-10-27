"""Runs the whole pipeline: ingest.py (collect + map sources to landing CSVs), clean.py (cleanse), then every
sql/kpi*.sql in file-name order.

Each SQL file is one transaction that rebuilds its curated tables, so re-running is safe. Afterwards every
table in the `curated` schema is also exported to data/curated/<name>.csv as a reference copy.
"""

import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pipeline"))

import clean  # noqa: E402
import ingest  # noqa: E402
from db import get_engine  # noqa: E402

SQL_DIR = ROOT / "sql"
CURATED_DIR = ROOT / "data" / "curated"


def run_sql_files(engine):
    for path in sorted(SQL_DIR.glob("kpi*.sql")):
        sql = path.read_text()
        with engine.begin() as conn:
            # Raw cursor with no parameters: the driver then leaves '%' in the SQL alone.
            cursor = conn.connection.cursor()
            cursor.execute(sql)
            cursor.close()
            tables = re.findall(r"^CREATE TABLE curated\.(\w+)", sql, flags=re.MULTILINE)
            counts = {t: conn.execute(text(f"SELECT COUNT(*) FROM curated.{t}")).scalar() for t in tables}
        print(f"[{path.name}] " + ", ".join(f"{t} ({n} rows)" for t, n in counts.items()))


def export_curated(engine):
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'curated' ORDER BY 1"))]
    for name in names:
        pd.read_sql(f"SELECT * FROM curated.{name}", engine).to_csv(CURATED_DIR / f"{name}.csv", index=False)
    print(f"\nExported {len(names)} curated tables to {CURATED_DIR}")


def main():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS curated"))
    ingest.run()
    clean.run()
    print("\n--- SQL KPIs ---")
    run_sql_files(engine)
    export_curated(engine)


if __name__ == "__main__":
    main()
