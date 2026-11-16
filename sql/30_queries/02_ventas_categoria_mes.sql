-- Pregunta: como evolucionan las ventas por categoria y que categorias crecen?
-- Tecnica: LAG() para variacion mes a mes y año contra año.
WITH base AS (
    SELECT *
      FROM reporting.v_ventas_categoria_mes
     WHERE month >= ((SELECT max(month) FROM reporting.v_ventas_mensuales) - interval '23 months')::date
), calc AS (
    SELECT
        *,
        lag(revenue) OVER (PARTITION BY category_id ORDER BY month)     AS prev_revenue,
        lag(revenue, 12) OVER (PARTITION BY category_id ORDER BY month) AS prev_year_revenue
    FROM base
)
SELECT
    month             AS mes,
    category_name     AS categoria,
    units             AS unidades,
    revenue           AS ingresos,
    round(revenue - cogs, 2) AS margen,
    revenue_share_pct AS pct_mes,
    round(100 * (revenue - prev_revenue) / NULLIF(prev_revenue, 0), 2) AS var_mom_pct,
    round(100 * (revenue - prev_year_revenue) / NULLIF(prev_year_revenue, 0), 2) AS var_yoy_pct
FROM calc
ORDER BY mes, ingresos DESC;
