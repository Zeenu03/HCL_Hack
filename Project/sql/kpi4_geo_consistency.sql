-- KPI 4: Geo-Location Consistency Index.
-- Per customer: geo_consistency_index = transactions at the home location / total transactions,
-- the number of distinct locations, and the average distance (km, haversine) from home using the
-- synthetic Locations table. geo_anomaly_flag = 1 for a low index AND several distinct locations.

DROP TABLE IF EXISTS curated.kpi4_geo_consistency;
CREATE TABLE curated.kpi4_geo_consistency AS
WITH params AS (
    SELECT 0.5::numeric AS max_index,   -- "low" consistency: index below this
           2            AS min_locations -- "several" locations: at least this many distinct
),
txn AS (
    SELECT t.customerid, t.locationid, c.homelocationid,
           2 * 6371 * asin(sqrt(LEAST(1, power(sin(radians(tl.latitude::float8 - hl.latitude::float8) / 2), 2)
               + cos(radians(hl.latitude::float8)) * cos(radians(tl.latitude::float8))
               * power(sin(radians(tl.longitude::float8 - hl.longitude::float8) / 2), 2)))) AS distance_km
    FROM cleansed.transactions t
    JOIN cleansed.customers c USING (customerid)
    LEFT JOIN cleansed.locations tl ON tl.locationid = t.locationid
    LEFT JOIN cleansed.locations hl ON hl.locationid = c.homelocationid
),
per_customer AS (
    SELECT customerid,
           COUNT(*) AS total_txns,
           COUNT(*) FILTER (WHERE locationid = homelocationid) AS home_txns,
           COUNT(DISTINCT locationid) AS distinct_locations,
           AVG(distance_km) AS avg_distance_km
    FROM txn
    GROUP BY customerid
)
SELECT p.customerid, c.customername, c.segment, c.homelocationid, p.total_txns, p.home_txns,
       round(p.home_txns::numeric / p.total_txns, 4) AS geo_consistency_index,
       p.distinct_locations,
       round(p.avg_distance_km::numeric, 1) AS avg_distance_km,
       ((p.home_txns::numeric / p.total_txns) < params.max_index
        AND p.distinct_locations >= params.min_locations)::int AS geo_anomaly_flag
FROM per_customer p
CROSS JOIN params
JOIN cleansed.customers c USING (customerid)
ORDER BY geo_anomaly_flag DESC, geo_consistency_index, p.customerid;
