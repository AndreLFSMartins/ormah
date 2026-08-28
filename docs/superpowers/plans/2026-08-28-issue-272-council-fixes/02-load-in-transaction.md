# Task 2: Load the node inside the write transaction

Read `00-overview.md` first — it carries the island rules, the test command, and the baseline.
Task 1 must already be committed (this task's diff sits on top of it, same file).

**Problem:** In `_record_confirmed_use`, `node = self.file_store.load(node_id)` runs BEFORE
`with self.db.transaction()`. `BEGIN IMMEDIATE` can block up to `busy_timeout=5000` ms
(`index/db.py:38`) between the load and the save — a window this branch's diff widened (load and
save were contiguous before it). Moving the load inside restores contiguity. It does NOT fix the
pre-existing dual-writer race across processes — the commit message must say so.

**Files:**
- Modify: `/Users/andre/Documents/GitHub/Tools/ormah-wt-272/src/ormah/engine/memory_engine.py`
  (`_record_confirmed_use`, load at ~`:2295`, transaction at ~`:2310`)
- Test: `/Users/andre/Documents/GitHub/Tools/ormah-wt-272/tests/test_engine/test_confirmed_use_contract.py`

**Interfaces:**
- Consumes: helpers `_make_nodes`, `_seed_whisper_log`, `_take_claim` from the same test file;
  Task 1's committed state of `memory_engine.py`.
- Produces: nothing later tasks rely on.

- [ ] **Step 1: Write the failing test** — append to
  `tests/test_engine/test_confirmed_use_contract.py`, after
  `test_mutator_is_at_most_once_on_an_applied_claim`:

```python
def test_a_failed_latch_never_loads_the_file(engine, monkeypatch):
    """Council #272 finding 2: the load belongs inside the transaction, after
    the latch. Observable consequence — and this test's RED: when the claim is
    already applied, the mutator must return before any file I/O. Today the
    load runs unconditionally before the transaction even opens.
    """
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    _take_claim(engine, log_id, target)
    engine._record_confirmed_use(target, whisper_log_id=log_id)  # applies the claim

    calls = []
    real_load = engine.file_store.load
    monkeypatch.setattr(
        engine.file_store, "load",
        lambda node_id: calls.append(node_id) or real_load(node_id),
    )

    engine._record_confirmed_use(target, whisper_log_id=log_id)  # latch fails

    assert calls == [], (
        "the mutator loaded the markdown for a claim it then refused to apply — "
        "the load must sit inside the transaction, after the at-most-once latch"
    )
```

- [ ] **Step 2: Run it, verify it FAILS for the right reason**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-272
H=$(mktemp -d); H=$(cd "$H" && pwd -P)
HOME="$H" .venv/bin/python -m pytest \
  "tests/test_engine/test_confirmed_use_contract.py::test_a_failed_latch_never_loads_the_file" -v
```

Expected: FAIL with `AssertionError` and `calls == [target]` — the load ran despite the failed
latch. Any other failure means the test is wrong — fix the test, not the code.

- [ ] **Step 3: Implement.** In `_record_confirmed_use`:

  (a) DELETE the standalone load line that sits before the transaction (currently ~`:2295`,
  right after the docstring):

```python
        node = self.file_store.load(node_id)
```

  (b) Keep the existing comment block that begins `# Issue #272: one transaction covers the
  claim's outcome...` where it is (it explains why file I/O inside the transaction is safe —
  now it justifies the load too). Append one sentence to that same comment:

```python
        # The load also lives inside (council #272 finding 2): BEGIN IMMEDIATE can
        # block up to busy_timeout between statements, and loading before the
        # transaction reopened the load->save window this method had closed. A
        # failed latch now returns before any file I/O. Cross-process, load and
        # save remain non-atomic — that race predates this branch.
```

  (c) INSERT the load right after the at-most-once latch guard (the
  `if conn.execute("SELECT changes()")...` block that `return`s when the UPDATE touched no
  row), BEFORE the `row = conn.execute("SELECT access_count, ...` statement:

```python
            node = self.file_store.load(node_id)
```

  The orphan check below (`if node is None or row is None:`) stays exactly as is — `node` is
  still bound before it runs.

- [ ] **Step 4: Run the test again** (same command as Step 2). Expected: PASS.

- [ ] **Step 5: Full suite + ruff** (commands and baseline in `00-overview.md`). Expected:
  `3 failed, 2055 passed` — only the `TestConfigureCodexMcp` trio fails; ruff clean. Pay attention to the mutator tests
  around `test_mutator_failure_leaves_no_residue` and `test_failed_commit_does_not_inflate_the_counter`
  — they exercise this exact method and must stay green.

- [ ] **Step 6: Commit** (island, exact paths; the message is honest about what this does NOT fix):

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-272
git add src/ormah/engine/memory_engine.py tests/test_engine/test_confirmed_use_contract.py
git commit -m "fix(lifecycle): load the node inside the reinforcement transaction (#272)

Restores the pre-branch contiguity of load and save: BEGIN IMMEDIATE could
block up to busy_timeout=5s between them. A failed latch no longer does file
I/O at all. The pre-existing dual-writer race across processes is NOT fixed:
load and save remain non-atomic between binaries sharing the store."
git show --stat HEAD
```

Expected: exactly the two files in the stat.
