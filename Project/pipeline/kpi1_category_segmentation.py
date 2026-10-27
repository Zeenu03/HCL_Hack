"""KPI 1: Customer Segmentation by Transaction Category.

Joins Transactions with Customers, computes each customer's share of spend per Category
(customer's spend in a category / customer's total spend), and picks the category with the
highest share as the customer's dominant category. The same share is computed per Segment.
Transactions.Category is used as the spend category (it disagrees with
Merchants.MerchantCategory in most rows; see readme).

Outputs (data/curated/):
    kpi1_customer_category_share.csv  - one row per customer: spend and share % per category,
                                        dominant category
    kpi1_segment_category_share.csv   - txn count / amount / share % per Segment x Category
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CLEANSED_DIR = DATA_DIR / "cleansed"
CURATED_DIR = DATA_DIR / "curated"

CATEGORIES = ["Retail", "Travel", "Healthcare", "Utilities"]


def load_transactions():
    transactions = pd.read_csv(CLEANSED_DIR / "Transactions.csv")
    customers = pd.read_csv(CLEANSED_DIR / "Customers.csv")

    return transactions.merge(
        customers[["CustomerID", "CustomerName", "Segment"]], on="CustomerID", how="inner"
    )


def customer_category_share(df):
    """Wide table: one row per customer with spend and share % for every category."""
    spend = (
        df.pivot_table(index="CustomerID", columns="Category", values="Amount", aggfunc="sum", fill_value=0)
        .reindex(columns=CATEGORIES, fill_value=0)
    )
    total = spend.sum(axis=1)
    share = spend.div(total, axis=0).mul(100).round(2)

    out = (
        df.groupby("CustomerID", as_index=False)
        .agg(CustomerName=("CustomerName", "first"), Segment=("Segment", "first"),
             txn_count=("TransactionID", "count"))
        .set_index("CustomerID")
    )
    out["total_spend"] = total.round(2)
    for cat in CATEGORIES:
        out[f"{cat}_spend"] = spend[cat].round(2)
    for cat in CATEGORIES:
        out[f"{cat}_share_pct"] = share[cat]

    # Ties go to the first category in CATEGORIES order.
    out["dominant_category"] = share.idxmax(axis=1)
    out["dominant_share_pct"] = share.max(axis=1)
    return out.reset_index().sort_values(["Segment", "CustomerID"])


def segment_category_share(df):
    """Long table (Segment x Category) so the dashboard can draw a stacked bar."""
    grid = pd.MultiIndex.from_product(
        [sorted(df["Segment"].unique()), CATEGORIES], names=["Segment", "Category"]
    )
    seg = (
        df.groupby(["Segment", "Category"])
        .agg(txn_count=("TransactionID", "count"), total_amount=("Amount", "sum"))
        .reindex(grid, fill_value=0)
        .reset_index()
    )
    seg_total = seg.groupby("Segment")["total_amount"].transform("sum")
    seg["spend_share_pct"] = (seg["total_amount"] / seg_total * 100).round(2)
    seg["total_amount"] = seg["total_amount"].round(2)
    return seg


def run():
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    df = load_transactions()

    customers = customer_category_share(df)
    segments = segment_category_share(df)
    outputs = {
        "kpi1_customer_category_share.csv": customers,
        "kpi1_segment_category_share.csv": segments,
    }
    for name, table in outputs.items():
        table.to_csv(CURATED_DIR / name, index=False)

    # Short console summary.
    overall = (df.groupby("Category")["Amount"].sum() / df["Amount"].sum() * 100).reindex(CATEGORIES, fill_value=0)
    dominant = customers["dominant_category"].value_counts().reindex(CATEGORIES, fill_value=0)
    print("\n[KPI 1] Customer Segmentation by Transaction Category")
    print(f"  - transactions analysed : {len(df)}")
    print(f"  - customers profiled    : {len(customers)}")
    print("  - overall spend share   : " + ", ".join(f"{c} {overall[c]:.1f}%" for c in CATEGORIES))
    print("  - customers by dominant : " + ", ".join(f"{c} {dominant[c]}" for c in CATEGORIES))
    print(f"  Written to {CURATED_DIR}: {', '.join(outputs)}")
    return outputs


if __name__ == "__main__":
    run()
