from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from ormah.cloud import jobs, protection, state
from ormah.cloud.entitlements import EntitlementStatus
from ormah.cloud.protection import CloudProtectionService, CloudProtectionStatus
from ormah.cloud.state import (
    ProtectionOperation,
    ProtectionOperationKind,
    ProtectionOperationPhase,
    ProtectionReasonCode,
    ProtectionState,
    load_state,
    state_path,
)
from tests.test_cloud_jobs import (
    FakeCloudClient,
    _patch_upload_prerequisites,
    _patch_verification,
    _settings,
    _verification_bundle,
)


@pytest.fixture
def cloud_state_dir(tmp_path, monkeypatch):
    path = tmp_path / "cloud-state"
    monkeypatch.setattr(state, "CLOUD_STATE_DIR", path)
    return path


def test_backup_now_returns_typed_completed_operation(tmp_path, monkeypatch, cloud_state_dir):
    settings, store_id = _settings(tmp_path)
    state.update_state(
        store_id,
        memory_dir=settings.memory_dir,
        last_upload_at=protection._utc_now(),
        protection_state=ProtectionState.PROTECTED,
    )
    client = FakeCloudClient()
    _patch_upload_prerequisites(monkeypatch, client)

    result = CloudProtectionService(settings).backup_now()

    assert isinstance(result, ProtectionOperation)
    assert result.kind is ProtectionOperationKind.BACKUP
    assert result.phase is ProtectionOperationPhase.COMPLETED
    assert result.state is ProtectionState.CHANGES_PENDING
    assert result.snapshot_id == "01SNAPSHOT"
    assert client.finalized == [(store_id, "upload-1")]
    durable = load_state(store_id)
    assert durable.last_operation_id == result.operation_id
    assert durable.last_operation_phase is ProtectionOperationPhase.COMPLETED


def test_failed_put_returns_typed_failure_and_never_finalizes(
    tmp_path, monkeypatch, cloud_state_dir
):
    settings, _store_id = _settings(tmp_path)
    client = FakeCloudClient()
    _patch_upload_prerequisites(monkeypatch, client)
    monkeypatch.setattr(
        protection,
        "put_file",
        lambda url, path, headers: (_ for _ in ()).throw(OSError("PUT failed")),
    )

    result = CloudProtectionService(settings).backup_now()

    assert isinstance(result, ProtectionOperation)
    assert result.phase is ProtectionOperationPhase.FAILED
    assert result.reason_code is ProtectionReasonCode.UPLOAD_FAILED
    assert client.finalized == []


def test_verify_now_accepts_snapshot_id_after_entitlement_lapse(
    tmp_path, monkeypatch, cloud_state_dir
):
    settings, store_id = _settings(tmp_path)
    settings.cloud_backup_enabled = False
    state.update_state(
        store_id,
        memory_dir=settings.memory_dir,
        last_successful_backup_snapshot_id="01SNAPSHOT",
        protection_state=ProtectionState.CHANGES_PENDING,
    )
    bundle, identity = _verification_bundle(tmp_path, settings, store_id)
    client = FakeCloudClient(bundle=bundle)
    _patch_verification(monkeypatch, client, bundle, identity)
    monkeypatch.setattr(
        protection,
        "check_entitlement",
        lambda settings: (_ for _ in ()).throw(
            AssertionError("downloads must not check upload entitlement")
        ),
    )

    result = CloudProtectionService(settings).verify_now("01SNAPSHOT")

    assert isinstance(result, ProtectionOperation)
    assert result.kind is ProtectionOperationKind.VERIFY
    assert result.phase is ProtectionOperationPhase.COMPLETED
    assert result.state is ProtectionState.PROTECTED
    assert result.snapshot_id == "01SNAPSHOT"
    assert load_state(store_id).last_verified_snapshot_id == "01SNAPSHOT"


def test_verifying_an_older_snapshot_does_not_claim_latest_backup_is_protected(
    tmp_path, monkeypatch, cloud_state_dir
):
    settings, store_id = _settings(tmp_path)
    state.update_state(
        store_id,
        memory_dir=settings.memory_dir,
        last_successful_backup_snapshot_id="01NEWER",
        protection_state=ProtectionState.CHANGES_PENDING,
    )
    bundle, identity = _verification_bundle(tmp_path, settings, store_id)
    client = FakeCloudClient(bundle=bundle)
    _patch_verification(monkeypatch, client, bundle, identity)

    result = CloudProtectionService(settings).verify_now("01SNAPSHOT")

    assert result.phase is ProtectionOperationPhase.COMPLETED
    assert result.state is ProtectionState.CHANGES_PENDING
    assert load_state(store_id).protection_state is ProtectionState.CHANGES_PENDING


def test_expired_entitlement_pauses_only_direct_upload(tmp_path, monkeypatch, cloud_state_dir):
    settings, store_id = _settings(tmp_path)
    state.update_state(
        store_id,
        memory_dir=settings.memory_dir,
        protection_state=ProtectionState.PROTECTED,
    )
    monkeypatch.setattr(protection, "key_file_exists", lambda: True)
    monkeypatch.setattr(protection, "check_entitlement", lambda settings: EntitlementStatus.EXPIRED)
    monkeypatch.setattr(
        protection,
        "client_from_settings",
        lambda settings: (_ for _ in ()).throw(AssertionError("upload should not start")),
    )

    result = CloudProtectionService(settings).backup_now()

    assert result.phase is ProtectionOperationPhase.CANCELED
    assert result.state is ProtectionState.PAUSED
    assert result.reason_code is ProtectionReasonCode.ENTITLEMENT_EXPIRED


def test_corrupt_state_stops_backup_and_verification_before_network(
    tmp_path, monkeypatch, cloud_state_dir
):
    settings, store_id = _settings(tmp_path)
    path = state_path(store_id)
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(protection, "key_file_exists", lambda: True)
    monkeypatch.setattr(
        protection,
        "check_entitlement",
        lambda settings: (_ for _ in ()).throw(AssertionError("entitlement should not run")),
    )
    monkeypatch.setattr(
        protection,
        "client_from_settings",
        lambda settings: (_ for _ in ()).throw(AssertionError("network should not run")),
    )

    backup = CloudProtectionService(settings).backup_now()
    verification = CloudProtectionService(settings).verify_now()

    assert backup.phase is ProtectionOperationPhase.FAILED
    assert verification.phase is ProtectionOperationPhase.FAILED
    assert path.read_bytes() == before


def test_scheduler_adapters_delegate_and_keep_legacy_results(monkeypatch):
    calls = []
    backup = ProtectionOperation(
        "backup-op",
        ProtectionOperationKind.BACKUP,
        ProtectionOperationPhase.COMPLETED,
        ProtectionState.CHANGES_PENDING,
        snapshot_id="01BACKUP",
    )
    verify = ProtectionOperation(
        "verify-op",
        ProtectionOperationKind.VERIFY,
        ProtectionOperationPhase.COMPLETED,
        ProtectionState.PROTECTED,
        snapshot_id="01BACKUP",
    )

    class FakeService:
        @classmethod
        def from_engine(cls, engine):
            calls.append(("engine", engine))
            return cls()

        def backup_now(self, reason="manual", *, only_if_due=False):
            calls.append(("backup", reason, only_if_due))
            return backup

        def verify_now(self, snapshot_id=None):
            calls.append(("verify", snapshot_id))
            return verify

    engine = SimpleNamespace(settings=SimpleNamespace(cloud_backup_enabled=True))
    monkeypatch.setattr(jobs, "CloudProtectionService", FakeService)

    assert jobs.run_cloud_backup(engine) == "01BACKUP"
    assert jobs.run_restore_verification(engine) is True
    assert calls == [
        ("engine", engine),
        ("backup", "cloud", True),
        ("engine", engine),
        ("verify", None),
    ]


@pytest.mark.parametrize(
    ("adapter", "fallback"),
    [(jobs.run_cloud_backup, None), (jobs.run_restore_verification, False)],
)
def test_scheduler_adapters_swallow_unexpected_exceptions(monkeypatch, caplog, adapter, fallback):
    class BrokenService:
        @classmethod
        def from_engine(cls, engine):
            raise RuntimeError("https://objects.example/secret?token=do-not-log")

    monkeypatch.setattr(jobs, "CloudProtectionService", BrokenService)

    engine = SimpleNamespace(settings=SimpleNamespace(cloud_backup_enabled=True))
    with caplog.at_level(logging.WARNING):
        assert adapter(engine) is fallback

    assert "RuntimeError" in caplog.text
    assert "objects.example" not in caplog.text
    assert "do-not-log" not in caplog.text


def test_status_is_typed_and_corrupt_state_fails_closed(tmp_path, monkeypatch, cloud_state_dir):
    settings, store_id = _settings(tmp_path)
    path = state_path(store_id)
    path.parent.mkdir(parents=True)
    path.write_text('{"protection_state":"protected","last_verify_ok":"yes"}', encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(protection, "check_entitlement", lambda settings: EntitlementStatus.ACTIVE)

    result = CloudProtectionService(settings).status()

    assert isinstance(result, CloudProtectionStatus)
    assert result.protection_state is ProtectionState.ATTENTION_REQUIRED
    assert result.state_error is not None
    assert result.last_verify_ok is None
    assert path.read_bytes() == before
    assert json.loads(path.read_text(encoding="utf-8"))["protection_state"] == "protected"


def test_service_can_be_constructed_from_engine(tmp_path):
    settings, _store_id = _settings(tmp_path)

    service = CloudProtectionService.from_engine(SimpleNamespace(settings=settings))

    assert service.settings is settings
