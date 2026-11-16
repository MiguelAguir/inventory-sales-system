-- Pregunta: que productos requieren reposicion y con que urgencia?
-- Tecnica: cruza stock, minimo configurado, cobertura de 30 dias y lead time.
SELECT
    warehouse_code   AS almacen,
    sku,
    product_name     AS producto,
    quantity         AS stock_actual,
    min_quantity     AS stock_minimo,
    deficit,
    avg_daily_units  AS venta_diaria_prom,
    coverage_days    AS dias_cobertura,
    lead_time_days   AS lead_time,
    priority         AS prioridad,
    reason           AS motivo,
    greatest(
        ceil(COALESCE(avg_daily_units, 0) * 30 + min_quantity - quantity),
        0
    )::integer AS cantidad_sugerida
FROM reporting.v_alertas_reposicion
ORDER BY
    CASE priority WHEN 'CRITICA' THEN 1 WHEN 'ALTA' THEN 2 ELSE 3 END,
    deficit DESC,
    coverage_days ASC NULLS LAST;
