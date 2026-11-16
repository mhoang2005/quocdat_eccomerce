import sqlite3
from contextlib import closing

import pytest

from app import create_app
from app.db import get_db
from app.services import etl
from app.services.analytics_dashboard import _marketplace_metrics
from app.services.snapshot_partitions import FACT, refresh_snapshot_months, snapshot_source
from conftest import login_as


@pytest.fixture
def feature_app(app, tmp_path):
    config = {"TESTING": True, "SECRET_KEY": "test-secret", "INSTANCE_DIR": tmp_path, "SQLSERVER_CONNECTION": ""}
    for key in ("OLTP_DATABASE", "STAGING_DATABASE", "DWH_DATABASE"):
        path = tmp_path / app.config[key].name
        source_uri = app.config[key].resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source:
            with closing(sqlite3.connect(path)) as target:
                source.backup(target)
        config[key] = path
    return create_app(config)


def test_sales_cdc_applies_changes_and_retries_failed_batch(feature_app, monkeypatch):
    with feature_app.app_context():
        oltp, staging, dwh = (get_db(name) for name in ("oltp", "staging", "dwh"))
        order_id = oltp.execute("SELECT id FROM orders WHERE order_number = 'ORD-DEMO-001'").fetchone()[0]
        line_id = oltp.execute("SELECT MIN(id) FROM order_items WHERE order_id = ?", (order_id,)).fetchone()[0]
        before = etl.run_etl()["sales_cdc"]
        assert before["events"] == before["staged"] == 0
        oltp.execute("UPDATE order_items SET line_total = 100 WHERE id = ?", (line_id,))
        oltp.rollback()
        assert oltp.execute("SELECT MAX(event_id) FROM cdc_event").fetchone()[0] == before["through_event_id"]
        oltp.execute("UPDATE order_items SET line_total = 200 WHERE id = ?", (line_id,))
        oltp.commit()

        def fail_refresh(**_kwargs):
            raise RuntimeError("Simulated OLAP failure")

        with monkeypatch.context() as patch:
            patch.setattr(etl, "refresh_olap", fail_refresh)
            with pytest.raises(RuntimeError, match="Simulated OLAP failure"):
                etl.run_etl()
        assert staging.execute("SELECT event_id FROM cdc_checkpoint").fetchone()[0] == before["through_event_id"]
        line_total = "SELECT net_amount FROM fact_sales WHERE source_order_item_id = ?"
        assert dwh.execute(line_total, (line_id,)).fetchone()[0] != 200
        after = etl.run_etl()["sales_cdc"]
        assert (after["events"], after["orders"], after["staged"]) == (1, 1, 2)
        assert dwh.execute(line_total, (line_id,)).fetchone()[0] == 200

        oltp.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
        oltp.commit()
        cancelled = etl.run_etl()["sales_cdc"]
        assert (cancelled["events"], cancelled["staged"], cancelled["removed_facts"]) == (1, 0, 2)
        assert dwh.execute(line_total, (line_id,)).fetchone() is None
        total = dwh.execute(
            "SELECT net_revenue FROM cube_sales WHERE time_level = 'ALL' AND grouping_mask = 7"
        ).fetchone()
        assert total[0] == 0
        assert etl.run_etl()["sales_cdc"]["events"] == 0


def test_snapshot_partitions_reconcile_and_fall_back_when_dirty(feature_app):
    with feature_app.app_context():
        dwh = get_db("dwh")
        month = dwh.execute("SELECT month_key FROM snapshot_month ORDER BY month_key LIMIT 1").fetchone()[0]
        year, month_number = divmod(month, 100)
        table = f"snapshot_{month}"
        filters = {"year": year, "month": month_number, "category": "", "platform": ""}
        assert snapshot_source(dwh, year, month_number) == table
        assert snapshot_source(dwh, year, None) == FACT
        partition_metrics = _marketplace_metrics(dwh, filters)
        dwh.execute("UPDATE snapshot_month SET dirty = 1 WHERE month_key = ?", (month,))
        assert snapshot_source(dwh, year, month_number) == FACT
        assert _marketplace_metrics(dwh, filters) == pytest.approx(partition_metrics)

        try:
            dwh.execute("UPDATE snapshot_month SET dirty = 0 WHERE month_key = ?", (month,))
            dwh.execute(f"UPDATE {FACT} SET sale_price = 123 WHERE date_key / 100 = ?", (month,))
            assert snapshot_source(dwh, year, month_number) == FACT
            expected = _marketplace_metrics(dwh, filters)
            assert expected["average_sale_price"] == 123
            assert refresh_snapshot_months(dwh) == 1
            assert _marketplace_metrics(dwh, filters) == expected
            assert snapshot_source(dwh, year, month_number) == table
        finally:
            dwh.rollback()


def test_staff_warehouse_grant_revoke_and_admin_masking(feature_app, csrf_token):
    staff = feature_app.test_client()
    admin = feature_app.test_client()
    employee_id = login_as(staff, feature_app, "employee@quocdat.local")
    login_as(admin, feature_app, "admin@quocdat.local")
    with feature_app.app_context():
        oltp = get_db()
        warehouse_id = oltp.execute("SELECT id FROM warehouses WHERE warehouse_code = 'WH-HCM'").fetchone()[0]
        receipt_id = oltp.execute(
            "SELECT id FROM procurement_receipts WHERE receipt_number = 'GRN-DEMO-001'"
        ).fetchone()[0]
        oltp.execute("UPDATE procurement_receipts SET warehouse_id = ? WHERE id = ?", (warehouse_id, receipt_id))
        oltp.commit()

    detail = f"/employee/procurements/{receipt_id}"
    assert staff.get(detail).status_code == 404
    assert b"GRN-DEMO-001" not in staff.get("/employee/procurements").data
    assert b"GRN-DEMO-001" not in staff.get("/employee/").data
    assert b"WH-HCM" not in staff.get("/employee/procurements/new").data
    assert admin.get(detail).status_code == 200
    access_form = {
        "employee_id": employee_id, "warehouse_id": warehouse_id, "csrf_token": csrf_token,
    }
    access_url = "/admin/settings/warehouse-access"
    assert staff.post(access_url, data={**access_form, "action": "grant"}).status_code == 403
    assert staff.post("/employee/procurements/new", data=access_form).status_code == 403
    assert admin.post(access_url, data={**access_form, "action": "grant"}).status_code == 302
    assert staff.get(detail).status_code == 200
    assert b"WH-HCM" in staff.get("/employee/procurements/new").data
    assert admin.post(access_url, data={**access_form, "action": "revoke"}).status_code == 302
    assert staff.get(detail).status_code == 404
    accounts = admin.get("/admin/users?role=customer")
    assert b"c***@quocdat.local" in accounts.data
    assert b"******0003" in accounts.data
    assert b"customer@quocdat.local" not in accounts.data
    assert b"0900000003" not in accounts.data
