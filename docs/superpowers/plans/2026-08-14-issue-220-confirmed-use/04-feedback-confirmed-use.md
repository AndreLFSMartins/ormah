# Task 4: Qualified positive feedback records confirmed use

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:3136-3234` (`_submit_feedback_locked`)
- Modify: `tests/test_engine/test_submit_feedback.py` (append one class)

**Interfaces:**
- Consumes: `MemoryEngine._record_confirmed_use(node_id: str) -> None` from Task 3.
- Produces: nothing new for later tasks. Task 5 is independent of this one.

This is an **addition**, not a rewire: `_submit_feedback_locked` never touched the lifecycle. Verified by reading L3136–L3234 — there is no call to the mutator anywhere in it.

The allowlist is fail-closed: only `signal == 1` with `source` in `{"explicit", "implicit", "auto_llm_judge"}` confirms. `auto_heuristic` is excluded pending #218 — on the reference store that gates off 153 of 184 positive affinity rows, which is deliberate. Every negative signal is prompt-specific affinity evidence and never confirms.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine/test_submit_feedback.py`. The module already provides `_insert_whisper_log(conn, node_id, ...)`; these tests need a **real** node, so they create one via the engine rather than using a synthetic id string.

```python
# ---------------------------------------------------------------------------
# TestFeedbackConfirmedUse — #220
# ---------------------------------------------------------------------------


class TestFeedbackConfirmedUse:
    """Only source-qualified positive feedback is confirmed use (#220, #191)."""

    LIFECYCLE_FIELDS = ("access_count", "last_accessed", "last_review", "stability")

    def _node(self, engine, title="Feedback target"):
        node_id, _ = engine.remember(CreateNodeRequest(
            content="A memory that will receive feedback.",
            title=title,
            type="fact",
            tier="working",
        ))
        _insert_whisper_log(engine.db.conn, node_id)
        return node_id

    def _fields(self, engine, node_id):
        node = engine.file_store.load(node_id)
        return {f: getattr(node, f) for f in self.LIFECYCLE_FIELDS}

    @pytest.mark.parametrize("source", ["explicit", "implicit", "auto_llm_judge"])
    def test_qualified_positive_confirms_use(self, engine, source):
        node_id = self._node(engine)
        before = self._fields(engine, node_id)

        engine.submit_feedback(node_id, 1, source)

        after = self._fields(engine, node_id)
        assert after["access_count"] == before["access_count"] + 1
        assert after["stability"] > before["stability"]

    @pytest.mark.parametrize("source", ["auto_heuristic", "some_future_source"])
    def test_unqualified_positive_does_not_confirm(self, engine, source):
        """auto_heuristic waits on #218; an unknown source fails closed."""
        node_id = self._node(engine)
        before = self._fields(engine, node_id)

        engine.submit_feedback(node_id, 1, source)

        assert self._fields(engine, node_id) == before

    @pytest.mark.parametrize(
        "source", ["explicit", "implicit", "auto_llm_judge", "auto_heuristic"],
    )
    def test_negative_feedback_never_confirms(self, engine, source):
        node_id = self._node(engine)
        before = self._fields(engine, node_id)

        engine.submit_feedback(node_id, -1, source)

        assert self._fields(engine, node_id) == before

    def test_affinity_is_still_recorded_when_use_is_not_confirmed(self, engine):
        """The exclusion is about lifecycle, not about losing the signal."""
        node_id = self._node(engine)

        engine.submit_feedback(node_id, 1, "auto_heuristic")

        row = engine.db.conn.execute(
            "SELECT signal, source FROM affinity WHERE node_id = ?", (node_id,)
        ).fetchone()
        assert row is not None
        assert row["signal"] == 1
        assert row["source"] == "auto_heuristic"

    def test_confirmed_use_applies_to_the_resolved_node_only(self, engine):
        """A second node with its own whisper_log row must be untouched."""
        target = self._node(engine, title="Target")
        bystander = self._node(engine, title="Bystander")
        before_bystander = self._fields(engine, bystander)

        engine.submit_feedback(target, 1, "explicit")

        assert self._fields(engine, bystander) == before_bystander
```

- [ ] **Step 2: Run to verify they fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_submit_feedback.py::TestFeedbackConfirmedUse -v )
```

Expected: the three `test_qualified_positive_confirms_use` cases FAIL on `access_count == before + 1` (nothing increments today). The negative and unqualified cases should already PASS — they assert the status quo, and they exist to stop Step 3 from over-reaching.

- [ ] **Step 3: Add the allowlist constant**

At `src/ormah/engine/memory_engine.py`, immediately above `def submit_feedback(` (currently `:3120`), add a module- or class-level constant. Put it directly above the method, at the same indentation as the method:

```python
    # Sources whose positive feedback counts as confirmed use (#220, decision
    # record #191). auto_heuristic is excluded until #218 gives signal strength
    # real variance. Unlisted sources fail closed.
    _CONFIRMED_USE_SOURCES = frozenset({"explicit", "implicit", "auto_llm_judge"})
```

- [ ] **Step 4: Call the mutator as the last statement of `_submit_feedback_locked`**

At the end of `_submit_feedback_locked` (currently `:3234`), replace:

```python
        return f"Feedback recorded for node {resolved_node_id[:8]}..."
```

with:

```python
        # Confirmed use runs last, inside the transaction the caller opened:
        # _record_confirmed_use saves the markdown file before stamping the DB
        # row, so being last means nothing after it can fail and roll the row
        # back behind an already-written file.
        if signal == 1 and source in self._CONFIRMED_USE_SOURCES:
            self._record_confirmed_use(resolved_node_id)

        return f"Feedback recorded for node {resolved_node_id[:8]}..."
```

Note the placement: **outside** the `with self.db.transaction() as conn:` block that precedes it (same indentation as the `return`), but still inside the outer transaction opened by `submit_feedback` at `:3128`. `Database.transaction` is reentrant per thread (`src/ormah/index/db.py:72`), so the nested transaction inside `_record_confirmed_use` is a pass-through.

- [ ] **Step 5: Run to verify the tests pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_submit_feedback.py -v )
```

Expected: all PASS, including the pre-existing tests in the file. Several of those use synthetic ids like `"node-explicit-001"` that do not exist as nodes; `_record_confirmed_use` returns early when `file_store.load` yields `None`, so they must keep passing unchanged. If one of them now errors, the early return is not doing its job — fix that rather than the test.

- [ ] **Step 6: Full suite and baseline diff**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort > /tmp/220-after-task4.txt )
diff /tmp/220-baseline-ids.txt /tmp/220-after-task4.txt
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
  git add src/ormah/engine/memory_engine.py tests/test_engine/test_submit_feedback.py && \
  git commit -m "feat(lifecycle): qualified positive feedback records confirmed use

submit_feedback never touched the lifecycle at all, so this is the other half
of #220: deliberate positive feedback is exactly the evidence of use that a
result list is not.

The source allowlist is fail-closed — explicit, implicit and auto_llm_judge
confirm; auto_heuristic waits on #218 and any unlisted source is ignored.
Negative feedback stays prompt-specific affinity evidence and never confirms.

Refs #220" )
```
