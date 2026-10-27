"""KPI 5: Digital vs. Branch Transaction Mix.

Maps each transaction's Channel to a channel group (Digital, or Physical = Branch + ATM) and
computes the percentage of Digital vs. Physical transactions overall, per Segment and per
customer. Percentages are given by transaction count and by amount.

Outputs (data/curated/):
    kpi5_channel_mix_overall.csv   - txn count / amount / share % per ChannelGroup
    kpi5_channel_mix_segment.csv   - txn count / amount / share % per Segment x ChannelGroup
    kpi5_customer_channel.csv      - one row per customer: Digital vs. Physical txns and %
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CLEANSED_DIR = DATA_DIR / "cleansed"
CURATED_DIR = DATA_DIR / "curated"

CHANNEL_GROUPS = {"Digital": "Digital", "Branch": "Physical", "ATM": "Physical"}
GROUP_ORDER = ["Digital", "Physical"]


def load_transactions():
    transactions = pd.read_csv(CLEANSED_DIR / "Transactions.csv")
    customers = pd.read_csv(CLEANSED_DIR / "Customers.csv")

    df = transactions.merge(
        customers[["CustomerID", "CustomerName", "Segment"]], on="CustomerID", how="inner"
    )
    df["ChannelGroup"] = df["Channel"].map(CHANNEL_GROUPS)
    return df


def channel_mix(df, by=()):
    """Txn count, amount and share % per ChannelGroup, within each `by` group."""
    by = list(by)
    if by:
        grid = pd.MultiIndex.from_product(
            [sorted(df[col].unique()) for col in by] + [GROUP_ORDER], names=[*by, "ChannelGroup"]
        )
    else:
        grid = pd.Index(GROUP_ORDER, name="ChannelGroup")
    mix = (
        df.groupby([*by, "ChannelGroup"])
        .agg(txn_count=("TransactionID", "count"), total_amount=("Amount", "sum"))
        .reindex(grid, fill_value=0)
        .reset_index()
    )
    if by:
        txn_total = mix.groupby(by)["txn_count"].transform("sum")
        amount_total = mix.groupby(by)["total_amount"].transform("sum")
    else:
        txn_total = mix["txn_count"].sum()
        amount_total = mix["total_amount"].sum()
    mix["txn_share_pct"] = (mix["txn_count"] / txn_total * 100).round(2)
    mix["amount_share_pct"] = (mix["total_amount"] / amount_total * 100).round(2)
    mix["total_amount"] = mix["total_amount"].round(2)
    return mix


def customer_channel(df):
    """Wide table: one row per customer with Digital vs. Physical counts and percentages."""
    counts = (
        pd.crosstab(df["CustomerID"], df["ChannelGroup"])
        .reindex(columns=GROUP_ORDER, fill_value=0)
    )
    out = (
        df.groupby("CustomerID")
        .agg(CustomerName=("CustomerName", "first"), Segment=("Segment", "first"),
             total_txns=("TransactionID", "count"))
    )
    out["digital_txns"] = counts["Digital"]
    out["physical_txns"] = counts["Physical"]
    out["digital_pct"] = (out["digital_txns"] / out["total_txns"] * 100).round(2)
    out["physical_pct"] = (out["physical_txns"] / out["total_txns"] * 100).round(2)
    return out.reset_index().sort_values(["Segment", "CustomerID"])


def run():
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    df = load_transactions()

    overall = channel_mix(df)
    segment = channel_mix(df, by=["Segment"])
    outputs = {
        "kpi5_channel_mix_overall.csv": overall,
        "kpi5_channel_mix_segment.csv": segment,
        "kpi5_customer_channel.csv": customer_channel(df),
    }
    for name, table in outputs.items():
        table.to_csv(CURATED_DIR / name, index=False)

    # Short console summary.
    pct = overall.set_index("ChannelGroup")["txn_share_pct"]
    seg_digital = segment[segment["ChannelGroup"] == "Digital"].set_index("Segment")["txn_share_pct"]
    print("\n[KPI 5] Digital vs. Branch Transaction Mix")
    print(f"  - transactions analysed : {len(df)}")
    print(f"  - overall mix           : Digital {pct['Digital']:.1f}% | Physical {pct['Physical']:.1f}%")
    print("  - digital % by segment  : " + ", ".join(f"{s} {v:.1f}%" for s, v in seg_digital.items()))
    print(f"  Written to {CURATED_DIR}: {', '.join(outputs)}")
    return outputs


if __name__ == "__main__":
    run()
