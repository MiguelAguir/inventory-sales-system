-- 02_tables.sql
-- Modelo relacional en 3NF. Dinero en numeric(12,2), fechas en timestamptz.
-- No se usan columnas serial: se prefiere GENERATED ALWAYS AS IDENTITY.

CREATE SEQUENCE IF NOT EXISTS core.sale_number_seq;
CREATE SEQUENCE IF NOT EXISTS core.purchase_number_seq;

-- ---------------------------------------------------------------------------
-- Catalogos
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS core.categories (
    category_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_id   integer REFERENCES core.categories(category_id) ON DELETE RESTRICT,
    code        text NOT NULL UNIQUE,
    name        text NOT NULL UNIQUE,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT categories_no_self_parent CHECK (parent_id IS NULL OR parent_id <> category_id),
    CONSTRAINT categories_code_format CHECK (code ~ '^[A-Z0-9_-]{2,20}$')
);

CREATE TABLE IF NOT EXISTS core.warehouses (
    warehouse_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         text NOT NULL UNIQUE,
    name         text NOT NULL,
    address      text,
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT warehouses_code_format CHECK (code ~ '^[A-Z0-9_-]{2,20}$')
);

CREATE TABLE IF NOT EXISTS core.suppliers (
    supplier_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ruc            text NOT NULL UNIQUE,
    name           text NOT NULL,
    email          text,
    phone          text,
    lead_time_days integer NOT NULL DEFAULT 7,
    is_active      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT suppliers_ruc_format CHECK (ruc ~ '^[0-9]{11}$'),
    CONSTRAINT suppliers_lead_time_range CHECK (lead_time_days BETWEEN 1 AND 120),
    CONSTRAINT suppliers_email_format CHECK (email IS NULL OR email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$')
);

CREATE TABLE IF NOT EXISTS core.products (
    product_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku        text NOT NULL UNIQUE,
    name       text NOT NULL,
    category_id integer NOT NULL REFERENCES core.categories(category_id) ON DELETE RESTRICT,
    unit       text NOT NULL DEFAULT 'UND',
    unit_price numeric(12,2) NOT NULL,
    unit_cost  numeric(12,2) NOT NULL,
    min_stock  integer NOT NULL DEFAULT 10,
    is_active  boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT products_unit_allowed CHECK (unit IN ('UND', 'CAJA', 'KG', 'LT', 'PACK')),
    CONSTRAINT products_price_positive CHECK (unit_price > 0),
    CONSTRAINT products_cost_positive CHECK (unit_cost > 0),
    CONSTRAINT products_margin_non_negative CHECK (unit_price >= unit_cost),
    CONSTRAINT products_min_stock_non_negative CHECK (min_stock >= 0)
);

CREATE TABLE IF NOT EXISTS core.product_suppliers (
    product_id      integer NOT NULL REFERENCES core.products(product_id) ON DELETE CASCADE,
    supplier_id     integer NOT NULL REFERENCES core.suppliers(supplier_id) ON DELETE RESTRICT,
    supplier_sku    text NOT NULL,
    unit_cost       numeric(12,2) NOT NULL,
    lead_time_days  integer NOT NULL,
    is_preferred    boolean NOT NULL DEFAULT false,
    PRIMARY KEY (product_id, supplier_id),
    CONSTRAINT product_suppliers_sku_unique UNIQUE (supplier_id, supplier_sku),
    CONSTRAINT product_suppliers_cost_positive CHECK (unit_cost > 0),
    CONSTRAINT product_suppliers_lead_time_range CHECK (lead_time_days BETWEEN 1 AND 120)
);

-- Un solo proveedor preferido por producto.
CREATE UNIQUE INDEX IF NOT EXISTS ux_product_suppliers_one_preferred
    ON core.product_suppliers (product_id)
    WHERE is_preferred;

CREATE TABLE IF NOT EXISTS core.customers (
    customer_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_type    core.doc_type NOT NULL,
    doc_number  text NOT NULL,
    name        text NOT NULL,
    email       text,
    phone       text,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT customers_doc_unique UNIQUE (doc_type, doc_number),
    CONSTRAINT customers_doc_format CHECK (
        (doc_type = 'DNI' AND doc_number ~ '^[0-9]{8}$')
        OR (doc_type = 'RUC' AND doc_number ~ '^[0-9]{11}$')
        OR (doc_type = 'CE' AND doc_number ~ '^[A-Za-z0-9]{9,12}$')
    ),
    CONSTRAINT customers_email_format CHECK (email IS NULL OR email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$')
);

-- ---------------------------------------------------------------------------
-- Ventas
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS core.sales (
    sale_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sale_number  text NOT NULL UNIQUE,
    customer_id  integer NOT NULL REFERENCES core.customers(customer_id) ON DELETE RESTRICT,
    warehouse_id integer NOT NULL REFERENCES core.warehouses(warehouse_id) ON DELETE RESTRICT,
    sale_date    timestamptz NOT NULL DEFAULT now(),
    status       core.order_status NOT NULL DEFAULT 'DRAFT',
    subtotal     numeric(12,2) NOT NULL DEFAULT 0,
    tax          numeric(12,2) NOT NULL DEFAULT 0,
    total        numeric(12,2) NOT NULL DEFAULT 0,
    notes        text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    confirmed_at timestamptz,
    cancelled_at timestamptz,
    CONSTRAINT sales_number_format CHECK (sale_number ~ '^V-[0-9]{6}-[0-9]{6}$'),
    CONSTRAINT sales_amounts_non_negative CHECK (subtotal >= 0 AND tax >= 0 AND total >= 0),
    CONSTRAINT sales_totals_match CHECK (total = subtotal + tax),
    CONSTRAINT sales_status_timestamps CHECK (
        (status = 'DRAFT' AND confirmed_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'CONFIRMED' AND confirmed_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'CANCELLED' AND confirmed_at IS NOT NULL AND cancelled_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS core.sale_items (
    sale_item_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sale_id      bigint NOT NULL REFERENCES core.sales(sale_id) ON DELETE RESTRICT,
    line_number  integer NOT NULL,
    product_id   integer NOT NULL REFERENCES core.products(product_id) ON DELETE RESTRICT,
    quantity     integer NOT NULL,
    unit_price   numeric(12,2) NOT NULL,
    unit_cost    numeric(12,2) NOT NULL,
    discount_pct numeric(5,2) NOT NULL DEFAULT 0,
    line_subtotal numeric(12,2) GENERATED ALWAYS AS
        (round(quantity * unit_price * (1 - discount_pct / 100), 2)) STORED,
    line_cost    numeric(12,2) GENERATED ALWAYS AS (round(quantity * unit_cost, 2)) STORED,
    CONSTRAINT sale_items_line_unique UNIQUE (sale_id, line_number),
    CONSTRAINT sale_items_product_unique UNIQUE (sale_id, product_id),
    CONSTRAINT sale_items_line_positive CHECK (line_number > 0),
    CONSTRAINT sale_items_quantity_positive CHECK (quantity > 0),
    CONSTRAINT sale_items_price_positive CHECK (unit_price > 0),
    CONSTRAINT sale_items_cost_positive CHECK (unit_cost > 0),
    CONSTRAINT sale_items_discount_range CHECK (discount_pct BETWEEN 0 AND 100)
);

-- ---------------------------------------------------------------------------
-- Compras
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS core.purchases (
    purchase_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_number text NOT NULL UNIQUE,
    supplier_id   integer NOT NULL REFERENCES core.suppliers(supplier_id) ON DELETE RESTRICT,
    warehouse_id  integer NOT NULL REFERENCES core.warehouses(warehouse_id) ON DELETE RESTRICT,
    purchase_date timestamptz NOT NULL DEFAULT now(),
    status        core.order_status NOT NULL DEFAULT 'DRAFT',
    subtotal      numeric(12,2) NOT NULL DEFAULT 0,
    tax           numeric(12,2) NOT NULL DEFAULT 0,
    total         numeric(12,2) NOT NULL DEFAULT 0,
    notes         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    confirmed_at  timestamptz,
    cancelled_at  timestamptz,
    CONSTRAINT purchases_number_format CHECK (purchase_number ~ '^C-[0-9]{6}-[0-9]{6}$'),
    CONSTRAINT purchases_amounts_non_negative CHECK (subtotal >= 0 AND tax >= 0 AND total >= 0),
    CONSTRAINT purchases_totals_match CHECK (total = subtotal + tax),
    CONSTRAINT purchases_status_timestamps CHECK (
        (status = 'DRAFT' AND confirmed_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'CONFIRMED' AND confirmed_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'CANCELLED' AND confirmed_at IS NOT NULL AND cancelled_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS core.purchase_items (
    purchase_item_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_id      bigint NOT NULL REFERENCES core.purchases(purchase_id) ON DELETE RESTRICT,
    line_number      integer NOT NULL,
    product_id       integer NOT NULL REFERENCES core.products(product_id) ON DELETE RESTRICT,
    quantity         integer NOT NULL,
    unit_cost        numeric(12,2) NOT NULL,
    line_subtotal    numeric(12,2) GENERATED ALWAYS AS (round(quantity * unit_cost, 2)) STORED,
    CONSTRAINT purchase_items_line_unique UNIQUE (purchase_id, line_number),
    CONSTRAINT purchase_items_product_unique UNIQUE (purchase_id, product_id),
    CONSTRAINT purchase_items_line_positive CHECK (line_number > 0),
    CONSTRAINT purchase_items_quantity_positive CHECK (quantity > 0),
    CONSTRAINT purchase_items_cost_positive CHECK (unit_cost > 0)
);

-- ---------------------------------------------------------------------------
-- Inventario: saldo + libro mayor inmutable
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS core.stock_levels (
    product_id   integer NOT NULL REFERENCES core.products(product_id) ON DELETE RESTRICT,
    warehouse_id integer NOT NULL REFERENCES core.warehouses(warehouse_id) ON DELETE RESTRICT,
    quantity     integer NOT NULL DEFAULT 0,
    min_quantity integer NOT NULL DEFAULT 0,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, warehouse_id),
    CONSTRAINT stock_levels_quantity_non_negative CHECK (quantity >= 0),
    CONSTRAINT stock_levels_min_non_negative CHECK (min_quantity >= 0)
);

CREATE TABLE IF NOT EXISTS core.stock_movements (
    movement_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id     integer NOT NULL REFERENCES core.products(product_id) ON DELETE RESTRICT,
    warehouse_id   integer NOT NULL REFERENCES core.warehouses(warehouse_id) ON DELETE RESTRICT,
    movement_type  core.movement_type NOT NULL,
    quantity_delta integer NOT NULL,
    unit_cost      numeric(12,2) NOT NULL,
    sale_id        bigint REFERENCES core.sales(sale_id) ON DELETE RESTRICT,
    purchase_id    bigint REFERENCES core.purchases(purchase_id) ON DELETE RESTRICT,
    occurred_at    timestamptz NOT NULL DEFAULT now(),
    reference_note text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT stock_movements_delta_not_zero CHECK (quantity_delta <> 0),
    CONSTRAINT stock_movements_unit_cost_non_negative CHECK (unit_cost >= 0),
    -- Integridad referencial real: no hay referencia polimorfica sin FK.
    CONSTRAINT stock_movements_source CHECK (
        (movement_type IN ('SALE', 'SALE_CANCEL') AND sale_id IS NOT NULL AND purchase_id IS NULL)
        OR (movement_type IN ('PURCHASE', 'PURCHASE_CANCEL') AND purchase_id IS NOT NULL AND sale_id IS NULL)
        OR (movement_type IN ('ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'TRANSFER_IN', 'TRANSFER_OUT')
            AND sale_id IS NULL AND purchase_id IS NULL)
    ),
    -- El signo debe ser coherente con el tipo de movimiento.
    CONSTRAINT stock_movements_sign CHECK (
        (movement_type IN ('PURCHASE', 'SALE_CANCEL', 'ADJUSTMENT_IN', 'TRANSFER_IN') AND quantity_delta > 0)
        OR (movement_type IN ('SALE', 'PURCHASE_CANCEL', 'ADJUSTMENT_OUT', 'TRANSFER_OUT') AND quantity_delta < 0)
    )
);

-- Idempotencia: una venta/compra no puede postear dos veces el mismo
-- producto, almacen y tipo de movimiento.
CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_movements_sale
    ON core.stock_movements (sale_id, product_id, warehouse_id, movement_type)
    WHERE sale_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_movements_purchase
    ON core.stock_movements (purchase_id, product_id, warehouse_id, movement_type)
    WHERE purchase_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Configuracion y auditoria
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS core.settings (
    setting_key   text PRIMARY KEY,
    setting_value numeric(12,4) NOT NULL,
    description   text,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO core.settings (setting_key, setting_value, description)
VALUES ('igv_rate', 0.18, 'Tasa de IGV aplicada a ventas y compras (Peru).')
ON CONFLICT (setting_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS audit.quality_results (
    quality_result_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    check_name        text NOT NULL,
    passed            boolean NOT NULL,
    detail            text,
    checked_at        timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE core.stock_movements IS
    'Libro mayor de inventario. Solo INSERT: UPDATE y DELETE estan bloqueados por trigger.';
COMMENT ON TABLE core.stock_levels IS
    'Saldo materializado por producto y almacen. Se mantiene desde stock_movements.';
COMMENT ON COLUMN core.sale_items.unit_cost IS
    'Costo congelado al momento de la venta; no cambia si el costo del producto cambia despues.';
COMMENT ON COLUMN core.sale_items.unit_price IS
    'Precio congelado al momento de la venta.';
