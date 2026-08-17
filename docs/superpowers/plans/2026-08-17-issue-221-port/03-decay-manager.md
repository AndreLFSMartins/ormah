### Task 3: `decay_manager` shares the retrievability and anchors on use

**Files:**
- Modify: `src/ormah/background/decay_manager.py:50-58`
- Modify: `tests/test_background/test_decay_manager.py`

**Interfaces:**
- Consumes: `lifecycle.retrievability` from Task 1.
- Produces: nothing consumed by later tasks.

`local-main`'s `decay_manager` still carries the inline `math.exp`, so the retrievability change ports almost as-is from `4cf017f`. It is **not** untouched, though: #222 (`5c4a1fe`) removed the importance pre-gate from `run_decay`, and the test file already carries #222-era tests. Diff before you apply anything.

- [ ] **Step 1: Write the failing test**

```bash
git show 4cf017f:tests/test_background/test_decay_manager.py > /tmp/t3-decay-tests.py
```

Diff `/tmp/t3-decay-tests.py` against `tests/test_background/test_decay_manager.py` and apply only the additions #221 made — including `test_a_naive_last_accessed_on_one_row_does_not_abort_the_whole_run`. Do not overwrite the file wholesale: `local-main` may carry decay tests from #222 that `4cf017f` never had.

**There is no importance gate on this branch, and no decay test needs to lower `importance`.** #222 (`5c4a1fe`) removed it — that is what #222 *is*: retrievability alone controls the working→archival demotion. `grep -n importance src/ormah/background/decay_manager.py` returns nothing.

This constraint was carried over verbatim from #221's plan, where the gate still existed and a test left at the default `importance = 0.5` never reached the retrievability code. **Here it is dead**, and following it adds setup that does nothing while implying a gate that is gone.

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_background/test_decay_manager.py -v`
Expected: the new tests fail — the naive-timestamp one because `(now - anchor)` sits outside the inner `try` and aborts the whole run through the outer `except Exception`.

- [ ] **Step 3: Replace the retrievability block**

Add `from ormah import lifecycle` to the imports. Replace:

```python
            # Compute FSRS retrievability
            stability = row["stability"] if row["stability"] else 1.0
            anchor_str = row["last_review"] or row["last_accessed"]
            try:
                anchor = datetime.fromisoformat(anchor_str)
            except (ValueError, TypeError):
                continue
            days_since = max((now - anchor).total_seconds() / 86400, 0.001)
            retrievability = math.exp(-days_since / stability)
```

with:

```python
            # Compute FSRS retrievability through the shared implementation (#221).
            # Anchor on use, not on the numeric stability update: the per-day
            # reinforcement cooldown can leave last_review a full window behind
            # the last use, and an actively used node must not read as stale.
            anchor_str = row["last_accessed"] or row["last_review"]
            try:
                anchor = datetime.fromisoformat(anchor_str)
                days_since = (now - anchor).total_seconds() / 86400
                # A naive anchor (hand-edited or externally generated frontmatter)
                # makes `now - anchor` raise TypeError; keep that failure scoped to
                # this one row instead of letting the outer except abort the whole
                # run and silently disable decay for every node in the store.
            except (ValueError, TypeError):
                continue
            # Pass the stored stability raw and let lifecycle own the zero case,
            # with the SAME fallback reinforcement uses. Hardcoding 1.0 here
            # while reinforcement falls back to fsrs_initial_stability is how
            # the two paths silently disagree (council round 3, I3).
            retrievability = lifecycle.retrievability(
                days_since,
                row["stability"],
                fallback_stability=settings.fsrs_initial_stability,
            )
```

Remove the now-unused `math` import only if nothing else in the file uses it — check before deleting.

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/python -m pytest tests/test_background/test_decay_manager.py -v`
Expected: all pass.

- [ ] **Step 5: Prove the hardening is load-bearing**

Move `days_since = (now - anchor)...` back outside the `try`, run `test_a_naive_last_accessed_on_one_row_does_not_abort_the_whole_run`, and confirm it fails with `can't subtract offset-naive and offset-aware datetimes` and leaves the well-formed node in `working`. Restore and confirm green. Report both.

- [ ] **Step 6: Commit**

```bash
./.venv/bin/python -m ruff check src/ tests/
git add src/ormah/background/decay_manager.py tests/test_background/test_decay_manager.py
git commit -m "fix(lifecycle): decay uses the shared retrievability and anchors on use (#221)"
```

