# Task 1: the suppression fact replaces the cursor advance

**Files:**
- Modify: `src/ormah/background/session_watcher.py:1502` (call site), `:1553-1575` (the method)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Produces: `SessionHandler._mark_frozen_prefix_parked(self, path: Path, rel: str, boundary: int | None = None) -> None`
  — replaces `_mark_frozen_prefix_consumed`, same signature. Writes three state keys and never
  writes `end_offset`: `frozen_until: int`, `frozen_ino: int`, `frozen_mtime_ns: int`. Tasks 2,
  3 and 4 read them.

The two identity keys exist because a size ceiling alone cannot say "unchanged". Council round 1
(cursor + codex, both critical/high, verified independently): a rotated or replaced transcript
whose new size is **at or below** the ceiling would be suppressed forever, and a same-size
replacement is invisible to a size-only comparison. Today the Observer lane consults no state at
all, so it catches both cases on the FSEvent — a size-only gate would be a regression there.
`st_ino` and `st_mtime_ns` come from the **same** `stat()` that computes `target`, never a second
one.

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
        self, path: Path, rel: str, boundary: int | None = None,
        *, examined: os.stat_result,
    ) -> None:
        """Record that this file closed nothing up to ``boundary`` — WITHOUT moving the
        cursor (ADR-0004, 2026-08-12).

        The predecessor (`_mark_frozen_prefix_consumed`) expressed "stop re-selecting this"
        by advancing ``end_offset``, which claims bytes nothing ingested. Measured on the
        live Beta: 75 state entries whose cursor had been advanced with nothing ingested,
        68 transcripts still on disk, and a whole-file parse closes recoverable content in
        14 of them. Suppression of selection is never expressed by moving the cursor.

        ``frozen_until`` means: the last examination of this file, up to byte N, closed
        nothing; do not re-select it while the file is still exactly the one examined. It is
        not a progress offset. Monotonic — a stale or out-of-order job carrying a LOWER
        boundary must not lower the ceiling, which would re-open the ratchet this method
        exists to stop. NEVER past the accepted ``boundary`` (council-pr F1): bytes above it
        were never accepted, so a later, higher nudge must still be able to examine them.

        ``frozen_ino``/``frozen_mtime_ns`` describe the file the examination actually read. A
        ceiling alone cannot express "unchanged": a rotation to a size at or below it, or a
        same-size replacement, would otherwise be suppressed forever (council round 1,
        both peers). Identity is what the producers compare; the ceiling only bounds it.

        ``examined`` is the stat ``_idle_with_unsafe_tail`` used. Re-stating here and
        refusing on any difference closes a TOCTOU that would be worse than the one this
        change removes (council round 2, codex, high): a rotation landing between the
        examination and this call would record the REPLACEMENT's identity, and both
        producers would then classify a file nobody has ever parsed as frozen-and-unchanged.
        Writing no fact is always safe — the file is simply re-selected.

        The monotonic rule applies to the CEILING only. Identity always converges (council
        round 2, cursor, high): after a same-size replacement the producers correctly
        re-open, the drain freezes again at the same ``target``, and an early return that
        skipped the identity write would leave the stale identity in place forever — every
        sweep re-selecting, re-dead-lettering, growing ``failed/`` without bound.

        And monotonicity holds only WITHIN one identity (council round 3, both peers, the
        single finding of that round). A ceiling belonging to a different file is not a
        ratchet guard, it is a lie: file A frozen at 1000, replaced by an unparseable B of
        size 500, would keep 1000, and ``frozen_until == st_size`` could never be true again.
        Guarding on identity also makes ``ceiling <= st.st_size`` provable rather than
        defensive: same inode and same mtime means the same bytes, so the stored ceiling was
        computed from this very size.
        """
        try:
            st = path.stat()
        except OSError:
            return
        if (st.st_ino, st.st_mtime_ns, st.st_size) != (
            examined.st_ino, examined.st_mtime_ns, examined.st_size
        ):
            return  # changed under the examination -- never park a file nobody parsed
        target = min(boundary, st.st_size) if boundary is not None else st.st_size
        entry = dict(self._state.get(rel, {}))
        same_file = (
            entry.get("frozen_ino") == st.st_ino
            and entry.get("frozen_mtime_ns") == st.st_mtime_ns
        )
        # Never lower the ceiling for the SAME file (an out-of-order job would re-open the
        # ratchet); always take the new one for a different file.
        ceiling = max(target, entry.get("frozen_until") or 0) if same_file else target
        if (
            entry.get("frozen_until") == ceiling
            and entry.get("frozen_ino") == st.st_ino
            and entry.get("frozen_mtime_ns") == st.st_mtime_ns
        ):
            return  # already recorded, identically -- no write
        entry["frozen_until"] = ceiling
        entry["frozen_ino"] = st.st_ino
        entry["frozen_mtime_ns"] = st.st_mtime_ns
        _commit_state(self._state, rel, entry, self._state_lock, self.watch_dir)
```

Then make `_idle_with_unsafe_tail` hand back the stat it examined, so the park can verify the
file did not change underneath it. Change its signature and its final return (`:1528-1551`):

```python
    def _idle_with_unsafe_tail(
        self, path: Path, rel: str, boundary: int | None = None
    ) -> os.stat_result | None:
        """The stat of an idle file that has bytes past the cursor yet closes nothing there
        (a single unterminated turn), or None. Returning the STAT rather than a bool is what
        lets the caller prove the parked file is the file that was parsed — see
        _mark_frozen_prefix_parked (council round 2, codex).

        Non-idle files keep being retried (re-enqueued as they grow); an unparseable/empty
        delta is the file's own fault.

        The parse honours the accepted ``boundary`` as a ``stop_offset`` ceiling (council-pr
        F1): a still-growing session can have bytes past the boundary that the nudge never
        accepted, and examining them here would decide "frozen" on unaccepted content."""
        try:
            st = path.stat()
        except OSError:
            return None
        if time.time() - st.st_mtime <= self.idle_threshold:
            return None
        cursor = self._state.get(rel, {}).get("end_offset") or 0
        if st.st_size <= cursor:
            return None
        try:
            parsed = parse_transcript(path, start_offset=cursor, stop_offset=boundary)
        except Exception:
            return None
        return st if parsed.safe_end_offset <= cursor else None
```

Then update the single call site at `:1495-1503`:

```python
        # NO_PROGRESS: the closed delta at the safe boundary is empty.
        examined = self._idle_with_unsafe_tail(path, rel, job.boundary)
        if examined is not None:
            self._mark_frozen_prefix_parked(path, rel, job.boundary, examined=examined)
            self.spool.requeue(job, failure_class="no_safe_boundary")
            return
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

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=3000, examined=jsonl.stat())
    assert handler._state[rel]["frozen_until"] == 3000
    assert handler._state[rel]["end_offset"] == 4000, "the park must not touch the cursor"

    handler._mark_frozen_prefix_parked(     # stale, LOWER boundary
        jsonl, rel, boundary=1000, examined=jsonl.stat())
    assert handler._state[rel]["frozen_until"] == 3000, (
        "a boundary below the current ceiling must never lower it (re-opens the ratchet)"
    )
    assert _load_state(watch_dir).get(rel, {}).get("frozen_until") == 3000, (
        "the stale boundary must not be persisted to disk either"
    )
    assert _load_state(watch_dir).get(rel, {}).get("end_offset") == 4000
```

- [ ] **Step 6b: Add the two council round-2 regression tests**

```python
def test_park_refuses_a_file_that_changed_under_the_examination(engine, tmp_path):
    """Council round 2, codex, high. The park stats the file AFTER the examination. A
    rotation landing in between would record the REPLACEMENT's identity, and both producers
    would then treat a file nobody has ever parsed as frozen-and-unchanged. Writing no fact
    is always safe: the file is simply re-selected."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "raced.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    examined = jsonl.stat()

    # the path is replaced between the examination and the park
    jsonl.unlink()
    _make_jsonl(jsonl, user_turns=2)

    handler._mark_frozen_prefix_parked(
        jsonl, rel, boundary=jsonl.stat().st_size, examined=examined)
    assert "frozen_until" not in handler._state.get(rel, {}), \
        "a file that changed under the examination must never be parked"


def test_park_converges_identity_when_the_ceiling_does_not_rise(engine, tmp_path):
    """Council round 2, cursor, high. After a same-size replacement the producers correctly
    re-open (identity differs). The re-park lands on the SAME ceiling; if it returned early
    the stale identity would stay forever and every sweep would re-select and re-dead-letter
    the file — an unbounded failed/, the failure mode ADR-0004 exists to avoid."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "samesize.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    size = jsonl.stat().st_size
    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=size, examined=jsonl.stat())
    first_ino = handler._state[rel]["frozen_ino"]

    # a NEW file at the same path with the SAME byte count
    original = jsonl.read_bytes()
    replacement = proj / "tmp.jsonl"
    replacement.write_bytes(original)
    replacement.replace(jsonl)
    _mark_idle(jsonl)
    assert jsonl.stat().st_size == size

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=size, examined=jsonl.stat())
    entry = handler._state[rel]
    assert entry["frozen_until"] == size, "the ceiling must not move"
    assert entry["frozen_ino"] != first_ino, \
        "identity must converge even when the ceiling does not rise"
    assert entry["frozen_ino"] == jsonl.stat().st_ino


def test_park_ceiling_is_monotonic_only_within_one_identity(engine, tmp_path):
    """Council round 3, both peers, the only finding of that round. A ceiling belonging to
    a different file is not a ratchet guard, it is a lie: file A frozen at a large size,
    replaced by a SMALLER file that is also unparseable, would keep A's ceiling, and
    `frozen_until == st_size` could never be true again — every sweep re-selecting and
    re-dead-lettering, an unbounded failed/."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "shrinking.jsonl"
    proj_big = "x" * 4000
    jsonl.write_text(
        json.dumps({"type": "user", "message": {"content": f"a long prompt {proj_big}"}})
        + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": f"an answer that never closed {proj_big}"}]}})
        + "\n"
    )
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    big = jsonl.stat().st_size
    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=big, examined=jsonl.stat())
    assert handler._state[rel]["frozen_until"] == big

    # replaced by a SMALLER file that is also unparseable
    jsonl.unlink()
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    small = jsonl.stat().st_size
    assert small < big

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=small, examined=jsonl.stat())
    assert handler._state[rel]["frozen_until"] == small, (
        "a ceiling from a different file must be replaced, not maxed — otherwise the "
        "predicate can never re-arm and the file re-selects forever"
    )
    assert _frozen_unchanged(handler._state[rel], jsonl.stat()), \
        "suppression must re-arm on the new file"
```

`_frozen_unchanged` arrives in Task 2; import it in the test module alongside the other
`session_watcher` helpers when you write Task 2, or move this single assertion there.

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "park_refuses_a_file_that_changed or park_converges_identity" -v`

Expected: both PASS against the implementation from Step 3.

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
