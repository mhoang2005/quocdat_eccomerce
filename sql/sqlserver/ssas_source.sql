CREATE OR ALTER VIEW dbo.ssas_fact_sales AS
SELECT sales_key, date_key, product_key, customer_key, platform_key,
       DENSE_RANK() OVER (ORDER BY order_number) AS order_key,
       quantity, gross_amount, discount_amount, net_amount
FROM dbo.fact_sales;
GO

CREATE OR ALTER VIEW dbo.ssas_dim_date AS
SELECT date_key, full_date, year_number, quarter_number, month_number,
       year_number * 10 + quarter_number AS quarter_key,
       year_number * 100 + month_number AS month_key,
       CAST(CONCAT('Q', quarter_number) AS nvarchar(8)) AS quarter_label,
       CAST(month_name AS nvarchar(20)) AS month_name
FROM dbo.dim_date;
GO

CREATE OR ALTER VIEW dbo.ssas_dim_product AS
SELECT product_key, category_name
FROM dbo.dim_product;
GO

CREATE OR ALTER VIEW dbo.ssas_dim_customer AS
SELECT customer_key, COALESCE(NULLIF(TRIM(city), N''), N'Unknown') AS customer_city
FROM dbo.dim_customer;
GO

CREATE OR ALTER VIEW dbo.ssas_dim_platform AS
SELECT platform_key, platform_name
FROM dbo.dim_platform;
GO
