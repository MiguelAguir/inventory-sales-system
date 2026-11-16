-- Pregunta: cuantas veces rota el inventario por categoria en los ultimos 12 meses?
-- Tecnica: COGS / inventario promedio. El inventario inicial y final se
-- reconstruye desde el libro mayor con reporting.fn_inventory_value_at().
WITH bounds AS (
    SELECT
        date_trunc('month', now()) - interval '12 months' AS start_at,
        now()                                              AS end_at
), cogs AS (
    SELECT
        p.category_id,
        sum(si.line_cost) AS cogs_12m
      FROM core.sales s
      JOIN core.sale_items si ON si.sale_id = s.sale_id
      JOIN core.products p    ON p.product_id = si.product_id
     WHERE s.status = 'CONFIRMED'
       AND s.sale_date >= (SELECT start_at FROM bounds)
       AND s.sale_date <  (SELECT end_at FROM bounds)
     GROUP BY 1
), inv_start AS (
    SELECT * FROM reporting.fn_inventory_value_at((SELECT start_at FROM bounds))
), inv_end AS (
    SELECT * FROM reporting.fn_inventory_value_at((SELECT end_at FROM bounds))
)
SELECT
    c.name AS categoria,
    round(COALESCE(k.cogs_12m, 0), 2) AS cogs_12m,
    round(COALESCE(i0.inventory_value, 0), 2) AS inventario_inicial,
    round(COALESCE(i1.inventory_value, 0), 2) AS inventario_final,
    round((COALESCE(i0.inventory_value, 0) + COALESCE(i1.inventory_value, 0)) / 2, 2) AS inventario_promedio,
    round(
        COALESCE(k.cogs_12m, 0)
        / NULLIF((COALESCE(i0.inventory_value, 0) + COALESCE(i1.inventory_value, 0)) / 2, 0),
        2
    ) AS rotacion_anual,
    round(
        365 / NULLIF(
            COALESCE(k.cogs_12m, 0)
            / NULLIF((COALESCE(i0.inventory_value, 0) + COALESCE(i1.inventory_value, 0)) / 2, 0),
            0
        ),
        1
    ) AS dias_inventario
FROM core.categories c
LEFT JOIN cogs k      ON k.category_id = c.category_id
LEFT JOIN inv_start i0 ON i0.category_id = c.category_id
LEFT JOIN inv_end i1   ON i1.category_id = c.category_id
ORDER BY rotacion_anual DESC NULLS LAST;
