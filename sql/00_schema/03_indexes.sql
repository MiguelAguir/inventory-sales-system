-- 03_indexes.sql
-- Indices para llaves foraneas y patrones de consulta reales.
-- Los indices de idempotencia ya se crean en 02_tables.sql.

-- Catalogos
CREATE INDEX IF NOT EXISTS ix_categories_parent ON core.categories (parent_id);
CREATE INDEX IF NOT EXISTS ix_products_category ON core.products (category_id);
CREATE INDEX IF NOT EXISTS ix_products_active ON core.products (is_active) WHERE is_active;
CREATE INDEX IF NOT EXISTS ix_product_suppliers_supplier ON core.product_suppliers (supplier_id);

-- Ventas
CREATE INDEX IF NOT EXISTS ix_sales_customer ON core.sales (customer_id);
CREATE INDEX IF NOT EXISTS ix_sales_warehouse ON core.sales (warehouse_id);
CREATE INDEX IF NOT EXISTS ix_sales_status_date ON core.sales (status, sale_date);
CREATE INDEX IF NOT EXISTS ix_sales_confirmed_date ON core.sales (sale_date) WHERE status = 'CONFIRMED';
CREATE INDEX IF NOT EXISTS ix_sale_items_product ON core.sale_items (product_id);

-- Compras
CREATE INDEX IF NOT EXISTS ix_purchases_supplier ON core.purchases (supplier_id);
CREATE INDEX IF NOT EXISTS ix_purchases_warehouse ON core.purchases (warehouse_id);
CREATE INDEX IF NOT EXISTS ix_purchases_status_date ON core.purchases (status, purchase_date);
CREATE INDEX IF NOT EXISTS ix_purchases_confirmed_date ON core.purchases (purchase_date) WHERE status = 'CONFIRMED';
CREATE INDEX IF NOT EXISTS ix_purchase_items_product ON core.purchase_items (product_id);

-- Inventario
CREATE INDEX IF NOT EXISTS ix_stock_levels_warehouse ON core.stock_levels (warehouse_id);
CREATE INDEX IF NOT EXISTS ix_stock_movements_product_time
    ON core.stock_movements (product_id, warehouse_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_stock_movements_time ON core.stock_movements (occurred_at);
CREATE INDEX IF NOT EXISTS ix_stock_movements_type_time ON core.stock_movements (movement_type, occurred_at);

-- Auditoria
CREATE INDEX IF NOT EXISTS ix_quality_results_check
    ON audit.quality_results (check_name, checked_at DESC);
