"""Benchmark reproducible con EXPLAIN (ANALYZE, BUFFERS).

Mide tres consultas:
  1. selectiva por producto/almacen en los ultimos 30 dias,
  2. rango de un mes de ventas,
  3. agregacion global de productos.

Para cada una compara con el indice disponible y sin el. No se afirma que
un indice siempre ayude: en agregaciones globales el scan secuencial suele
ser la mejor opcion a este volumen.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from .db import fetch_all, fetch_one

INDEX_DDL: dict[str, str] = {
    "core.ix_stock_movements_product_time": (
        "CREATE INDEX IF NOT EXISTS ix_stock_movements_product_time "
        "ON core.stock_movements (product_id, warehouse_id, occurred_at DESC)"
    ),
    "core.ix_stock_movements_time": (
        "CREATE INDEX IF NOT EXISTS ix_stock_movements_time "
        "ON core.stock_movements (occurred_at)"
    ),
    "core.ix_stock_movements_type_time": (
        "CREATE INDEX IF NOT EXISTS ix_stock_movements_type_time "
        "ON core.stock_movements (movement_type, occurred_at)"
    ),
    "core.ix_sales_confirmed_date": (
        "CREATE INDEX IF NOT EXISTS ix_sales_confirmed_date "
        "ON core.sales (sale_date) WHERE status = 'CONFIRMED'"
    ),
    "core.ix_sales_status_date": (
        "CREATE INDEX IF NOT EXISTS ix_sales_status_date "
        "ON core.sales (status, sale_date)"
    ),
    "core.ix_sale_items_product": (
        "CREATE INDEX IF NOT EXISTS ix_sale_items_product "
        "ON core.sale_items (product_id)"
    ),
}


@dataclass
class Scenario:
    key: str
    name: str
    sql: str
    indexes_to_drop: list[str]
    note: str


@dataclass
class Measurement:
    median_ms: float
    min_ms: float
    max_ms: float
    node_types: str


def _plan_json(row: dict[str, Any]) -> list[dict[str, Any]]:
    value = row.get("QUERY PLAN")
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        return [value]
    return list(value or [])


def _node_types(node: dict[str, Any], seen: list[str]) -> None:
    node_type = node.get("Node Type")
    if node_type and node_type not in seen:
        seen.append(node_type)
    for child in node.get("Plans", []) or []:
        _node_types(child, seen)


def _measure(conn: psycopg.Connection, sql: str, runs: int) -> Measurement:
    conn.execute("SELECT 1").fetchone()
    conn.commit()

    # Calentamiento: no se contabiliza.
    conn.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}").fetchone()
    conn.commit()

    times: list[float] = []
    nodes: list[str] = []
    for _ in range(max(1, runs)):
        row = conn.execute(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"
        ).fetchone()
        plan = _plan_json(row)
        execution_time = float(plan[0].get("Execution Time", 0.0))
        times.append(execution_time)
        nodes = []
        _node_types(plan[0].get("Plan", {}), nodes)
        conn.commit()

    return Measurement(
        median_ms=round(statistics.median(times), 3),
        min_ms=round(min(times), 3),
        max_ms=round(max(times), 3),
        node_types=" -> ".join(nodes),
    )


def _drop_indexes(conn: psycopg.Connection, indexes: list[str]) -> None:
    for index in indexes:
        conn.execute(f"DROP INDEX IF EXISTS {index}")
    conn.commit()


def _restore_indexes(conn: psycopg.Connection, indexes: list[str]) -> None:
    for index in indexes:
        conn.execute(INDEX_DDL[index])
    conn.commit()


def _build_scenarios(conn: psycopg.Connection) -> list[Scenario]:
    target = fetch_one(
        conn,
        """
        SELECT product_id, warehouse_id, count(*) AS n
          FROM core.stock_movements
         WHERE occurred_at >= now() - interval '30 days'
         GROUP BY 1, 2
         ORDER BY n DESC
         LIMIT 1
        """,
    )
    if not target:
        raise RuntimeError("No hay movimientos recientes para el benchmark. Siembre datos primero.")
    product_id = int(target["product_id"])
    warehouse_id = int(target["warehouse_id"])

    selective = f"""
        SELECT product_id, warehouse_id, sum(quantity_delta) AS net_units
          FROM core.stock_movements
         WHERE product_id = {product_id}
           AND warehouse_id = {warehouse_id}
           AND occurred_at >= now() - interval '30 days'
         GROUP BY 1, 2
    """

    monthly_range = """
        SELECT date_trunc('month', s.sale_date)::date AS month,
               count(DISTINCT s.sale_id) AS sales,
               sum(si.line_subtotal) AS revenue
          FROM core.sales s
          JOIN core.sale_items si ON si.sale_id = s.sale_id
         WHERE s.status = 'CONFIRMED'
           AND s.sale_date >= date_trunc('month', now()) - interval '1 month'
           AND s.sale_date <  date_trunc('month', now())
         GROUP BY 1
    """

    global_agg = """
        SELECT p.product_id, p.sku, sum(si.line_subtotal) AS revenue
          FROM core.sales s
          JOIN core.sale_items si ON si.sale_id = s.sale_id
          JOIN core.products p    ON p.product_id = si.product_id
         WHERE s.status = 'CONFIRMED'
         GROUP BY 1, 2
         ORDER BY revenue DESC
         LIMIT 10
    """

    return [
        Scenario(
            key="selectiva",
            name=f"Movimientos de un producto/almacen (id {product_id}/{warehouse_id}, 30 dias)",
            sql=selective,
            indexes_to_drop=[
                "core.ix_stock_movements_product_time",
                "core.ix_stock_movements_time",
                "core.ix_stock_movements_type_time",
            ],
            note="Filtro muy selectivo: hay que quitar todos los indices que sirven al libro mayor para ver el plan secuencial real.",
        ),
        Scenario(
            key="rango",
            name="Ventas confirmadas del mes anterior",
            sql=monthly_range,
            indexes_to_drop=[
                "core.ix_sales_confirmed_date",
                "core.ix_sales_status_date",
            ],
            note="Rango de fechas con filtro por estado: hay dos indices candidatos, se desactivan ambos.",
        ),
        Scenario(
            key="global",
            name="Top 10 productos por ingreso (todo el periodo)",
            sql=global_agg,
            indexes_to_drop=[
                "core.ix_sale_items_product",
                "core.ix_sales_confirmed_date",
                "core.ix_sales_status_date",
            ],
            note="Agregacion global: el costo dominante es leer y agrupar, no buscar filas.",
        ),
    ]


def run_benchmark(
    conn: psycopg.Connection,
    output: Path,
    runs: int = 5,
) -> Path:
    version = fetch_one(conn, "SELECT version() AS v")["v"]
    counts = fetch_one(
        conn,
        """
        SELECT
            (SELECT count(*) FROM core.sales) AS sales,
            (SELECT count(*) FROM core.sale_items) AS sale_items,
            (SELECT count(*) FROM core.stock_movements) AS movements
        """,
    )
    scenarios = _build_scenarios(conn)
    results: list[dict[str, Any]] = []

    for scenario in scenarios:
        print(f"midiendo: {scenario.name} ...", end=" ", flush=True)
        with_index = _measure(conn, scenario.sql, runs)
        _drop_indexes(conn, scenario.indexes_to_drop)
        try:
            without_index = _measure(conn, scenario.sql, runs)
        finally:
            _restore_indexes(conn, scenario.indexes_to_drop)
        speedup = (
            round(without_index.median_ms / with_index.median_ms, 2)
            if with_index.median_ms > 0 else None
        )
        results.append({
            "scenario": scenario,
            "with_index": with_index,
            "without_index": without_index,
            "speedup": speedup,
        })
        print(
            f"con indice {with_index.median_ms:.3f} ms | "
            f"sin indice {without_index.median_ms:.3f} ms | "
            f"x{speedup if speedup is not None else 'n/d'}"
        )

    # Verifica que los indices quedaron restaurados.
    missing = [
        key for key in INDEX_DDL
        if not fetch_one(
            conn,
            "SELECT 1 AS ok FROM pg_indexes WHERE schemaname = split_part(%s, '.', 1) "
            "AND indexname = split_part(%s, '.', 2)",
            (key, key),
        )
    ]
    if missing:
        raise RuntimeError(f"No se restauraron los indices: {missing}")

    lines: list[str] = []
    lines.append("# Rendimiento y planes de ejecucion")
    lines.append("")
    lines.append(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')} (America/Lima)")
    lines.append("")
    lines.append("## Entorno")
    lines.append("")
    lines.append(f"- {version}")
    lines.append(
        f"- Volumen: {counts['sales']:,} ventas, {counts['sale_items']:,} lineas, "
        f"{counts['movements']:,} movimientos de stock."
    )
    lines.append("- Entorno local en Docker, cache caliente despues de un calentamiento.")
    lines.append(f"- Medicion: mediana de {runs} ejecuciones de `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.")
    lines.append("")
    lines.append("## Resultados")
    lines.append("")
    lines.append("| Consulta | Con indice (ms) | Sin indice (ms) | Aceleracion | Plan con indice | Plan sin indice |")
    lines.append("|---|---:|---:|---:|---|---|")
    for result in results:
        scenario: Scenario = result["scenario"]
        speedup = result["speedup"]
        lines.append(
            f"| {scenario.name} | {result['with_index'].median_ms:.3f} | "
            f"{result['without_index'].median_ms:.3f} | "
            f"{f'x{speedup}' if speedup is not None else 'n/d'} | "
            f"{result['with_index'].node_types} | {result['without_index'].node_types} |"
        )
    lines.append("")
    lines.append("## Lectura")
    lines.append("")
    by_key = {result["scenario"].key: result for result in results}

    def _reading(key: str, with_text: str, without_text: str) -> str:
        result = by_key.get(key)
        if not result:
            return "- Sin medicion para este escenario."
        with_ms = result["with_index"].median_ms
        without_ms = result["without_index"].median_ms
        speedup = result["speedup"]
        if speedup is None:
            verdict = "No se pudo calcular la aceleracion."
        elif speedup >= 1.2:
            verdict = (
                f"El indice aporta: {speedup:.2f}x mas rapido "
                f"({with_ms:.3f} ms vs {without_ms:.3f} ms)."
            )
        elif speedup <= 0.85:
            verdict = (
                f"A este volumen el indice no aporta: {speedup:.2f}x, es decir, "
                f"ligeramente mas lento que el scan secuencial "
                f"({with_ms:.3f} ms vs {without_ms:.3f} ms). "
                "El planeador prefiere leer la tabla completa."
            )
        else:
            verdict = (
                f"Diferencia marginal ({with_ms:.3f} ms vs {without_ms:.3f} ms, "
                f"{speedup:.2f}x): ambos planes cuestan practicamente lo mismo."
            )
        return f"- {with_text} {verdict[0].lower() + verdict[1:]} {without_text}"

    lines.append(
        _reading(
            "selectiva",
            "Consulta selectiva del libro mayor:",
            f"Plan con indices: {by_key['selectiva']['with_index'].node_types}; "
            f"sin indices: {by_key['selectiva']['without_index'].node_types}.",
        )
    )
    lines.append(
        _reading(
            "rango",
            "Ventas de un mes:",
            f"Plan con indices: {by_key['rango']['with_index'].node_types}; "
            f"sin indices: {by_key['rango']['without_index'].node_types}.",
        )
    )
    lines.append(
        _reading(
            "global",
            "Top 10 productos por ingreso:",
            f"Plan con indices: {by_key['global']['with_index'].node_types}; "
            f"sin indices: {by_key['global']['without_index'].node_types}.",
        )
    )
    lines.append("")
    lines.append(
        "- En una agregacion global el costo dominante es leer y agrupar casi toda la tabla. "
        "Ahi un indice no reduce el trabajo y puede hasta estorbar si el planeador lo elige por error."
    )
    lines.append(
        "- Conclusion honesta: indexar no es automatico. Primero se mide; se indexa lo que filtra, "
        "y no se asume que un indice siempre acelera."
    )
    lines.append("")
    lines.append("## Notas")
    lines.append("")
    lines.append("- Los tiempos absolutos dependen de la maquina y de Docker; la comparacion relativa es la util.")
    lines.append("- Para cada escenario se quitaron **todos** los indices que podian servir la consulta, no uno solo; despues se restauraron uno por uno.")
    lines.append("- `DROP INDEX` y `CREATE INDEX` se ejecutaron en autocommit y se verifico su restauracion al final.")
    lines.append("- Los indices se definen en `sql/00_schema/03_indexes.sql`.")
    lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReporte escrito en {output}")
    return output
