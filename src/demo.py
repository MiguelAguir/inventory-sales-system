"""Demostracion guiada del flujo de inventario.

Muestra, contra la base real:
  1. saldo antes de vender,
  2. una venta confirmada y su descuento de stock,
  3. la cancelacion y la reversa,
  4. el rechazo de una venta sin stock,
  5. la conciliacion saldo vs libro mayor.
"""

from __future__ import annotations

import json

import psycopg

from .db import fetch_all, fetch_one


def _stock(conn: psycopg.Connection, product_id: int, warehouse_id: int) -> int:
    row = fetch_one(
        conn,
        """
        SELECT quantity
          FROM core.stock_levels
         WHERE product_id = %s AND warehouse_id = %s
        """,
        (product_id, warehouse_id),
    )
    return int(row["quantity"]) if row else 0


def _ledger(conn: psycopg.Connection, product_id: int, warehouse_id: int) -> int:
    row = fetch_one(
        conn,
        """
        SELECT COALESCE(sum(quantity_delta), 0) AS quantity
          FROM core.stock_movements
         WHERE product_id = %s AND warehouse_id = %s
        """,
        (product_id, warehouse_id),
    )
    return int(row["quantity"]) if row else 0


def _ensure_demo_customer(conn: psycopg.Connection) -> int:
    row = fetch_one(
        conn,
        "SELECT customer_id FROM core.customers WHERE doc_type = 'DNI' AND doc_number = '99999999'",
    )
    if row:
        return int(row["customer_id"])
    created = conn.execute(
        """
        INSERT INTO core.customers (doc_type, doc_number, name, email)
        VALUES ('DNI', '99999999', 'Cliente Demo (sintetico)', 'demo@example.com')
        RETURNING customer_id
        """
    ).fetchone()
    conn.commit()
    return int(created["customer_id"])


def run_demo(conn: psycopg.Connection) -> None:
    from .pipeline import print_rows

    target = fetch_one(
        conn,
        """
        SELECT
            sl.product_id,
            sl.warehouse_id,
            sl.quantity,
            p.sku,
            p.name AS product_name,
            p.unit_price,
            w.code AS warehouse_code
          FROM core.stock_levels sl
          JOIN core.products p   ON p.product_id = sl.product_id
          JOIN core.warehouses w ON w.warehouse_id = sl.warehouse_id
         WHERE sl.quantity >= 5
           AND p.is_active
         ORDER BY sl.quantity DESC
         LIMIT 1
        """,
    )
    if not target:
        print("No hay stock suficiente para la demo. Ejecute primero: python -m src.pipeline seed --reset")
        return

    product_id = int(target["product_id"])
    warehouse_id = int(target["warehouse_id"])
    customer_id = _ensure_demo_customer(conn)

    print("=" * 72)
    print("DEMO: ciclo venta -> stock -> cancelacion -> reversa")
    print("=" * 72)
    print(f"Producto : {target['sku']} - {target['product_name']}")
    print(f"Almacen  : {target['warehouse_code']}")
    print(f"Precio   : S/ {target['unit_price']:.2f}")

    before = _stock(conn, product_id, warehouse_id)
    ledger_before = _ledger(conn, product_id, warehouse_id)
    print(f"\nStock antes de vender : {before} unidades")
    print(f"Suma del libro mayor  : {ledger_before} unidades (deben coincidir)")

    items = [{
        "product_id": product_id,
        "quantity": 5,
        "unit_price": float(target["unit_price"]),
        "discount_pct": 5,
    }]
    sale = conn.execute(
        "SELECT core.fn_register_sale(%s, %s, %s::jsonb, now()) AS sale_id",
        (customer_id, warehouse_id, json.dumps(items)),
    ).fetchone()
    conn.commit()
    sale_id = int(sale["sale_id"])

    sale_row = fetch_one(
        conn,
        """
        SELECT sale_number, status, subtotal, tax, total
          FROM core.sales WHERE sale_id = %s
        """,
        (sale_id,),
    )
    after_sale = _stock(conn, product_id, warehouse_id)
    print(f"\nVenta registrada: {sale_row['sale_number']} ({sale_row['status']})")
    print(f"  subtotal S/ {sale_row['subtotal']:.2f} | IGV S/ {sale_row['tax']:.2f} | total S/ {sale_row['total']:.2f}")
    print(f"  stock despues de vender: {after_sale} unidades (esperado {before - 5})")
    print(f"  suma del libro mayor   : {_ledger(conn, product_id, warehouse_id)} unidades")

    conn.execute("SELECT core.fn_cancel_sale(%s, now())", (sale_id,))
    conn.commit()
    sale_row = fetch_one(
        conn,
        "SELECT status FROM core.sales WHERE sale_id = %s",
        (sale_id,),
    )
    after_cancel = _stock(conn, product_id, warehouse_id)
    print(f"\nVenta cancelada: estado {sale_row['status']}")
    print(f"  stock despues de cancelar: {after_cancel} unidades (esperado {before})")
    print(f"  suma del libro mayor     : {_ledger(conn, product_id, warehouse_id)} unidades")

    print("\nMovimientos generados por esta venta:")
    movements = fetch_all(
        conn,
        """
        SELECT movement_id, movement_type, quantity_delta,
               occurred_at::date AS fecha, reference_note
          FROM core.stock_movements
         WHERE sale_id = %s
         ORDER BY movement_id
        """,
        (sale_id,),
    )
    print_rows(movements, limit=20)

    print("\nPrueba de stock insuficiente (debe fallar y no alterar el saldo):")
    impossible = [{
        "product_id": product_id,
        "quantity": after_cancel + 1000,
        "unit_price": float(target["unit_price"]),
        "discount_pct": 0,
    }]
    try:
        conn.execute(
            "SELECT core.fn_register_sale(%s, %s, %s::jsonb, now())",
            (customer_id, warehouse_id, json.dumps(impossible)),
        )
        conn.commit()
        print("  ERROR: la venta imposible fue aceptada")
    except psycopg.Error as exc:
        conn.rollback()
        message = exc.diag.message_primary or str(exc)
        print(f"  rechazada correctamente: {message}")
        print(f"  stock intacto: {_stock(conn, product_id, warehouse_id)} unidades")

    mismatch = fetch_one(
        conn,
        """
        SELECT count(*) AS n
          FROM core.stock_levels sl
          FULL JOIN (
              SELECT product_id, warehouse_id, sum(quantity_delta) AS quantity
                FROM core.stock_movements
               GROUP BY 1, 2
          ) mv USING (product_id, warehouse_id)
         WHERE COALESCE(sl.quantity, 0) <> COALESCE(mv.quantity, 0)
        """,
    )
    print(f"\nConciliacion global saldo vs libro mayor: {mismatch['n']} diferencias")

    alerts = fetch_one(
        conn,
        "SELECT count(*) AS n FROM reporting.v_alertas_reposicion",
    )
    print(f"Alertas de reposicion activas: {alerts['n']}")
    print("\nDemo completada.")
