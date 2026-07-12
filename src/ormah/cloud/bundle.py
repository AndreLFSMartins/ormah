"""Encrypted snapshot bundles (E08 §2).

A bundle is ``age-encrypt( gzip-tar( snapshot_dir ) )`` where the snapshot dir
contains ``nodes/*.md``, ``deleted/*.md``, ``backup.json`` and a
``bundle-manifest.json`` with per-file SHA-256 hashes. Opening a bundle always
verifies every extracted file against the manifest — hash checking is not
optional; restore and verification both consume it.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ormah.cloud.crypto import decrypt_bytes, encrypt_bytes

logger = logging.getLogger(__name__)

BUNDLE_FORMAT_VERSION = 1
MANIFEST_NAME = "bundle-manifest.json"
BACKUP_MANIFEST_NAME = "backup.json"

# Extraction hardening limits (E08 §2)
MAX_MEMBERS = 100_000
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


class BundleError(RuntimeError):
    """Raised when building or opening a bundle fails."""


@dataclass(frozen=True)
class BundleInfo:
    store_id: str
    created_at: str
    reason: str
    node_count: int
    deleted_count: int
    total_bytes: int
    file_count: int
    sync_base_snapshot_id: str | None
    device_id: str | None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iter_bundle_files(backup_dir: Path) -> list[Path]:
    """Files that enter a bundle, as paths relative to backup_dir."""
    files: list[Path] = []
    for sub in ("nodes", "deleted"):
        d = backup_dir / sub
        if d.is_dir():
            files.extend(sorted(p for p in d.glob("*.md") if p.is_file()))
    backup_json = backup_dir / BACKUP_MANIFEST_NAME
    if backup_json.is_file():
        files.append(backup_json)
    return files


def build_bundle(
    backup_dir: Path,
    out_path: Path,
    recipients: list,
    *,
    store_id: str,
    reason: str = "manual",
    sync_base_snapshot_id: str | None = None,
    device_id: str | None = None,
) -> Path:
    """Build an encrypted bundle from a finished local backup directory.

    Returns the written ``.age`` path. The write is atomic (tmp + rename).
    """
    backup_dir = backup_dir.expanduser()
    if not backup_dir.is_dir():
        raise BundleError(f"Backup directory not found: {backup_dir}")

    files = _iter_bundle_files(backup_dir)
    entries = []
    node_count = deleted_count = total_bytes = 0
    payloads: list[tuple[str, bytes]] = []
    for path in files:
        rel = path.relative_to(backup_dir).as_posix()
        data = path.read_bytes()
        entries.append({"path": rel, "size": len(data), "sha256": _sha256(data)})
        payloads.append((rel, data))
        total_bytes += len(data)
        if rel.startswith("nodes/"):
            node_count += 1
        elif rel.startswith("deleted/"):
            deleted_count += 1

    manifest = {
        "format_version": BUNDLE_FORMAT_VERSION,
        "store_id": store_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "node_count": node_count,
        "deleted_count": deleted_count,
        "total_bytes": total_bytes,
        "files": entries,
        "sync": {"base_snapshot_id": sync_base_snapshot_id, "device_id": device_id},
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        for rel, data in payloads:
            _add_member(tar, rel, data)
        _add_member(tar, MANIFEST_NAME, manifest_bytes)

    ciphertext = encrypt_bytes(tar_buffer.getvalue(), recipients)

    out_path = out_path.expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(out_path.parent), suffix=".tmp", prefix=".ormah_bundle_")
    try:
        os.write(fd, ciphertext)
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp, str(out_path))
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return out_path


def _add_member(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0  # deterministic archives; real times live in frontmatter
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))


def _member_allowed(name: str) -> bool:
    """Strict allowlist: exactly nodes/*.md, deleted/*.md, and the two json files."""
    if name in (BACKUP_MANIFEST_NAME, MANIFEST_NAME):
        return True
    for prefix in ("nodes/", "deleted/"):
        if name.startswith(prefix):
            rest = name[len(prefix):]
            return bool(rest) and "/" not in rest and rest.endswith(".md")
    return False


def open_bundle(
    bundle_path: Path,
    dest_dir: Path,
    identities: list,
    *,
    max_members: int = MAX_MEMBERS,
    max_expanded_bytes: int = MAX_EXPANDED_BYTES,
) -> BundleInfo:
    """Decrypt, safely extract, and hash-verify a bundle into dest_dir.

    Any manifest mismatch (hash, size, missing, or extra file) is a hard
    failure. Members are validated against a strict allowlist and written
    manually from ``extractfile`` bytes — tar metadata is never applied, which
    is strictly stronger than ``filter="data"``.
    """
    bundle_path = bundle_path.expanduser()
    if not bundle_path.is_file():
        raise BundleError(f"Bundle not found: {bundle_path}")

    plaintext = decrypt_bytes(bundle_path.read_bytes(), identities)

    extracted: dict[str, bytes] = {}
    seen_casefold: set[str] = set()
    expanded = 0
    try:
        tar = tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz")
    except tarfile.TarError as e:
        raise BundleError(f"Bundle payload is not a valid tar.gz archive: {e}") from e
    with tar:
        members = 0
        for member in tar:
            members += 1
            if members > max_members:
                raise BundleError(f"Bundle exceeds member limit ({max_members}).")
            name = member.name
            if not member.isreg():
                raise BundleError(f"Bundle contains non-regular member: {name!r}")
            if name.startswith("/") or ".." in Path(name).parts or "\\" in name:
                raise BundleError(f"Bundle contains unsafe path: {name!r}")
            if not _member_allowed(name):
                raise BundleError(f"Bundle contains disallowed member: {name!r}")
            if name in extracted:
                raise BundleError(f"Bundle contains duplicate member: {name!r}")
            if name.casefold() in seen_casefold:
                raise BundleError(f"Bundle contains case-colliding member: {name!r}")
            expanded += member.size
            if expanded > max_expanded_bytes:
                raise BundleError(
                    f"Bundle exceeds expansion limit ({max_expanded_bytes} bytes)."
                )
            fileobj = tar.extractfile(member)
            if fileobj is None:
                raise BundleError(f"Bundle member unreadable: {name!r}")
            extracted[name] = fileobj.read()
            seen_casefold.add(name.casefold())

    if MANIFEST_NAME not in extracted:
        raise BundleError(f"Bundle is missing {MANIFEST_NAME}.")
    try:
        manifest = json.loads(extracted[MANIFEST_NAME].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BundleError(f"Bundle manifest is not valid JSON: {e}") from e
    if manifest.get("format_version") != BUNDLE_FORMAT_VERSION:
        raise BundleError(
            f"Unsupported bundle format_version: {manifest.get('format_version')!r}"
        )

    manifest_files = {entry["path"]: entry for entry in manifest.get("files", [])}
    content_files = {n: d for n, d in extracted.items() if n != MANIFEST_NAME}

    missing = sorted(set(manifest_files) - set(content_files))
    extra = sorted(set(content_files) - set(manifest_files))
    if missing:
        raise BundleError(f"Bundle is missing manifest-listed files: {missing}")
    if extra:
        raise BundleError(f"Bundle contains files not in the manifest: {extra}")

    for name, data in content_files.items():
        entry = manifest_files[name]
        if len(data) != entry["size"]:
            raise BundleError(
                f"Size mismatch for {name!r}: manifest {entry['size']}, got {len(data)}."
            )
        if _sha256(data) != entry["sha256"]:
            raise BundleError(f"Hash mismatch for {name!r} — bundle is corrupt or tampered.")

    dest_dir = dest_dir.expanduser()
    for name, data in content_files.items():
        target = dest_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (dest_dir / MANIFEST_NAME).write_bytes(extracted[MANIFEST_NAME])

    sync = manifest.get("sync") or {}
    return BundleInfo(
        store_id=manifest.get("store_id", ""),
        created_at=manifest.get("created_at", ""),
        reason=manifest.get("reason", ""),
        node_count=manifest.get("node_count", 0),
        deleted_count=manifest.get("deleted_count", 0),
        total_bytes=manifest.get("total_bytes", 0),
        file_count=len(content_files),
        sync_base_snapshot_id=sync.get("base_snapshot_id"),
        device_id=sync.get("device_id"),
    )
