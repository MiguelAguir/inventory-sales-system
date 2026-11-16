-- Pregunta: como se distribuye el ingreso entre las clases A, B y C?
-- Tecnica: clasificacion ABC por participacion acumulada (Pareto 80/15/5).
WITH base AS (
    SELECT * FROM reporting.v_abc_productos
)
SELECT
    abc_class AS clase,
    count(*)  AS productos,
    sum(units) AS unidades,
    round(sum(revenue), 2) AS ingresos,
    round(100 * sum(revenue) / NULLIF((SELECT sum(revenue) FROM base), 0), 2) AS pct_ingresos,
    round(100 * sum(gross_margin) / NULLIF(sum(revenue), 0), 2) AS margen_pct
FROM base
GROUP BY abc_class
ORDER BY abc_class;
