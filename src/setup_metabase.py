"""Configuracion idempotente de Metabase por API.

Crea (si no existen):
  * la conexion a PostgreSQL,
  * una coleccion,
  * seis preguntas nativas,
  * un tablero con esas preguntas.

Tambien habilita el enlace publico del tablero, util para una captura.
Requiere que el contenedor `inventory_metabase` este activo.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .config import settings

BASE = settings.metabase_url.rstrip("/")
HEADERS: dict[str, str] = {}
COLLECTION_NAME = "Inventario y Ventas"
DASHBOARD_NAME = "Inventario y Ventas | Operacion y alertas"
DB_NAME = "Inventario y Ventas (PostgreSQL)"


def _url(path: str) -> str:
    return f"{BASE}{path}"


def _check(response: requests.Response, action: str) -> Any:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{action} fallo ({response.status_code}): {response.text[:800]}"
        )
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def _wait_for_metabase(timeout_seconds: int = 240) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = requests.get(_url("/api/health"), timeout=5)
            if response.status_code == 200:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(3)
    raise RuntimeError(f"Metabase no respondio en {timeout_seconds}s: {last_error}")


def _ensure_setup() -> None:
    properties = _check(
        requests.get(_url("/api/session/properties"), timeout=20),
        "leer propiedades de Metabase",
    )
    token = properties.get("setup-token")
    if not token:
        return

    payload = {
        "token": token,
        "user": {
            "email": settings.metabase_email,
            "first_name": "Data",
            "last_name": "Analyst",
            "password": settings.metabase_password,
            "site_name": "Inventario y Ventas",
        },
        "prefs": {
            "site_name": "Inventario y Ventas",
            "site_locale": "es",
            "allow_tracking": False,
        },
        "database": None,
    }
    _check(requests.post(_url("/api/setup"), json=payload, timeout=120), "configurar Metabase")


def _login() -> None:
    global HEADERS
    session = _check(
        requests.post(
            _url("/api/session"),
            json={"username": settings.metabase_email, "password": settings.metabase_password},
            timeout=30,
        ),
        "iniciar sesion en Metabase",
    )
    session_id = session.get("id") if isinstance(session, dict) else session
    if not session_id:
        raise RuntimeError("Metabase no devolvio un id de sesion")
    HEADERS = {"X-Metabase-Session": session_id}


def _get_collection_items(
    collection_id: int,
    models: tuple[str, ...] = ("card",),
) -> list[dict[str, Any]]:
    # La API espera el parametro `models` repetido, no una lista separada por comas.
    response = requests.get(
        _url(f"/api/collection/{collection_id}/items"),
        params=[("models", model) for model in models] + [("limit", 200)],
        headers=HEADERS,
        timeout=30,
    )
    if response.status_code >= 400:
        return []
    data = response.json()
    if isinstance(data, dict):
        return list(data.get("data") or [])
    return list(data or [])


def _find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("name") == name:
            return item
    return None


def _ensure_database() -> int:
    databases = _check(
        requests.get(_url("/api/database"), headers=HEADERS, timeout=30),
        "listar bases de Metabase",
    )
    rows = databases.get("data") if isinstance(databases, dict) else databases
    for database in rows or []:
        if database.get("name") == DB_NAME:
            return int(database["id"])

    payload = {
        "engine": "postgres",
        "name": DB_NAME,
        "details": {
            "host": "postgres",
            "port": 5432,
            "dbname": settings.dbname,
            "user": settings.user,
            "password": settings.password,
            "ssl": False,
        },
        "is_full_sync": True,
        "is_on_demand": False,
    }
    created = _check(
        requests.post(_url("/api/database"), json=payload, headers=HEADERS, timeout=120),
        "crear conexion de base en Metabase",
    )
    db_id = int(created["id"])
    # Sincronizacion inicial; si falla, Metabase igual sincroniza en segundo plano.
    requests.post(_url(f"/api/database/{db_id}/sync_schema"), headers=HEADERS, timeout=30)
    return db_id


def _ensure_collection() -> int:
    collections = _check(
        requests.get(_url("/api/collection"), headers=HEADERS, timeout=30),
        "listar colecciones",
    )
    rows = collections.get("data") if isinstance(collections, dict) else collections
    for collection in rows or []:
        if collection.get("name") == COLLECTION_NAME:
            return int(collection["id"])

    created = _check(
        requests.post(
            _url("/api/collection"),
            json={
                "name": COLLECTION_NAME,
                "description": "Tablero y preguntas del sistema de inventario y ventas.",
                "color": "#509EE3",
                "parent_id": None,
            },
            headers=HEADERS,
            timeout=30,
        ),
        "crear coleccion",
    )
    return int(created["id"])


CARDS: list[dict[str, Any]] = [
    {
        "name": "Ingresos confirmados",
        "display": "scalar",
        "query": """
            SELECT round(COALESCE(sum(total), 0), 2) AS ingresos
              FROM core.sales
             WHERE status = 'CONFIRMED'
        """,
        "viz": {},
    },
    {
        "name": "Margen bruto",
        "display": "scalar",
        "query": """
            SELECT round(COALESCE(sum(si.line_subtotal - si.line_cost), 0), 2) AS margen
              FROM core.sales s
              JOIN core.sale_items si ON si.sale_id = s.sale_id
             WHERE s.status = 'CONFIRMED'
        """,
        "viz": {},
    },
    {
        "name": "Ventas mensuales",
        "display": "line",
        "query": """
            SELECT month AS mes, revenue AS ingresos, gross_margin AS margen
              FROM reporting.mv_ventas_mensuales
             ORDER BY month
        """,
        "viz": {
            "graph.dimensions": ["mes"],
            "graph.metrics": ["ingresos", "margen"],
        },
    },
    {
        "name": "Top 10 productos por ingreso",
        "display": "bar",
        "query": """
            SELECT product_name AS producto, revenue AS ingresos
              FROM reporting.v_abc_productos
             ORDER BY revenue DESC
             LIMIT 10
        """,
        "viz": {
            "graph.dimensions": ["producto"],
            "graph.metrics": ["ingresos"],
        },
    },
    {
        "name": "Alertas de reposicion",
        "display": "table",
        "query": """
            SELECT warehouse_code AS almacen,
                   sku,
                   product_name AS producto,
                   quantity AS stock_actual,
                   min_quantity AS stock_minimo,
                   COALESCE(coverage_days, 0) AS dias_cobertura,
                   priority AS prioridad
              FROM reporting.v_alertas_reposicion
             ORDER BY CASE priority WHEN 'CRITICA' THEN 1 WHEN 'ALTA' THEN 2 ELSE 3 END,
                      quantity ASC
             LIMIT 50
        """,
        "viz": {},
    },
    {
        "name": "Rotacion anual por categoria",
        "display": "bar",
        "query": """
            SELECT category_name AS categoria, annualized_turns AS rotacion
              FROM reporting.v_rotacion_actual
             WHERE annualized_turns IS NOT NULL
             ORDER BY annualized_turns DESC
        """,
        "viz": {
            "graph.dimensions": ["categoria"],
            "graph.metrics": ["rotacion"],
        },
    },
]


def _ensure_card(
    collection_id: int,
    database_id: int,
    card: dict[str, Any],
    existing_items: list[dict[str, Any]],
) -> int:
    existing = _find_by_name(existing_items, card["name"])
    payload = {
        "name": card["name"],
        "description": f"Pregunta nativa del proyecto. {card['name']}.",
        "collection_id": collection_id,
        "dataset_query": {
            "database": database_id,
            "type": "native",
            "native": {"query": card["query"], "template-tags": {}},
        },
        "display": card["display"],
        "visualization_settings": card["viz"],
    }
    if existing:
        card_id = int(existing["id"])
        _check(
            requests.put(_url(f"/api/card/{card_id}"), json=payload, headers=HEADERS, timeout=60),
            f"actualizar tarjeta {card['name']}",
        )
        return card_id
    created = _check(
        requests.post(_url("/api/card"), json=payload, headers=HEADERS, timeout=120),
        f"crear tarjeta {card['name']}",
    )
    return int(created["id"])


def _ensure_dashboard(collection_id: int) -> int:
    items = _get_collection_items(collection_id, models=("dashboard",))
    existing = _find_by_name(items, DASHBOARD_NAME)
    if existing and existing.get("model") == "dashboard":
        return int(existing["id"])

    created = _check(
        requests.post(
            _url("/api/dashboard"),
            json={
                "name": DASHBOARD_NAME,
                "description": "Ventas, margen, productos, inventario y alertas de reposicion.",
                "collection_id": collection_id,
            },
            headers=HEADERS,
            timeout=30,
        ),
        "crear tablero",
    )
    return int(created["id"])


def _dashboard_card_ids(dashboard_id: int) -> set[int]:
    dashboard = _check(
        requests.get(_url(f"/api/dashboard/{dashboard_id}"), headers=HEADERS, timeout=30),
        "leer tablero",
    )
    ids: set[int] = set()
    for dashcard in dashboard.get("dashcards", []) or []:
        card = dashcard.get("card") or {}
        if card.get("id"):
            ids.add(int(card["id"]))
        elif dashcard.get("card_id"):
            ids.add(int(dashcard["card_id"]))
    return ids


def _add_card(dashboard_id: int, card_id: int) -> None:
    response = requests.post(
        _url(f"/api/dashboard/{dashboard_id}/cards"),
        json={"cardId": card_id},
        headers=HEADERS,
        timeout=60,
    )
    if response.status_code < 400:
        return

    # Fallback para versiones recientes: PUT del tablero con dashcards.
    dashboard = _check(
        requests.get(_url(f"/api/dashboard/{dashboard_id}"), headers=HEADERS, timeout=30),
        "leer tablero para agregar tarjeta",
    )
    dashcards = dashboard.get("dashcards", []) or []
    dashcards.append({
        "id": -(card_id),
        "card_id": card_id,
        "row": 0,
        "col": 0,
        "size_x": 6,
        "size_y": 4,
        "parameter_mappings": [],
        "visualization_settings": {},
    })
    _check(
        requests.put(
            _url(f"/api/dashboard/{dashboard_id}"),
            json={"dashcards": dashcards},
            headers=HEADERS,
            timeout=60,
        ),
        "agregar tarjeta al tablero",
    )


def _layout_dashboard(dashboard_id: int, card_ids: list[int]) -> None:
    """Acomoda las tarjetas en una grilla de 24 columnas.

    Sin esto, la API puede dejar todas las tarjetas en row=0, col=0 y el
    tablero se ve superpuesto.
    """
    dashboard = _check(
        requests.get(_url(f"/api/dashboard/{dashboard_id}"), headers=HEADERS, timeout=30),
        "leer tablero para acomodar tarjetas",
    )
    dashcards = dashboard.get("dashcards") or []
    by_card: dict[int, dict[str, Any]] = {}
    for dashcard in dashcards:
        card = dashcard.get("card") or {}
        card_id = card.get("id") or dashcard.get("card_id")
        if card_id:
            by_card[int(card_id)] = dashcard

    display_by_id = {
        card_id: CARDS[index]["display"]
        for index, card_id in enumerate(card_ids)
        if index < len(CARDS)
    }

    row = 0
    col = 0
    row_height = 0
    updates: list[dict[str, Any]] = []
    for card_id in card_ids:
        dashcard = by_card.get(card_id)
        if not dashcard:
            continue
        is_scalar = display_by_id.get(card_id) == "scalar"
        width = 6 if is_scalar else 12
        height = 3 if is_scalar else 6

        if col + width > 24 or (height > row_height and col > 0):
            row += row_height
            col = 0
            row_height = 0

        updates.append({
            "id": dashcard["id"],
            "card_id": card_id,
            "row": row,
            "col": col,
            "size_x": width,
            "size_y": height,
            "parameter_mappings": dashcard.get("parameter_mappings", []),
            "visualization_settings": dashcard.get("visualization_settings", {}),
        })
        col += width
        row_height = max(row_height, height)

    if updates:
        _check(
            requests.put(
                _url(f"/api/dashboard/{dashboard_id}"),
                json={"dashcards": updates},
                headers=HEADERS,
                timeout=60,
            ),
            "acomodar tarjetas del tablero",
        )


def _public_link(dashboard_id: int) -> str | None:
    response = requests.post(
        _url(f"/api/dashboard/{dashboard_id}/public_link"),
        headers=HEADERS,
        timeout=30,
    )
    if response.status_code in (200, 201):
        data = response.json()
        uuid = data.get("uuid")
        if uuid:
            return f"{BASE}/public/dashboard/{uuid}"
    if response.status_code == 409:
        dashboard = requests.get(
            _url(f"/api/dashboard/{dashboard_id}"), headers=HEADERS, timeout=30
        ).json()
        uuid = dashboard.get("public_uuid")
        if uuid:
            return f"{BASE}/public/dashboard/{uuid}"
    return None


def setup_metabase() -> None:
    print(f"Esperando Metabase en {BASE} ...")
    _wait_for_metabase()
    _ensure_setup()
    _login()
    print("Sesion iniciada.")

    database_id = _ensure_database()
    print(f"Base de datos Metabase: {database_id}")

    collection_id = _ensure_collection()
    print(f"Coleccion: {collection_id}")

    items = _get_collection_items(collection_id)
    card_ids: list[int] = []
    for card in CARDS:
        card_id = _ensure_card(collection_id, database_id, card, items)
        card_ids.append(card_id)
        print(f"  tarjeta {card['name']}: {card_id}")

    dashboard_id = _ensure_dashboard(collection_id)
    existing_card_ids = _dashboard_card_ids(dashboard_id)
    for card_id in card_ids:
        if card_id not in existing_card_ids:
            _add_card(dashboard_id, card_id)
    _layout_dashboard(dashboard_id, card_ids)

    public_url = _public_link(dashboard_id)
    print("")
    print(f"Tablero listo: {BASE}/dashboard/{dashboard_id}")
    if public_url:
        print(f"Enlace publico: {public_url}")
