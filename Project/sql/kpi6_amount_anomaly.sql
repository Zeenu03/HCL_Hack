-- KPI 6: Transaction Amount Anomaly (extension).
-- z-score of each transaction's Amount against the mean and sample standard deviation of its Category across all
-- customers (customers have too few transactions for a per-customer baseline). A category with a single
-- transaction or identical amounts has no spread, so z = 0. All rows are kept (dashboard scatter, KPI 8).

DROP TABLE IF EXISTS curated.kpi6_amount_anomalies;
CREATE TABLE curated.kpi6_amount_anomalies AS
WITH params AS (
    SELECT 2.0::numeric AS z_threshold  -- flag when z is above this
),
stats AS (
    SELECT t.transactionid, t.customerid, c.customername, c.segment, t.merchantid, t.category, t.channel,
           t.amount::numeric AS amount,
           AVG(t.amount::numeric)         OVER (PARTITION BY t.category) AS category_mean,
           STDDEV_SAMP(t.amount::numeric) OVER (PARTITION BY t.category) AS category_std
    FROM cleansed.transactions t
    LEFT JOIN cleansed.customers c USING (customerid)
),
scored AS (
    SELECT *, COALESCE((amount - category_mean) / NULLIF(category_std, 0), 0) AS z
    FROM stats
)
SELECT transactionid, customerid, customername, segment, merchantid, category, channel,
       round(amount, 2) AS amount,
       round(category_mean, 2) AS category_mean,
       round(category_std, 2) AS category_std,
       round(z, 2) AS amount_zscore,
       (z > params.z_threshold)::int AS amount_anomaly_flag
FROM scored
CROSS JOIN params
ORDER BY z DESC, transactionid;
