from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import click
from flask import current_app
from werkzeug.security import generate_password_hash

from app.db import close_db, execute_script, get_db, sqlserver_enabled, table_exists

from .analytics import ensure_olap_schema
from .raw_loader import product_code, stage_raw_products
from .snapshot_partitions import refresh_snapshot_months


DEMO_ACCOUNTS = (
    ("admin@quocdat.local", "Admin@123", "admin", "System Administrator", "0900000001", "Hanoi"),
    ("employee@quocdat.local", "Staff@123", "employee", "Procurement Staff", "0900000002", "Hanoi"),
    ("customer@quocdat.local", "Customer@123", "customer", "Demo Customer", "0900000003", "Hanoi"),
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _reset_files() -> None:
    if sqlserver_enabled():
        raise ValueError("Use empty SQL Server databases for a fresh initialization")
    close_db()
    for key in ("OLTP_DATABASE", "STAGING_DATABASE", "DWH_DATABASE"):
        path = Path(current_app.config[key]).resolve()
        instance_root = Path(current_app.config["INSTANCE_DIR"]).resolve()
        if instance_root not in path.parents:
            raise RuntimeError(f"Refusing to delete database outside instance directory: {path}")
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if candidate.exists():
                candidate.unlink()


def _seed_reference_data() -> None:
    db = get_db("oltp")
    db.executemany(
        "INSERT OR IGNORE INTO platforms(code, name) VALUES (?, ?)",
        [("LAZADA", "Lazada"), ("TIKI", "Tiki")],
    )
    db.executemany(
        "INSERT OR IGNORE INTO warehouses(warehouse_code, name, address) VALUES (?, ?, ?)",
        [
            ("WH-HN", "Hanoi Fulfillment Center", "Nam Tu Liem, Hanoi"),
            ("WH-HCM", "Ho Chi Minh City Fulfillment Center", "Thu Duc City, Ho Chi Minh City"),
        ],
    )
    db.executemany(
        """
        INSERT OR IGNORE INTO suppliers(
            supplier_code, name, contact_name, phone, email, address
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("SUP-001", "Sao Viet Distribution Co.", "Nguyen Minh Anh", "0911000001", "sale@saoviet.local", "Hanoi"),
            ("SUP-002", "An Phat Trading", "Tran Hoang Nam", "0911000002", "contact@anphat.local", "Bac Ninh"),
            ("SUP-003", "Southern Supply Co.", "Le Thu Trang", "0911000003", "hello@phuongnam.local", "Ho Chi Minh City"),
        ],
    )
    db.commit()


def _seed_users() -> None:
    db = get_db("oltp")
    for email, password, role, full_name, phone, city in DEMO_ACCOUNTS:
        db.execute(
            """
            INSERT OR IGNORE INTO users(email, password_hash, role, full_name, phone, address, city)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (email, generate_password_hash(password), role, full_name, phone, "Demo address", city),
        )
    customer = db.execute("SELECT id FROM users WHERE email = ?", ("customer@quocdat.local",)).fetchone()
    db.execute("INSERT OR IGNORE INTO carts(customer_id) VALUES (?)", (customer["id"],))
    db.commit()


def _seed_products(product_limit: int | None = None) -> int:
    staging = get_db("staging")
    oltp = get_db("oltp")
    query = """
        SELECT * FROM (
            SELECT s.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY natural_key ORDER BY snapshot_at DESC, id DESC
                   ) AS rn
            FROM stg_product_snapshot s
            WHERE dq_status != 'INVALID' AND is_duplicate = 0
        ) latest
        WHERE rn = 1
        ORDER BY source_system, natural_key
    """
    params: tuple = ()
    if product_limit:
        query += " LIMIT ?"
        params = (product_limit,)
    latest_rows = staging.execute(query, params).fetchall()

    platform_ids = {row["name"]: row["id"] for row in oltp.execute("SELECT id, name FROM platforms")}
    category_cache = {
        row["name"].casefold(): row["id"] for row in oltp.execute("SELECT id, name FROM categories")
    }
    warehouse_ids = [row["id"] for row in oltp.execute("SELECT id FROM warehouses ORDER BY id")]

    for row in latest_rows:
        category_name = row["category_name"] or "Uncategorized"
        category_id = category_cache.get(category_name.casefold())
        if not category_id:
            cursor = oltp.execute("INSERT INTO categories(name) VALUES (?)", (category_name,))
            category_id = cursor.lastrowid
            category_cache[category_name.casefold()] = category_id

        code = product_code(row["natural_key"], row["platform_product_id"])
        cursor = oltp.execute(
            """
            INSERT OR IGNORE INTO products(
                product_code, natural_key, platform_product_id, sku, platform_id,
                category_id, name, brand_name, origin, current_price, list_price,
                discount_rate, rating, review_count, sold_snapshot, image_url,
                source_snapshot_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                row["natural_key"],
                row["platform_product_id"],
                row["sku"],
                platform_ids[row["source_system"]],
                category_id,
                row["product_name"],
                row["brand_name"],
                row["origin"],
                row["sale_price"] or 0,
                row["list_price"],
                row["discount_rate"] or 0,
                row["rating"],
                row["review_count"] or 0,
                row["quantity_sold"] or 0,
                row["image_url"],
                row["snapshot_at"],
                row["snapshot_at"],
            ),
        )
        if cursor.rowcount == 0:
            product = oltp.execute(
                "SELECT id FROM products WHERE natural_key = ?", (row["natural_key"],)
            ).fetchone()
            product_id = product["id"]
        else:
            product_id = cursor.lastrowid

        digest = int(hashlib.sha256(row["natural_key"].encode()).hexdigest()[:8], 16)
        primary_qty = 12 + digest % 89
        average_cost = round((row["sale_price"] or 10_000) * (0.58 + (digest % 14) / 100), 2)
        oltp.execute(
            """
            INSERT OR IGNORE INTO inventory(
                product_id, warehouse_id, quantity_on_hand, reorder_level, average_cost
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (product_id, warehouse_ids[0], primary_qty, 10, average_cost),
        )
        if digest % 4 == 0:
            oltp.execute(
                """
                INSERT OR IGNORE INTO inventory(
                    product_id, warehouse_id, quantity_on_hand, reorder_level, average_cost
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (product_id, warehouse_ids[1], 5 + digest % 35, 8, average_cost),
            )

    oltp.commit()
    return len(latest_rows)


def _seed_demo_transactions() -> None:
    db = get_db("oltp")
    if db.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]:
        return
    customer = db.execute("SELECT id FROM users WHERE role = 'customer' ORDER BY id LIMIT 1").fetchone()
    employee = db.execute("SELECT id FROM users WHERE role = 'employee' ORDER BY id LIMIT 1").fetchone()
    supplier = db.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1").fetchone()
    warehouse = db.execute("SELECT id FROM warehouses ORDER BY id LIMIT 1").fetchone()
    products = db.execute(
        """
        SELECT p.id, p.current_price, i.average_cost
        FROM products p JOIN inventory i ON i.product_id = p.id
        WHERE i.warehouse_id = ? AND i.quantity_on_hand >= 5
        ORDER BY p.id LIMIT 3
        """,
        (warehouse["id"],),
    ).fetchall()
    if len(products) < 3:
        return

    now = _utcnow()
    subtotal = sum(products[index]["current_price"] * (index + 1) for index in range(2))
    order_cursor = db.execute(
        """
        INSERT INTO orders(
            order_number, customer_id, status, payment_status, shipping_address,
            shipping_city, subtotal, discount_total, shipping_fee, total_amount,
            created_at, paid_at
        ) VALUES (?, ?, 'confirmed', 'paid', ?, ?, ?, 0, 30000, ?, ?, ?)
        """,
        ("ORD-DEMO-001", customer["id"], "Demo address", "Hanoi", subtotal, subtotal + 30000, now, now),
    )
    for index, product in enumerate(products[:2]):
        quantity = index + 1
        line_total = product["current_price"] * quantity
        db.execute(
            """
            INSERT INTO order_items(
                order_id, product_id, warehouse_id, quantity, unit_price,
                discount_amount, line_total
            ) VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (order_cursor.lastrowid, product["id"], warehouse["id"], quantity, product["current_price"], line_total),
        )
        db.execute(
            """
            UPDATE inventory SET quantity_on_hand = quantity_on_hand - ?, updated_at = ?
            WHERE product_id = ? AND warehouse_id = ?
            """,
            (quantity, now, product["id"], warehouse["id"]),
        )
    db.execute(
        "INSERT INTO payments(order_id, method, status, amount, transaction_ref, paid_at) VALUES (?, 'demo_card', 'success', ?, ?, ?)",
        (order_cursor.lastrowid, subtotal + 30000, "PAY-DEMO-001", now),
    )
    db.execute(
        "INSERT INTO invoices(order_id, invoice_number, issued_at, total_amount) VALUES (?, ?, ?, ?)",
        (order_cursor.lastrowid, "INV-DEMO-001", now, subtotal + 30000),
    )

    receipt_cursor = db.execute(
        """
        INSERT INTO procurement_receipts(
            receipt_number, supplier_id, warehouse_id, employee_id, total_cost,
            notes, received_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "GRN-DEMO-001",
            supplier["id"],
            warehouse["id"],
            employee["id"],
            products[2]["average_cost"] * 25,
            "Sample goods receipt for the live demo",
            now,
        ),
    )
    db.execute(
        "INSERT INTO procurement_items(receipt_id, product_id, quantity, unit_cost, line_total) VALUES (?, ?, 25, ?, ?)",
        (receipt_cursor.lastrowid, products[2]["id"], products[2]["average_cost"], products[2]["average_cost"] * 25),
    )
    db.execute(
        """
        UPDATE inventory SET quantity_on_hand = quantity_on_hand + 25, updated_at = ?
        WHERE product_id = ? AND warehouse_id = ?
        """,
        (now, products[2]["id"], warehouse["id"]),
    )
    db.commit()


def initialize_system(reset: bool = False, product_limit: int | None = None, run_initial_etl: bool = True) -> dict:
    if reset:
        _reset_files()
    execute_script("oltp", "oltp_schema.sql")
    execute_script("staging", "staging_schema.sql")
    execute_script("dwh", "dwh_schema.sql")

    _seed_reference_data()
    _seed_users()
    install_oltp_features()

    staging = get_db("staging")
    if staging.execute("SELECT COUNT(*) AS n FROM stg_product_snapshot").fetchone()["n"] == 0:
        batch_id = "RAW-" + datetime.now().strftime("%Y%m%d%H%M%S")
        raw_stats = stage_raw_products(batch_id, replace=True)
        staging.execute(
            """
            INSERT OR REPLACE INTO etl_batch(
                batch_id, batch_type, status, source_started_at, completed_at,
                source_row_count, valid_row_count, warning_row_count,
                invalid_row_count, message
            ) VALUES (?, 'RAW_IMPORT', 'SUCCESS', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                _utcnow(),
                _utcnow(),
                raw_stats["source"],
                raw_stats["valid"],
                raw_stats["warning"],
                raw_stats["invalid"],
                json.dumps(raw_stats, ensure_ascii=False),
            ),
        )
        staging.commit()
    else:
        raw_stats = {"source": 0, "duplicate": 0}

    product_count = _seed_products(product_limit=product_limit)
    _seed_demo_transactions()

    etl_result = None
    if run_initial_etl:
        from .etl import run_etl

        etl_result = run_etl("full")

    return {"products": product_count, "raw": raw_stats, "etl": etl_result}


def install_oltp_features() -> None:
    if sqlserver_enabled():
        connection = get_db()
        if table_exists("oltp", "oltp_feature_migration") and connection.execute(
            "SELECT 1 FROM oltp_feature_migration WHERE name = 'sales_cdc_and_warehouse_scope'"
        ).fetchone():
            return
        execute_script("oltp", "oltp_features.sql")
        provision_sqlserver_demo_access()
    elif not table_exists("oltp", "oltp_feature_migration"):
        execute_script("oltp", "oltp_features.sql")


def provision_sqlserver_demo_access():
    connection = get_db()
    with connection:
        if not connection.in_transaction:
            connection.begin()
        if connection.execute(
            "SELECT 1 FROM oltp_feature_migration WHERE name = 'sales_cdc_and_warehouse_scope'"
        ).fetchone():
            return
        staff = connection.execute(
            "SELECT id FROM users WHERE email = 'employee@quocdat.local' AND role = 'employee'"
        ).fetchone()
        warehouse = connection.execute("SELECT id FROM warehouses WHERE warehouse_code = 'WH-HN'").fetchone()
        if staff and warehouse:
            connection.execute("INSERT OR IGNORE INTO employee_warehouse VALUES (?, ?)", (staff[0], warehouse[0]))
        connection.execute("INSERT INTO oltp_feature_migration VALUES ('sales_cdc_and_warehouse_scope')")


def upgrade_existing_system() -> None:
    install_oltp_features()
    if not table_exists("staging", "cdc_checkpoint"):
        execute_script("staging", "staging_schema.sql")
    if sqlserver_enabled():
        return
    if not table_exists("dwh", "snapshot_month"):
        ensure_olap_schema()
    connection = get_db("dwh")
    if connection.execute("SELECT 1 FROM snapshot_month WHERE dirty = 1 LIMIT 1").fetchone():
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            refresh_snapshot_months(connection)


def ensure_initialized() -> None:
    if not table_exists("oltp", "users"):
        if sqlserver_enabled():
            raise ValueError("Run migrate-sqlserver to set up the SQL Server databases")
        initialize_system()
    else:
        upgrade_existing_system()


@click.command("init-system")
@click.option("--reset", is_flag=True, help="Recreate all OLTP, staging and DWH databases.")
@click.option("--limit", type=int, default=None, help="Limit catalog size for development.")
def init_system_command(reset: bool, limit: int | None) -> None:
    result = initialize_system(reset=reset, product_limit=limit)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def init_app(app) -> None:
    app.cli.add_command(init_system_command)

    @app.before_request
    def upgrade_on_first_request():
        if not app.config.get("FEATURE_SCHEMA_READY") and table_exists("oltp", "users"):
            upgrade_existing_system()
            app.config["FEATURE_SCHEMA_READY"] = True
