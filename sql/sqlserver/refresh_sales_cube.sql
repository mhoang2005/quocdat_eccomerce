DECLARE @refreshed_at nvarchar(33) = ?;

WITH sales AS (
    SELECT f.sales_key, f.order_number, f.customer_key, f.quantity, f.gross_amount,
           f.discount_amount, f.net_amount, p.platform_name, pr.category_name,
           COALESCE(NULLIF(TRIM(c.city), N''), N'Unknown') AS customer_city,
           d.date_key, d.full_date, d.year_number, d.quarter_number, d.month_number,
           RIGHT('0000' + CONVERT(varchar(4), d.year_number), 4) AS year_text,
           RIGHT('00' + CONVERT(varchar(2), d.month_number), 2) AS month_text,
           CONVERT(varchar(1), d.quarter_number) AS quarter_text
    FROM dbo.fact_sales f
    JOIN dbo.dim_date d ON d.date_key = f.date_key
    JOIN dbo.dim_product pr ON pr.product_key = f.product_key
    JOIN dbo.dim_platform p ON p.platform_key = f.platform_key
    JOIN dbo.dim_customer c ON c.customer_key = f.customer_key
),
periods AS (
    SELECT s.*, t.time_level, t.time_key, t.time_label, t.period_date,
           t.period_year, t.period_quarter, t.period_month
    FROM sales s
    CROSS APPLY (VALUES
        ('DAY', CONVERT(varchar(8), s.date_key), s.full_date, s.date_key, s.year_number, s.quarter_number, s.month_number),
        ('MONTH', s.year_text + '-' + s.month_text, s.year_text + '-' + s.month_text, NULL, s.year_number, s.quarter_number, s.month_number),
        ('QUARTER', s.year_text + '-Q' + s.quarter_text, s.year_text + ' Q' + s.quarter_text, NULL, s.year_number, s.quarter_number, NULL),
        ('YEAR', s.year_text, s.year_text, NULL, s.year_number, NULL, NULL),
        ('ALL', 'ALL', 'All time', NULL, NULL, NULL, NULL)
    ) t(time_level, time_key, time_label, period_date, period_year, period_quarter, period_month)
)
INSERT INTO dbo.cube_sales (
    time_level, time_key, time_label, date_key, year_number, quarter_number, month_number,
    platform_name, category_name, customer_city, grouping_mask, order_count, customer_count,
    line_count, quantity_sold, gross_revenue, discount_amount, net_revenue,
    average_selling_price, refreshed_at
)
SELECT time_level, time_key, time_label, period_date, period_year, period_quarter, period_month,
       COALESCE(platform_name, N'ALL'), COALESCE(category_name, N'ALL'), COALESCE(customer_city, N'ALL'),
       GROUPING(platform_name) + 2 * GROUPING(category_name) + 4 * GROUPING(customer_city),
       COUNT_BIG(DISTINCT order_number), COUNT_BIG(DISTINCT customer_key), COUNT_BIG(*),
       SUM(quantity), SUM(gross_amount), SUM(discount_amount), SUM(net_amount),
       COALESCE(SUM(net_amount) / NULLIF(SUM(quantity), 0), 0), @refreshed_at
FROM periods
GROUP BY time_level, time_key, time_label, period_date, period_year, period_quarter, period_month,
         CUBE (platform_name, category_name, customer_city);

IF @@ROWCOUNT = 0
    INSERT INTO dbo.cube_sales (
        time_level, time_key, time_label, platform_name, category_name, customer_city,
        grouping_mask, order_count, customer_count, line_count, quantity_sold,
        gross_revenue, discount_amount, net_revenue, average_selling_price, refreshed_at
    )
    VALUES ('ALL', 'ALL', 'All time', 'ALL', 'ALL', 'ALL', 7, 0, 0, 0, 0, 0, 0, 0, 0, @refreshed_at);
