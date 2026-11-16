from app.sqlserver import Row, translate


def test_parameter_order_for_sqlserver_pagination():
    statement, params, _ = translate(
        "SELECT * FROM products WHERE is_active = ? ORDER BY id LIMIT ? OFFSET ?",
        (1, 20, 80),
    )
    assert statement.endswith("OFFSET ? ROWS FETCH NEXT ? ROWS ONLY")
    assert params == (1, 80, 20)


def test_sales_conflict_translation_keeps_business_key():
    statement, params, _ = translate(
        "INSERT INTO fact_sales(source_order_item_id, net_amount) VALUES (?, ?) "
        "ON CONFLICT(source_order_item_id) DO UPDATE SET net_amount = excluded.net_amount",
        (17, 21000),
    )
    assert "dest.[source_order_item_id] = incoming.[source_order_item_id]" in statement
    assert "UPDATE SET net_amount = incoming.[net_amount]" in statement
    assert params == (17, 21000)


def test_identity_insert_and_row_interface():
    statement, params, identity = translate("INSERT INTO carts(customer_id) VALUES (?)", (5,))
    assert statement == "INSERT INTO carts(customer_id) VALUES (?)"
    assert identity == "carts"
    row = Row(("id", "customer_id"), (7, params[0]))
    assert row[0] == row["ID"] == 7
    assert dict(row) == {"id": 7, "customer_id": 5}
    assert tuple(row) == (7, 5)
