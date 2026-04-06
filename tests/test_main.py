"""Tests for the FastAPI app shell."""

from ormah.main import _is_reserved_api_path


def test_spa_fallback_excludes_api_prefixes():
    assert _is_reserved_api_path("agent/context") is True
    assert _is_reserved_api_path("admin/healthz") is True
    assert _is_reserved_api_path("ingest/missing") is True
    assert _is_reserved_api_path("ui/missing") is True


def test_spa_fallback_allows_frontend_routes():
    assert _is_reserved_api_path("") is False
    assert _is_reserved_api_path("graph") is False
    assert _is_reserved_api_path("projects/ormah") is False
