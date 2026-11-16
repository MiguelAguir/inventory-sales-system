-- Pregunta: que productos lideran las ventas de cada mes y cuanto concentran?
-- Tecnica: vista con RANK() y suma acumulada por particion mensual.
WITH ranked AS (
    SELECT *
      FROM reporting.v_ranking_productos
     WHERE month >= ((SELECT max(month) FROM reporting.v_ventas_mensuales) - interval '11 months')::date
)
SELECT
    month              AS mes,
    revenue_rank       AS ranking,
    sku,
    product_name       AS producto,
    units              AS unidades,
    revenue            AS ingresos,
    revenue_share_pct  AS pct_mes,
    cumulative_share_pct AS pct_acumulado
FROM ranked
WHERE revenue_rank <= 10
ORDER BY mes DESC, ranking;
