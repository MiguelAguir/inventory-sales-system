-- Pregunta: que proveedores concentran mas compras y cuanto representan?
-- Tecnica: ranking con participacion y suma acumulada (Pareto).
SELECT
    amount_rank       AS ranking,
    supplier_name     AS proveedor,
    ruc,
    purchases         AS compras,
    units             AS unidades,
    amount            AS monto,
    amount_share_pct  AS pct_total,
    avg_ticket        AS ticket_promedio,
    round(
        100 * sum(amount) OVER (
            ORDER BY amount DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) / NULLIF(sum(amount) OVER (), 0),
        2
    ) AS pct_acumulado,
    last_purchase_at  AS ultima_compra
FROM reporting.v_proveedores_compras
ORDER BY ranking;
