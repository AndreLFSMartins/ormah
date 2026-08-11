# Task 4: Enforce `flush_chars ≤ ingest_chunk_chars` (⛔ ADR-0001 Amendment 2)

**Files:**
- Modify: `src/ormah/config.py:347` (default), `:568-573` (validator), `_flush_chars_within_cap`
- Test: `tests/test_background/test_session_watcher_flush.py`, `tests/test_engine/test_ingest.py:292-296`

**Interfaces:**
- Consumes: Task 3's `Settings.session_watcher_flush_chars`.
- Produces: the enforced chain `flush_chars ≤ ingest_chunk_chars ≤ ingest_max_content_chars`.

**This task is not optional and it cannot ship separately.** Amendment 2 prescribed a
`flush ≤ chunk` validator that was never added. Today `ingest_chunk_chars = 40000 <
flush = 60000`, and the violation is **masked** only because payloads never approach 40000 chars. The
moment Task 1 lands, every full Batch splits into two chunk-blind extraction calls
(`_INGEST_LLM_PROMPT.format(conversation=chunk)` sees one chunk at a time), re-introducing exactly the
cross-chunk blindness the sweet-spot sizing exists to remove — a fact decided in chunk 1 and superseded
in chunk 2 gets extracted stale.

**Value decision.** Set `ingest_chunk_chars = 60000`: the minimum that satisfies the invariant, smallest
blast radius. Do **not** raise it to `ingest_max_content_chars` (100000) here — that is a separate
judgement about the oversized-single-turn case, and it is out of scope.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_session_watcher_flush.py`:

```python
def test_chunk_chars_defaults_at_or_above_the_flush_budget():
    """ADR-0001 Amendment 2: a Batch sized to the recall sweet spot must reach the Extractor
    in ONE reasoning context. A chunk smaller than the batch chops every full batch into
    chunk-blind calls by design."""
    s = Settings()
    assert s.ingest_chunk_chars >= s.session_watcher_flush_chars
    assert s.ingest_chunk_chars <= s.ingest_max_content_chars


def test_chunk_smaller_than_flush_is_rejected():
    """The validator Amendment 2 prescribed and that was never added. Without it the
    violation returns silently."""
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_chars=60000, ingest_chunk_chars=40000)


def test_a_full_batch_reaches_the_extractor_as_one_chunk(tmp_path):
    """The behavioural consequence, not just the validator: a payload the size of a full
    Batch must produce exactly ONE extraction call."""
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    calls = []

    def fake_generate(settings, prompt, **kwargs):
        calls.append(prompt)
        return '{"memories": []}'

    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate,
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            engine._extract_memories_llm("x" * settings.session_watcher_flush_chars)
    finally:
        engine.shutdown()

    assert len(calls) == 1, f"a full Batch was split into {len(calls)} chunk-blind calls"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./.venv/bin/python -m pytest tests/test_background/test_session_watcher_flush.py -k "chunk" -v
```

Expected: FAIL — `assert 40000 >= 60000`, no `ValidationError` raised, and 2 calls instead of 1.

- [ ] **Step 3: Raise the default**

Replace `src/ormah/config.py:347` with:

```python
    ingest_chunk_chars: int = 60000  # >= session_watcher_flush_chars, so a full Batch is ONE call
```

- [ ] **Step 4: Add the invariant to the model validator**

In `_flush_chars_within_cap` (from Task 3), insert this check **before** the existing
`ingest_max_content_chars` check, so the operator sees the tighter, more actionable bound first:

```python
        if self.session_watcher_flush_chars > self.ingest_chunk_chars:
            raise ValueError(
                f"session_watcher_flush_chars ({self.session_watcher_flush_chars}) must be <= "
                f"ingest_chunk_chars ({self.ingest_chunk_chars}); a chunk smaller than the batch "
                "chops every full Batch into chunk-blind extraction calls, re-introducing the "
                "cross-chunk blindness the sweet-spot sizing exists to remove (ADR-0001 "
                "Amendment 2)"
            )
```

Then extend the chain check so `ingest_chunk_chars` cannot exceed the hard cap either:

```python
        if self.ingest_chunk_chars > self.ingest_max_content_chars:
            raise ValueError(
                f"ingest_chunk_chars ({self.ingest_chunk_chars}) must be <= "
                f"ingest_max_content_chars ({self.ingest_max_content_chars})"
            )
```

- [ ] **Step 5: Fix the tests the new invariant breaks**

`tests/test_background/test_session_watcher_flush.py:321-323` constructs settings that now violate the
chain. Add the missing knob:

```python
    settings = Settings(
        memory_dir=tmp_path, ingest_max_content_chars=1000, session_watcher_flush_chars=1000,
        ingest_chunk_chars=1000,
    )
```

`tests/test_engine/test_ingest.py:295-296` already sets both `ingest_max_content_chars = 2000` and
`ingest_chunk_chars = 2000`, but mutates them on an existing `engine.settings` rather than constructing
`Settings`, so no validator runs. Leave it as is — but verify it still passes, because
`session_watcher_flush_chars` stays at its 60000 default there and only the runtime values matter.

Now sweep for any other construction that trips the chain:

```bash
grep -rn "ingest_chunk_chars\|ingest_max_content_chars" tests/ --include='*.py'
```

Fix every `Settings(...)` call (not attribute mutation) that leaves the chain violated.

- [ ] **Step 6: Run the full suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: PASS. (This task both adds the `ingest_chunk_chars <= ingest_max_content_chars`
check and fixes the one test that construction breaks, in the same commit — Task 3 left
nothing red.)

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/ tests/
git add src/ormah/config.py tests/
git commit -m "fix(config): enforce flush_chars <= ingest_chunk_chars <= ingest_max_content_chars

ADR-0001 Amendment 2 prescribed this validator and it was never added, so
ingest_chunk_chars=40000 < flush=60000 held in live config. The violation was masked only
because payloads never approached 40000 chars; budgeting on conversation length un-masks it,
and every full Batch would split into two chunk-blind extraction calls.

Raises ingest_chunk_chars to 60000 -- the minimum that satisfies the invariant."
```
