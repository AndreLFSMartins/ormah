import pytest
from pydantic import ValidationError

from ormah.config import Settings


def test_flush_defaults():
    s = Settings()
    assert s.session_watcher_flush_bytes == 60000
    assert s.session_watcher_retry_seconds == 30.0     # decoupled from idle
    assert s.session_watcher_idle_threshold == 600.0   # policy A
    assert s.session_watcher_flush_bytes <= s.ingest_max_content_chars


def test_flush_bytes_over_cap_rejected():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_bytes=200000, ingest_max_content_chars=100000)


def test_flush_bytes_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_bytes=500)


def test_flush_bytes_equal_cap_allowed():
    s = Settings(session_watcher_flush_bytes=100000, ingest_max_content_chars=100000)
    assert s.session_watcher_flush_bytes == s.ingest_max_content_chars


def test_retry_seconds_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_retry_seconds=0)
