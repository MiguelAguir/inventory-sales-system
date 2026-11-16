"""Configuracion central del proyecto.

Lee variables de entorno y, si existe, el archivo .env de la raiz.
Los valores por defecto coinciden con docker-compose.yml para que
`python -m src.pipeline schema` funcione sin configuracion adicional.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    host: str = _env("POSTGRES_HOST", "localhost")
    port: int = int(_env("POSTGRES_PORT", "5433"))
    dbname: str = _env("POSTGRES_DB", "inventory")
    user: str = _env("POSTGRES_USER", "inventory")
    password: str = _env("POSTGRES_PASSWORD", "inventory_dev")
    metabase_url: str = _env("METABASE_URL", "http://localhost:3001")
    metabase_email: str = _env("METABASE_EMAIL", "analyst@inventory.local")
    metabase_password: str = _env("METABASE_PASSWORD", "Inventory2026!")

    @property
    def conninfo(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "application_name": "inventory-sales-system",
        }


settings = Settings()
