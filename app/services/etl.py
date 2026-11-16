from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

import click
from flask import current_app

from app.db import execute_script, get_db
from app.services.analytics import ensure_olap_schema, refresh_olap
from app.services.bootstrap import install_oltp_features
from app.services.sales_cdc import ensure_sales_fact_order_key, remove_stale_sales, stage_sales


FAR_FUTURE = "9999-12-31T23:59:59"


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _date_key(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.year * 10000 + parsed.month * 100 + parsed.day


def _hash_attributes(*values) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_date(connection, value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    key = parsed.year * 10000 + parsed.month * 100 + parsed.day
    connection.execute(
        """
        INSERT OR IGNORE INTO dim_date(
            date_key, full_date, day_of_month, day_name, week_of_year,
            month_number, month_name, quarter_number, year_number, is_weekend
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            key,
            parsed.date().isoformat(),
            parsed.day,
            parsed.strftime("%A"),
            int(parsed.strftime("%W")) + 1,
            parsed.month,
            parsed.strftime("%B"),
            (parsed.month - 1) // 3 + 1,
            parsed.year,
            1 if parsed.weekday() >= 5 else 0,
        ),
    )
    return key


def _stage_oltp(batch_id: str, snapshot_at: str, full: bool):
    oltp = get_db("oltp")
    staging = get_db("staging")
    for table in (
        "stg_customer",
        "stg_procurement_line",
        "stg_inventory_snapshot",
    ):
        staging.execute(f"DELETE FROM {table}")

    customers = oltp.execute(
        """
        SELECT id, email, full_name, phone, city, address, is_active, updated_at
        FROM users WHERE role = 'customer'
        """
    ).fetchall()
    staging.executemany(
        """
        INSERT INTO stg_customer(
            customer_id, email, full_name, phone, city, address,
            is_active, source_updated_at, batch_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [tuple(row) + (batch_id,) for row in customers],
    )

    sales_cdc, changed_orders = stage_sales(oltp, staging, batch_id, full)
    sales = sales_cdc["staged"]

    procurement = oltp.execute(
        """
        SELECT pi.id, pr.id, pr.receipt_number, pr.received_at,
               pr.supplier_id, pr.warehouse_id, pi.product_id, p.natural_key,
               pi.quantity, pi.unit_cost, pi.line_total
        FROM procurement_items pi
        JOIN procurement_receipts pr ON pr.id = pi.receipt_id
        JOIN products p ON p.id = pi.product_id
        WHERE pr.status = 'received'
        """
    ).fetchall()
    staging.executemany(
        """
        INSERT INTO stg_procurement_line(
            source_procurement_item_id, source_receipt_id, receipt_number,
            received_at, supplier_id, warehouse_id, product_id, product_nk,
            quantity, unit_cost, total_cost, batch_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [tuple(row) + (batch_id,) for row in procurement],
    )

    inventory = oltp.execute(
        """
        SELECT i.product_id, p.natural_key, i.warehouse_id, i.quantity_on_hand,
               i.average_cost, i.quantity_on_hand * i.average_cost AS inventory_value
        FROM inventory i JOIN products p ON p.id = i.product_id
        """
    ).fetchall()
    staging.executemany(
        """
        INSERT INTO stg_inventory_snapshot(
            product_id, product_nk, warehouse_id, snapshot_at, quantity_on_hand,
            average_cost, inventory_value, batch_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["product_id"],
                row["natural_key"],
                row["warehouse_id"],
                snapshot_at,
                row["quantity_on_hand"],
                row["average_cost"],
                row["inventory_value"],
                batch_id,
            )
            for row in inventory
        ],
    )

    products = oltp.execute(
        """
        SELECT p.*, c.name AS category_name, pl.name AS platform_name
        FROM products p
        JOIN categories c ON c.id = p.category_id
        JOIN platforms pl ON pl.id = p.platform_id
        """
    ).fetchall()
    staged_hashes = {
        row[0] for row in staging.execute(
            "SELECT record_hash FROM stg_product_snapshot WHERE source_system = 'OLTP'"
        )
    }
    product_snapshots = 0
    for row in products:
        payload = dict(row)
        record_hash = _hash_attributes(
            row["natural_key"],
            row["name"],
            row["category_name"],
            row["platform_name"],
            row["brand_name"],
            row["origin"],
            row["is_active"],
            row["updated_at"],
        )
        if record_hash in staged_hashes:
            continue
        staging.execute(
            """
            INSERT INTO stg_product_snapshot(
                batch_id, source_system, source_file, source_row_number,
                natural_key, platform_product_id, sku, snapshot_at, product_name,
                category_name, category_l1, brand_name, origin, list_price,
                sale_price, discount_rate, quantity_sold, rating, review_count,
                image_url, is_duplicate, dq_status, record_hash, raw_payload
            ) VALUES (?, 'OLTP', 'oltp.products', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'VALID', ?, ?)
            """,
            (
                batch_id,
                row["id"],
                row["natural_key"],
                row["platform_product_id"],
                row["sku"],
                row["updated_at"] or snapshot_at,
                row["name"],
                row["category_name"],
                row["category_name"],
                row["brand_name"],
                row["origin"],
                row["list_price"],
                row["current_price"],
                row["discount_rate"],
                row["sold_snapshot"],
                row["rating"],
                row["review_count"],
                row["image_url"],
                record_hash,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        staged_hashes.add(record_hash)
        product_snapshots += 1

    total_rows = len(customers) + sales + len(procurement) + len(inventory) + product_snapshots
    counts = {
        "customers": len(customers),
        "sales": sales,
        "procurement": len(procurement),
        "inventory": len(inventory),
        "product_snapshots": product_snapshots,
        "total": total_rows,
        "sales_cdc": sales_cdc,
    }
    staging.execute(
        """
        INSERT OR REPLACE INTO etl_batch(
            batch_id, batch_type, status, source_started_at, completed_at,
            source_row_count, valid_row_count, warning_row_count,
            invalid_row_count, message
        ) VALUES (?, ?, 'SUCCESS', ?, ?, ?, ?, 0, 0, ?)
        """,
        (
            batch_id,
            "OLTP_FULL" if full else "OLTP_INCREMENTAL",
            snapshot_at,
            _now(),
            total_rows,
            total_rows,
            json.dumps(counts),
        ),
    )
    return counts, changed_orders


def _clear_dwh(run_id: str) -> None:
    connection = get_db("dwh")
    for table in (
        "cube_sales",
        "mv_sales_daily",
        "mv_procurement_daily",
        "mv_inventory_daily",
        "mv_marketplace_daily",
        "olap_refresh_run",
        "fact_sales",
        "fact_procurement",
        "fact_inventory",
        "fact_product_snapshot",
        "dim_customer",
        "dim_supplier",
        "dim_warehouse",
        "dim_platform",
        "dim_product",
        "dim_date",
    ):
        connection.execute(f"DELETE FROM {table}")
    connection.execute("DELETE FROM sqlite_sequence")
    connection.execute("DELETE FROM etl_run WHERE run_id != ?", (run_id,))


def _load_static_dimensions() -> int:
    oltp = get_db("oltp")
    staging = get_db("staging")
    dwh = get_db("dwh")
    affected = 0

    for row in oltp.execute("SELECT * FROM platforms"):
        dwh.execute(
            """
            INSERT INTO dim_platform(platform_nk, platform_code, platform_name, is_active)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(platform_nk) DO UPDATE SET
                platform_code = excluded.platform_code,
                platform_name = excluded.platform_name,
                is_active = excluded.is_active
            """,
            (row["id"], row["code"], row["name"], row["is_active"]),
        )
        affected += 1

    for row in oltp.execute("SELECT * FROM suppliers"):
        dwh.execute(
            """
            INSERT INTO dim_supplier(
                supplier_nk, supplier_code, supplier_name, contact_name,
                phone, email, address, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(supplier_nk) DO UPDATE SET
                supplier_code = excluded.supplier_code,
                supplier_name = excluded.supplier_name,
                contact_name = excluded.contact_name,
                phone = excluded.phone,
                email = excluded.email,
                address = excluded.address,
                is_active = excluded.is_active
            """,
            (
                row["id"],
                row["supplier_code"],
                row["name"],
                row["contact_name"],
                row["phone"],
                row["email"],
                row["address"],
                row["is_active"],
            ),
        )
        affected += 1

    for row in oltp.execute("SELECT * FROM warehouses"):
        dwh.execute(
            """
            INSERT INTO dim_warehouse(
                warehouse_nk, warehouse_code, warehouse_name, address, is_active
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(warehouse_nk) DO UPDATE SET
                warehouse_code = excluded.warehouse_code,
                warehouse_name = excluded.warehouse_name,
                address = excluded.address,
                is_active = excluded.is_active
            """,
            (row["id"], row["warehouse_code"], row["name"], row["address"], row["is_active"]),
        )
        affected += 1

    for row in staging.execute("SELECT * FROM stg_customer"):
        dwh.execute(
            """
            INSERT INTO dim_customer(
                customer_nk, email, full_name, phone, city, address,
                is_active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(customer_nk) DO UPDATE SET
                email = excluded.email,
                full_name = excluded.full_name,
                phone = excluded.phone,
                city = excluded.city,
                address = excluded.address,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (
                row["customer_id"],
                row["email"],
                row["full_name"],
                row["phone"],
                row["city"],
                row["address"],
                row["is_active"],
                row["source_updated_at"],
            ),
        )
        affected += 1

    return affected


def _load_product_dimension() -> int:
    oltp = get_db("oltp")
    staging = get_db("staging")
    dwh = get_db("dwh")
    product_master = {
        row["natural_key"]: row
        for row in oltp.execute("SELECT id, natural_key, product_code, is_active FROM products")
    }
    current = {
        row["product_nk"]: dict(row)
        for row in dwh.execute("SELECT * FROM dim_product WHERE is_current = 1")
    }
    staged_rows = staging.execute(
        """
        SELECT * FROM stg_product_snapshot
        WHERE dq_status != 'INVALID' AND is_duplicate = 0
        ORDER BY snapshot_at, id
        """
    ).fetchall()
    affected = 0
    for row in staged_rows:
        natural_key = row["natural_key"]
        master = product_master.get(natural_key)
        active = master["is_active"] if master else 1
        product_name = row["product_name"] or "Unknown"
        category_name = row["category_name"] or "Uncategorized"
        platform_name = "Lazada" if row["source_system"] == "Lazada" else "Tiki" if row["source_system"] == "Tiki" else None
        if platform_name is None and master:
            platform_name = oltp.execute(
                """
                SELECT pl.name FROM products p JOIN platforms pl ON pl.id = p.platform_id
                WHERE p.id = ?
                """,
                (master["id"],),
            ).fetchone()["name"]
        platform_name = platform_name or "Unknown"
        attr_hash = _hash_attributes(
            product_name,
            category_name,
            platform_name,
            row["brand_name"],
            row["origin"],
            active,
        )
        effective_at = row["snapshot_at"]
        existing = current.get(natural_key)
        if existing and effective_at <= existing["valid_from"]:
            continue
        if existing and existing["attribute_hash"] == attr_hash:
            continue
        if existing:
            dwh.execute(
                "UPDATE dim_product SET valid_to = ?, is_current = 0 WHERE product_key = ?",
                (effective_at, existing["product_key"]),
            )
        cursor = dwh.execute(
            """
            INSERT INTO dim_product(
                product_nk, source_product_id, product_code, product_name,
                category_name, platform_name, brand_name, origin, is_active,
                valid_from, valid_to, is_current, attribute_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                natural_key,
                master["id"] if master else None,
                master["product_code"] if master else None,
                product_name,
                category_name,
                platform_name,
                row["brand_name"],
                row["origin"],
                active,
                effective_at,
                FAR_FUTURE,
                attr_hash,
            ),
        )
        current[natural_key] = dict(
            product_key=cursor.lastrowid,
            product_nk=natural_key,
            valid_from=effective_at,
            valid_to=FAR_FUTURE,
            is_current=1,
            attribute_hash=attr_hash,
        )
        affected += 1
    return affected


def _product_versions() -> dict[str, list[dict]]:
    versions: dict[str, list[dict]] = defaultdict(list)
    for row in get_db("dwh").execute(
        "SELECT product_key, product_nk, valid_from, valid_to, is_current FROM dim_product ORDER BY product_nk, valid_from"
    ):
        versions[row["product_nk"]].append(dict(row))
    return versions


def _product_key_at(versions: dict[str, list[dict]], natural_key: str, timestamp: str) -> int | None:
    candidates = versions.get(natural_key, [])
    for version in reversed(candidates):
        if version["valid_from"] <= timestamp < version["valid_to"]:
            return version["product_key"]
    return candidates[-1]["product_key"] if candidates else None


def _load_facts(batch_id: str) -> int:
    staging = get_db("staging")
    dwh = get_db("dwh")
    versions = _product_versions()
    known_dates = {row[0] for row in dwh.execute("SELECT date_key FROM dim_date")}

    def date_key_for(value):
        key = _date_key(value)
        if key not in known_dates:
            _ensure_date(dwh, value)
            known_dates.add(key)
        return key

    platform_map = {
        row["platform_name"]: row["platform_key"] for row in dwh.execute("SELECT * FROM dim_platform")
    }
    customer_map = {
        row["customer_nk"]: row["customer_key"] for row in dwh.execute("SELECT * FROM dim_customer")
    }
    supplier_map = {
        row["supplier_nk"]: row["supplier_key"] for row in dwh.execute("SELECT * FROM dim_supplier")
    }
    warehouse_map = {
        row["warehouse_nk"]: row["warehouse_key"] for row in dwh.execute("SELECT * FROM dim_warehouse")
    }
    affected = 0
    loaded_snapshots = {
        tuple(row) for row in dwh.execute("SELECT source_record_hash, snapshot_at FROM fact_product_snapshot")
    }

    for row in staging.execute(
        """
        SELECT * FROM stg_product_snapshot
        WHERE dq_status != 'INVALID' AND is_duplicate = 0 AND source_system IN ('Lazada', 'Tiki')
        ORDER BY id
        """
    ):
        snapshot_identity = (row["record_hash"], row["snapshot_at"])
        if snapshot_identity in loaded_snapshots:
            continue
        product_key = _product_key_at(versions, row["natural_key"], row["snapshot_at"])
        platform_name = row["source_system"]
        if not product_key or platform_name not in platform_map:
            continue
        date_key = date_key_for(row["snapshot_at"])
        cursor = dwh.execute(
            """
            INSERT OR IGNORE INTO fact_product_snapshot(
                date_key, product_key, platform_key, source_record_hash,
                snapshot_at, list_price, sale_price, discount_amount,
                discount_rate, quantity_sold_snapshot, rating, review_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date_key,
                product_key,
                platform_map[platform_name],
                row["record_hash"],
                row["snapshot_at"],
                row["list_price"],
                row["sale_price"],
                row["discount_amount"],
                row["discount_rate"],
                row["quantity_sold"],
                row["rating"],
                row["review_count"],
            ),
        )
        loaded_snapshots.add(snapshot_identity)
        affected += max(cursor.rowcount, 0)

    for row in staging.execute("SELECT * FROM stg_sales_line WHERE batch_id = ?", (batch_id,)):
        product_key = _product_key_at(versions, row["product_nk"], row["order_at"])
        if not product_key:
            raise RuntimeError(f"Missing product dimension for sales line {row['source_order_item_id']}")
        date_key = date_key_for(row["order_at"])
        cursor = dwh.execute(
            """
            INSERT INTO fact_sales(
                date_key, product_key, customer_key, platform_key, warehouse_key,
                source_order_item_id, order_number, invoice_number, quantity,
                unit_price, discount_amount, gross_amount, net_amount, source_order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_order_item_id) DO UPDATE SET
                date_key = excluded.date_key,
                product_key = excluded.product_key,
                customer_key = excluded.customer_key,
                platform_key = excluded.platform_key,
                warehouse_key = excluded.warehouse_key,
                order_number = excluded.order_number,
                invoice_number = excluded.invoice_number,
                quantity = excluded.quantity,
                unit_price = excluded.unit_price,
                discount_amount = excluded.discount_amount,
                gross_amount = excluded.gross_amount,
                net_amount = excluded.net_amount,
                source_order_id = excluded.source_order_id,
                loaded_at = CURRENT_TIMESTAMP
            """,
            (
                date_key,
                product_key,
                customer_map[row["customer_id"]],
                platform_map[row["platform_name"]],
                warehouse_map[row["warehouse_id"]],
                row["source_order_item_id"],
                row["order_number"],
                row["invoice_number"],
                row["quantity"],
                row["unit_price"],
                row["discount_amount"],
                row["gross_amount"],
                row["net_amount"],
                row["source_order_id"],
            ),
        )
        affected += max(cursor.rowcount, 0)

    for row in staging.execute("SELECT * FROM stg_procurement_line"):
        product_key = _product_key_at(versions, row["product_nk"], row["received_at"])
        if not product_key:
            continue
        date_key = date_key_for(row["received_at"])
        cursor = dwh.execute(
            """
            INSERT OR IGNORE INTO fact_procurement(
                date_key, product_key, supplier_key, warehouse_key,
                source_procurement_item_id, receipt_number, quantity,
                unit_cost, total_cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date_key,
                product_key,
                supplier_map[row["supplier_id"]],
                warehouse_map[row["warehouse_id"]],
                row["source_procurement_item_id"],
                row["receipt_number"],
                row["quantity"],
                row["unit_cost"],
                row["total_cost"],
            ),
        )
        affected += max(cursor.rowcount, 0)

    for row in staging.execute("SELECT * FROM stg_inventory_snapshot"):
        product_key = _product_key_at(versions, row["product_nk"], row["snapshot_at"])
        if not product_key:
            continue
        date_key = date_key_for(row["snapshot_at"])
        dwh.execute(
            """
            INSERT INTO fact_inventory(
                date_key, product_key, warehouse_key, quantity_on_hand,
                average_cost, inventory_value, snapshot_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date_key, product_key, warehouse_key) DO UPDATE SET
                quantity_on_hand = excluded.quantity_on_hand,
                average_cost = excluded.average_cost,
                inventory_value = excluded.inventory_value,
                snapshot_at = excluded.snapshot_at,
                loaded_at = CURRENT_TIMESTAMP
            """,
            (
                date_key,
                product_key,
                warehouse_map[row["warehouse_id"]],
                row["quantity_on_hand"],
                row["average_cost"],
                row["inventory_value"],
                row["snapshot_at"],
            ),
        )
        affected += 1

    return affected


def run_etl(mode: str = "incremental") -> dict:
    if mode not in {"incremental", "full"}:
        raise ValueError("ETL mode must be incremental or full")
    install_oltp_features()
    execute_script("staging", "staging_schema.sql")
    ensure_olap_schema()
    staging = get_db("staging")
    oltp = get_db("oltp")
    dwh = get_db("dwh")
    run_id = "ETL-" + uuid.uuid4().hex[:12].upper()
    staging.execute("BEGIN IMMEDIATE")
    started_at = _now()
    try:
        dwh.execute(
            "INSERT INTO etl_run(run_id, mode, status, started_at) VALUES (?, ?, 'RUNNING', ?)",
            (run_id, mode, started_at),
        )
        dwh.commit()
        dwh.execute("BEGIN IMMEDIATE")
        ensure_sales_fact_order_key(dwh)
        if mode == "full":
            _clear_dwh(run_id)
        oltp.execute("BEGIN")
        try:
            staged, changed_orders = _stage_oltp(run_id, started_at, mode == "full")
            dimension_rows = _load_static_dimensions() + _load_product_dimension()
        finally:
            oltp.rollback()
        sales_cdc = staged["sales_cdc"]
        sales_cdc["removed_facts"] = remove_stale_sales(
            dwh, staging, run_id, sales_cdc["mode"] == "baseline", changed_orders
        )
        fact_rows = _load_facts(run_id)
        analytics = refresh_olap(source_etl_run_id=run_id, within_etl=True)
        snapshot_partitions_refreshed = analytics["snapshot_partitions_refreshed"]
        warning_rows = staging.execute(
            "SELECT COUNT(*) AS n FROM stg_product_snapshot WHERE dq_status = 'WARNING'"
        ).fetchone()["n"]
        completed_at = _now()
        message = json.dumps(
            {
                "staging": staged,
                "snapshot_partitions_refreshed": snapshot_partitions_refreshed,
                "olap": {
                    "refresh_id": analytics["refresh_id"],
                    "materialized_rows": analytics["materialized_rows"],
                    "cube_rows": analytics["cube_rows"],
                },
                "note": "Analytics Dashboard and three-Fact Drill-across are available.",
            },
            ensure_ascii=False,
        )
        dwh.execute(
            """
            UPDATE etl_run SET status = 'SUCCESS', completed_at = ?, staged_rows = ?,
                dimension_rows = ?, fact_rows = ?, warning_rows = ?, message = ?
            WHERE run_id = ?
            """,
            (completed_at, staged["total"], dimension_rows, fact_rows, warning_rows, message, run_id),
        )
        dwh.commit()
        staging.commit()
        return {
            "run_id": run_id,
            "status": "SUCCESS",
            "mode": mode,
            "staged_rows": staged["total"],
            "dimension_rows": dimension_rows,
            "fact_rows": fact_rows,
            "warning_rows": warning_rows,
            "sales_cdc": sales_cdc,
            "snapshot_partitions_refreshed": snapshot_partitions_refreshed,
            "olap": analytics,
        }
    except Exception as exc:
        staging.rollback()
        dwh.rollback()
        dwh.execute(
            "UPDATE etl_run SET status = 'FAILED', completed_at = ?, message = ? WHERE run_id = ?",
            (_now(), str(exc), run_id),
        )
        dwh.commit()
        raise


def warehouse_counts() -> dict:
    connection = get_db("dwh")
    tables = (
        "dim_date",
        "dim_product",
        "dim_customer",
        "dim_supplier",
        "dim_warehouse",
        "dim_platform",
        "fact_sales",
        "fact_procurement",
        "fact_inventory",
        "fact_product_snapshot",
    )
    return {
        table: connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in tables
    }


@click.command("run-etl")
@click.option("--mode", type=click.Choice(["incremental", "full"]), default="incremental")
def run_etl_command(mode: str) -> None:
    click.echo(json.dumps(run_etl(mode), ensure_ascii=False, indent=2))


def init_app(app) -> None:
    app.cli.add_command(run_etl_command)
