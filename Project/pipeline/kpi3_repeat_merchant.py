"""KPI 3: Repeat Merchant Ratio.

Per customer, measures how often they return to a merchant they have already used:
    repeat_merchant_ratio = (total_txns - unique_merchants) / total_txns
(0 = every transaction at a new merchant, closer to 1 = very loyal). Also reports the
share of the customer's transactions made with High-risk merchants.

Outputs (data/curated/):
    kpi3_repeat_merchant.csv - one row per customer that has transactions
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CLEANSED_DIR = DATA_DIR / "cleansed"
CURATED_DIR = DATA_DIR / "curated"

HIGH_RISK = "High"


def load_transactions():
    transactions = pd.read_csv(CLEANSED_DIR / "Transactions.csv")
    merchants = pd.read_csv(CLEANSED_DIR / "Merchants.csv")
    customers = pd.read_csv(CLEANSED_DIR / "Customers.csv")

    df = transactions.merge(merchants[["MerchantID", "RiskLevel"]], on="MerchantID", how="left")
    df["is_high_risk"] = (df["RiskLevel"] == HIGH_RISK).astype(int)
    return df, customers


def repeat_merchant_ratio(df, customers):
    per_customer = df.groupby("CustomerID", as_index=False).agg(
        total_txns=("TransactionID", "count"),
        unique_merchants=("MerchantID", "nunique"),
        high_risk_txns=("is_high_risk", "sum"),
    )
    per_customer["repeat_txns"] = per_customer["total_txns"] - per_customer["unique_merchants"]
    per_customer["repeat_merchant_ratio"] = (per_customer["repeat_txns"] / per_customer["total_txns"]).round(4)
    per_customer["high_risk_share"] = (per_customer["high_risk_txns"] / per_customer["total_txns"]).round(4)
    # Consumed by KPI 8: customer has at least one High-risk merchant transaction.
    per_customer["high_risk_flag"] = (per_customer["high_risk_txns"] > 0).astype(int)

    out = per_customer.merge(customers[["CustomerID", "CustomerName", "Segment"]], on="CustomerID", how="left")
    cols = [
        "CustomerID", "CustomerName", "Segment", "total_txns", "unique_merchants", "repeat_txns",
        "repeat_merchant_ratio", "high_risk_txns", "high_risk_share", "high_risk_flag",
    ]
    return out[cols].sort_values(["repeat_merchant_ratio", "total_txns"], ascending=False)


def run():
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    df, customers = load_transactions()
    result = repeat_merchant_ratio(df, customers)
    result.to_csv(CURATED_DIR / "kpi3_repeat_merchant.csv", index=False)

    repeaters = (result["repeat_txns"] > 0).sum()
    print("\n[KPI 3] Repeat Merchant Ratio")
    print(f"  - customers analysed        : {len(result)}")
    print(f"  - customers with a repeat   : {repeaters}")
    print(f"  - mean repeat ratio         : {result['repeat_merchant_ratio'].mean():.3f}")
    print(f"  - customers using High risk : {result['high_risk_flag'].sum()}")
    print(f"  Written to {CURATED_DIR}: kpi3_repeat_merchant.csv")
    return {"kpi3_repeat_merchant.csv": result}


if __name__ == "__main__":
    run()
