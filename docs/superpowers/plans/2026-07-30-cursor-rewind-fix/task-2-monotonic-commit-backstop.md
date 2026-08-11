# Task 2: Monotonic cursor invariant in `_commit_state` (backstop)

**Files:**
- Modify: `src/ormah/background/session_watcher.py:779-787` (`_commit_state`), `:858-859` (shrink flag), `:867-895` (fail-key offset), `:963-967`/`:1005-1007` (fail-counter keying), `:989`, `:1009`, `:1084` (call-sites)
- Test: `tests/test_background/test_session_watcher.py` (extend `TestAboveCapOrphanRecovery` from Task 1 + one unit test class for `_commit_state`)

**Interfaces:**
- Consumes: `_write_orphan_tail_jsonl(path, pairs, pad)` from Task 1; existing helpers `_mark_idle`, `_LLM_PATCH`, `_make_jsonl(path, user_turns)`, `_commit_state`, `_load_state`.
- Produces: `_commit_state(state, rel, entry, state_lock, watch_dir, *, allow_rewind: bool = False)` — the keyword is the seam the future ADR-0004 backfill will use.

**Background:** Audit of 2026-07-30: 3 of the 4 `_commit_state` call-sites can write a LOWER `end_offset` than the stored one — the rewind path zeroes `prev_offset` (line 879), so the extraction-failure path (line 1005) literally commits `end_offset=0`, and the quarantine path (line 980) and happy path (line 1073) compare against 0 instead of the stored cursor. Task 1 removes the loop's trigger; this task makes the state layer reject the whole class.

**Council R1 revisions incorporated:**
1. *(Codex, high-confidence)* The compare-and-clamp must live INSIDE the `state_lock` critical section — a stale read outside the lock lets two writers interleave 200-then-150 and persist the retreat anyway. The whole read-clamp-assign-save sequence below is one critical section. Cross-PROCESS writers remain unprotected (`threading.Lock` cannot span processes) — that is the pre-existing #150-class limitation, documented in the docstring, out of scope here.
2. *(Cursor)* The failure counter must be KEYED on the durable pre-rewind cursor, not on the transient zeroed `prev_offset` — otherwise a clamped fail-path entry carries `end_offset=orphan_start` with `extract_fail_offset=0`, an inconsistent pair. A `fail_key_offset` local fixes both the check and the write.
3. Constraints already in the plan, kept: the shrink path (`:858`) is the ONLY legitimate retreat (without the escape, `reconcile` `:1390` drops the file forever); the invariant clamps ONLY `end_offset`, never the entry (dropping it would lose `extract_fail_count` — council-pr I1).

- [ ] **Step 1: Write the failing test — extraction failure during rewind must not zero the cursor** (extend `TestAboveCapOrphanRecovery`)

```python
    def test_extract_failure_during_rewind_keeps_cursor(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "failrewind.jsonl"
        _write_orphan_tail_jsonl(jsonl, pairs=1, pad=10)   # small file: rewind proceeds
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        last_line_bytes = len((jsonl.read_text().splitlines()[-1] + "\n").encode())
        orphan_start = size - last_line_bytes
        rel = str(jsonl.relative_to(watch_dir))
        state = {rel: {"hash": "stale", "end_offset": orphan_start}}
        # Slice-specific failure: the LLM answers, but with unparseable content — the
        # deterministic class that goes through _record_extract_failure (not TRANSIENT-early).
        with patch(_LLM_PATCH, return_value="not-json"):
            result = _ingest_session(engine, jsonl, state, watch_dir,
                                     min_turns=1, flush_bytes=60000)
        assert result == IngestResult.TRANSIENT
        # Pre-fix this is 0: the rewind zeroed prev_offset and the fail path committed it.
        assert state[rel]["end_offset"] == orphan_start
        # Council R1 (Cursor): the counter is keyed on the durable pre-rewind cursor, so
        # the persisted pair is consistent — not extract_fail_offset=0 with a real cursor.
        assert state[rel]["extract_fail_offset"] == orphan_start
        assert state[rel]["extract_fail_count"] == 1
        # Council R3 (Codex): one failure cannot distinguish correct keying from a
        # counter that resets to 1 forever. A SECOND failed rewind must accumulate...
        with patch(_LLM_PATCH, return_value="not-json"):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=1, flush_bytes=60000) == IngestResult.TRANSIENT
        assert state[rel]["extract_fail_count"] == 2
        # ...and the THIRD reaches MAX_EXTRACT_FAILURES: the toxic slice is quarantined
        # (skipped_slices) and the cursor finally advances — the counter converges
        # instead of pinning the cursor forever.
        with patch(_LLM_PATCH, return_value="not-json"):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=1, flush_bytes=60000) == IngestResult.OK
        assert state[rel]["end_offset"] > orphan_start
        # council C2: the quarantine's loss record starts at the durable pre-rewind
        # cursor — NOT at 0, which would make the backfill replay ingested history.
        assert state[rel]["skipped_slices"][0]["start"] == orphan_start
        assert "extract_fail_count" not in state[rel]
```

- [ ] **Step 2: Run it — must FAIL on current code**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_background/test_session_watcher.py::TestAboveCapOrphanRecovery::test_extract_failure_during_rewind_keeps_cursor -v`
Expected: FAIL with `assert 0 == <orphan_start>`.

- [ ] **Step 3: Write the shrink guard test** (same class — must pass before AND after; it pins the escape hatch)

```python
    def test_file_shrink_still_rewinds_cursor(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "shrunk.jsonl"
        _make_jsonl(jsonl, user_turns=6)
        _mark_idle(jsonl)
        rel = str(jsonl.relative_to(watch_dir))
        state: dict = {}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.OK
        assert state[rel]["end_offset"] == jsonl.stat().st_size
        # The transcript is rewritten smaller (compaction/rewrite) — a legitimate retreat.
        _make_jsonl(jsonl, user_turns=2)
        _mark_idle(jsonl)
        new_size = jsonl.stat().st_size
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=1) == IngestResult.OK
        # A naive monotonic clamp would freeze the cursor above EOF and reconcile
        # (session_watcher.py:1390) would skip this file forever.
        assert state[rel]["end_offset"] == new_size

    def test_shrunk_file_with_no_safe_boundary_is_not_stranded(self, engine, tmp_path):
        # council C2 (codex): a shrunk rewrite with NO closed boundary used to return
        # NO_PROGRESS without any commit, leaving the durable cursor above EOF —
        # _idle_with_unsafe_tail sees size <= cursor and reconcile skips the file
        # forever. The shrink reset must persist even on a no-progress tick.
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "shrunkbad.jsonl"
        _make_jsonl(jsonl, user_turns=6)
        _mark_idle(jsonl)
        rel = str(jsonl.relative_to(watch_dir))
        state: dict = {}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.OK
        # Rewritten smaller with NO closed boundary: a single open user turn.
        jsonl.write_text(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "only an open turn"},
        }) + "\n")
        _mark_idle(jsonl)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)
        assert state[rel]["end_offset"] <= jsonl.stat().st_size
```

- [ ] **Step 4: Write the stale-writer unit test for `_commit_state`** (new class, same module — deterministic pin of the in-lock clamp; council R1, Codex)

```python
class TestCommitStateMonotonic:
    def test_stale_lower_commit_is_clamped(self, tmp_path):
        state: dict = {}
        lock = threading.Lock()
        _commit_state(state, "a.jsonl", {"end_offset": 200}, lock, tmp_path)
        # A writer that decided on stale data commits a LOWER offset afterwards —
        # the ordering Codex flagged. The clamp re-reads under the lock, so the
        # retreat is refused no matter when the stale decision was made.
        _commit_state(state, "a.jsonl", {"end_offset": 150, "extra": "kept"}, lock, tmp_path)
        assert state["a.jsonl"]["end_offset"] == 200
        assert state["a.jsonl"]["extra"] == "kept"      # only the offset is clamped
        assert _load_state(tmp_path)["a.jsonl"]["end_offset"] == 200

    def test_allow_rewind_accepts_lower_commit(self, tmp_path):
        state: dict = {}
        _commit_state(state, "a.jsonl", {"end_offset": 200}, None, tmp_path)
        _commit_state(state, "a.jsonl", {"end_offset": 50}, None, tmp_path,
                      allow_rewind=True)
        assert state["a.jsonl"]["end_offset"] == 50

    def test_save_failure_does_not_publish_in_memory(self, tmp_path, monkeypatch):
        # council R2 (codex): a failed persist must not leave the shared in-memory dict
        # claiming the new cursor — the retry would look already-consumed while disk
        # kept the old offset.
        state: dict = {}
        _commit_state(state, "a.jsonl", {"end_offset": 100}, None, tmp_path)

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("ormah.background.session_watcher._save_state", _boom)
        with pytest.raises(OSError):
            _commit_state(state, "a.jsonl", {"end_offset": 200}, None, tmp_path)
        assert state["a.jsonl"]["end_offset"] == 100   # not published on failed persist
        monkeypatch.undo()
        assert _load_state(tmp_path)["a.jsonl"]["end_offset"] == 100
```

- [ ] **Step 5: Run steps 3-4 tests — shrink and allow_rewind PASS already; stale-writer FAILS**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest "tests/test_background/test_session_watcher.py::TestAboveCapOrphanRecovery::test_file_shrink_still_rewinds_cursor" "tests/test_background/test_session_watcher.py::TestCommitStateMonotonic" -v`
Expected: shrink PASS; `test_stale_lower_commit_is_clamped` FAIL (`assert 150 == 200`); `test_allow_rewind_accepts_lower_commit` FAIL (TypeError: unexpected keyword `allow_rewind`).

- [ ] **Step 6: Implement the invariant.** Replace `_commit_state` (lines 779-787) with:

```python
def _commit_state(
    state: dict, rel: str, entry: dict, state_lock, watch_dir: Path,
    *, allow_rewind: bool = False,
) -> None:
    """Write one state entry and persist, honoring the optional cross-thread lock.

    Monotonic invariant (#154): ``end_offset`` never moves backward. The read-clamp-
    write sequence is ONE critical section — a stale read outside the lock would let
    two writers interleave a higher then a lower offset and persist the retreat anyway
    (council R1). Only the offset field is clamped — the rest of the entry
    (extract_fail_count, skipped_slices…) always persists, so a refused retreat can
    never lose the failure/quarantine trail (council-pr I1). Callers with a LEGITIMATE
    retreat (file shrank; deliberate backfill) opt in with ``allow_rewind=True``.
    Threat model: same-path concurrent writers do not exist in-process — _run_job
    serializes per path via _ingesting_guard — so the clamp is a backstop against
    LOGIC bugs (a code path that computes a lower offset), not a substitute for that
    ownership. Cross-PROCESS writers are NOT covered (threading.Lock is per-process)
    — the pre-existing #150-class spool limitation, unchanged here.
    """
    def _clamp_and_save() -> None:
        committed = entry
        if not allow_rewind:
            current = (state.get(rel) or {}).get("end_offset")
            new = entry.get("end_offset")
            if current is not None and new is not None and new < current:
                logger.warning(
                    "Session watcher refusing cursor retreat for %s: %d -> %d (clamped)",
                    rel, current, new,
                )
                committed = {**entry, "end_offset": current}
        # Persist FIRST, publish SECOND (council R2, codex): if _save_state raises, the
        # shared in-memory dict must not already claim the new cursor — a requeued job
        # would look consumed while disk kept the old offset, and a restart would undo
        # a supposedly durable commit.
        snapshot = dict(state)
        snapshot[rel] = committed
        _save_state(watch_dir, snapshot)
        state[rel] = committed

    if state_lock is not None:
        with state_lock:
            _clamp_and_save()
    else:
        _clamp_and_save()
```

- [ ] **Step 7: Wire the shrink escape and the fail-key offset.** At lines 858-859, replace:

```python
    if prev_offset > size:
        prev_offset = 0  # file shrank (compaction/rewrite) -> re-ingest whole
```

with:

```python
    allow_rewind = False
    if prev_offset > size:
        prev_offset = 0  # file shrank (compaction/rewrite) -> re-ingest whole
        # The ONLY legitimate cursor retreat: the old offset no longer exists in the
        # file. Without this opt-in the monotonic clamp would freeze the cursor above
        # EOF and reconcile (:1390) would drop the file from the sweep forever.
        allow_rewind = True
        # Persist the reset NOW (council C2): if this very tick finds no safe boundary
        # (malformed/unclosed rewrite), _ingest_session returns NO_PROGRESS without any
        # commit, the durable cursor stays above EOF, _idle_with_unsafe_tail sees
        # size <= cursor, and reconcile skips the file FOREVER. With the reset
        # persisted, a later grow/reconcile re-selects it normally.
        reset_entry = dict(existing or {})
        reset_entry.update({"hash": h, "end_offset": 0})
        _commit_state(state, rel, reset_entry, state_lock, watch_dir, allow_rewind=True)
        existing = state.get(rel)
```

In the rewind branch (right after `original_offset = prev_offset`, line ~877), add the durable failure key:

```python
            fail_key_offset = original_offset
```

and directly before the `try:` at line ~867 initialize it for the non-rewind case:

```python
    fail_key_offset = prev_offset
```

(after the parse the variable is re-pointed only inside the rewind branch; keep the initialization adjacent to the `allow_rewind` block so both flags read as one preamble). Then in `_record_extract_failure`, replace both uses of `prev_offset` as the counter key — the check (lines 963-967):

```python
        fail_count = (
            existing.get("extract_fail_count", 0) + 1
            if existing and existing.get("extract_fail_offset") == fail_key_offset
            else 1
        )
```

and — council C2 — the QUARANTINE branch's loss record must also use the durable key, or a rewind quarantine records `[0, payload_offset)` and the deferred backfill would replay already-ingested history: in the `skipped_slices.append({...})` block (lines ~971-977) replace `"start": prev_offset` with `"start": fail_key_offset`, and in the `logger.error` call (lines ~990-994) replace both `prev_offset` occurrences with `fail_key_offset`.

and the not-yet-capped write (lines 1002-1009):

```python
        fail_entry = dict(existing or {})
        fail_entry.update({
            "hash": h,
            "end_offset": prev_offset,  # clamped by _commit_state inside a rewind
            "extract_fail_offset": fail_key_offset,
            "extract_fail_count": fail_count,
        })
        _commit_state(state, rel, fail_entry, state_lock, watch_dir,
                      allow_rewind=allow_rewind)
```

Finally pass the flag at the two remaining mutating call-sites:
- line 989 (quarantine skip): `_commit_state(state, rel, skip_entry, state_lock, watch_dir, allow_rewind=allow_rewind)`
- line 1084 (happy path): `_commit_state(state, rel, entry, state_lock, watch_dir, allow_rewind=allow_rewind)`

(Task 1's abandonment commit keeps the default `allow_rewind=False` — it always advances. The fourth site, `_mark_frozen_prefix_consumed` line 1341, keeps its own `target <= cursor` guard and stays untouched.)

- [ ] **Step 8: Run the full class + unit class — all PASS**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest "tests/test_background/test_session_watcher.py::TestAboveCapOrphanRecovery" "tests/test_background/test_session_watcher.py::TestCommitStateMonotonic" -v`
Expected: 10 passed (Task 1: loop, small-file, run_job e2e, frozen-prefix composition; this task: fail-rewind, shrink, shrink-no-boundary, stale-writer, allow-rewind, save-failure).

- [ ] **Step 9: Run the whole watcher module**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_background/test_session_watcher.py -v`
Expected: all pass. If an existing test fails on the new clamp, STOP and inspect: it is either a test that (correctly) relied on shrink-retreat — fix by asserting through the new flag — or a REAL fifth retreat path the audit missed; report it in the PR body either way.

- [ ] **Step 10: Commit**

```bash
git add tests/test_background/test_session_watcher.py src/ormah/background/session_watcher.py
git commit -m "fix(session-watcher): enforce monotonic cursor in _commit_state with explicit rewind escape"
```
