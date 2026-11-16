"""Acceso a PostgreSQL.

- apply_sql_file: ejecuta scripts con varias sentencias (DDL).
- fetch_all / execute: consultas parametrizadas con filas tipo dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg import ClientCursor
from psycopg.rows import dict_row

from .config import settings


def connect(*, autocommit: bool = False, dbname: str | None = None) -> psycopg.Connection:
    params = dict(settings.conninfo)
    if dbname:
        params["dbname"] = dbname
    conn = psycopg.connect(**params, autocommit=autocommit, row_factory=dict_row)
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'America/Lima'")
    if not autocommit:
        conn.commit()
    return conn


def apply_sql_file(conn: psycopg.Connection, path: str | Path) -> None:
    """Ejecuta un archivo SQL con una o varias sentencias.

    ClientCursor usa el protocolo simple de PostgreSQL, que permite
    multiples comandos en una sola llamada (necesario para los scripts DDL).
    """
    sql = Path(path).read_text(encoding="utf-8")
    # ClientCursor (psycopg3) usa el protocolo simple y acepta varios comandos.
    with ClientCursor(conn) as cur:
        cur.execute(sql)
    if not conn.autocommit:
        conn.commit()


def fetch_all(
    conn: psycopg.Connection,
    sql: str,
    params: Iterable[Any] | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return []
        return cur.fetchall()


def fetch_one(
    conn: psycopg.Connection,
    sql: str,
    params: Iterable[Any] | dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


def execute(
    conn: psycopg.Connection,
    sql: str,
    params: Iterable[Any] | dict[str, Any] | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
    if not conn.autocommit:
        conn.commit()
