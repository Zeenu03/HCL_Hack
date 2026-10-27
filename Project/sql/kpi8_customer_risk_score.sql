-- KPI 8: Customer Anomaly Score (extension).
-- Per customer with transactions: five 0/1 flags from the other KPIs, summed into anomaly_score (0-5), then ranked.
-- Reads the curated tables of KPIs 2-6, so it must run after them (guaranteed by file-name order).

DROP TABLE IF EXISTS curated.kpi8_customer_risk_score;
CREATE TABLE curated.kpi8_customer_risk_score AS
WITH flags AS (
    SELECT c.customerid, c.customername, c.segment,
           EXISTS (SELECT 1 FROM curated.kpi2_odd_hour_txns o WHERE o.customerid = c.customerid)::int AS odd_hour_flag,
           COALESCE(g.geo_anomaly_flag, 0)      AS geo_anomaly_flag,
           COALESCE(ch.channel_shift_flag, 0)   AS channel_shift_flag,
           COALESCE((SELECT MAX(a.amount_anomaly_flag) FROM curated.kpi6_amount_anomalies a
                     WHERE a.customerid = c.customerid), 0) AS amount_anomaly_flag,
           COALESCE(r.high_risk_flag, 0)        AS high_risk_flag
    FROM cleansed.customers c
    LEFT JOIN curated.kpi4_geo_consistency g USING (customerid)
    LEFT JOIN curated.kpi5_customer_channel ch USING (customerid)
    LEFT JOIN curated.kpi3_repeat_merchant r USING (customerid)
    WHERE c.customerid IN (SELECT customerid FROM cleansed.transactions)
),
scored AS (
    SELECT *, odd_hour_flag + geo_anomaly_flag + channel_shift_flag + amount_anomaly_flag + high_risk_flag AS anomaly_score
    FROM flags
)
SELECT customerid, customername, segment, odd_hour_flag, geo_anomaly_flag, channel_shift_flag,
       amount_anomaly_flag, high_risk_flag, anomaly_score,
       RANK() OVER (ORDER BY anomaly_score DESC) AS risk_rank
FROM scored
ORDER BY risk_rank, customerid;
