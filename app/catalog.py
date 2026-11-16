from __future__ import annotations

import math

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from .db import get_db
from .security import role_required


bp = Blueprint("catalog", __name__)


PRODUCT_SELECT = """
    SELECT p.*, c.name AS category_name, pl.name AS platform_name,
           COALESCE(i.stock, 0) AS stock_quantity
    FROM products p
    JOIN categories c ON c.id = p.category_id
    JOIN platforms pl ON pl.id = p.platform_id
    LEFT JOIN (SELECT product_id, SUM(quantity_on_hand) AS stock FROM inventory GROUP BY product_id) i
      ON i.product_id = p.id
"""


@bp.get("/")
def home():
    database = get_db()
    featured = database.execute(
        PRODUCT_SELECT
        + " WHERE p.is_active = 1 AND i.stock > 0 ORDER BY p.rating DESC, p.sold_snapshot DESC LIMIT 8"
    ).fetchall()
    categories = database.execute(
        """
        SELECT c.id, c.name, COUNT(p.id) AS product_count
        FROM categories c JOIN products p ON p.category_id = c.id
        WHERE p.is_active = 1 GROUP BY c.id, c.name ORDER BY product_count DESC LIMIT 6
        """
    ).fetchall()
    stats = database.execute(
        """
        SELECT COUNT(*) AS products,
               COUNT(DISTINCT category_id) AS categories,
               COUNT(DISTINCT platform_id) AS platforms
        FROM products WHERE is_active = 1
        """
    ).fetchone()
    return render_template("home.html", products=featured, categories=categories, stats=stats)


@bp.get("/products")
def products():
    database = get_db()
    query = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    platform_id = request.args.get("platform", type=int)
    sort = request.args.get("sort", "popular")
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = current_app.config["PRODUCTS_PER_PAGE"]

    where = ["p.is_active = 1"]
    params: list = []
    if query:
        where.append("(LOWER(p.name) LIKE LOWER(?) OR LOWER(p.product_code) LIKE LOWER(?) OR LOWER(p.brand_name) LIKE LOWER(?))")
        token = f"%{query}%"
        params.extend([token, token, token])
    if category_id:
        where.append("p.category_id = ?")
        params.append(category_id)
    if platform_id:
        where.append("p.platform_id = ?")
        params.append(platform_id)
    where_sql = " WHERE " + " AND ".join(where)
    order_sql = {
        "price_asc": "p.current_price ASC",
        "price_desc": "p.current_price DESC",
        "rating": "p.rating DESC, p.review_count DESC",
        "newest": "p.id DESC",
    }.get(sort, "p.sold_snapshot DESC, p.rating DESC")

    count = database.execute(
        "SELECT COUNT(*) AS n FROM products p" + where_sql, params
    ).fetchone()["n"]
    rows = database.execute(
        PRODUCT_SELECT
        + where_sql
        + f" ORDER BY {order_sql} LIMIT ? OFFSET ?",
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    categories = database.execute(
        "SELECT id, name FROM categories WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    platforms = database.execute("SELECT id, name FROM platforms WHERE is_active = 1").fetchall()
    return render_template(
        "catalog/products.html",
        products=rows,
        categories=categories,
        platforms=platforms,
        page=page,
        pages=max(math.ceil(count / per_page), 1),
        total=count,
        query=query,
        category_id=category_id,
        platform_id=platform_id,
        sort=sort,
    )


@bp.get("/products/<int:product_id>")
def product_detail(product_id: int):
    product = get_db().execute(
        PRODUCT_SELECT + " WHERE p.id = ?", (product_id,)
    ).fetchone()
    if product is None or not product["is_active"]:
        abort(404)
    related = get_db().execute(
        PRODUCT_SELECT
        + " WHERE p.category_id = ? AND p.id != ? AND p.is_active = 1 ORDER BY p.rating DESC LIMIT 4",
        (product["category_id"], product_id),
    ).fetchall()
    return render_template("catalog/product_detail.html", product=product, related=related)


@bp.get("/api/products")
@role_required("employee", "admin")
def product_lookup():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])
    token = f"%{query}%"
    rows = get_db().execute(
        """
        SELECT p.id, p.product_code, p.name, p.current_price,
               COALESCE(SUM(i.quantity_on_hand), 0) AS stock
        FROM products p
        JOIN platforms pl ON pl.id = p.platform_id
        LEFT JOIN inventory i ON i.product_id = p.id
        WHERE p.is_active = 1
          AND (LOWER(p.product_code) LIKE LOWER(?) OR LOWER(p.name) LIKE LOWER(?) OR LOWER(pl.name) LIKE LOWER(?))
        GROUP BY p.id, p.product_code, p.name, p.current_price ORDER BY p.name LIMIT 20
        """,
        (token, token, token),
    ).fetchall()
    return jsonify([dict(row) for row in rows])

