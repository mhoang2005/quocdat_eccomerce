from __future__ import annotations

import pytest

from app.db import get_db
from app.services.analytics import refresh_olap
from app.services.analytics_dashboard import build_analytics_dashboard
from app.services.etl import run_etl

from conftest import login_as


def test_public_storefront_pages_render(client):
    for path in ("/", "/products", "/products/1", "/auth/login", "/auth/register"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert b"QuocDat" in response.data


def test_real_login_and_role_redirect(client):
    client.get("/auth/login")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/auth/login",
        data={
            "csrf_token": token,
            "email": "employee@quocdat.local",
            "password": "Staff@123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert response.request.path == "/employee/"
    assert b"Staff operations" in response.data


def test_role_boundaries_and_backoffice_templates(client, app):
    login_as(client, app, "customer@quocdat.local")
    assert client.get("/customer/orders").status_code == 200
    assert client.get("/admin/").status_code == 403
    assert client.get("/employee/").status_code == 403

    login_as(client, app, "employee@quocdat.local")
    assert client.get("/employee/").status_code == 200
    assert client.get("/employee/procurements").status_code == 200
    assert client.get("/employee/procurements/new").status_code == 200
    assert client.get("/admin/").status_code == 403

    login_as(client, app, "admin@quocdat.local")
    for path in (
        "/admin/",
        "/admin/products",
        "/admin/users",
        "/admin/settings",
        "/admin/etl",
        "/admin/olap",
        "/admin/analytics",
        "/employee/procurements",
    ):
        assert client.get(path).status_code == 200, path

    lookup = client.get("/api/products?q=Lazada")
    assert lookup.status_code == 200
    assert len(lookup.get_json()) > 0


def test_customer_checkout_creates_invoice_and_decrements_stock(client, app, csrf_token):
    customer_id = login_as(client, app, "customer@quocdat.local")
    with app.app_context():
        database = get_db()
        product = database.execute(
            """
            SELECT p.id, SUM(i.quantity_on_hand) AS stock
            FROM products p JOIN inventory i ON i.product_id = p.id
            WHERE p.is_active = 1
            GROUP BY p.id HAVING SUM(i.quantity_on_hand) >= 10
            ORDER BY p.id LIMIT 1
            """
        ).fetchone()
        product_id = product["id"]
        stock_before = product["stock"]

    response = client.post(
        f"/customer/cart/add/{product_id}",
        data={"csrf_token": csrf_token, "quantity": 2, "next": "/customer/cart"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Review before checkout" in response.data

    response = client.post(
        "/customer/checkout",
        data={
            "csrf_token": csrf_token,
            "shipping_address": "123 Data Street",
            "shipping_city": "Hanoi",
            "phone": "0909123456",
            "payment_method": "demo_card",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Sales invoice" in response.data

    with app.app_context():
        database = get_db()
        order = database.execute(
            "SELECT * FROM orders WHERE customer_id = ? ORDER BY id DESC LIMIT 1",
            (customer_id,),
        ).fetchone()
        assert order["payment_status"] == "paid"
        assert database.execute(
            "SELECT 1 FROM invoices WHERE order_id = ?", (order["id"],)
        ).fetchone()
        assert database.execute(
            "SELECT 1 FROM payments WHERE order_id = ? AND status = 'success'", (order["id"],)
        ).fetchone()
        stock_after = database.execute(
            "SELECT SUM(quantity_on_hand) AS n FROM inventory WHERE product_id = ?", (product_id,)
        ).fetchone()["n"]
        assert stock_after == stock_before - 2


def test_employee_procurement_increases_inventory(client, app, csrf_token):
    login_as(client, app, "employee@quocdat.local")
    with app.app_context():
        database = get_db()
        product = database.execute("SELECT id, product_code FROM products ORDER BY id LIMIT 1").fetchone()
        supplier_id = database.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1").fetchone()["id"]
        warehouse_id = database.execute("SELECT id FROM warehouses ORDER BY id LIMIT 1").fetchone()["id"]
        stock_before = database.execute(
            "SELECT quantity_on_hand FROM inventory WHERE product_id = ? AND warehouse_id = ?",
            (product["id"], warehouse_id),
        ).fetchone()["quantity_on_hand"]

    response = client.post(
        "/employee/procurements/new",
        data={
            "csrf_token": csrf_token,
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "notes": "Procurement workflow test",
            "product_code[]": product["product_code"],
            "quantity[]": "5",
            "unit_cost[]": "75000",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Inventory was updated in real time" in response.data

    with app.app_context():
        stock_after = get_db().execute(
            "SELECT quantity_on_hand FROM inventory WHERE product_id = ? AND warehouse_id = ?",
            (product["id"], warehouse_id),
        ).fetchone()["quantity_on_hand"]
        assert stock_after == stock_before + 5


def test_admin_edit_creates_scd2_version_after_etl(client, app, csrf_token):
    login_as(client, app, "admin@quocdat.local")
    with app.app_context():
        database = get_db()
        product = database.execute("SELECT * FROM products ORDER BY id LIMIT 1").fetchone()
        category_id = product["category_id"]
        product_id = product["id"]
        natural_key = product["natural_key"]
        new_name = product["name"] + " · SCD2 version"
        before = get_db("dwh").execute(
            "SELECT COUNT(*) AS n FROM dim_product WHERE product_nk = ?", (natural_key,)
        ).fetchone()["n"]

    response = client.post(
        f"/admin/products/{product_id}/edit",
        data={
            "csrf_token": csrf_token,
            "name": new_name,
            "category_id": category_id,
            "current_price": product["current_price"],
            "list_price": product["list_price"] or product["current_price"],
            "origin": product["origin"] or "Vietnam",
            "brand_name": product["brand_name"] or "QuocDat Marketplace",
            "is_active": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "SCD2".encode() in response.data

    with app.app_context():
        result = run_etl("incremental")
        assert result["status"] == "SUCCESS"
        dwh = get_db("dwh")
        versions = dwh.execute(
            "SELECT * FROM dim_product WHERE product_nk = ? ORDER BY valid_from", (natural_key,)
        ).fetchall()
        assert len(versions) == before + 1
        assert sum(row["is_current"] for row in versions) == 1
        assert versions[-1]["product_name"] == new_name


def test_staging_and_four_facts_are_populated(app):
    with app.app_context():
        staging = get_db("staging")
        assert staging.execute("SELECT COUNT(*) AS n FROM stg_product_snapshot").fetchone()["n"] >= 17_640
        assert staging.execute("SELECT COUNT(*) AS n FROM stg_sales_line").fetchone()["n"] >= 1
        assert staging.execute("SELECT COUNT(*) AS n FROM stg_procurement_line").fetchone()["n"] >= 1
        assert staging.execute("SELECT COUNT(*) AS n FROM stg_inventory_snapshot").fetchone()["n"] >= 1

        dwh = get_db("dwh")
        for table in ("fact_sales", "fact_procurement", "fact_inventory", "fact_product_snapshot"):
            assert dwh.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] >= 1


def test_materialized_views_and_sales_cube_are_populated_and_idempotent(app):
    with app.app_context():
        dwh = get_db("dwh")
        materialized_views = (
            "mv_sales_daily",
            "mv_procurement_daily",
            "mv_inventory_daily",
            "mv_marketplace_daily",
        )
        for table in materialized_views:
            assert dwh.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] >= 1

        fact_total = dwh.execute(
            "SELECT COUNT(*) AS lines, SUM(quantity) AS units, SUM(net_amount) AS revenue FROM fact_sales"
        ).fetchone()
        mv_total = dwh.execute(
            "SELECT SUM(line_count) AS lines, SUM(quantity_sold) AS units, SUM(net_revenue) AS revenue FROM mv_sales_daily"
        ).fetchone()
        grand_total = dwh.execute(
            """
            SELECT * FROM cube_sales
            WHERE time_level = 'ALL' AND platform_name = 'ALL'
              AND category_name = 'ALL'
              AND customer_city = 'ALL'
            """
        ).fetchone()
        assert grand_total is not None
        assert mv_total["lines"] == fact_total["lines"] == grand_total["line_count"]
        assert mv_total["units"] == fact_total["units"] == grand_total["quantity_sold"]
        assert mv_total["revenue"] == pytest.approx(fact_total["revenue"])
        assert grand_total["net_revenue"] == pytest.approx(fact_total["revenue"])

        levels = {
            row["time_level"]
            for row in dwh.execute("SELECT DISTINCT time_level FROM cube_sales")
        }
        masks = {
            row["grouping_mask"]
            for row in dwh.execute("SELECT DISTINCT grouping_mask FROM cube_sales")
        }
        assert levels == {"DAY", "MONTH", "QUARTER", "YEAR", "ALL"}
        assert masks == set(range(8))
        assert dwh.execute(
            """
            SELECT COUNT(*) AS n FROM cube_sales
            WHERE customer_city != 'ALL'
            """
        ).fetchone()["n"] >= 1

        counts_before = {
            table: dwh.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in (*materialized_views, "cube_sales")
        }
        first = refresh_olap(source_etl_run_id="TEST-ETL")
        second = refresh_olap(source_etl_run_id="TEST-ETL")
        assert first["status"] == second["status"] == "SUCCESS"
        counts_after = {
            table: dwh.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in (*materialized_views, "cube_sales")
        }
        assert counts_after == counts_before


def test_admin_can_explore_and_refresh_olap_layer(client, app, csrf_token):
    login_as(client, app, "admin@quocdat.local")
    response = client.get(
        "/admin/olap?level=YEAR&platform=Tiki&category=&city=ALL&pivot=location"
    )
    assert response.status_code == 200
    assert b"Cube Explorer" in response.data
    assert b"Apply Slice / Dice" in response.data
    assert b"Drill down to Quarter" in response.data
    assert b"Pivot View" in response.data
    assert b"Location \xc3\x97 Time" in response.data

    response = client.post(
        "/admin/olap/refresh",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"OLAP refresh completed" in response.data


def test_admin_analytics_dashboard_and_drill_across(client, app):
    login_as(client, app, "admin@quocdat.local")
    with app.app_context():
        dwh = get_db("dwh")
        grain = dwh.execute(
            """
            SELECT d.year_number, f.date_key, pr.category_name, w.warehouse_name,
                   COUNT(DISTINCT f.order_number) AS order_count,
                   SUM(f.quantity) AS quantity_sold,
                   SUM(f.net_amount) AS net_revenue
            FROM fact_sales f
            JOIN dim_date d ON d.date_key = f.date_key
            JOIN dim_product pr ON pr.product_key = f.product_key
            JOIN dim_warehouse w ON w.warehouse_key = f.warehouse_key
            GROUP BY d.year_number, f.date_key, pr.category_name, w.warehouse_name
            ORDER BY f.date_key DESC LIMIT 1
            """
        ).fetchone()
        dashboard = build_analytics_dashboard(
            dwh,
            {
                "year": str(grain["year_number"]),
                "category": grain["category_name"],
                "warehouse": grain["warehouse_name"],
            },
        )
        aligned = next(
            row
            for row in dashboard["drill_rows"]
            if row["date_key"] == grain["date_key"]
            and row["category_name"] == grain["category_name"]
            and row["warehouse_name"] == grain["warehouse_name"]
        )
        assert aligned["order_count"] == grain["order_count"]
        assert aligned["quantity_sold"] == grain["quantity_sold"]
        assert aligned["net_revenue"] == pytest.approx(grain["net_revenue"])
        assert dashboard["drill_summary"]["aligned_cells"] >= 1

    response = client.get(
        "/admin/analytics",
        query_string={
            "year": grain["year_number"],
            "category": grain["category_name"],
            "warehouse": grain["warehouse_name"],
        },
    )
    assert response.status_code == 200
    assert b"Analytics Dashboard" in response.data
    assert b"Sales \xc3\x97 Procurement \xc3\x97 Inventory" in response.data
    assert b"Conformed analytical grain" in response.data
    assert b"Aggregate facts" in response.data
