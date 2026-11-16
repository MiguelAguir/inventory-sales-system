"""Pruebas de reglas de negocio e invariantes del modelo."""

from __future__ import annotations

import psycopg
import pytest

from tests.conftest import (
    ledger_quantity,
    register_purchase,
    register_sale,
    stock_quantity,
)


def _create_draft(conn: psycopg.Connection, base: dict[str, int], quantity: int = 2) -> int:
    sale_id = conn.execute(
        """
        INSERT INTO core.sales (sale_number, customer_id, warehouse_id, status)
        VALUES ('V-202601-000001', %s, %s, 'DRAFT')
        RETURNING sale_id
        """,
        (base["customer_id"], base["warehouse_id"]),
    ).fetchone()["sale_id"]
    conn.execute(
        """
        INSERT INTO core.sale_items (
            sale_id, line_number, product_id, quantity, unit_price, unit_cost, discount_pct
        )
        VALUES (%s, 1, %s, %s, 100.00, 60.00, 0)
        """,
        (sale_id, base["product_id"], quantity),
    )
    return int(sale_id)


def test_sale_totals_and_igv(conn, base) -> None:
    sale_id = register_sale(conn, base, 2, unit_price=100.0, discount_pct=10)

    sale = conn.execute(
        "SELECT status, subtotal, tax, total FROM core.sales WHERE sale_id = %s",
        (sale_id,),
    ).fetchone()

    assert sale["status"] == "CONFIRMED"
    assert float(sale["subtotal"]) == 180.00
    assert float(sale["tax"]) == 32.40
    assert float(sale["total"]) == 212.40


def test_stock_and_ledger_stay_in_sync(conn, base) -> None:
    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 10
    register_sale(conn, base, 3)

    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 7
    assert ledger_quantity(conn, base["product_id"], base["warehouse_id"]) == 7


def test_sale_without_stock_is_rejected_atomically(conn, base) -> None:
    register_sale(conn, base, 3)
    sales_before = conn.execute("SELECT count(*) AS n FROM core.sales").fetchone()["n"]

    with pytest.raises(psycopg.errors.CheckViolation):
        register_sale(conn, base, 8)

    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 7
    assert conn.execute("SELECT count(*) AS n FROM core.sales").fetchone()["n"] == sales_before


def test_cancel_sale_reverses_stock_and_is_idempotent(conn, base) -> None:
    sale_id = register_sale(conn, base, 3)
    conn.execute("SELECT core.fn_cancel_sale(%s)", (sale_id,))

    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 10
    assert ledger_quantity(conn, base["product_id"], base["warehouse_id"]) == 10
    assert conn.execute(
        "SELECT status FROM core.sales WHERE sale_id = %s", (sale_id,)
    ).fetchone()["status"] == "CANCELLED"
    assert conn.execute(
        "SELECT count(*) AS n FROM core.stock_movements WHERE sale_id = %s", (sale_id,)
    ).fetchone()["n"] == 2

    conn.execute("SELECT core.fn_cancel_sale(%s)", (sale_id,))
    assert conn.execute(
        "SELECT count(*) AS n FROM core.stock_movements WHERE sale_id = %s", (sale_id,)
    ).fetchone()["n"] == 2


def test_stock_movements_are_immutable(conn, base) -> None:
    movement_id = conn.execute(
        "SELECT movement_id FROM core.stock_movements LIMIT 1"
    ).fetchone()["movement_id"]

    with pytest.raises(psycopg.Error):
        conn.execute(
            "UPDATE core.stock_movements SET quantity_delta = 999 WHERE movement_id = %s",
            (movement_id,),
        )
    with pytest.raises(psycopg.Error):
        conn.execute("DELETE FROM core.stock_movements WHERE movement_id = %s", (movement_id,))


def test_confirmed_sale_header_is_immutable(conn, base) -> None:
    sale_id = register_sale(conn, base, 2)

    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE core.sales SET total = 1 WHERE sale_id = %s", (sale_id,))

    assert float(
        conn.execute("SELECT total FROM core.sales WHERE sale_id = %s", (sale_id,)).fetchone()["total"]
    ) == 236.00


def test_direct_confirmation_is_blocked(conn, base) -> None:
    sale_id = _create_draft(conn, base, 2)

    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE core.sales SET status = 'CONFIRMED', confirmed_at = now() WHERE sale_id = %s",
            (sale_id,),
        )

    assert conn.execute(
        "SELECT status FROM core.sales WHERE sale_id = %s", (sale_id,)
    ).fetchone()["status"] == "DRAFT"


def test_confirm_sale_is_idempotent(conn, base) -> None:
    sale_id = _create_draft(conn, base, 2)
    conn.execute("SELECT core.fn_confirm_sale(%s)", (sale_id,))
    conn.execute("SELECT core.fn_confirm_sale(%s)", (sale_id,))

    assert conn.execute(
        "SELECT count(*) AS n FROM core.stock_movements WHERE sale_id = %s AND movement_type = 'SALE'",
        (sale_id,),
    ).fetchone()["n"] == 1
    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 8


def test_purchase_and_cancel_update_stock(conn, base) -> None:
    purchase_id = register_purchase(conn, base, 5)
    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 15

    conn.execute("SELECT core.fn_cancel_purchase(%s)", (purchase_id,))
    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 10
    assert conn.execute(
        "SELECT status FROM core.purchases WHERE purchase_id = %s", (purchase_id,)
    ).fetchone()["status"] == "CANCELLED"


def test_purchase_cancel_cannot_leave_negative_stock(conn, base) -> None:
    purchase_id = register_purchase(conn, base, 5)
    register_sale(conn, base, 15)
    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 0

    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("SELECT core.fn_cancel_purchase(%s)", (purchase_id,))

    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 0
    assert conn.execute(
        "SELECT status FROM core.purchases WHERE purchase_id = %s", (purchase_id,)
    ).fetchone()["status"] == "CONFIRMED"


def test_transfer_moves_stock_between_warehouses(conn, base) -> None:
    other_id = conn.execute(
        "INSERT INTO core.warehouses (code, name) VALUES ('WH-T2', 'Almacen Test 2') RETURNING warehouse_id"
    ).fetchone()["warehouse_id"]

    conn.execute(
        "SELECT core.fn_transfer_stock(%s, %s, %s, 4)",
        (base["product_id"], base["warehouse_id"], other_id),
    )

    assert stock_quantity(conn, base["product_id"], base["warehouse_id"]) == 6
    assert stock_quantity(conn, base["product_id"], other_id) == 4
    assert ledger_quantity(conn, base["product_id"], base["warehouse_id"]) == 6
    assert ledger_quantity(conn, base["product_id"], other_id) == 4


def test_min_stock_and_low_stock_view(conn, base) -> None:
    conn.execute(
        "SELECT core.fn_set_min_stock(%s, %s, 12)",
        (base["product_id"], base["warehouse_id"]),
    )
    row = conn.execute(
        """
        SELECT stock_status, deficit
          FROM reporting.v_bajo_minimo
         WHERE product_id = %s AND warehouse_id = %s
        """,
        (base["product_id"], base["warehouse_id"]),
    ).fetchone()

    assert row is not None
    assert row["stock_status"] == "BAJO MINIMO"
    assert row["deficit"] == 2
