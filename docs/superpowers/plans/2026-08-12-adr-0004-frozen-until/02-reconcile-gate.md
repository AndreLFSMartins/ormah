# Task 2: the "unchanged since the examination" predicate, and `reconcile` uses it

**Files:**
- Modify: `src/ormah/background/session_watcher.py` — new module-level function next to
  `_commit_state` (~`:823`), and the cheap-skip arm of `reconcile` (`:1622-1631`)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: `frozen_until` / `frozen_ino` / `frozen_mtime_ns` from Task 1.
- Produces: `_frozen_unchanged(entry: dict, st: os.stat_result) -> bool` — module-level, the
  single definition of "this file is still exactly the one the freeze examined". Task 3 calls
  the same function; there is deliberately no second copy of the predicate.

Without this task the cursor no longer drops the file from the sweep, so `reconcile` re-enqueues
a frozen transcript on every tick. Task 1 is not shippable alone.

**Council round 1 (both peers, critical/high):** the first draft of this gate was
`frozen_until >= st.st_size`. That is not "reopen on growth" — it also skips when the file
**shrank**, so a rotated transcript is suppressed forever and the Task 4 reset becomes
unreachable through either producer. The predicate below skips only on *identity*, so any
change at all — growth, shrink, replacement — re-selects.

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_session_watcher.py`, next to the other reconcile tests:

```python
def test_reconcile_skips_a_frozen_file_until_it_changes(engine, tmp_path):
    """The cursor no longer drops a frozen file from the sweep — the frozen identity does.
    Growth past the recorded ceiling re-opens it, with the parse resuming from the
    UNTOUCHED cursor rather than wherever a ratchet would have left it."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "frozen.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    size = jsonl.stat().st_size

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1        # first sweep: never seen -> enqueued
        _drain_all(handler)
        assert handler._state[rel]["frozen_until"] == size
        assert handler.reconcile() == 0, "an unchanged frozen file must be skipped"

        # the session resumes and closes its turn: the file grows past the ceiling
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user",
                "message": {"content": "a second prompt long enough to parse here"},
            }) + "\n")
        _mark_idle(jsonl)
        assert handler.reconcile() == 1, "growth must re-open the file"


def test_reconcile_reopens_a_frozen_file_that_was_rotated_smaller(engine, tmp_path):
    """Council round 1, critical (cursor + codex, verified): a ceiling-only gate
    (frozen_until >= size) also skips a file that SHRANK, so a rotated transcript is
    suppressed forever and no producer can ever arm the shrink reset. Any change to the
    file's identity must re-select it."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "rotated.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler.reconcile()
        _drain_all(handler)
        frozen = handler._state[rel]["frozen_until"]
        assert handler.reconcile() == 0

        # rotated: same path, a NEW smaller file with a complete conversation
        jsonl.unlink()
        _make_jsonl(jsonl, user_turns=6)
        assert jsonl.stat().st_size < frozen
        _mark_idle(jsonl)

        assert handler.reconcile() == 1, \
            "a rotated file must be re-selected, not hidden behind the old ceiling"
        _drain_all(handler)

    assert handler._state[rel].get("node_ids"), "the rotated file's content must be ingested"


def test_reconcile_reopens_a_frozen_file_replaced_at_the_same_size(engine, tmp_path):
    """A replacement of exactly the same byte count is invisible to a size comparison. The
    Observer lane catches it today because it consults no state at all, so a size-only gate
    would be a regression. Identity (inode/mtime) is what makes it visible."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "samesize.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler.reconcile()
        _drain_all(handler)
        original = jsonl.read_bytes()
        assert handler.reconcile() == 0

        # a NEW file at the same path with the SAME byte count
        replacement = proj / "tmp.jsonl"
        replacement.write_bytes(original)
        replacement.replace(jsonl)
        assert jsonl.stat().st_size == len(original)
        _mark_idle(jsonl)

        stale_ino = handler._state[rel]["frozen_ino"]
        assert stale_ino != jsonl.stat().st_ino, \
            "the replacement must carry a different inode — otherwise this fixture proves nothing"
        assert handler.reconcile() == 1, \
            "a same-size replacement is a different file and must be re-selected"

        # Council round 2, cursor, medium: stopping at the first re-open would ship a park
        # that never refreshes identity. Suppression must RE-ARM on the new file, or every
        # sweep re-selects and re-dead-letters it forever.
        _drain_all(handler)
        assert handler._state[rel]["frozen_ino"] == jsonl.stat().st_ino, \
            "the re-park must converge identity onto the replacement"
        assert handler.reconcile() == 0, "suppression must re-arm on the new identity"


def test_reconcile_selects_a_file_whose_cursor_sits_above_eof(engine, tmp_path):
    """Council round 2, codex, high. The frozen predicate's 'cursor above EOF' escape is
    unreachable while the arm above it skips on `>=`: a previously-ingested file that froze
    and was then rotated below its cursor is dropped from the sweep before the escape is
    ever evaluated, so reconcile can never arm the shrink gate. Only the Observer could —
    and reconcile exists precisely for when FSEvents are dropped.

    Pre-existing behaviour, not introduced by the frozen fact; it is repaired here because
    the fact's contract claims the escape works."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "shrunk.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler.reconcile()
        _drain_all(handler)
        cursor = handler._state[rel]["end_offset"]
        assert cursor > 0

        # rotated below the retained cursor, WITHOUT any Observer event
        jsonl.unlink()
        _make_jsonl(jsonl, user_turns=2)
        assert jsonl.stat().st_size < cursor
        _mark_idle(jsonl)

        assert handler.reconcile() == 1, \
            "a cursor above EOF means the file shrank — never 'fully consumed'"


def test_reconcile_still_selects_a_never_seen_file_with_only_a_frozen_fact(engine, tmp_path):
    """A file whose FIRST examination froze has an entry with no end_offset at all. The
    cheap-skip arm evaluates (entry.get('end_offset') or 0) >= size -> 0 >= size is false,
    so it must fall through to the frozen gate and be judged there."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "firstfreeze.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler.reconcile()
        _drain_all(handler)

    assert "end_offset" not in handler._state[rel], \
        "the freeze must not create a cursor for a file that was never ingested"
    assert handler._state[rel]["frozen_until"] == jsonl.stat().st_size
    assert handler.reconcile() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "frozen_file_until_it_changes or rotated_smaller or replaced_at_the_same_size or never_seen_file_with_only_a_frozen_fact or cursor_sits_above_eof" -v`

Expected: `cursor_sits_above_eof` FAILS on `reconcile() == 1` (today's `>=` arm skips it), and
the "unchanged" and "never seen" tests FAIL on the second `reconcile()` returning `1`
(nothing skips the file now that the cursor stays at 0). The rotation and same-size tests
currently PASS for the wrong reason — nothing skips anything yet. They are the regression net
for the gate you are about to add; if they are still green after Step 3, the gate is correct.

One assumption to check while you are here: `"end_offset" not in handler._state[rel]` rests on
the freeze being the *only* writer for a file that never ingested anything — which is what the
production census found (75 entries holding `end_offset` and nothing else). If that assertion
fails, print the entry: some other path is creating a cursor for a never-ingested file, and that
is a finding worth reporting before continuing, not a test to loosen.

- [ ] **Step 3: Add the predicate and use it in `reconcile`**

Add a module-level function after `_commit_state` (~`:823`):

```python
def _frozen_unchanged(entry: dict, st: os.stat_result) -> bool:
    """True when this file is still EXACTLY the one the freeze examined, so re-selecting it
    would reproduce the same dead-letter and nothing else.

    Identity, not a ceiling. Council round 1 killed the first draft (`frozen_until >= size`):
    it also skipped a file that shrank, so a rotated transcript was suppressed forever and the
    shrink reset became unreachable through either producer. Any change — growth, shrink,
    replacement at the same byte count — re-selects.

    Two explicit escapes:
    - ``shrink_pending``: the two-tick shrink gate is mid-confirmation; dropping the file from
      the sweep now would strand the marker, exactly as the arm above this one already guards.
    - a cursor above EOF: the file shrank relative to the stored cursor, which is the state the
      shrink gate exists to resolve. It must be selected so that gate can run.
    """
    if entry.get("shrink_pending"):
        return False
    if (entry.get("end_offset") or 0) > st.st_size:
        return False
    return (
        (entry.get("frozen_until") or 0) == st.st_size
        and entry.get("frozen_ino") == st.st_ino
        and entry.get("frozen_mtime_ns") == st.st_mtime_ns
    )
```

Then rewrite `reconcile`'s cheap-skip arm at `:1626-1631` and add the frozen arm after it. Note
the `>=` becoming `==`: a cursor **above** EOF means the file shrank, which is not "fully
consumed" and must reach the shrink gate (council round 2, codex, high).

```python
            elif (entry.get("end_offset") or 0) == st.st_size and not entry.get(
                "shrink_pending"
            ):
                # Fully consumed -> skip cheaply. EXCEPT a shrink_pending entry (task 4):
                # between tick 1 and tick 2 the durable cursor is still above EOF -- skipping
                # here would drop the file from the sweep and tick 2 would never arrive,
                # stranding the marker itself.
                #
                # `==`, never `>=`: a cursor ABOVE EOF means the file shrank, and skipping it
                # here made the shrink gate reachable only through the Observer -- so a
                # dropped FSEvent stranded the transcript, in the one component that exists to
                # recover dropped FSEvents.
                continue
            elif _frozen_unchanged(entry, st):
                # Frozen and byte-for-byte the file that was examined: re-selecting it would
                # reproduce the same dead-letter and nothing else (ADR-0004, 2026-08-12).
                # A SEPARATE arm on purpose: the one above carries the shrink_pending
                # exception, and folding two independent gates into one expression ties them
                # together.
                continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "frozen_file_until_it_changes or rotated_smaller or replaced_at_the_same_size or never_seen_file_with_only_a_frozen_fact or cursor_sits_above_eof" -v`

Expected: all five PASS.

- [ ] **Step 5: Run the whole watcher suite**

Run: `python -m pytest tests/test_background/test_session_watcher.py -v`

Expected: all PASS.

- [ ] **Step 6: Lint**

Run: `ruff check src/ tests/`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(watcher): reconcile skips a frozen transcript only while it is unchanged

The cursor used to drop a frozen file from the sweep as a side effect of
claiming its bytes. With the cursor left alone, _frozen_unchanged takes that
job — identity (size + inode + mtime), not a ceiling: a ceiling-only test also
skips a file that shrank, which would suppress a rotated transcript forever.

Refs ADR-0004"
```
