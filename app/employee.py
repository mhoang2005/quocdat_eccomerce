from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import DATABASE_ERRORS, get_db
from .security import role_required


bp = Blueprint("employee", __name__, url_prefix="/employee")


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _warehouse_scope(column):
    if g.user["role"] == "admin":
        return "1 = 1", ()
    return (
        f"{column} IN (SELECT warehouse_id FROM employee_warehouse WHERE employee_id = ?)",
        (g.user["id"],),
    )


@bp.get("/")
@role_required("employee", "admin")
def dashboard():
    database = get_db()
    receipt_scope, params = _warehouse_scope("pr.warehouse_id")
    inventory_scope, _ = _warehouse_scope("i.warehouse_id")
    metrics = {
        "receipts": database.execute(
            f"SELECT COUNT(*) AS n FROM procurement_receipts pr WHERE {receipt_scope}", params
        ).fetchone()["n"],
        "units_received": database.execute(
            f"""SELECT COALESCE(SUM(pi.quantity), 0) AS n FROM procurement_items pi
                JOIN procurement_receipts pr ON pr.id = pi.receipt_id WHERE {receipt_scope}""",
            params,
        ).fetchone()["n"],
        "low_stock": database.execute(
            f"""SELECT COUNT(*) AS n FROM inventory i
                WHERE i.quantity_on_hand <= i.reorder_level AND {inventory_scope}""",
            params,
        ).fetchone()["n"],
        "suppliers": database.execute(
            "SELECT COUNT(*) AS n FROM suppliers WHERE is_active = 1"
        ).fetchone()["n"],
    }
    receipts = database.execute(
        f"""
        SELECT pr.*, s.name AS supplier_name, w.name AS warehouse_name,
               u.full_name AS employee_name, pi.line_count, pi.total_units
        FROM procurement_receipts pr
        JOIN suppliers s ON s.id = pr.supplier_id
        JOIN warehouses w ON w.id = pr.warehouse_id
        JOIN users u ON u.id = pr.employee_id
        JOIN (SELECT receipt_id, COUNT(*) AS line_count, SUM(quantity) AS total_units
              FROM procurement_items GROUP BY receipt_id) pi ON pi.receipt_id = pr.id
        WHERE {receipt_scope}
        ORDER BY pr.received_at DESC LIMIT 8
        """,
        params,
    ).fetchall()
    low_stock = database.execute(
        f"""
        SELECT p.product_code, p.name, i.quantity_on_hand, i.reorder_level,
               w.name AS warehouse_name
        FROM inventory i JOIN products p ON p.id = i.product_id
        JOIN warehouses w ON w.id = i.warehouse_id
        WHERE i.quantity_on_hand <= i.reorder_level AND {inventory_scope}
        ORDER BY i.quantity_on_hand ASC LIMIT 8
        """,
        params,
    ).fetchall()
    return render_template(
        "employee/dashboard.html", metrics=metrics, receipts=receipts, low_stock=low_stock
    )


@bp.get("/procurements")
@role_required("employee", "admin")
def procurements():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 20
    database = get_db()
    scope, params = _warehouse_scope("pr.warehouse_id")
    count = database.execute(
        f"SELECT COUNT(*) AS n FROM procurement_receipts pr WHERE {scope}", params
    ).fetchone()["n"]
    rows = database.execute(
        f"""
        SELECT pr.*, s.name AS supplier_name, w.name AS warehouse_name,
               u.full_name AS employee_name, pi.line_count, pi.total_units
        FROM procurement_receipts pr
        JOIN suppliers s ON s.id = pr.supplier_id
        JOIN warehouses w ON w.id = pr.warehouse_id
        JOIN users u ON u.id = pr.employee_id
        JOIN (SELECT receipt_id, COUNT(*) AS line_count, SUM(quantity) AS total_units
              FROM procurement_items GROUP BY receipt_id) pi ON pi.receipt_id = pr.id
        WHERE {scope}
        ORDER BY pr.received_at DESC LIMIT ? OFFSET ?
        """,
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return render_template(
        "employee/procurements.html",
        receipts=rows,
        page=page,
        pages=max((count + per_page - 1) // per_page, 1),
    )


@bp.route("/procurements/new", methods=("GET", "POST"))
@role_required("employee", "admin")
def new_procurement():
    database = get_db()
    suppliers = database.execute(
        "SELECT * FROM suppliers WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    scope, scope_params = _warehouse_scope("id")
    warehouses = database.execute(
        f"SELECT * FROM warehouses WHERE is_active = 1 AND {scope} ORDER BY name", scope_params
    ).fetchall()
    if request.method == "POST":
        supplier_id = request.form.get("supplier_id", type=int)
        warehouse_id = request.form.get("warehouse_id", type=int)
        notes = request.form.get("notes", "").strip()
        codes = request.form.getlist("product_code[]")
        quantities = request.form.getlist("quantity[]")
        costs = request.form.getlist("unit_cost[]")
        if warehouse_id is not None and not any(row["id"] == warehouse_id for row in warehouses):
            abort(403)
        error = None
        if not any(row["id"] == supplier_id for row in suppliers):
            error = "Invalid supplier."
        elif warehouse_id is None:
            error = "Invalid receiving warehouse."
        elif not codes:
            error = "A goods receipt requires at least one product."
        parsed_lines = []
        if not error:
            seen_products = set()
            for index, code in enumerate(codes):
                code = code.strip().upper()
                if not code:
                    continue
                product = database.execute(
                    "SELECT id, product_code, name FROM products WHERE product_code = ? AND is_active = 1",
                    (code,),
                ).fetchone()
                try:
                    quantity = int(quantities[index])
                    unit_cost = float(costs[index])
                except (ValueError, IndexError):
                    error = f"Invalid quantity or unit cost on line {index + 1}."
                    break
                if product is None:
                    error = f"Product code {code} was not found."
                    break
                if product["id"] in seen_products:
                    error = f"Product {code} appears more than once in this receipt."
                    break
                if quantity <= 0 or unit_cost < 0:
                    error = f"Quantity and unit cost must be valid on line {index + 1}."
                    break
                seen_products.add(product["id"])
                parsed_lines.append((product, quantity, unit_cost, quantity * unit_cost))
            if not parsed_lines and not error:
                error = "A goods receipt requires at least one valid line."
        if error:
            flash(error, "error")
        else:
            now = _now()
            receipt_number = "GRN-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8].upper()
            total_cost = sum(line[3] for line in parsed_lines)
            try:
                database.execute("BEGIN IMMEDIATE")
                if not database.execute(
                    f"SELECT 1 FROM warehouses WHERE id = ? AND is_active = 1 AND {scope}",
                    (warehouse_id, *scope_params),
                ).fetchone():
                    database.rollback()
                    abort(403)
                cursor = database.execute(
                    """
                    INSERT INTO procurement_receipts(
                        receipt_number, supplier_id, warehouse_id, employee_id,
                        total_cost, notes, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (receipt_number, supplier_id, warehouse_id, g.user["id"], total_cost, notes, now),
                )
                receipt_id = cursor.lastrowid
                for product, quantity, unit_cost, line_total in parsed_lines:
                    database.execute(
                        """
                        INSERT INTO procurement_items(
                            receipt_id, product_id, quantity, unit_cost, line_total
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (receipt_id, product["id"], quantity, unit_cost, line_total),
                    )
                    current = database.execute(
                        "SELECT * FROM inventory WHERE product_id = ? AND warehouse_id = ?",
                        (product["id"], warehouse_id),
                    ).fetchone()
                    if current:
                        new_quantity = current["quantity_on_hand"] + quantity
                        weighted_cost = (
                            current["quantity_on_hand"] * current["average_cost"] + line_total
                        ) / new_quantity
                        database.execute(
                            """
                            UPDATE inventory SET quantity_on_hand = ?, average_cost = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (new_quantity, weighted_cost, now, current["id"]),
                        )
                    else:
                        database.execute(
                            """
                            INSERT INTO inventory(
                                product_id, warehouse_id, quantity_on_hand,
                                reorder_level, average_cost, updated_at
                            ) VALUES (?, ?, ?, 10, ?, ?)
                            """,
                            (product["id"], warehouse_id, quantity, unit_cost, now),
                        )
                database.execute(
                    """
                    INSERT INTO audit_log(actor_user_id, action, entity_type, entity_id, details)
                    VALUES (?, 'RECEIVE_STOCK', 'PROCUREMENT_RECEIPT', ?, ?)
                    """,
                    (g.user["id"], receipt_id, json.dumps({"receipt": receipt_number, "lines": len(parsed_lines)}, ensure_ascii=False)),
                )
                database.commit()
            except DATABASE_ERRORS as exc:
                database.rollback()
                flash(f"Unable to create goods receipt: {exc}", "error")
            else:
                flash("Goods received and inventory updated.", "success")
                return redirect(url_for("employee.procurement_detail", receipt_id=receipt_id))
    return render_template(
        "employee/new_procurement.html", suppliers=suppliers, warehouses=warehouses
    )


@bp.get("/procurements/<int:receipt_id>")
@role_required("employee", "admin")
def procurement_detail(receipt_id: int):
    database = get_db()
    scope, params = _warehouse_scope("pr.warehouse_id")
    receipt = database.execute(
        f"""
        SELECT pr.*, s.name AS supplier_name, s.supplier_code,
               w.name AS warehouse_name, w.warehouse_code,
               u.full_name AS employee_name
        FROM procurement_receipts pr
        JOIN suppliers s ON s.id = pr.supplier_id
        JOIN warehouses w ON w.id = pr.warehouse_id
        JOIN users u ON u.id = pr.employee_id
        WHERE pr.id = ? AND {scope}
        """,
        (receipt_id, *params),
    ).fetchone()
    if receipt is None:
        abort(404)
    lines = database.execute(
        """
        SELECT pi.*, p.product_code, p.name
        FROM procurement_items pi JOIN products p ON p.id = pi.product_id
        WHERE pi.receipt_id = ? ORDER BY pi.id
        """,
        (receipt_id,),
    ).fetchall()
    return render_template("employee/procurement_detail.html", receipt=receipt, lines=lines)

