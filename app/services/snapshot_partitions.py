"""Monthly SQLite tables used by the marketplace dashboard."""

FACT = "fact_product_snapshot"
PARTITION_COLUMNS = (
    "product_snapshot_key, date_key, product_key, platform_key, sale_price, "
    "discount_rate, rating, review_count, quantity_sold_snapshot"
)


def refresh_snapshot_months(connection):
    """Rebuild changed partitions inside the caller's write transaction."""
    if getattr(connection, "dialect", None) == "sqlserver":
        return 0
    months = connection.execute(
        "SELECT month_key FROM snapshot_month WHERE dirty = 1 ORDER BY month_key"
    ).fetchall()
    for (month,) in months:
        table = f"snapshot_{month:d}"
        first_day = month * 100 + 1
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                product_snapshot_key INTEGER PRIMARY KEY,
                date_key INTEGER NOT NULL CHECK (date_key / 100 = {month:d}),
                product_key INTEGER NOT NULL,
                platform_key INTEGER NOT NULL,
                sale_price REAL,
                discount_rate REAL,
                rating REAL,
                review_count INTEGER,
                quantity_sold_snapshot INTEGER
            )
            """
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_platform_date_price "
            f"ON {table}(platform_key, date_key, sale_price)"
        )
        connection.execute(f"DELETE FROM {table}")
        connection.execute(
            f"""
            INSERT INTO {table} ({PARTITION_COLUMNS})
            SELECT {PARTITION_COLUMNS} FROM {FACT}
            WHERE date_key >= ? AND date_key < ?
            """,
            (first_day, first_day + 100),
        )
        connection.execute("UPDATE snapshot_month SET dirty = 0 WHERE month_key = ?", (month,))
    return len(months)


def snapshot_source(connection, year, month):
    if year is None or month is None or getattr(connection, "dialect", None) == "sqlserver":
        return FACT
    month_key = year * 100 + month
    table = f"snapshot_{month_key:d}"
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'snapshot_month'"
    ).fetchone():
        return FACT
    ready = connection.execute(
        """
        SELECT 1 FROM snapshot_month
        WHERE month_key = ? AND dirty = 0
          AND EXISTS (SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?)
        """,
        (month_key, table),
    ).fetchone()
    return table if ready else FACT
