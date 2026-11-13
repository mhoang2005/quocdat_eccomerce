PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date TEXT NOT NULL UNIQUE,
    day_of_month INTEGER NOT NULL,
    day_name TEXT NOT NULL,
    week_of_year INTEGER NOT NULL,
    month_number INTEGER NOT NULL,
    month_name TEXT NOT NULL,
    quarter_number INTEGER NOT NULL,
    year_number INTEGER NOT NULL,
    is_weekend INTEGER NOT NULL CHECK (is_weekend IN (0, 1))
);

CREATE TABLE IF NOT EXISTS dim_platform (
    platform_key INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_nk INTEGER NOT NULL UNIQUE,
    platform_code TEXT NOT NULL,
    platform_name TEXT NOT NULL,
    is_active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_key INTEGER PRIMARY KEY AUTOINCREMENT,
    product_nk TEXT NOT NULL,
    source_product_id INTEGER,
    product_code TEXT,
    product_name TEXT NOT NULL,
    category_name TEXT NOT NULL,
    platform_name TEXT NOT NULL,
    brand_name TEXT,
    origin TEXT,
    is_active INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
    attribute_hash TEXT NOT NULL,
    UNIQUE (product_nk, valid_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dim_product_current
ON dim_product(product_nk) WHERE is_current = 1;
CREATE INDEX IF NOT EXISTS idx_dim_product_effective
ON dim_product(product_nk, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS dim_customer (
    customer_key INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_nk INTEGER NOT NULL UNIQUE,
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    city TEXT,
    address TEXT,
    is_active INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_supplier (
    supplier_key INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_nk INTEGER NOT NULL UNIQUE,
    supplier_code TEXT NOT NULL,
    supplier_name TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    is_active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_warehouse (
    warehouse_key INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_nk INTEGER NOT NULL UNIQUE,
    warehouse_code TEXT NOT NULL,
    warehouse_name TEXT NOT NULL,
    address TEXT NOT NULL,
    is_active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_sales (
    sales_key INTEGER PRIMARY KEY AUTOINCREMENT,
    date_key INTEGER NOT NULL REFERENCES dim_date(date_key),
    product_key INTEGER NOT NULL REFERENCES dim_product(product_key),
    customer_key INTEGER NOT NULL REFERENCES dim_customer(customer_key),
    platform_key INTEGER NOT NULL REFERENCES dim_platform(platform_key),
    warehouse_key INTEGER NOT NULL REFERENCES dim_warehouse(warehouse_key),
    source_order_item_id INTEGER NOT NULL UNIQUE,
    order_number TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    discount_amount REAL NOT NULL,
    gross_amount REAL NOT NULL,
    net_amount REAL NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fact_sales_date_product ON fact_sales(date_key, product_key);

CREATE TABLE IF NOT EXISTS fact_procurement (
    procurement_key INTEGER PRIMARY KEY AUTOINCREMENT,
    date_key INTEGER NOT NULL REFERENCES dim_date(date_key),
    product_key INTEGER NOT NULL REFERENCES dim_product(product_key),
    supplier_key INTEGER NOT NULL REFERENCES dim_supplier(supplier_key),
    warehouse_key INTEGER NOT NULL REFERENCES dim_warehouse(warehouse_key),
    source_procurement_item_id INTEGER NOT NULL UNIQUE,
    receipt_number TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    total_cost REAL NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fact_procurement_date_product
ON fact_procurement(date_key, product_key);

CREATE TABLE IF NOT EXISTS fact_inventory (
    inventory_key INTEGER PRIMARY KEY AUTOINCREMENT,
    date_key INTEGER NOT NULL REFERENCES dim_date(date_key),
    product_key INTEGER NOT NULL REFERENCES dim_product(product_key),
    warehouse_key INTEGER NOT NULL REFERENCES dim_warehouse(warehouse_key),
    quantity_on_hand INTEGER NOT NULL,
    average_cost REAL NOT NULL,
    inventory_value REAL NOT NULL,
    snapshot_at TEXT NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (date_key, product_key, warehouse_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_inventory_date_product
ON fact_inventory(date_key, product_key);

CREATE TABLE IF NOT EXISTS fact_product_snapshot (
    product_snapshot_key INTEGER PRIMARY KEY AUTOINCREMENT,
    date_key INTEGER NOT NULL REFERENCES dim_date(date_key),
    product_key INTEGER NOT NULL REFERENCES dim_product(product_key),
    platform_key INTEGER NOT NULL REFERENCES dim_platform(platform_key),
    source_record_hash TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    list_price REAL,
    sale_price REAL,
    discount_amount REAL,
    discount_rate REAL,
    quantity_sold_snapshot INTEGER,
    rating REAL,
    review_count INTEGER,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_record_hash, snapshot_at)
);

CREATE INDEX IF NOT EXISTS idx_fact_product_snapshot_date_product
ON fact_product_snapshot(date_key, product_key);

CREATE TABLE IF NOT EXISTS etl_run (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    staged_rows INTEGER NOT NULL DEFAULT 0,
    dimension_rows INTEGER NOT NULL DEFAULT 0,
    fact_rows INTEGER NOT NULL DEFAULT 0,
    warning_rows INTEGER NOT NULL DEFAULT 0,
    message TEXT
);

-- SQLite does not provide native materialized views. The following physical
-- aggregate tables are refreshed after ETL and behave as complete-refresh MVs.
CREATE TABLE IF NOT EXISTS mv_sales_daily (
    date_key INTEGER NOT NULL,
    full_date TEXT NOT NULL,
    year_number INTEGER NOT NULL,
    quarter_number INTEGER NOT NULL,
    month_number INTEGER NOT NULL,
    platform_key INTEGER NOT NULL,
    platform_name TEXT NOT NULL,
    warehouse_key INTEGER NOT NULL,
    warehouse_name TEXT NOT NULL,
    category_name TEXT NOT NULL,
    order_count INTEGER NOT NULL,
    customer_count INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    quantity_sold INTEGER NOT NULL,
    gross_revenue REAL NOT NULL,
    discount_amount REAL NOT NULL,
    net_revenue REAL NOT NULL,
    average_selling_price REAL NOT NULL,
    refreshed_at TEXT NOT NULL,
    PRIMARY KEY (date_key, platform_key, warehouse_key, category_name)
);

CREATE INDEX IF NOT EXISTS idx_mv_sales_daily_slice
ON mv_sales_daily(year_number, month_number, platform_name, category_name);

CREATE TABLE IF NOT EXISTS mv_procurement_daily (
    date_key INTEGER NOT NULL,
    full_date TEXT NOT NULL,
    year_number INTEGER NOT NULL,
    quarter_number INTEGER NOT NULL,
    month_number INTEGER NOT NULL,
    supplier_key INTEGER NOT NULL,
    supplier_name TEXT NOT NULL,
    warehouse_key INTEGER NOT NULL,
    warehouse_name TEXT NOT NULL,
    category_name TEXT NOT NULL,
    receipt_count INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    quantity_received INTEGER NOT NULL,
    procurement_cost REAL NOT NULL,
    average_unit_cost REAL NOT NULL,
    refreshed_at TEXT NOT NULL,
    PRIMARY KEY (date_key, supplier_key, warehouse_key, category_name)
);

CREATE INDEX IF NOT EXISTS idx_mv_procurement_daily_slice
ON mv_procurement_daily(year_number, month_number, supplier_name, warehouse_name);

CREATE TABLE IF NOT EXISTS mv_inventory_daily (
    date_key INTEGER NOT NULL,
    full_date TEXT NOT NULL,
    year_number INTEGER NOT NULL,
    quarter_number INTEGER NOT NULL,
    month_number INTEGER NOT NULL,
    platform_name TEXT NOT NULL,
    warehouse_key INTEGER NOT NULL,
    warehouse_name TEXT NOT NULL,
    category_name TEXT NOT NULL,
    product_count INTEGER NOT NULL,
    quantity_on_hand INTEGER NOT NULL,
    inventory_value REAL NOT NULL,
    average_unit_cost REAL NOT NULL,
    refreshed_at TEXT NOT NULL,
    PRIMARY KEY (date_key, platform_name, warehouse_key, category_name)
);

CREATE INDEX IF NOT EXISTS idx_mv_inventory_daily_slice
ON mv_inventory_daily(year_number, month_number, platform_name, warehouse_name);

CREATE TABLE IF NOT EXISTS mv_marketplace_daily (
    date_key INTEGER NOT NULL,
    full_date TEXT NOT NULL,
    year_number INTEGER NOT NULL,
    quarter_number INTEGER NOT NULL,
    month_number INTEGER NOT NULL,
    platform_key INTEGER NOT NULL,
    platform_name TEXT NOT NULL,
    category_name TEXT NOT NULL,
    product_count INTEGER NOT NULL,
    snapshot_count INTEGER NOT NULL,
    average_list_price REAL NOT NULL,
    average_sale_price REAL NOT NULL,
    average_discount_rate REAL NOT NULL,
    average_rating REAL NOT NULL,
    review_count_snapshot INTEGER NOT NULL,
    sold_quantity_snapshot INTEGER NOT NULL,
    refreshed_at TEXT NOT NULL,
    PRIMARY KEY (date_key, platform_key, category_name)
);

CREATE INDEX IF NOT EXISTS idx_mv_marketplace_daily_slice
ON mv_marketplace_daily(year_number, month_number, platform_name, category_name);

-- Precomputed Sales Cube aligned with the course model. Time is represented
-- by a hierarchy level while the other dimensions map as follows:
-- Product=Category, Customer=Dim_Customer member, Location=Customer City,
-- Store/Seller=Platform sales channel. grouping_mask uses bit 1=Store/Seller
-- ALL, bit 2=Product ALL, bit 4=Customer ALL, bit 8=Location ALL.
CREATE TABLE IF NOT EXISTS cube_sales (
    cube_key INTEGER PRIMARY KEY AUTOINCREMENT,
    time_level TEXT NOT NULL CHECK (time_level IN ('DAY', 'MONTH', 'QUARTER', 'YEAR', 'ALL')),
    time_key TEXT NOT NULL,
    time_label TEXT NOT NULL,
    date_key INTEGER,
    year_number INTEGER,
    quarter_number INTEGER,
    month_number INTEGER,
    platform_name TEXT NOT NULL,
    category_name TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_city TEXT NOT NULL,
    grouping_mask INTEGER NOT NULL CHECK (grouping_mask BETWEEN 0 AND 15),
    order_count INTEGER NOT NULL,
    customer_count INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    quantity_sold INTEGER NOT NULL,
    gross_revenue REAL NOT NULL,
    discount_amount REAL NOT NULL,
    net_revenue REAL NOT NULL,
    average_selling_price REAL NOT NULL,
    refreshed_at TEXT NOT NULL,
    UNIQUE (
        time_level, time_key, platform_name, category_name,
        customer_name, customer_city
    )
);

CREATE INDEX IF NOT EXISTS idx_cube_sales_slice
ON cube_sales(
    time_level, platform_name, category_name, customer_name, customer_city
);
CREATE INDEX IF NOT EXISTS idx_cube_sales_rollup
ON cube_sales(time_level, time_key, grouping_mask);

CREATE TABLE IF NOT EXISTS olap_refresh_run (
    refresh_id TEXT PRIMARY KEY,
    source_etl_run_id TEXT,
    refresh_type TEXT NOT NULL DEFAULT 'COMPLETE',
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    materialized_rows INTEGER NOT NULL DEFAULT 0,
    cube_rows INTEGER NOT NULL DEFAULT 0,
    message TEXT
);
