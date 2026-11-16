-- SQL Server schema for the dwh database.
IF NOT EXISTS (SELECT 1 FROM sys.partition_functions WHERE name = 'pf_snapshot_month')
    CREATE PARTITION FUNCTION pf_snapshot_month (BIGINT) AS RANGE RIGHT FOR VALUES (20200101, 20200201, 20200301, 20200401, 20200501, 20200601, 20200701, 20200801, 20200901, 20201001, 20201101, 20201201, 20210101, 20210201, 20210301, 20210401, 20210501, 20210601, 20210701, 20210801, 20210901, 20211001, 20211101, 20211201, 20220101, 20220201, 20220301, 20220401, 20220501, 20220601, 20220701, 20220801, 20220901, 20221001, 20221101, 20221201, 20230101, 20230201, 20230301, 20230401, 20230501, 20230601, 20230701, 20230801, 20230901, 20231001, 20231101, 20231201, 20240101, 20240201, 20240301, 20240401, 20240501, 20240601, 20240701, 20240801, 20240901, 20241001, 20241101, 20241201, 20250101, 20250201, 20250301, 20250401, 20250501, 20250601, 20250701, 20250801, 20250901, 20251001, 20251101, 20251201, 20260101, 20260201, 20260301, 20260401, 20260501, 20260601, 20260701, 20260801, 20260901, 20261001, 20261101, 20261201, 20270101, 20270201, 20270301, 20270401, 20270501, 20270601, 20270701, 20270801, 20270901, 20271001, 20271101, 20271201, 20280101, 20280201, 20280301, 20280401, 20280501, 20280601, 20280701, 20280801, 20280901, 20281001, 20281101, 20281201, 20290101, 20290201, 20290301, 20290401, 20290501, 20290601, 20290701, 20290801, 20290901, 20291001, 20291101, 20291201, 20300101, 20300201, 20300301, 20300401, 20300501, 20300601, 20300701, 20300801, 20300901, 20301001, 20301101, 20301201, 20310101, 20310201, 20310301, 20310401, 20310501, 20310601, 20310701, 20310801, 20310901, 20311001, 20311101, 20311201, 20320101, 20320201, 20320301, 20320401, 20320501, 20320601, 20320701, 20320801, 20320901, 20321001, 20321101, 20321201, 20330101, 20330201, 20330301, 20330401, 20330501, 20330601, 20330701, 20330801, 20330901, 20331001, 20331101, 20331201, 20340101, 20340201, 20340301, 20340401, 20340501, 20340601, 20340701, 20340801, 20340901, 20341001, 20341101, 20341201, 20350101, 20350201, 20350301, 20350401, 20350501, 20350601, 20350701, 20350801, 20350901, 20351001, 20351101, 20351201, 20360101, 20360201, 20360301, 20360401, 20360501, 20360601, 20360701, 20360801, 20360901, 20361001, 20361101, 20361201, 20370101, 20370201, 20370301, 20370401, 20370501, 20370601, 20370701, 20370801, 20370901, 20371001, 20371101, 20371201, 20380101, 20380201, 20380301, 20380401, 20380501, 20380601, 20380701, 20380801, 20380901, 20381001, 20381101, 20381201, 20390101, 20390201, 20390301, 20390401, 20390501, 20390601, 20390701, 20390801, 20390901, 20391001, 20391101, 20391201);
IF NOT EXISTS (SELECT 1 FROM sys.partition_schemes WHERE name = 'ps_snapshot_month')
    CREATE PARTITION SCHEME ps_snapshot_month AS PARTITION pf_snapshot_month ALL TO ([PRIMARY]);
GO

IF OBJECT_ID(N'dbo.dim_date', N'U') IS NULL
    CREATE TABLE dbo.dim_date (
    [date_key] BIGINT PRIMARY KEY,
    [full_date] NVARCHAR(12) NOT NULL UNIQUE,
    [day_of_month] BIGINT NOT NULL,
    [day_name] NVARCHAR(MAX) NOT NULL,
    [week_of_year] BIGINT NOT NULL,
    [month_number] BIGINT NOT NULL,
    [month_name] NVARCHAR(MAX) NOT NULL,
    [quarter_number] BIGINT NOT NULL,
    [year_number] BIGINT NOT NULL,
    [is_weekend] BIGINT NOT NULL CHECK (is_weekend IN (0, 1))
);
GO

IF OBJECT_ID(N'dbo.dim_platform', N'U') IS NULL
    CREATE TABLE dbo.dim_platform (
    [platform_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [platform_nk] BIGINT NOT NULL UNIQUE,
    [platform_code] NVARCHAR(MAX) NOT NULL,
    [platform_name] NVARCHAR(100) NOT NULL,
    [is_active] BIGINT NOT NULL
);
GO

IF OBJECT_ID(N'dbo.dim_product', N'U') IS NULL
    CREATE TABLE dbo.dim_product (
    [product_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [product_nk] NVARCHAR(400) NOT NULL,
    [source_product_id] BIGINT,
    [product_code] NVARCHAR(100),
    [product_name] NVARCHAR(MAX) NOT NULL,
    [category_name] NVARCHAR(300) NOT NULL,
    [platform_name] NVARCHAR(100) NOT NULL,
    [brand_name] NVARCHAR(MAX),
    [origin] NVARCHAR(MAX),
    [is_active] BIGINT NOT NULL,
    [valid_from] NVARCHAR(33) NOT NULL,
    [valid_to] NVARCHAR(33) NOT NULL,
    [is_current] BIGINT NOT NULL CHECK (is_current IN (0, 1)),
    [attribute_hash] NVARCHAR(64) NOT NULL,
    UNIQUE (product_nk, valid_from)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.dim_product') AND name = 'idx_dim_product_current')
    CREATE UNIQUE INDEX idx_dim_product_current ON dbo.dim_product(product_nk) WHERE is_current = 1;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.dim_product') AND name = 'idx_dim_product_effective')
    CREATE INDEX idx_dim_product_effective ON dbo.dim_product(product_nk, valid_from, valid_to);
GO

IF OBJECT_ID(N'dbo.dim_customer', N'U') IS NULL
    CREATE TABLE dbo.dim_customer (
    [customer_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [customer_nk] BIGINT NOT NULL UNIQUE,
    [email] NVARCHAR(320) NOT NULL,
    [full_name] NVARCHAR(MAX) NOT NULL,
    [phone] NVARCHAR(100),
    [city] NVARCHAR(200),
    [address] NVARCHAR(MAX),
    [is_active] BIGINT NOT NULL,
    [updated_at] NVARCHAR(33) NOT NULL
);
GO

IF OBJECT_ID(N'dbo.dim_supplier', N'U') IS NULL
    CREATE TABLE dbo.dim_supplier (
    [supplier_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [supplier_nk] BIGINT NOT NULL UNIQUE,
    [supplier_code] NVARCHAR(100) NOT NULL,
    [supplier_name] NVARCHAR(300) NOT NULL,
    [contact_name] NVARCHAR(MAX),
    [phone] NVARCHAR(100),
    [email] NVARCHAR(320),
    [address] NVARCHAR(MAX),
    [is_active] BIGINT NOT NULL
);
GO

IF OBJECT_ID(N'dbo.dim_warehouse', N'U') IS NULL
    CREATE TABLE dbo.dim_warehouse (
    [warehouse_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [warehouse_nk] BIGINT NOT NULL UNIQUE,
    [warehouse_code] NVARCHAR(100) NOT NULL,
    [warehouse_name] NVARCHAR(300) NOT NULL,
    [address] NVARCHAR(MAX) NOT NULL,
    [is_active] BIGINT NOT NULL
);
GO

IF OBJECT_ID(N'dbo.fact_sales', N'U') IS NULL
    CREATE TABLE dbo.fact_sales (
    [sales_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [date_key] BIGINT NOT NULL REFERENCES dbo.dim_date(date_key),
    [product_key] BIGINT NOT NULL REFERENCES dbo.dim_product(product_key),
    [customer_key] BIGINT NOT NULL REFERENCES dbo.dim_customer(customer_key),
    [platform_key] BIGINT NOT NULL REFERENCES dbo.dim_platform(platform_key),
    [warehouse_key] BIGINT NOT NULL REFERENCES dbo.dim_warehouse(warehouse_key),
    [source_order_item_id] BIGINT NOT NULL UNIQUE,
    [order_number] NVARCHAR(100) NOT NULL,
    [invoice_number] NVARCHAR(100) NOT NULL,
    [quantity] BIGINT NOT NULL,
    [unit_price] FLOAT(53) NOT NULL,
    [discount_amount] FLOAT(53) NOT NULL,
    [gross_amount] FLOAT(53) NOT NULL,
    [net_amount] FLOAT(53) NOT NULL,
    [loaded_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [source_order_id] BIGINT
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.fact_sales') AND name = 'idx_fact_sales_date_product')
    CREATE INDEX idx_fact_sales_date_product ON dbo.fact_sales(date_key, product_key);
GO

IF OBJECT_ID(N'dbo.fact_procurement', N'U') IS NULL
    CREATE TABLE dbo.fact_procurement (
    [procurement_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [date_key] BIGINT NOT NULL REFERENCES dbo.dim_date(date_key),
    [product_key] BIGINT NOT NULL REFERENCES dbo.dim_product(product_key),
    [supplier_key] BIGINT NOT NULL REFERENCES dbo.dim_supplier(supplier_key),
    [warehouse_key] BIGINT NOT NULL REFERENCES dbo.dim_warehouse(warehouse_key),
    [source_procurement_item_id] BIGINT NOT NULL UNIQUE,
    [receipt_number] NVARCHAR(100) NOT NULL,
    [quantity] BIGINT NOT NULL,
    [unit_cost] FLOAT(53) NOT NULL,
    [total_cost] FLOAT(53) NOT NULL,
    [loaded_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.fact_procurement') AND name = 'idx_fact_procurement_date_product')
    CREATE INDEX idx_fact_procurement_date_product ON dbo.fact_procurement(date_key, product_key);
GO

IF OBJECT_ID(N'dbo.fact_inventory', N'U') IS NULL
    CREATE TABLE dbo.fact_inventory (
    [inventory_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [date_key] BIGINT NOT NULL REFERENCES dbo.dim_date(date_key),
    [product_key] BIGINT NOT NULL REFERENCES dbo.dim_product(product_key),
    [warehouse_key] BIGINT NOT NULL REFERENCES dbo.dim_warehouse(warehouse_key),
    [quantity_on_hand] BIGINT NOT NULL,
    [average_cost] FLOAT(53) NOT NULL,
    [inventory_value] FLOAT(53) NOT NULL,
    [snapshot_at] NVARCHAR(33) NOT NULL,
    [loaded_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    UNIQUE (date_key, product_key, warehouse_key)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.fact_inventory') AND name = 'idx_fact_inventory_date_product')
    CREATE INDEX idx_fact_inventory_date_product ON dbo.fact_inventory(date_key, product_key);
GO

IF OBJECT_ID(N'dbo.fact_product_snapshot', N'U') IS NULL
    CREATE TABLE dbo.fact_product_snapshot (
    [product_snapshot_key] BIGINT IDENTITY(1,1) NOT NULL,
    [date_key] BIGINT NOT NULL REFERENCES dbo.dim_date(date_key),
    [product_key] BIGINT NOT NULL REFERENCES dbo.dim_product(product_key),
    [platform_key] BIGINT NOT NULL REFERENCES dbo.dim_platform(platform_key),
    [source_record_hash] NVARCHAR(64) NOT NULL,
    [snapshot_at] NVARCHAR(33) NOT NULL,
    [list_price] FLOAT(53),
    [sale_price] FLOAT(53),
    [discount_amount] FLOAT(53),
    [discount_rate] FLOAT(53),
    [quantity_sold_snapshot] BIGINT,
    [rating] FLOAT(53),
    [review_count] BIGINT,
    [loaded_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    PRIMARY KEY NONCLUSTERED (product_snapshot_key) ON [PRIMARY],
    UNIQUE NONCLUSTERED (source_record_hash, snapshot_at) ON [PRIMARY]
) ON ps_snapshot_month(date_key);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.fact_product_snapshot') AND name = 'cx_snapshot_month')
    CREATE CLUSTERED INDEX cx_snapshot_month ON dbo.fact_product_snapshot(date_key, product_snapshot_key) ON ps_snapshot_month(date_key);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.fact_product_snapshot') AND name = 'idx_fact_product_snapshot_date_product')
    CREATE INDEX idx_fact_product_snapshot_date_product ON dbo.fact_product_snapshot(date_key, product_key);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.fact_product_snapshot') AND name = 'idx_fact_snapshot_platform_date_price')
    CREATE INDEX idx_fact_snapshot_platform_date_price ON dbo.fact_product_snapshot(platform_key, date_key) INCLUDE (sale_price);
GO

IF OBJECT_ID(N'dbo.etl_run', N'U') IS NULL
    CREATE TABLE dbo.etl_run (
    [run_id] NVARCHAR(100) PRIMARY KEY,
    [mode] NVARCHAR(20) NOT NULL,
    [status] NVARCHAR(25) NOT NULL,
    [started_at] NVARCHAR(33) NOT NULL,
    [completed_at] NVARCHAR(33),
    [staged_rows] BIGINT NOT NULL DEFAULT 0,
    [dimension_rows] BIGINT NOT NULL DEFAULT 0,
    [fact_rows] BIGINT NOT NULL DEFAULT 0,
    [warning_rows] BIGINT NOT NULL DEFAULT 0,
    [message] NVARCHAR(MAX)
);
GO

IF OBJECT_ID(N'dbo.mv_sales_daily', N'U') IS NULL
    CREATE TABLE dbo.mv_sales_daily (
    [date_key] BIGINT NOT NULL,
    [full_date] NVARCHAR(12) NOT NULL,
    [year_number] BIGINT NOT NULL,
    [quarter_number] BIGINT NOT NULL,
    [month_number] BIGINT NOT NULL,
    [platform_key] BIGINT NOT NULL,
    [platform_name] NVARCHAR(100) NOT NULL,
    [warehouse_key] BIGINT NOT NULL,
    [warehouse_name] NVARCHAR(300) NOT NULL,
    [category_name] NVARCHAR(300) NOT NULL,
    [order_count] BIGINT NOT NULL,
    [customer_count] BIGINT NOT NULL,
    [line_count] BIGINT NOT NULL,
    [quantity_sold] BIGINT NOT NULL,
    [gross_revenue] FLOAT(53) NOT NULL,
    [discount_amount] FLOAT(53) NOT NULL,
    [net_revenue] FLOAT(53) NOT NULL,
    [average_selling_price] FLOAT(53) NOT NULL,
    [refreshed_at] NVARCHAR(33) NOT NULL,
    PRIMARY KEY (date_key, platform_key, warehouse_key, category_name)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.mv_sales_daily') AND name = 'idx_mv_sales_daily_slice')
    CREATE INDEX idx_mv_sales_daily_slice ON dbo.mv_sales_daily(year_number, month_number, platform_name, category_name);
GO

IF OBJECT_ID(N'dbo.mv_procurement_daily', N'U') IS NULL
    CREATE TABLE dbo.mv_procurement_daily (
    [date_key] BIGINT NOT NULL,
    [full_date] NVARCHAR(12) NOT NULL,
    [year_number] BIGINT NOT NULL,
    [quarter_number] BIGINT NOT NULL,
    [month_number] BIGINT NOT NULL,
    [supplier_key] BIGINT NOT NULL,
    [supplier_name] NVARCHAR(300) NOT NULL,
    [warehouse_key] BIGINT NOT NULL,
    [warehouse_name] NVARCHAR(300) NOT NULL,
    [category_name] NVARCHAR(300) NOT NULL,
    [receipt_count] BIGINT NOT NULL,
    [line_count] BIGINT NOT NULL,
    [quantity_received] BIGINT NOT NULL,
    [procurement_cost] FLOAT(53) NOT NULL,
    [average_unit_cost] FLOAT(53) NOT NULL,
    [refreshed_at] NVARCHAR(33) NOT NULL,
    PRIMARY KEY (date_key, supplier_key, warehouse_key, category_name)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.mv_procurement_daily') AND name = 'idx_mv_procurement_daily_slice')
    CREATE INDEX idx_mv_procurement_daily_slice ON dbo.mv_procurement_daily(year_number, month_number, supplier_name, warehouse_name);
GO

IF OBJECT_ID(N'dbo.mv_inventory_daily', N'U') IS NULL
    CREATE TABLE dbo.mv_inventory_daily (
    [date_key] BIGINT NOT NULL,
    [full_date] NVARCHAR(12) NOT NULL,
    [year_number] BIGINT NOT NULL,
    [quarter_number] BIGINT NOT NULL,
    [month_number] BIGINT NOT NULL,
    [platform_name] NVARCHAR(100) NOT NULL,
    [warehouse_key] BIGINT NOT NULL,
    [warehouse_name] NVARCHAR(300) NOT NULL,
    [category_name] NVARCHAR(300) NOT NULL,
    [product_count] BIGINT NOT NULL,
    [quantity_on_hand] BIGINT NOT NULL,
    [inventory_value] FLOAT(53) NOT NULL,
    [average_unit_cost] FLOAT(53) NOT NULL,
    [refreshed_at] NVARCHAR(33) NOT NULL,
    PRIMARY KEY (date_key, platform_name, warehouse_key, category_name)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.mv_inventory_daily') AND name = 'idx_mv_inventory_daily_slice')
    CREATE INDEX idx_mv_inventory_daily_slice ON dbo.mv_inventory_daily(year_number, month_number, platform_name, warehouse_name);
GO

IF OBJECT_ID(N'dbo.mv_marketplace_daily', N'U') IS NULL
    CREATE TABLE dbo.mv_marketplace_daily (
    [date_key] BIGINT NOT NULL,
    [full_date] NVARCHAR(12) NOT NULL,
    [year_number] BIGINT NOT NULL,
    [quarter_number] BIGINT NOT NULL,
    [month_number] BIGINT NOT NULL,
    [platform_key] BIGINT NOT NULL,
    [platform_name] NVARCHAR(100) NOT NULL,
    [category_name] NVARCHAR(300) NOT NULL,
    [product_count] BIGINT NOT NULL,
    [snapshot_count] BIGINT NOT NULL,
    [average_list_price] FLOAT(53) NOT NULL,
    [average_sale_price] FLOAT(53) NOT NULL,
    [average_discount_rate] FLOAT(53) NOT NULL,
    [average_rating] FLOAT(53) NOT NULL,
    [review_count_snapshot] BIGINT NOT NULL,
    [sold_quantity_snapshot] BIGINT NOT NULL,
    [refreshed_at] NVARCHAR(33) NOT NULL,
    PRIMARY KEY (date_key, platform_key, category_name)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.mv_marketplace_daily') AND name = 'idx_mv_marketplace_daily_slice')
    CREATE INDEX idx_mv_marketplace_daily_slice ON dbo.mv_marketplace_daily(year_number, month_number, platform_name, category_name);
GO

IF OBJECT_ID(N'dbo.cube_sales', N'U') IS NULL
    CREATE TABLE dbo.cube_sales (
    [cube_key] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [time_level] NVARCHAR(16) NOT NULL CHECK (time_level IN ('DAY', 'MONTH', 'QUARTER', 'YEAR', 'ALL')),
    [time_key] NVARCHAR(40) NOT NULL,
    [time_label] NVARCHAR(60) NOT NULL,
    [date_key] BIGINT,
    [year_number] BIGINT,
    [quarter_number] BIGINT,
    [month_number] BIGINT,
    [platform_name] NVARCHAR(100) NOT NULL,
    [category_name] NVARCHAR(300) NOT NULL,
    [customer_city] NVARCHAR(200) NOT NULL,
    [grouping_mask] BIGINT NOT NULL CHECK (grouping_mask BETWEEN 0 AND 7),
    [order_count] BIGINT NOT NULL,
    [customer_count] BIGINT NOT NULL,
    [line_count] BIGINT NOT NULL,
    [quantity_sold] BIGINT NOT NULL,
    [gross_revenue] FLOAT(53) NOT NULL,
    [discount_amount] FLOAT(53) NOT NULL,
    [net_revenue] FLOAT(53) NOT NULL,
    [average_selling_price] FLOAT(53) NOT NULL,
    [refreshed_at] NVARCHAR(33) NOT NULL,
    UNIQUE (
        time_level, time_key, platform_name, category_name, customer_city
    )
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.cube_sales') AND name = 'idx_cube_sales_slice')
    CREATE INDEX idx_cube_sales_slice ON dbo.cube_sales(
    time_level, platform_name, category_name, customer_city
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.cube_sales') AND name = 'idx_cube_sales_rollup')
    CREATE INDEX idx_cube_sales_rollup ON dbo.cube_sales(time_level, time_key, grouping_mask);
GO

IF OBJECT_ID(N'dbo.olap_refresh_run', N'U') IS NULL
    CREATE TABLE dbo.olap_refresh_run (
    [refresh_id] NVARCHAR(100) PRIMARY KEY,
    [source_etl_run_id] NVARCHAR(100),
    [refresh_type] NVARCHAR(MAX) NOT NULL DEFAULT 'COMPLETE',
    [status] NVARCHAR(25) NOT NULL,
    [started_at] NVARCHAR(33) NOT NULL,
    [completed_at] NVARCHAR(33),
    [materialized_rows] BIGINT NOT NULL DEFAULT 0,
    [cube_rows] BIGINT NOT NULL DEFAULT 0,
    [message] NVARCHAR(MAX)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.fact_sales') AND name = 'idx_fact_sales_source_order')
    CREATE INDEX idx_fact_sales_source_order ON dbo.fact_sales(source_order_id);
GO
