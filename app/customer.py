from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import DATABASE_ERRORS, get_db
from .security import role_required


bp = Blueprint("customer", __name__, url_prefix="/customer")


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _cart_id(database) -> int:
    row = database.execute("SELECT id FROM carts WHERE customer_id = ?", (g.user["id"],)).fetchone()
    if row:
        return row["id"]
    cursor = database.execute("INSERT INTO carts(customer_id) VALUES (?)", (g.user["id"],))
    database.commit()
    return cursor.lastrowid


def _cart_rows(database):
    return database.execute(
        """
        SELECT ci.id AS cart_item_id, ci.quantity, p.*, c.name AS category_name,
               pl.name AS platform_name,
               COALESCE(i.stock, 0) AS stock_quantity,
               ci.quantity * p.current_price AS line_total
        FROM carts ca
        JOIN cart_items ci ON ci.cart_id = ca.id
        JOIN products p ON p.id = ci.product_id
        JOIN categories c ON c.id = p.category_id
        JOIN platforms pl ON pl.id = p.platform_id
        LEFT JOIN (SELECT product_id, SUM(quantity_on_hand) AS stock FROM inventory GROUP BY product_id) i
          ON i.product_id = p.id
        WHERE ca.customer_id = ?
        ORDER BY ci.created_at DESC
        """,
        (g.user["id"],),
    ).fetchall()


@bp.get("/cart")
@role_required("customer")
def cart():
    rows = _cart_rows(get_db())
    subtotal = sum(row["line_total"] for row in rows)
    shipping_fee = 0 if subtotal >= 500_000 and subtotal > 0 else 30_000 if rows else 0
    return render_template(
        "customer/cart.html",
        items=rows,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=subtotal + shipping_fee,
    )


@bp.post("/cart/add/<int:product_id>")
@role_required("customer")
def add_to_cart(product_id: int):
    quantity = max(request.form.get("quantity", 1, type=int), 1)
    database = get_db()
    product = database.execute(
        """
        SELECT p.id, p.is_active, COALESCE(SUM(i.quantity_on_hand), 0) AS stock
        FROM products p LEFT JOIN inventory i ON i.product_id = p.id
        WHERE p.id = ? GROUP BY p.id, p.is_active
        """,
        (product_id,),
    ).fetchone()
    if product is None or not product["is_active"]:
        abort(404)
    if product["stock"] < quantity:
        flash("Insufficient product stock.", "error")
        return redirect(request.referrer or url_for("catalog.products"))
    cart_id = _cart_id(database)
    database.execute(
        """
        INSERT INTO cart_items(cart_id, product_id, quantity)
        VALUES (?, ?, ?)
        ON CONFLICT(cart_id, product_id) DO UPDATE SET
            quantity = CASE WHEN cart_items.quantity + excluded.quantity > ?
                THEN ? ELSE cart_items.quantity + excluded.quantity END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (cart_id, product_id, quantity, product["stock"], product["stock"]),
    )
    database.commit()
    flash("Product added to your cart.", "success")
    return redirect(request.form.get("next") or request.referrer or url_for("customer.cart"))


@bp.post("/cart/update/<int:item_id>")
@role_required("customer")
def update_cart(item_id: int):
    quantity = request.form.get("quantity", type=int)
    database = get_db()
    item = database.execute(
        """
        SELECT ci.*, COALESCE(i.stock, 0) AS stock
        FROM cart_items ci
        JOIN carts c ON c.id = ci.cart_id
        LEFT JOIN (SELECT product_id, SUM(quantity_on_hand) AS stock FROM inventory GROUP BY product_id) i
          ON i.product_id = ci.product_id
        WHERE ci.id = ? AND c.customer_id = ?
        """,
        (item_id, g.user["id"]),
    ).fetchone()
    if item is None:
        abort(404)
    if quantity is None or quantity <= 0:
        database.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
    elif quantity > item["stock"]:
        flash("The requested quantity exceeds available stock.", "error")
        return redirect(url_for("customer.cart"))
    else:
        database.execute(
            "UPDATE cart_items SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (quantity, item_id),
        )
    database.commit()
    flash("Shopping cart updated.", "success")
    return redirect(url_for("customer.cart"))


@bp.post("/cart/remove/<int:item_id>")
@role_required("customer")
def remove_from_cart(item_id: int):
    database = get_db()
    database.execute(
        """
        DELETE FROM cart_items WHERE id = ? AND cart_id IN (
            SELECT id FROM carts WHERE customer_id = ?
        )
        """,
        (item_id, g.user["id"]),
    )
    database.commit()
    flash("Product removed from your cart.", "info")
    return redirect(url_for("customer.cart"))


@bp.route("/checkout", methods=("GET", "POST"))
@role_required("customer")
def checkout():
    database = get_db()
    rows = _cart_rows(database)
    if not rows:
        flash("Your shopping cart is empty.", "error")
        return redirect(url_for("customer.cart"))
    subtotal = sum(row["line_total"] for row in rows)
    shipping_fee = 0 if subtotal >= 500_000 else 30_000
    total = subtotal + shipping_fee
    if request.method == "POST":
        address = request.form.get("shipping_address", "").strip()
        city = request.form.get("shipping_city", "").strip()
        phone = request.form.get("phone", "").strip()
        payment_method = request.form.get("payment_method", "demo_card")
        if not address or not city or not phone:
            flash("Please enter a complete shipping address and phone number.", "error")
        elif payment_method not in {"cod", "bank_transfer", "demo_card"}:
            flash("Invalid payment method.", "error")
        else:
            now = _now()
            suffix = uuid.uuid4().hex[:8].upper()
            try:
                database.execute("BEGIN IMMEDIATE")
                allocations = []
                for item in rows:
                    stock = database.execute(
                        """
                        SELECT * FROM inventory
                        WHERE product_id = ? AND quantity_on_hand >= ?
                        ORDER BY quantity_on_hand DESC LIMIT 1
                        """,
                        (item["id"], item["quantity"]),
                    ).fetchone()
                    if stock is None:
                        raise ValueError(f"Insufficient stock for {item['name']}")
                    allocations.append((item, stock))
                order_number = "ORD-" + datetime.now().strftime("%Y%m%d") + "-" + suffix
                cursor = database.execute(
                    """
                    INSERT INTO orders(
                        order_number, customer_id, status, payment_status,
                        shipping_address, shipping_city, subtotal, discount_total,
                        shipping_fee, total_amount, created_at, paid_at
                    ) VALUES (?, ?, 'confirmed', 'paid', ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (order_number, g.user["id"], address, city, subtotal, shipping_fee, total, now, now),
                )
                order_id = cursor.lastrowid
                for item, stock in allocations:
                    database.execute(
                        """
                        INSERT INTO order_items(
                            order_id, product_id, warehouse_id, quantity, unit_price,
                            discount_amount, line_total
                        ) VALUES (?, ?, ?, ?, ?, 0, ?)
                        """,
                        (order_id, item["id"], stock["warehouse_id"], item["quantity"], item["current_price"], item["line_total"]),
                    )
                    changed = database.execute(
                        """
                        UPDATE inventory SET quantity_on_hand = quantity_on_hand - ?, updated_at = ?
                        WHERE id = ? AND quantity_on_hand >= ?
                        """,
                        (item["quantity"], now, stock["id"], item["quantity"]),
                    )
                    if changed.rowcount != 1:
                        raise ValueError(f"Inventory changed while processing {item['name']}")
                database.execute(
                    """
                    INSERT INTO payments(order_id, method, status, amount, transaction_ref, paid_at)
                    VALUES (?, ?, 'success', ?, ?, ?)
                    """,
                    (order_id, payment_method, total, "PAY-" + suffix, now),
                )
                database.execute(
                    """
                    INSERT INTO invoices(order_id, invoice_number, issued_at, total_amount)
                    VALUES (?, ?, ?, ?)
                    """,
                    (order_id, "INV-" + datetime.now().strftime("%Y%m%d") + "-" + suffix, now, total),
                )
                database.execute(
                    "UPDATE users SET phone = ?, address = ?, city = ?, updated_at = ? WHERE id = ?",
                    (phone, address, city, now, g.user["id"]),
                )
                database.execute("DELETE FROM cart_items WHERE cart_id = ?", (_cart_id(database),))
                database.execute(
                    "INSERT INTO audit_log(actor_user_id, action, entity_type, entity_id, details) VALUES (?, 'CHECKOUT', 'ORDER', ?, ?)",
                    (g.user["id"], order_id, f"Order {order_number}; total {total}"),
                )
                database.commit()
            except (ValueError, *DATABASE_ERRORS) as exc:
                database.rollback()
                flash(str(exc), "error")
            else:
                flash("Order placed successfully. Your invoice has been created.", "success")
                return redirect(url_for("customer.order_detail", order_id=order_id))
    return render_template(
        "customer/checkout.html",
        items=rows,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=total,
    )


@bp.get("/orders")
@role_required("customer")
def orders():
    rows = get_db().execute(
        """
        SELECT o.*, inv.invoice_number, oi.item_count
        FROM orders o
        JOIN invoices inv ON inv.order_id = o.id
        JOIN (SELECT order_id, COUNT(*) AS item_count FROM order_items GROUP BY order_id) oi ON oi.order_id = o.id
        WHERE o.customer_id = ? ORDER BY o.created_at DESC
        """,
        (g.user["id"],),
    ).fetchall()
    return render_template("customer/orders.html", orders=rows)


@bp.get("/orders/<int:order_id>")
@role_required("customer")
def order_detail(order_id: int):
    database = get_db()
    order = database.execute(
        """
        SELECT o.*, inv.invoice_number, inv.issued_at, pay.method AS payment_method,
               pay.transaction_ref
        FROM orders o JOIN invoices inv ON inv.order_id = o.id
        JOIN payments pay ON pay.order_id = o.id
        WHERE o.id = ? AND o.customer_id = ?
        """,
        (order_id, g.user["id"]),
    ).fetchone()
    if order is None:
        abort(404)
    items = database.execute(
        """
        SELECT oi.*, p.product_code, p.name, p.image_url, pl.name AS platform_name
        FROM order_items oi JOIN products p ON p.id = oi.product_id
        JOIN platforms pl ON pl.id = p.platform_id
        WHERE oi.order_id = ? ORDER BY oi.id
        """,
        (order_id,),
    ).fetchall()
    return render_template("customer/order_detail.html", order=order, items=items)
