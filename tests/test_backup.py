from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import sqlite3
from unittest.mock import patch

import pytest

from ormah.backup import BackupError, BackupService, resolve_backup_user_node_id, run_auto_backup
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine
from ormah.index.db import Database
from ormah.models.node import MemoryNode, NodeType, Tier
from ormah.store.file_store import FileStore


def _service(memory_dir: Path, backup_dir: Path, retention_count: int = 10) -> BackupService:
    return BackupService(
        memory_dir=memory_dir,
        backup_dir=backup_dir,
        retention_count=retention_count,
    )


def _save_node(memory_dir: Path, title: str, content: str) -> MemoryNode:
    store = FileStore(memory_dir / "nodes")
    node = MemoryNode(type=NodeType.fact, title=title, content=content)
    store.save(node)
    return node


def _save_self_node(memory_dir: Path, title: str) -> MemoryNode:
    node = MemoryNode(
        type=NodeType.person,
        tier=Tier.core,
        source="system:self",
        title=title,
        content=f"Identity node {title}",
    )
    FileStore(memory_dir / "nodes").save(node)
    return node


def _set_active_self(memory_dir: Path, node_id: str) -> None:
    database = Database(memory_dir / "index.db")
    try:
        database.init_schema()
        with database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('user_node_id', ?)",
                (node_id,),
            )
    finally:
        database.close()


def _active_self(memory_dir: Path) -> str | None:
    connection = sqlite3.connect(memory_dir / "index.db")
    try:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'user_node_id'"
        ).fetchone()
    finally:
        connection.close()
    return row[0] if row else None


def test_create_backup_copies_nodes_and_deleted_only(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    active = _save_node(memory_dir, "Active", "Active memory")
    deleted = _save_node(memory_dir, "Deleted", "Deleted memory")
    FileStore(memory_dir / "nodes").soft_delete(deleted.id)
    (memory_dir / "index.db").write_text("derived index", encoding="utf-8")
    (memory_dir / ".env").write_text("SECRET=value", encoding="utf-8")

    backup = _service(memory_dir, backup_dir).create(
        now=datetime(2026, 4, 26, 20, 45, 12, tzinfo=timezone.utc)
    )

    assert backup.name == "memory_2026-04-26_20-45-12"
    assert backup.node_count == 1
    assert backup.deleted_count == 1
    assert (backup.path / "nodes").is_dir()
    assert (backup.path / "deleted").is_dir()
    assert list((backup.path / "nodes").glob(f"*_{active.short_id}.md"))
    assert list((backup.path / "deleted").glob(f"*_{deleted.short_id}.md"))
    assert not (backup.path / "index.db").exists()
    assert not (backup.path / ".env").exists()


def test_create_backup_records_exact_active_self_with_historical_duplicate(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    historical = _save_self_node(memory_dir, "Historical Self")
    active = _save_self_node(memory_dir, "Active Self")
    _set_active_self(memory_dir, active.id)

    backup = _service(memory_dir, backup_dir).create()

    manifest = json.loads((backup.path / "backup.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 2
    assert manifest["user_node_id"] == active.id
    assert manifest["user_node_id"] != historical.id
    assert resolve_backup_user_node_id(backup.path) == active.id


def test_retention_keeps_latest_ten_backups(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    _save_node(memory_dir, "Memory", "Content")
    service = _service(memory_dir, backup_dir, retention_count=10)
    start = datetime(2026, 4, 26, 20, 0, 0, tzinfo=timezone.utc)

    for offset in range(12):
        service.create(now=start + timedelta(seconds=offset))

    backups = service.list()

    assert len(backups) == 10
    assert backups[0].name == "memory_2026-04-26_20-00-11"
    assert backups[-1].name == "memory_2026-04-26_20-00-02"
    assert not (backup_dir / "memory_2026-04-26_20-00-00").exists()
    assert not (backup_dir / "memory_2026-04-26_20-00-01").exists()


def test_concurrent_backup_creates_use_distinct_atomic_directories(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    _save_node(memory_dir, "Memory", "Content")
    service = _service(memory_dir, backup_dir)
    created_at = datetime(2026, 4, 26, 20, 0, 0, tzinfo=timezone.utc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        backups = list(pool.map(lambda _: service.create(now=created_at), range(2)))

    assert {backup.name for backup in backups} == {
        "memory_2026-04-26_20-00-00",
        "memory_2026-04-26_20-00-00_01",
    }


def test_restore_replaces_memory_files_and_rebuilds_index(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    original = _save_node(memory_dir, "Original", "Original memory")
    deleted = _save_node(memory_dir, "Old deleted", "Deleted memory")
    FileStore(memory_dir / "nodes").soft_delete(deleted.id)
    service = _service(memory_dir, backup_dir)
    backup = service.create(now=datetime(2026, 4, 26, 20, 0, 0, tzinfo=timezone.utc))

    for path in (memory_dir / "nodes").glob("*.md"):
        path.unlink()
    replacement = _save_node(memory_dir, "Replacement", "Replacement memory")

    result = service.restore(backup.name)

    assert result.restored.name == backup.name
    assert result.safety_backup is not None
    assert result.safety_backup.name.startswith("memory_")
    assert list((memory_dir / "nodes").glob(f"*_{original.short_id}.md"))
    assert list((memory_dir / "deleted").glob(f"*_{deleted.short_id}.md"))
    assert not list((memory_dir / "nodes").glob(f"*_{replacement.short_id}.md"))
    assert result.rebuilt_nodes == 1

    conn = sqlite3.connect(memory_dir / "index.db")
    try:
        row = conn.execute("SELECT id, title FROM nodes").fetchone()
    finally:
        conn.close()
    assert row == (original.id, "Original")


def test_restore_replaces_target_self_pointer_without_reconciling_source_duplicates(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    active = _save_self_node(memory_dir, "Source Active Self")
    historical = _save_self_node(memory_dir, "Source Historical Self")
    _save_node(memory_dir, "Source Memory", "Restored content")
    _set_active_self(memory_dir, active.id)
    service = _service(memory_dir, backup_dir)
    backup = service.create()

    store = FileStore(memory_dir / "nodes")
    for path in store.list_paths():
        path.unlink()
    target_self = _save_self_node(memory_dir, "Target Generated Self")
    _set_active_self(memory_dir, target_self.id)

    result = service.restore(backup.name)

    restored_ids = {node.id for node in FileStore(memory_dir / "nodes").list_all()}
    assert active.id in restored_ids
    assert historical.id in restored_ids
    assert target_self.id not in restored_ids
    assert _active_self(memory_dir) == active.id
    assert result.safety_backup is not None
    assert resolve_backup_user_node_id(result.safety_backup.path) == target_self.id

    database = Database(memory_dir / "index.db")
    try:
        restarted = SimpleNamespace(
            db=database,
            file_store=FileStore(memory_dir / "nodes"),
            user_node_id=None,
        )
        node_count = len(restarted.file_store.list_paths())
        MemoryEngine._ensure_self_node(restarted)
        assert restarted.user_node_id == active.id
        assert len(restarted.file_store.list_paths()) == node_count
    finally:
        database.close()


def test_restore_rejects_invalid_manifest_pointer_before_touching_target(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    target = _save_node(memory_dir, "Target", "Must remain")
    service = _service(memory_dir, backup_dir)
    backup = service.create()
    manifest_path = backup.path / "backup.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["user_node_id"] = "missing-self-node"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="exact system:self node is not present"):
        service.restore(backup.name)

    assert FileStore(memory_dir / "nodes").load(target.id) is not None
    assert len(service.list()) == 1


def test_restore_adopts_unique_self_from_legacy_backup(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    source_self = _save_self_node(memory_dir, "Legacy Source Self")
    service = _service(memory_dir, backup_dir)
    backup = service.create()
    manifest_path = backup.path / "backup.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = 1
    manifest.pop("user_node_id")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    for path in (memory_dir / "nodes").glob("*.md"):
        path.unlink()
    target_self = _save_self_node(memory_dir, "Target Self")
    _set_active_self(memory_dir, target_self.id)

    service.restore(backup.name)

    assert _active_self(memory_dir) == source_self.id
    assert FileStore(memory_dir / "nodes").load(target_self.id) is None


def test_restore_rejects_ambiguous_legacy_self_before_touching_target(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    first = _save_self_node(memory_dir, "First Self")
    _save_self_node(memory_dir, "Second Self")
    _set_active_self(memory_dir, first.id)
    service = _service(memory_dir, backup_dir)
    backup = service.create()
    manifest_path = backup.path / "backup.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = 1
    manifest.pop("user_node_id")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="no portable active pointer"):
        service.restore(backup.name)

    assert _active_self(memory_dir) == first.id
    assert len(service.list()) == 1


def test_auto_backup_creates_only_when_due(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    _save_node(memory_dir, "Memory", "Content")
    settings = Settings(
        memory_dir=memory_dir,
        backup_dir=backup_dir,
        backup_interval_hours=24,
        backup_retention_count=10,
    )
    engine = SimpleNamespace(settings=settings)

    first = run_auto_backup(engine)
    second = run_auto_backup(engine)

    assert first is not None
    assert second is None
    assert len(_service(memory_dir, backup_dir).list()) == 1


def test_auto_backup_skips_empty_memory_store(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    (memory_dir / "nodes").mkdir(parents=True)
    settings = Settings(
        memory_dir=memory_dir,
        backup_dir=backup_dir,
        backup_interval_hours=24,
        backup_retention_count=10,
    )
    engine = SimpleNamespace(settings=settings)

    result = run_auto_backup(engine)

    assert result is None
    assert not backup_dir.exists()


def test_auto_backup_skips_self_only_memory_store(tmp_path):
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    store = FileStore(memory_dir / "nodes")
    store.save(
        MemoryNode(
            type=NodeType.person,
            tier=Tier.core,
            source="system:self",
            title="Self",
            content="The user's identity and personal information.",
        )
    )
    settings = Settings(
        memory_dir=memory_dir,
        backup_dir=backup_dir,
        backup_interval_hours=24,
        backup_retention_count=10,
    )
    engine = SimpleNamespace(settings=settings)

    result = run_auto_backup(engine)

    assert result is None
    assert not backup_dir.exists()


def test_scheduler_registers_memory_backup_job(tmp_path, monkeypatch):
    from ormah.background import scheduler as scheduler_module

    class FakeScheduler:
        def __init__(self):
            self.jobs = []
            self.started = False

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append({"func": func, "trigger": trigger, **kwargs})

        def start(self):
            self.started = True

        def get_jobs(self):
            return self.jobs

    monkeypatch.setattr(scheduler_module, "BackgroundScheduler", FakeScheduler)
    settings = Settings(memory_dir=tmp_path / "memory", backup_dir=tmp_path / "backups")
    engine = SimpleNamespace(
        settings=settings,
        builder=SimpleNamespace(incremental_update=lambda: (0, 0)),
    )

    fake_scheduler, _tracker = scheduler_module.start_scheduler(engine)

    backup_job = next(job for job in fake_scheduler.jobs if job["id"] == "memory_backup")
    assert backup_job["trigger"] == "interval"
    assert backup_job["hours"] == 24
    assert backup_job["next_run_time"] is not None


def test_cli_backup_create_delegates_to_service(tmp_path, capsys):
    from ormah.backup import BackupInfo
    from ormah.cli import main

    backup = BackupInfo(
        name="memory_2026-04-26_20-45-12",
        path=tmp_path / "backups" / "memory_2026-04-26_20-45-12",
        created_at=datetime(2026, 4, 26, 20, 45, 12, tzinfo=timezone.utc),
        node_count=2,
        deleted_count=1,
        size_bytes=123,
    )
    service = SimpleNamespace(create=lambda reason="manual": backup)

    with (
        patch("sys.argv", ["ormah", "backup", "create"]),
        patch("ormah.backup.service_from_settings", return_value=service),
    ):
        main()

    out = capsys.readouterr().out
    assert "Created backup: memory_2026-04-26_20-45-12" in out
    assert "2 active, 1 deleted" in out


def test_cli_backup_status_explains_empty_memory_store(capsys):
    from ormah.cli import main

    service = SimpleNamespace(
        latest=lambda: None,
        has_backupable_memory=lambda: False,
        backup_due=lambda interval_hours: True,
    )

    with (
        patch("sys.argv", ["ormah", "backup", "status"]),
        patch("ormah.backup.service_from_settings", return_value=service),
    ):
        main()

    out = capsys.readouterr().out
    assert "Latest backup: none" in out
    assert "Backup due now: no (no memory nodes yet)" in out
