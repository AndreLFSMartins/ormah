"""Tests for the FastAPI app shell."""

import re

from ormah.main import _LOCAL_CORS_ORIGIN_REGEX, _is_reserved_api_path


def test_spa_fallback_excludes_api_prefixes():
    assert _is_reserved_api_path("agent/context") is True
    assert _is_reserved_api_path("admin/healthz") is True
    assert _is_reserved_api_path("ingest/missing") is True
    assert _is_reserved_api_path("ui/missing") is True


def test_spa_fallback_allows_frontend_routes():
    assert _is_reserved_api_path("") is False
    assert _is_reserved_api_path("graph") is False
    assert _is_reserved_api_path("projects/ormah") is False


def test_cors_regex_allows_only_loopback_origins():
    assert re.match(_LOCAL_CORS_ORIGIN_REGEX, "http://localhost:5173")
    assert re.match(_LOCAL_CORS_ORIGIN_REGEX, "http://127.0.0.1:8787")
    assert re.match(_LOCAL_CORS_ORIGIN_REGEX, "https://[::1]:8787")
    assert not re.match(_LOCAL_CORS_ORIGIN_REGEX, "https://evil.example")
