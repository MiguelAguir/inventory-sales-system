"""Pruebas de las vistas analiticas."""

from __future__ import annotations

from tests.conftest import register_purchase, register_sale, stock_quantity


def test_views_return_consistent_data(conn, base) -> None:
    register_purchase(conn, base, 5)
    register_sale(conn, base, 2, unit_price=100.0, discount_pct=0)

    stock = conn.execute(
        """
        SELECT quantity, stock_value, stock_status
          FROM reporting.v_stock_actual
         WHERE product_id = %s AND warehouse_id = %s
        """,
        (base["product_id"], base["warehouse_id"]),
    ).fetchone()
    assert stock["quantity"] == 13
    assert float(stock["stock_value"]) == 780.00
    assert stock["stock_status"] == "OK"

    monthly = conn.execute(
        """
        SELECT revenue, units, gross_margin
          FROM reporting.v_ventas_mensuales
         ORDER BY month DESC
         LIMIT 1
        """
    ).fetchone()
    assert float(monthly["revenue"]) == 200.00
    assert monthly["units"] == 2
    assert float(monthly["gross_margin"]) == 80.00

    ranking = conn.execute(
        "SELECT revenue_rank, revenue_share_pct FROM reporting.v_ranking_productos"
    ).fetchone()
    assert ranking["revenue_rank"] == 1
    assert float(ranking["revenue_share_pct"]) == 100.00

    abc = conn.execute(
        "SELECT abc_class, revenue_share_pct FROM reporting.v_abc_productos"
    ).fetchone()
    assert abc["abc_class"] == "A"
    assert float(abc["revenue_share_pct"]) == 100.00

    supplier = conn.execute(
        "SELECT purchases, units, amount FROM reporting.v_proveedores_compras"
    ).fetchone()
    assert supplier["purchases"] == 1
    assert supplier["units"] == 5
    assert float(supplier["amount"]) == 300.00

    rotation = conn.execute(
        """
        SELECT annualized_turns
          FROM reporting.v_rotacion_actual
         WHERE category_id = %s
        """,
        (base["category_id"],),
    ).fetchone()
    assert rotation["annualized_turns"] is not None

    value = conn.execute(
        "SELECT inventory_value FROM reporting.fn_inventory_value_at(now()) WHERE category_id = %s",
        (base["category_id"],),
    ).fetchone()
    assert float(value["inventory_value"]) == 780.00


def test_low_stock_and_replenishment_alert(conn, base) -> None:
    conn.execute(
        "SELECT core.fn_set_min_stock(%s, %s, 20)",
        (base["product_id"], base["warehouse_id"]),
    )
    low = conn.execute(
        """
        SELECT stock_status, deficit
          FROM reporting.v_bajo_minimo
         WHERE product_id = %s AND warehouse_id = %s
        """,
        (base["product_id"], base["warehouse_id"]),
    ).fetchone()
    assert low["stock_status"] == "BAJO MINIMO"
    assert low["deficit"] == 10

    alert = conn.execute(
        """
        SELECT priority, lead_time_days, supplier_name
          FROM reporting.v_alertas_reposicion
         WHERE product_id = %s AND warehouse_id = %s
        """,
        (base["product_id"], base["warehouse_id"]),
    ).fetchone()
    assert alert["priority"] == "ALTA"
    assert alert["lead_time_days"] == 5
    assert alert["supplier_name"] == "Proveedor Test S.A.C."


def test_no_negative_stock_after_sale(conn, base) -> None:
    register_sale(conn, base, 10)
    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 0
    assert conn.execute(
        "SELECT count(*) AS n FROM reporting.v_stock_actual WHERE quantity < 0"
    ).fetchone()["n"] == 0
