-- 1. Revenue by date and platform
SELECT d.full_date,
       p.platform_name,
       SUM(f.quantity) AS units_sold,
       SUM(f.net_amount) AS revenue
FROM fact_sales f
JOIN dim_date d ON d.date_key = f.date_key
JOIN dim_platform p ON p.platform_key = f.platform_key
GROUP BY d.full_date, p.platform_name
ORDER BY d.full_date DESC, revenue DESC;

-- 2. Procurement cost by supplier
SELECT s.supplier_name,
       SUM(f.quantity) AS units_received,
       SUM(f.total_cost) AS procurement_cost
FROM fact_procurement f
JOIN dim_supplier s ON s.supplier_key = f.supplier_key
GROUP BY s.supplier_name
ORDER BY procurement_cost DESC;

-- 3. Latest inventory snapshot value by warehouse
WITH latest_date AS (SELECT MAX(date_key) AS date_key FROM fact_inventory)
SELECT w.warehouse_name,
       SUM(f.quantity_on_hand) AS units_on_hand,
       SUM(f.inventory_value) AS inventory_value
FROM fact_inventory f
JOIN latest_date ld ON ld.date_key = f.date_key
JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
GROUP BY w.warehouse_name
ORDER BY inventory_value DESC;

-- 4. Inspect SCD Type 2 history for products with multiple versions
SELECT product_nk, product_key, product_name, category_name,
       valid_from, valid_to, is_current
FROM dim_product
WHERE product_nk IN (
    SELECT product_nk FROM dim_product
    GROUP BY product_nk HAVING COUNT(*) > 1
)
ORDER BY product_nk, valid_from;

-- 5. Query the Daily Sales Materialized View instead of rescanning Fact_Sales
SELECT full_date, platform_name, category_name, warehouse_name,
       order_count, quantity_sold, net_revenue
FROM mv_sales_daily
ORDER BY full_date DESC, net_revenue DESC;

-- 6. Roll up Sales Cube totals through the complete time hierarchy
SELECT time_level, time_label, order_count, quantity_sold, net_revenue
FROM cube_sales
WHERE platform_name = 'ALL'
  AND category_name = 'ALL'
  AND customer_name = 'ALL'
  AND customer_city = 'ALL'
ORDER BY CASE time_level
    WHEN 'DAY' THEN 1 WHEN 'MONTH' THEN 2 WHEN 'QUARTER' THEN 3
    WHEN 'YEAR' THEN 4 ELSE 5 END,
    time_key;

-- 7. Slice by platform and dice by category at the yearly level
SELECT time_label, platform_name, category_name,
       customer_name, customer_city, order_count, customer_count,
       quantity_sold, net_revenue
FROM cube_sales
WHERE time_level = 'YEAR'
  AND platform_name = 'Tiki'
  AND customer_name = 'ALL'
  AND customer_city = 'ALL'
ORDER BY net_revenue DESC;

-- 8. Reconcile Fact -> Materialized View -> Cube grand total
SELECT 'FACT' AS layer, COUNT(*) AS line_count,
       SUM(quantity) AS units, SUM(net_amount) AS revenue
FROM fact_sales
UNION ALL
SELECT 'MV', SUM(line_count), SUM(quantity_sold), SUM(net_revenue)
FROM mv_sales_daily
UNION ALL
SELECT 'CUBE', line_count, quantity_sold, net_revenue
FROM cube_sales
WHERE time_level = 'ALL' AND platform_name = 'ALL'
  AND category_name = 'ALL' AND customer_name = 'ALL'
  AND customer_city = 'ALL';
