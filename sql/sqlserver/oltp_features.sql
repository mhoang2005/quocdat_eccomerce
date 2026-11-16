IF OBJECT_ID('dbo.employee_warehouse', 'U') IS NULL
    CREATE TABLE dbo.employee_warehouse (
        employee_id bigint NOT NULL REFERENCES dbo.users(id) ON DELETE CASCADE,
        warehouse_id bigint NOT NULL REFERENCES dbo.warehouses(id) ON DELETE CASCADE,
        PRIMARY KEY (employee_id, warehouse_id)
    );
IF OBJECT_ID('dbo.oltp_feature_migration', 'U') IS NULL
    CREATE TABLE dbo.oltp_feature_migration (
        name nvarchar(120) PRIMARY KEY
    );
IF OBJECT_ID('dbo.cdc_event', 'U') IS NULL
    CREATE TABLE dbo.cdc_event (
        event_id bigint IDENTITY(1,1) PRIMARY KEY,
        source_table nvarchar(40) NOT NULL,
        operation nvarchar(10) NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
        order_id bigint NOT NULL
    );
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.procurement_receipts') AND name = 'idx_procurement_warehouse')
    CREATE INDEX idx_procurement_warehouse ON dbo.procurement_receipts(warehouse_id);
GO

CREATE OR ALTER TRIGGER dbo.cdc_orders ON dbo.orders
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO dbo.cdc_event(source_table, operation, order_id)
    SELECT 'orders',
           CASE WHEN d.id IS NULL THEN 'INSERT' WHEN i.id IS NULL THEN 'DELETE' ELSE 'UPDATE' END,
           touched.order_id
    FROM inserted i
    FULL JOIN deleted d ON i.id = d.id
    CROSS APPLY (
        SELECT i.id AS order_id WHERE i.id IS NOT NULL
        UNION
        SELECT d.id WHERE d.id IS NOT NULL
    ) touched;
END;
GO

CREATE OR ALTER TRIGGER dbo.cdc_order_items ON dbo.order_items
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO dbo.cdc_event(source_table, operation, order_id)
    SELECT 'order_items',
           CASE WHEN d.id IS NULL THEN 'INSERT' WHEN i.id IS NULL THEN 'DELETE' ELSE 'UPDATE' END,
           touched.order_id
    FROM inserted i
    FULL JOIN deleted d ON i.id = d.id
    CROSS APPLY (
        SELECT i.order_id AS order_id WHERE i.id IS NOT NULL
        UNION
        SELECT d.order_id WHERE d.id IS NOT NULL
    ) touched;
END;
GO

CREATE OR ALTER TRIGGER dbo.cdc_invoices ON dbo.invoices
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO dbo.cdc_event(source_table, operation, order_id)
    SELECT 'invoices',
           CASE WHEN d.id IS NULL THEN 'INSERT' WHEN i.id IS NULL THEN 'DELETE' ELSE 'UPDATE' END,
           touched.order_id
    FROM inserted i
    FULL JOIN deleted d ON i.id = d.id
    CROSS APPLY (
        SELECT i.order_id AS order_id WHERE i.id IS NOT NULL
        UNION
        SELECT d.order_id WHERE d.id IS NOT NULL
    ) touched;
END;
GO

IF OBJECT_ID(N'dbo.qd_warehouse_access', N'IF') IS NULL
EXEC(N'CREATE FUNCTION dbo.qd_warehouse_access(@warehouse_id bigint)
RETURNS TABLE WITH SCHEMABINDING AS RETURN
    SELECT 1 AS allowed
    WHERE ISNULL(CONVERT(nvarchar(20), SESSION_CONTEXT(N''qd_role'')), N'''') <> N''employee''
       OR EXISTS (
           SELECT 1 FROM dbo.employee_warehouse ew
           WHERE ew.employee_id = TRY_CONVERT(bigint, SESSION_CONTEXT(N''qd_user''))
             AND ew.warehouse_id = @warehouse_id
       );');
GO

IF OBJECT_ID(N'dbo.qd_order_access', N'IF') IS NULL
EXEC(N'CREATE FUNCTION dbo.qd_order_access(@customer_id bigint)
RETURNS TABLE WITH SCHEMABINDING AS RETURN
    SELECT 1 AS allowed
    WHERE ISNULL(CONVERT(nvarchar(20), SESSION_CONTEXT(N''qd_role'')), N'''') <> N''customer''
       OR @customer_id = TRY_CONVERT(bigint, SESSION_CONTEXT(N''qd_user''));');
GO

IF NOT EXISTS (SELECT 1 FROM sys.security_policies WHERE name = 'qd_warehouse_security')
    CREATE SECURITY POLICY dbo.qd_warehouse_security
        ADD FILTER PREDICATE dbo.qd_warehouse_access(warehouse_id) ON dbo.inventory,
        ADD BLOCK PREDICATE dbo.qd_warehouse_access(warehouse_id) ON dbo.inventory AFTER INSERT,
        ADD BLOCK PREDICATE dbo.qd_warehouse_access(warehouse_id) ON dbo.inventory AFTER UPDATE,
        ADD FILTER PREDICATE dbo.qd_warehouse_access(warehouse_id) ON dbo.procurement_receipts,
        ADD BLOCK PREDICATE dbo.qd_warehouse_access(warehouse_id) ON dbo.procurement_receipts AFTER INSERT,
        ADD BLOCK PREDICATE dbo.qd_warehouse_access(warehouse_id) ON dbo.procurement_receipts AFTER UPDATE
        WITH (STATE = ON);
IF NOT EXISTS (SELECT 1 FROM sys.security_policies WHERE name = 'qd_order_security')
    CREATE SECURITY POLICY dbo.qd_order_security
        ADD FILTER PREDICATE dbo.qd_order_access(customer_id) ON dbo.orders,
        ADD BLOCK PREDICATE dbo.qd_order_access(customer_id) ON dbo.orders AFTER INSERT,
        ADD BLOCK PREDICATE dbo.qd_order_access(customer_id) ON dbo.orders AFTER UPDATE
        WITH (STATE = ON);
GO
