"""Shared encrypted cloud-backup and restore-verification orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
import uuid

import httpx

from ormah.backup import (
    BackupError,
    BackupInfo,
    resolve_backup_user_node_id,
    resolve_current_user_node_id,
    service_from_settings,
)
from ormah.cloud.bundle import BundleError, build_bundle, open_bundle
from ormah.cloud.client import CloudError, client_from_settings
from ormah.cloud.entitlements import EntitlementStatus, check_entitlement
from ormah.cloud.keys import (
    STORE_ID_NAME,
    current_recipient,
    get_or_create_store_id,
    key_file_exists,
    load_identities,
)
from ormah.cloud.state import (
    CURRENT_CLOUD_STATE_SCHEMA_VERSION,
    CloudState,
    CloudStateVersionError,
    ProtectionOperation,
    ProtectionOperationKind,
    ProtectionOperationPhase,
    ProtectionReasonCode,
    ProtectionState,
    load_state,
    update_state,
)
from ormah.cloud.store_lock import StoreLock, StoreLockTimeout
from ormah.cloud.transfer import download_file, put_file, sha256_file
from ormah.index.builder import IndexBuilder
from ormah.index.db import Database
from ormah.index.graph import GraphIndex
from ormah.store.file_store import FileStore
from ormah.store.markdown import parse_node


logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bBearer\s+[^\s]+", re.IGNORECASE)
_AGE_SECRET_RE = re.compile(r"AGE-SECRET-KEY-[A-Z0-9]+", re.IGNORECASE)
_QUERY_SECRET_RE = re.compile(
    r"(?i)((?:^|[?&\s])(?:x-amz-signature|x-amz-credential|x-amz-security-token|"
    r"access_token|token|signature)=)[^&\s]+"
)
_SNAPSHOT_ID_RE = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_error_message(value: object, *sensitive_values: str | None) -> str:
    """Return a useful error without returning or logging credential-bearing material."""

    message = str(value)
    message = _URL_RE.sub("<redacted-url>", message)
    message = _QUERY_SECRET_RE.sub(r"\1<redacted>", message)
    message = _BEARER_RE.sub("Bearer <redacted>", message)
    message = _AGE_SECRET_RE.sub("<redacted-age-key>", message)
    for sensitive in sensitive_values:
        if sensitive:
            message = message.replace(sensitive, "<redacted>")
    return message[:1000]


def _existing_store_id(memory_dir: Path) -> str | None:
    memory_dir = Path(memory_dir).expanduser()
    if not (memory_dir / STORE_ID_NAME).is_file():
        return None
    return get_or_create_store_id(memory_dir)


def _load_writable_state(store_id: str) -> CloudState:
    state = load_state(store_id)
    if state.schema_version > CURRENT_CLOUD_STATE_SCHEMA_VERSION:
        raise CloudStateVersionError(
            f"Cloud state schema {state.schema_version} is newer than this client's schema "
            f"{CURRENT_CLOUD_STATE_SCHEMA_VERSION}; update Ormah before writing it."
        )
    return state


def _snapshot_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for dirname in ("nodes", "deleted"):
        source = Path(root) / dirname
        if not source.is_dir():
            continue
        for path in source.glob("*.md"):
            if path.is_file():
                files[f"{dirname}/{path.name}"] = path
    return files


def _backup_matches_memory(backup: BackupInfo, memory_dir: Path) -> bool:
    try:
        if resolve_backup_user_node_id(backup.path) != resolve_current_user_node_id(memory_dir):
            return False
    except BackupError:
        return False

    source_files = _snapshot_files(memory_dir)
    backup_files = _snapshot_files(backup.path)
    if source_files.keys() != backup_files.keys():
        return False
    return all(
        source_files[name].stat().st_size == backup_files[name].stat().st_size
        and sha256_file(source_files[name]) == sha256_file(backup_files[name])
        for name in source_files
    )


def _backup_for_upload(service, *, reason: str = "manual") -> BackupInfo:
    latest = service.latest()
    if latest is not None and _backup_matches_memory(latest, service.memory_dir):
        return latest
    return service.create(reason=reason)


def _upload_due(state: CloudState, interval_hours: int, now: datetime) -> bool:
    if state.last_upload_at is None:
        return True
    return now - state.last_upload_at >= timedelta(hours=interval_hours)


def _known_state(state: CloudState) -> ProtectionState:
    value = state.protection_state
    return value if isinstance(value, ProtectionState) else ProtectionState.ATTENTION_REQUIRED


def _state_after_backup(state: CloudState) -> ProtectionState:
    current = _known_state(state)
    if current is ProtectionState.LOCAL_ONLY:
        return ProtectionState.VERIFYING_FIRST_BACKUP
    if current is ProtectionState.STOPPED:
        return ProtectionState.STOPPED
    if current is ProtectionState.UPLOADING_FIRST_BACKUP:
        return ProtectionState.VERIFYING_FIRST_BACKUP
    return ProtectionState.CHANGES_PENDING


def _state_after_verification(state: CloudState, snapshot_id: str) -> ProtectionState:
    current = _known_state(state)
    if snapshot_id != state.last_successful_backup_snapshot_id:
        return current
    if current in {
        ProtectionState.VERIFYING_FIRST_BACKUP,
        ProtectionState.CHANGES_PENDING,
        ProtectionState.ATTENTION_REQUIRED,
        ProtectionState.OFFLINE,
        ProtectionState.PROTECTED,
    }:
        return ProtectionState.PROTECTED
    return current


def _state_after_failure(
    state: CloudState,
    requested: ProtectionState,
) -> ProtectionState:
    current = _known_state(state)
    if current is ProtectionState.STOPPED:
        return ProtectionState.STOPPED
    return requested


def _is_offline_error(error: object) -> bool:
    return isinstance(error, httpx.RequestError) or (
        isinstance(error, CloudError) and error.status_code is None
    )


def _validated_snapshot_id(value: object) -> str:
    if not isinstance(value, str) or _SNAPSHOT_ID_RE.fullmatch(value) is None:
        raise RuntimeError("Cloud response contained an invalid snapshot id.")
    return value


def _probe_search(database: Database, nodes: list[Any]) -> None:
    if not nodes:
        raise RuntimeError("Restored snapshot has no active node available for a search probe.")
    graph = GraphIndex(database)
    for node in nodes:
        words = re.findall(r"\w{2,}", f"{node.title or ''} {node.content}")
        for word in sorted(words, key=len, reverse=True):
            if any(result["id"] == node.id for result in graph.fts_search(word, limit=10)):
                return
    raise RuntimeError("Scratch search probe did not return a known restored node.")


def _verify_extracted_bundle(extracted: Path, expected_store_id: str, info) -> int:
    if info.store_id != expected_store_id:
        raise RuntimeError(
            f"Bundle store id {info.store_id!r} does not match local store {expected_store_id!r}."
        )

    resolve_backup_user_node_id(extracted)

    active_nodes = []
    for dirname in ("nodes", "deleted"):
        for path in sorted((extracted / dirname).glob("*.md")):
            node = parse_node(path.read_text(encoding="utf-8"))
            if dirname == "nodes":
                active_nodes.append(node)

    database = Database(extracted / "scratch-index" / "index.db")
    try:
        database.init_schema()
        rebuilt = IndexBuilder(database, FileStore(extracted / "nodes")).full_rebuild()
        if rebuilt != info.node_count:
            raise RuntimeError(
                f"Scratch index rebuilt {rebuilt} nodes; bundle manifest declares {info.node_count}."
            )
        _probe_search(database, active_nodes)
        return rebuilt
    finally:
        database.close()


class CloudProtectionService:
    """Reusable cloud protection operations constructed from application settings."""

    def __init__(self, settings) -> None:
        self.settings = settings

    @classmethod
    def from_engine(cls, engine) -> CloudProtectionService:
        return cls(engine.settings)

    def _message(self, value: object) -> str:
        return safe_error_message(value, getattr(self.settings, "account_token", None))

    def backup_now(
        self,
        reason: str = "manual",
        *,
        only_if_due: bool = False,
    ) -> ProtectionOperation:
        """Create, encrypt, upload, and finalize one backup."""

        operation_id = str(uuid.uuid4())
        try:
            with StoreLock(self.settings.memory_dir):
                return self._backup_now(
                    operation_id,
                    reason=reason,
                    only_if_due=only_if_due,
                )
        except StoreLockTimeout:
            return self._store_busy_operation(
                operation_id,
                ProtectionOperationKind.BACKUP,
            )
        except Exception as exc:
            return self._backup_failure(operation_id, exc)

    def _backup_now(
        self,
        operation_id: str,
        *,
        reason: str,
        only_if_due: bool,
    ) -> ProtectionOperation:
        settings = self.settings
        store_id: str | None = None
        client = None
        try:
            store_id = _existing_store_id(settings.memory_dir)
            try:
                state = _load_writable_state(store_id) if store_id is not None else None
            except CloudStateVersionError:
                return self._client_update_required_operation(
                    operation_id,
                    ProtectionOperationKind.BACKUP,
                )
            if state is not None and not isinstance(state.protection_state, ProtectionState):
                return self._client_update_required_operation(
                    operation_id,
                    ProtectionOperationKind.BACKUP,
                )

            if not settings.cloud_backup_enabled:
                logger.debug("Ormah Cloud backup is disabled")
                return ProtectionOperation(
                    operation_id,
                    ProtectionOperationKind.BACKUP,
                    ProtectionOperationPhase.CANCELED,
                    state.protection_state if state is not None else ProtectionState.LOCAL_ONLY,
                    ProtectionReasonCode.NOT_ENABLED,
                    "Cloud backup is disabled.",
                )

            if state is not None and state.protection_state is ProtectionState.STOPPED:
                return ProtectionOperation(
                    operation_id,
                    ProtectionOperationKind.BACKUP,
                    ProtectionOperationPhase.CANCELED,
                    ProtectionState.STOPPED,
                    ProtectionReasonCode.PROTECTION_STOPPED,
                    "Cloud protection is stopped for this memory store.",
                )

            if not key_file_exists():
                return self._backup_failure(
                    operation_id,
                    "Cloud encryption key is missing; run `ormah cloud init`.",
                    store_id=store_id,
                    reason_code=ProtectionReasonCode.KEY_MISSING,
                )

            if store_id is None:
                return self._backup_failure(
                    operation_id,
                    "Cloud store id is missing; run `ormah cloud init`.",
                    reason_code=ProtectionReasonCode.NOT_ENABLED,
                )

            assert state is not None
            entitlement = check_entitlement(settings)
            if entitlement not in {EntitlementStatus.ACTIVE, EntitlementStatus.GRACE}:
                return self._backup_failure(
                    operation_id,
                    f"Cloud backup paused because entitlement is {entitlement.value}.",
                    store_id=store_id,
                    reason_code=ProtectionReasonCode.ENTITLEMENT_EXPIRED,
                    phase=ProtectionOperationPhase.CANCELED,
                    protection_state=ProtectionState.PAUSED,
                )

            backup_service = service_from_settings(settings)
            if not backup_service.has_backupable_memory():
                logger.debug("Skipping Ormah Cloud backup; no memory nodes exist yet")
                return ProtectionOperation(
                    operation_id,
                    ProtectionOperationKind.BACKUP,
                    ProtectionOperationPhase.CANCELED,
                    state.protection_state
                    if isinstance(state.protection_state, ProtectionState)
                    else ProtectionState.ATTENTION_REQUIRED,
                    ProtectionReasonCode.NO_BACKUPABLE_MEMORY,
                    message="No memory nodes are available to back up.",
                )

            now = _utc_now()
            if only_if_due and not _upload_due(state, settings.cloud_backup_interval_hours, now):
                logger.debug("Skipping Ormah Cloud backup; latest upload is still fresh")
                return ProtectionOperation(
                    operation_id,
                    ProtectionOperationKind.BACKUP,
                    ProtectionOperationPhase.CANCELED,
                    state.protection_state
                    if isinstance(state.protection_state, ProtectionState)
                    else ProtectionState.ATTENTION_REQUIRED,
                    ProtectionReasonCode.NOT_DUE,
                    message="The latest cloud backup is still fresh.",
                    snapshot_id=state.last_upload_snapshot_id,
                )

            backup = _backup_for_upload(backup_service, reason=reason)
            with tempfile.TemporaryDirectory(prefix="ormah-cloud-upload-") as tmp:
                bundle = Path(tmp) / f"{backup.name}.age"
                build_bundle(
                    backup.path,
                    bundle,
                    [current_recipient()],
                    store_id=store_id,
                    reason=reason,
                )
                size = bundle.stat().st_size
                digest = sha256_file(bundle)
                client = client_from_settings(settings)
                upload = client.create_upload(store_id, size, digest)
                upload_id = upload.get("upload_id")
                snapshot_id = _validated_snapshot_id(upload.get("snapshot_id"))
                put_url = upload.get("put_url")
                expires_at = upload.get("expires_at")
                required_headers = upload.get("required_headers", {})
                if not all(
                    isinstance(value, str) and value for value in (upload_id, put_url)
                ):
                    raise RuntimeError("Cloud upload reservation response was malformed.")
                if not isinstance(expires_at, str):
                    raise RuntimeError("Cloud upload reservation did not include an expiry.")
                parsed_expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if parsed_expiry.tzinfo is None or parsed_expiry <= _utc_now():
                    raise RuntimeError("Cloud upload reservation is already expired.")
                if not isinstance(required_headers, dict) or not all(
                    isinstance(name, str) and isinstance(value, str)
                    for name, value in required_headers.items()
                ):
                    raise RuntimeError("Cloud upload reservation headers were malformed.")

                put_file(put_url, bundle, required_headers)
                finalized = client.finalize_upload(store_id, upload_id)
                finalized_snapshot = _validated_snapshot_id(finalized.get("snapshot_id"))
                if finalized.get("status") != "committed" or finalized_snapshot != snapshot_id:
                    raise RuntimeError("Cloud upload finalize response was malformed.")

            uploaded_at = _utc_now()
            next_state = _state_after_backup(state)
            update_state(
                store_id,
                memory_dir=settings.memory_dir,
                last_upload_at=uploaded_at,
                last_upload_snapshot_id=snapshot_id,
                last_upload_error=None,
                last_successful_upload_at=uploaded_at,
                last_successful_backup_snapshot_id=snapshot_id,
                protection_state=next_state,
                last_operation_id=operation_id,
                last_operation_kind=ProtectionOperationKind.BACKUP,
                last_operation_phase=ProtectionOperationPhase.COMPLETED,
                last_error_code=None,
                last_error_message=None,
                last_error_at=None,
            )
            logger.info("Uploaded encrypted Ormah Cloud snapshot %s", self._message(snapshot_id))
            return ProtectionOperation(
                operation_id,
                ProtectionOperationKind.BACKUP,
                ProtectionOperationPhase.COMPLETED,
                next_state,
                snapshot_id=snapshot_id,
            )
        except Exception as exc:
            if _is_offline_error(exc):
                return self._backup_failure(
                    operation_id,
                    exc,
                    store_id=store_id,
                    reason_code=ProtectionReasonCode.OFFLINE,
                    protection_state=ProtectionState.OFFLINE,
                )
            return self._backup_failure(operation_id, exc, store_id=store_id)
        finally:
            self._close_client(client)

    def _backup_failure(
        self,
        operation_id: str,
        error: object,
        *,
        store_id: str | None = None,
        reason_code: ProtectionReasonCode = ProtectionReasonCode.UPLOAD_FAILED,
        phase: ProtectionOperationPhase = ProtectionOperationPhase.FAILED,
        protection_state: ProtectionState = ProtectionState.ATTENTION_REQUIRED,
    ) -> ProtectionOperation:
        message = self._message(error)
        logger.warning("Ormah Cloud backup skipped or failed: %s", message)
        if store_id is not None:
            try:
                current = _load_writable_state(store_id)
                if not isinstance(current.protection_state, ProtectionState):
                    return self._client_update_required_operation(
                        operation_id,
                        ProtectionOperationKind.BACKUP,
                    )
                persisted_state = _state_after_failure(current, protection_state)
                update_state(
                    store_id,
                    memory_dir=self.settings.memory_dir,
                    last_upload_error=message,
                    protection_state=persisted_state,
                    last_operation_id=operation_id,
                    last_operation_kind=ProtectionOperationKind.BACKUP,
                    last_operation_phase=phase,
                    last_error_code=reason_code,
                    last_error_message=message,
                    last_error_at=_utc_now(),
                )
                protection_state = persisted_state
            except CloudStateVersionError:
                return self._client_update_required_operation(
                    operation_id,
                    ProtectionOperationKind.BACKUP,
                )
            except Exception as exc:
                logger.warning("Could not persist Ormah Cloud state: %s", self._message(exc))
        return ProtectionOperation(
            operation_id,
            ProtectionOperationKind.BACKUP,
            phase,
            protection_state,
            reason_code,
            message,
        )

    def verify_now(self, snapshot_id: str | None = None) -> ProtectionOperation:
        """Download and prove one committed snapshot entirely in scratch space."""

        operation_id = str(uuid.uuid4())
        try:
            with StoreLock(self.settings.memory_dir):
                return self._verify_now(operation_id, requested_snapshot_id=snapshot_id)
        except StoreLockTimeout:
            return self._store_busy_operation(
                operation_id,
                ProtectionOperationKind.VERIFY,
                snapshot_id=snapshot_id,
            )
        except Exception as exc:
            return self._verification_failure(operation_id, exc, snapshot_id=snapshot_id)

    def _verify_now(
        self, operation_id: str, *, requested_snapshot_id: str | None
    ) -> ProtectionOperation:
        settings = self.settings
        store_id: str | None = None
        snapshot_id: str | None = requested_snapshot_id
        tracks_latest_snapshot = requested_snapshot_id is None
        client = None
        tmp_root: Path | None = None
        try:
            store_id = _existing_store_id(settings.memory_dir)
            if store_id is None:
                raise _VerificationPrerequisiteError(
                    "Cloud store id is missing; cannot verify restore.",
                    ProtectionReasonCode.NOT_ENABLED,
                )
            try:
                state = _load_writable_state(store_id)
            except CloudStateVersionError:
                return self._client_update_required_operation(
                    operation_id,
                    ProtectionOperationKind.VERIFY,
                    snapshot_id=requested_snapshot_id,
                )
            if not isinstance(state.protection_state, ProtectionState):
                return self._client_update_required_operation(
                    operation_id,
                    ProtectionOperationKind.VERIFY,
                    snapshot_id=requested_snapshot_id,
                )
            if not key_file_exists():
                raise _VerificationPrerequisiteError(
                    "Cloud encryption key is missing; cannot verify restore.",
                    ProtectionReasonCode.KEY_MISSING,
                )
            if not settings.account_token:
                raise _VerificationPrerequisiteError(
                    "Ormah Cloud login is required to verify restore.",
                    ProtectionReasonCode.SIGN_IN_REQUIRED,
                )

            client = client_from_settings(settings)
            listing = client.list_blobs(store_id)
            blobs = listing.get("blobs")
            if not isinstance(blobs, list) or not blobs:
                raise RuntimeError("No committed cloud snapshot is available to verify.")
            latest_snapshot_id = _validated_snapshot_id(
                blobs[0].get("snapshot_id") if isinstance(blobs[0], dict) else None
            )
            selected = (
                blobs[0]
                if requested_snapshot_id is None
                else next(
                    (
                        blob
                        for blob in blobs
                        if isinstance(blob, dict)
                        and blob.get("snapshot_id") == requested_snapshot_id
                    ),
                    None,
                )
            )
            if not isinstance(selected, dict):
                raise RuntimeError("The requested cloud snapshot is not available to verify.")
            snapshot_id = _validated_snapshot_id(selected.get("snapshot_id"))
            expected_latest_snapshot_id = (
                state.last_successful_backup_snapshot_id or latest_snapshot_id
            )
            tracks_latest_snapshot = (
                requested_snapshot_id is None or snapshot_id == expected_latest_snapshot_id
            )
            size_bytes = selected.get("size_bytes")
            if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
                raise RuntimeError("Cloud snapshot listing did not include a valid size.")
            if size_bytes > client.processing_limit(require_hardened_write=False):
                raise CloudError("Cloud snapshot exceeds this client's safe processing limit.")

            presigned = client.presign_download(store_id, snapshot_id)
            get_url = presigned.get("get_url")
            if not isinstance(get_url, str) or not get_url:
                raise RuntimeError("Cloud download response was malformed.")

            tmp_root = Path(tempfile.mkdtemp(prefix="ormah-restore-verify-"))
            bundle = tmp_root / f"{snapshot_id}.age"
            extracted = tmp_root / "snapshot"
            download_file(get_url, bundle)
            info = open_bundle(bundle, extracted, load_identities())
            _verify_extracted_bundle(extracted, store_id, info)

            verified_at = _utc_now()
            next_state = _state_after_verification(state, snapshot_id)
            changes: dict[str, object] = {
                "last_operation_id": operation_id,
                "last_operation_kind": ProtectionOperationKind.VERIFY,
                "last_operation_phase": ProtectionOperationPhase.COMPLETED,
                "last_error_code": None,
                "last_error_message": None,
                "last_error_at": None,
            }
            if tracks_latest_snapshot:
                changes.update(
                    last_verify_at=verified_at,
                    last_verify_ok=True,
                    last_verify_snapshot_id=snapshot_id,
                    last_verify_error=None,
                    last_successful_verify_at=verified_at,
                    last_verified_snapshot_id=snapshot_id,
                    protection_state=next_state,
                )
            update_state(store_id, memory_dir=settings.memory_dir, **changes)
            logger.info(
                "Verified Ormah Cloud snapshot %s is restorable", self._message(snapshot_id)
            )
            return ProtectionOperation(
                operation_id,
                ProtectionOperationKind.VERIFY,
                ProtectionOperationPhase.COMPLETED,
                next_state,
                snapshot_id=snapshot_id,
            )
        except Exception as exc:
            offline = _is_offline_error(exc)
            reason_code = (
                exc.reason_code
                if isinstance(exc, _VerificationPrerequisiteError)
                else ProtectionReasonCode.OFFLINE
                if offline
                else ProtectionReasonCode.BUNDLE_CORRUPT
                if isinstance(exc, BundleError)
                else ProtectionReasonCode.VERIFICATION_FAILED
            )
            return self._verification_failure(
                operation_id,
                exc,
                store_id=store_id,
                snapshot_id=snapshot_id,
                reason_code=reason_code,
                record_health=tracks_latest_snapshot and not offline,
                protection_state=(
                    ProtectionState.OFFLINE
                    if offline
                    else ProtectionState.ATTENTION_REQUIRED
                    if tracks_latest_snapshot
                    else None
                ),
            )
        finally:
            self._close_client(client)
            if tmp_root is not None:
                shutil.rmtree(tmp_root, ignore_errors=True)

    def _verification_failure(
        self,
        operation_id: str,
        error: object,
        *,
        store_id: str | None = None,
        snapshot_id: str | None = None,
        reason_code: ProtectionReasonCode = ProtectionReasonCode.VERIFICATION_FAILED,
        record_health: bool = True,
        protection_state: ProtectionState | None = ProtectionState.ATTENTION_REQUIRED,
    ) -> ProtectionOperation:
        message = self._message(error)
        logger.warning("Ormah Cloud restore verification failed: %s", message)
        if store_id is None:
            try:
                store_id = _existing_store_id(self.settings.memory_dir)
            except Exception:
                store_id = None
        if store_id is not None:
            try:
                current = _load_writable_state(store_id)
                if not isinstance(current.protection_state, ProtectionState):
                    return self._client_update_required_operation(
                        operation_id,
                        ProtectionOperationKind.VERIFY,
                        snapshot_id=snapshot_id,
                    )
                persisted_state = (
                    _state_after_failure(current, protection_state)
                    if protection_state is not None
                    else _known_state(current)
                )
                failed_at = _utc_now()
                changes: dict[str, object] = {
                    "last_operation_id": operation_id,
                    "last_operation_kind": ProtectionOperationKind.VERIFY,
                    "last_operation_phase": ProtectionOperationPhase.FAILED,
                    "last_error_code": reason_code,
                    "last_error_message": message,
                    "last_error_at": failed_at,
                }
                if record_health:
                    changes.update(
                        last_verify_at=failed_at,
                        last_verify_ok=False,
                        last_verify_snapshot_id=snapshot_id,
                        last_verify_error=message,
                    )
                if protection_state is not None:
                    changes["protection_state"] = persisted_state
                update_state(store_id, memory_dir=self.settings.memory_dir, **changes)
                failure_state = persisted_state
            except CloudStateVersionError:
                return self._client_update_required_operation(
                    operation_id,
                    ProtectionOperationKind.VERIFY,
                    snapshot_id=snapshot_id,
                )
            except Exception as exc:
                logger.warning("Could not persist Ormah Cloud state: %s", self._message(exc))
                failure_state = ProtectionState.ATTENTION_REQUIRED
        else:
            failure_state = ProtectionState.ATTENTION_REQUIRED
        return ProtectionOperation(
            operation_id,
            ProtectionOperationKind.VERIFY,
            ProtectionOperationPhase.FAILED,
            failure_state,
            reason_code,
            message,
            snapshot_id,
        )

    def _client_update_required_operation(
        self,
        operation_id: str,
        kind: ProtectionOperationKind,
        *,
        snapshot_id: str | None = None,
    ) -> ProtectionOperation:
        """Fail closed when durable state belongs to a newer client."""

        return ProtectionOperation(
            operation_id,
            kind,
            ProtectionOperationPhase.CANCELED,
            ProtectionState.ATTENTION_REQUIRED,
            ProtectionReasonCode.CLIENT_UPDATE_REQUIRED,
            "This cloud state requires a newer Ormah version.",
            snapshot_id,
        )

    def _store_busy_operation(
        self,
        operation_id: str,
        kind: ProtectionOperationKind,
        *,
        snapshot_id: str | None = None,
    ) -> ProtectionOperation:
        """Return transient contention without changing durable protection health."""

        current_state = ProtectionState.ATTENTION_REQUIRED
        try:
            store_id = _existing_store_id(self.settings.memory_dir)
            if store_id is None:
                current_state = ProtectionState.LOCAL_ONLY
            else:
                current_state = _known_state(load_state(store_id))
        except Exception:
            pass
        logger.info("Ormah Cloud operation canceled because the memory store is busy")
        return ProtectionOperation(
            operation_id,
            kind,
            ProtectionOperationPhase.CANCELED,
            current_state,
            ProtectionReasonCode.STORE_BUSY,
            "Memory store is busy; try again shortly.",
            snapshot_id,
        )

    @staticmethod
    def _close_client(client) -> None:
        close = getattr(client, "close", None) if client is not None else None
        if close is not None:
            try:
                close()
            except Exception:
                pass


class _VerificationPrerequisiteError(RuntimeError):
    def __init__(self, message: str, reason_code: ProtectionReasonCode) -> None:
        super().__init__(message)
        self.reason_code = reason_code
