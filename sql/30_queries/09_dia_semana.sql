-- Pregunta: en que dias de la semana se vende mas y cual es el ticket promedio?
-- Tecnica: agregacion por dia de la semana sobre ventas confirmadas.
WITH base AS (
    SELECT
        s.sale_id,
        s.sale_date,
        sum(si.line_subtotal) AS revenue
      FROM core.sales s
      JOIN core.sale_items si ON si.sale_id = s.sale_id
     WHERE s.status = 'CONFIRMED'
     GROUP BY s.sale_id, s.sale_date
)
SELECT
    extract(dow FROM sale_date)::integer AS dow,
    CASE extract(dow FROM sale_date)
        WHEN 0 THEN 'Domingo'
        WHEN 1 THEN 'Lunes'
        WHEN 2 THEN 'Martes'
        WHEN 3 THEN 'Miercoles'
        WHEN 4 THEN 'Jueves'
        WHEN 5 THEN 'Viernes'
        WHEN 6 THEN 'Sabado'
    END AS dia,
    count(*) AS transacciones,
    round(sum(revenue), 2) AS ingresos,
    round(avg(revenue), 2) AS ticket_promedio
FROM base
GROUP BY 1, 2
ORDER BY 1;
