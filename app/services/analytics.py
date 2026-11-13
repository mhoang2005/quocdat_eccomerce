from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import click

from app.db import execute_script, get_db


MATERIALIZED_VIEWS = {
    "mv_sales_daily": {
        "label": "Daily Sales",
        "grain": "Date × Platform × Category × Warehouse",
        "source": "Fact_Sales",
    },
    "mv_procurement_daily": {
        "label": "Daily Procurement",
        "grain": "Date × Supplier × Category × Warehouse",
        "source": "Fact_Procurement",
    },
    "mv_inventory_daily": {
        "label": "Daily Inventory",
        "grain": "Date × Platform × Category × Warehouse",
        "source": "Fact_Inventory",
    },
    "mv_marketplace_daily": {
        "label": "Daily Marketplace Snapshot",
        "grain": "Date × Platform × Category",
        "source": "Fact_Product_Snapshot",
    },
}

OLAP_TABLES = (*MATERIALIZED_VIEWS.keys(), "cube_sales")


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _ensure_olap_schema() -> None:
    """Apply the DDL and replace obsolete derived Cube schemas when required."""
    execute_script("dwh", "dwh_schema.sql")
    connection = get_db("dwh")
    cube_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(cube_sales)")
    }
    required_columns = {"customer_name", "customer_city"}
    if cube_columns and not required_columns.issubset(cube_columns):
        connection.execute("DROP TABLE cube_sales")
        connection.commit()
        execute_script("dwh", "dwh_schema.sql")


MV_REFRESH_SQL = {
    "mv_sales_daily": """
        INSERT INTO mv_sales_daily(
            date_key, full_date, year_number, quarter_number, month_number,
            platform_key, platform_name, warehouse_key, warehouse_name,
            category_name, order_count, customer_count, line_count,
            quantity_sold, gross_revenue, discount_amount, net_revenue,
            average_selling_price, refreshed_at
        )
        SELECT d.date_key, d.full_date, d.year_number, d.quarter_number,
               d.month_number, p.platform_key, p.platform_name,
               w.warehouse_key, w.warehouse_name, pr.category_name,
               COUNT(DISTINCT f.order_number),
               COUNT(DISTINCT f.customer_key),
               COUNT(*),
               COALESCE(SUM(f.quantity), 0),
               COALESCE(SUM(f.gross_amount), 0),
               COALESCE(SUM(f.discount_amount), 0),
               COALESCE(SUM(f.net_amount), 0),
               COALESCE(SUM(f.net_amount) / NULLIF(SUM(f.quantity), 0), 0),
               ?
        FROM fact_sales f
        JOIN dim_date d ON d.date_key = f.date_key
        JOIN dim_product pr ON pr.product_key = f.product_key
        JOIN dim_platform p ON p.platform_key = f.platform_key
        JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        GROUP BY d.date_key, d.full_date, d.year_number, d.quarter_number,
                 d.month_number, p.platform_key, p.platform_name,
                 w.warehouse_key, w.warehouse_name, pr.category_name
    """,
    "mv_procurement_daily": """
        INSERT INTO mv_procurement_daily(
            date_key, full_date, year_number, quarter_number, month_number,
            supplier_key, supplier_name, warehouse_key, warehouse_name,
            category_name, receipt_count, line_count, quantity_received,
            procurement_cost, average_unit_cost, refreshed_at
        )
        SELECT d.date_key, d.full_date, d.year_number, d.quarter_number,
               d.month_number, s.supplier_key, s.supplier_name,
               w.warehouse_key, w.warehouse_name, pr.category_name,
               COUNT(DISTINCT f.receipt_number),
               COUNT(*),
               COALESCE(SUM(f.quantity), 0),
               COALESCE(SUM(f.total_cost), 0),
               COALESCE(SUM(f.total_cost) / NULLIF(SUM(f.quantity), 0), 0),
               ?
        FROM fact_procurement f
        JOIN dim_date d ON d.date_key = f.date_key
        JOIN dim_product pr ON pr.product_key = f.product_key
        JOIN dim_supplier s ON s.supplier_key = f.supplier_key
        JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        GROUP BY d.date_key, d.full_date, d.year_number, d.quarter_number,
                 d.month_number, s.supplier_key, s.supplier_name,
                 w.warehouse_key, w.warehouse_name, pr.category_name
    """,
    "mv_inventory_daily": """
        INSERT INTO mv_inventory_daily(
            date_key, full_date, year_number, quarter_number, month_number,
            platform_name, warehouse_key, warehouse_name, category_name,
            product_count, quantity_on_hand, inventory_value,
            average_unit_cost, refreshed_at
        )
        SELECT d.date_key, d.full_date, d.year_number, d.quarter_number,
               d.month_number, pr.platform_name, w.warehouse_key,
               w.warehouse_name, pr.category_name,
               COUNT(DISTINCT f.product_key),
               COALESCE(SUM(f.quantity_on_hand), 0),
               COALESCE(SUM(f.inventory_value), 0),
               COALESCE(SUM(f.inventory_value) /
                        NULLIF(SUM(f.quantity_on_hand), 0), 0),
               ?
        FROM fact_inventory f
        JOIN dim_date d ON d.date_key = f.date_key
        JOIN dim_product pr ON pr.product_key = f.product_key
        JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        GROUP BY d.date_key, d.full_date, d.year_number, d.quarter_number,
                 d.month_number, pr.platform_name, w.warehouse_key,
                 w.warehouse_name, pr.category_name
    """,
    "mv_marketplace_daily": """
        INSERT INTO mv_marketplace_daily(
            date_key, full_date, year_number, quarter_number, month_number,
            platform_key, platform_name, category_name, product_count,
            snapshot_count, average_list_price, average_sale_price,
            average_discount_rate, average_rating, review_count_snapshot,
            sold_quantity_snapshot, refreshed_at
        )
        SELECT d.date_key, d.full_date, d.year_number, d.quarter_number,
               d.month_number, p.platform_key, p.platform_name,
               pr.category_name, COUNT(DISTINCT f.product_key), COUNT(*),
               COALESCE(AVG(f.list_price), 0),
               COALESCE(AVG(f.sale_price), 0),
               COALESCE(AVG(f.discount_rate), 0),
               COALESCE(AVG(f.rating), 0),
               CAST(COALESCE(SUM(f.review_count), 0) AS INTEGER),
               CAST(COALESCE(SUM(f.quantity_sold_snapshot), 0) AS INTEGER),
               ?
        FROM fact_product_snapshot f
        JOIN dim_date d ON d.date_key = f.date_key
        JOIN dim_product pr ON pr.product_key = f.product_key
        JOIN dim_platform p ON p.platform_key = f.platform_key
        GROUP BY d.date_key, d.full_date, d.year_number, d.quarter_number,
                 d.month_number, p.platform_key, p.platform_name,
                 pr.category_name
    """,
}


TIME_ROLLUPS = (
    {
        "level": "DAY",
        "key": "printf('%08d', d.date_key)",
        "label": "d.full_date",
        "date_key": "d.date_key",
        "year": "d.year_number",
        "quarter": "d.quarter_number",
        "month": "d.month_number",
        "group_by": [
            "d.date_key",
            "d.full_date",
            "d.year_number",
            "d.quarter_number",
            "d.month_number",
        ],
    },
    {
        "level": "MONTH",
        "key": "printf('%04d-%02d', d.year_number, d.month_number)",
        "label": "printf('%04d-%02d', d.year_number, d.month_number)",
        "date_key": "NULL",
        "year": "d.year_number",
        "quarter": "d.quarter_number",
        "month": "d.month_number",
        "group_by": ["d.year_number", "d.quarter_number", "d.month_number"],
    },
    {
        "level": "QUARTER",
        "key": "printf('%04d-Q%d', d.year_number, d.quarter_number)",
        "label": "printf('%04d Q%d', d.year_number, d.quarter_number)",
        "date_key": "NULL",
        "year": "d.year_number",
        "quarter": "d.quarter_number",
        "month": "NULL",
        "group_by": ["d.year_number", "d.quarter_number"],
    },
    {
        "level": "YEAR",
        "key": "CAST(d.year_number AS TEXT)",
        "label": "CAST(d.year_number AS TEXT)",
        "date_key": "NULL",
        "year": "d.year_number",
        "quarter": "NULL",
        "month": "NULL",
        "group_by": ["d.year_number"],
    },
    {
        "level": "ALL",
        "key": "'ALL'",
        "label": "'All time'",
        "date_key": "NULL",
        "year": "NULL",
        "quarter": "NULL",
        "month": "NULL",
        "group_by": [],
    },
)


def _refresh_sales_cube(connection, refreshed_at: str) -> int:
    """Build all time roll-ups and all 2^4 course-aligned grouping sets."""
    connection.execute("DELETE FROM cube_sales")
    for time_rollup in TIME_ROLLUPS:
        for grouping_mask in range(16):
            platform_all = bool(grouping_mask & 1)
            category_all = bool(grouping_mask & 2)
            customer_all = bool(grouping_mask & 4)
            location_all = bool(grouping_mask & 8)

            platform_expr = "'ALL'" if platform_all else "p.platform_name"
            category_expr = "'ALL'" if category_all else "pr.category_name"
            customer_expr = (
                "'ALL'"
                if customer_all
                else "c.full_name || ' · ' || c.email"
            )
            location_expr = (
                "'ALL'"
                if location_all
                else "COALESCE(NULLIF(TRIM(c.city), ''), 'Unknown')"
            )

            group_by = list(time_rollup["group_by"])
            if not platform_all:
                group_by.append("p.platform_name")
            if not category_all:
                group_by.append("pr.category_name")
            if not customer_all:
                group_by.extend(("c.full_name", "c.email"))
            if not location_all:
                group_by.append("COALESCE(NULLIF(TRIM(c.city), ''), 'Unknown')")
            group_clause = " GROUP BY " + ", ".join(group_by) if group_by else ""

            connection.execute(
                f"""
                INSERT INTO cube_sales(
                    time_level, time_key, time_label, date_key, year_number,
                    quarter_number, month_number, platform_name, category_name,
                    customer_name, customer_city, grouping_mask, order_count, customer_count,
                    line_count, quantity_sold, gross_revenue, discount_amount,
                    net_revenue, average_selling_price, refreshed_at
                )
                SELECT '{time_rollup['level']}', {time_rollup['key']},
                       {time_rollup['label']}, {time_rollup['date_key']},
                       {time_rollup['year']}, {time_rollup['quarter']},
                       {time_rollup['month']}, {platform_expr}, {category_expr},
                       {customer_expr}, {location_expr}, {grouping_mask},
                       COUNT(DISTINCT f.order_number),
                       COUNT(DISTINCT f.customer_key),
                       COUNT(*),
                       COALESCE(SUM(f.quantity), 0),
                       COALESCE(SUM(f.gross_amount), 0),
                       COALESCE(SUM(f.discount_amount), 0),
                       COALESCE(SUM(f.net_amount), 0),
                       COALESCE(SUM(f.net_amount) /
                                NULLIF(SUM(f.quantity), 0), 0),
                       ?
                FROM fact_sales f
                JOIN dim_date d ON d.date_key = f.date_key
                JOIN dim_product pr ON pr.product_key = f.product_key
                JOIN dim_platform p ON p.platform_key = f.platform_key
                JOIN dim_customer c ON c.customer_key = f.customer_key
                {group_clause}
                """,
                (refreshed_at,),
            )
    return connection.execute("SELECT COUNT(*) AS n FROM cube_sales").fetchone()["n"]


def refresh_olap(source_etl_run_id: str | None = None) -> dict:
    """Complete-refresh all physical MVs and the Sales Cube."""
    _ensure_olap_schema()
    connection = get_db("dwh")
    refresh_id = "OLAP-" + uuid.uuid4().hex[:12].upper()
    started_at = _now()
    connection.execute(
        """
        INSERT INTO olap_refresh_run(
            refresh_id, source_etl_run_id, refresh_type, status, started_at
        ) VALUES (?, ?, 'COMPLETE', 'RUNNING', ?)
        """,
        (refresh_id, source_etl_run_id, started_at),
    )
    connection.commit()

    try:
        refreshed_at = _now()
        connection.execute("BEGIN IMMEDIATE")
        mv_counts: dict[str, int] = {}
        for table_name, statement in MV_REFRESH_SQL.items():
            connection.execute(f"DELETE FROM {table_name}")
            connection.execute(statement, (refreshed_at,))
            mv_counts[table_name] = connection.execute(
                f"SELECT COUNT(*) AS n FROM {table_name}"
            ).fetchone()["n"]

        cube_rows = _refresh_sales_cube(connection, refreshed_at)
        materialized_rows = sum(mv_counts.values())
        completed_at = _now()
        message = json.dumps(
            {
                "materialized_views": mv_counts,
                "cube": {
                    "table": "cube_sales",
                    "rows": cube_rows,
                    "time_levels": [rollup["level"] for rollup in TIME_ROLLUPS],
                    "grouping_sets_per_level": 16,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        connection.execute(
            """
            UPDATE olap_refresh_run
            SET status = 'SUCCESS', completed_at = ?, materialized_rows = ?,
                cube_rows = ?, message = ?
            WHERE refresh_id = ?
            """,
            (completed_at, materialized_rows, cube_rows, message, refresh_id),
        )
        connection.commit()
        return {
            "refresh_id": refresh_id,
            "status": "SUCCESS",
            "source_etl_run_id": source_etl_run_id,
            "materialized_views": mv_counts,
            "materialized_rows": materialized_rows,
            "cube_rows": cube_rows,
            "completed_at": completed_at,
        }
    except Exception as exc:
        connection.rollback()
        connection.execute(
            """
            UPDATE olap_refresh_run
            SET status = 'FAILED', completed_at = ?, message = ?
            WHERE refresh_id = ?
            """,
            (_now(), str(exc), refresh_id),
        )
        connection.commit()
        raise


def olap_status() -> dict:
    _ensure_olap_schema()
    connection = get_db("dwh")
    counts = {
        table_name: connection.execute(
            f"SELECT COUNT(*) AS n FROM {table_name}"
        ).fetchone()["n"]
        for table_name in OLAP_TABLES
    }
    latest = connection.execute(
        "SELECT * FROM olap_refresh_run ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return {
        "counts": counts,
        "materialized_rows": sum(counts[name] for name in MATERIALIZED_VIEWS),
        "cube_rows": counts["cube_sales"],
        "latest": latest,
    }


@click.command("refresh-olap")
@click.option("--source-etl-run", default=None, help="Optional ETL run identifier for lineage.")
def refresh_olap_command(source_etl_run: str | None) -> None:
    click.echo(
        json.dumps(
            refresh_olap(source_etl_run_id=source_etl_run),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def init_app(app) -> None:
    app.cli.add_command(refresh_olap_command)
