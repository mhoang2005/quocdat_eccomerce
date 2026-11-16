from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import DATABASE_ERRORS, get_db, sqlserver_enabled
from .security import mask_email, mask_phone, role_required
from .services.analytics import MATERIALIZED_VIEWS, olap_status, refresh_olap
from .services.analytics_dashboard import build_analytics_dashboard
from .services.etl import run_etl, warehouse_counts


bp = Blueprint("admin", __name__, url_prefix="/admin")


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


@bp.get("/")
@role_required("admin")
def dashboard():
    database = get_db()
    metrics = {
        "products": database.execute("SELECT COUNT(*) AS n FROM products WHERE is_active = 1").fetchone()["n"],
        "customers": database.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'customer' AND is_active = 1").fetchone()["n"],
        "orders": database.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"],
        "revenue": database.execute("SELECT COALESCE(SUM(total_amount), 0) AS n FROM orders WHERE payment_status = 'paid'").fetchone()["n"],
        "low_stock": database.execute("SELECT COUNT(*) AS n FROM inventory WHERE quantity_on_hand <= reorder_level").fetchone()["n"],
    }
    recent_orders = database.execute(
        """
        SELECT o.order_number, o.created_at, o.status, o.total_amount,
               u.full_name, inv.invoice_number
        FROM orders o JOIN users u ON u.id = o.customer_id
        JOIN invoices inv ON inv.order_id = o.id
        ORDER BY o.created_at DESC LIMIT 6
        """
    ).fetchall()
    recent_audit = database.execute(
        """
        SELECT a.*, u.full_name FROM audit_log a
        LEFT JOIN users u ON u.id = a.actor_user_id
        ORDER BY a.created_at DESC LIMIT 8
        """
    ).fetchall()
    return render_template(
        "admin/dashboard.html", metrics=metrics, recent_orders=recent_orders, recent_audit=recent_audit
    )


@bp.get("/analytics")
@role_required("admin")
def analytics_dashboard():
    database = get_db("dwh")
    database.execute("BEGIN")
    try:
        dashboard_data = build_analytics_dashboard(database, dict(request.args))
    finally:
        database.rollback()
    return render_template("admin/analytics.html", **dashboard_data)


@bp.get("/products")
@role_required("admin")
def products():
    database = get_db()
    query = request.args.get("q", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 30
    params: list = []
    where = ""
    if query:
        where = " WHERE LOWER(p.product_code) LIKE LOWER(?) OR LOWER(p.name) LIKE LOWER(?)"
        params = [f"%{query}%", f"%{query}%"]
    count = database.execute("SELECT COUNT(*) AS n FROM products p" + where, params).fetchone()["n"]
    rows = database.execute(
        """
        SELECT p.*, c.name AS category_name, pl.name AS platform_name,
               COALESCE(i.stock, 0) AS stock_quantity
        FROM products p JOIN categories c ON c.id = p.category_id
        JOIN platforms pl ON pl.id = p.platform_id
        LEFT JOIN (SELECT product_id, SUM(quantity_on_hand) AS stock FROM inventory GROUP BY product_id) i
          ON i.product_id = p.id
        """
        + where
        + " ORDER BY p.id DESC LIMIT ? OFFSET ?",
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return render_template(
        "admin/products.html",
        products=rows,
        query=query,
        page=page,
        pages=max((count + per_page - 1) // per_page, 1),
        total=count,
    )


@bp.route("/products/<int:product_id>/edit", methods=("GET", "POST"))
@role_required("admin")
def edit_product(product_id: int):
    database = get_db()
    product = database.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        abort(404)
    categories = database.execute("SELECT * FROM categories ORDER BY name").fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category_id = request.form.get("category_id", type=int)
        current_price = request.form.get("current_price", type=float)
        list_price = request.form.get("list_price", type=float)
        origin = request.form.get("origin", "").strip()
        brand_name = request.form.get("brand_name", "").strip()
        is_active = 1 if request.form.get("is_active") == "1" else 0
        category_ids = {row["id"] for row in categories}
        if len(name) < 2 or category_id not in category_ids or current_price is None or current_price < 0:
            flash("Invalid product information.", "error")
        else:
            now = _now()
            database.execute(
                """
                UPDATE products SET name = ?, category_id = ?, current_price = ?,
                    list_price = ?, origin = ?, brand_name = ?, is_active = ?,
                    updated_at = ? WHERE id = ?
                """,
                (name, category_id, current_price, list_price, origin, brand_name, is_active, now, product_id),
            )
            database.execute(
                """
                INSERT INTO audit_log(actor_user_id, action, entity_type, entity_id, details)
                VALUES (?, 'UPDATE', 'PRODUCT', ?, ?)
                """,
                (g.user["id"], product_id, "Product attributes updated; the next ETL run will process SCD Type 2"),
            )
            database.commit()
            flash("Product updated. Run ETL to create the new SCD Type 2 version.", "success")
            return redirect(url_for("admin.edit_product", product_id=product_id))
    inventory = database.execute(
        """
        SELECT i.*, w.name AS warehouse_name FROM inventory i
        JOIN warehouses w ON w.id = i.warehouse_id WHERE i.product_id = ?
        """,
        (product_id,),
    ).fetchall()
    return render_template(
        "admin/edit_product.html", product=product, categories=categories, inventory=inventory
    )


@bp.get("/users")
@role_required("admin")
def users():
    role = request.args.get("role", "")
    database = get_db()
    statement = "SELECT id, full_name, email, role, phone, city, created_at, is_active FROM users"
    if role in {"customer", "employee", "admin"}:
        rows = database.execute(statement + " WHERE role = ? ORDER BY created_at DESC", (role,))
    else:
        rows = database.execute(statement + " ORDER BY role, created_at DESC")
    accounts = []
    for row in rows:
        account = dict(row)
        if account["id"] != g.user["id"]:
            account["email"] = mask_email(account["email"])
            account["phone"] = mask_phone(account["phone"])
        accounts.append(account)
    return render_template("admin/users.html", users=accounts, selected_role=role)


@bp.post("/users/<int:user_id>/toggle")
@role_required("admin")
def toggle_user(user_id: int):
    if user_id == g.user["id"]:
        flash("You cannot lock the account currently signed in.", "error")
        return redirect(url_for("admin.users"))
    database = get_db()
    target = database.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        abort(404)
    database.execute(
        "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
        (0 if target["is_active"] else 1, _now(), user_id),
    )
    database.execute(
        "INSERT INTO audit_log(actor_user_id, action, entity_type, entity_id, details) VALUES (?, 'TOGGLE_ACTIVE', 'USER', ?, ?)",
        (g.user["id"], user_id, f"is_active={0 if target['is_active'] else 1}"),
    )
    database.commit()
    flash("Account status updated.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/settings", methods=("GET", "POST"))
@role_required("admin")
def settings():
    database = get_db()
    if request.method == "POST":
        entity = request.form.get("entity")
        try:
            if entity == "supplier":
                code = request.form.get("code", "").strip().upper()
                name = request.form.get("name", "").strip()
                if not code or not name:
                    raise ValueError("Supplier code and name are required.")
                database.execute(
                    "INSERT INTO suppliers(supplier_code, name, contact_name, phone, email, address) VALUES (?, ?, ?, ?, ?, ?)",
                    (code, name, request.form.get("contact_name"), request.form.get("phone"), request.form.get("email"), request.form.get("address")),
                )
            elif entity == "warehouse":
                code = request.form.get("code", "").strip().upper()
                name = request.form.get("name", "").strip()
                address = request.form.get("address", "").strip()
                if not code or not name or not address:
                    raise ValueError("Warehouse code, name, and address are required.")
                database.execute(
                    "INSERT INTO warehouses(warehouse_code, name, address) VALUES (?, ?, ?)",
                    (code, name, address),
                )
            else:
                raise ValueError("Invalid configuration type.")
            database.commit()
        except (ValueError, *DATABASE_ERRORS) as exc:
            database.rollback()
            flash(str(exc), "error")
        else:
            flash("Operational reference data added.", "success")
            return redirect(url_for("admin.settings"))
    suppliers = database.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    warehouses = database.execute("SELECT * FROM warehouses ORDER BY name").fetchall()
    employees = database.execute(
        "SELECT id, full_name FROM users WHERE role = 'employee' ORDER BY full_name, id"
    ).fetchall()
    assignments = database.execute(
        """
        SELECT u.full_name, w.warehouse_code FROM employee_warehouse ew
        JOIN users u ON u.id = ew.employee_id JOIN warehouses w ON w.id = ew.warehouse_id
        WHERE u.role = 'employee' ORDER BY u.full_name, w.warehouse_code
        """
    ).fetchall()
    return render_template(
        "admin/settings.html", suppliers=suppliers, warehouses=warehouses,
        employees=employees, assignments=assignments,
    )


@bp.post("/settings/warehouse-access")
@role_required("admin")
def warehouse_access():
    employee_id = request.form.get("employee_id", type=int)
    warehouse_id = request.form.get("warehouse_id", type=int)
    action = request.form.get("action")
    if action not in {"grant", "revoke"}:
        abort(400)
    database = get_db()
    with database:
        database.execute("BEGIN IMMEDIATE")
        if not database.execute(
            "SELECT 1 FROM users WHERE id = ? AND role = 'employee'", (employee_id,)
        ).fetchone() or not database.execute(
            "SELECT 1 FROM warehouses WHERE id = ?", (warehouse_id,)
        ).fetchone():
            abort(400)
        if action == "grant":
            cursor = database.execute(
                "INSERT OR IGNORE INTO employee_warehouse VALUES (?, ?)", (employee_id, warehouse_id)
            )
        else:
            cursor = database.execute(
                "DELETE FROM employee_warehouse WHERE employee_id = ? AND warehouse_id = ?",
                (employee_id, warehouse_id),
            )
        if cursor.rowcount:
            database.execute(
                """
                INSERT INTO audit_log(actor_user_id, action, entity_type, entity_id, details)
                VALUES (?, ?, 'USER', ?, ?)
                """,
                (g.user["id"], f"{action.upper()}_WAREHOUSE_ACCESS", employee_id, f"warehouse_id={warehouse_id}"),
            )
    flash("Warehouse access saved.", "success")
    return redirect(url_for("admin.settings"))


@bp.get("/etl")
@role_required("admin")
def etl_status():
    staging = get_db("staging")
    dwh = get_db("dwh")
    counts = warehouse_counts()
    runs = []
    for row in dwh.execute("SELECT * FROM etl_run ORDER BY started_at DESC, rowid DESC LIMIT 20"):
        run = dict(row)
        run["sales_cdc"] = None
        if run["status"] == "SUCCESS" and run["message"]:
            try:
                run["sales_cdc"] = json.loads(run["message"]).get("staging", {}).get("sales_cdc")
            except (ValueError, AttributeError):
                pass
        runs.append(run)
    checkpoint = staging.execute("SELECT event_id FROM cdc_checkpoint WHERE stream = 'sales'").fetchone()
    pending_events = get_db().execute(
        "SELECT COUNT(*) FROM cdc_event WHERE event_id > ?", (checkpoint[0] if checkpoint else 0,)
    ).fetchone()[0]
    month_sql = (
        "SELECT COUNT(DISTINCT $PARTITION.pf_snapshot_month(date_key)) FROM fact_product_snapshot"
        if sqlserver_enabled() else "SELECT COUNT(*) FROM snapshot_month WHERE dirty = 0"
    )
    ready_months = dwh.execute(month_sql).fetchone()[0]
    dq = staging.execute(
        """
        SELECT dq_status, COUNT(*) AS row_count,
               SUM(CASE WHEN is_duplicate = 1 THEN 1 ELSE 0 END) AS duplicate_count
        FROM stg_product_snapshot GROUP BY dq_status ORDER BY dq_status
        """
    ).fetchall()
    batches = staging.execute(
        "SELECT * FROM etl_batch ORDER BY source_started_at DESC LIMIT 10"
    ).fetchall()
    return render_template(
        "admin/etl.html", counts=counts, runs=runs, dq=dq, batches=batches,
        checkpoint=checkpoint[0] if checkpoint else None, pending_events=pending_events,
        ready_months=ready_months,
    )


@bp.get("/olap")
@role_required("admin")
def olap():
    dwh = get_db("dwh")
    status = olap_status()

    time_hierarchy = ["DAY", "MONTH", "QUARTER", "YEAR", "ALL"]
    level = request.args.get("level", "DAY").upper()
    if level not in time_hierarchy:
        level = "DAY"
    hierarchy_index = time_hierarchy.index(level)
    drilldown_level = time_hierarchy[hierarchy_index - 1] if hierarchy_index > 0 else None
    rollup_level = (
        time_hierarchy[hierarchy_index + 1]
        if hierarchy_index < len(time_hierarchy) - 1
        else None
    )

    platform = request.args.get("platform", "ALL").strip()
    category = request.args.get("category", "").strip()
    city = request.args.get("city", "ALL").strip()
    pivot_mode = request.args.get("pivot", "product")
    pivot_configs = {
        "product": {
            "label": "Product × Time",
            "member_label": "Product category",
            "member_column": "category_name",
            "grouping_mask": 5,
        },
        "location": {
            "label": "Location × Time",
            "member_label": "Customer city",
            "member_column": "customer_city",
            "grouping_mask": 3,
        },
        "seller": {
            "label": "Store/Seller × Time",
            "member_label": "Seller channel",
            "member_column": "platform_name",
            "grouping_mask": 6,
        },
    }
    if pivot_mode not in pivot_configs:
        pivot_mode = "product"

    dimensions = {}
    for column, selected in (
        ("platform_name", platform),
        ("category_name", category),
        ("customer_city", city),
    ):
        members = [
            row["member"]
            for row in dwh.execute(
                f"SELECT DISTINCT {column} AS member FROM cube_sales "
                f"WHERE {column} != 'ALL' ORDER BY {column}"
            )
        ]
        dimensions[column] = {"members": members, "selected": selected}

    where = ["time_level = ?"]
    params: list = [level]
    for column, selected in (
        ("platform_name", platform),
        ("category_name", category),
        ("customer_city", city),
    ):
        if selected:
            where.append(f"{column} = ?")
            params.append(selected)
    cube_rows = dwh.execute(
        """
        SELECT * FROM cube_sales
        WHERE """
        + " AND ".join(where)
        + " ORDER BY time_key DESC, net_revenue DESC, category_name, customer_city LIMIT 100",
        params,
    ).fetchall()

    grand_total = dwh.execute(
        """
        SELECT * FROM cube_sales
        WHERE time_level = 'ALL' AND platform_name = 'ALL'
          AND category_name = 'ALL' AND customer_city = 'ALL'
        LIMIT 1
        """
    ).fetchone()

    pivot_config = pivot_configs[pivot_mode]
    pivot_source = dwh.execute(
        f"""
        SELECT time_key, time_label,
               {pivot_config['member_column']} AS member,
               net_revenue
        FROM cube_sales
        WHERE time_level = ? AND grouping_mask = ?
        ORDER BY time_key, member
        """,
        (level, pivot_config["grouping_mask"]),
    ).fetchall()
    time_members: dict[str, str] = {}
    for row in pivot_source:
        time_members[row["time_key"]] = row["time_label"]
    pivot_keys = list(time_members)[-12:]
    pivot_columns = [
        {"key": key, "label": time_members[key]} for key in pivot_keys
    ]
    pivot_values: dict[str, dict[str, float]] = {}
    for row in pivot_source:
        if row["time_key"] in pivot_keys:
            pivot_values.setdefault(row["member"], {})[row["time_key"]] = row[
                "net_revenue"
            ]
    pivot_rows = [
        {
            "member": member,
            "values": [values.get(key, 0) for key in pivot_keys],
            "total": sum(values.get(key, 0) for key in pivot_keys),
        }
        for member, values in pivot_values.items()
    ]
    pivot_rows.sort(key=lambda row: (-row["total"], row["member"]))

    refresh_runs = dwh.execute(
        "SELECT * FROM olap_refresh_run ORDER BY started_at DESC LIMIT 10"
    ).fetchall()
    materialized_views = [
        {
            "table": table_name,
            **metadata,
            "row_count": status["counts"][table_name],
        }
        for table_name, metadata in MATERIALIZED_VIEWS.items()
    ]
    return render_template(
        "admin/olap.html",
        status=status,
        materialized_views=materialized_views,
        cube_rows=cube_rows,
        grand_total=grand_total,
        refresh_runs=refresh_runs,
        dimensions=dimensions,
        selected_level=level,
        drilldown_level=drilldown_level,
        rollup_level=rollup_level,
        pivot_mode=pivot_mode,
        pivot_config=pivot_config,
        pivot_columns=pivot_columns,
        pivot_rows=pivot_rows,
    )


@bp.post("/olap/refresh")
@role_required("admin")
def refresh_olap_data():
    dwh = get_db("dwh")
    latest_etl = dwh.execute(
        "SELECT run_id FROM etl_run WHERE status = 'SUCCESS' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    try:
        result = refresh_olap(
            source_etl_run_id=latest_etl["run_id"] if latest_etl else None
        )
    except Exception as exc:
        flash(f"OLAP refresh failed: {exc}", "error")
    else:
        flash(
            f"OLAP refresh completed: {result['materialized_rows']:,} materialized rows "
            f"and {result['cube_rows']:,} cube rows.",
            "success",
        )
    return redirect(url_for("admin.olap"))


@bp.post("/etl/run")
@role_required("admin")
def execute_etl():
    mode = request.form.get("mode", "incremental")
    if mode not in {"incremental", "full"}:
        abort(400)
    try:
        result = run_etl(mode)
    except Exception as exc:
        flash(f"ETL failed: {exc}", "error")
    else:
        flash(
            f"ETL {mode} completed: {result['dimension_rows']} dimension rows, "
            f"{result['fact_rows']} fact rows, and {result['olap']['cube_rows']} cube rows processed.",
            "success",
        )
    return redirect(url_for("admin.etl_status"))
