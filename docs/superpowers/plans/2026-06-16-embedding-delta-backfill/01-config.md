# Task 01: Config settings

**Files:**
- Modify: `src/ormah/config.py` (settings block ~L52-58; validators ~L280-311)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_embedding_backfill_settings_defaults():
    from ormah.config import Settings
    s = Settings()
    assert s.embedding_backfill_interval_minutes == 60
    assert s.embedding_index_max_retries == 2
    assert s.embedding_index_retry_backoff_seconds == 0.5


def test_embedding_backfill_interval_rejects_zero():
    import pytest
    from pydantic import ValidationError
    from ormah.config import Settings
    with pytest.raises(ValidationError):
        Settings(embedding_backfill_interval_minutes=0)


def test_embedding_index_max_retries_rejects_negative():
    import pytest
    from pydantic import ValidationError
    from ormah.config import Settings
    with pytest.raises(ValidationError):
        Settings(embedding_index_max_retries=-1)


def test_embedding_schema_max_attempts_default_and_floor():
    import pytest
    from pydantic import ValidationError
    from ormah.config import Settings
    assert Settings().embedding_schema_max_attempts == 3
    with pytest.raises(ValidationError):
        Settings(embedding_schema_max_attempts=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_embedding_backfill_settings_defaults -v`
Expected: FAIL — `AttributeError`/`ValidationError` (unknown field).

- [ ] **Step 3: Add the settings**

In `src/ormah/config.py`, after the `auto_cluster_interval_minutes` line (~L58) inside the
"Background intervals" block add:

```python
    # Embedding backfill / vector-store reconciliation (#32)
    embedding_backfill_interval_minutes: int = 60
    embedding_index_max_retries: int = 2
    embedding_index_retry_backoff_seconds: float = 0.5
    embedding_schema_max_attempts: int = 3  # quarantine a node after this many failed schema-bump embeds
```

- [ ] **Step 4: Add validators**

Add `embedding_backfill_interval_minutes` to the existing `_interval_minutes_positive`
field_validator list (~L280-285) so it reads:

```python
    @field_validator(
        "auto_link_interval_minutes",
        "conflict_check_interval_minutes",
        "duplicate_check_interval_minutes",
        "auto_cluster_interval_minutes",
        "embedding_backfill_interval_minutes",
    )
    @classmethod
    def _interval_minutes_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"interval must be >= 1 minute, got {v}")
        return v
```

Then add a new validator below it:

```python
    @field_validator("embedding_index_max_retries")
    @classmethod
    def _embedding_index_max_retries_nonneg(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"embedding_index_max_retries must be >= 0, got {v}")
        return v

    @field_validator("embedding_index_retry_backoff_seconds")
    @classmethod
    def _embedding_index_backoff_nonneg(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"embedding_index_retry_backoff_seconds must be >= 0, got {v}")
        return v

    @field_validator("embedding_schema_max_attempts")
    @classmethod
    def _embedding_schema_max_attempts_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"embedding_schema_max_attempts must be >= 1, got {v}")
        return v
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -v -k embedding_backfill or embedding_index`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/config.py tests/test_config.py
git add src/ormah/config.py tests/test_config.py
git commit -m "feat(config): add embedding backfill + index-retry settings (#32)"
```
