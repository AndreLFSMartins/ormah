"""Key lifecycle, store identity, and the recovery kit (E08 §1, §5).

The key file keeps every identity ever generated — the current one first,
older ones retained below so pre-rotation bundles stay decryptable forever.
Nothing here is ever destructive; there is no ``--force``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ormah.cloud.crypto import (
    generate_identity,
    identity_from_str,
    identity_to_str,
)

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "ormah"
KEY_PATH = CONFIG_DIR / "cloud.key"
RECOVERY_KIT_PATH = CONFIG_DIR / "ormah-recovery-kit.md"
STORE_ID_NAME = ".store_id"


class CloudKeyError(RuntimeError):
    """Raised for key-file lifecycle failures."""


def _atomic_write_0600(path: Path, text: str) -> None:
    from ormah.setup import _atomic_write

    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(str(path), text, mode=0o600)


# --- Key file ---


def key_file_exists(key_path: Path | None = None) -> bool:
    key_path = KEY_PATH if key_path is None else key_path
    return key_path.expanduser().is_file()


def load_identity_strings(key_path: Path | None = None) -> list[str]:
    """All identity strings in the key file, current first."""
    key_path = (KEY_PATH if key_path is None else key_path).expanduser()
    if not key_path.is_file():
        raise CloudKeyError(
            f"No cloud key found at {key_path}. Run `ormah cloud init` first."
        )
    strings = [
        line.strip()
        for line in key_path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("AGE-SECRET-KEY-")
    ]
    if not strings:
        raise CloudKeyError(f"Cloud key file {key_path} contains no identities.")
    return strings


def load_identities(key_path: Path | None = None) -> list:
    """All identities for decryption, current first."""
    return [identity_from_str(s) for s in load_identity_strings(key_path)]


def current_recipient(key_path: Path | None = None):
    """The encryption recipient (public key of the current identity)."""
    return load_identities(key_path)[0].to_public()


def _serialize_key_file(identity_strings: list[str], rotated: bool) -> str:
    """Current identity first; older identities retained below it."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Ormah cloud encryption identities (age). KEEP THIS FILE SAFE.",
        "# The first identity encrypts new bundles; all of them decrypt.",
        "# Never delete old identities — older backups still need them.",
        f"# current since {now}" + (" (rotation)" if rotated else ""),
        identity_strings[0],
    ]
    for old in identity_strings[1:]:
        lines.append("# retained pre-rotation identity")
        lines.append(old)
    return "\n".join(lines) + "\n"


def init_key(key_path: Path | None = None) -> str:
    """Generate the first identity. Refuses if a key file already exists."""
    key_path = (KEY_PATH if key_path is None else key_path).expanduser()
    if key_path.is_file():
        raise CloudKeyError(
            f"A cloud key already exists at {key_path}. "
            "To get a new encryption key, run `ormah cloud rotate-key` — "
            "it keeps old identities so existing backups stay readable."
        )
    identity_str = identity_to_str(generate_identity())
    _atomic_write_0600(key_path, _serialize_key_file([identity_str], rotated=False))
    return identity_str


def import_key(source: str, key_path: Path | None = None) -> list[str]:
    """Install identities from a recovery kit or key file (fresh machine).

    Accepts a path or raw pasted text; extracts every AGE-SECRET-KEY line,
    preserving order (current first). Refuses if a key file already exists.
    """
    key_path = (KEY_PATH if key_path is None else key_path).expanduser()
    if key_path.is_file():
        raise CloudKeyError(
            f"A cloud key already exists at {key_path}; refusing to overwrite. "
            "Move it aside first if you really mean to replace it."
        )
    source_path = Path(source).expanduser()
    text = source_path.read_text(encoding="utf-8") if source_path.is_file() else source
    strings = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("AGE-SECRET-KEY-")
    ]
    if not strings:
        raise CloudKeyError("No age identities found in the provided key material.")
    for s in strings:  # validate before writing anything
        identity_from_str(s)
    _atomic_write_0600(key_path, _serialize_key_file(strings, rotated=False))
    return strings


def rotate_key(key_path: Path | None = None) -> str:
    """Generate a new current identity, retaining all previous ones."""
    key_path = KEY_PATH if key_path is None else key_path
    existing = load_identity_strings(key_path)
    new_identity = identity_to_str(generate_identity())
    _atomic_write_0600(
        key_path.expanduser(),
        _serialize_key_file([new_identity, *existing], rotated=True),
    )
    return new_identity


# --- store_id (E08 §1) ---


def get_or_create_store_id(memory_dir: Path) -> str:
    """UUIDv4 per memory store, persisted at <memory_dir>/.store_id."""
    memory_dir = memory_dir.expanduser()
    store_path = memory_dir / STORE_ID_NAME
    if store_path.is_file():
        value = store_path.read_text(encoding="utf-8").strip()
        try:
            return str(uuid.UUID(value))
        except ValueError as e:
            raise CloudKeyError(f"Corrupt store id at {store_path}: {value!r}") from e
    memory_dir.mkdir(parents=True, exist_ok=True)
    store_id = str(uuid.uuid4())
    store_path.write_text(store_id + "\n", encoding="utf-8")
    return store_id


# --- Recovery kit ---


def write_recovery_kit(
    store_id: str,
    key_path: Path | None = None,
    kit_path: Path | None = None,
    account_email: str | None = None,
) -> Path:
    """(Re)generate the recovery kit with ALL identities.

    The kit is the entire recovery story: anyone with this file can read the
    backups; without it, nobody can — including us.
    """
    kit_path = RECOVERY_KIT_PATH if kit_path is None else kit_path
    identity_strings = load_identity_strings(key_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    identities_block = "\n".join(identity_strings)
    kit = f"""# Ormah Recovery Kit

Generated: {now}

> **Anyone with this file can read your backups; without it, nobody can —
> including us. Store it offline** (print it, or keep it on a USB drive in a
> drawer). Do not store it in the same cloud account it protects.

## Your encryption identities (all of them — order matters, current first)

```
{identities_block}
```

## Your store id

```
{store_id}
```

## Account

Email: {account_email or "<your ormah account email>"}

## Restore on a fresh machine

1. Install ormah, then log in:  `ormah account login`
2. Import this kit's keys:      `ormah cloud init --import-key <path-to-this-file>`
3. Restore your memory graph:   `ormah backup restore --cloud`

That's the whole procedure. Every identity listed above is needed to read
backups made before key rotations — never trim this list.
"""
    kit_path = kit_path.expanduser()
    _atomic_write_0600(kit_path, kit)
    return kit_path
