-- Pregunta: hay estacionalidad en las ventas?
-- Tecnica: promedio historico por mes calendario e indice contra el promedio general.
WITH monthly AS (
    SELECT month, revenue
      FROM reporting.v_ventas_mensuales
), avg_all AS (
    SELECT avg(revenue) AS avg_revenue FROM monthly
)
SELECT
    extract(month FROM month)::integer AS mes,
    count(*) AS anios,
    round(avg(revenue), 2) AS ingreso_promedio,
    round(min(revenue), 2) AS ingreso_minimo,
    round(max(revenue), 2) AS ingreso_maximo,
    round(avg(revenue) / NULLIF((SELECT avg_revenue FROM avg_all), 0) * 100, 2) AS indice_estacional
FROM monthly
GROUP BY 1
ORDER BY 1;
