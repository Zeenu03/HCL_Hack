"""Streamlit dashboard. Reads only the `curated` schema; its one extra job is to re-run the pipeline when any
configured source changes (a source CSV is modified, or a source database table gains or loses rows), so new data
appears live.

    streamlit run app.py
"""

import sys
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pipeline"))

import ingest  # noqa: E402
import run_pipeline  # noqa: E402
from db import get_engine  # noqa: E402

SEGMENTS = ["All", "Student", "Premium", "Standard"]

st.set_page_config(page_title="Customer Transaction Analytics", layout="wide")


@st.cache_resource
def engine():
    return get_engine()


@st.cache_resource
def pipeline_lock():
    return threading.Lock()


def curated_ready():
    with engine().connect() as conn:
        return conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'curated' AND table_name = 'kpi8_customer_risk_score'")).scalar() > 0


def refresh_if_changed():
    signature = ingest.signature()  # changes when any configured source (CSV or database) changes
    if st.session_state.get("signature") == signature and curated_ready():
        return
    with pipeline_lock(), st.spinner("Source data changed, re-running the pipeline..."):
        run_pipeline.main()
    st.session_state["signature"] = signature
    st.session_state["refreshed_at"] = datetime.now()


def table(name):
    return pd.read_sql(f"SELECT * FROM curated.{name}", engine())


def dashboard(segment):
    refresh_if_changed()

    def seg(df):
        if segment != "All" and "segment" in df.columns:
            return df[df["segment"] == segment]
        return df

    txns = seg(table("kpi6_amount_anomalies"))
    risk = seg(table("kpi8_customer_risk_score"))
    odd = seg(table("kpi2_odd_hour_txns"))
    geo = seg(table("kpi4_geo_consistency"))

    st.title("Customer Transaction Analytics")
    st.caption(f"Last refreshed at {st.session_state.get('refreshed_at', datetime.now()):%H:%M:%S}"
               f" - segment: {segment}")

    cols = st.columns(6)
    cols[0].metric("Transactions", f"{len(txns):,}")
    cols[1].metric("Total amount", f"{txns['amount'].sum():,.0f}")
    cols[2].metric("Active customers", f"{txns['customerid'].nunique():,}")
    cols[3].metric("Odd-hour txns", f"{len(odd):,}")
    cols[4].metric("Amount anomalies", f"{int(txns['amount_anomaly_flag'].sum()):,}")
    cols[5].metric("Customers with a flag", f"{int((risk['anomaly_score'] > 0).sum()):,}")

    tabs = st.tabs([f"KPI {i}" for i in range(1, 9)])

    with tabs[0]:
        st.subheader("Customer Segmentation by Transaction Category")
        share = seg(table("kpi1_segment_category_share"))
        st.bar_chart(share.pivot(index="segment", columns="category", values="spend_share_pct"))
        customers = seg(table("kpi1_customer_category_share"))
        st.dataframe(customers[["customerid", "customername", "segment", "dominant_category",
                                "dominant_share_pct", "total_spend"]], hide_index=True)

    with tabs[1]:
        st.subheader("Peak Transaction Time Analysis")
        hourly = seg(table("kpi2_hourly")).groupby("hourofday")["txn_count"].sum()
        daily = seg(table("kpi2_daily")).groupby(["dayorder", "dayofweek"])["txn_count"].sum().reset_index()
        left, right = st.columns(2)
        left.bar_chart(hourly)
        right.bar_chart(daily.set_index("dayofweek")["txn_count"])
        st.write("Odd-hour (night) transactions")
        st.dataframe(odd, hide_index=True)

    with tabs[2]:
        st.subheader("Repeat Merchant Ratio")
        repeat = seg(table("kpi3_repeat_merchant"))
        bins = pd.cut(repeat["repeat_merchant_ratio"], [-0.001, 0, 0.25, 0.5, 0.75, 1.0],
                      labels=["0", "0-0.25", "0.25-0.5", "0.5-0.75", "0.75-1"])
        st.bar_chart(bins.value_counts().reindex(["0", "0-0.25", "0.25-0.5", "0.5-0.75", "0.75-1"]))
        left, right = st.columns(2)
        left.write("Most loyal customers")
        left.dataframe(repeat.head(10)[["customerid", "customername", "total_txns", "repeat_merchant_ratio"]],
                       hide_index=True)
        right.write("High-risk merchant exposure")
        right.dataframe(repeat[repeat["high_risk_flag"] == 1][["customerid", "customername", "high_risk_txns",
                                                              "high_risk_share"]], hide_index=True)

    with tabs[3]:
        st.subheader("Geo-Location Consistency Index")
        st.caption("Locations are synthetic, so distances are illustrative.")
        st.bar_chart(geo.set_index("customerid")["avg_distance_km"])
        st.write("Flagged customers (low consistency, several locations)")
        st.dataframe(geo[geo["geo_anomaly_flag"] == 1], hide_index=True)

    with tabs[4]:
        st.subheader("Digital vs. Branch Transaction Mix")
        left, right = st.columns(2)
        left.write("Overall")
        left.bar_chart(table("kpi5_channel_mix_overall").set_index("channelgroup")["txn_share_pct"])
        right.write("By segment")
        by_segment = seg(table("kpi5_channel_mix_segment"))
        right.bar_chart(by_segment.pivot(index="segment", columns="channelgroup", values="txn_share_pct"))
        st.write("Customers whose preferred channel is not among their most-used")
        shifted = seg(table("kpi5_customer_channel"))
        st.dataframe(shifted[shifted["channel_shift_flag"] == 1], hide_index=True)

    with tabs[5]:
        st.subheader("Transaction Amount Anomaly")
        st.scatter_chart(txns, x="amount", y="amount_zscore", color="category")
        st.dataframe(txns[txns["amount_anomaly_flag"] == 1], hide_index=True)

    with tabs[6]:
        st.subheader("Monthly Spend Trend")
        monthly = table("kpi7_monthly_spend")
        monthly["period"] = monthly["year"].astype(str) + "-" + monthly["monthnum"].astype(str).str.zfill(2)
        st.line_chart(monthly.pivot(index="period", columns="category", values="total_spend"))
        st.dataframe(monthly, hide_index=True)

    with tabs[7]:
        st.subheader("Customer Anomaly Score")
        st.dataframe(risk, hide_index=True)


live = st.sidebar.toggle("Live updates (every 3 s)", value=True)
segment = st.sidebar.selectbox("Segment", SEGMENTS)
st.sidebar.caption("Add a row to any source (CSV or database) and the dashboard re-runs the pipeline.")

# The fragment reruns on its own timer; the sidebar widgets stay outside it.
st.fragment(run_every="3s" if live else None)(dashboard)(segment)
