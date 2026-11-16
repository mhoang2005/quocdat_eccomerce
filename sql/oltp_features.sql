BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS employee_warehouse (
    employee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    PRIMARY KEY (employee_id, warehouse_id)
);

CREATE TABLE IF NOT EXISTS oltp_feature_migration (name TEXT PRIMARY KEY);

CREATE INDEX IF NOT EXISTS idx_procurement_warehouse ON procurement_receipts(warehouse_id);

INSERT OR IGNORE INTO employee_warehouse(employee_id, warehouse_id)
SELECT u.id, w.id
FROM users u CROSS JOIN warehouses w
WHERE u.email = 'employee@quocdat.local' AND u.role = 'employee'
  AND w.warehouse_code = 'WH-HN'
  AND NOT EXISTS (SELECT 1 FROM oltp_feature_migration WHERE name = 'sales_cdc_and_warehouse_scope');

CREATE TABLE IF NOT EXISTS cdc_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    order_id INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS cdc_orders_insert AFTER INSERT ON orders
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('orders', 'INSERT', NEW.id);
END;

CREATE TRIGGER IF NOT EXISTS cdc_orders_update AFTER UPDATE ON orders
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('orders', 'UPDATE', NEW.id);
    INSERT INTO cdc_event(source_table, operation, order_id)
    SELECT 'orders', 'UPDATE', OLD.id WHERE OLD.id != NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS cdc_orders_delete AFTER DELETE ON orders
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('orders', 'DELETE', OLD.id);
END;

CREATE TRIGGER IF NOT EXISTS cdc_order_items_insert AFTER INSERT ON order_items
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('order_items', 'INSERT', NEW.order_id);
END;

CREATE TRIGGER IF NOT EXISTS cdc_order_items_update AFTER UPDATE ON order_items
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('order_items', 'UPDATE', NEW.order_id);
    INSERT INTO cdc_event(source_table, operation, order_id)
    SELECT 'order_items', 'UPDATE', OLD.order_id WHERE OLD.order_id != NEW.order_id;
END;

CREATE TRIGGER IF NOT EXISTS cdc_order_items_delete AFTER DELETE ON order_items
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('order_items', 'DELETE', OLD.order_id);
END;

CREATE TRIGGER IF NOT EXISTS cdc_invoices_insert AFTER INSERT ON invoices
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('invoices', 'INSERT', NEW.order_id);
END;

CREATE TRIGGER IF NOT EXISTS cdc_invoices_update AFTER UPDATE ON invoices
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('invoices', 'UPDATE', NEW.order_id);
    INSERT INTO cdc_event(source_table, operation, order_id)
    SELECT 'invoices', 'UPDATE', OLD.order_id WHERE OLD.order_id != NEW.order_id;
END;

CREATE TRIGGER IF NOT EXISTS cdc_invoices_delete AFTER DELETE ON invoices
BEGIN
    INSERT INTO cdc_event(source_table, operation, order_id)
    VALUES ('invoices', 'DELETE', OLD.order_id);
END;

INSERT OR IGNORE INTO oltp_feature_migration(name) VALUES ('sales_cdc_and_warehouse_scope');
COMMIT;
