-- KPI 2: Peak Transaction Time Analysis.
-- Transaction count and amount by HourOfDay and by DayOfWeek (per Segment, so the dashboard can filter),
-- hours bucketed into Night (0-5), Morning (6-11), Afternoon (12-17), Evening (18-23).
-- Night transactions are odd-hour anomalies (odd_hour_flag = 1).

CREATE TEMP TABLE kpi2_txn_time ON COMMIT DROP AS
SELECT t.transactionid, t.customerid, c.customername, c.segment, t.merchantid,
       tm.date, tm.dayofweek, tm.hourofday, t.amount::numeric AS amount, t.category, t.channel,
       CASE WHEN tm.hourofday BETWEEN 0  AND 5  THEN 'Night'
            WHEN tm.hourofday BETWEEN 6  AND 11 THEN 'Morning'
            WHEN tm.hourofday BETWEEN 12 AND 17 THEN 'Afternoon'
            WHEN tm.hourofday BETWEEN 18 AND 23 THEN 'Evening'
            ELSE 'Unknown' END AS timebucket
FROM cleansed.transactions t
JOIN cleansed.time tm USING (timeid)
LEFT JOIN cleansed.customers c USING (customerid);

DROP TABLE IF EXISTS curated.kpi2_hourly;
CREATE TABLE curated.kpi2_hourly AS
SELECT segment, hourofday, timebucket, COUNT(*) AS txn_count, round(SUM(amount), 2) AS total_amount
FROM kpi2_txn_time
GROUP BY segment, hourofday, timebucket
ORDER BY segment, hourofday;

DROP TABLE IF EXISTS curated.kpi2_daily;
CREATE TABLE curated.kpi2_daily AS
SELECT segment, dayofweek, COUNT(*) AS txn_count, round(SUM(amount), 2) AS total_amount,
       CASE dayofweek WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 WHEN 'Thursday' THEN 4
                      WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 WHEN 'Sunday' THEN 7 END AS dayorder
FROM kpi2_txn_time
GROUP BY segment, dayofweek
ORDER BY segment, dayorder;

DROP TABLE IF EXISTS curated.kpi2_odd_hour_txns;
CREATE TABLE curated.kpi2_odd_hour_txns AS
SELECT transactionid, customerid, customername, segment, merchantid, date, dayofweek, hourofday, timebucket,
       round(amount, 2) AS amount, category, channel, 1 AS odd_hour_flag
FROM kpi2_txn_time
WHERE timebucket = 'Night'
ORDER BY date, hourofday;
