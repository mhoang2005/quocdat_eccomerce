-- SQL Server schema for the staging database.
IF OBJECT_ID(N'dbo.etl_batch', N'U') IS NULL
    CREATE TABLE dbo.etl_batch (
    [batch_id] NVARCHAR(100) PRIMARY KEY,
    [batch_type] NVARCHAR(MAX) NOT NULL,
    [status] NVARCHAR(25) NOT NULL,
    [source_started_at] NVARCHAR(33) NOT NULL,
    [completed_at] NVARCHAR(33),
    [source_row_count] BIGINT NOT NULL DEFAULT 0,
    [valid_row_count] BIGINT NOT NULL DEFAULT 0,
    [warning_row_count] BIGINT NOT NULL DEFAULT 0,
    [invalid_row_count] BIGINT NOT NULL DEFAULT 0,
    [message] NVARCHAR(MAX)
);
GO

IF OBJECT_ID(N'dbo.stg_product_snapshot', N'U') IS NULL
    CREATE TABLE dbo.stg_product_snapshot (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [batch_id] NVARCHAR(100) NOT NULL,
    [source_system] NVARCHAR(40) NOT NULL,
    [source_file] NVARCHAR(MAX) NOT NULL,
    [source_row_number] BIGINT NOT NULL,
    [natural_key] NVARCHAR(400) NOT NULL,
    [platform_product_id] NVARCHAR(MAX),
    [sku] NVARCHAR(MAX),
    [snapshot_at] NVARCHAR(33) NOT NULL,
    [product_name] NVARCHAR(MAX),
    [category_name] NVARCHAR(300),
    [category_l1] NVARCHAR(MAX),
    [category_l2] NVARCHAR(MAX),
    [category_l3] NVARCHAR(MAX),
    [brand_name] NVARCHAR(MAX),
    [seller_id] NVARCHAR(MAX),
    [seller_type] NVARCHAR(MAX),
    [origin] NVARCHAR(MAX),
    [list_price] FLOAT(53),
    [sale_price] FLOAT(53),
    [discount_amount] FLOAT(53),
    [discount_rate] FLOAT(53),
    [quantity_sold] BIGINT,
    [rating] FLOAT(53),
    [review_count] BIGINT,
    [image_url] NVARCHAR(MAX),
    [is_duplicate] BIGINT NOT NULL DEFAULT 0 CHECK (is_duplicate IN (0, 1)),
    [dq_status] NVARCHAR(20) NOT NULL CHECK (dq_status IN ('VALID', 'WARNING', 'INVALID')),
    [dq_message] NVARCHAR(MAX),
    [record_hash] NVARCHAR(64) NOT NULL,
    [raw_payload] NVARCHAR(MAX) NOT NULL,
    [staged_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.stg_product_snapshot') AND name = 'idx_stg_product_nk')
    CREATE INDEX idx_stg_product_nk ON dbo.stg_product_snapshot(natural_key);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.stg_product_snapshot') AND name = 'idx_stg_product_snapshot_at')
    CREATE INDEX idx_stg_product_snapshot_at ON dbo.stg_product_snapshot(snapshot_at);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.stg_product_snapshot') AND name = 'idx_stg_product_hash')
    CREATE INDEX idx_stg_product_hash ON dbo.stg_product_snapshot(record_hash);
GO

IF OBJECT_ID(N'dbo.stg_customer', N'U') IS NULL
    CREATE TABLE dbo.stg_customer (
    [customer_id] BIGINT PRIMARY KEY,
    [email] NVARCHAR(320) NOT NULL,
    [full_name] NVARCHAR(MAX) NOT NULL,
    [phone] NVARCHAR(100),
    [city] NVARCHAR(200),
    [address] NVARCHAR(MAX),
    [is_active] BIGINT NOT NULL,
    [source_updated_at] NVARCHAR(33) NOT NULL,
    [batch_id] NVARCHAR(100) NOT NULL
);
GO

IF OBJECT_ID(N'dbo.stg_sales_line', N'U') IS NULL
    CREATE TABLE dbo.stg_sales_line (
    [source_order_item_id] BIGINT PRIMARY KEY,
    [source_order_id] BIGINT NOT NULL,
    [order_number] NVARCHAR(100) NOT NULL,
    [invoice_number] NVARCHAR(100) NOT NULL,
    [order_at] NVARCHAR(33) NOT NULL,
    [customer_id] BIGINT NOT NULL,
    [product_id] BIGINT NOT NULL,
    [product_nk] NVARCHAR(400) NOT NULL,
    [platform_name] NVARCHAR(100) NOT NULL,
    [warehouse_id] BIGINT NOT NULL,
    [quantity] BIGINT NOT NULL,
    [unit_price] FLOAT(53) NOT NULL,
    [discount_amount] FLOAT(53) NOT NULL,
    [gross_amount] FLOAT(53) NOT NULL,
    [net_amount] FLOAT(53) NOT NULL,
    [batch_id] NVARCHAR(100) NOT NULL
);
GO

IF OBJECT_ID(N'dbo.stg_procurement_line', N'U') IS NULL
    CREATE TABLE dbo.stg_procurement_line (
    [source_procurement_item_id] BIGINT PRIMARY KEY,
    [source_receipt_id] BIGINT NOT NULL,
    [receipt_number] NVARCHAR(100) NOT NULL,
    [received_at] NVARCHAR(33) NOT NULL,
    [supplier_id] BIGINT NOT NULL,
    [warehouse_id] BIGINT NOT NULL,
    [product_id] BIGINT NOT NULL,
    [product_nk] NVARCHAR(400) NOT NULL,
    [quantity] BIGINT NOT NULL,
    [unit_cost] FLOAT(53) NOT NULL,
    [total_cost] FLOAT(53) NOT NULL,
    [batch_id] NVARCHAR(100) NOT NULL
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.stg_sales_line') AND name = 'idx_stg_sales_order')
    CREATE INDEX idx_stg_sales_order ON dbo.stg_sales_line(source_order_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.stg_sales_line') AND name = 'idx_stg_sales_batch')
    CREATE INDEX idx_stg_sales_batch ON dbo.stg_sales_line(batch_id);
GO

IF OBJECT_ID(N'dbo.cdc_checkpoint', N'U') IS NULL
    CREATE TABLE dbo.cdc_checkpoint (
    [stream] NVARCHAR(40) PRIMARY KEY,
    [event_id] BIGINT NOT NULL
);
GO

IF OBJECT_ID(N'dbo.stg_inventory_snapshot', N'U') IS NULL
    CREATE TABLE dbo.stg_inventory_snapshot (
    [product_id] BIGINT NOT NULL,
    [product_nk] NVARCHAR(400) NOT NULL,
    [warehouse_id] BIGINT NOT NULL,
    [snapshot_at] NVARCHAR(33) NOT NULL,
    [quantity_on_hand] BIGINT NOT NULL,
    [average_cost] FLOAT(53) NOT NULL,
    [inventory_value] FLOAT(53) NOT NULL,
    [batch_id] NVARCHAR(100) NOT NULL,
    PRIMARY KEY (product_id, warehouse_id)
);
GO
