-- Run in QuocDatDWH with Include Actual Execution Plan enabled.
-- Each query returns the same count and average. Compare logical reads and elapsed milliseconds.
SET NOCOUNT ON;
DROP TABLE IF EXISTS #unpartitioned_snapshot;
SELECT product_snapshot_key, date_key, product_key, platform_key, sale_price
INTO #unpartitioned_snapshot
FROM dbo.fact_product_snapshot;

CREATE INDEX ix_baseline ON #unpartitioned_snapshot(date_key, product_key);
CREATE INDEX ix_covering ON #unpartitioned_snapshot(platform_key, date_key) INCLUDE (sale_price);

DECLARE @platform bigint = 2, @first_day bigint = 20260101, @next_month bigint = 20260201;
SET STATISTICS IO, TIME ON;

SELECT 'Date/product index' AS scenario, COUNT_BIG(*) AS snapshots, ROUND(AVG(sale_price), 2) AS average_price
FROM #unpartitioned_snapshot WITH (INDEX(ix_baseline))
WHERE platform_key = @platform AND date_key >= @first_day AND date_key < @next_month
OPTION (RECOMPILE);

SELECT 'Covering index' AS scenario, COUNT_BIG(*) AS snapshots, ROUND(AVG(sale_price), 2) AS average_price
FROM #unpartitioned_snapshot WITH (INDEX(ix_covering))
WHERE platform_key = @platform AND date_key >= @first_day AND date_key < @next_month
OPTION (RECOMPILE);

SELECT 'Partition and covering index' AS scenario, COUNT_BIG(*) AS snapshots, ROUND(AVG(sale_price), 2) AS average_price
FROM dbo.fact_product_snapshot WITH (INDEX(idx_fact_snapshot_platform_date_price))
WHERE platform_key = @platform AND date_key >= @first_day AND date_key < @next_month
OPTION (RECOMPILE);

SET STATISTICS IO, TIME OFF;
