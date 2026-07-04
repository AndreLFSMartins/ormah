"""Shared test fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine
from ormah.index.db import Database
from ormah.store.file_store import FileStore


@pytest.fixture(autouse=True)
def _isolate_settings_from_global_env(monkeypatch, tmp_path):
    """Stop the global ~/.config/ormah/.env and stray ORMAH_* OS vars from
    leaking into bare Settings() during tests (env pollution, not regressions).
    """
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")
    monkeypatch.setitem(Settings.model_config, "env_file", str(empty_env))
    for key in list(os.environ):
        if key.startswith("ORMAH_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Temporary memory directory."""
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    return tmp_path


@pytest.fixture
def settings(tmp_memory_dir):
    return Settings(memory_dir=tmp_memory_dir)


@pytest.fixture
def file_store(tmp_memory_dir):
    return FileStore(tmp_memory_dir / "nodes")


@pytest.fixture
def db(tmp_memory_dir):
    database = Database(tmp_memory_dir / "index.db")
    database.init_schema()
    yield database
    database.close()


@pytest.fixture
def engine(settings):
    eng = MemoryEngine(settings)
    eng.startup()
    yield eng
    eng.shutdown()
