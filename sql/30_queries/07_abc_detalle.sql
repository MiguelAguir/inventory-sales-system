-- Pregunta: que productos de clase A sostienen el negocio?
-- Tecnica: detalle del Pareto con participacion individual y acumulada.
SELECT
    abc_class          AS clase,
    sku,
    product_name       AS producto,
    category_name      AS categoria,
    units              AS unidades,
    revenue            AS ingresos,
    gross_margin       AS margen,
    revenue_share_pct  AS pct_ingresos,
    cumulative_share_pct AS pct_acumulado
FROM reporting.v_abc_productos
WHERE abc_class = 'A'
ORDER BY revenue DESC
LIMIT 20;
