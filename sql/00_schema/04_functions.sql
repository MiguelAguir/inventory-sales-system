-- 04_functions.sql
-- Reglas de negocio centralizadas en la base de datos.
--
-- Principios:
--   * El stock se deriva del libro mayor (stock_movements), nunca se edita a mano.
--   * Confirmar y cancelar son funciones explicitas e idempotentes.
--   * Los triggers protegen invariantes, no ocultan el flujo de negocio.
--   * Los bloqueos se toman en orden de product_id para reducir deadlocks.

-- ---------------------------------------------------------------------------
-- Configuracion
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.fn_igv_rate()
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(
        (SELECT setting_value FROM core.settings WHERE setting_key = 'igv_rate'),
        0.18
    );
$$;

-- ---------------------------------------------------------------------------
-- Totales de ventas
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.fn_recalc_sale_totals(p_sale_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_subtotal numeric(12,2);
    v_tax      numeric(12,2);
BEGIN
    SELECT COALESCE(SUM(line_subtotal), 0)
      INTO v_subtotal
      FROM core.sale_items
     WHERE sale_id = p_sale_id;

    v_tax := round(v_subtotal * core.fn_igv_rate(), 2);

    UPDATE core.sales
       SET subtotal = v_subtotal,
           tax = v_tax,
           total = v_subtotal + v_tax
     WHERE sale_id = p_sale_id
       AND status = 'DRAFT';
END;
$$;

CREATE OR REPLACE FUNCTION core.trg_sale_items_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_sale_id bigint;
    v_status  core.order_status;
BEGIN
    v_sale_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.sale_id ELSE NEW.sale_id END;

    SELECT status INTO v_status
      FROM core.sales
     WHERE sale_id = v_sale_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'La venta % no existe', v_sale_id USING ERRCODE = '23503';
    END IF;

    IF v_status <> 'DRAFT' THEN
        RAISE EXCEPTION 'No se pueden modificar lineas de una venta en estado %', v_status
            USING ERRCODE = '23514';
    END IF;

    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_sale_items_guard ON core.sale_items;
CREATE TRIGGER trg_sale_items_guard
    BEFORE INSERT OR UPDATE OR DELETE ON core.sale_items
    FOR EACH ROW EXECUTE FUNCTION core.trg_sale_items_guard();

CREATE OR REPLACE FUNCTION core.trg_sale_items_totals()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_sale_id bigint;
BEGIN
    v_sale_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.sale_id ELSE NEW.sale_id END;
    PERFORM core.fn_recalc_sale_totals(v_sale_id);
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_sale_items_totals ON core.sale_items;
CREATE TRIGGER trg_sale_items_totals
    AFTER INSERT OR UPDATE OR DELETE ON core.sale_items
    FOR EACH ROW EXECUTE FUNCTION core.trg_sale_items_totals();

-- ---------------------------------------------------------------------------
-- Totales de compras
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.fn_recalc_purchase_totals(p_purchase_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_subtotal numeric(12,2);
    v_tax      numeric(12,2);
BEGIN
    SELECT COALESCE(SUM(line_subtotal), 0)
      INTO v_subtotal
      FROM core.purchase_items
     WHERE purchase_id = p_purchase_id;

    v_tax := round(v_subtotal * core.fn_igv_rate(), 2);

    UPDATE core.purchases
       SET subtotal = v_subtotal,
           tax = v_tax,
           total = v_subtotal + v_tax
     WHERE purchase_id = p_purchase_id
       AND status = 'DRAFT';
END;
$$;

CREATE OR REPLACE FUNCTION core.trg_purchase_items_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_purchase_id bigint;
    v_status      core.order_status;
BEGIN
    v_purchase_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.purchase_id ELSE NEW.purchase_id END;

    SELECT status INTO v_status
      FROM core.purchases
     WHERE purchase_id = v_purchase_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'La compra % no existe', v_purchase_id USING ERRCODE = '23503';
    END IF;

    IF v_status <> 'DRAFT' THEN
        RAISE EXCEPTION 'No se pueden modificar lineas de una compra en estado %', v_status
            USING ERRCODE = '23514';
    END IF;

    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_purchase_items_guard ON core.purchase_items;
CREATE TRIGGER trg_purchase_items_guard
    BEFORE INSERT OR UPDATE OR DELETE ON core.purchase_items
    FOR EACH ROW EXECUTE FUNCTION core.trg_purchase_items_guard();

CREATE OR REPLACE FUNCTION core.trg_purchase_items_totals()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_purchase_id bigint;
BEGIN
    v_purchase_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.purchase_id ELSE NEW.purchase_id END;
    PERFORM core.fn_recalc_purchase_totals(v_purchase_id);
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_purchase_items_totals ON core.purchase_items;
CREATE TRIGGER trg_purchase_items_totals
    AFTER INSERT OR UPDATE OR DELETE ON core.purchase_items
    FOR EACH ROW EXECUTE FUNCTION core.trg_purchase_items_totals();

-- ---------------------------------------------------------------------------
-- Guardas de cabecera: importes inmutables y transiciones controladas
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.trg_sales_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status = 'CANCELLED' THEN
        RAISE EXCEPTION 'Una venta cancelada es inmutable' USING ERRCODE = '23514';
    END IF;

    IF OLD.status IN ('CONFIRMED', 'CANCELLED') THEN
        IF NEW.customer_id IS DISTINCT FROM OLD.customer_id
           OR NEW.warehouse_id IS DISTINCT FROM OLD.warehouse_id
           OR NEW.sale_date IS DISTINCT FROM OLD.sale_date
           OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
           OR NEW.tax IS DISTINCT FROM OLD.tax
           OR NEW.total IS DISTINCT FROM OLD.total THEN
            RAISE EXCEPTION 'Los datos economicos de una venta confirmada son inmutables'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.status = 'DRAFT' AND NEW.status = 'CONFIRMED' THEN
        IF current_setting('inventory.posting', true) IS DISTINCT FROM 'sale:' || OLD.sale_id::text THEN
            RAISE EXCEPTION 'Use core.fn_confirm_sale() para confirmar una venta'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.status = 'CONFIRMED' AND NEW.status = 'CANCELLED' THEN
        IF current_setting('inventory.posting', true) IS DISTINCT FROM 'sale-cancel:' || OLD.sale_id::text THEN
            RAISE EXCEPTION 'Use core.fn_cancel_sale() para cancelar una venta'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.status = 'DRAFT' AND NEW.status = 'CANCELLED' THEN
        RAISE EXCEPTION 'Un borrador no se cancela: se elimina o se confirma' USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sales_guard ON core.sales;
CREATE TRIGGER trg_sales_guard
    BEFORE UPDATE ON core.sales
    FOR EACH ROW EXECUTE FUNCTION core.trg_sales_guard();

CREATE OR REPLACE FUNCTION core.trg_sales_no_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Las ventas no se eliminan; use el estado CANCELLED' USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER IF EXISTS trg_sales_no_delete ON core.sales;
CREATE TRIGGER trg_sales_no_delete
    BEFORE DELETE ON core.sales
    FOR EACH ROW EXECUTE FUNCTION core.trg_sales_no_delete();

CREATE OR REPLACE FUNCTION core.trg_purchases_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status = 'CANCELLED' THEN
        RAISE EXCEPTION 'Una compra cancelada es inmutable' USING ERRCODE = '23514';
    END IF;

    IF OLD.status IN ('CONFIRMED', 'CANCELLED') THEN
        IF NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
           OR NEW.warehouse_id IS DISTINCT FROM OLD.warehouse_id
           OR NEW.purchase_date IS DISTINCT FROM OLD.purchase_date
           OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
           OR NEW.tax IS DISTINCT FROM OLD.tax
           OR NEW.total IS DISTINCT FROM OLD.total THEN
            RAISE EXCEPTION 'Los datos economicos de una compra confirmada son inmutables'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.status = 'DRAFT' AND NEW.status = 'CONFIRMED' THEN
        IF current_setting('inventory.posting', true) IS DISTINCT FROM 'purchase:' || OLD.purchase_id::text THEN
            RAISE EXCEPTION 'Use core.fn_confirm_purchase() para confirmar una compra'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.status = 'CONFIRMED' AND NEW.status = 'CANCELLED' THEN
        IF current_setting('inventory.posting', true) IS DISTINCT FROM 'purchase-cancel:' || OLD.purchase_id::text THEN
            RAISE EXCEPTION 'Use core.fn_cancel_purchase() para cancelar una compra'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF OLD.status = 'DRAFT' AND NEW.status = 'CANCELLED' THEN
        RAISE EXCEPTION 'Un borrador no se cancela: se elimina o se confirma' USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_purchases_guard ON core.purchases;
CREATE TRIGGER trg_purchases_guard
    BEFORE UPDATE ON core.purchases
    FOR EACH ROW EXECUTE FUNCTION core.trg_purchases_guard();

CREATE OR REPLACE FUNCTION core.trg_purchases_no_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Las compras no se eliminan; use el estado CANCELLED' USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER IF EXISTS trg_purchases_no_delete ON core.purchases;
CREATE TRIGGER trg_purchases_no_delete
    BEFORE DELETE ON core.purchases
    FOR EACH ROW EXECUTE FUNCTION core.trg_purchases_no_delete();

-- ---------------------------------------------------------------------------
-- Inventario: aplicar movimientos y bloquear edicion
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.trg_stock_movements_apply()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_available integer;
    v_min_stock integer;
BEGIN
    IF NEW.quantity_delta < 0 THEN
        -- UPDATE atomico: si el saldo resultante es negativo, no actualiza.
        -- Bajo concurrencia, PostgreSQL reevalua el WHERE tras el lock.
        UPDATE core.stock_levels
           SET quantity = quantity + NEW.quantity_delta,
               updated_at = now()
         WHERE product_id = NEW.product_id
           AND warehouse_id = NEW.warehouse_id
           AND quantity + NEW.quantity_delta >= 0;

        IF NOT FOUND THEN
            SELECT quantity INTO v_available
              FROM core.stock_levels
             WHERE product_id = NEW.product_id
               AND warehouse_id = NEW.warehouse_id;

            IF v_available IS NULL THEN
                RAISE EXCEPTION
                    'No existe saldo de stock para producto % en almacen %. Registre una entrada primero.',
                    NEW.product_id, NEW.warehouse_id
                    USING ERRCODE = '23514';
            END IF;

            RAISE EXCEPTION
                'Stock insuficiente para producto % en almacen %: disponible %, requerido %',
                NEW.product_id, NEW.warehouse_id, v_available, abs(NEW.quantity_delta)
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT min_stock INTO v_min_stock
          FROM core.products
         WHERE product_id = NEW.product_id;

        INSERT INTO core.stock_levels (product_id, warehouse_id, quantity, min_quantity, updated_at)
        VALUES (NEW.product_id, NEW.warehouse_id, NEW.quantity_delta, COALESCE(v_min_stock, 0), now())
        ON CONFLICT (product_id, warehouse_id) DO UPDATE
            SET quantity = core.stock_levels.quantity + EXCLUDED.quantity,
                updated_at = now();
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_stock_movements_apply ON core.stock_movements;
CREATE TRIGGER trg_stock_movements_apply
    AFTER INSERT ON core.stock_movements
    FOR EACH ROW EXECUTE FUNCTION core.trg_stock_movements_apply();

CREATE OR REPLACE FUNCTION core.trg_stock_movements_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'stock_movements es un libro mayor inmutable: registre un movimiento contrario'
        USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER IF EXISTS trg_stock_movements_immutable ON core.stock_movements;
CREATE TRIGGER trg_stock_movements_immutable
    BEFORE UPDATE OR DELETE ON core.stock_movements
    FOR EACH ROW EXECUTE FUNCTION core.trg_stock_movements_immutable();

-- ---------------------------------------------------------------------------
-- Ventas: confirmar, cancelar y registrar
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.fn_confirm_sale(p_sale_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_sale core.sales%ROWTYPE;
    v_line record;
BEGIN
    SELECT * INTO v_sale
      FROM core.sales
     WHERE sale_id = p_sale_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'La venta % no existe', p_sale_id USING ERRCODE = '23503';
    END IF;

    -- Idempotente: confirmar dos veces no duplica movimientos.
    IF v_sale.status = 'CONFIRMED' THEN
        RETURN;
    END IF;

    IF v_sale.status <> 'DRAFT' THEN
        RAISE EXCEPTION 'No se puede confirmar una venta en estado %', v_sale.status
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM core.sale_items WHERE sale_id = p_sale_id) THEN
        RAISE EXCEPTION 'La venta % no tiene lineas', p_sale_id USING ERRCODE = '23514';
    END IF;

    -- ORDER BY product_id: orden estable de locks para evitar deadlocks.
    FOR v_line IN
        SELECT si.product_id, si.quantity, si.unit_cost
          FROM core.sale_items si
         WHERE si.sale_id = p_sale_id
         ORDER BY si.product_id
    LOOP
        INSERT INTO core.stock_movements (
            product_id, warehouse_id, movement_type, quantity_delta,
            unit_cost, sale_id, occurred_at, reference_note
        )
        VALUES (
            v_line.product_id, v_sale.warehouse_id, 'SALE', -v_line.quantity,
            v_line.unit_cost, p_sale_id, v_sale.sale_date,
            'Venta ' || v_sale.sale_number
        );
    END LOOP;

    PERFORM set_config('inventory.posting', 'sale:' || p_sale_id::text, true);
    UPDATE core.sales
       SET status = 'CONFIRMED',
           confirmed_at = now()
     WHERE sale_id = p_sale_id;
    PERFORM set_config('inventory.posting', '', true);
END;
$$;

CREATE OR REPLACE FUNCTION core.fn_cancel_sale(
    p_sale_id bigint,
    p_occurred_at timestamptz DEFAULT now()
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_sale core.sales%ROWTYPE;
    v_line record;
BEGIN
    SELECT * INTO v_sale
      FROM core.sales
     WHERE sale_id = p_sale_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'La venta % no existe', p_sale_id USING ERRCODE = '23503';
    END IF;

    -- Idempotente: cancelar dos veces no duplica la reversa.
    IF v_sale.status = 'CANCELLED' THEN
        RETURN;
    END IF;

    IF v_sale.status <> 'CONFIRMED' THEN
        RAISE EXCEPTION 'Solo se cancela una venta confirmada; estado actual: %', v_sale.status
            USING ERRCODE = '23514';
    END IF;

    FOR v_line IN
        SELECT si.product_id, si.quantity, si.unit_cost
          FROM core.sale_items si
         WHERE si.sale_id = p_sale_id
         ORDER BY si.product_id
    LOOP
        INSERT INTO core.stock_movements (
            product_id, warehouse_id, movement_type, quantity_delta,
            unit_cost, sale_id, occurred_at, reference_note
        )
        VALUES (
            v_line.product_id, v_sale.warehouse_id, 'SALE_CANCEL', v_line.quantity,
            v_line.unit_cost, p_sale_id, COALESCE(p_occurred_at, now()),
            'Anulacion venta ' || v_sale.sale_number
        );
    END LOOP;

    PERFORM set_config('inventory.posting', 'sale-cancel:' || p_sale_id::text, true);
    UPDATE core.sales
       SET status = 'CANCELLED',
           cancelled_at = now()
     WHERE sale_id = p_sale_id;
    PERFORM set_config('inventory.posting', '', true);
END;
$$;

CREATE OR REPLACE FUNCTION core.fn_register_sale(
    p_customer_id integer,
    p_warehouse_id integer,
    p_items jsonb,
    p_sale_date timestamptz DEFAULT now()
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_sale_id bigint;
    v_number text;
    v_item jsonb;
    v_line integer := 0;
    v_product_id integer;
    v_quantity integer;
    v_price numeric(12,2);
    v_cost numeric(12,2);
    v_discount numeric(5,2);
BEGIN
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'La venta debe incluir al menos una linea en p_items' USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM core.customers WHERE customer_id = p_customer_id AND is_active) THEN
        RAISE EXCEPTION 'Cliente % no existe o esta inactivo', p_customer_id USING ERRCODE = '23503';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM core.warehouses WHERE warehouse_id = p_warehouse_id AND is_active) THEN
        RAISE EXCEPTION 'Almacen % no existe o esta inactivo', p_warehouse_id USING ERRCODE = '23503';
    END IF;

    v_number := 'V-' || to_char(p_sale_date, 'YYYYMM') || '-'
                || lpad(nextval('core.sale_number_seq')::text, 6, '0');

    INSERT INTO core.sales (sale_number, customer_id, warehouse_id, sale_date, status)
    VALUES (v_number, p_customer_id, p_warehouse_id, p_sale_date, 'DRAFT')
    RETURNING sale_id INTO v_sale_id;

    FOR v_item IN SELECT value FROM jsonb_array_elements(p_items)
    LOOP
        v_line := v_line + 1;
        v_product_id := (v_item ->> 'product_id')::integer;
        v_quantity := (v_item ->> 'quantity')::integer;

        SELECT unit_price, unit_cost
          INTO v_price, v_cost
          FROM core.products
         WHERE product_id = v_product_id
           AND is_active;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Producto % no existe o esta inactivo', v_product_id
                USING ERRCODE = '23503';
        END IF;

        v_price := COALESCE(NULLIF(v_item ->> 'unit_price', '')::numeric, v_price);
        v_discount := COALESCE(NULLIF(v_item ->> 'discount_pct', '')::numeric, 0);

        INSERT INTO core.sale_items (
            sale_id, line_number, product_id, quantity, unit_price, unit_cost, discount_pct
        )
        VALUES (
            v_sale_id, v_line, v_product_id, v_quantity, v_price, v_cost, v_discount
        );
    END LOOP;

    PERFORM core.fn_confirm_sale(v_sale_id);
    RETURN v_sale_id;
END;
$$;

-- ---------------------------------------------------------------------------
-- Compras: confirmar, cancelar y registrar
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.fn_confirm_purchase(p_purchase_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_purchase core.purchases%ROWTYPE;
    v_line record;
BEGIN
    SELECT * INTO v_purchase
      FROM core.purchases
     WHERE purchase_id = p_purchase_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'La compra % no existe', p_purchase_id USING ERRCODE = '23503';
    END IF;

    IF v_purchase.status = 'CONFIRMED' THEN
        RETURN;
    END IF;

    IF v_purchase.status <> 'DRAFT' THEN
        RAISE EXCEPTION 'No se puede confirmar una compra en estado %', v_purchase.status
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM core.purchase_items WHERE purchase_id = p_purchase_id) THEN
        RAISE EXCEPTION 'La compra % no tiene lineas', p_purchase_id USING ERRCODE = '23514';
    END IF;

    FOR v_line IN
        SELECT pi.product_id, pi.quantity, pi.unit_cost
          FROM core.purchase_items pi
         WHERE pi.purchase_id = p_purchase_id
         ORDER BY pi.product_id
    LOOP
        INSERT INTO core.stock_movements (
            product_id, warehouse_id, movement_type, quantity_delta,
            unit_cost, purchase_id, occurred_at, reference_note
        )
        VALUES (
            v_line.product_id, v_purchase.warehouse_id, 'PURCHASE', v_line.quantity,
            v_line.unit_cost, p_purchase_id, v_purchase.purchase_date,
            'Compra ' || v_purchase.purchase_number
        );
    END LOOP;

    PERFORM set_config('inventory.posting', 'purchase:' || p_purchase_id::text, true);
    UPDATE core.purchases
       SET status = 'CONFIRMED',
           confirmed_at = now()
     WHERE purchase_id = p_purchase_id;
    PERFORM set_config('inventory.posting', '', true);
END;
$$;

CREATE OR REPLACE FUNCTION core.fn_cancel_purchase(
    p_purchase_id bigint,
    p_occurred_at timestamptz DEFAULT now()
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_purchase core.purchases%ROWTYPE;
    v_line record;
BEGIN
    SELECT * INTO v_purchase
      FROM core.purchases
     WHERE purchase_id = p_purchase_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'La compra % no existe', p_purchase_id USING ERRCODE = '23503';
    END IF;

    IF v_purchase.status = 'CANCELLED' THEN
        RETURN;
    END IF;

    IF v_purchase.status <> 'CONFIRMED' THEN
        RAISE EXCEPTION 'Solo se cancela una compra confirmada; estado actual: %', v_purchase.status
            USING ERRCODE = '23514';
    END IF;

    -- Si parte de la mercaderia ya se vendio, el trigger de stock impedira
    -- la cancelacion para no dejar saldos negativos.
    FOR v_line IN
        SELECT pi.product_id, pi.quantity, pi.unit_cost
          FROM core.purchase_items pi
         WHERE pi.purchase_id = p_purchase_id
         ORDER BY pi.product_id
    LOOP
        INSERT INTO core.stock_movements (
            product_id, warehouse_id, movement_type, quantity_delta,
            unit_cost, purchase_id, occurred_at, reference_note
        )
        VALUES (
            v_line.product_id, v_purchase.warehouse_id, 'PURCHASE_CANCEL', -v_line.quantity,
            v_line.unit_cost, p_purchase_id, COALESCE(p_occurred_at, now()),
            'Anulacion compra ' || v_purchase.purchase_number
        );
    END LOOP;

    PERFORM set_config('inventory.posting', 'purchase-cancel:' || p_purchase_id::text, true);
    UPDATE core.purchases
       SET status = 'CANCELLED',
           cancelled_at = now()
     WHERE purchase_id = p_purchase_id;
    PERFORM set_config('inventory.posting', '', true);
END;
$$;

CREATE OR REPLACE FUNCTION core.fn_register_purchase(
    p_supplier_id integer,
    p_warehouse_id integer,
    p_items jsonb,
    p_purchase_date timestamptz DEFAULT now()
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_purchase_id bigint;
    v_number text;
    v_item jsonb;
    v_line integer := 0;
    v_product_id integer;
    v_quantity integer;
    v_cost numeric(12,2);
BEGIN
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'La compra debe incluir al menos una linea en p_items' USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM core.suppliers WHERE supplier_id = p_supplier_id AND is_active) THEN
        RAISE EXCEPTION 'Proveedor % no existe o esta inactivo', p_supplier_id USING ERRCODE = '23503';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM core.warehouses WHERE warehouse_id = p_warehouse_id AND is_active) THEN
        RAISE EXCEPTION 'Almacen % no existe o esta inactivo', p_warehouse_id USING ERRCODE = '23503';
    END IF;

    v_number := 'C-' || to_char(p_purchase_date, 'YYYYMM') || '-'
                || lpad(nextval('core.purchase_number_seq')::text, 6, '0');

    INSERT INTO core.purchases (purchase_number, supplier_id, warehouse_id, purchase_date, status)
    VALUES (v_number, p_supplier_id, p_warehouse_id, p_purchase_date, 'DRAFT')
    RETURNING purchase_id INTO v_purchase_id;

    FOR v_item IN SELECT value FROM jsonb_array_elements(p_items)
    LOOP
        v_line := v_line + 1;
        v_product_id := (v_item ->> 'product_id')::integer;
        v_quantity := (v_item ->> 'quantity')::integer;

        SELECT unit_cost
          INTO v_cost
          FROM core.products
         WHERE product_id = v_product_id
           AND is_active;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Producto % no existe o esta inactivo', v_product_id
                USING ERRCODE = '23503';
        END IF;

        v_cost := COALESCE(NULLIF(v_item ->> 'unit_cost', '')::numeric, v_cost);

        INSERT INTO core.purchase_items (
            purchase_id, line_number, product_id, quantity, unit_cost
        )
        VALUES (
            v_purchase_id, v_line, v_product_id, v_quantity, v_cost
        );
    END LOOP;

    PERFORM core.fn_confirm_purchase(v_purchase_id);
    RETURN v_purchase_id;
END;
$$;

-- ---------------------------------------------------------------------------
-- Operaciones auxiliares de inventario
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.fn_adjust_stock(
    p_product_id integer,
    p_warehouse_id integer,
    p_quantity_delta integer,
    p_note text,
    p_occurred_at timestamptz DEFAULT now()
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_movement_id bigint;
    v_cost numeric(12,2);
    v_type core.movement_type;
BEGIN
    IF p_quantity_delta = 0 THEN
        RAISE EXCEPTION 'El ajuste debe tener cantidad distinta de cero' USING ERRCODE = '22023';
    END IF;

    SELECT unit_cost INTO v_cost
      FROM core.products
     WHERE product_id = p_product_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Producto % no existe', p_product_id USING ERRCODE = '23503';
    END IF;

    v_type := CASE WHEN p_quantity_delta > 0 THEN 'ADJUSTMENT_IN'::core.movement_type
                   ELSE 'ADJUSTMENT_OUT'::core.movement_type END;

    INSERT INTO core.stock_movements (
        product_id, warehouse_id, movement_type, quantity_delta,
        unit_cost, occurred_at, reference_note
    )
    VALUES (
        p_product_id, p_warehouse_id, v_type, p_quantity_delta,
        v_cost, COALESCE(p_occurred_at, now()), p_note
    )
    RETURNING movement_id INTO v_movement_id;

    RETURN v_movement_id;
END;
$$;

CREATE OR REPLACE FUNCTION core.fn_set_min_stock(
    p_product_id integer,
    p_warehouse_id integer,
    p_min_quantity integer
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_min_quantity < 0 THEN
        RAISE EXCEPTION 'El stock minimo no puede ser negativo' USING ERRCODE = '22023';
    END IF;

    INSERT INTO core.stock_levels (product_id, warehouse_id, quantity, min_quantity, updated_at)
    VALUES (p_product_id, p_warehouse_id, 0, p_min_quantity, now())
    ON CONFLICT (product_id, warehouse_id) DO UPDATE
        SET min_quantity = EXCLUDED.min_quantity,
            updated_at = now();
END;
$$;

CREATE OR REPLACE FUNCTION core.fn_transfer_stock(
    p_product_id integer,
    p_from_warehouse_id integer,
    p_to_warehouse_id integer,
    p_quantity integer,
    p_occurred_at timestamptz DEFAULT now()
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_cost numeric(12,2);
    v_note text;
BEGIN
    IF p_quantity <= 0 THEN
        RAISE EXCEPTION 'La cantidad a transferir debe ser positiva' USING ERRCODE = '22023';
    END IF;

    IF p_from_warehouse_id = p_to_warehouse_id THEN
        RAISE EXCEPTION 'El almacen origen y destino deben ser distintos' USING ERRCODE = '22023';
    END IF;

    SELECT unit_cost INTO v_cost FROM core.products WHERE product_id = p_product_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Producto % no existe', p_product_id USING ERRCODE = '23503';
    END IF;

    v_note := 'Transferencia ' || p_from_warehouse_id || ' -> ' || p_to_warehouse_id;

    INSERT INTO core.stock_movements (
        product_id, warehouse_id, movement_type, quantity_delta,
        unit_cost, occurred_at, reference_note
    )
    VALUES (
        p_product_id, p_from_warehouse_id, 'TRANSFER_OUT', -p_quantity,
        v_cost, COALESCE(p_occurred_at, now()), v_note
    );

    INSERT INTO core.stock_movements (
        product_id, warehouse_id, movement_type, quantity_delta,
        unit_cost, occurred_at, reference_note
    )
    VALUES (
        p_product_id, p_to_warehouse_id, 'TRANSFER_IN', p_quantity,
        v_cost, COALESCE(p_occurred_at, now()), v_note
    );
END;
$$;

COMMENT ON FUNCTION core.fn_register_sale(integer, integer, jsonb, timestamptz) IS
    'Crea, valida y confirma una venta en una sola transaccion. p_items: [{"product_id":1,"quantity":2,"discount_pct":10}]';
COMMENT ON FUNCTION core.fn_register_purchase(integer, integer, jsonb, timestamptz) IS
    'Crea, valida y confirma una compra en una sola transaccion. p_items: [{"product_id":1,"quantity":10,"unit_cost":95.50}]';
COMMENT ON FUNCTION core.fn_cancel_sale(bigint, timestamptz) IS
    'Genera movimientos SALE_CANCEL y marca la venta como CANCELLED. Idempotente.';
COMMENT ON FUNCTION core.fn_cancel_purchase(bigint, timestamptz) IS
    'Genera movimientos PURCHASE_CANCEL. Falla si dejaria stock negativo. Idempotente.';
