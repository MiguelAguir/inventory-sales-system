"""Pruebas de estructura del repositorio y de los controles de calidad."""

from __future__ import annotations

from src.config import ROOT


def test_required_files_exist() -> None:
    required = [
        "README.md",
        "docker-compose.yml",
        "requirements.txt",
        ".env.example",
        "sql/00_schema/02_tables.sql",
        "sql/00_schema/04_functions.sql",
        "sql/00_schema/05_views.sql",
        "sql/20_checks/01_quality_checks.sql",
    ]
    for relative in required:
        assert (ROOT / relative).exists(), f"Falta {relative}"


def test_readme_declares_synthetic_data() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "sintetic" in text or "sintético" in text


def test_quality_checks_execute(conn) -> None:
    sql = (ROOT / "sql" / "20_checks" / "01_quality_checks.sql").read_text(encoding="utf-8")
    rows = conn.execute(sql).fetchall()
    assert len(rows) >= 10
    assert {"check_name", "passed", "detail"}.issubset(rows[0].keys())
