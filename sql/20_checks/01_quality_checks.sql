-- 20_checks/01_quality_checks.sql
-- Controles de calidad ejecutables. Devuelve una fila por control.
-- El CLI guarda el resultado en audit.quality_results.

WITH sales_mismatch AS (
    SELECT s.sale_id
      FROM core.sales s
      JOIN (
          SELECT sale_id, sum(line_subtotal) AS subtotal
            FROM core.sale_items
           GROUP BY sale_id
      ) x ON x.sale_id = s.sale_id
     WHERE s.status = 'CONFIRMED'
       AND (
           s.subtotal <> x.subtotal
           OR s.tax <> round(x.subtotal * core.fn_igv_rate(), 2)
           OR s.total <> x.subtotal + round(x.subtotal * core.fn_igv_rate(), 2)
       )
),
purchase_mismatch AS (
    SELECT p.purchase_id
      FROM core.purchases p
      JOIN (
          SELECT purchase_id, sum(line_subtotal) AS subtotal
            FROM core.purchase_items
           GROUP BY purchase_id
      ) x ON x.purchase_id = p.purchase_id
     WHERE p.status = 'CONFIRMED'
       AND (
           p.subtotal <> x.subtotal
           OR p.tax <> round(x.subtotal * core.fn_igv_rate(), 2)
           OR p.total <> x.subtotal + round(x.subtotal * core.fn_igv_rate(), 2)
       )
),
stock_mismatch AS (
    SELECT COALESCE(sl.product_id, mv.product_id) AS product_id,
           COALESCE(sl.warehouse_id, mv.warehouse_id) AS warehouse_id,
           COALESCE(sl.quantity, 0) AS stock_quantity,
           COALESCE(mv.quantity, 0) AS ledger_quantity
      FROM core.stock_levels sl
      FULL JOIN (
          SELECT product_id, warehouse_id, sum(quantity_delta) AS quantity
            FROM core.stock_movements
           GROUP BY 1, 2
      ) mv ON mv.product_id = sl.product_id
          AND mv.warehouse_id = sl.warehouse_id
     WHERE COALESCE(sl.quantity, 0) <> COALESCE(mv.quantity, 0)
),
missing_sale_posting AS (
    SELECT s.sale_id
      FROM core.sales s
     WHERE s.status IN ('CONFIRMED', 'CANCELLED')
       AND EXISTS (SELECT 1 FROM core.sale_items si WHERE si.sale_id = s.sale_id)
       AND NOT EXISTS (
           SELECT 1 FROM core.stock_movements sm
            WHERE sm.sale_id = s.sale_id
              AND sm.movement_type = 'SALE'
       )
),
missing_cancel_posting AS (
    SELECT s.sale_id
      FROM core.sales s
     WHERE s.status = 'CANCELLED'
       AND EXISTS (SELECT 1 FROM core.sale_items si WHERE si.sale_id = s.sale_id)
       AND NOT EXISTS (
           SELECT 1 FROM core.stock_movements sm
            WHERE sm.sale_id = s.sale_id
              AND sm.movement_type = 'SALE_CANCEL'
       )
),
missing_purchase_posting AS (
    SELECT p.purchase_id
      FROM core.purchases p
     WHERE p.status IN ('CONFIRMED', 'CANCELLED')
       AND EXISTS (SELECT 1 FROM core.purchase_items pi WHERE pi.purchase_id = p.purchase_id)
       AND NOT EXISTS (
           SELECT 1 FROM core.stock_movements sm
            WHERE sm.purchase_id = p.purchase_id
              AND sm.movement_type = 'PURCHASE'
       )
),
duplicate_lines AS (
    SELECT sale_id, product_id
      FROM core.sale_items
     GROUP BY 1, 2
    HAVING count(*) > 1
),
abc_counts AS (
    SELECT abc_class, count(*) AS products
      FROM reporting.v_abc_productos
     GROUP BY abc_class
)
SELECT 'Ventas: totales cuadran con lineas' AS check_name,
       (SELECT count(*) = 0 FROM sales_mismatch) AS passed,
       (SELECT count(*)::text FROM sales_mismatch) || ' ventas con diferencia' AS detail
UNION ALL
SELECT 'Compras: totales cuadran con lineas',
       (SELECT count(*) = 0 FROM purchase_mismatch),
       (SELECT count(*)::text FROM purchase_mismatch) || ' compras con diferencia'
UNION ALL
SELECT 'Inventario: saldo = suma del libro mayor',
       (SELECT count(*) = 0 FROM stock_mismatch),
       (SELECT count(*)::text FROM stock_mismatch) || ' combinaciones producto/almacen descuadradas'
UNION ALL
SELECT 'Inventario: no hay saldos negativos',
       (SELECT count(*) = 0 FROM core.stock_levels WHERE quantity < 0),
       (SELECT count(*)::text FROM core.stock_levels WHERE quantity < 0) || ' saldos negativos'
UNION ALL
SELECT 'Ventas confirmadas tienen movimientos SALE',
       (SELECT count(*) = 0 FROM missing_sale_posting),
       (SELECT count(*)::text FROM missing_sale_posting) || ' ventas sin posteo'
UNION ALL
SELECT 'Ventas canceladas tienen reversa SALE_CANCEL',
       (SELECT count(*) = 0 FROM missing_cancel_posting),
       (SELECT count(*)::text FROM missing_cancel_posting) || ' ventas sin reversa'
UNION ALL
SELECT 'Compras confirmadas tienen movimientos PURCHASE',
       (SELECT count(*) = 0 FROM missing_purchase_posting),
       (SELECT count(*)::text FROM missing_purchase_posting) || ' compras sin posteo'
UNION ALL
SELECT 'Ventas: una linea por producto',
       (SELECT count(*) = 0 FROM duplicate_lines),
       (SELECT count(*)::text FROM duplicate_lines) || ' lineas duplicadas'
UNION ALL
SELECT 'Ventas confirmadas con total positivo',
       (SELECT count(*) = 0 FROM core.sales WHERE status = 'CONFIRMED' AND total <= 0),
       (SELECT count(*)::text FROM core.sales WHERE status = 'CONFIRMED' AND total <= 0) || ' ventas con total no positivo'
UNION ALL
SELECT 'Fechas de venta no futuras',
       (SELECT count(*) = 0 FROM core.sales WHERE status = 'CONFIRMED' AND sale_date > now() + interval '1 day'),
       (SELECT count(*)::text FROM core.sales WHERE status = 'CONFIRMED' AND sale_date > now() + interval '1 day') || ' ventas futuras'
UNION ALL
SELECT 'ABC: las tres clases tienen productos',
       (SELECT count(*) = 3 FROM abc_counts),
       COALESCE((SELECT string_agg(abc_class || '=' || products, ', ' ORDER BY abc_class) FROM abc_counts), 'sin datos')
UNION ALL
SELECT 'Configuracion: tasa IGV valida',
       (SELECT count(*) = 1 FROM core.settings WHERE setting_key = 'igv_rate' AND setting_value > 0 AND setting_value < 1),
       COALESCE((SELECT setting_value::text FROM core.settings WHERE setting_key = 'igv_rate'), 'no configurada')
UNION ALL
SELECT 'Libro mayor: trigger de inmutabilidad activo',
       (SELECT count(*) >= 1 FROM pg_trigger
         WHERE tgname = 'trg_stock_movements_immutable' AND NOT tgisinternal),
       (SELECT count(*)::text FROM pg_trigger
         WHERE tgname = 'trg_stock_movements_immutable' AND NOT tgisinternal) || ' trigger(s)'
ORDER BY check_name;
