"""CLI del proyecto.

Uso:
    python -m src.pipeline schema
    python -m src.pipeline seed --reset
    python -m src.pipeline quality
    python -m src.pipeline queries
    python -m src.pipeline demo
    python -m src.pipeline refresh
    python -m src.pipeline benchmark
    python -m src.pipeline metabase
    python -m src.pipeline info
    python -m src.pipeline all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import psycopg

from .config import ROOT
from .db import apply_sql_file, connect, fetch_all, fetch_one
from .seed import SeedOptions, reset_database, seed_database

SCHEMA_FILES = sorted((ROOT / "sql" / "00_schema").glob("*.sql"))
QUERY_FILES = sorted((ROOT / "sql" / "30_queries").glob("*.sql"))
CHECKS_FILE = ROOT / "sql" / "20_checks" / "01_quality_checks.sql"


def _truncate(value: Any, width: int = 46) -> str:
    text = "" if value is None else str(value).replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def print_rows(rows: Sequence[dict[str, Any]], limit: int = 30) -> None:
    if not rows:
        print("(sin filas)")
        return
    columns = list(rows[0].keys())
    widths = []
    for column in columns:
        width = max(
            len(column),
            max(len(_truncate(row.get(column), 46)) for row in rows[:limit]),
        )
        widths.append(min(width, 46))

    header = " | ".join(column.ljust(widths[i]) for i, column in enumerate(columns))
    print(header)
    print("-+-".join("-" * width for width in widths))
    for row in rows[:limit]:
        print(" | ".join(_truncate(row.get(column), 46).ljust(widths[i])
                         for i, column in enumerate(columns)))
    if len(rows) > limit:
        print(f"... ({len(rows):,} filas en total, mostrando {limit})")


def _connect_or_exit() -> psycopg.Connection:
    try:
        return connect()
    except psycopg.OperationalError as exc:
        print("No se pudo conectar a PostgreSQL.", file=sys.stderr)
        print(f"Detalle: {exc}", file=sys.stderr)
        print("Verifique que Docker este activo y ejecute: docker compose up -d", file=sys.stderr)
        raise SystemExit(2)


def cmd_schema(_: argparse.Namespace) -> int:
    if not SCHEMA_FILES:
        print("No se encontraron archivos en sql/00_schema", file=sys.stderr)
        return 1
    conn = _connect_or_exit()
    try:
        for path in SCHEMA_FILES:
            print(f"aplicando {path.name} ...", end=" ", flush=True)
            apply_sql_file(conn, path)
            print("ok")
    finally:
        conn.close()
    print("Esquema aplicado. Siguiente paso: python -m src.pipeline seed --reset")
    return 0


def cmd_reset(_: argparse.Namespace) -> int:
    conn = _connect_or_exit()
    try:
        print("Borrando datos operativos ...", end=" ", flush=True)
        reset_database(conn)
        print("ok")
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW reporting.mv_ventas_mensuales")
            cur.execute("REFRESH MATERIALIZED VIEW reporting.mv_ventas_categoria_mes")
        conn.commit()
    finally:
        conn.close()
    print("Base vacia, esquema intacto.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    conn = _connect_or_exit()
    try:
        if args.reset:
            print("Reiniciando datos ...", end=" ", flush=True)
            reset_database(conn)
            print("ok")
        print("Generando datos sinteticos (semilla fija) ...")
        stats = seed_database(
            conn,
            SeedOptions(
                seed=args.seed,
                months=args.months,
                sales_per_day=args.sales_per_day,
            ),
        )
    except RuntimeError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print("\nSembrado completo")
    print(f"  periodo          : {stats.start_date} a {stats.end_date}")
    print(f"  productos        : {stats.products:,}")
    print(f"  proveedores      : {stats.suppliers:,}")
    print(f"  clientes         : {stats.customers:,}")
    print(f"  ventas           : {stats.sales:,}")
    print(f"  lineas de venta  : {stats.sale_items:,}")
    print(f"  compras          : {stats.purchases:,}")
    print(f"  movimientos      : {stats.movements:,}")
    print(f"  cancelaciones    : {stats.cancellations:,} ({stats.cancellations / max(stats.sales, 1):.2%})")
    print("\nSiguiente paso: python -m src.pipeline quality")
    return 0


def cmd_quality(_: argparse.Namespace) -> int:
    if not CHECKS_FILE.exists():
        print(f"No existe {CHECKS_FILE}", file=sys.stderr)
        return 1
    conn = _connect_or_exit()
    try:
        sql = CHECKS_FILE.read_text(encoding="utf-8")
        rows = fetch_all(conn, sql)
        print_rows(rows, limit=100)
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO audit.quality_results (check_name, passed, detail)
                VALUES (%s, %s, %s)
                """,
                [(r["check_name"], r["passed"], r["detail"]) for r in rows],
            )
        conn.commit()
        failed = [r for r in rows if not r["passed"]]
        print(f"\n{len(rows) - len(failed)}/{len(rows)} controles aprobados")
        if failed:
            print("Controles fallidos: " + ", ".join(r["check_name"] for r in failed), file=sys.stderr)
            return 1
    finally:
        conn.close()
    return 0


def cmd_queries(args: argparse.Namespace) -> int:
    conn = _connect_or_exit()
    try:
        for path in QUERY_FILES:
            print(f"\n=== {path.name} ===")
            sql = path.read_text(encoding="utf-8")
            rows = fetch_all(conn, sql)
            print_rows(rows, limit=args.limit)
    finally:
        conn.close()
    return 0


def cmd_refresh(_: argparse.Namespace) -> int:
    # CONCURRENTLY requiere autocommit y un indice unico (creado en 06_marts.sql).
    conn = connect(autocommit=True)
    try:
        print("Refrescando marts ...", end=" ", flush=True)
        conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY reporting.mv_ventas_mensuales")
        conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY reporting.mv_ventas_categoria_mes")
        print("ok")
    finally:
        conn.close()
    return 0


def cmd_demo(_: argparse.Namespace) -> int:
    from .demo import run_demo

    conn = _connect_or_exit()
    try:
        run_demo(conn)
    finally:
        conn.close()
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from .benchmark import run_benchmark

    conn = _connect_or_exit()
    try:
        run_benchmark(conn, output=ROOT / "docs" / "06_performance.md", runs=args.runs)
    finally:
        conn.close()
    return 0


def cmd_metabase(_: argparse.Namespace) -> int:
    from .setup_metabase import setup_metabase

    setup_metabase()
    return 0


def cmd_info(_: argparse.Namespace) -> int:
    conn = _connect_or_exit()
    try:
        counts = fetch_one(
            conn,
            """
            SELECT
                (SELECT count(*) FROM core.products)   AS productos,
                (SELECT count(*) FROM core.customers)  AS clientes,
                (SELECT count(*) FROM core.suppliers)  AS proveedores,
                (SELECT count(*) FROM core.sales)      AS ventas,
                (SELECT count(*) FROM core.sale_items) AS lineas,
                (SELECT count(*) FROM core.purchases)  AS compras,
                (SELECT count(*) FROM core.stock_movements) AS movimientos
            """,
        )
        print_rows([counts] if counts else [])
        totals = fetch_one(
            conn,
            """
            SELECT
                count(*)                         AS ventas_confirmadas,
                round(sum(total), 2)             AS ingresos,
                round(sum(total) / count(*), 2)  AS ticket_promedio,
                min(sale_date)::date             AS primera_venta,
                max(sale_date)::date             AS ultima_venta
              FROM core.sales
             WHERE status = 'CONFIRMED'
            """,
        )
        print()
        print_rows([totals] if totals else [])
        stock = fetch_one(
            conn,
            """
            SELECT
                count(*) AS productos_almacen,
                sum(quantity) AS unidades,
                round(sum(quantity * p.unit_cost), 2) AS valor_inventario
              FROM core.stock_levels sl
              JOIN core.products p USING (product_id)
            """,
        )
        print()
        print_rows([stock] if stock else [])
    finally:
        conn.close()
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    conn = _connect_or_exit()
    try:
        for path in SCHEMA_FILES:
            apply_sql_file(conn, path)
        existing = fetch_one(conn, "SELECT count(*) AS n FROM core.products")
        has_data = bool(existing and existing["n"] > 0)
        if args.reset or not has_data:
            if has_data:
                reset_database(conn)
            print("Sembrando datos ...")
            stats = seed_database(conn, SeedOptions())
            print(f"Listo: {stats.sales:,} ventas, {stats.movements:,} movimientos.")
        else:
            print("Datos existentes: se omite el sembrado (use --reset para regenerar).")
    finally:
        conn.close()

    if cmd_quality(args) != 0:
        return 1
    cmd_refresh(args)
    return cmd_queries(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.pipeline",
        description="Sistema de inventario y ventas multi-almacen (PostgreSQL).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("schema", help="Aplica el DDL del esquema")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("reset", help="Borra datos y reinicia identidades")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("seed", help="Genera datos sinteticos")
    p.add_argument("--reset", action="store_true", help="Borra antes de sembrar")
    p.add_argument("--seed", type=int, default=42, help="Semilla aleatoria (default: 42)")
    p.add_argument("--months", type=int, default=24, help="Meses a generar (default: 24)")
    p.add_argument("--sales-per-day", type=int, default=9, help="Ventas base por dia (default: 9)")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("quality", help="Ejecuta los controles de calidad")
    p.set_defaults(func=cmd_quality)

    p = sub.add_parser("queries", help="Ejecuta las consultas de negocio")
    p.add_argument("--limit", type=int, default=20, help="Filas a mostrar por consulta")
    p.set_defaults(func=cmd_queries)

    p = sub.add_parser("demo", help="Demostracion de venta, stock y cancelacion")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("refresh", help="Refresca las vistas materializadas")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("benchmark", help="Mide planes con y sin indices")
    p.add_argument("--runs", type=int, default=5, help="Repeticiones por consulta")
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("metabase", help="Configura Metabase por API (requiere contenedor activo)")
    p.set_defaults(func=cmd_metabase)

    p = sub.add_parser("info", help="Resumen de volumenes de la base")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("all", help="Esquema + seed si esta vacio + calidad + consultas")
    p.add_argument("--reset", action="store_true", help="Regenera los datos")
    p.set_defaults(func=cmd_all, limit=20)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
