-- One-time seed (runs on first database start).
-- Creates the three schemas and loads the CRM-style source tables from the given CSVs.
-- Source columns are all text on purpose: type checking and cleansing happen in clean.py.

CREATE SCHEMA IF NOT EXISTS source;
CREATE SCHEMA IF NOT EXISTS cleansed;
CREATE SCHEMA IF NOT EXISTS curated;

CREATE TABLE source.customers (
    customerid text, customername text, segment text, homelocationid text, preferredchannel text
);
CREATE TABLE source.merchants (
    merchantid text, merchantname text, merchantcategory text, risklevel text
);
CREATE TABLE source.locations (
    locationid text, city text, latitude text, longitude text
);

COPY source.customers FROM '/seed/Customers.csv' WITH (FORMAT csv, HEADER true);
COPY source.merchants FROM '/seed/Merchants.csv' WITH (FORMAT csv, HEADER true);

-- Synthetic Locations reference table: one row per LocationID in use, with a made-up city and coordinates.
CREATE TEMP TABLE seed_txn (
    transactionid text, customerid text, merchantid text, timeid text, locationid text,
    amount text, category text, channel text
);
COPY seed_txn FROM '/seed/Transactions.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO source.locations
WITH cities(idx, city, lat, lon) AS (
    VALUES (0, 'Mumbai', 19.0760, 72.8777), (1, 'Delhi', 28.7041, 77.1025),
           (2, 'Bengaluru', 12.9716, 77.5946), (3, 'Chennai', 13.0827, 80.2707),
           (4, 'Kolkata', 22.5726, 88.3639), (5, 'Hyderabad', 17.3850, 78.4867),
           (6, 'Ahmedabad', 23.0225, 72.5714), (7, 'Pune', 18.5204, 73.8567),
           (8, 'Jaipur', 26.9124, 75.7873), (9, 'Lucknow', 26.8467, 80.9462)
),
ids AS (
    SELECT DISTINCT locationid FROM (
        SELECT locationid FROM seed_txn
        UNION SELECT homelocationid FROM source.customers
    ) u WHERE locationid IS NOT NULL
),
numbered AS (
    SELECT locationid, regexp_replace(locationid, '[^0-9]', '', 'g')::int AS n FROM ids
)
SELECT n.locationid,
       c.city,
       round((c.lat + ((n.n / 10) % 5 - 2) * 0.02)::numeric, 4)::text,
       round((c.lon + ((n.n / 10) % 5 - 2) * 0.02)::numeric, 4)::text
FROM numbered n
JOIN cities c ON c.idx = n.n % 10
ORDER BY n.locationid;
