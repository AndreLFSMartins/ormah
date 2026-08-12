# Task 1: the suppression fact replaces the cursor advance

**Files:**
- Modify: `src/ormah/background/session_watcher.py:1502` (call site), `:1553-1575` (the method)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Produces: `SessionHandler._mark_frozen_prefix_parked(self, path: Path, rel: str, boundary: int | None = None) -> None`
  — replaces `_mark_frozen_prefix_consumed`, same signature. Writes the state key
  `frozen_until: int` and never writes `end_offset`. Tasks 2, 3 and 4 read that key.

---

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_session_watcher.py`, next to the other frozen-prefix
tests (after `test_frozen_prefix_advance_never_passes_the_accepted_boundary`):

```python
def test_frozen_prefix_does_not_consume_bytes_the_next_job_can_ingest(engine, tmp_path):
    """ADR-0004 2026-08-12 — the ratchet. A job whose accepted boundary cuts the first
    assistant record in half closes nothing, so the frozen-prefix path fires. It must NOT
    advance the cursor: a second job at the file's real EOF has to ingest the WHOLE
    transcript. With the cursor advanced (the pre-fix behaviour) the second job resumes
    mid-record and the content is unreachable — that happened 24 times in a row on one
    production transcript, boundary climbing 98,985 -> 1,435,339, nothing ever ingested."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "ratchet.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    size = jsonl.stat().st_size

    # A boundary strictly INSIDE the first assistant record: the parser reads that line
    # (its start is below the ceiling) and _exceeds_ceiling refuses it at commit, so
    # safe_end_offset == start_offset == 0 and _idle_with_unsafe_tail is True.
    first_line = jsonl.read_bytes().split(b"\n")[0]
    boundary = len(first_line) + 1 + 10
    assert boundary < size

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        spool.enqueue(jsonl, boundary=boundary, reason="observer", force_flush=False)
        _drain_all(handler)

        entry = handler._state.get(rel, {})
        assert entry.get("frozen_until") == boundary, \
            "the freeze must be recorded as a suppression fact"
        assert (entry.get("end_offset") or 0) == 0, \
            "the freeze must NOT move the cursor over bytes nothing ingested"

        spool.enqueue(jsonl, boundary=size, reason="reconcile", force_flush=False)
        _drain_all(handler)

    entry = handler._state[rel]
    assert entry["end_offset"] == size, \
        "the second job, at the real EOF, must ingest the whole transcript"
    assert entry.get("node_ids"), "the content must have reached the store"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_background/test_session_watcher.py::test_frozen_prefix_does_not_consume_bytes_the_next_job_can_ingest -v`

Expected: FAIL on the first assertion — `entry.get("frozen_until")` is `None` because today the
freeze writes `end_offset` instead.

If it fails on `assert boundary < size` or the freeze never fires (no `frozen_until` **and**
`end_offset == 0`), the fixture is wrong, not the code: `boundary` must land strictly inside the
second line. Print `first_line` and the byte offsets and adjust before continuing.

- [ ] **Step 3: Rename the method and write the fact instead of the cursor**

In `src/ormah/background/session_watcher.py`, replace the whole method at `:1553`:

```python
    def _mark_frozen_prefix_parked(
        self, path: Path, rel: str, boundary: int | None = None
    ) -> None:
        """Record that this file closed nothing up to ``boundary`` — WITHOUT moving the
        cursor (ADR-0004, 2026-08-12).

        The predecessor (`_mark_frozen_prefix_consumed`) expressed "stop re-selecting this"
        by advancing ``end_offset``, which claims bytes nothing ingested. Measured on the
        live Beta: 75 state entries whose cursor had been advanced with nothing ingested,
        68 transcripts still on disk, and a whole-file parse closes recoverable content in
        14 of them. Suppression of selection is never expressed by moving the cursor.

        ``frozen_until`` means: the last examination of this file, up to byte N, closed
        nothing; do not re-select it until it grows past N. It is not a progress offset.
        Monotonic — a stale or out-of-order job carrying a LOWER boundary must not lower the
        ceiling, which would re-open the ratchet this method exists to stop. NEVER past the
        accepted ``boundary`` (council-pr F1): bytes above it were never accepted, so a
        later, higher nudge must still be able to examine them.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return
        target = min(boundary, size) if boundary is not None else size
        entry = dict(self._state.get(rel, {}))
        if target <= (entry.get("frozen_until") or 0):
            return  # stale/out-of-order boundary -- monotonic: never lower the ceiling
        entry["frozen_until"] = target
        _commit_state(self._state, rel, entry, self._state_lock, self.watch_dir)
```

Then update the single call site at `:1502`:

```python
            self._mark_frozen_prefix_parked(path, rel, job.boundary)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python -m pytest tests/test_background/test_session_watcher.py::test_frozen_prefix_does_not_consume_bytes_the_next_job_can_ingest -v`

Expected: PASS.

- [ ] **Step 5: Run the whole watcher suite and read what moved**

Run: `python -m pytest tests/test_background/test_session_watcher.py -v`

Expected: exactly one failure —
`TestAboveCapOrphanRecovery::test_abandonment_with_unclosed_tail_composes_with_frozen_prefix`,
on `assert entry["end_offset"] == size`.

Two other tests keep passing but have gone **vacuous** — their assertions are now trivially
true because the cursor is never touched. They are rewritten in Step 6 so the invariant they
guard follows the field that now carries it. If any test fails that is not the one named above,
stop and report it before changing anything.

- [ ] **Step 6: Rewrite the three affected tests**

In `test_abandonment_with_unclosed_tail_composes_with_frozen_prefix` (~`:3850`), replace:

```python
        assert entry["end_offset"] == size
```

with:

```python
        # The residual unclosed tail is now PARKED, not consumed: the cursor stays at the
        # abandoned range's end and the suppression fact carries the ceiling.
        assert entry["end_offset"] == skipped[0]["end"]
        assert entry["frozen_until"] == size
```

In `test_frozen_prefix_advance_never_passes_the_accepted_boundary` (~`:2692`), replace the
docstring's first line and the two closing assertions:

```python
    """council-pr F1, carried onto the suppression fact: a nudge accepted boundary B; the
    live file then grew to S>B, still an unterminated single turn, and went idle. The
    freeze must record B, NEVER raw EOF S -- bytes [B,S] were never accepted, so a later
    nudge at S must still be able to re-examine them."""
```

```python
    entry = _load_state(watch_dir).get(rel, {})
    assert (entry.get("end_offset") or 0) == 0, "the freeze must not move the cursor at all"
    assert entry.get("frozen_until") == boundary, (
        f"the freeze recorded {entry.get('frozen_until')} (S={size}); it must never pass "
        f"the accepted boundary B={boundary}, or bytes [B,S] are suppressed forever"
    )
    # [B,S] was not permanently consumed: a second nudge at S can still claim it for work.
    spool.enqueue(jsonl, boundary=size, reason="nudge")
    assert spool.claim_next() is not None, "the second nudge at S must be claimable"
```

Rename `test_frozen_prefix_advance_never_moves_the_cursor_backward` (~`:2830`) to
`test_frozen_prefix_park_is_monotonic` and replace its body after the `spool`/`handler` setup:

```python
    # cursor already well past, persisted to BOTH memory and disk
    _commit_state(handler._state, rel, {"end_offset": 4000}, handler._state_lock, watch_dir)

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=3000)
    assert handler._state[rel]["frozen_until"] == 3000
    assert handler._state[rel]["end_offset"] == 4000, "the park must not touch the cursor"

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=1000)   # stale, LOWER boundary
    assert handler._state[rel]["frozen_until"] == 3000, (
        "a boundary below the current ceiling must never lower it (re-opens the ratchet)"
    )
    assert _load_state(watch_dir).get(rel, {}).get("frozen_until") == 3000, (
        "the stale boundary must not be persisted to disk either"
    )
    assert _load_state(watch_dir).get(rel, {}).get("end_offset") == 4000
```

- [ ] **Step 7: Run the whole watcher suite again**

Run: `python -m pytest tests/test_background/test_session_watcher.py -v`

Expected: all PASS.

- [ ] **Step 8: Lint**

Run: `ruff check src/ tests/`

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(watcher): park a frozen prefix with a fact, never by moving the cursor

_mark_frozen_prefix_consumed advanced end_offset to mean 'stop re-selecting
this', which claims bytes nothing ingested. Renamed _mark_frozen_prefix_parked
and it now writes frozen_until, monotonic, leaving the cursor untouched.

Measured on the live Beta 2026-08-12: 75 state entries with the cursor advanced
and nothing ingested; one transcript ratcheted through 24 dead-letters, boundary
climbing 98,985 -> 1,435,339, never ingested, while a whole-file parse closes
1,434,322 of its 1,435,339 bytes.

Refs ADR-0004"
```
