"""Pruebas de estructura del esquema."""

from __future__ import annotations


def test_core_tables_exist(conn) -> None:
    expected = {
        "categories", "warehouses", "suppliers", "products", "product_suppliers",
        "customers", "sales", "sale_items", "purchases", "purchase_items",
        "stock_levels", "stock_movements", "settings",
    }
    rows = conn.execute(
        """
        SELECT table_name
          FROM information_schema.tables
         WHERE table_schema = 'core' AND table_type = 'BASE TABLE'
        """
    ).fetchall()
    assert expected.issubset({row["table_name"] for row in rows})


def test_reporting_views_exist(conn) -> None:
    expected = {
        "v_stock_actual", "v_bajo_minimo", "v_alertas_reposicion", "v_stock_muerto",
        "v_ventas_mensuales", "v_ventas_categoria_mes", "v_ranking_productos",
        "v_abc_productos", "v_proveedores_compras", "v_rotacion_actual",
    }
    rows = conn.execute(
        """
        SELECT table_name
          FROM information_schema.views
         WHERE table_schema = 'reporting'
        """
    ).fetchall()
    assert expected.issubset({row["table_name"] for row in rows})


def test_triggers_and_idempotency_indexes(conn) -> None:
    triggers = {
        row["tgname"]
        for row in conn.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"
        ).fetchall()
    }
    assert {
        "trg_stock_movements_apply",
        "trg_stock_movements_immutable",
        "trg_sale_items_guard",
        "trg_sale_items_totals",
        "trg_sales_guard",
        "trg_purchases_guard",
    }.issubset(triggers)

    indexes = {
        row["indexname"]
        for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'core'"
        ).fetchall()
    }
    assert "ux_stock_movements_sale" in indexes
    assert "ux_stock_movements_purchase" in indexes
    assert "ux_product_suppliers_one_preferred" in indexes


def test_generated_columns(conn) -> None:
    rows = conn.execute(
        """
        SELECT column_name, is_generated
          FROM information_schema.columns
         WHERE table_schema = 'core'
           AND table_name IN ('sale_items', 'purchase_items')
           AND is_generated = 'ALWAYS'
        """
    ).fetchall()
    generated = {row["column_name"] for row in rows}
    assert {"line_subtotal", "line_cost"}.issubset(generated)


def test_enums(conn) -> None:
    values = {
        row["enumlabel"]
        for row in conn.execute(
            """
            SELECT e.enumlabel
              FROM pg_enum e
              JOIN pg_type t ON t.oid = e.enumtypid
              JOIN pg_namespace n ON n.oid = t.typnamespace
             WHERE n.nspname = 'core' AND t.typname = 'movement_type'
            """
        ).fetchall()
    }
    assert {"SALE", "SALE_CANCEL", "PURCHASE", "PURCHASE_CANCEL", "ADJUSTMENT_IN"}.issubset(values)
