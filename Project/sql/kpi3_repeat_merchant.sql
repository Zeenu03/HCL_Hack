-- KPI 3: Repeat Merchant Ratio.
-- Per customer: repeat_merchant_ratio = (total_txns - unique_merchants) / total_txns
-- (0 = every transaction at a new merchant, closer to 1 = very loyal), plus exposure to High-risk merchants.
-- high_risk_flag = 1 when the customer has any High-risk merchant transaction.

DROP TABLE IF EXISTS curated.kpi3_repeat_merchant;
CREATE TABLE curated.kpi3_repeat_merchant AS
WITH per_customer AS (
    SELECT t.customerid,
           COUNT(*)                                  AS total_txns,
           COUNT(DISTINCT t.merchantid)              AS unique_merchants,
           COUNT(*) FILTER (WHERE m.risklevel = 'High') AS high_risk_txns
    FROM cleansed.transactions t
    LEFT JOIN cleansed.merchants m USING (merchantid)
    GROUP BY t.customerid
)
SELECT p.customerid, c.customername, c.segment, p.total_txns, p.unique_merchants,
       p.total_txns - p.unique_merchants AS repeat_txns,
       round((p.total_txns - p.unique_merchants)::numeric / p.total_txns, 4) AS repeat_merchant_ratio,
       p.high_risk_txns,
       round(p.high_risk_txns::numeric / p.total_txns, 4) AS high_risk_share,
       (p.high_risk_txns > 0)::int AS high_risk_flag
FROM per_customer p
LEFT JOIN cleansed.customers c USING (customerid)
ORDER BY repeat_merchant_ratio DESC, p.total_txns DESC, p.customerid;
