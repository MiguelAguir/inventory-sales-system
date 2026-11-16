-- 01_schemas.sql
-- Esquemas y tipos base del sistema.
-- Idempotente: se puede ejecutar varias veces sin efectos colaterales.

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS reporting;
CREATE SCHEMA IF NOT EXISTS audit;

DO $$
BEGIN
    CREATE TYPE core.doc_type AS ENUM ('DNI', 'RUC', 'CE');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
    CREATE TYPE core.order_status AS ENUM ('DRAFT', 'CONFIRMED', 'CANCELLED');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
    CREATE TYPE core.movement_type AS ENUM (
        'PURCHASE',
        'PURCHASE_CANCEL',
        'SALE',
        'SALE_CANCEL',
        'ADJUSTMENT_IN',
        'ADJUSTMENT_OUT',
        'TRANSFER_IN',
        'TRANSFER_OUT'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

COMMENT ON SCHEMA core IS 'Tablas operativas normalizadas (3NF) y reglas de negocio.';
COMMENT ON SCHEMA reporting IS 'Vistas y objetos de solo lectura para analitica y BI.';
COMMENT ON SCHEMA audit IS 'Resultados de controles de calidad y evidencia de pruebas.';
