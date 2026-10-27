# Customer Transaction Analytics — Design Document

## 1. Overview

A retail bank wants to analyze customer transaction behavior to **improve personalized marketing** and **detect anomalies**.
This project builds a simple, fully local data pipeline that takes raw CSV files from a landing zone, cleanses them,
transforms them into KPI-ready tables in a curated layer, and displays the results in a dashboard that **updates live
when a row is added to a landing CSV**.

**Goal:** keep it simple and easy to run. The whole thing runs with two commands.

```
python run_pipeline.py
streamlit run app.py
```

A third, optional command generates synthetic transactions (one-off batch or a live stream) to exercise the pipeline:

```
python pipeline/generate_synthetic.py --rows 50
```

---

## 2. KPIs

| # | KPI | What it measures | Business use |
|---|-----|------------------|--------------|
| 1 | Customer Segmentation by Transaction Category | Share of spend across categories (Retail, Travel, Healthcare, Utilities) | Targeted campaigns; detect unusual category shifts |
| 2 | Peak Transaction Time Analysis | Most common hours / days customers transact | Time marketing pushes; flag odd-hour transactions |
| 3 | Repeat Merchant Ratio | How often customers return to the same merchant | Loyalty partnerships; new high-risk merchants may signal fraud |
| 4 | Geo-Location Consistency Index | How consistent transaction locations are with the customer's usual footprint | Detect location anomalies; local offers |
| 5 | Digital vs. Branch Transaction Mix | Proportion of digital vs. physical (Branch/ATM) transactions | Digital adoption campaigns; flag channel shifts |
| 6 | Transaction Amount Anomaly | How far a transaction's amount is from the norm for its category | Flag unusually large transactions |
| 7 | Monthly Spend Trend | Spend per month and category, with month-over-month change | Seasonal campaigns; detect category shifts over time |
| 8 | Customer Anomaly Score | Count of anomaly flags raised per customer across KPIs 2–6 | One ranked list of customers to review |

KPIs 1–5 are the required set; 6–8 are extensions. New KPIs are added by dropping one more `kpiN_*.py` file into
`pipeline/` (see section 6).

---

## 3. Tech Stack

| Tool | Role in the project |
|------|---------------------|
| **Python** | Main language |
| **pandas** | Load CSVs, clean data, write output files |
| **numpy** | Numeric calculations, conditional flags |
| **Streamlit** (≥ 1.37) | Dashboard to visualize all KPIs; `st.fragment(run_every=…)` gives live refresh with no extra library |

Joins and aggregations are done in pandas (`merge`, `groupby`); no database or server is needed.

Install:

```
pip install pandas numpy "streamlit>=1.37"
```

---

## 4. Source Data (Landing Zone)

Four CSV files form a simple **star schema**: one fact table and three dimension tables. A fifth, synthetic reference
table `Locations.csv` resolves the `LocationID` codes (see the table below).

| File | Type | Rows | Columns |
|------|------|------|---------|
| `Transactions.csv` | Fact | 100 | TransactionID, CustomerID, MerchantID, TimeID, LocationID, Amount, Category, Channel |
| `Customers.csv` | Dimension | 60 | CustomerID, CustomerName, Segment, HomeLocationID, PreferredChannel |
| `Merchants.csv` | Dimension | 60 | MerchantID, MerchantName, MerchantCategory, RiskLevel |
| `Time.csv` | Dimension | 60 | TimeID, Date, DayOfWeek, Month, Year, HourOfDay |
| `Locations.csv` | Reference (synthetic, new) | one row per `LocationID` in use | LocationID, City, Latitude, Longitude |

`Locations.csv` is not part of the given data. It is made up for this project and is the only new file; the four given
CSVs keep their columns exactly as they are. `Transactions.LocationID` and `Customers.HomeLocationID` both join to it.

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
- **No location table in the given data:** only `LocationID` codes (e.g. `L035`) exist. The synthetic `Locations.csv` adds a city and coordinates per code so distances can be computed; the real data itself still carries only the codes.
- **Small history per customer:** 47 of 60 customers have transactions, averaging ~2 each (max 6). Per-customer KPIs should be read with this in mind.
- **ID overlap:** `TransactionID` (`T001`…) and `TimeID` (`T1001`…) share the `T` prefix; always join on the correct column.
- Date range: Jan 2026 – Mar 2026.

---

## 5. Project Structure

```
project/
├── data/
│   ├── landing/            # raw CSVs (given)
│   ├── cleansed/           # cleaned CSVs (output of clean.py)
│   └── curated/            # KPI tables (output of kpi scripts)
├── pipeline/
│   ├── clean.py            # ingest + cleanse all raw CSVs
│   ├── kpi1_category_segmentation.py
│   ├── kpi2_peak_time.py
│   ├── kpi3_repeat_merchant.py
│   ├── kpi4_geo_consistency.py
│   ├── kpi5_channel_mix.py
│   ├── kpi6_amount_anomaly.py
│   ├── kpi7_monthly_trend.py
│   ├── kpi8_customer_risk_score.py
│   └── generate_synthetic.py   # appends synthetic rows to the landing CSVs
├── run_pipeline.py         # runs clean.py, then every pipeline/kpi*.py in name order
├── app.py                  # Streamlit dashboard
└── readme.md
```

---

## 6. End-to-End Pipeline

```
 data/landing/*.csv
        │
        ▼
 ┌───────────────┐
 │   clean.py    │  ingest + cleanse
 └──────┬────────┘
        ▼
 data/cleansed/*.csv
        │
        ▼
 ┌───────────────────────────┐
 │ kpi1.py … kpi8.py         │  transform (pandas)
 └──────┬────────────────────┘
        ▼
 data/curated/*.csv
        │
        ▼
 ┌───────────────┐   file change detected   ┌──────────────────────┐
 │    app.py     │◄─────────────────────────┤ data/landing/*.csv   │◄── row added by hand,
 │ (live refresh)│   re-runs the pipeline   └──────────────────────┘    or generate_synthetic.py
 └───────────────┘
```

`run_pipeline.py` calls `clean.py` first, then every `pipeline/kpi*.py` in file-name order (so `kpi8` runs after the
KPIs it reads), and prints a short log for each step. Each KPI script exposes a `run()` function; adding a KPI needs no
change to `run_pipeline.py`.

### Step 1 — Ingest & Cleanse (`pipeline/clean.py`)

Loads every CSV from `data/landing/`, applies the rules below, and writes the cleaned files to `data/cleansed/` with the same file names.

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

### Step 2 — Transform into Curated Layer (`pipeline/kpi*.py`)

Each KPI script reads from `data/cleansed/`, joins the tables it needs (pandas), computes the metric, and writes the result to `data/curated/`.

#### KPI 1 — Customer Segmentation by Transaction Category
- **Logic:** per customer, total spend per `Category` ÷ customer's total spend = category share. The category with the highest share is the customer's **dominant category**.
- **Also:** the same share at `Segment` level (Student / Premium / Standard).
- **Output:** `kpi1_customer_category_share.csv`, `kpi1_segment_category_share.csv`

#### KPI 2 — Peak Transaction Time Analysis
- **Logic:** join with `Time`; count transactions and total amount by `HourOfDay` and by `DayOfWeek`. Bucket hours into Night (0–5), Morning (6–11), Afternoon (12–17), Evening (18–23).
- **Anomaly flag:** transactions in the Night bucket (0–5) → `odd_hour_flag = 1`.
- **Output:** `kpi2_hourly.csv`, `kpi2_daily.csv`, `kpi2_odd_hour_txns.csv`

#### KPI 3 — Repeat Merchant Ratio
- **Logic:** per customer,
  `repeat_merchant_ratio = (total_txns − unique_merchants) / total_txns`
  (0 = always a new merchant, closer to 1 = very loyal).
- **Also:** share of each customer's transactions with `High` risk merchants.
- **Output:** `kpi3_repeat_merchant.csv`

#### KPI 4 — Geo-Location Consistency Index
- **Logic:** per customer,
  `geo_consistency_index = txns where LocationID == HomeLocationID / total_txns`
  plus `distinct_locations` count and, using `Locations.csv`, the average distance (km) of a customer's transactions
  from their home location.
- **Anomaly flag:** customers with low index and multiple distinct locations → `geo_anomaly_flag = 1`.
- **Note:** in the current data almost no transactions happen at the home location, so most customers will score low. This is a data characteristic, worth calling out in the dashboard.
- **Output:** `kpi4_geo_consistency.csv`

#### KPI 5 — Digital vs. Branch Transaction Mix
- **Logic:** map `Channel` → `Digital` vs. `Physical` (Branch + ATM). Compute share overall, by `Segment`, and per customer.
- **Anomaly flag:** customers whose most-used channel differs from their `PreferredChannel` → `channel_shift_flag = 1`.
- **Output:** `kpi5_channel_mix_overall.csv`, `kpi5_channel_mix_segment.csv`, `kpi5_customer_channel.csv`

#### KPI 6 — Transaction Amount Anomaly (extension)
- **Logic:** z-score of each transaction's `Amount` against the mean and standard deviation of its `Category` across all
  customers. Customers have only ~2 transactions each, so a per-customer baseline would be too thin.
- **Anomaly flag:** `z > 2` → `amount_anomaly_flag = 1` (threshold is a constant at the top of the script).
- **Output:** `kpi6_amount_anomalies.csv`

#### KPI 7 — Monthly Spend Trend (extension)
- **Logic:** total spend and transaction count by `Year`, `Month` and `Category`; month-over-month % change per category.
- **Also:** the category whose share moved most in the latest month (`category_shift`).
- **Output:** `kpi7_monthly_spend.csv`

#### KPI 8 — Customer Anomaly Score (extension)
- **Logic:** per customer, sum of `odd_hour_flag` (KPI 2), `geo_anomaly_flag` (KPI 4), `channel_shift_flag` (KPI 5),
  `amount_anomaly_flag` (KPI 6) and a high-risk-merchant flag (KPI 3: any `High` risk merchant). Rank customers by score.
- **Reads:** the curated outputs of KPIs 2–6, so it must run last (guaranteed by the file-name ordering).
- **Output:** `kpi8_customer_risk_score.csv`

### Step 3 — Dashboard (`app.py`)

A Streamlit app that reads only from `data/curated/` (no calculations in the UI).

| Section | Visuals |
|---------|---------|
| Overview | Total transactions, total amount, active customers, anomaly counts |
| KPI 1 | Stacked bar of category share by segment; table of dominant category per customer |
| KPI 2 | Bar chart by hour, bar chart by day of week; table of odd-hour transactions |
| KPI 3 | Distribution of repeat merchant ratio; top loyal customers; high-risk merchant exposure |
| KPI 4 | Geo consistency index per customer; flagged customers |
| KPI 5 | Digital vs. Physical split (overall + by segment); channel-shift customers |
| KPI 6 | Table of flagged high-amount transactions; amount vs. category scatter |
| KPI 7 | Line chart of monthly spend by category; month-over-month change table |
| KPI 8 | Ranked table of customers by anomaly score |

A sidebar filter for `Segment` lets the user slice the views.

### Live Updates

The dashboard refreshes itself when a row is added to any file in `data/landing/`.

1. The dashboard body is wrapped in `@st.fragment(run_every="3s")`, so it reruns every 3 seconds.
2. On each run, `app.py` compares the modified times of the landing CSVs with those seen on the previous run.
3. If any changed, `app.py` calls `run_pipeline.py` (clean + all KPIs), then reloads `data/curated/`.
4. The page shows "Last refreshed at …" and the current transaction count, so a new row is visibly picked up.

A live toggle in the sidebar turns auto-refresh off. The dashboard still only *reads* curated data; its only extra job is
to trigger the pipeline.

To try it: run `streamlit run app.py`, then either append a line to `data/landing/Transactions.csv` by hand or run
`python pipeline/generate_synthetic.py --interval 5` in a second terminal.

### Synthetic Data Generation (`pipeline/generate_synthetic.py`)

"Synthetic data" here means one thing only: **adding more rows to the existing CSVs**. No column is added, removed or
renamed in any given file. The generator only appends rows, so the pipeline and live dashboard can be tested beyond the
100 given rows. The one new file, `Locations.csv`, is a synthetic reference table that is created once and can also grow
with new rows.

| Option | Meaning |
|--------|---------|
| `--rows N` | Append `N` transactions in one go (default 50) |
| `--interval S` | Append one transaction every `S` seconds, until stopped (live demo) |
| `--anomaly-rate P` | Fraction of rows deliberately made anomalous (default 0.05) |
| `--seed K` | Fixed random seed for reproducible data |

How rows are built:
- `CustomerID`, `MerchantID` and `LocationID` are sampled from the existing dimension tables (and `Locations.csv`), so
  referential integrity holds.
- Rows may also be appended to `Customers.csv` and `Merchants.csv` (with `--new-customers K` / `--new-merchants K`) to grow
  the dimensions, again using only their existing columns.
- `Category`, `Channel` and `Amount` follow the distributions in the current data; the customer's `PreferredChannel` is
  favoured so the channel-shift KPI has a baseline.
- A new `Time.csv` row is appended for each new timestamp, with a fresh `TimeID` that continues the existing numbering;
  `TransactionID` also continues its own numbering.
- Anomalous rows are produced by picking one of: night hour (0–5), a location far from the customer's home, an amount
  well above the category mean, a `High` risk merchant, or a channel different from the customer's preference. These
  trigger the flags in KPIs 2–6 and make KPI 8 meaningful.
- Each row is written with a single append, so the dashboard never reads a half-written line.

Generated rows go into the same landing files as the real data; keep a copy of the original CSVs if you need to reset.

---

## 7. How to Run

1. Place the raw CSV files in `data/landing/`.
2. Install dependencies: `pip install pandas numpy "streamlit>=1.37"`
3. Run the pipeline: `python run_pipeline.py`
4. Open the dashboard: `streamlit run app.py`
5. (Optional) Watch it update live: in a second terminal run `python pipeline/generate_synthetic.py --interval 5`

---

## 8. Assumptions & Limitations

- Data is small (100 transactions), so everything runs in memory with pandas; no distributed tools needed.
- Live update re-runs the whole pipeline whenever a landing file changes (polling every 3 s). That is fine at this size
  but would need incremental processing at larger volumes.
- Synthetic rows follow simple sampling rules; they test the pipeline and dashboard, not real banking behaviour.
- `LocationID` has no lookup table in the given data. `Locations.csv` is synthetic, so distances are illustrative, not real geography.
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
- **Approach:** a small adapter script (`pipeline/adapters/<dataset>.py`) reshapes the download into our four landing
  CSVs (`Transactions`, `Customers`, `Merchants`, `Time`) with the same column names. Everything after that, from
  `clean.py` to the dashboard, runs unchanged.
- **Mapping gaps to handle:** invented `LocationID` values (for example from a rounded latitude/longitude or the
  city), a derived `Channel` where the dataset has none, and `Segment` / `RiskLevel` / `PreferredChannel` derived from
  spend or fraud rate where missing.
- **What it shows:** how the KPIs behave with far more history per customer, and, if the dataset has fraud labels, how
  well our anomaly flags line up with them. A sample of a few thousand rows is enough.

### Other ideas

- Store curated tables as Parquet instead of CSV.
- Process only new rows (incremental load) instead of re-running the whole pipeline on every change.
- Replace the synthetic `Locations.csv` with a real location dimension (city/country) for real distance-based geo anomalies.
- Schedule the pipeline (e.g. Prefect / cron) for daily loads.
- Add clustering (scikit-learn KMeans) on category shares for richer segments.
