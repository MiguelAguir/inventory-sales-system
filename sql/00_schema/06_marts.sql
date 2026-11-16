-- 06_marts.sql
-- Vistas materializadas para BI. Se refrescan manualmente:
--   python -m src.pipeline refresh
-- La version CONCURRENTLY se ejecuta desde el CLI en autocommit.
-- La funcion usa REFRESH normal para poder invocarse dentro de una transaccion.

-- IF NOT EXISTS mantiene los datos si el esquema se reaplica.
-- Si cambia la definicion de la vista, hay que hacer DROP manual.
CREATE MATERIALIZED VIEW IF NOT EXISTS reporting.mv_ventas_mensuales AS
SELECT * FROM reporting.v_ventas_mensuales
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_ventas_mensuales_month
    ON reporting.mv_ventas_mensuales (month);

CREATE MATERIALIZED VIEW IF NOT EXISTS reporting.mv_ventas_categoria_mes AS
SELECT * FROM reporting.v_ventas_categoria_mes
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_ventas_categoria_mes
    ON reporting.mv_ventas_categoria_mes (month, category_id);

CREATE OR REPLACE FUNCTION reporting.fn_refresh_marts()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW reporting.mv_ventas_mensuales;
    REFRESH MATERIALIZED VIEW reporting.mv_ventas_categoria_mes;
END;
$$;
