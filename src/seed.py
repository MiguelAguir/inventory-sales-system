"""Generador de datos sinteticos reproducibles.

No usa datos reales: todos los nombres, RUC, clientes y precios son
inventados. La semilla fija permite regenerar exactamente el mismo dataset.

El generador ejercita las funciones reales de la base:
  * fn_register_purchase / fn_register_sale
  * fn_cancel_sale
  * triggers de stock y de totales
Por eso, si el modelo tiene un error, el sembrado falla en vez de esconderlo.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import psycopg

from .db import fetch_one

LIMA = timezone(timedelta(hours=-5))

CATEGORIES: list[tuple[str, str, str | None]] = [
    ("TEC", "Tecnologia", None),
    ("COMP", "Computadoras", "TEC"),
    ("PERI", "Perifericos", "TEC"),
    ("IMPR", "Impresion", "TEC"),
    ("REDES", "Redes", "TEC"),
    ("CONSUM", "Consumibles", "TEC"),
    ("OFI", "Oficina", None),
    ("PAPE", "Papeleria", "OFI"),
    ("ESCR", "Mobiliario", "OFI"),
    ("ARCH", "Archivo", "OFI"),
    ("LIMP", "Limpieza", None),
    ("ASEO", "Aseo", "LIMP"),
    ("QUIM", "Quimicos", "LIMP"),
    ("SEG", "Seguridad", None),
    ("EPP", "Proteccion personal", "SEG"),
    ("HERR", "Herramientas", "SEG"),
]

CATEGORY_WEIGHTS = {
    "COMP": 0.16,
    "PERI": 0.10,
    "IMPR": 0.09,
    "REDES": 0.06,
    "CONSUM": 0.09,
    "PAPE": 0.12,
    "ESCR": 0.06,
    "ARCH": 0.06,
    "ASEO": 0.08,
    "QUIM": 0.05,
    "EPP": 0.07,
    "HERR": 0.06,
}

# (nombre, precio minimo, precio maximo, unidad)
PRODUCT_TEMPLATES: dict[str, list[tuple[str, float, float, str]]] = {
    "COMP": [
        ("Laptop 14 pulgadas Core i5", 2600, 3400, "UND"),
        ("Laptop 15 pulgadas Ryzen 7", 3100, 4200, "UND"),
        ("Desktop Core i5", 2100, 2800, "UND"),
        ("All in One 23.8 pulgadas", 2800, 3600, "UND"),
        ("Mini PC 16GB RAM", 1800, 2400, "UND"),
    ],
    "PERI": [
        ("Monitor 24 pulgadas FHD", 520, 720, "UND"),
        ("Teclado mecanico USB", 120, 220, "UND"),
        ("Mouse inalambrico", 55, 110, "UND"),
        ("Webcam Full HD", 95, 180, "UND"),
        ("Hub USB-C 7 puertos", 110, 210, "UND"),
    ],
    "IMPR": [
        ("Impresora laser monocromatica", 780, 1100, "UND"),
        ("Impresora multifuncional", 1050, 1450, "UND"),
        ("Toner negro compatible", 190, 320, "UND"),
        ("Cartucho de color", 130, 240, "UND"),
        ("Etiquetadora industrial", 260, 420, "UND"),
    ],
    "REDES": [
        ("Router WiFi 6", 380, 620, "UND"),
        ("Switch 24 puertos gigabit", 550, 850, "UND"),
        ("Access point de techo", 310, 520, "UND"),
        ("Cable UTP cat6", 210, 360, "CAJA"),
        ("Patch panel 24 puertos", 120, 220, "UND"),
    ],
    "CONSUM": [
        ("Toner alternativo alta capacidad", 150, 260, "UND"),
        ("Cabezal de impresora", 180, 300, "UND"),
        ("Cinta correctora", 18, 32, "PACK"),
        ("Marcadores de pizarra", 28, 55, "CAJA"),
        ("Borradores de tinta", 15, 30, "PACK"),
    ],
    "PAPE": [
        ("Papel bond A4 75g", 18, 28, "PACK"),
        ("Lapicero azul", 22, 38, "CAJA"),
        ("Resaltador fluorescente", 16, 30, "CAJA"),
        ("Cuaderno A4 cuadriculado", 9, 18, "UND"),
        ("Grapas standard", 7, 14, "CAJA"),
    ],
    "ESCR": [
        ("Silla ergonomica con malla", 420, 650, "UND"),
        ("Escritorio de melamina 1.2m", 380, 620, "UND"),
        ("Archivador metalico 4 gavetas", 520, 780, "UND"),
        ("Lampara LED de escritorio", 75, 140, "UND"),
        ("Pizarra acrilica 90x120", 180, 310, "UND"),
    ],
    "ARCH": [
        ("Folder manila oficio", 12, 22, "PACK"),
        ("Caja de archivo plastica", 18, 35, "UND"),
        ("Separadores plasticos", 10, 20, "PACK"),
        ("Perforador de 2 huecos", 28, 55, "UND"),
        ("Engrapadora metalica", 24, 48, "UND"),
    ],
    "ASEO": [
        ("Papel higienico institucional", 32, 55, "PACK"),
        ("Jabon liquido para manos", 14, 26, "LT"),
        ("Alcohol etilico 70", 12, 22, "LT"),
        ("Desinfectante multisuperficie", 16, 30, "LT"),
        ("Toallas de papel", 28, 48, "PACK"),
    ],
    "QUIM": [
        ("Lejia concentrada", 9, 18, "LT"),
        ("Detergente industrial", 22, 38, "KG"),
        ("Cera para piso", 26, 45, "LT"),
        ("Limpiador desengrasante", 18, 34, "LT"),
        ("Guantes de limpieza", 12, 24, "PACK"),
    ],
    "EPP": [
        ("Casco de seguridad", 28, 52, "UND"),
        ("Chaleco reflectivo", 22, 42, "UND"),
        ("Guantes anticorte", 35, 65, "PACK"),
        ("Lentes de seguridad", 18, 38, "UND"),
        ("Botas de seguridad", 95, 165, "UND"),
    ],
    "HERR": [
        ("Taladro percutor 650W", 210, 340, "UND"),
        ("Juego de destornilladores", 65, 120, "UND"),
        ("Cinta metrica 5m", 18, 34, "UND"),
        ("Alicate universal", 32, 58, "UND"),
        ("Caja de herramientas", 85, 150, "UND"),
    ],
}

SUPPLIER_BASES = [
    "Distribuidora Andina",
    "Comercial Lima",
    "Importaciones del Pacifico",
    "Suministros Peru",
    "Tecnologia Total",
    "Oficina Global",
    "Redes y Servicios",
    "Papelera Nacional",
    "Limpieza Integral",
    "Seguridad Industrial",
    "Proveedora Norte",
    "Comercial Arequipa",
    "Importadora Sur",
    "Soluciones Office",
    "Abastecimientos Centro",
    "Equipos y Accesorios",
    "Corporacion Selva",
    "Distribuidora Piura",
    "Suministros Cusco",
    "Comercial Trujillo",
]

SEASONALITY = {1: 0.55, 2: 0.80, 3: 0.95, 4: 1.00, 5: 1.05, 6: 1.00,
               7: 0.95, 8: 1.00, 9: 1.00, 10: 1.05, 11: 1.45, 12: 1.55}
WEEKDAY_FACTOR = {0: 1.15, 1: 1.10, 2: 1.10, 3: 1.10, 4: 1.15, 5: 0.85, 6: 0.35}


@dataclass(frozen=True)
class SeedOptions:
    seed: int = 42
    months: int = 24
    end_date: date | None = None
    sales_per_day: int = 9
    cancellation_rate: float = 0.03
    average_lines: float = 2.2


@dataclass
class ProductSeed:
    product_id: int
    sku: str
    name: str
    category_code: str
    category_id: int
    unit: str
    unit_price: float
    unit_cost: float
    weight: float = 0.0
    min_stock: int = 0
    supplier_ids: list[int] = field(default_factory=list)
    preferred_supplier_id: int | None = None


@dataclass
class SupplierSeed:
    supplier_id: int
    name: str
    lead_time_days: int


@dataclass
class SeedStats:
    products: int = 0
    suppliers: int = 0
    customers: int = 0
    sales: int = 0
    sale_items: int = 0
    purchases: int = 0
    movements: int = 0
    cancellations: int = 0
    start_date: date | None = None
    end_date: date | None = None


def _month_shift(day: date, delta_months: int) -> date:
    total = day.year * 12 + (day.month - 1) + delta_months
    return date(total // 12, total % 12 + 1, 1)


def _weighted_choice(rng: random.Random, items: list[Any], weights: list[float]) -> Any:
    return rng.choices(items, weights=weights, k=1)[0]


def _chunked(seq: list[Any], size: int = 1000) -> list[list[Any]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def reset_database(conn: psycopg.Connection) -> None:
    """Borra los datos operativos y reinicia identidades. No toca el esquema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE TABLE
                core.stock_movements,
                core.sale_items,
                core.purchase_items,
                core.sales,
                core.purchases,
                core.stock_levels,
                core.product_suppliers,
                core.products,
                core.categories,
                core.customers,
                core.suppliers,
                core.warehouses,
                audit.quality_results
            RESTART IDENTITY CASCADE
            """
        )
        cur.execute("ALTER SEQUENCE core.sale_number_seq RESTART WITH 1")
        cur.execute("ALTER SEQUENCE core.purchase_number_seq RESTART WITH 1")
    if not conn.autocommit:
        conn.commit()


def _insert_categories(conn: psycopg.Connection) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for code, name, parent_code in CATEGORIES:
        parent_id = mapping.get(parent_code) if parent_code else None
        row = conn.execute(
            """
            INSERT INTO core.categories (parent_id, code, name)
            VALUES (%s, %s, %s)
            RETURNING category_id
            """,
            (parent_id, code, name),
        ).fetchone()
        mapping[code] = row["category_id"]
    return mapping


def _insert_warehouses(conn: psycopg.Connection) -> list[int]:
    ids: list[int] = []
    for code, name, address in [
        ("WH-CENTRAL", "Almacen Central", "Av. Los Almacenes 100, Lima"),
        ("WH-SUR", "Almacen Sur", "Av. Industrial 250, Arequipa"),
    ]:
        row = conn.execute(
            """
            INSERT INTO core.warehouses (code, name, address)
            VALUES (%s, %s, %s)
            RETURNING warehouse_id
            """,
            (code, name, address),
        ).fetchone()
        ids.append(row["warehouse_id"])
    return ids


def _insert_suppliers(conn: psycopg.Connection) -> list[SupplierSeed]:
    suppliers: list[SupplierSeed] = []
    for i, base in enumerate(SUPPLIER_BASES, start=1):
        name = f"{base} {i:02d} S.A.C."
        ruc = f"20{100000000 + i:09d}"[:11]
        lead_time = 3 + (i % 5) * 3
        row = conn.execute(
            """
            INSERT INTO core.suppliers (ruc, name, email, phone, lead_time_days)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING supplier_id
            """,
            (ruc, name, f"ventas{i:02d}@example.com", f"9{1000000 + i:07d}", lead_time),
        ).fetchone()
        suppliers.append(
            SupplierSeed(
                supplier_id=row["supplier_id"],
                name=name,
                lead_time_days=lead_time,
            )
        )
    return suppliers


def _insert_products(
    conn: psycopg.Connection,
    categories: dict[str, int],
    suppliers: list[SupplierSeed],
    rng: random.Random,
) -> list[ProductSeed]:
    products: list[ProductSeed] = []
    for category_code, templates in PRODUCT_TEMPLATES.items():
        category_id = categories[category_code]
        for index, (base_name, price_min, price_max, unit) in enumerate(templates, start=1):
            sku = f"{category_code}-{index:03d}"
            price = round(rng.uniform(price_min, price_max), 2)
            margin = rng.uniform(0.28, 0.55)
            cost = round(price / (1 + margin), 2)
            # El precio de catalogo debe cubrir el costo.
            price = max(price, round(cost * 1.05, 2))
            name = f"{base_name} marca sintetica {index:02d}"
            row = conn.execute(
                """
                INSERT INTO core.products (sku, name, category_id, unit, unit_price, unit_cost, min_stock)
                VALUES (%s, %s, %s, %s, %s, %s, 0)
                RETURNING product_id
                """,
                (sku, name, category_id, unit, price, cost),
            ).fetchone()
            product = ProductSeed(
                product_id=row["product_id"],
                sku=sku,
                name=name,
                category_code=category_code,
                category_id=category_id,
                unit=unit,
                unit_price=price,
                unit_cost=cost,
            )

            supplier_count = rng.randint(1, 3)
            chosen = rng.sample(suppliers, k=supplier_count)
            for position, supplier in enumerate(chosen):
                is_preferred = position == 0
                conn.execute(
                    """
                    INSERT INTO core.product_suppliers (
                        product_id, supplier_id, supplier_sku, unit_cost, lead_time_days, is_preferred
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        product.product_id,
                        supplier.supplier_id,
                        f"{supplier.supplier_id:02d}-{sku}",
                        round(cost * rng.uniform(0.96, 1.08), 2),
                        max(1, supplier.lead_time_days + rng.randint(-2, 4)),
                        is_preferred,
                    ),
                )
                product.supplier_ids.append(supplier.supplier_id)
                if is_preferred:
                    product.preferred_supplier_id = supplier.supplier_id
            products.append(product)

    # Popularidad Pareto dentro de cada categoria, conservando el peso de categoria.
    total = 0.0
    for category_code, category_weight in CATEGORY_WEIGHTS.items():
        group = [p for p in products if p.category_code == category_code]
        raw = [rng.paretovariate(1.35) for _ in group]
        raw_total = sum(raw)
        for product, value in zip(group, raw):
            product.weight = category_weight * value / raw_total
            total += product.weight
    for product in products:
        product.weight /= total

    return products


def _insert_customers(conn: psycopg.Connection, rng: random.Random) -> list[int]:
    ids: list[int] = []
    for i in range(1, 201):
        if i <= 70:
            doc_type = "RUC"
            doc_number = f"20{900000000 + i:09d}"[:11]
            name = f"Empresa Sintetica {i:03d} S.A.C."
            email = f"compras{i:03d}@example.com"
        else:
            doc_type = "DNI"
            doc_number = f"{70000000 + i:08d}"[:8]
            name = f"Cliente Sintetico {i:03d}"
            email = f"cliente{i:03d}@example.com"
        row = conn.execute(
            """
            INSERT INTO core.customers (doc_type, doc_number, name, email, phone)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING customer_id
            """,
            (doc_type, doc_number, name, email, f"9{2000000 + i:07d}"),
        ).fetchone()
        ids.append(row["customer_id"])
    return ids


def _opening_stock(
    conn: psycopg.Connection,
    products: list[ProductSeed],
    warehouses: list[int],
    daily_units: dict[int, float],
    opening_date: date,
    rng: random.Random,
) -> dict[tuple[int, int], int]:
    occurred_at = datetime.combine(opening_date, time(18, 0), tzinfo=LIMA) - timedelta(days=1)
    stock: dict[tuple[int, int], int] = {}
    rows: list[tuple[Any, ...]] = []

    for product in products:
        for warehouse_id in warehouses:
            base = daily_units[product.product_id] * 0.35
            quantity = max(product.min_stock * 2, math.ceil(base * 35)) + rng.randint(0, 10)
            stock[(product.product_id, warehouse_id)] = quantity
            rows.append(
                (
                    product.product_id,
                    warehouse_id,
                    "ADJUSTMENT_IN",
                    quantity,
                    product.unit_cost,
                    occurred_at,
                    "Saldo inicial de inventario",
                )
            )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO core.stock_movements (
                product_id, warehouse_id, movement_type, quantity_delta,
                unit_cost, occurred_at, reference_note
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
    return stock


def _register_purchase_group(
    conn: psycopg.Connection,
    supplier_id: int,
    warehouse_id: int,
    purchase_dt: datetime,
    items: list[dict[str, Any]],
    stock: dict[tuple[int, int], int],
) -> None:
    if not items:
        return
    conn.execute(
        "SELECT core.fn_register_purchase(%s, %s, %s::jsonb, %s)",
        (supplier_id, warehouse_id, json.dumps(items), purchase_dt),
    ).fetchone()
    for item in items:
        key = (item["product_id"], warehouse_id)
        stock[key] = stock.get(key, 0) + item["quantity"]


def _monthly_replenishment(
    conn: psycopg.Connection,
    products_by_id: dict[int, ProductSeed],
    warehouses: list[int],
    warehouse_share: dict[int, float],
    daily_units: dict[int, float],
    stock: dict[tuple[int, int], int],
    day: date,
    rng: random.Random,
) -> None:
    purchase_dt = datetime.combine(day, time(8, 0), tzinfo=LIMA)
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}

    for product in products_by_id.values():
        supplier_id = product.preferred_supplier_id
        if supplier_id is None:
            continue
        for warehouse_id in warehouses:
            key = (product.product_id, warehouse_id)
            available = stock.get(key, 0)
            target = max(
                product.min_stock * 2,
                math.ceil(daily_units[product.product_id] * warehouse_share[warehouse_id] * 30)
                + product.min_stock,
            )
            if available < max(product.min_stock, 5):
                quantity = max(target - available, 1)
                grouped.setdefault((supplier_id, warehouse_id), []).append(
                    {
                        "product_id": product.product_id,
                        "quantity": quantity,
                        "unit_cost": round(product.unit_cost * rng.uniform(0.96, 1.05), 2),
                    }
                )

    for (supplier_id, warehouse_id), items in grouped.items():
        _register_purchase_group(conn, supplier_id, warehouse_id, purchase_dt, items, stock)


def seed_database(conn: psycopg.Connection, options: SeedOptions | None = None) -> SeedStats:
    options = options or SeedOptions()
    rng = random.Random(options.seed)
    stats = SeedStats()

    existing = fetch_one(conn, "SELECT count(*) AS n FROM core.products")
    if existing and existing["n"] > 0:
        raise RuntimeError(
            "La base ya tiene productos. Use `python -m src.pipeline seed --reset` "
            "o `python -m src.pipeline reset` antes de sembrar."
        )

    end = options.end_date or (date.today() - timedelta(days=1))
    start = _month_shift(end.replace(day=1), -(options.months - 1))
    stats.start_date = start
    stats.end_date = end

    with conn.transaction():
        conn.execute("SET LOCAL synchronous_commit = off")

        categories = _insert_categories(conn)
        warehouses = _insert_warehouses(conn)
        suppliers = _insert_suppliers(conn)
        products = _insert_products(conn, categories, suppliers, rng)
        customers = _insert_customers(conn, rng)

        stats.products = len(products)
        stats.suppliers = len(suppliers)
        stats.customers = len(customers)

        total_units_per_day = options.sales_per_day * options.average_lines
        daily_units = {
            p.product_id: total_units_per_day * p.weight for p in products
        }

        for product in products:
            product.min_stock = max(3, round(daily_units[product.product_id] * 10))
            conn.execute(
                "UPDATE core.products SET min_stock = %s WHERE product_id = %s",
                (product.min_stock, product.product_id),
            )

        warehouse_share = {warehouses[0]: 0.68, warehouses[1]: 0.32}
        stock = _opening_stock(conn, products, warehouses, daily_units, start, rng)

        products_by_id = {p.product_id: p for p in products}
        product_ids = [p.product_id for p in products]
        product_weights = [p.weight for p in products]
        customer_weights = [rng.paretovariate(1.5) for _ in customers]
        unit_choices = [1, 2, 3, 5, 10]
        unit_probabilities = [0.45, 0.25, 0.15, 0.10, 0.05]

        day = start
        last_progress = 0
        while day <= end:
            if day.day == 1 or day == start:
                _monthly_replenishment(
                    conn, products_by_id, warehouses, warehouse_share,
                    daily_units, stock, day, rng,
                )

            factor = SEASONALITY[day.month] * WEEKDAY_FACTOR[day.weekday()]
            expected = options.sales_per_day * factor
            sales_today = max(0, round(expected * rng.uniform(0.65, 1.35)))

            for _ in range(sales_today):
                sale_dt = datetime.combine(
                    day, time(8, 0), tzinfo=LIMA
                ) + timedelta(minutes=rng.randint(0, 600))

                warehouse_id = _weighted_choice(
                    rng,
                    warehouses,
                    [warehouse_share[w] for w in warehouses],
                )
                customer_id = _weighted_choice(rng, customers, customer_weights)
                line_count = rng.choices([1, 2, 3, 4], weights=[0.35, 0.35, 0.20, 0.10], k=1)[0]
                chosen_products = rng.choices(
                    product_ids, weights=product_weights, k=line_count
                )
                # Evita productos repetidos en la misma venta.
                seen: set[int] = set()
                chosen_products = [p for p in chosen_products if not (p in seen or seen.add(p))]
                if not chosen_products:
                    continue

                items: list[dict[str, Any]] = []
                inflation = 1 + 0.0025 * ((sale_dt.year - start.year) * 12 + sale_dt.month - start.month)
                for product_id in chosen_products:
                    product = products_by_id[product_id]
                    quantity = rng.choices(unit_choices, weights=unit_probabilities, k=1)[0]
                    key = (product_id, warehouse_id)

                    if stock.get(key, 0) < quantity:
                        supplier_id = product.preferred_supplier_id
                        if supplier_id is None:
                            raise RuntimeError(f"Producto {product_id} sin proveedor preferido")
                        needed = max(product.min_stock * 2, quantity * 4)
                        purchase_dt = sale_dt - timedelta(hours=2)
                        _register_purchase_group(
                            conn,
                            supplier_id,
                            warehouse_id,
                            purchase_dt,
                            [{
                                "product_id": product_id,
                                "quantity": needed,
                                "unit_cost": round(product.unit_cost * rng.uniform(0.96, 1.05), 2),
                            }],
                            stock,
                        )
                        stats.purchases += 1

                    price = round(
                        product.unit_price * inflation * rng.uniform(0.97, 1.05),
                        2,
                    )
                    discount = rng.choices([0, 5, 10], weights=[0.80, 0.15, 0.05], k=1)[0]
                    items.append(
                        {
                            "product_id": product_id,
                            "quantity": quantity,
                            "unit_price": price,
                            "discount_pct": discount,
                        }
                    )

                sale_id = conn.execute(
                    "SELECT core.fn_register_sale(%s, %s, %s::jsonb, %s)",
                    (customer_id, warehouse_id, json.dumps(items), sale_dt),
                ).fetchone()["fn_register_sale"]

                stats.sales += 1
                stats.sale_items += len(items)
                for item in items:
                    key = (item["product_id"], warehouse_id)
                    stock[key] -= item["quantity"]

                if rng.random() < options.cancellation_rate:
                    cancel_dt = min(
                        sale_dt + timedelta(hours=rng.randint(2, 30)),
                        datetime.now(LIMA) - timedelta(minutes=30),
                    )
                    conn.execute(
                        "SELECT core.fn_cancel_sale(%s, %s)",
                        (sale_id, cancel_dt),
                    )
                    for item in items:
                        key = (item["product_id"], warehouse_id)
                        stock[key] += item["quantity"]
                    stats.cancellations += 1

                if stats.sales - last_progress >= 1000:
                    last_progress = stats.sales
                    print(f"  ventas generadas: {stats.sales:,} (dia {day})")

            day += timedelta(days=1)

        row = fetch_one(
            conn,
            "SELECT count(*) AS n FROM core.stock_movements",
        )
        stats.movements = row["n"] if row else 0
        row = fetch_one(conn, "SELECT count(*) AS n FROM core.purchases")
        stats.purchases = row["n"] if row else stats.purchases

        conn.execute("ANALYZE core.products")
        conn.execute("ANALYZE core.sales")
        conn.execute("ANALYZE core.sale_items")
        conn.execute("ANALYZE core.purchases")
        conn.execute("ANALYZE core.purchase_items")
        conn.execute("ANALYZE core.stock_movements")
        conn.execute("ANALYZE core.stock_levels")

    # Refresco inicial de marts (fuera de la transaccion principal).
    with conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW reporting.mv_ventas_mensuales")
        cur.execute("REFRESH MATERIALIZED VIEW reporting.mv_ventas_categoria_mes")
    if not conn.autocommit:
        conn.commit()

    return stats
