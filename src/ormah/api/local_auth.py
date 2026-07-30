"""Owner-only capability authentication for sensitive local API routes."""

from __future__ import annotations

import re
import secrets
import stat
from ipaddress import ip_address
from pathlib import Path

from fastapi import Depends, Header, HTTPException, Request


LOCAL_ADMIN_TOKEN_PATH = Path.home() / ".local" / "share" / "ormah" / "local_api_token"
LOCAL_ADMIN_HEADER = "X-Ormah-Local-Token"
_TOKEN_RE = re.compile(r"[0-9a-f]{64}")


def load_or_create_local_admin_token(path: Path | None = None) -> str:
    """Load this installation's local API capability, creating it mode 0600."""
    path = (path or LOCAL_ADMIN_TOKEN_PATH).expanduser()
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        from ormah.setup import _atomic_write

        token = secrets.token_hex(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(str(path), token + "\n", mode=0o600)
        return token
    except OSError as exc:
        raise RuntimeError(f"Could not inspect local API capability {path}: {exc}") from exc
    try:
        if path.is_symlink() or not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(f"Local API capability {path} is not a regular file")
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            path.chmod(0o600)
    except OSError as exc:
        raise RuntimeError(f"Could not secure local API capability {path}: {exc}") from exc
    try:
        token = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Could not read local API capability {path}: {exc}") from exc

    if _TOKEN_RE.fullmatch(token) is None:
        raise RuntimeError(f"Local API capability {path} is invalid; refusing to replace it")
    return token


async def require_loopback(request: Request) -> None:
    """Reject sensitive requests that did not originate on this machine."""
    peer = request.client.host if request.client is not None else ""
    try:
        is_loopback = ip_address(peer.split("%", 1)[0]).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=403, detail="Local admin routes are loopback-only.")


async def require_local_admin(
    request: Request,
    provided: str | None = Header(default=None, alias=LOCAL_ADMIN_HEADER),
    _loopback: None = Depends(require_loopback),
) -> None:
    """Authenticate a native local caller without exposing the cloud account token."""
    expected = getattr(request.app.state, "local_admin_token", None)
    if (
        not isinstance(expected, str)
        or not isinstance(provided, str)
        or not expected.isascii()
        or not provided.isascii()
        or not secrets.compare_digest(provided, expected)
    ):
        raise HTTPException(status_code=401, detail="Local admin authentication required.")
