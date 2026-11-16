"""Prueba de concurrencia: dos ventas compiten por la ultima unidad."""

from __future__ import annotations

import threading
from typing import Callable

import psycopg

from tests.conftest import register_sale, stock_quantity


def test_last_unit_can_only_be_sold_once(db_factory: Callable[[], psycopg.Connection], base) -> None:
    setup = db_factory()
    try:
        # Deja exactamente 1 unidad en stock.
        register_sale(setup, base, 9)
        assert stock_quantity(setup, base["product_id"], base["warehouse_id"]) == 1
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[str] = []

    def worker() -> None:
        connection = db_factory()
        try:
            barrier.wait(timeout=10)
            register_sale(connection, base, 1)
            results.append("ok")
        except psycopg.Error as exc:
            errors.append(exc.diag.message_primary or str(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert results == ["ok"], f"Se esperaba exactamente una venta exitosa; errores: {errors}"
    assert len(errors) == 1
    assert "Stock insuficiente" in errors[0]

    check = db_factory()
    try:
        assert stock_quantity(check, base["product_id"], base["warehouse_id"]) == 0
        sale_movements = check.execute(
            """
            SELECT count(*) AS n
              FROM core.stock_movements
             WHERE product_id = %s
               AND warehouse_id = %s
               AND movement_type = 'SALE'
            """,
            (base["product_id"], base["warehouse_id"]),
        ).fetchone()["n"]
        assert sale_movements == 2  # la venta de 9 y la unica venta de 1 que gano
    finally:
        check.close()
