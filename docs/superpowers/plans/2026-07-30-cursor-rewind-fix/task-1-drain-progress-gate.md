# Task 1: Above-cap orphan recovery — explicit abandonment (never a cursor retreat)

**Files:**
- Modify: `src/ormah/background/session_watcher.py:891-895` (inside `_ingest_session`, orphan-recovery block)
- Test: `tests/test_background/test_session_watcher.py` (new class `TestAboveCapOrphanRecovery` + one module-level fixture helper)

**Interfaces:**
- Consumes: `_ingest_session(...) -> IngestResult` (existing); `parse_transcript(path, start_offset, max_bytes=None, stop_offset=None)` (existing); test helpers `_mark_idle(path)`, `_LLM_PATCH`, `_LLM_RESPONSE`, `_handler_with_spool(engine, watch_dir, spool_dir, **overrides)`, `_drain_all(handler)`, `_spool_idle(spool)` (all existing in the test module).
- Produces: helper `_write_orphan_tail_jsonl(path, pairs, pad)` — reused verbatim by Task 2's tests; state key `skipped_slices[].reason == "orphan_above_cap"` — the durable trail the deferred backfill will consume.

**Background:** `should_rewind` fires when a parse from the stored cursor sees a leading orphan AND makes no forward progress. The recovery re-parses from 0: an UNCAPPED probe decides whether anything is recoverable, but the CAPPED drain (`max_bytes=flush_bytes`) is what gets committed. When the file is bigger than `flush_bytes`, the drain's `safe_end_offset` lands BELOW the original cursor → the commit moves the cursor backward → later ticks climb back up → the orphan re-fires → permanent loop (measured: 5,342 re-ingests of one file).

**Design decision (council R1, both peers):** a bare `return IngestResult.NO_PROGRESS` here is NOT a stable "park". In production `_run_job` maps NO_PROGRESS + idle unsafe tail to `_mark_frozen_prefix_consumed` (`session_watcher.py:1286-1293`): the cursor would be bumped to EOF by SIDE EFFECT and the job dead-lettered, with no durable loss record in the state entry. So the gate must ABANDON EXPLICITLY: advance the cursor past the un-drainable tail itself, record the abandoned byte range in `skipped_slices` (the same durable-loss pattern the quarantine path uses), and return OK — deliberate, visible, testable at the worker level, zero LLM cost. Small files (drain reaches EOF ≥ cursor in one slice) keep the documented one-shot recovery of issue #154.

- [ ] **Step 1: Add the fixture helper to `tests/test_background/test_session_watcher.py`** (module level, next to `_make_jsonl`)

```python
def _write_orphan_tail_jsonl(path: Path, pairs: int = 6, pad: int = 600) -> None:
    """#154 fixture: `pairs` closed user/assistant pairs, one final closed pair, then a
    TRAILING assistant(end_turn) WITH text and no user after it. Parsed from any cursor
    sitting just before the trailing record it is a leading orphan with no forward
    progress (rewind fires); parsed from 0 the same record CLOSES (safe boundary reaches
    EOF), so the uncapped probe authorises recovery. With flush_bytes below the file size
    the capped drain then lands BELOW the original cursor — the #154 loop trigger."""
    filler = "x" * pad
    lines = []
    for i in range(pairs):
        lines.append({"type": "user",
                      "message": {"role": "user", "content": f"User {i} {filler}"}})
        lines.append({"type": "assistant",
                      "message": {"role": "assistant", "stop_reason": "end_turn",
                                  "content": [{"type": "text", "text": f"Answer {i} {filler}"}]}})
    lines.append({"type": "user", "message": {"role": "user", "content": f"Final ask {filler}"}})
    lines.append({"type": "assistant",
                  "message": {"role": "assistant", "stop_reason": "end_turn",
                              "content": [{"type": "text", "text": f"Final answer {filler}"}]}})
    lines.append({"type": "assistant",
                  "message": {"role": "assistant", "stop_reason": "end_turn",
                              "content": [{"type": "text", "text": f"Trailing orphan {filler}"}]}})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
```

- [ ] **Step 2: Write the failing loop test** (same file, new class; reuse the module's existing `engine` fixture exactly like the neighboring tests do)

```python
class TestAboveCapOrphanRecovery:
    """#154 above-flush_bytes class: recovery must never move the cursor backward, and
    an un-drainable tail is abandoned EXPLICITLY (skipped_slices), not looped over."""

    def test_cursor_never_retreats_and_abandons_explicitly(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "loop154.jsonl"
        _write_orphan_tail_jsonl(jsonl)          # ~10 KB total
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        rel = str(jsonl.relative_to(watch_dir))
        state: dict = {}
        offsets = []
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as llm:
            for _ in range(12):
                _ingest_session(engine, jsonl, state, watch_dir,
                                min_turns=5, flush_bytes=2000)
                offsets.append(state[rel]["end_offset"])
                _mark_idle(jsonl)                # ingest re-stats; keep it idle
        for prev, cur in zip(offsets, offsets[1:]):
            assert cur >= prev, f"cursor retreated: {offsets}"
        # The un-drainable tail is abandoned explicitly: cursor lands at EOF with a
        # durable loss record, and the LLM is never called again afterwards.
        assert offsets[-1] == size
        skipped = state[rel]["skipped_slices"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "orphan_above_cap"
        assert skipped[0]["end"] == size
        assert skipped[0]["start"] < size
        assert llm.call_count <= 8, f"re-extraction loop: {llm.call_count} LLM calls"
```

- [ ] **Step 3: Run it — must FAIL on current code**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_background/test_session_watcher.py::TestAboveCapOrphanRecovery::test_cursor_never_retreats_and_abandons_explicitly -v`
Expected: FAIL on the monotonicity assert (`cursor retreated: [...]` — offsets climb, then drop, cyclically). If it fails for any OTHER reason (fixture doesn't trigger the orphan), STOP and compare the fixture against `scratchpad/fixture_rewind_loop.jsonl` — do not weaken the assert.

- [ ] **Step 4: Write the small-file guard test** (same class — the documented #154 one-shot behavior must survive the fix)

```python
    def test_small_file_recovery_is_still_one_shot(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "oneshot.jsonl"
        _write_orphan_tail_jsonl(jsonl, pairs=1, pad=10)   # well below flush_bytes
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        last_line_bytes = len((jsonl.read_text().splitlines()[-1] + "\n").encode())
        orphan_start = size - last_line_bytes
        rel = str(jsonl.relative_to(watch_dir))
        # A legacy mid-response cursor parked right before the trailing orphan record.
        state = {rel: {"hash": "stale", "end_offset": orphan_start}}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            result = _ingest_session(engine, jsonl, state, watch_dir,
                                     min_turns=1, flush_bytes=60000)
        assert result == IngestResult.OK
        assert state[rel]["end_offset"] == size   # recovered to EOF in one slice, no retreat
        assert not state[rel].get("skipped_slices")   # nothing was abandoned
```

- [ ] **Step 5: Run the guard test — expected PASS already** (it documents behavior the fix must not break)

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_background/test_session_watcher.py::TestAboveCapOrphanRecovery -v`
Expected: `test_small_file_recovery_is_still_one_shot` PASS, `test_cursor_never_retreats_and_abandons_explicitly` FAIL.

- [ ] **Step 6: Implement the explicit abandonment.** In `src/ormah/background/session_watcher.py`. Three structural constraints from council R2/R3, all load-bearing:

- The abandonment target is the probe's **`safe_end_offset`** — a CLOSED-turn, line-aligned boundary that honours the `stop_offset` ceiling. Neither raw `min(size, boundary)` (can bisect a record written mid-flight) nor the probe's `end_offset` (`f.tell()` may overrun `stop_offset` on a straddling record and advances over malformed trailing JSON) is safe to persist as a cursor.
- The COMMIT must live OUTSIDE the broad parse `try:` (lines 867-898): its `except Exception` returns `NO_PROGRESS`, so an `OSError` from `_save_state` inside it would masquerade as a parse failure and route a valid transcript into frozen-prefix/dead-letter handling. Inside the `try` only DECIDE; commit after.
- Bytes past `safe_end_offset` stay unconsumed on purpose — they are the in-flight-forever class ADR-0003 already refuses to ingest.

First, immediately before the `try:` at line 867, initialize the decision carrier next to the `allow_rewind` preamble:

```python
    abandon_range: tuple[int, int] | None = None
```

Inside the `should_rewind` branch, right after the existing probe no-progress check (line ~890, before the capped drain re-parse), capture the probe's safe boundary:

```python
            # Abandonment target (council R2/R3): the probe's CLOSED-turn boundary.
            # Line-aligned by construction and never past the accepted stop_offset —
            # unlike raw min(size, boundary) (mid-write boundary can bisect a record)
            # or end_offset (f.tell() can overrun the ceiling on a straddling record).
            probe_safe_end = result.safe_end_offset
```

After the capped drain re-parse (existing lines 891-895), still inside the `should_rewind` branch, DECIDE only:

```python
            if result.safe_end_offset <= original_offset:
                # The capped drain cannot get PAST the original cursor in one slice.
                # Committing it would move the cursor backward; later ticks would climb
                # back to the orphan and rewind again — a permanent re-extraction loop
                # (#154 above-flush_bytes class, measured at 5,342 re-ingests of one
                # file). A bare NO_PROGRESS is no better: _run_job would treat the idle
                # unsafe tail as frozen and bump the cursor to EOF by SIDE EFFECT, with
                # no loss record (council R1). Abandon EXPLICITLY: decided here, but
                # COMMITTED below, outside this try — a storage error must surface as
                # itself, never as a fake parse failure -> NO_PROGRESS (council R3).
                abandon_range = (original_offset, probe_safe_end)
```

Then, between the `except` block (line ~898) and the `payload_offset = ...` line (~906), the commit:

```python
    if abandon_range is not None:
        abandon_from, abandon_to = abandon_range
        if abandon_to <= abandon_from:
            return IngestResult.NO_PROGRESS  # nothing safely closed past the cursor
        skip_entry = dict(existing or {})
        skipped_slices = list(skip_entry.get("skipped_slices", []))
        skipped_slices.append({
            "start": abandon_from,
            "end": abandon_to,
            "source_hash": h,
            "reason": "orphan_above_cap",
            "at": datetime.now(UTC).isoformat(),
        })
        skip_entry.update({
            "hash": h,
            "end_offset": abandon_to,
            "skipped_slices": skipped_slices,
        })
        skip_entry.pop("extract_fail_offset", None)
        skip_entry.pop("extract_fail_count", None)
        _commit_state(state, rel, skip_entry, state_lock, watch_dir)
        logger.error(
            "Session watcher ABANDONING above-cap orphan recovery for %s: "
            "cursor %d->%d, %d bytes recorded in skipped_slices "
            "(observable data loss)",
            rel, abandon_from, abandon_to, abandon_to - abandon_from,
        )
        return IngestResult.OK
```

Note the loop test's EOF assertion still holds: for the idle fixture the trailing orphan CLOSES from 0 (`end_turn`), so `probe_safe_end == size`. If the implementation lands with `probe_safe_end < size` on the fixture, the parser's safe boundary does not include the trailing closed orphan — STOP and re-derive the fixture against `parse_transcript` before weakening any assert.

- [ ] **Step 7: Run both tests — PASS**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_background/test_session_watcher.py::TestAboveCapOrphanRecovery -v`
Expected: 2 passed.

- [ ] **Step 8: Write the worker-level (end-to-end) test** — council R1: the unit seam hides the `_run_job` interaction; this test pins the behavior through the REAL drain path (spool → `_run_job` → `_ingest_session` → state), asserting the cursor was advanced by the EXPLICIT abandonment (with its `skipped_slices` record), not by the frozen-prefix side effect (which writes none).

```python
    def test_run_job_completes_abandoned_orphan_without_dead_letter(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "loop154.jsonl"
        _write_orphan_tail_jsonl(jsonl)
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        rel = str(jsonl.relative_to(watch_dir))
        handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool",
                                      min_turns=5, idle_threshold=30.0)
        handler.flush_bytes = 2000
        handler.spool.enqueue(jsonl, boundary=size, reason="drain")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
            _mark_idle(jsonl)
            _drain_all(handler)          # second pass drains any capped continuations
        assert _spool_idle(handler.spool), "job neither completed nor drained"
        entry = handler._state[rel]
        assert entry["end_offset"] == size
        # The EXPLICIT path leaves the durable record; the frozen-prefix side effect
        # (_mark_frozen_prefix_consumed) would have advanced the cursor WITHOUT it.
        assert entry["skipped_slices"][0]["reason"] == "orphan_above_cap"
```

Note: `_handler_with_spool` may not expose `flush_bytes` as a constructor override — check its `**overrides` handling and the `SessionHandler` signature; set it the way neighboring spool tests configure it. If `SessionHandler` takes `flush_bytes` in `__init__`, pass it through `overrides` instead of attribute assignment. Adjust ONLY the wiring, never the asserts.

Second test in the same step — the composition case (council confirmation round, codex): when `probe_safe_end < job.boundary` (an unclosed record remains past the closing orphan), the worker enqueues a continuation, which finds no safe progress and routes the residual tail through the PRE-EXISTING frozen-prefix path (`_idle_with_unsafe_tail` → `_mark_frozen_prefix_consumed` + dead-letter `no_safe_boundary`). This is the system's standard treatment for every unclosed tail (ADR-0004 slice 1; the durable record for THAT range is the spool dead-letter, and the mid-record frozen target is pre-existing slice-3 territory) — this plan neither introduces nor changes it, and this test PINS the composition so the abandonment's promise is stated accurately: `skipped_slices` covers `[original_offset, probe_safe_end)`; the tail past `probe_safe_end` follows the standard path.

```python
    def test_abandonment_with_unclosed_tail_composes_with_frozen_prefix(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "loop154tail.jsonl"
        _write_orphan_tail_jsonl(jsonl)
        # An UNCLOSED in-flight record after the closing orphan: probe_safe_end < size.
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "stop_reason": None,
                            "content": [{"type": "text", "text": "still streaming"}]},
            }) + "\n")
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        rel = str(jsonl.relative_to(watch_dir))
        handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool",
                                      min_turns=5, idle_threshold=30.0)
        handler.flush_bytes = 2000
        handler.spool.enqueue(jsonl, boundary=size, reason="drain")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
            _mark_idle(jsonl)
            _drain_all(handler)
        entry = handler._state[rel]
        # The abandonment recorded ITS range durably...
        skipped = entry["skipped_slices"]
        assert skipped[0]["reason"] == "orphan_above_cap"
        assert skipped[0]["end"] < size            # == probe_safe_end, before the unclosed tail
        # ...and the residual tail followed the standard frozen-prefix path (cursor at the
        # accepted boundary, job dead-lettered as no_safe_boundary — pre-existing behavior).
        assert entry["end_offset"] == size
        dead = [j for j in handler.spool.iter_dead_letter()] if hasattr(handler.spool, "iter_dead_letter") else None
        if dead is not None:
            assert any("no_safe_boundary" in str(j) for j in dead)
```

If `IngestSpool` exposes no dead-letter iterator, drop the last three lines and assert the dead-letter through whatever inspection the existing `no_safe_boundary` tests in this module use — mirror them; never assert less than cursor position + skipped_slices.

- [ ] **Step 9: Run the worker-level test — PASS**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_background/test_session_watcher.py::TestAboveCapOrphanRecovery::test_run_job_completes_abandoned_orphan_without_dead_letter -v`
Expected: PASS.

- [ ] **Step 10: Run the whole watcher module to catch regressions**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_background/test_session_watcher.py -v`
Expected: all pass (this module has no known pre-existing failures).

- [ ] **Step 11: Commit**

```bash
git add tests/test_background/test_session_watcher.py src/ormah/background/session_watcher.py
git commit -m "fix(session-watcher): abandon above-cap orphan recovery explicitly instead of retreating cursor (#154)"
```
