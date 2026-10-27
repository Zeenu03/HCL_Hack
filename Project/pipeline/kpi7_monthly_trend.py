"""KPI 7: Monthly Spend Trend (extension).

Joins Transactions with Time, totals spend and transaction count per month and category,
adds month-over-month % change per category, and marks the category whose share of
monthly spend moved the most in the latest month (category_shift).

Outputs (data/curated/):
    kpi7_monthly_spend.csv - one row per Year x Month x Category (months with no spend appear as 0)
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CLEANSED_DIR = DATA_DIR / "cleansed"
CURATED_DIR = DATA_DIR / "curated"


def load_transactions():
    transactions = pd.read_csv(CLEANSED_DIR / "Transactions.csv")
    time = pd.read_csv(CLEANSED_DIR / "Time.csv")
    df = transactions.merge(time, on="TimeID", how="inner")
    # Time.Month is a name ("Jan"); build a real month number so months sort correctly.
    df["MonthNum"] = pd.to_datetime(df["Date"]).dt.month
    return df


def monthly_spend(df):
    monthly = df.groupby(["Year", "MonthNum", "Month", "Category"], as_index=False).agg(
        total_spend=("Amount", "sum"), txn_count=("TransactionID", "count")
    )

    # Full month x category grid so a month with no spend shows as 0, not a missing row.
    month_names = df.drop_duplicates(["Year", "MonthNum"]).set_index(["Year", "MonthNum"])["Month"]
    periods = pd.period_range(
        pd.to_datetime(df["Date"]).min(), pd.to_datetime(df["Date"]).max(), freq="M"
    )
    grid = pd.MultiIndex.from_product(
        [[(p.year, p.month) for p in periods], sorted(df["Category"].unique())], names=["period", "Category"]
    ).to_frame(index=False)
    grid["Year"] = grid["period"].str[0]
    grid["MonthNum"] = grid["period"].str[1]
    grid["Month"] = [month_names.get((y, m), pd.Timestamp(year=y, month=m, day=1).strftime("%b"))
                     for y, m in grid["period"]]
    monthly = grid.drop(columns="period").merge(
        monthly, on=["Year", "MonthNum", "Month", "Category"], how="left"
    ).fillna({"total_spend": 0.0, "txn_count": 0})
    monthly["txn_count"] = monthly["txn_count"].astype(int)
    monthly = monthly.sort_values(["Category", "Year", "MonthNum"]).reset_index(drop=True)

    # Month-over-month % change per category; undefined (blank) when the previous month is 0.
    previous = monthly.groupby("Category")["total_spend"].shift()
    monthly["mom_change_pct"] = ((monthly["total_spend"] - previous) / previous.where(previous > 0) * 100).round(2)

    # Category share of each month's total spend, and its change (percentage points) vs. the month before.
    month_total = monthly.groupby(["Year", "MonthNum"])["total_spend"].transform("sum")
    monthly["category_share"] = (monthly["total_spend"] / month_total.where(month_total > 0)).round(4)
    monthly["share_change_pp"] = (monthly.groupby("Category")["category_share"].diff() * 100).round(2)

    # category_shift = 1 on the single row (latest month) whose share moved the most.
    monthly["category_shift"] = 0
    latest = monthly[(monthly["Year"] == monthly["Year"].max())]
    latest = latest[latest["MonthNum"] == latest["MonthNum"].max()]
    if latest["share_change_pp"].notna().any():
        monthly.loc[latest["share_change_pp"].abs().idxmax(), "category_shift"] = 1

    cols = [
        "Year", "MonthNum", "Month", "Category", "total_spend", "txn_count",
        "mom_change_pct", "category_share", "share_change_pp", "category_shift",
    ]
    monthly["total_spend"] = monthly["total_spend"].round(2)
    return monthly[cols].sort_values(["Year", "MonthNum", "Category"])


def run():
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    df = load_transactions()
    result = monthly_spend(df)
    result.to_csv(CURATED_DIR / "kpi7_monthly_spend.csv", index=False)

    by_month = df.groupby(["Year", "MonthNum", "Month"])["Amount"].sum()
    shift = result[result["category_shift"] == 1]
    print("\n[KPI 7] Monthly Spend Trend")
    print(f"  - transactions analysed : {len(df)}")
    print(f"  - months covered        : {len(by_month)}")
    print(f"  - highest-spend month   : {by_month.idxmax()[2]} {by_month.idxmax()[0]} ({by_month.max():,.2f})")
    if not shift.empty:
        row = shift.iloc[0]
        print(f"  - latest category shift : {row['Category']} ({row['share_change_pp']:+.2f} pp in {row['Month']})")
    print(f"  Written to {CURATED_DIR}: kpi7_monthly_spend.csv")
    return {"kpi7_monthly_spend.csv": result}


if __name__ == "__main__":
    run()
