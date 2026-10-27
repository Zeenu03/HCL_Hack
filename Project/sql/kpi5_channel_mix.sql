-- KPI 5: Digital vs. Branch Transaction Mix.
-- Channel -> channel group (Digital, or Physical = Branch + ATM); share by count and amount overall, per Segment
-- and per customer. channel_shift_flag = 1 when a customer's PreferredChannel is not among their most-used
-- channels (ties for most-used do not count as a shift). The flag is read by KPI 8.

CREATE TEMP TABLE kpi5_txn ON COMMIT DROP AS
SELECT t.transactionid, t.customerid, c.customername, c.segment, c.preferredchannel, t.channel,
       t.amount::numeric AS amount,
       CASE WHEN t.channel = 'Digital' THEN 'Digital' ELSE 'Physical' END AS channelgroup
FROM cleansed.transactions t
JOIN cleansed.customers c USING (customerid);

DROP TABLE IF EXISTS curated.kpi5_channel_mix_overall;
CREATE TABLE curated.kpi5_channel_mix_overall AS
WITH g(channelgroup) AS (VALUES ('Digital'), ('Physical')),
agg AS (
    SELECT g.channelgroup, COUNT(k.amount) AS txn_count, COALESCE(SUM(k.amount), 0) AS total_amount
    FROM g LEFT JOIN kpi5_txn k USING (channelgroup)
    GROUP BY g.channelgroup
)
SELECT channelgroup, txn_count, round(total_amount, 2) AS total_amount,
       round(txn_count::numeric / SUM(txn_count) OVER () * 100, 2) AS txn_share_pct,
       round(total_amount / SUM(total_amount) OVER () * 100, 2) AS amount_share_pct
FROM agg
ORDER BY channelgroup;

DROP TABLE IF EXISTS curated.kpi5_channel_mix_segment;
CREATE TABLE curated.kpi5_channel_mix_segment AS
WITH g AS (
    SELECT s.segment, x.channelgroup
    FROM (SELECT DISTINCT segment FROM kpi5_txn) s
    CROSS JOIN (VALUES ('Digital'), ('Physical')) AS x(channelgroup)
),
agg AS (
    SELECT g.segment, g.channelgroup, COUNT(k.amount) AS txn_count, COALESCE(SUM(k.amount), 0) AS total_amount
    FROM g LEFT JOIN kpi5_txn k ON k.segment = g.segment AND k.channelgroup = g.channelgroup
    GROUP BY g.segment, g.channelgroup
)
SELECT segment, channelgroup, txn_count, round(total_amount, 2) AS total_amount,
       round(txn_count::numeric / SUM(txn_count) OVER (PARTITION BY segment) * 100, 2) AS txn_share_pct,
       round(total_amount / SUM(total_amount) OVER (PARTITION BY segment) * 100, 2) AS amount_share_pct
FROM agg
ORDER BY segment, channelgroup;

DROP TABLE IF EXISTS curated.kpi5_customer_channel;
CREATE TABLE curated.kpi5_customer_channel AS
WITH by_channel AS (
    SELECT customerid, channel, COUNT(*) AS n FROM kpi5_txn GROUP BY customerid, channel
),
shift AS (
    SELECT k.customerid,
           MAX(b.n) AS top_count,
           COALESCE(MAX(b.n) FILTER (WHERE b.channel = k.preferredchannel), 0) AS preferred_count,
           (ARRAY_AGG(b.channel ORDER BY b.n DESC, b.channel))[1] AS most_used_channel
    FROM (SELECT DISTINCT customerid, preferredchannel FROM kpi5_txn) k
    JOIN by_channel b USING (customerid)
    GROUP BY k.customerid, k.preferredchannel
),
per_customer AS (
    SELECT customerid, MIN(customername) AS customername, MIN(segment) AS segment, COUNT(*) AS total_txns,
           COUNT(*) FILTER (WHERE channelgroup = 'Digital')  AS digital_txns,
           COUNT(*) FILTER (WHERE channelgroup = 'Physical') AS physical_txns
    FROM kpi5_txn
    GROUP BY customerid
)
SELECT p.customerid, p.customername, p.segment, p.total_txns, p.digital_txns, p.physical_txns,
       round(p.digital_txns::numeric  / p.total_txns * 100, 2) AS digital_pct,
       round(p.physical_txns::numeric / p.total_txns * 100, 2) AS physical_pct,
       c.preferredchannel, s.most_used_channel,
       (s.preferred_count < s.top_count)::int AS channel_shift_flag
FROM per_customer p
JOIN shift s USING (customerid)
JOIN cleansed.customers c USING (customerid)
ORDER BY p.segment, p.customerid;
