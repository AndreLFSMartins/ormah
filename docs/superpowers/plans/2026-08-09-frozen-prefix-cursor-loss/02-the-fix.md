# Task 2: The fix

Read `00-overview.md` first. Run everything inside `../ormah-wt-frozen-prefix`. Task 1 must be committed and green.

**Files:**
- Modify: `src/ormah/background/session_watcher.py:1475-1484` — the `NO_PROGRESS` branch of `_run_job`
- Modify: `src/ormah/background/session_watcher.py:1524-1545` — delete `_mark_frozen_prefix_consumed`
- Modify: `src/ormah/background/session_watcher.py:1501-1508` — docstring of `_idle_with_unsafe_tail`
- Modify: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: `IngestSpool.requeue(job, failure_class: str)` — `"external"` retries forever with persisted exponential backoff (2s base, 300s ceiling); any other class dead-letters immediately.
- Produces: `SessionHandler._mark_frozen_prefix_consumed` ceases to exist; `failure_class="no_safe_boundary"` disappears from the codebase.

- [ ] **Step 1: Write the two failing tests**

Append after the test added in Task 1:

```python
def test_frozen_prefix_never_advances_the_cursor(engine, tmp_path):
    """The defect: an idle transcript whose accepted bytes close nothing must NOT have its
    cursor advanced. Advancing it jumps the PROMPT, so when the response later closes its
    user turn is already behind the cursor and is never paired -- permanent, silent loss."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "partial.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)

    assert handler._state.get(rel) is None, \
        "an unclosed prefix must leave NO cursor behind -- nothing was ingested"
    assert handler.spool.pending_count() == 0, \
        "the job completes; re-admission is the producers' job, not a parked retry"
    assert not list((handler.spool.root / "failed").glob("*.json"))


def test_frozen_prefixes_do_not_accumulate_in_the_spool(engine, tmp_path):
    """Council R1 (Cursor HIGH, Codex HIGH): the rejected Revision 1 requeued these jobs
    forever, turning a bounded dead-letter into an unbounded hot queue -- 3239 jobs in
    production. complete() must leave the spool EMPTY no matter how many frozen files
    there are, and no matter how many times they are re-enqueued."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")

    frozen = []
    for i in range(12):
        p = proj / f"frozen{i}.jsonl"
        _partial_unterminated(p)
        _mark_idle(p)
        frozen.append(p)

    for _sweep in range(3):                      # three reconcile ticks over the same set
        for p in frozen:
            handler.spool.enqueue(p, boundary=p.stat().st_size, reason="reconcile")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
        assert handler.spool.pending_count() == 0, "frozen files must not pile up in pending/"
        assert not list((handler.spool.root / "failed").glob("*.json"))
        assert not any(p.name.endswith(".json")
                       for p in (handler.spool.root / "running").iterdir())
    assert not handler._state, "and not one cursor was written"


def test_no_state_entry_holds_only_end_offset(engine, tmp_path):
    """Production signature regression: an entry carrying ONLY end_offset means the cursor
    moved with nothing ingested. 49 such entries were found in production on 2026-08-09.
    No sequence of _run_job may ever produce one."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")

    unclosed = proj / "unclosed.jsonl"
    _partial_unterminated(unclosed)
    _mark_idle(unclosed)
    closed = proj / "closed.jsonl"
    _make_jsonl(closed, user_turns=6)
    _mark_idle(closed)

    for path in (unclosed, closed):
        handler.spool.enqueue(path, boundary=path.stat().st_size, reason="nudge")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)

    offenders = {rel: e for rel, e in handler._state.items() if set(e) == {"end_offset"}}
    assert not offenders, f"cursor advanced with nothing ingested: {offenders}"
```

- [ ] **Step 2: Run them — both must FAIL**

```bash
python -m pytest tests/test_background/test_session_watcher.py::test_frozen_prefix_never_advances_the_cursor tests/test_background/test_session_watcher.py::test_no_state_entry_holds_only_end_offset -v
```

Expected: `2 failed`. The first on `assert handler._state.get(rel) is None` — the entry exists, holding `{"end_offset": <size>}`. The second on the `offenders` assertion, naming `unclosed.jsonl`.

If either PASSES, **stop and report**. The defect is not reproducing and the rest of this plan rests on a false premise.

- [ ] **Step 3: Apply the fix in `_run_job`**

Replace lines 1475-1484 of `src/ormah/background/session_watcher.py` with:

```python
        # NO_PROGRESS: the closed delta at the safe boundary is empty. Nothing to commit,
        # so the job is DONE -- complete it and leave the cursor exactly where it is.
        #
        # There is deliberately no mechanism here to stop reconcile re-selecting a frozen
        # transcript. Five were tried (force-close, watermark, park token, prefix digest,
        # a forever-requeue) and none converged, because all were fail-CLOSED: getting one
        # wrong suppressed selection and lost data, so each needed exact file identity and
        # exact ordering, and each new guarantee created the next failure surface. The
        # requirement they served was never measured. Measured 2026-08-09: reconcile is
        # capped at session_watcher_reconcile_max_per_tick (50) every 5 minutes, and the
        # 50 largest live frozen transcripts (151 MB) parse in 0.50 s -- a 0.17% duty
        # cycle, independent of how many frozen files exist. Half a second every five
        # minutes does not justify a mechanism that can lose a conversation.
        #
        # Re-admission belongs to the producers, which already do it: the Observer's
        # on_modified -> spool.enqueue fires when the file grows, independent of reconcile,
        # so acceptance-only roots (`discover=False`) are covered too.
        #
        # ADR-0004, amendment 2026-07-28, the one rule of it that survives: suppressing
        # re-selection is NEVER expressed by advancing the cursor. Here it is not expressed
        # at all.
```

The branch is removed entirely — after this edit the `NO_PROGRESS` path reads only the
`shrink_pending` check followed by `self.spool.complete(job)`.

- [ ] **Step 4: Delete both dead methods**

Delete `_mark_frozen_prefix_consumed` (lines 1524-1545) and `_idle_with_unsafe_tail`
(lines 1501-1522) in full, including their docstrings. With the branch gone, the predicate
has no caller and no purpose — a predicate whose only action was deleted is dead code.

Verify:

```bash
grep -rn "_mark_frozen_prefix_consumed\|_idle_with_unsafe_tail" src/
```

Expected: no output.

- [ ] **Step 6: Run the two new tests — both must PASS**

```bash
python -m pytest tests/test_background/test_session_watcher.py::test_frozen_prefix_never_advances_the_cursor tests/test_background/test_session_watcher.py::test_no_state_entry_holds_only_end_offset -v
```

Expected: `2 passed`.

- [ ] **Step 7: Update the tests the fix invalidates**

See which break:

```bash
python -m pytest tests/test_background/test_session_watcher.py -v 2>&1 | grep -E "^(FAILED|ERROR)"
```

Exactly four are expected, with these resolutions:

**7a. `test_idle_file_with_no_safe_boundary_is_dead_lettered` (line 2666) — invert it.**

Rename to `test_idle_file_with_no_safe_boundary_is_retried_not_dead_lettered`. Replace its docstring with:

```python
    """T-N3 superseded 2026-08-09: an idle transcript whose bytes never reach a safe
    boundary simply completes with the cursor untouched. Dead-lettering it used to come
    paired with a silent cursor advance that jumped the prompt."""
```

Replace the four trailing assertions (currently lines 2684-2689) with:

```python
    assert not list((spool.root / "failed").glob("*.json")), \
        "nothing failed -- there was simply nothing to commit"
    assert spool.pending_count() == 0
    assert not any(p.name.endswith(".json") for p in (spool.root / "running").iterdir())
```

**7b. `test_frozen_prefix_advance_never_passes_the_accepted_boundary` (line 2692) — delete the whole test.** It pins the behaviour of a mechanism that no longer exists.

**7c. The monotonic guard calling `handler._mark_frozen_prefix_consumed(...)` directly (around lines 2830-2849) — delete the whole test.** Same reason.

**7d. `test_abandonment_with_unclosed_tail_composes_with_frozen_prefix` (line 3850) — retarget it.**

Rename to `test_abandonment_with_unclosed_tail_leaves_the_residual_tail_alone`. Replace the assertions from `assert entry["end_offset"] == size` onward with:

```python
        # ...and the residual unclosed tail is left for a later parse. It used to be
        # swallowed by a SECOND, silent loss layered on top of the recorded one.
        assert entry["end_offset"] == skipped[0]["end"]
        assert entry["end_offset"] < size
        assert not list((handler.spool.root / "failed").glob("*.json"))
```

Also update the stale comment at line 3847 to read:

```python
        # The EXPLICIT path leaves the durable record; the deleted frozen-prefix side
        # effect used to advance the cursor WITHOUT one.
```

**If any test fails that is NOT on this list, STOP and report it** rather than adjusting it. An unlisted failure means the change reaches further than the spec predicted.

- [ ] **Step 8: Full file, lint, and symbol retirement all green**

```bash
python -m pytest tests/test_background/test_session_watcher.py -q
ruff check src/ tests/
grep -rn "_mark_frozen_prefix_consumed\|_idle_with_unsafe_tail\|no_safe_boundary" src/ tests/
```

Expected: suite passes, ruff clean, and the final grep returns **nothing** — all three symbols fully retired.

- [ ] **Step 9: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(ingest): never advance the cursor over bytes that were never ingested

_mark_frozen_prefix_consumed advanced the durable cursor past an unclosed
prefix to stop reconcile re-selecting the file. That prefix begins with a
PROMPT: once the cursor jumped it, the response that later closed could
never be paired with it. 49 state entries in production carried the
signature of this loss (only end_offset, no hash/node_ids); measured, the
cursor stopped 1.5 KB to 8 KB short of the first close.

Suppression of re-selection is not replaced -- it is abandoned. Five
mechanisms were built to serve it and none converged, because all were
fail-closed: getting one wrong lost data, so each needed exact identity and
exact ordering, and each guarantee created the next failure surface. The
requirement itself was never measured. It is: reconcile is capped at 50 per
tick every 5 minutes, and the 50 largest live frozen transcripts (151 MB)
parse in 0.50s -- a 0.17%% duty cycle, independent of population. Producers
already re-admit on growth (Observer on_modified -> enqueue), which covers
acceptance-only roots that reconcile never sweeps.

Refs ADR-0004 amendment 2026-07-28. Revision 1 of this fix was rejected by
/council (Cursor and Codex convergent) for making the requeue unbounded."
```
