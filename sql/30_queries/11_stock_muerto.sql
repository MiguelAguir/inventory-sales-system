-- Pregunta: cuanto capital esta inmovilizado en productos sin ventas recientes?
-- Tecnica: stock valorizado sin movimientos SALE en los ultimos 90 dias.
SELECT
    warehouse_code AS almacen,
    sku,
    product_name   AS producto,
    category_name  AS categoria,
    quantity       AS stock_actual,
    stock_value    AS valor_inmovilizado,
    last_sale_at   AS ultima_venta,
    COALESCE((current_date - last_sale_at::date), 9999) AS dias_sin_venta
FROM reporting.v_stock_muerto
ORDER BY valor_inmovilizado DESC;
