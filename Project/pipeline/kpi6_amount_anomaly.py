"""KPI 6: Transaction Amount Anomaly.

Scores each transaction's Amount with a z-score against the mean and standard deviation
of its Category across all customers (customers have too few transactions for a
per-customer baseline), and flags transactions with z > Z_THRESHOLD.

Output (data/curated/):
    kpi6_amount_anomalies.csv - every transaction with its category stats, z-score and
                                amount_anomaly_flag (all rows kept for the dashboard
                                scatter and for KPI 8)
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CLEANSED_DIR = DATA_DIR / "cleansed"
CURATED_DIR = DATA_DIR / "curated"

Z_THRESHOLD = 2.0


def load_transactions():
    transactions = pd.read_csv(CLEANSED_DIR / "Transactions.csv")
    customers = pd.read_csv(CLEANSED_DIR / "Customers.csv")
    return transactions.merge(
        customers[["CustomerID", "CustomerName", "Segment"]], on="CustomerID", how="left"
    )


def score_amounts(df):
    stats = df.groupby("Category")["Amount"]
    df["category_mean"] = stats.transform("mean")
    df["category_std"] = stats.transform("std")

    # A category with a single transaction (or identical amounts) has no spread: z = 0.
    z = (df["Amount"] - df["category_mean"]) / df["category_std"].replace(0, np.nan)
    df["amount_zscore"] = z.fillna(0)
    df["amount_anomaly_flag"] = (df["amount_zscore"] > Z_THRESHOLD).astype(int)

    for col in ["category_mean", "category_std", "amount_zscore"]:
        df[col] = df[col].round(2)
    return df


def run():
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    df = score_amounts(load_transactions())

    cols = [
        "TransactionID", "CustomerID", "CustomerName", "Segment", "MerchantID",
        "Category", "Channel", "Amount", "category_mean", "category_std",
        "amount_zscore", "amount_anomaly_flag",
    ]
    output = df[cols].sort_values("amount_zscore", ascending=False)
    output.to_csv(CURATED_DIR / "kpi6_amount_anomalies.csv", index=False)

    flagged = output[output["amount_anomaly_flag"] == 1]
    print("\n[KPI 6] Transaction Amount Anomaly")
    print(f"  - transactions scored   : {len(output)}")
    print(f"  - z-score threshold     : {Z_THRESHOLD}")
    print(f"  - highest z-score       : {output['amount_zscore'].max()}")
    print(f"  - flagged transactions  : {len(flagged)}")
    print(f"  Written to {CURATED_DIR}: kpi6_amount_anomalies.csv")
    return output


if __name__ == "__main__":
    run()
