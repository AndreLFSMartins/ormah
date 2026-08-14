# Task 5: The `auto_llm_judge` positive path records confirmed use

**Files:**
- Modify: `src/ormah/background/session_watcher.py:556-579` (the judge-records transaction block in `_record_whisper_usage_signals`)
- Modify: `tests/test_background/test_session_watcher.py` (append one class)

**Interfaces:**
- Consumes: `MemoryEngine._record_confirmed_use(node_id: str) -> None` from Task 3.
- Produces: nothing for later tasks. Independent of Task 4.

The session watcher writes `affinity` and `signals` rows **directly**, through `_insert_affinity` and `_insert_usage_signal`, and never calls `submit_feedback`. So Task 4's allowlist does not reach it, and this path needs its own hook. `auto_heuristic` records (`:494-514`) are a separate loop and stay untouched.

Placement matters: the judge loop runs inside `with engine.db.transaction() as conn:` over a whole batch. `_record_confirmed_use` writes a markdown file before its DB update, so calling it inside would hold `BEGIN IMMEDIATE` across per-node file I/O for the entire batch. Collect the ids during the loop, apply after the block closes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_session_watcher.py`:

```python
# ---------------------------------------------------------------------------
# TestLlmJudgeConfirmedUse — #220
# ---------------------------------------------------------------------------


class TestLlmJudgeConfirmedUse:
    """A positive auto_llm_judge verdict is confirmed use; auto_heuristic is not."""

    LIFECYCLE_FIELDS = ("access_count", "last_accessed", "last_review", "stability")

    def _fields(self, engine, node_id):
        node = engine.file_store.load(node_id)
        return {f: getattr(node, f) for f in self.LIFECYCLE_FIELDS}

    def test_positive_judge_verdict_confirms_use(self, engine):
        from ormah.background import session_watcher
        from ormah.models.node import CreateNodeRequest

        node_id, _ = engine.remember(CreateNodeRequest(
            content="A whispered memory the judge says was used.",
            title="Judged used",
            type="fact",
            tier="working",
        ))
        before = self._fields(engine, node_id)

        session_watcher._record_confirmed_use_batch(engine, [node_id])

        after = self._fields(engine, node_id)
        assert after["access_count"] == before["access_count"] + 1
        assert after["stability"] > before["stability"]

    def test_batch_helper_tolerates_a_missing_node(self, engine):
        from ormah.background import session_watcher

        # Must not raise: whisper_log can outlive the node it points at.
        session_watcher._record_confirmed_use_batch(engine, ["does-not-exist"])

    def test_batch_helper_applies_to_every_id(self, engine):
        from ormah.background import session_watcher
        from ormah.models.node import CreateNodeRequest

        ids = []
        for i in range(3):
            node_id, _ = engine.remember(CreateNodeRequest(
                content=f"Whispered memory number {i}.",
                title=f"Judged {i}",
                type="fact",
                tier="working",
            ))
            ids.append(node_id)
        before = {node_id: self._fields(engine, node_id) for node_id in ids}

        session_watcher._record_confirmed_use_batch(engine, ids)

        for node_id in ids:
            after = self._fields(engine, node_id)
            assert after["access_count"] == before[node_id]["access_count"] + 1
```

These test the extracted helper rather than driving a full transcript through `_record_whisper_usage_signals`, which needs an LLM judge and a transcript fixture. The wiring — that only `polarity == 1` judge records reach the helper — is covered by reading Step 3's diff and by the `auto_heuristic` loop being left alone.

- [ ] **Step 2: Run to verify they fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_background/test_session_watcher.py::TestLlmJudgeConfirmedUse -v )
```

Expected: all three FAIL with `AttributeError: module 'ormah.background.session_watcher' has no attribute '_record_confirmed_use_batch'`.

- [ ] **Step 3: Add the helper and wire it into the judge loop**

In `src/ormah/background/session_watcher.py`, add the helper immediately above `def _record_whisper_usage_signals(` (currently `:402`):

```python
def _record_confirmed_use_batch(engine: MemoryEngine, node_ids: list[str]) -> None:
    """Apply confirmed use to *node_ids*, outside any open transaction.

    Kept separate from the judge loop on purpose: _record_confirmed_use writes
    the markdown file before stamping the SQLite row, so running it inside the
    batch transaction would hold BEGIN IMMEDIATE across per-node file I/O.
    """
    for node_id in node_ids:
        engine._record_confirmed_use(node_id)
```

Then replace the judge-records block at `:556-579`:

```python
    with engine.db.transaction() as conn:
        for record in judge_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_LLM_JUDGE_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] in (1, -1):
                _insert_affinity(
                    conn,
                    row,
                    signal=record["polarity"],
                    source=_LLM_JUDGE_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )

    return recorded
```

with:

```python
    confirmed_use_ids: list[str] = []
    with engine.db.transaction() as conn:
        for record in judge_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_LLM_JUDGE_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] in (1, -1):
                _insert_affinity(
                    conn,
                    row,
                    signal=record["polarity"],
                    source=_LLM_JUDGE_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )
            # Only a positive verdict is confirmed use (#220). A negative one
            # stays prompt-specific affinity evidence, and an uncertain verdict
            # (polarity 0) is neither.
            if record["polarity"] == 1:
                confirmed_use_ids.append(row["node_id"])

    _record_confirmed_use_batch(engine, confirmed_use_ids)

    return recorded
```

`row["node_id"]` is available: the query at `:419` selects `wl.node_id`.

Leave the `auto_heuristic` loop at `:494-514` exactly as it is. Its positive records write affinity and must **not** confirm use until #218 lands.

- [ ] **Step 4: Run to verify the tests pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_background/test_session_watcher.py -v )
```

Expected: all PASS, including the file's pre-existing tests.

- [ ] **Step 5: Confirm the heuristic path was not wired by accident**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  grep -n "_record_confirmed_use_batch\|_HEURISTIC_AFFINITY_SOURCE" src/ormah/background/session_watcher.py )
```

Expected: `_record_confirmed_use_batch` appears exactly twice (its definition and one call), and `_HEURISTIC_AFFINITY_SOURCE` appears exactly twice (its constant and the heuristic loop) — with no call to the batch helper anywhere near the heuristic loop.

- [ ] **Step 6: Full suite and baseline diff**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort > /tmp/220-after-task5.txt )
diff /tmp/220-baseline-ids.txt /tmp/220-after-task5.txt
```

Expected: no added (`>`) lines.

- [ ] **Step 7: Lint**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && ruff check src/ tests/ )
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py && \
  git commit -m "feat(lifecycle): positive auto_llm_judge verdicts record confirmed use

The session watcher writes affinity rows directly and never goes through
submit_feedback, so it needs its own hook into the same lifecycle operation.

Confirmed use is applied after the batch transaction closes rather than inside
it: the mutator writes markdown before the DB row, and doing that per node
under BEGIN IMMEDIATE would hold the write lock for the whole batch.

The auto_heuristic loop is untouched — it keeps recording affinity and keeps
not confirming use until #218.

Refs #220" )
```
