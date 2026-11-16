"""Fixtures de pruebas.

Cada ejecucion crea una base `inventory_test` independiente, aplica el
esquema y trunca los datos entre pruebas. No toca la base `inventory` de
desarrollo ni los datos sembrados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from src.config import ROOT, settings
from src.db import apply_sql_file

TEST_DB = "inventory_test"
SCHEMA_FILES = sorted((ROOT / "sql" / "00_schema").glob("*.sql"))


def _params(dbname: str) -> dict[str, Any]:
    params = dict(settings.conninfo)
    params["dbname"] = dbname
    return params


def _admin_connect() -> psycopg.Connection:
    return psycopg.connect(
        **_params("postgres"),
        autocommit=True,
        row_factory=dict_row,
    )


@pytest.fixture(scope="session")
def test_database() -> None:
    try:
        admin = _admin_connect()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL no disponible en {settings.host}:{settings.port}: {exc}")

    identifier = sql.Identifier(TEST_DB)
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(identifier))
    admin.execute(sql.SQL("CREATE DATABASE {}").format(identifier))
    admin.close()
    yield
    admin = _admin_connect()
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(identifier))
    admin.close()


@pytest.fixture(scope="session")
def schema_ready(test_database: None) -> None:
    conn = psycopg.connect(**_params(TEST_DB), autocommit=True, row_factory=dict_row)
    try:
        for path in SCHEMA_FILES:
            apply_sql_file(conn, path)
        # Segunda aplicacion: valida idempotencia del DDL.
        for path in SCHEMA_FILES:
            apply_sql_file(conn, path)
    finally:
        conn.close()


@pytest.fixture(scope="session")
def db_factory(schema_ready: None) -> Callable[[], psycopg.Connection]:
    def factory() -> psycopg.Connection:
        return psycopg.connect(**_params(TEST_DB), autocommit=True, row_factory=dict_row)
    return factory


@pytest.fixture
def conn(db_factory: Callable[[], psycopg.Connection]) -> psycopg.Connection:
    connection = db_factory()
    connection.execute(
        """
        TRUNCATE TABLE
            core.stock_movements,
            core.sale_items,
            core.purchase_items,
            core.sales,
            core.purchases,
            core.stock_levels,
            core.product_suppliers,
            core.products,
            core.categories,
            core.customers,
            core.suppliers,
            core.warehouses,
            audit.quality_results
        RESTART IDENTITY CASCADE
        """
    )
    connection.execute("ALTER SEQUENCE core.sale_number_seq RESTART WITH 1")
    connection.execute("ALTER SEQUENCE core.purchase_number_seq RESTART WITH 1")
    yield connection
    connection.close()


@pytest.fixture
def base(conn: psycopg.Connection) -> dict[str, int]:
    category_id = conn.execute(
        "INSERT INTO core.categories (code, name) VALUES ('TEST', 'Categoria Test') RETURNING category_id"
    ).fetchone()["category_id"]
    warehouse_id = conn.execute(
        "INSERT INTO core.warehouses (code, name) VALUES ('WH-T', 'Almacen Test') RETURNING warehouse_id"
    ).fetchone()["warehouse_id"]
    supplier_id = conn.execute(
        """
        INSERT INTO core.suppliers (ruc, name, lead_time_days)
        VALUES ('20199999999', 'Proveedor Test S.A.C.', 5)
        RETURNING supplier_id
        """
    ).fetchone()["supplier_id"]
    product_id = conn.execute(
        """
        INSERT INTO core.products (
            sku, name, category_id, unit_price, unit_cost, min_stock
        )
        VALUES ('TEST-001', 'Producto Test', %s, 100.00, 60.00, 5)
        RETURNING product_id
        """,
        (category_id,),
    ).fetchone()["product_id"]
    conn.execute(
        """
        INSERT INTO core.product_suppliers (
            product_id, supplier_id, supplier_sku, unit_cost, lead_time_days, is_preferred
        )
        VALUES (%s, %s, 'SUP-TEST-001', 60.00, 5, true)
        """,
        (product_id, supplier_id),
    )
    customer_id = conn.execute(
        """
        INSERT INTO core.customers (doc_type, doc_number, name)
        VALUES ('DNI', '12345678', 'Cliente Test')
        RETURNING customer_id
        """
    ).fetchone()["customer_id"]

    # Saldo inicial: entra por el libro mayor, no se escribe stock_levels a mano.
    conn.execute(
        """
        INSERT INTO core.stock_movements (
            product_id, warehouse_id, movement_type, quantity_delta,
            unit_cost, reference_note
        )
        VALUES (%s, %s, 'ADJUSTMENT_IN', 10, 60.00, 'Saldo inicial de prueba')
        """,
        (product_id, warehouse_id),
    )

    return {
        "category_id": int(category_id),
        "warehouse_id": int(warehouse_id),
        "supplier_id": int(supplier_id),
        "product_id": int(product_id),
        "customer_id": int(customer_id),
    }


def stock_quantity(conn: psycopg.Connection, product_id: int, warehouse_id: int) -> int:
    row = conn.execute(
        """
        SELECT quantity FROM core.stock_levels
         WHERE product_id = %s AND warehouse_id = %s
        """,
        (product_id, warehouse_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def ledger_quantity(conn: psycopg.Connection, product_id: int, warehouse_id: int) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(sum(quantity_delta), 0) AS quantity
          FROM core.stock_movements
         WHERE product_id = %s AND warehouse_id = %s
        """,
        (product_id, warehouse_id),
    ).fetchone()
    return int(row["quantity"])


def register_sale(
    conn: psycopg.Connection,
    base: dict[str, int],
    quantity: int,
    *,
    unit_price: float = 100.0,
    discount_pct: float = 0.0,
) -> int:
    items = json.dumps([{
        "product_id": base["product_id"],
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_pct": discount_pct,
    }])
    row = conn.execute(
        "SELECT core.fn_register_sale(%s, %s, %s::jsonb, now()) AS sale_id",
        (base["customer_id"], base["warehouse_id"], items),
    ).fetchone()
    return int(row["sale_id"])


def register_purchase(
    conn: psycopg.Connection,
    base: dict[str, int],
    quantity: int,
    *,
    unit_cost: float = 60.0,
) -> int:
    items = json.dumps([{
        "product_id": base["product_id"],
        "quantity": quantity,
        "unit_cost": unit_cost,
    }])
    row = conn.execute(
        "SELECT core.fn_register_purchase(%s, %s, %s::jsonb, now()) AS purchase_id",
        (base["supplier_id"], base["warehouse_id"], items),
    ).fetchone()
    return int(row["purchase_id"])
