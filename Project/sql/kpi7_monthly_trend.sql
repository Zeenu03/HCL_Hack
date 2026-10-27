-- KPI 7: Monthly Spend Trend (extension).
-- Spend and transaction count per month and category (months with no spend show as 0), month-over-month % change
-- (blank when the previous month is 0), category share of the month, share change in percentage points, and
-- category_shift = 1 on the single latest-month row whose share moved the most.

DROP TABLE IF EXISTS curated.kpi7_monthly_spend;
CREATE TABLE curated.kpi7_monthly_spend AS
WITH txn AS (
    SELECT date_trunc('month', tm.date)::date AS month_start, t.category, t.amount::numeric AS amount
    FROM cleansed.transactions t
    JOIN cleansed.time tm USING (timeid)
),
months AS (
    SELECT generate_series(MIN(month_start), MAX(month_start), interval '1 month')::date AS month_start FROM txn
),
cats AS (
    SELECT DISTINCT category FROM txn
),
monthly AS (
    SELECT m.month_start, c.category, COALESCE(SUM(t.amount), 0) AS total_spend, COUNT(t.amount) AS txn_count
    FROM months m
    CROSS JOIN cats c
    LEFT JOIN txn t ON t.month_start = m.month_start AND t.category = c.category
    GROUP BY m.month_start, c.category
),
shares AS (
    SELECT month_start, category, total_spend, txn_count,
           LAG(total_spend) OVER (PARTITION BY category ORDER BY month_start) AS prev_spend,
           round(total_spend / NULLIF(SUM(total_spend) OVER (PARTITION BY month_start), 0), 4) AS category_share
    FROM monthly
),
changes AS (
    SELECT *, round((category_share - LAG(category_share) OVER (PARTITION BY category ORDER BY month_start)) * 100, 2)
              AS share_change_pp
    FROM shares
),
shift AS (
    SELECT month_start, category
    FROM changes
    WHERE month_start = (SELECT MAX(month_start) FROM changes) AND share_change_pp IS NOT NULL
    ORDER BY abs(share_change_pp) DESC, category
    LIMIT 1
)
SELECT EXTRACT(year FROM c.month_start)::int  AS year,
       EXTRACT(month FROM c.month_start)::int AS monthnum,
       to_char(c.month_start, 'Mon')          AS month,
       c.category,
       round(c.total_spend, 2)                AS total_spend,
       c.txn_count,
       round((c.total_spend - c.prev_spend) / NULLIF(c.prev_spend, 0) * 100, 2) AS mom_change_pct,
       c.category_share,
       c.share_change_pp,
       (s.category IS NOT NULL)::int          AS category_shift
FROM changes c
LEFT JOIN shift s ON s.month_start = c.month_start AND s.category = c.category
ORDER BY c.month_start, c.category;
