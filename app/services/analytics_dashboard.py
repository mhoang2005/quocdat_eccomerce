from __future__ import annotations

from calendar import month_abbr
from math import ceil

from .snapshot_partitions import snapshot_source


def _integer(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _where(filters: dict, columns: dict[str, str]) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    for key, column in columns.items():
        value = filters.get(key)
        if value not in (None, ""):
            clauses.append(f"{column} = ?")
            params.append(value)
    return (" WHERE " + " AND ".join(clauses) if clauses else "", params)


def _options(connection) -> dict:
    years = [
        row["year_number"]
        for row in connection.execute(
            "SELECT DISTINCT year_number FROM dim_date ORDER BY year_number DESC"
        )
    ]
    months = [
        {"value": row["month_number"], "label": month_abbr[row["month_number"]]}
        for row in connection.execute(
            "SELECT DISTINCT month_number FROM dim_date ORDER BY month_number"
        )
    ]
    categories = [
        row["category_name"]
        for row in connection.execute(
            """
            SELECT DISTINCT category_name
            FROM dim_product
            WHERE is_current = 1
            ORDER BY category_name
            """
        )
    ]
    platforms = [
        row["platform_name"]
        for row in connection.execute(
            "SELECT platform_name FROM dim_platform ORDER BY platform_name"
        )
    ]
    warehouses = [
        row["warehouse_name"]
        for row in connection.execute(
            "SELECT warehouse_name FROM dim_warehouse ORDER BY warehouse_name"
        )
    ]
    return {
        "years": years,
        "months": months,
        "categories": categories,
        "platforms": platforms,
        "warehouses": warehouses,
    }


def _normalize_filters(options: dict, requested: dict) -> dict:
    year = _integer(requested.get("year"))
    if year not in options["years"]:
        year = options["years"][0] if options["years"] else None

    valid_months = {month["value"] for month in options["months"]}
    month = _integer(requested.get("month"))
    if month not in valid_months:
        month = None

    filters = {"year": year, "month": month}
    for key, option_key in (
        ("category", "categories"),
        ("platform", "platforms"),
        ("warehouse", "warehouses"),
    ):
        value = str(requested.get(key) or "").strip()
        filters[key] = value if value in options[option_key] else ""
    return filters


def _sales_metrics(connection, filters: dict) -> dict:
    where, params = _where(
        filters,
        {
            "year": "d.year_number",
            "month": "d.month_number",
            "category": "pr.category_name",
            "platform": "p.platform_name",
            "warehouse": "w.warehouse_name",
        },
    )
    row = connection.execute(
        """
        SELECT COUNT(DISTINCT f.order_number) AS order_count,
               COUNT(DISTINCT f.customer_key) AS customer_count,
               COALESCE(SUM(f.quantity), 0) AS quantity_sold,
               COALESCE(SUM(f.gross_amount), 0) AS gross_revenue,
               COALESCE(SUM(f.discount_amount), 0) AS discount_amount,
               COALESCE(SUM(f.net_amount), 0) AS net_revenue
        FROM fact_sales f
        JOIN dim_date d ON d.date_key = f.date_key
        JOIN dim_product pr ON pr.product_key = f.product_key
        JOIN dim_platform p ON p.platform_key = f.platform_key
        JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        """
        + where,
        params,
    ).fetchone()
    return dict(row)


def _procurement_metrics(connection, filters: dict) -> dict:
    where, params = _where(
        filters,
        {
            "year": "d.year_number",
            "month": "d.month_number",
            "category": "pr.category_name",
            "warehouse": "w.warehouse_name",
        },
    )
    row = connection.execute(
        """
        SELECT COUNT(DISTINCT f.receipt_number) AS receipt_count,
               COALESCE(SUM(f.quantity), 0) AS quantity_received,
               COALESCE(SUM(f.total_cost), 0) AS procurement_cost
        FROM fact_procurement f
        JOIN dim_date d ON d.date_key = f.date_key
        JOIN dim_product pr ON pr.product_key = f.product_key
        JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        """
        + where,
        params,
    ).fetchone()
    return dict(row)


def _inventory_metrics(connection, filters: dict) -> dict:
    where, params = _where(
        filters,
        {
            "year": "d.year_number",
            "month": "d.month_number",
            "category": "pr.category_name",
            "platform": "pr.platform_name",
            "warehouse": "w.warehouse_name",
        },
    )
    row = connection.execute(
        """
        WITH filtered AS (
            SELECT f.date_key, d.full_date, f.product_key,
                   f.quantity_on_hand, f.inventory_value
            FROM fact_inventory f
            JOIN dim_date d ON d.date_key = f.date_key
            JOIN dim_product pr ON pr.product_key = f.product_key
            JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        """
        + where
        + """
        ), latest AS (SELECT MAX(date_key) AS date_key FROM filtered)
        SELECT COALESCE(MAX(filtered.full_date), '') AS snapshot_date,
               COUNT(DISTINCT filtered.product_key) AS product_count,
               COALESCE(SUM(filtered.quantity_on_hand), 0) AS quantity_on_hand,
               COALESCE(SUM(filtered.inventory_value), 0) AS inventory_value
        FROM filtered
        JOIN latest ON latest.date_key = filtered.date_key
        """,
        params,
    ).fetchone()
    return dict(row)


def _marketplace_metrics(connection, filters: dict) -> dict:
    year, month = filters["year"], filters["month"]
    source = snapshot_source(connection, year, month)
    clauses, params = [], []
    if year is not None:
        first_day = year * 10000 + (month or 1) * 100 + 1
        end_day = first_day + 100 if month else (year + 1) * 10000 + 101
        clauses.append("f.date_key >= ? AND f.date_key < ?")
        params.extend((first_day, end_day))
    if filters["category"]:
        clauses.append("pr.category_name = ?")
        params.append(filters["category"])
    if filters["platform"]:
        clauses.append("f.platform_key IN (SELECT platform_key FROM dim_platform WHERE platform_name = ?)")
        params.append(filters["platform"])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    row = connection.execute(
        f"""
        WITH filtered AS (
            SELECT f.date_key, d.full_date, f.product_key, f.sale_price,
                   f.discount_rate, f.rating, f.review_count,
                   f.quantity_sold_snapshot
            FROM {source} f
            JOIN dim_date d ON d.date_key = f.date_key
            JOIN dim_product pr ON pr.product_key = f.product_key
        """
        + where
        + """
        ), latest AS (SELECT MAX(date_key) AS date_key FROM filtered)
        SELECT COALESCE(MAX(filtered.full_date), '') AS snapshot_date,
               COUNT(DISTINCT filtered.product_key) AS product_count,
               COALESCE(AVG(filtered.sale_price), 0) AS average_sale_price,
               COALESCE(AVG(filtered.discount_rate), 0) AS average_discount_rate,
               COALESCE(AVG(filtered.rating), 0) AS average_rating,
               CAST(COALESCE(SUM(filtered.review_count), 0) AS INTEGER) AS review_count,
               CAST(COALESCE(SUM(filtered.quantity_sold_snapshot), 0) AS INTEGER)
                   AS sold_quantity_snapshot
        FROM filtered
        JOIN latest ON latest.date_key = filtered.date_key
        """,
        params,
    ).fetchone()
    return dict(row)


def _trend(connection, filters: dict) -> list[dict]:
    sales_where, sales_params = _where(
        filters,
        {
            "year": "year_number",
            "month": "month_number",
            "category": "category_name",
            "platform": "platform_name",
            "warehouse": "warehouse_name",
        },
    )
    procurement_where, procurement_params = _where(
        filters,
        {
            "year": "year_number",
            "month": "month_number",
            "category": "category_name",
            "warehouse": "warehouse_name",
        },
    )
    sales = connection.execute(
        """
        SELECT date_key, full_date, COALESCE(SUM(net_revenue), 0) AS value
        FROM mv_sales_daily
        """
        + sales_where
        + " GROUP BY date_key, full_date ORDER BY date_key",
        sales_params,
    ).fetchall()
    procurement = connection.execute(
        """
        SELECT date_key, full_date, COALESCE(SUM(procurement_cost), 0) AS value
        FROM mv_procurement_daily
        """
        + procurement_where
        + " GROUP BY date_key, full_date ORDER BY date_key",
        procurement_params,
    ).fetchall()

    points: dict[int, dict] = {}
    for row in sales:
        points.setdefault(
            row["date_key"],
            {"date_key": row["date_key"], "label": row["full_date"]},
        )["sales"] = row["value"]
    for row in procurement:
        points.setdefault(
            row["date_key"],
            {"date_key": row["date_key"], "label": row["full_date"]},
        )["procurement"] = row["value"]

    result = sorted(points.values(), key=lambda point: point["date_key"])[-12:]
    maximum = max(
        [float(point.get("sales", 0)) for point in result]
        + [float(point.get("procurement", 0)) for point in result]
        + [1.0]
    )
    for point in result:
        point["sales"] = float(point.get("sales", 0))
        point["procurement"] = float(point.get("procurement", 0))
        point["sales_percent"] = round(point["sales"] / maximum * 100, 2)
        point["procurement_percent"] = round(
            point["procurement"] / maximum * 100, 2
        )
        point["short_label"] = point["label"][5:].replace("-", "/")
    return result


def _category_demand(connection, filters: dict) -> list[dict]:
    where, params = _where(
        filters,
        {
            "year": "year_number",
            "month": "month_number",
            "category": "category_name",
            "platform": "platform_name",
        },
    )
    rows = connection.execute(
        """
        SELECT category_name,
               SUM(sold_quantity_snapshot) AS demand,
               SUM(review_count_snapshot) AS reviews,
               COALESCE(
                   SUM(average_rating * snapshot_count) /
                   NULLIF(SUM(snapshot_count), 0), 0
               ) AS average_rating,
               COALESCE(
                   SUM(average_discount_rate * snapshot_count) /
                   NULLIF(SUM(snapshot_count), 0), 0
               ) AS average_discount_rate,
               COALESCE(
                   SUM(average_sale_price * snapshot_count) /
                   NULLIF(SUM(snapshot_count), 0), 0
               ) AS average_price
        FROM mv_marketplace_daily
        """
        + where
        + " GROUP BY category_name ORDER BY demand DESC LIMIT 7",
        params,
    ).fetchall()
    result = [dict(row) for row in rows]
    maximum = max([float(row["demand"] or 0) for row in result] + [1.0])
    for row in result:
        row["bar_percent"] = round(float(row["demand"] or 0) / maximum * 100, 2)
    return result


def _platform_benchmark(connection, filters: dict) -> list[dict]:
    marketplace_where, marketplace_params = _where(
        filters,
        {
            "year": "year_number",
            "month": "month_number",
            "category": "category_name",
            "platform": "platform_name",
        },
    )
    sales_where, sales_params = _where(
        filters,
        {
            "year": "year_number",
            "month": "month_number",
            "category": "category_name",
            "platform": "platform_name",
            "warehouse": "warehouse_name",
        },
    )
    marketplace_rows = connection.execute(
        """
        SELECT platform_name, SUM(snapshot_count) AS snapshot_count,
               SUM(sold_quantity_snapshot) AS observed_demand,
               COALESCE(
                   SUM(average_sale_price * snapshot_count) /
                   NULLIF(SUM(snapshot_count), 0), 0
               ) AS average_price,
               COALESCE(
                   SUM(average_rating * snapshot_count) /
                   NULLIF(SUM(snapshot_count), 0), 0
               ) AS average_rating,
               COALESCE(
                   SUM(average_discount_rate * snapshot_count) /
                   NULLIF(SUM(snapshot_count), 0), 0
               ) AS average_discount_rate
        FROM mv_marketplace_daily
        """
        + marketplace_where
        + " GROUP BY platform_name ORDER BY platform_name",
        marketplace_params,
    ).fetchall()
    sales_rows = connection.execute(
        """
        SELECT platform_name, COALESCE(SUM(net_revenue), 0) AS net_revenue,
               COALESCE(SUM(quantity_sold), 0) AS quantity_sold
        FROM mv_sales_daily
        """
        + sales_where
        + " GROUP BY platform_name",
        sales_params,
    ).fetchall()

    platforms = {row["platform_name"]: dict(row) for row in marketplace_rows}
    for row in sales_rows:
        platforms.setdefault(row["platform_name"], {"platform_name": row["platform_name"]})
        platforms[row["platform_name"]].update(dict(row))
    result = sorted(
        platforms.values(),
        key=lambda row: (-float(row.get("observed_demand", 0) or 0), row["platform_name"]),
    )
    maximum = max([float(row.get("observed_demand", 0) or 0) for row in result] + [1.0])
    for row in result:
        row.setdefault("snapshot_count", 0)
        row.setdefault("observed_demand", 0)
        row.setdefault("average_price", 0)
        row.setdefault("average_rating", 0)
        row.setdefault("average_discount_rate", 0)
        row.setdefault("net_revenue", 0)
        row.setdefault("quantity_sold", 0)
        row["bar_percent"] = round(float(row["observed_demand"] or 0) / maximum * 100, 2)
    return result


def _warehouse_health(connection, filters: dict) -> list[dict]:
    where, params = _where(
        filters,
        {
            "year": "d.year_number",
            "month": "d.month_number",
            "category": "pr.category_name",
            "platform": "pr.platform_name",
            "warehouse": "w.warehouse_name",
        },
    )
    rows = connection.execute(
        """
        WITH filtered AS (
            SELECT f.date_key, d.full_date, w.warehouse_name, f.product_key,
                   f.quantity_on_hand, f.inventory_value
            FROM fact_inventory f
            JOIN dim_date d ON d.date_key = f.date_key
            JOIN dim_product pr ON pr.product_key = f.product_key
            JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        """
        + where
        + """
        ), latest AS (SELECT MAX(date_key) AS date_key FROM filtered)
        SELECT MAX(filtered.full_date) AS snapshot_date, filtered.warehouse_name,
               COUNT(DISTINCT filtered.product_key) AS product_count,
               COALESCE(SUM(filtered.quantity_on_hand), 0) AS quantity_on_hand,
               COALESCE(SUM(filtered.inventory_value), 0) AS inventory_value,
               COALESCE(
                   SUM(filtered.inventory_value) /
                   NULLIF(SUM(filtered.quantity_on_hand), 0), 0
               ) AS average_unit_cost
        FROM filtered
        JOIN latest ON latest.date_key = filtered.date_key
        GROUP BY filtered.warehouse_name
        ORDER BY inventory_value DESC
        """,
        params,
    ).fetchall()
    result = [dict(row) for row in rows]
    maximum = max([float(row["inventory_value"] or 0) for row in result] + [1.0])
    for row in result:
        row["bar_percent"] = round(float(row["inventory_value"] or 0) / maximum * 100, 2)
    return result


def _drill_across(connection, filters: dict) -> list[dict]:
    columns = {
        "year": "d.year_number",
        "month": "d.month_number",
        "category": "pr.category_name",
        "warehouse": "w.warehouse_name",
    }
    sales_where, sales_params = _where(filters, columns)
    procurement_where, procurement_params = _where(filters, columns)
    inventory_where, inventory_params = _where(filters, columns)
    rows = connection.execute(
        """
        WITH sales AS (
            SELECT d.date_key, d.full_date, pr.category_name, w.warehouse_name,
                   COUNT(DISTINCT f.order_number) AS order_count,
                   SUM(f.quantity) AS quantity_sold,
                   SUM(f.net_amount) AS net_revenue
            FROM fact_sales f
            JOIN dim_date d ON d.date_key = f.date_key
            JOIN dim_product pr ON pr.product_key = f.product_key
            JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        """
        + sales_where
        + """
            GROUP BY d.date_key, d.full_date, pr.category_name, w.warehouse_name
        ), procurement AS (
            SELECT d.date_key, d.full_date, pr.category_name, w.warehouse_name,
                   COUNT(DISTINCT f.receipt_number) AS receipt_count,
                   SUM(f.quantity) AS quantity_received,
                   SUM(f.total_cost) AS procurement_cost
            FROM fact_procurement f
            JOIN dim_date d ON d.date_key = f.date_key
            JOIN dim_product pr ON pr.product_key = f.product_key
            JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        """
        + procurement_where
        + """
            GROUP BY d.date_key, d.full_date, pr.category_name, w.warehouse_name
        ), inventory AS (
            SELECT d.date_key, d.full_date, pr.category_name, w.warehouse_name,
                   COUNT(DISTINCT f.product_key) AS product_count,
                   SUM(f.quantity_on_hand) AS quantity_on_hand,
                   SUM(f.inventory_value) AS inventory_value
            FROM fact_inventory f
            JOIN dim_date d ON d.date_key = f.date_key
            JOIN dim_product pr ON pr.product_key = f.product_key
            JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
        """
        + inventory_where
        + """
            GROUP BY d.date_key, d.full_date, pr.category_name, w.warehouse_name
        ), grain AS (
            SELECT date_key, full_date, category_name, warehouse_name FROM sales
            UNION
            SELECT date_key, full_date, category_name, warehouse_name FROM procurement
            UNION
            SELECT date_key, full_date, category_name, warehouse_name FROM inventory
        )
        SELECT g.date_key, g.full_date, g.category_name, g.warehouse_name,
               COALESCE(s.order_count, 0) AS order_count,
               COALESCE(s.quantity_sold, 0) AS quantity_sold,
               COALESCE(s.net_revenue, 0) AS net_revenue,
               COALESCE(p.receipt_count, 0) AS receipt_count,
               COALESCE(p.quantity_received, 0) AS quantity_received,
               COALESCE(p.procurement_cost, 0) AS procurement_cost,
               COALESCE(i.product_count, 0) AS product_count,
               COALESCE(i.quantity_on_hand, 0) AS quantity_on_hand,
               COALESCE(i.inventory_value, 0) AS inventory_value
        FROM grain g
        LEFT JOIN sales s ON s.date_key = g.date_key AND s.full_date = g.full_date
            AND s.category_name = g.category_name AND s.warehouse_name = g.warehouse_name
        LEFT JOIN procurement p ON p.date_key = g.date_key AND p.full_date = g.full_date
            AND p.category_name = g.category_name AND p.warehouse_name = g.warehouse_name
        LEFT JOIN inventory i ON i.date_key = g.date_key AND i.full_date = g.full_date
            AND i.category_name = g.category_name AND i.warehouse_name = g.warehouse_name
        ORDER BY g.date_key DESC,
                 (COALESCE(s.quantity_sold, 0) +
                  COALESCE(p.quantity_received, 0)) DESC,
                 COALESCE(i.inventory_value, 0) DESC,
                 g.category_name, g.warehouse_name
        """,
        sales_params + procurement_params + inventory_params,
    ).fetchall()

    result: list[dict] = []
    for source in rows:
        row = dict(source)
        has_sales = bool(row["order_count"] or row["quantity_sold"])
        has_procurement = bool(row["receipt_count"] or row["quantity_received"])
        has_inventory = bool(row["product_count"] or row["quantity_on_hand"])
        row["process_count"] = sum((has_sales, has_procurement, has_inventory))
        row["coverage_ratio"] = (
            row["quantity_on_hand"] / row["quantity_sold"]
            if row["quantity_sold"]
            else None
        )
        if row["process_count"] == 3:
            row["signal"] = "All 3 facts"
            row["signal_class"] = "complete"
        elif has_sales and has_inventory:
            row["signal"] = "Demand + stock"
            row["signal_class"] = "active"
        elif has_procurement and has_inventory:
            row["signal"] = "Restock + stock"
            row["signal_class"] = "restock"
        elif has_sales:
            row["signal"] = "Demand only"
            row["signal_class"] = "active"
        elif has_procurement:
            row["signal"] = "Restock only"
            row["signal_class"] = "restock"
        else:
            row["signal"] = "Inventory only"
            row["signal_class"] = "inventory"
        result.append(row)
    return result


def build_analytics_dashboard(connection, requested: dict) -> dict:
    options = _options(connection)
    filters = _normalize_filters(options, requested)
    page = max(_integer(requested.get("page"), 1) or 1, 1)

    sales = _sales_metrics(connection, filters)
    procurement = _procurement_metrics(connection, filters)
    inventory = _inventory_metrics(connection, filters)
    marketplace = _marketplace_metrics(connection, filters)
    drill_rows = _drill_across(connection, filters)

    page_size = 24
    total_rows = len(drill_rows)
    pages = max(ceil(total_rows / page_size), 1)
    page = min(page, pages)
    start = (page - 1) * page_size
    paged_rows = drill_rows[start : start + page_size]

    latest_refresh = connection.execute(
        """
        SELECT * FROM olap_refresh_run
        WHERE status = 'SUCCESS'
        ORDER BY started_at DESC LIMIT 1
        """
    ).fetchone()
    active_filter_count = sum(
        1
        for key in ("month", "category", "platform", "warehouse")
        if filters.get(key) not in (None, "")
    )

    return {
        "options": options,
        "filters": filters,
        "active_filter_count": active_filter_count,
        "sales": sales,
        "procurement": procurement,
        "inventory": inventory,
        "marketplace": marketplace,
        "trend": _trend(connection, filters),
        "category_demand": _category_demand(connection, filters),
        "platform_benchmark": _platform_benchmark(connection, filters),
        "warehouse_health": _warehouse_health(connection, filters),
        "drill_rows": paged_rows,
        "drill_summary": {
            "aligned_cells": total_rows,
            "multi_process_cells": sum(
                1 for row in drill_rows if row["process_count"] >= 2
            ),
            "all_three_cells": sum(
                1 for row in drill_rows if row["process_count"] == 3
            ),
        },
        "page": page,
        "pages": pages,
        "page_size": page_size,
        "latest_refresh": latest_refresh,
    }
