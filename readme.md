# Analyze customer transactions — Design Document

## 1. Overview

A retail bank wants to analyze customer transaction behavior to **improve personalized marketing** and **detect anomalies**.
This project builds a simple, fully local data pipeline. In real life data arrives from **many different sources**
(CSV drops, PostgreSQL or any other database, ...). The pipeline first **collects every source and maps it to one
canonical schema as CSV files** (the landing zone), then cleanses those CSVs in Python, transforms them into KPI-ready
tables with **SQL** in a curated layer, and displays the results in a dashboard that **updates live when a row is added
to any source**.

```
sources (CSV, PostgreSQL, ...) -> ingest -> landing CSVs -> clean.py -> sql/kpi*.sql -> Streamlit
```

**Design rules:** ingestion only collects and maps; cleansing is Python; **all business logic (joins, KPI
calculations, anomaly flags) is SQL.** Everything after ingestion is independent of where the data came from.

**Goal:** keep it simple and easy to run. After a one-time `docker compose up -d` for the database, the whole thing runs
with two commands.

```
python run_pipeline.py
streamlit run app.py
```

A third, optional command generates synthetic transactions (one-off batch or a live stream) to exercise the pipeline:

```
python pipeline/generate_synthetic.py --rows 50
```

**Contents:** 1 Overview · 2 KPIs · 3 Tech stack · 4 Source data · 5 Project structure · 6 End-to-end pipeline (complete flow,
worked example, each step) · 7 How to run · 8 Assumptions · 9 Future enhancements · 10 Component reference (every file
explained) · 11 Expected questions and answers

---

## 2. KPIs

| # | KPI | What it measures | Business use |
|---|-----|------------------|--------------|
| 1 | Customer Segmentation by Transaction Category | Share of spend across categories (Retail, Travel, Healthcare, Utilities) | Targeted campaigns; detect unusual category shifts |
| 2 | Peak Transaction Time Analysis | Most common hours / days customers transact | Time marketing pushes; flag odd-hour transactions |
| 3 | Repeat Merchant Ratio | How often customers return to the same merchant | Loyalty partnerships; new high-risk merchants may signal fraud |
| 4 | Geo-Location Consistency Index | How consistent transaction locations are with the customer's usual footprint | Detect location anomalies; local offers |
| 5 | Digital vs. Branch Transaction Mix | Proportion of digital vs. physical (Branch/ATM) transactions | Digital adoption campaigns; flag channel shifts |

New KPIs are added by dropping one more `kpiN_*.sql` file into
`sql/` (see section 6).

---

## 3. Tech Stack

| Tool | Role in the project |
|------|---------------------|
| **Python** | Main language |
| **pandas** | Read the sources and cleanse the data (ingest + cleansing only, no KPI logic) |
| **PostgreSQL** (Docker) | Second data source (CRM-style tables) and the home of the `cleansed` and `curated` schemas |
| **SQL** | All business logic: joins, KPI calculations, anomaly flags (`sql/*.sql`) |
| **SQLAlchemy + psycopg2** | Python connection to PostgreSQL (read sources, load cleansed data, run the `.sql` files, read curated tables) |
| **Streamlit** (≥ 1.37) | Dashboard to visualize all KPIs; `st.fragment(run_every=…)` gives live refresh with no extra library |

Install:

```
docker compose up -d        # starts PostgreSQL
pip install -r requirements.txt
```

---

## 4. Source Data

### Canonical schema

Whatever the source, data is mapped to these tables. They form a simple **star schema**: one fact table and three
dimension tables, plus a synthetic reference table that resolves the `LocationID` codes.

| Table | Type | Columns |
|-------|------|---------|
| `Transactions` | Fact | TransactionID, CustomerID, MerchantID, TimeID, LocationID, Amount, Category, Channel |
| `Time` | Dimension | TimeID, Date, DayOfWeek, Month, Year, HourOfDay |
| `Customers` | Dimension | CustomerID, CustomerName, Segment, HomeLocationID, PreferredChannel |
| `Merchants` | Dimension | MerchantID, MerchantName, MerchantCategory, RiskLevel |
| `Locations` | Reference (synthetic, new) | LocationID, City, Latitude, Longitude |

### Configured sources (current setup)

| Table | Rows | Source |
|-------|------|--------|
| `Transactions` | 100 | CSV: `data/raw/Transactions.csv` (payment-gateway style) |
| `Time` | 60 | CSV: `data/raw/Time.csv` |
| `Customers` | 60 | PostgreSQL table `source.customers` (CRM style) |
| `Merchants` | 60 | PostgreSQL table `source.merchants` (CRM style) |
| `Locations` | 55 | PostgreSQL table `source.locations` |

The given data arrives as four CSVs (`data/raw/`). To have a real second source, `sql/seed_source.sql` (run by
`docker compose up` on first start) loads `Customers.csv` and `Merchants.csv` into the `source` schema and builds the
synthetic `Locations` table. It stands in for a real external database. The given tables keep their columns exactly as
they are.

Sources are listed in one place, `SOURCES` in `pipeline/ingest.py`. A table can have several sources (their rows are
concatenated), and each source maps its own column names to the canonical ones:

```python
{"type": "csv",      "path": "other_bank/payments.csv",           "columns": {"txn_ref": "TransactionID", ...}}
{"type": "database", "url": "postgresql://...", "query": "SELECT ...", "columns": {"cust_ref": "CustomerID", ...}}
```

`database` works with any SQLAlchemy-supported database (PostgreSQL, MySQL, SQL Server, ...). A new kind of source
(API, JSON, ...) is added by registering one `read` and one `signature` function in `READERS`. A source that lacks a
canonical column fails loudly with the column names.

`Locations` is not part of the given data. It is made up for this project and is the only new table.
`Transactions.LocationID` and `Customers.HomeLocationID` both join to it.

### Data Model

```
                 ┌──────────────┐
                 │  Customers   │
                 │ CustomerID PK│
                 └──────┬───────┘
                        │
┌──────────────┐  ┌─────┴────────┐  ┌──────────────┐
│  Merchants   ├──┤ Transactions ├──┤     Time     │
│ MerchantID PK│  │  (Fact)      │  │  TimeID PK   │
└──────────────┘  └──────────────┘  └──────────────┘
```

### Data Observations (from profiling)

- No null values or duplicate rows in any file; all foreign keys in `Transactions` resolve to the dimension tables.
- **Values:** Segment = Student / Premium / Standard; Channel = Digital / ATM / Branch; Category = Retail / Travel / Healthcare / Utilities; RiskLevel = Low / Medium / High.
- **Category mismatch:** in 81 of 100 transactions, `Transactions.Category` differs from `Merchants.MerchantCategory`. KPI 1 uses `Transactions.Category` (what the customer actually spent on).
- **No location table in the given data:** only `LocationID` codes (e.g. `L035`) exist. The synthetic `Locations` table adds a city and coordinates per code so distances can be computed; the real data itself still carries only the codes.
- **Small history per customer:** 47 of 60 customers have transactions, averaging ~2 each (max 6). Per-customer KPIs should be read with this in mind.
- **ID overlap:** `TransactionID` (`T001`…) and `TimeID` (`T1001`…) share the `T` prefix; always join on the correct column.
- Date range: `Time.csv` covers Jan – Mar 2026, but the 100 transactions fall in Jan – Feb 2026.

---

## 5. Project Structure

```
project/
├── docker-compose.yml      # PostgreSQL; runs sql/seed_source.sql on first start
├── data/
│   ├── raw/                # CSV sources as delivered (Transactions, Time; Customers/Merchants seed the demo database)
│   ├── Landing/            # OUTPUT of ingest.py: canonical CSVs, one per table, from all sources
│   ├── cleansed/           # cleaned CSVs (output of clean.py; also loaded into the `cleansed` schema)
│   └── curated/            # CSV export of every curated table (reference copy)
├── pipeline/
│   ├── db.py               # PostgreSQL connection (DATABASE_URL, defaults match docker-compose.yml)
│   ├── ingest.py           # Python: collect every source, map to the canonical schema, write landing CSVs
│   ├── clean.py            # Python: cleanse the landing CSVs
│   └── generate_synthetic.py   # appends synthetic rows to the sources
├── sql/                    # ALL business logic
│   ├── seed_source.sql     # one-time: creates the demo source database (`source` schema) and loads CRM tables
│   ├── kpi1_category_segmentation.sql
│   ├── kpi2_peak_time.sql
│   ├── kpi3_repeat_merchant.sql
│   ├── kpi4_geo_consistency.sql
│   └── kpi5_channel_mix.sql
├── run_pipeline.py         # runs ingest.py, clean.py, then every sql/kpi*.sql in name order
├── app.py                  # Streamlit dashboard
└── readme.md
```

The earlier pandas versions of KPIs 1–3 and 5 were removed after the SQL outputs were checked to match them.

---

## 6. End-to-End Pipeline

```
 Source A: CSV files        Source B: PostgreSQL        Source C: any other database / system
 (data/raw/*.csv)           (`source` schema)           (add to SOURCES in ingest.py)
        │                          │                          │
        └────────────┬─────────────┴──────────────────────────┘
                     ▼
            ┌─────────────────┐
            │    ingest.py    │  Python: collect all sources + map columns to the canonical schema
            └────────┬────────┘
                     ▼
            data/Landing/*.csv   (canonical CSVs, one per table)
                     │
                     ▼
            ┌─────────────────┐
            │    clean.py     │  Python: cleanse
            └────────┬────────┘
                     ▼
        PostgreSQL `cleansed` schema  (+ data/cleansed/*.csv)
                     │
                     ▼
         ┌───────────────────────────┐
         │ sql/kpi1.sql … kpi5.sql   │  SQL: all business logic
         └──────┬────────────────────┘
                ▼
        PostgreSQL `curated` schema  (+ data/curated/*.csv)
                │
                ▼
 ┌───────────────┐    change detected in any source    ┌─────────────────────────┐
 │    app.py     │◄────────────────────────────────────┤ a source CSV or database│◄── row added by hand,
 │ (live refresh)│    re-runs the whole pipeline       │ table                   │    or generate_synthetic.py
 └───────────────┘                                     └─────────────────────────┘
```

`run_pipeline.py` calls `ingest.py`, then `clean.py`, then runs every `sql/kpi*.sql` in file-name order, and prints a short log for each step. Each SQL file is a self-contained `DROP TABLE IF EXISTS …;
CREATE TABLE curated.<name> AS SELECT …`, so re-running is safe; adding a KPI needs no change to `run_pipeline.py`.

### Complete flow, step by step

| # | Stage | Triggered by | Reads | Writes | Language |
|---|-------|--------------|-------|--------|----------|
| 0 | Set up the demo source database | `docker compose up -d` (first start only) | `data/raw/Customers.csv`, `Merchants.csv`, `Transactions.csv` (for location IDs) | PostgreSQL `source.customers`, `source.merchants`, `source.locations` | SQL |
| 1 | **Ingest**: collect all sources, map to the canonical schema | `run_pipeline.py` (or `ingest.py`) | every source in `SOURCES`: `data/raw/*.csv` and the `source.*` tables | `data/Landing/*.csv` (5 files) | Python |
| 2 | **Cleanse** | `run_pipeline.py` (or `clean.py`) | `data/Landing/*.csv` | PostgreSQL `cleansed.*` and `data/cleansed/*.csv` | Python |
| 3 | **Transform**: all business logic | `run_pipeline.py`, one `sql/kpiN_*.sql` at a time in name order | `cleansed.*` | PostgreSQL `curated.*` (10 tables) | SQL |
| 4 | **Export** a CSV copy | `run_pipeline.py` | `curated.*` | `data/curated/*.csv` | Python |
| 5 | **Serve** | `streamlit run app.py` | `curated.*` only | the dashboard | Python / Streamlit |
| 6 | **Live loop** | `app.py` every 3 s | `ingest.signature()` of all sources | re-runs stages 1–4 if anything changed | Python |

Each stage only reads what the stage before it wrote, so every layer can be inspected on its own: open
`data/Landing/` to see what the sources were mapped to, `data/cleansed/` to see what survived cleansing, and
`data/curated/` to see the KPI results.

**What happens when a new row arrives**
1. A row is added to a source: a line in `data/raw/Transactions.csv`, an `INSERT` into `source.customers`, or the
   synthetic generator doing either.
2. Within 3 seconds, the dashboard's fragment reruns and calls `ingest.signature()`. The CSV's modified time or the
   table's row count has changed, so the fingerprint differs from the last run.
3. `app.py` runs the whole pipeline (stages 1–4). Stage 1 rewrites the landing CSVs, stage 2 recleans them, stage 3
   rebuilds every curated table, stage 4 refreshes the CSV copies.
4. The dashboard reloads the `curated` tables, and the new row shows up in the metrics, charts and "Last refreshed" time.

#### Worked example: following one transaction

The first transaction in the data, `T001`, from the source to the dashboard:

| Layer | What `T001` / customer `C054` looks like |
|-------|-------------------------------------------|
| Source CSV (`data/raw/Transactions.csv`) | `T001,C054,M015,T1028,L036,1903.97,Retail,Digital` |
| Source database (`source.customers`) | `C054, Amy Rodriguez, Standard, L057, Branch` (the customer's CRM record) |
| Ingest → `data/Landing/` | the same row in `Transactions.csv`; the customer, merchant (`M015 Villarreal-Butler, Travel, Low`), time (`T1028 = 2026-01-28, Wednesday, 19:00`) and location (`L036 = Ahmedabad`) rows in their own landing CSVs, all with canonical column names |
| Cleanse → `cleansed.*` | passes every rule (amount > 0, valid category and channel, all four foreign keys exist), so nothing is dropped |
| KPI 1 | Amy spent 5,840.59 in total: Retail 32.6 %, Travel 67.4 %, so her **dominant category is Travel** |
| KPI 3 | 2 transactions at 2 different merchants, `repeat_merchant_ratio = 0`, no High-risk merchant |
| KPI 4 | home `L057`, 0 of 2 transactions at home, 2 distinct locations, 521 km away on average, so `geo_anomaly_flag = 1` |
| KPI 5 | 1 Digital + 1 Physical (50 / 50); preferred channel is Branch but she used Digital and ATM, so `channel_shift_flag = 1` |
| Dashboard | the transaction counts in the overview, her row in the KPI 1 table, her bar in the KPI 4 chart |

### Step 1 — Ingest: collect and map (`pipeline/ingest.py`)

For every canonical table, reads each configured source, renames its columns to the canonical names, concatenates the
sources and writes `data/Landing/<Table>.csv`. It does no cleaning and no business logic, so bad values pass through
untouched for `clean.py` to deal with. The log shows how many rows each source contributed.

### Step 2 — Cleanse (`pipeline/clean.py`)

Reads the five canonical CSVs from `data/Landing/` (it never touches the original sources), applies the rules below in
Python, and writes the cleaned tables to the `cleansed` schema (and to `data/cleansed/` as CSV). Cleansing stays in
Python by design; it contains no KPI logic.

| Rule | Applied to |
|------|-----------|
| Trim whitespace in text columns; standardize case of category values | All files |
| Drop exact duplicate rows | All files |
| Drop rows with a missing primary key | All files |
| Remove duplicate primary keys (keep first) | All files |
| Convert types: `Amount` → float, `Date` → date, `HourOfDay` / `Year` → int | Transactions, Time |
| Remove transactions with `Amount <= 0` or missing | Transactions |
| Remove `HourOfDay` outside 0–23 | Time |
| Keep only allowed values for `Channel`, `Category`, `Segment`, `RiskLevel` | All files |
| Drop transactions whose CustomerID / MerchantID / TimeID do not exist in dimension tables (referential integrity) | Transactions |

The step prints how many rows were removed by each rule, so the cleansing is traceable.

### Step 3 — Transform into Curated Layer (`sql/kpi*.sql`)

Each KPI file reads from the `cleansed` schema, joins the tables it needs, computes the metric in SQL (CTEs, window
functions, `GROUP BY`), and creates the result as a table in the `curated` schema. The output names below are table
names (`curated.<name>`); `run_pipeline.py` also exports each one to `data/curated/<name>.csv` as a reference copy.
The SQL results for KPIs 1–3 and 5 were checked against the earlier pandas versions and match; KPI 4 is SQL-only.

#### KPI 1 — Customer Segmentation by Transaction Category
- **Logic:** per customer, total spend per `Category` ÷ customer's total spend = category share. The category with the highest share is the customer's **dominant category**.
- **Also:** the same share at `Segment` level (Student / Premium / Standard).
- **Output:** `kpi1_customer_category_share`, `kpi1_segment_category_share`

#### KPI 2 — Peak Transaction Time Analysis
- **Logic:** join with `Time`; count transactions and total amount by `HourOfDay` and by `DayOfWeek`. Bucket hours into Night (0–5), Morning (6–11), Afternoon (12–17), Evening (18–23).
- **Anomaly flag:** transactions in the Night bucket (0–5) → `odd_hour_flag = 1`.
- **Output:** `kpi2_hourly`, `kpi2_daily`, `kpi2_odd_hour_txns`

#### KPI 3 — Repeat Merchant Ratio
- **Logic:** per customer,
  `repeat_merchant_ratio = (total_txns − unique_merchants) / total_txns`
  (0 = always a new merchant, closer to 1 = very loyal).
- **Also:** share of each customer's transactions with `High` risk merchants.
- **Output:** `kpi3_repeat_merchant`

#### KPI 4 — Geo-Location Consistency Index
- **Logic:** per customer,
  `geo_consistency_index = txns where LocationID == HomeLocationID / total_txns`
  plus `distinct_locations` count and, using `Locations`, the average distance (km) of a customer's transactions
  from their home location.
- **Anomaly flag:** customers with low index and multiple distinct locations → `geo_anomaly_flag = 1`.
- **Note:** in the current data almost no transactions happen at the home location, so most customers will score low. This is a data characteristic, worth calling out in the dashboard.
- **Output:** `kpi4_geo_consistency`

#### KPI 5 — Digital vs. Branch Transaction Mix
- **Logic:** map `Channel` → `Digital` vs. `Physical` (Branch + ATM). Compute share overall, by `Segment`, and per customer.
- **Anomaly flag:** customers whose most-used channel differs from their `PreferredChannel` → `channel_shift_flag = 1`.
- **Output:** `kpi5_channel_mix_overall`, `kpi5_channel_mix_segment`, `kpi5_customer_channel`

### Step 4 — Dashboard (`app.py`)

A Streamlit app that reads only from the `curated` schema in PostgreSQL (no calculations in the UI).

| Section | Visuals |
|---------|---------|
| Overview | Total transactions, total amount, active customers, odd-hour transactions, geo-flagged and channel-shift customers |
| KPI 1 | Stacked bar of category share by segment; table of dominant category per customer |
| KPI 2 | Bar chart by hour, bar chart by day of week; table of odd-hour transactions |
| KPI 3 | Distribution of repeat merchant ratio; top loyal customers; high-risk merchant exposure |
| KPI 4 | Geo consistency index per customer; flagged customers |
| KPI 5 | Digital vs. Physical split (overall + by segment); channel-shift customers |

A sidebar filter for `Segment` lets the user slice the views.

### Live Updates

The dashboard refreshes itself when a row is added to any configured source (a source CSV or a database table).

1. The dashboard body is wrapped in `@st.fragment(run_every="3s")`, so it reruns every 3 seconds.
2. On each run, `app.py` asks `ingest.signature()` for a fingerprint of every configured source: the modified time of
   each CSV and the row count of each database query. It compares it with the fingerprint from the previous run.
3. If it changed, `app.py` calls `run_pipeline.py` (ingest + clean + all SQL KPIs), then reloads the `curated` tables.
4. The page shows "Last refreshed at …" and the current transaction count, so a new row is visibly picked up.

A live toggle in the sidebar turns auto-refresh off. The dashboard still only *reads* curated data; its only extra job is
to trigger the pipeline.

To try it: run `streamlit run app.py`, then either append a line to `data/raw/Transactions.csv` by hand, insert a
row into a `source` table, or run `python pipeline/generate_synthetic.py --interval 5` in a second terminal.

### Synthetic Data Generation (`pipeline/generate_synthetic.py`)

"Synthetic data" here means one thing only: **adding more rows to the existing tables**. No column is added, removed or
renamed in any given table. The generator only appends rows (to the source CSVs in `data/raw/` for `Transactions` and `Time`,
and with `INSERT` for the PostgreSQL `source` tables), so the pipeline and live dashboard can be tested beyond the 100 given rows.
The one new table, `Locations`, is a synthetic reference table that is created once and can also grow with new rows.

| Option | Meaning |
|--------|---------|
| `--rows N` | Append `N` transactions in one go (default 50) |
| `--interval S` | Append one transaction every `S` seconds, until stopped (live demo) |
| `--anomaly-rate P` | Fraction of rows deliberately made anomalous (default 0.05) |
| `--seed K` | Fixed random seed for reproducible data |

How rows are built:
- `CustomerID`, `MerchantID` and `LocationID` are sampled from the existing dimension tables (and `Locations`), so
  referential integrity holds.
- Rows may also be inserted into `Customers` and `Merchants` (with `--new-customers K` / `--new-merchants K`) to grow
  the dimensions, again using only their existing columns.
- `Category`, `Channel` and `Amount` follow the distributions in the current data; the customer's `PreferredChannel` is
  favoured so the channel-shift KPI has a baseline.
- A new `Time.csv` row is appended for each new timestamp (dated after the last existing date), with a fresh `TimeID`
  that continues the existing numbering; `TransactionID` also continues its own numbering.
- Anomalous rows are produced by picking one of: night hour (0–5), a location far from the customer's home, a `High`
  risk merchant, or a channel different from the customer's preference. These trigger the flags in KPIs 2, 3, 4 and 5.
- Each CSV row is written with a single append, and each database row with a single `INSERT`, so the dashboard never
  reads a half-written row.

Generated rows go into the same sources as the real data; keep a copy of the original CSVs (and re-run the seed step)
if you need to reset.

---

## 7. How to Run

All commands run from the project folder (`Project/`).

1. Place the source CSV files in `data/raw/`. If the repo sits in an iCloud-synced folder (e.g. Desktop), make sure the
   files are downloaded (`cat data/raw/*.csv > /dev/null`); Docker cannot read cloud-only placeholders.
2. Start the database (also seeds the `source` schema on first start): `docker compose up -d`
3. Install dependencies: `pip install -r requirements.txt`
4. Run the pipeline: `python run_pipeline.py`
5. Open the dashboard: `streamlit run app.py`
6. (Optional) Add data: `python pipeline/generate_synthetic.py --rows 50`, or watch it update live: in a second terminal run `python pipeline/generate_synthetic.py --interval 5`

---

## 8. Assumptions & Limitations

- Data is small (100 transactions), so a single local PostgreSQL container and in-memory pandas cleansing are enough; no
  distributed tools needed.
- Customers and Merchants are loaded into PostgreSQL from the given CSVs to act as a second source; the given data
  does not come from a real database. Only the CSV and database source types are implemented and tested; other types
  (API, JSON, ...) need a new reader in `ingest.py`.
- Ingestion re-reads every source in full on each run (no incremental pull), and when a table has several sources
  their rows are only concatenated; duplicates across sources are removed later by `clean.py`'s primary-key rule.
- `data/Landing/` is generated output, so it can be rebuilt at any time with `python pipeline/ingest.py`.
- Cleansing is in Python and business logic is in SQL by design. The cleansing rules are not repeated in SQL, so the
  SQL files assume the `cleansed` schema is already valid.
- Live update re-runs the whole pipeline whenever a source changes (polling every 3 s). That is fine at this size
  but would need incremental processing at larger volumes.
- Synthetic rows follow simple sampling rules; they test the pipeline and dashboard, not real banking behaviour.
- `LocationID` has no lookup table in the given data. `Locations` is synthetic, so distances are illustrative, not real geography.
- Per-customer KPIs are based on few transactions and are indicative, not statistically strong.
- `Transactions.Category` is treated as the source of truth for spend category.

## 9. Future Enhancements

### If time permits: run the pipeline on a real public dataset

Prove the pipeline is not tied to the 100-row sample by running it on the closest public transaction dataset.

- **Candidates** (check licence and exact columns before use):
  - Sparkov synthetic credit-card transactions (Kaggle): customer, merchant, category, amount, timestamp, and
    latitude/longitude. Likely the closest fit to our schema.
  - IBM TabFormer credit-card transactions: user, merchant, amount, time, channel type.
  - PaySim (Kaggle): synthetic mobile-money transactions, with no merchant categories or locations, so a weaker fit.
- **Approach:** add the dataset as a new entry in `SOURCES` (`pipeline/ingest.py`) with a `columns` mapping to our
  canonical names; where one file has to be split into several tables, a small pre-processing script writes the split
  CSVs first. Everything after ingest, from `clean.py` to the SQL KPIs and the dashboard, runs unchanged.
- **Mapping gaps to handle:** invented `LocationID` values (for example from a rounded latitude/longitude or the
  city), a derived `Channel` where the dataset has none, and `Segment` / `RiskLevel` / `PreferredChannel` derived from
  spend or fraud rate where missing.
- **What it shows:** how the KPIs behave with far more history per customer, and, if the dataset has fraud labels, how
  well our anomaly flags line up with them. A sample of a few thousand rows is enough.

### Other ideas

- Process only new rows (incremental load) instead of re-running the whole pipeline on every change.
- Replace the synthetic `Locations` table with a real location dimension (city/country) for real distance-based geo anomalies.
- Schedule the pipeline (e.g. Prefect / cron) for daily loads.
- Add clustering (scikit-learn KMeans) on category shares for richer segments.

---

## 10. Component Reference

Every file in the project, what it does, and what it reads and writes.

### Data files (the CSVs)

**`data/raw/`: the CSV sources as delivered.** Edit or append here to simulate a source changing.

| File | Rows | What it holds |
|------|------|---------------|
| `Transactions.csv` | 100 | One row per card/bank transaction: who (`CustomerID`), where it was spent (`MerchantID`, `LocationID`), when (`TimeID`), how much (`Amount`), what for (`Category`) and through what (`Channel`). The fact table. |
| `Time.csv` | 60 | A calendar lookup: for each `TimeID`, the date, day of week, month, year and hour of day. |
| `Customers.csv` | 60 | One row per customer: name, `Segment` (Student / Premium / Standard), `HomeLocationID`, `PreferredChannel`. Used only to seed the demo database. |
| `Merchants.csv` | 60 | One row per merchant: name, `MerchantCategory`, `RiskLevel` (Low / Medium / High). Used only to seed the demo database. |

**`data/Landing/`: output of `ingest.py`, the canonical CSVs.** Same columns as the canonical schema, whatever the
sources were: `Transactions.csv`, `Time.csv`, `Customers.csv`, `Merchants.csv`, `Locations.csv` (the last holds
`LocationID`, `City`, `Latitude`, `Longitude`). Nothing is cleaned yet. Rebuild any time with `python pipeline/ingest.py`.

**`data/cleansed/`: output of `clean.py`.** The same five tables after the cleansing rules (types fixed, duplicates and
invalid rows removed, foreign keys checked). These are also loaded into the PostgreSQL `cleansed` schema.

**`data/curated/`: CSV copy of every KPI table** (the database `curated` schema is the source of truth for the dashboard):

| File | Grain (one row per) | Main columns |
|------|---------------------|--------------|
| `kpi1_customer_category_share.csv` | customer | spend and % share per category, `dominant_category` |
| `kpi1_segment_category_share.csv` | segment × category | transaction count, amount, `spend_share_pct` |
| `kpi2_hourly.csv` | segment × hour | `txn_count`, `total_amount`, time bucket |
| `kpi2_daily.csv` | segment × weekday | `txn_count`, `total_amount` |
| `kpi2_odd_hour_txns.csv` | night-time transaction | the transaction, with `odd_hour_flag` |
| `kpi3_repeat_merchant.csv` | customer | `repeat_merchant_ratio`, `high_risk_share`, `high_risk_flag` |
| `kpi4_geo_consistency.csv` | customer | `geo_consistency_index`, `distinct_locations`, `avg_distance_km`, `geo_anomaly_flag` |
| `kpi5_channel_mix_overall.csv` | channel group | Digital vs. Physical share by count and amount |
| `kpi5_channel_mix_segment.csv` | segment × channel group | the same share per segment |
| `kpi5_customer_channel.csv` | customer | digital / physical %, `most_used_channel`, `channel_shift_flag` |

### Code components

| Component | What it is | Reads | Writes | Notes |
|-----------|------------|-------|--------|-------|
| `docker-compose.yml` | Starts a PostgreSQL 16 container (user, password, database all `bank`, port 5432) | `sql/seed_source.sql`, `data/raw/` | the running database | Data lives in a Docker volume; `docker compose down -v` resets it |
| `sql/seed_source.sql` | One-time setup of the **demo source database**; stands in for a real CRM | `data/raw/*.csv` | schemas `source`, `cleansed`, `curated`; tables `source.customers`, `source.merchants`, `source.locations` | Builds the synthetic `Locations` table (a city and coordinates per `LocationID`). Source columns are plain text on purpose: validation is `clean.py`'s job |
| `pipeline/db.py` | Creates the database connection used by the pipeline and dashboard | env var `DATABASE_URL` | nothing | Default matches `docker-compose.yml` |
| `pipeline/ingest.py` | **Collect + map.** Reads every source in `SOURCES`, renames columns to the canonical names, concatenates, writes landing CSVs. Also provides `signature()` for change detection | the configured CSVs and database queries | `data/Landing/*.csv` | Add a source = add a dict to `SOURCES`; new source *type* = add a reader to `READERS`. Raises an error naming any missing column |
| `pipeline/clean.py` | **Cleanse** the landing CSVs with the rules in section 6 and report how many rows each rule removed | `data/Landing/*.csv` | `cleansed.*` tables, `data/cleansed/*.csv` | No KPI logic |
| `sql/kpi1…kpi5_*.sql` | **All business logic**, one file per KPI. Each one drops and recreates its `curated` tables | `cleansed.*` | `curated.*` | Re-running is safe. The geo thresholds (index < 0.5, at least 2 locations) are constants at the top of `kpi4_geo_consistency.sql` |
| `run_pipeline.py` | The **orchestrator**: ingest → clean → every `sql/kpi*.sql` in name order → export curated CSVs | all of the above | logs, `data/curated/*.csv` | `python run_pipeline.py` |
| `app.py` | The **Streamlit dashboard**, 5 KPI tabs, segment filter, live toggle | `curated.*` only | nothing (it triggers the pipeline when a source changes) | Refreshes every 3 s through `st.fragment` |
| `pipeline/generate_synthetic.py` | **Synthetic data**: appends more rows to the existing sources, never changes a column | the sources (for IDs and distributions) | rows appended to `data/raw/Transactions.csv`, `Time.csv`; rows inserted into `source.customers`, `source.merchants` | `--rows`, `--interval`, `--anomaly-rate`, `--seed`, `--new-customers`, `--new-merchants` |

---

## 11. Expected Questions and Answers

Answers refer to what is actually built. Where something is a limitation, the answer says so.

### Architecture and design

**1. Why collect everything into CSVs first instead of reading the sources directly in the pipeline?**
So that everything after ingestion is independent of where the data came from. Each source can have its own column
names and type; once mapped to the canonical CSVs, `clean.py`, the SQL KPIs and the dashboard never change. The landing
CSVs are also an inspectable checkpoint: you can open a file and see exactly what a source delivered.

**2. Why is cleansing in Python but the KPI logic in SQL?**
Cleansing is row-by-row data repair (trimming, type conversion, rule counting, logging), which pandas does naturally.
The KPIs are joins and aggregations, which SQL is built for and which the task asked to keep in SQL. It also means the
KPI definitions can be read and reviewed by anyone who knows SQL without reading Python.

**3. How would you add a new data source, for example another bank's payments or a MySQL database?**
Add one dictionary to `SOURCES` in `ingest.py` with the file path or database URL and a `columns` mapping to the
canonical names. A table can have several sources and their rows are concatenated. Nothing downstream changes. A new
*kind* of source (an API, JSON, a message queue) needs one `read` and one `signature` function in `READERS`.

**4. What if two sources contain the same record, or disagree?**
Rows are concatenated and `clean.py` keeps the first row for a duplicated primary key. There is no source priority or
field-level reconciliation; that is a known limitation and would be the next step for a real multi-source setup.

**5. Is this really real-time?**
It is near-real-time polling, not streaming. Every 3 seconds the dashboard checks a fingerprint of the sources (file
modified time, row count of each database query) and re-runs the whole pipeline if it changed. That is fast at this size
(100 rows). It would not suit millions of rows or sub-second needs, where you would use incremental loads or a streaming
tool (Kafka, change-data-capture).

**6. Why PostgreSQL? Could it be SQL Server or MySQL?**
PostgreSQL is free, runs in one Docker command, and is a real server. Ingestion already works with any
SQLAlchemy-supported database, because the source URL and query are configuration. The KPI SQL files use some
PostgreSQL features (`FILTER`, `LATERAL`, `generate_series`, `date_trunc`), so moving the *warehouse* to another database
means translating those parts.

**7. Why Streamlit?**
It is pure Python, needs no front-end code, and `st.fragment(run_every=…)` gives the live refresh with no extra library.
The dashboard contains no business logic; it only draws curated tables.

### Data quality

**8. How do you handle dirty data?**
`clean.py` trims text, standardises case, drops exact duplicates, rows with a missing or duplicate key, rows that cannot
be typed (bad amount or date), amounts of 0 or less, hours outside 0–23, values outside the allowed lists, and
transactions whose customer, merchant or time does not exist. It prints how many rows each rule removed. One honest
caveat: the sample data was already clean (no nulls, no duplicates, all keys valid), so these rules removed nothing on it
and have not been exercised on a deliberately dirty file. That is the first test we would add.

**9. `Transactions.Category` and `Merchants.MerchantCategory` disagree in 81 of 100 rows. Which one do you use?**
`Transactions.Category`, because it records what the customer actually spent on in that transaction (a retail merchant
can sell travel). Using the merchant's category would misstate the customer's spending mix in KPI 1.

**10. Where does `Locations` come from? Is the geography real?**
The given data only has codes like `L036`. `Locations` is a synthetic table we made up (a city and coordinates per code)
so that distances can be computed. The distances are illustrative, not real geography.

### KPIs and analytics

**11. How exactly are the five required KPIs calculated?**
- KPI 1: per customer, spend in a category ÷ total spend; the highest share is the dominant category.
- KPI 2: transaction counts and amounts by hour and weekday; hours 0–5 are the "Night" bucket and flagged as odd-hour.
- KPI 3: `(transactions − distinct merchants) / transactions` per customer; 0 means always a new merchant.
- KPI 4: share of a customer's transactions made at their home location, plus distinct locations and average distance.
- KPI 5: Digital vs. Physical (Branch + ATM) share overall, by segment and per customer.

**12. Why do 27 of 47 customers show a geo anomaly?**
Almost no transaction happens at the customer's home location in this data, and the synthetic locations are random, so
most customers score a consistency index near 0. The flag needs a low index *and* at least 2 distinct locations. It is a
property of the data, not evidence of fraud, and the dashboard says so.

**13. How would you detect fraud properly?**
Replace or complement the rules with a model such as Isolation Forest, trained on far more history per customer, with
labels where available. The current KPI flags (odd-hour, geo, channel shift, High-risk merchant) make good features for it, and the pipeline would feed the model the same
curated tables.

**14. What business decisions can the dashboard support?**
Target campaigns by dominant category (KPI 1), time marketing pushes to peak hours (KPI 2), pick loyalty partners where
repeat ratio is high (KPI 3), localise offers (KPI 4), prioritise digital-adoption campaigns for Physical-heavy segments
(KPI 5), and review the customers flagged by KPIs 2–5 first.

### Engineering and quality

**15. How do you know the SQL is correct?**
We first wrote KPIs 1–3 and 5 in pandas, then rewrote them in SQL and compared every output table: all 9 matched
(KPI 5's SQL version adds a few extra columns). KPI 4 is new and was checked for sensible values only. We also
ran the full pipeline from an empty database and tested the live refresh by adding rows to a CSV source and to a
database source. What is *not* tested: the cleansing rules on dirty data, other source types, and the dashboard in a real
browser (it was checked with Streamlit's test runner).

**16. Is the pipeline safe to re-run?**
Yes. Each SQL file drops and recreates its tables inside one transaction, ingest overwrites the landing CSVs, and the
cleaned tables are replaced each time. Running it twice gives the same result.

**17. How does it scale?**
Today the whole pipeline runs again on every change and cleansing is in memory with pandas, which is fine for thousands
of rows. For millions: load only new rows (incremental), move cleansing into the database or Spark, add indexes and
partitioning on the PostgreSQL tables, and schedule runs instead of polling.

**18. What about security and privacy?**
Customer names are personal data, and the demo database password (`bank`) is in `docker-compose.yml` for convenience;
real credentials would come from environment variables or a secrets manager (`DATABASE_URL` and `SOURCE_DATABASE_URL`
already read from the environment). Access control, masking of names in the dashboard and audit logging are not
implemented.

**19. What did you add beyond the five required KPIs?**
Distance-based geo analysis (with the synthetic locations), channel-shift and High-risk-merchant flags, multi-source
ingestion with column mapping, live refresh, a synthetic data generator for testing, and a layered pipeline whose every stage can be inspected.

**20. What would you do with more time?**
Test cleansing on deliberately dirty files, add source priority rules for conflicting records, make loads incremental,
replace the synthetic `Locations` table with real geography, add more KPIs (amount outliers, monthly spend trend, a combined customer risk score) and a trained anomaly model, and run the pipeline on a
larger public transaction dataset (section 9).

