-- SQL Server schema for the oltp database.
IF OBJECT_ID(N'dbo.users', N'U') IS NULL
    CREATE TABLE dbo.users (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [email] NVARCHAR(320) COLLATE Latin1_General_100_CI_AS MASKED WITH (FUNCTION = 'email()') NOT NULL UNIQUE,
    [password_hash] NVARCHAR(MAX) NOT NULL,
    [role] NVARCHAR(20) NOT NULL CHECK (role IN ('customer', 'employee', 'admin')),
    [full_name] NVARCHAR(MAX) NOT NULL,
    [phone] NVARCHAR(100) MASKED WITH (FUNCTION = 'partial(0,"******",4)') NULL,
    [address] NVARCHAR(MAX),
    [city] NVARCHAR(200),
    [is_active] BIGINT NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [updated_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF OBJECT_ID(N'dbo.platforms', N'U') IS NULL
    CREATE TABLE dbo.platforms (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [code] NVARCHAR(80) NOT NULL UNIQUE,
    [name] NVARCHAR(400) NOT NULL UNIQUE,
    [is_active] BIGINT NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
GO

IF OBJECT_ID(N'dbo.categories', N'U') IS NULL
    CREATE TABLE dbo.categories (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [name] NVARCHAR(400) COLLATE Latin1_General_100_CI_AS NOT NULL UNIQUE,
    [parent_id] BIGINT REFERENCES dbo.categories(id),
    [is_active] BIGINT NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
GO

IF OBJECT_ID(N'dbo.products', N'U') IS NULL
    CREATE TABLE dbo.products (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [product_code] NVARCHAR(100) NOT NULL UNIQUE,
    [natural_key] NVARCHAR(400) NOT NULL UNIQUE,
    [platform_product_id] NVARCHAR(MAX),
    [sku] NVARCHAR(MAX),
    [platform_id] BIGINT NOT NULL REFERENCES dbo.platforms(id),
    [category_id] BIGINT NOT NULL REFERENCES dbo.categories(id),
    [name] NVARCHAR(800) NOT NULL,
    [brand_name] NVARCHAR(MAX),
    [origin] NVARCHAR(MAX),
    [current_price] FLOAT(53) NOT NULL DEFAULT 0 CHECK (current_price >= 0),
    [list_price] FLOAT(53) CHECK (list_price IS NULL OR list_price >= 0),
    [discount_rate] FLOAT(53) NOT NULL DEFAULT 0 CHECK (discount_rate BETWEEN 0 AND 100),
    [rating] FLOAT(53) CHECK (rating IS NULL OR rating BETWEEN 0 AND 5),
    [review_count] BIGINT NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    [sold_snapshot] BIGINT NOT NULL DEFAULT 0 CHECK (sold_snapshot >= 0),
    [image_url] NVARCHAR(MAX),
    [source_snapshot_at] NVARCHAR(33),
    [is_active] BIGINT NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [updated_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.products') AND name = 'idx_products_name')
    CREATE INDEX idx_products_name ON dbo.products(name);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.products') AND name = 'idx_products_category')
    CREATE INDEX idx_products_category ON dbo.products(category_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.products') AND name = 'idx_products_platform')
    CREATE INDEX idx_products_platform ON dbo.products(platform_id);
GO

IF OBJECT_ID(N'dbo.suppliers', N'U') IS NULL
    CREATE TABLE dbo.suppliers (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [supplier_code] NVARCHAR(100) NOT NULL UNIQUE,
    [name] NVARCHAR(400) NOT NULL,
    [contact_name] NVARCHAR(MAX),
    [phone] NVARCHAR(100),
    [email] NVARCHAR(320),
    [address] NVARCHAR(MAX),
    [is_active] BIGINT NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [updated_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF OBJECT_ID(N'dbo.warehouses', N'U') IS NULL
    CREATE TABLE dbo.warehouses (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [warehouse_code] NVARCHAR(100) NOT NULL UNIQUE,
    [name] NVARCHAR(400) NOT NULL,
    [address] NVARCHAR(MAX) NOT NULL,
    [is_active] BIGINT NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [updated_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF OBJECT_ID(N'dbo.inventory', N'U') IS NULL
    CREATE TABLE dbo.inventory (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [product_id] BIGINT NOT NULL REFERENCES dbo.products(id),
    [warehouse_id] BIGINT NOT NULL REFERENCES dbo.warehouses(id),
    [quantity_on_hand] BIGINT NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
    [reorder_level] BIGINT NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    [average_cost] FLOAT(53) NOT NULL DEFAULT 0 CHECK (average_cost >= 0),
    [updated_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    UNIQUE (product_id, warehouse_id)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.inventory') AND name = 'idx_inventory_product')
    CREATE INDEX idx_inventory_product ON dbo.inventory(product_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.inventory') AND name = 'idx_inventory_warehouse')
    CREATE INDEX idx_inventory_warehouse ON dbo.inventory(warehouse_id);
GO

IF OBJECT_ID(N'dbo.carts', N'U') IS NULL
    CREATE TABLE dbo.carts (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [customer_id] BIGINT NOT NULL UNIQUE REFERENCES dbo.users(id) ON DELETE CASCADE,
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [updated_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF OBJECT_ID(N'dbo.cart_items', N'U') IS NULL
    CREATE TABLE dbo.cart_items (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [cart_id] BIGINT NOT NULL REFERENCES dbo.carts(id) ON DELETE CASCADE,
    [product_id] BIGINT NOT NULL REFERENCES dbo.products(id),
    [quantity] BIGINT NOT NULL CHECK (quantity > 0),
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [updated_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    UNIQUE (cart_id, product_id)
);
GO

IF OBJECT_ID(N'dbo.orders', N'U') IS NULL
    CREATE TABLE dbo.orders (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [order_number] NVARCHAR(100) NOT NULL UNIQUE,
    [customer_id] BIGINT NOT NULL REFERENCES dbo.users(id),
    [status] NVARCHAR(25) NOT NULL CHECK (status IN ('confirmed', 'packing', 'shipping', 'completed', 'cancelled')),
    [payment_status] NVARCHAR(MAX) NOT NULL CHECK (payment_status IN ('paid', 'refunded')),
    [shipping_address] NVARCHAR(MAX) NOT NULL,
    [shipping_city] NVARCHAR(MAX) NOT NULL,
    [subtotal] FLOAT(53) NOT NULL CHECK (subtotal >= 0),
    [discount_total] FLOAT(53) NOT NULL DEFAULT 0 CHECK (discount_total >= 0),
    [shipping_fee] FLOAT(53) NOT NULL DEFAULT 0 CHECK (shipping_fee >= 0),
    [total_amount] FLOAT(53) NOT NULL CHECK (total_amount >= 0),
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [paid_at] NVARCHAR(33),
    [completed_at] NVARCHAR(33)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.orders') AND name = 'idx_orders_customer')
    CREATE INDEX idx_orders_customer ON dbo.orders(customer_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.orders') AND name = 'idx_orders_created')
    CREATE INDEX idx_orders_created ON dbo.orders(created_at);
GO

IF OBJECT_ID(N'dbo.order_items', N'U') IS NULL
    CREATE TABLE dbo.order_items (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [order_id] BIGINT NOT NULL REFERENCES dbo.orders(id) ON DELETE CASCADE,
    [product_id] BIGINT NOT NULL REFERENCES dbo.products(id),
    [warehouse_id] BIGINT NOT NULL REFERENCES dbo.warehouses(id),
    [quantity] BIGINT NOT NULL CHECK (quantity > 0),
    [unit_price] FLOAT(53) NOT NULL CHECK (unit_price >= 0),
    [discount_amount] FLOAT(53) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    [line_total] FLOAT(53) NOT NULL CHECK (line_total >= 0)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.order_items') AND name = 'idx_order_items_order')
    CREATE INDEX idx_order_items_order ON dbo.order_items(order_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.order_items') AND name = 'idx_order_items_product')
    CREATE INDEX idx_order_items_product ON dbo.order_items(product_id);
GO

IF OBJECT_ID(N'dbo.payments', N'U') IS NULL
    CREATE TABLE dbo.payments (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [order_id] BIGINT NOT NULL UNIQUE REFERENCES dbo.orders(id),
    [method] NVARCHAR(MAX) NOT NULL CHECK (method IN ('cod', 'bank_transfer', 'demo_card')),
    [status] NVARCHAR(25) NOT NULL CHECK (status IN ('success', 'refunded')),
    [amount] FLOAT(53) NOT NULL CHECK (amount >= 0),
    [transaction_ref] NVARCHAR(100) NOT NULL UNIQUE,
    [paid_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF OBJECT_ID(N'dbo.invoices', N'U') IS NULL
    CREATE TABLE dbo.invoices (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [order_id] BIGINT NOT NULL UNIQUE REFERENCES dbo.orders(id),
    [invoice_number] NVARCHAR(100) NOT NULL UNIQUE,
    [issued_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [total_amount] FLOAT(53) NOT NULL CHECK (total_amount >= 0)
);
GO

IF OBJECT_ID(N'dbo.procurement_receipts', N'U') IS NULL
    CREATE TABLE dbo.procurement_receipts (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [receipt_number] NVARCHAR(100) NOT NULL UNIQUE,
    [supplier_id] BIGINT NOT NULL REFERENCES dbo.suppliers(id),
    [warehouse_id] BIGINT NOT NULL REFERENCES dbo.warehouses(id),
    [employee_id] BIGINT NOT NULL REFERENCES dbo.users(id),
    [status] NVARCHAR(25) NOT NULL DEFAULT 'received' CHECK (status = 'received'),
    [total_cost] FLOAT(53) NOT NULL CHECK (total_cost >= 0),
    [notes] NVARCHAR(MAX),
    [received_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126)),
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.procurement_receipts') AND name = 'idx_procurement_received')
    CREATE INDEX idx_procurement_received ON dbo.procurement_receipts(received_at);
GO

IF OBJECT_ID(N'dbo.procurement_items', N'U') IS NULL
    CREATE TABLE dbo.procurement_items (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [receipt_id] BIGINT NOT NULL REFERENCES dbo.procurement_receipts(id) ON DELETE CASCADE,
    [product_id] BIGINT NOT NULL REFERENCES dbo.products(id),
    [quantity] BIGINT NOT NULL CHECK (quantity > 0),
    [unit_cost] FLOAT(53) NOT NULL CHECK (unit_cost >= 0),
    [line_total] FLOAT(53) NOT NULL CHECK (line_total >= 0)
);
GO

IF OBJECT_ID(N'dbo.audit_log', N'U') IS NULL
    CREATE TABLE dbo.audit_log (
    [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [actor_user_id] BIGINT REFERENCES dbo.users(id),
    [action] NVARCHAR(MAX) NOT NULL,
    [entity_type] NVARCHAR(MAX) NOT NULL,
    [entity_id] NVARCHAR(MAX),
    [details] NVARCHAR(MAX),
    [created_at] NVARCHAR(33) NOT NULL DEFAULT (CONVERT(nvarchar(19), SYSUTCDATETIME(), 126))
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.audit_log') AND name = 'idx_audit_created')
    CREATE INDEX idx_audit_created ON dbo.audit_log(created_at);
GO
