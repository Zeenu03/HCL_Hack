-- KPI 1: Customer Segmentation by Transaction Category.
-- Share of each customer's spend per Category (Transactions.Category = what the customer actually spent on),
-- the dominant category (ties go to the first of Retail, Travel, Healthcare, Utilities), and the same share per Segment.

DROP TABLE IF EXISTS curated.kpi1_customer_category_share;
CREATE TABLE curated.kpi1_customer_category_share AS
WITH txn AS (
    SELECT c.customerid, c.customername, c.segment, t.transactionid, t.category, t.amount::numeric AS amount
    FROM cleansed.transactions t
    JOIN cleansed.customers c USING (customerid)
),
spend AS (
    SELECT customerid, MIN(customername) AS customername, MIN(segment) AS segment,
           COUNT(*) AS txn_count, SUM(amount) AS total_spend,
           COALESCE(SUM(amount) FILTER (WHERE category = 'Retail'), 0)     AS retail_spend,
           COALESCE(SUM(amount) FILTER (WHERE category = 'Travel'), 0)     AS travel_spend,
           COALESCE(SUM(amount) FILTER (WHERE category = 'Healthcare'), 0) AS healthcare_spend,
           COALESCE(SUM(amount) FILTER (WHERE category = 'Utilities'), 0)  AS utilities_spend
    FROM txn
    GROUP BY customerid
)
SELECT s.customerid, s.customername, s.segment, s.txn_count,
       round(s.total_spend, 2)       AS total_spend,
       round(s.retail_spend, 2)      AS retail_spend,
       round(s.travel_spend, 2)      AS travel_spend,
       round(s.healthcare_spend, 2)  AS healthcare_spend,
       round(s.utilities_spend, 2)   AS utilities_spend,
       round(s.retail_spend     / s.total_spend * 100, 2) AS retail_share_pct,
       round(s.travel_spend     / s.total_spend * 100, 2) AS travel_share_pct,
       round(s.healthcare_spend / s.total_spend * 100, 2) AS healthcare_share_pct,
       round(s.utilities_spend  / s.total_spend * 100, 2) AS utilities_share_pct,
       d.category AS dominant_category,
       round(d.spend / s.total_spend * 100, 2) AS dominant_share_pct
FROM spend s
CROSS JOIN LATERAL (
    SELECT v.category, v.spend
    FROM (VALUES (1, 'Retail', s.retail_spend), (2, 'Travel', s.travel_spend),
                 (3, 'Healthcare', s.healthcare_spend), (4, 'Utilities', s.utilities_spend)) AS v(ord, category, spend)
    ORDER BY v.spend DESC, v.ord
    LIMIT 1
) d
ORDER BY s.segment, s.customerid;

DROP TABLE IF EXISTS curated.kpi1_segment_category_share;
CREATE TABLE curated.kpi1_segment_category_share AS
WITH txn AS (
    SELECT c.segment, t.category, t.amount::numeric AS amount
    FROM cleansed.transactions t
    JOIN cleansed.customers c USING (customerid)
),
grid AS (
    SELECT s.segment, k.category
    FROM (SELECT DISTINCT segment FROM txn) s
    CROSS JOIN (VALUES ('Retail'), ('Travel'), ('Healthcare'), ('Utilities')) AS k(category)
),
seg AS (
    SELECT g.segment, g.category, COUNT(t.amount) AS txn_count, COALESCE(SUM(t.amount), 0) AS total_amount
    FROM grid g
    LEFT JOIN txn t ON t.segment = g.segment AND t.category = g.category
    GROUP BY g.segment, g.category
)
SELECT segment, category, txn_count,
       round(total_amount, 2) AS total_amount,
       round(total_amount / SUM(total_amount) OVER (PARTITION BY segment) * 100, 2) AS spend_share_pct
FROM seg
ORDER BY segment, category;
