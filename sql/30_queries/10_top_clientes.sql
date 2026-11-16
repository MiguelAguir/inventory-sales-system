-- Pregunta: quienes son los mejores clientes y cuanto concentran?
-- Tecnica: ranking con participacion y suma acumulada; dias desde la ultima compra.
WITH base AS (
    SELECT
        s.customer_id,
        c.name AS customer_name,
        count(DISTINCT s.sale_id) AS orders,
        sum(si.line_subtotal)     AS revenue,
        min(s.sale_date)          AS first_sale_at,
        max(s.sale_date)          AS last_sale_at
      FROM core.sales s
      JOIN core.sale_items si ON si.sale_id = s.sale_id
      JOIN core.customers c   ON c.customer_id = s.customer_id
     WHERE s.status = 'CONFIRMED'
     GROUP BY 1, 2
)
SELECT
    rank() OVER (ORDER BY revenue DESC) AS ranking,
    customer_name AS cliente,
    orders        AS pedidos,
    revenue       AS ingresos,
    round(100 * revenue / NULLIF(sum(revenue) OVER (), 0), 2) AS pct_total,
    round(
        100 * sum(revenue) OVER (
            ORDER BY revenue DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) / NULLIF(sum(revenue) OVER (), 0),
        2
    ) AS pct_acumulado,
    (current_date - last_sale_at::date) AS dias_sin_comprar
FROM base
ORDER BY ranking
LIMIT 25;
