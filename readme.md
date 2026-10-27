# Customer Transaction Analytics — Design Document

## 1. Overview

A retail bank wants to analyze customer transaction behavior to **improve personalized marketing** and **detect anomalies**.
This project builds a simple, fully local data pipeline that takes raw CSV files from a landing zone, cleanses them,
transforms them into KPI-ready tables in a curated layer, and displays the results in a dashboard.

**Goal:** keep it simple and easy to run. The whole thing runs with two commands.

```
python run_pipeline.py
streamlit run app.py
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

---

## 3. Tech Stack

| Tool | Role in the project |
|------|---------------------|
| **Python** | Main language |
| **pandas** | Load CSVs, clean data, write output files |
| **numpy** | Numeric calculations, conditional flags |
| **DuckDB** | SQL on top of DataFrames / CSVs for joins and aggregations in KPI scripts (no server needed) |
| **Streamlit** | Dashboard to visualize all 5 KPIs |

Install:

```
pip install pandas numpy duckdb streamlit
```

---

## 4. Source Data (Landing Zone)

Four CSV files form a simple **star schema**: one fact table and three dimension tables.

| File | Type | Rows | Columns |
|------|------|------|---------|
| `Transactions.csv` | Fact | 100 | TransactionID, CustomerID, MerchantID, TimeID, LocationID, Amount, Category, Channel |
| `Customers.csv` | Dimension | 60 | CustomerID, CustomerName, Segment, HomeLocationID, PreferredChannel |
| `Merchants.csv` | Dimension | 60 | MerchantID, MerchantName, MerchantCategory, RiskLevel |
| `Time.csv` | Dimension | 60 | TimeID, Date, DayOfWeek, Month, Year, HourOfDay |

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
- **No location table:** only `LocationID` codes (e.g. `L035`) exist, so geo analysis compares IDs, not real distances.
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
│   └── kpi5_channel_mix.py
├── run_pipeline.py         # runs all steps in order
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
 │ kpi1.py … kpi5.py         │  transform (pandas + DuckDB SQL)
 └──────┬────────────────────┘
        ▼
 data/curated/*.csv
        │
        ▼
 ┌───────────────┐
 │    app.py     │  Streamlit dashboard
 └───────────────┘
```

`run_pipeline.py` calls `clean.py` first, then the five KPI scripts in order, and prints a short log for each step.

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

Each KPI script reads from `data/cleansed/`, joins the tables it needs (DuckDB SQL), computes the metric, and writes the result to `data/curated/`.

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
  plus `distinct_locations` count.
- **Anomaly flag:** customers with low index and multiple distinct locations → `geo_anomaly_flag = 1`.
- **Note:** in the current data almost no transactions happen at the home location, so most customers will score low. This is a data characteristic, worth calling out in the dashboard.
- **Output:** `kpi4_geo_consistency.csv`

#### KPI 5 — Digital vs. Branch Transaction Mix
- **Logic:** map `Channel` → `Digital` vs. `Physical` (Branch + ATM). Compute share overall, by `Segment`, and per customer.
- **Anomaly flag:** customers whose most-used channel differs from their `PreferredChannel` → `channel_shift_flag = 1`.
- **Output:** `kpi5_channel_mix_overall.csv`, `kpi5_channel_mix_segment.csv`, `kpi5_customer_channel.csv`

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

A sidebar filter for `Segment` lets the user slice the views.

---

## 7. How to Run

1. Place the raw CSV files in `data/landing/`.
2. Install dependencies: `pip install pandas numpy duckdb streamlit`
3. Run the pipeline: `python run_pipeline.py`
4. Open the dashboard: `streamlit run app.py`

---

## 8. Assumptions & Limitations

- Data is small (100 transactions), so everything runs in memory with pandas/DuckDB; no distributed tools needed.
- `LocationID` has no lookup table, so geo consistency is ID-based, not distance-based.
- Per-customer KPIs are based on few transactions and are indicative, not statistically strong.
- `Transactions.Category` is treated as the source of truth for spend category.

## 9. Future Enhancements

- Store curated tables as Parquet instead of CSV.
- Add a location dimension (city/country) for real distance-based geo anomalies.
- Schedule the pipeline (e.g. Prefect / cron) for daily loads.
- Add clustering (scikit-learn KMeans) on category shares for richer segments.
