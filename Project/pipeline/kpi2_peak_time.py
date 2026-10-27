"""KPI 2: Peak Transaction Time Analysis.

Joins Transactions with Time (and Customers for Segment), counts transactions and total
amount by HourOfDay and by DayOfWeek, buckets hours into parts of the day, and flags
transactions made at night (0-5) as odd-hour anomalies.

Outputs (data/curated/):
    kpi2_hourly.csv         - txn count / amount per Segment x HourOfDay
    kpi2_daily.csv          - txn count / amount per Segment x DayOfWeek
    kpi2_odd_hour_txns.csv  - transactions with odd_hour_flag = 1
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CLEANSED_DIR = DATA_DIR / "cleansed"
CURATED_DIR = DATA_DIR / "curated"

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# (start hour, end hour inclusive, label)
TIME_BUCKETS = [
    (0, 5, "Night"),
    (6, 11, "Morning"),
    (12, 17, "Afternoon"),
    (18, 23, "Evening"),
]
ODD_HOUR_BUCKET = "Night"


def time_bucket(hours):
    conditions = [hours.between(start, end) for start, end, _ in TIME_BUCKETS]
    labels = [label for _, _, label in TIME_BUCKETS]
    return np.select(conditions, labels, default="Unknown")


def load_transactions():
    transactions = pd.read_csv(CLEANSED_DIR / "Transactions.csv")
    time = pd.read_csv(CLEANSED_DIR / "Time.csv")
    customers = pd.read_csv(CLEANSED_DIR / "Customers.csv")

    df = transactions.merge(time, on="TimeID", how="inner").merge(
        customers[["CustomerID", "CustomerName", "Segment"]], on="CustomerID", how="left"
    )
    df["TimeBucket"] = time_bucket(df["HourOfDay"])
    df["odd_hour_flag"] = (df["TimeBucket"] == ODD_HOUR_BUCKET).astype(int)
    return df


def summarize(df, by):
    """Transaction count and total amount per Segment x `by` (Segment kept for dashboard filtering)."""
    return (
        df.groupby(["Segment", *by], as_index=False)
        .agg(txn_count=("TransactionID", "count"), total_amount=("Amount", "sum"))
        .assign(total_amount=lambda d: d["total_amount"].round(2))
    )


def hourly_summary(df):
    hourly = summarize(df, ["HourOfDay", "TimeBucket"])
    return hourly.sort_values(["Segment", "HourOfDay"])


def daily_summary(df):
    daily = summarize(df, ["DayOfWeek"])
    daily["DayOrder"] = daily["DayOfWeek"].map({d: i for i, d in enumerate(DAY_ORDER, start=1)})
    return daily.sort_values(["Segment", "DayOrder"])


def odd_hour_transactions(df):
    cols = [
        "TransactionID", "CustomerID", "CustomerName", "Segment", "MerchantID",
        "Date", "DayOfWeek", "HourOfDay", "TimeBucket", "Amount", "Category", "Channel",
        "odd_hour_flag",
    ]
    odd = df[df["odd_hour_flag"] == 1]
    return odd[cols].sort_values(["Date", "HourOfDay"])


def run():
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    df = load_transactions()

    outputs = {
        "kpi2_hourly.csv": hourly_summary(df),
        "kpi2_daily.csv": daily_summary(df),
        "kpi2_odd_hour_txns.csv": odd_hour_transactions(df),
    }
    for name, table in outputs.items():
        table.to_csv(CURATED_DIR / name, index=False)

    # Short console summary of the peaks.
    by_hour = df.groupby("HourOfDay")["TransactionID"].count()
    by_day = df.groupby("DayOfWeek")["TransactionID"].count()
    by_bucket = df.groupby("TimeBucket")["TransactionID"].count()
    print("\n[KPI 2] Peak Transaction Time")
    print(f"  - transactions analysed : {len(df)}")
    print(f"  - peak hour             : {by_hour.idxmax()}:00 ({by_hour.max()} txns)")
    print(f"  - peak day              : {by_day.idxmax()} ({by_day.max()} txns)")
    print(f"  - busiest part of day   : {by_bucket.idxmax()} ({by_bucket.max()} txns)")
    print(f"  - odd-hour transactions : {df['odd_hour_flag'].sum()}")
    print(f"  Written to {CURATED_DIR}: {', '.join(outputs)}")
    return outputs


if __name__ == "__main__":
    run()
