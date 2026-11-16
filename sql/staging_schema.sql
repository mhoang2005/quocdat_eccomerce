PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS etl_batch (
    batch_id TEXT PRIMARY KEY,
    batch_type TEXT NOT NULL,
    status TEXT NOT NULL,
    source_started_at TEXT NOT NULL,
    completed_at TEXT,
    source_row_count INTEGER NOT NULL DEFAULT 0,
    valid_row_count INTEGER NOT NULL DEFAULT 0,
    warning_row_count INTEGER NOT NULL DEFAULT 0,
    invalid_row_count INTEGER NOT NULL DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS stg_product_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    natural_key TEXT NOT NULL,
    platform_product_id TEXT,
    sku TEXT,
    snapshot_at TEXT NOT NULL,
    product_name TEXT,
    category_name TEXT,
    category_l1 TEXT,
    category_l2 TEXT,
    category_l3 TEXT,
    brand_name TEXT,
    seller_id TEXT,
    seller_type TEXT,
    origin TEXT,
    list_price REAL,
    sale_price REAL,
    discount_amount REAL,
    discount_rate REAL,
    quantity_sold INTEGER,
    rating REAL,
    review_count INTEGER,
    image_url TEXT,
    is_duplicate INTEGER NOT NULL DEFAULT 0 CHECK (is_duplicate IN (0, 1)),
    dq_status TEXT NOT NULL CHECK (dq_status IN ('VALID', 'WARNING', 'INVALID')),
    dq_message TEXT,
    record_hash TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    staged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stg_product_nk ON stg_product_snapshot(natural_key);
CREATE INDEX IF NOT EXISTS idx_stg_product_snapshot_at ON stg_product_snapshot(snapshot_at);
CREATE INDEX IF NOT EXISTS idx_stg_product_hash ON stg_product_snapshot(record_hash);

CREATE TABLE IF NOT EXISTS stg_customer (
    customer_id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    city TEXT,
    address TEXT,
    is_active INTEGER NOT NULL,
    source_updated_at TEXT NOT NULL,
    batch_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_sales_line (
    source_order_item_id INTEGER PRIMARY KEY,
    source_order_id INTEGER NOT NULL,
    order_number TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    order_at TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    product_nk TEXT NOT NULL,
    platform_name TEXT NOT NULL,
    warehouse_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    discount_amount REAL NOT NULL,
    gross_amount REAL NOT NULL,
    net_amount REAL NOT NULL,
    batch_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_procurement_line (
    source_procurement_item_id INTEGER PRIMARY KEY,
    source_receipt_id INTEGER NOT NULL,
    receipt_number TEXT NOT NULL,
    received_at TEXT NOT NULL,
    supplier_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    product_nk TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    total_cost REAL NOT NULL,
    batch_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stg_sales_order ON stg_sales_line(source_order_id);
CREATE INDEX IF NOT EXISTS idx_stg_sales_batch ON stg_sales_line(batch_id);

CREATE TABLE IF NOT EXISTS cdc_checkpoint (
    stream TEXT PRIMARY KEY,
    event_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_inventory_snapshot (
    product_id INTEGER NOT NULL,
    product_nk TEXT NOT NULL,
    warehouse_id INTEGER NOT NULL,
    snapshot_at TEXT NOT NULL,
    quantity_on_hand INTEGER NOT NULL,
    average_cost REAL NOT NULL,
    inventory_value REAL NOT NULL,
    batch_id TEXT NOT NULL,
    PRIMARY KEY (product_id, warehouse_id)
);

