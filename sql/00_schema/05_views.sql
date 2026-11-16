-- 05_views.sql
-- Vistas de solo lectura para analitica, dashboards y consultas de negocio.
-- No contienen logica de escritura.

-- ---------------------------------------------------------------------------
-- Inventario
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW reporting.v_stock_actual AS
SELECT
    w.warehouse_id,
    w.code  AS warehouse_code,
    w.name  AS warehouse_name,
    p.product_id,
    p.sku,
    p.name  AS product_name,
    p.is_active,
    c.category_id,
    c.name  AS category_name,
    sl.quantity,
    sl.min_quantity,
    (sl.quantity - sl.min_quantity) AS surplus,
    CASE
        WHEN sl.quantity = 0 THEN 'SIN STOCK'
        WHEN sl.quantity <= sl.min_quantity THEN 'BAJO MINIMO'
        ELSE 'OK'
    END AS stock_status,
    p.unit_cost,
    round(sl.quantity * p.unit_cost, 2) AS stock_value,
    gl.units_30d,
    round(gl.units_30d / 30.0, 2) AS avg_daily_units,
    CASE
        WHEN gl.units_30d = 0 THEN NULL
        ELSE round(sl.quantity / (gl.units_30d / 30.0), 1)
    END AS coverage_days,
    sl.updated_at
FROM core.stock_levels sl
JOIN core.products p   ON p.product_id = sl.product_id
JOIN core.categories c ON c.category_id = p.category_id
JOIN core.warehouses w ON w.warehouse_id = sl.warehouse_id
LEFT JOIN LATERAL (
    SELECT COALESCE(SUM(
        CASE WHEN sm.movement_type IN ('SALE', 'SALE_CANCEL') THEN -sm.quantity_delta END
    ), 0)::numeric AS units_30d
      FROM core.stock_movements sm
     WHERE sm.product_id = sl.product_id
       AND sm.warehouse_id = sl.warehouse_id
       AND sm.occurred_at >= now() - interval '30 days'
) gl ON true;

COMMENT ON VIEW reporting.v_stock_actual IS
    'Saldo por producto/almacen, valorizado a costo estandar y con cobertura de 30 dias.';

CREATE OR REPLACE VIEW reporting.v_bajo_minimo AS
SELECT
    s.*,
    greatest(s.min_quantity - s.quantity, 0) AS deficit
FROM reporting.v_stock_actual s
WHERE s.quantity <= s.min_quantity
  AND s.is_active;

CREATE OR REPLACE VIEW reporting.v_alertas_reposicion AS
SELECT
    s.*,
    ps.lead_time_days,
    ps.supplier_name,
    CASE
        WHEN s.quantity = 0 THEN 'CRITICA'
        WHEN s.quantity <= s.min_quantity THEN 'ALTA'
        ELSE 'MEDIA'
    END AS priority,
    CASE
        WHEN s.quantity = 0 THEN 'Reponer de inmediato: sin stock.'
        WHEN s.coverage_days IS NOT NULL AND ps.lead_time_days IS NOT NULL
             AND s.coverage_days <= ps.lead_time_days
            THEN 'La cobertura no cubre el lead time del proveedor.'
        ELSE 'Saldo en o por debajo del minimo configurado.'
    END AS reason,
    greatest(s.min_quantity - s.quantity, 0) AS deficit
FROM reporting.v_stock_actual s
LEFT JOIN LATERAL (
    SELECT sup.lead_time_days, sup.name AS supplier_name
      FROM core.product_suppliers ps
      JOIN core.suppliers sup ON sup.supplier_id = ps.supplier_id
     WHERE ps.product_id = s.product_id
     ORDER BY ps.is_preferred DESC, ps.lead_time_days ASC
     LIMIT 1
) ps ON true
WHERE s.is_active
  AND (
      s.quantity <= s.min_quantity
      OR (s.coverage_days IS NOT NULL
          AND ps.lead_time_days IS NOT NULL
          AND s.coverage_days <= ps.lead_time_days)
  );

CREATE OR REPLACE VIEW reporting.v_stock_muerto AS
SELECT
    s.*,
    ls.last_sale_at,
    round(s.stock_value, 2) AS immobilized_value
FROM reporting.v_stock_actual s
LEFT JOIN LATERAL (
    SELECT max(sm.occurred_at) AS last_sale_at
      FROM core.stock_movements sm
     WHERE sm.product_id = s.product_id
       AND sm.warehouse_id = s.warehouse_id
       AND sm.movement_type = 'SALE'
) ls ON true
WHERE s.is_active
  AND s.quantity > 0
  AND (ls.last_sale_at IS NULL OR ls.last_sale_at < now() - interval '90 days');

-- ---------------------------------------------------------------------------
-- Ventas
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW reporting.v_ventas_mensuales AS
WITH base AS (
    SELECT
        date_trunc('month', s.sale_date)::date AS month,
        count(DISTINCT s.sale_id)      AS sales_count,
        count(DISTINCT s.customer_id)  AS customers,
        sum(si.quantity)               AS units,
        sum(si.line_subtotal)          AS revenue,
        sum(si.line_cost)              AS cogs
      FROM core.sales s
      JOIN core.sale_items si ON si.sale_id = s.sale_id
     WHERE s.status = 'CONFIRMED'
     GROUP BY 1
)
SELECT
    month,
    sales_count,
    customers,
    units,
    revenue,
    cogs,
    round(revenue - cogs, 2) AS gross_margin,
    round(100 * (revenue - cogs) / NULLIF(revenue, 0), 2) AS margin_pct,
    round(revenue / NULLIF(sales_count, 0), 2) AS avg_ticket
FROM base;

CREATE OR REPLACE VIEW reporting.v_ventas_categoria_mes AS
WITH base AS (
    SELECT
        date_trunc('month', s.sale_date)::date AS month,
        p.category_id,
        c.name AS category_name,
        sum(si.quantity)      AS units,
        sum(si.line_subtotal) AS revenue,
        sum(si.line_cost)     AS cogs
      FROM core.sales s
      JOIN core.sale_items si ON si.sale_id = s.sale_id
      JOIN core.products p    ON p.product_id = si.product_id
      JOIN core.categories c  ON c.category_id = p.category_id
     WHERE s.status = 'CONFIRMED'
     GROUP BY 1, 2, 3
)
SELECT
    month,
    category_id,
    category_name,
    units,
    revenue,
    cogs,
    round(revenue - cogs, 2) AS gross_margin,
    round(100 * revenue / sum(revenue) OVER (PARTITION BY month), 2) AS revenue_share_pct
FROM base;

CREATE OR REPLACE VIEW reporting.v_ranking_productos AS
WITH base AS (
    SELECT
        date_trunc('month', s.sale_date)::date AS month,
        p.product_id,
        p.sku,
        p.name AS product_name,
        sum(si.quantity)      AS units,
        sum(si.line_subtotal) AS revenue,
        sum(si.line_cost)     AS cogs
      FROM core.sales s
      JOIN core.sale_items si ON si.sale_id = s.sale_id
      JOIN core.products p    ON p.product_id = si.product_id
     WHERE s.status = 'CONFIRMED'
     GROUP BY 1, 2, 3, 4
)
SELECT
    month,
    product_id,
    sku,
    product_name,
    units,
    revenue,
    round(revenue - cogs, 2) AS gross_margin,
    rank() OVER (PARTITION BY month ORDER BY revenue DESC) AS revenue_rank,
    round(100 * revenue / sum(revenue) OVER (PARTITION BY month), 2) AS revenue_share_pct,
    round(
        100 * sum(revenue) OVER (
            PARTITION BY month ORDER BY revenue DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) / sum(revenue) OVER (PARTITION BY month),
        2
    ) AS cumulative_share_pct
FROM base;

CREATE OR REPLACE VIEW reporting.v_abc_productos AS
WITH base AS (
    SELECT
        p.product_id,
        p.sku,
        p.name AS product_name,
        c.name AS category_name,
        sum(si.quantity)      AS units,
        sum(si.line_subtotal) AS revenue,
        sum(si.line_cost)     AS cogs
      FROM core.sales s
      JOIN core.sale_items si ON si.sale_id = s.sale_id
      JOIN core.products p    ON p.product_id = si.product_id
      JOIN core.categories c  ON c.category_id = p.category_id
     WHERE s.status = 'CONFIRMED'
     GROUP BY 1, 2, 3, 4
), ranked AS (
    SELECT
        *,
        sum(revenue) OVER () AS total_revenue,
        sum(revenue) OVER (
            ORDER BY revenue DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_revenue
    FROM base
)
SELECT
    product_id,
    sku,
    product_name,
    category_name,
    units,
    revenue,
    round(revenue - cogs, 2) AS gross_margin,
    round(100 * revenue / NULLIF(total_revenue, 0), 2) AS revenue_share_pct,
    round(100 * cumulative_revenue / NULLIF(total_revenue, 0), 2) AS cumulative_share_pct,
    CASE
        WHEN (cumulative_revenue - revenue) / NULLIF(total_revenue, 0) < 0.80 THEN 'A'
        WHEN (cumulative_revenue - revenue) / NULLIF(total_revenue, 0) < 0.95 THEN 'B'
        ELSE 'C'
    END AS abc_class
FROM ranked;

-- ---------------------------------------------------------------------------
-- Compras y rotacion
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW reporting.v_proveedores_compras AS
WITH base AS (
    SELECT
        sup.supplier_id,
        sup.ruc,
        sup.name AS supplier_name,
        count(DISTINCT pu.purchase_id) AS purchases,
        sum(pi.quantity)               AS units,
        sum(pi.line_subtotal)          AS amount,
        max(pu.purchase_date)          AS last_purchase_at
      FROM core.purchases pu
      JOIN core.purchase_items pi ON pi.purchase_id = pu.purchase_id
      JOIN core.suppliers sup     ON sup.supplier_id = pu.supplier_id
     WHERE pu.status = 'CONFIRMED'
     GROUP BY 1, 2, 3
)
SELECT
    supplier_id,
    ruc,
    supplier_name,
    purchases,
    units,
    amount,
    round(amount / NULLIF(purchases, 0), 2) AS avg_ticket,
    round(100 * amount / NULLIF(sum(amount) OVER (), 0), 2) AS amount_share_pct,
    rank() OVER (ORDER BY amount DESC) AS amount_rank,
    last_purchase_at
FROM base;

CREATE OR REPLACE VIEW reporting.v_rotacion_actual AS
WITH cogs AS (
    SELECT
        p.category_id,
        sum(si.line_cost) AS cogs_90d
      FROM core.sales s
      JOIN core.sale_items si ON si.sale_id = s.sale_id
      JOIN core.products p    ON p.product_id = si.product_id
     WHERE s.status = 'CONFIRMED'
       AND s.sale_date >= now() - interval '90 days'
     GROUP BY 1
), inventory AS (
    SELECT category_id, sum(stock_value) AS inventory_value
      FROM reporting.v_stock_actual
     WHERE quantity > 0
     GROUP BY 1
)
SELECT
    c.category_id,
    c.name AS category_name,
    COALESCE(k.cogs_90d, 0) AS cogs_90d,
    COALESCE(i.inventory_value, 0) AS inventory_value,
    round(COALESCE(k.cogs_90d, 0) / NULLIF(i.inventory_value, 0) * 4, 2) AS annualized_turns,
    round(365 / NULLIF(COALESCE(k.cogs_90d, 0) / NULLIF(i.inventory_value, 0) * 4, 0), 1) AS days_of_inventory
FROM core.categories c
LEFT JOIN cogs k      ON k.category_id = c.category_id
LEFT JOIN inventory i ON i.category_id = c.category_id;

-- Valor de inventario a una fecha, derivado del libro mayor.
CREATE OR REPLACE FUNCTION reporting.fn_inventory_value_at(p_at timestamptz)
RETURNS TABLE (
    category_id integer,
    category_name text,
    inventory_value numeric
)
LANGUAGE sql
STABLE
AS $$
    WITH balances AS (
        SELECT
            sm.product_id,
            sm.warehouse_id,
            sum(sm.quantity_delta)::numeric AS quantity
          FROM core.stock_movements sm
         WHERE sm.occurred_at <= p_at
         GROUP BY 1, 2
    ), last_cost AS (
        SELECT DISTINCT ON (sm.product_id, sm.warehouse_id)
            sm.product_id,
            sm.warehouse_id,
            sm.unit_cost
          FROM core.stock_movements sm
         WHERE sm.occurred_at <= p_at
         ORDER BY sm.product_id, sm.warehouse_id, sm.occurred_at DESC, sm.movement_id DESC
    )
    SELECT
        p.category_id,
        c.name AS category_name,
        round(sum(b.quantity * COALESCE(lc.unit_cost, p.unit_cost)), 2) AS inventory_value
      FROM balances b
      JOIN core.products p   ON p.product_id = b.product_id
      JOIN core.categories c ON c.category_id = p.category_id
      LEFT JOIN last_cost lc ON lc.product_id = b.product_id
                            AND lc.warehouse_id = b.warehouse_id
     WHERE b.quantity <> 0
     GROUP BY p.category_id, c.name;
$$;
