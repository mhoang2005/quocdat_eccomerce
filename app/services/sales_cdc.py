"""Capture the current sales lines for orders touched since the last ETL."""

SALES_SOURCE = """
    SELECT oi.id, o.id, o.order_number, inv.invoice_number, o.created_at,
           o.customer_id, oi.product_id, p.natural_key, pl.name,
           oi.warehouse_id, oi.quantity, oi.unit_price, oi.discount_amount,
           oi.quantity * oi.unit_price AS gross_amount, oi.line_total AS net_amount
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    JOIN invoices inv ON inv.order_id = o.id
    JOIN products p ON p.id = oi.product_id
    JOIN platforms pl ON pl.id = p.platform_id
    WHERE o.payment_status = 'paid' AND o.status != 'cancelled'
"""
STAGE_SALES = """
    INSERT INTO stg_sales_line(
        source_order_item_id, source_order_id, order_number, invoice_number,
        order_at, customer_id, product_id, product_nk, platform_name,
        warehouse_id, quantity, unit_price, discount_amount, gross_amount,
        net_amount, batch_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def stage_sales(oltp, staging, batch_id, full):
    checkpoint = staging.execute(
        "SELECT event_id FROM cdc_checkpoint WHERE stream = 'sales'"
    ).fetchone()
    through = oltp.execute("SELECT COALESCE(MAX(event_id), 0) FROM cdc_event").fetchone()[0]
    previous = checkpoint[0] if checkpoint else 0
    baseline = full or checkpoint is None or through < previous
    changed_orders = ()
    events = 0
    source = ()
    if baseline:
        staging.execute("DELETE FROM stg_sales_line")
        source = oltp.execute(SALES_SOURCE)
    elif through > previous:
        event_filter = "FROM cdc_event WHERE event_id > ? AND event_id <= ?"
        bounds = (previous, through)
        events = oltp.execute("SELECT COUNT(*) " + event_filter, bounds).fetchone()[0]
        staging.execute("CREATE TEMP TABLE IF NOT EXISTS changed_sales_order (id INTEGER PRIMARY KEY)")
        staging.execute("DELETE FROM changed_sales_order")
        changed_orders = oltp.execute("SELECT DISTINCT order_id " + event_filter, bounds).fetchall()
        staging.executemany("INSERT INTO changed_sales_order VALUES (?)", changed_orders)
        staging.execute(
            "DELETE FROM stg_sales_line WHERE source_order_id IN (SELECT id FROM changed_sales_order)"
        )
        source = oltp.execute(
            SALES_SOURCE + " AND o.id IN (SELECT order_id " + event_filter + ")", bounds
        )
    staged = staging.executemany(STAGE_SALES, (tuple(row) + (batch_id,) for row in source)).rowcount
    orders = len(changed_orders)
    if baseline:
        orders = staging.execute("SELECT COUNT(DISTINCT source_order_id) FROM stg_sales_line").fetchone()[0]
    if baseline or through > previous:
        staging.execute(
            """
            INSERT INTO cdc_checkpoint(stream, event_id) VALUES ('sales', ?)
            ON CONFLICT(stream) DO UPDATE SET event_id = excluded.event_id
            """,
            (through,),
        )
    return {
        "mode": "baseline" if baseline else "delta",
        "from_event_id": previous,
        "through_event_id": through,
        "events": events,
        "orders": orders,
        "staged": staged,
    }, changed_orders


def ensure_sales_fact_order_key(dwh):
    if getattr(dwh, "dialect", None) == "sqlserver":
        return
    columns = {row["name"] for row in dwh.execute("PRAGMA table_info(fact_sales)")}
    if "source_order_id" not in columns:
        dwh.execute("ALTER TABLE fact_sales ADD COLUMN source_order_id INTEGER")
    dwh.execute("CREATE INDEX IF NOT EXISTS idx_fact_sales_source_order ON fact_sales(source_order_id)")


def remove_stale_sales(dwh, staging, batch_id, baseline, changed_orders):
    if not baseline and not changed_orders:
        return 0
    dwh.execute("CREATE TEMP TABLE IF NOT EXISTS current_sales_line (id INTEGER PRIMARY KEY)")
    dwh.execute("DELETE FROM current_sales_line")
    dwh.executemany(
        "INSERT INTO current_sales_line VALUES (?)",
        staging.execute("SELECT source_order_item_id FROM stg_sales_line WHERE batch_id = ?", (batch_id,)),
    )
    stale = "DELETE FROM fact_sales WHERE source_order_item_id NOT IN (SELECT id FROM current_sales_line)"
    if baseline:
        return dwh.execute(stale).rowcount
    return dwh.executemany(stale + " AND source_order_id = ?", changed_orders).rowcount
