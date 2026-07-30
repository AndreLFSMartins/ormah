"""Tests for the owner-only local admin capability."""

from __future__ import annotations

import stat

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ormah.api.local_auth import load_or_create_local_admin_token, require_loopback


def test_local_admin_token_is_stable_and_owner_only(tmp_path):
    path = tmp_path / "ormah" / "local_api_token"

    first = load_or_create_local_admin_token(path)
    second = load_or_create_local_admin_token(path)

    assert first == second
    assert len(first) == 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_invalid_existing_local_admin_token_is_never_replaced(tmp_path):
    path = tmp_path / "local_api_token"
    path.write_text("too-short\n", encoding="ascii")

    with pytest.raises(RuntimeError, match="invalid; refusing to replace"):
        load_or_create_local_admin_token(path)

    assert path.read_text(encoding="ascii") == "too-short\n"


def test_existing_local_admin_token_permissions_are_repaired(tmp_path):
    path = tmp_path / "local_api_token"
    path.write_text("a" * 64 + "\n", encoding="ascii")
    path.chmod(0o644)

    assert load_or_create_local_admin_token(path) == "a" * 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_local_admin_token_rejects_symlinks(tmp_path):
    target = tmp_path / "target"
    target.write_text("a" * 64 + "\n", encoding="ascii")
    path = tmp_path / "local_api_token"
    path.symlink_to(target)

    with pytest.raises(RuntimeError, match="not a regular file"):
        load_or_create_local_admin_token(path)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
async def test_loopback_dependency_accepts_only_local_peers(host):
    request = Request({"type": "http", "client": (host, 50000)})

    assert await require_loopback(request) is None


async def test_loopback_dependency_rejects_lan_peers():
    request = Request({"type": "http", "client": ("192.168.1.50", 50000)})

    with pytest.raises(HTTPException) as exc_info:
        await require_loopback(request)

    assert exc_info.value.status_code == 403
