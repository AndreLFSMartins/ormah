# Task 2: Independent raw-byte ceiling + the rewind invariant

**Files:**
- Modify: `src/ormah/transcript/parser.py` (signature + second predicate + both call-site guards)
- Test: `tests/test_transcript/test_parser.py`

**Interfaces:**
- Consumes: Task 1's `parse_transcript(..., max_conversation_chars=None, ...)`, `_commit_turn`,
  `_would_overshoot`, `_projected_len`.
- Produces: `parse_transcript(path, start_offset=0, max_conversation_chars=None,
  max_raw_bytes=None, stop_offset=None)` and `result.capped` set by **either** budget.

**Why this exists.** A pure content budget leaves the raw span unbounded: measured, a 60000-char
slice spans ~1.4 MB at p50 and ~16 MB at p99. Resource safety is a different concern from recall and
needs its own bound. The default value is **not** decided here — Task 6 measures it. This task ships
the parameter defaulting to `None` (disabled), so nothing changes behaviourally until Task 6.

**The one rule you may not break.** The raw ceiling is a *budget*, not a ceiling in the `stop_offset`
sense: it keeps the same `_safe_len > 0` progress guard. That guard is the entire proof that a cap
cannot produce a rewind. `stop_offset` stays the only absolute limit.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transcript/test_parser.py`:

```python
def test_raw_ceiling_binds_independently_of_the_content_budget(tmp_path):
    """Tiny conversation, enormous raw span: the content budget is nowhere near full, so
    only the raw ceiling can close this slice."""
    from ormah.transcript.parser import parse_transcript

    path = tmp_path / "sparse.jsonl"
    _tool_heavy_jsonl(path, turns=20, text_chars=50, noise_chars=60000)

    unbounded = parse_transcript(path, max_conversation_chars=60000)
    bounded = parse_transcript(path, max_conversation_chars=60000, max_raw_bytes=200000)

    assert len(unbounded.safe_conversation) < 60000     # content budget never binds here
    assert bounded.capped is True
    assert bounded.safe_end_offset < unbounded.safe_end_offset
    assert bounded.safe_end_offset <= 200000            # start_offset == 0 here


def test_raw_ceiling_keeps_the_progress_guard(tmp_path):
    """A lone turn whose raw span exceeds the ceiling is committed anyway. Without this the
    drain would starve, AND `capped` would stop implying forward progress — which is what
    keeps should_rewind unreachable (see the next test)."""
    from ormah.transcript.parser import parse_transcript

    path = tmp_path / "one_big.jsonl"
    _tool_heavy_jsonl(path, turns=1, text_chars=50, noise_chars=100000)

    result = parse_transcript(path, max_conversation_chars=60000, max_raw_bytes=1000)

    assert result.safe_user_turn_count == 1
    assert result.safe_end_offset > 1000  # unavoidable for a lone oversized turn


def test_capped_always_implies_forward_progress(tmp_path):
    """ADR-0001 Amendment 3's open question, closed as a property.

    should_rewind == leading_orphan AND safe_end_offset <= start_offset. A cap only fires with
    _safe_len > 0, which implies the boundary already advanced. Therefore NO budget, on either
    axis, can produce a rewind. Verified on 1400 real slices during design; pinned here.
    """
    from ormah.transcript.parser import parse_transcript, should_rewind

    path = tmp_path / "walk.jsonl"
    _tool_heavy_jsonl(path, turns=25, text_chars=800, noise_chars=30000)

    for budget, ceiling in ((20000, None), (60000, 150000), (None, 100000)):
        offset = 0
        for _ in range(200):
            result = parse_transcript(
                path, start_offset=offset,
                max_conversation_chars=budget, max_raw_bytes=ceiling,
            )
            if result.capped:
                assert result.safe_end_offset > offset, (
                    f"capped without progress at offset={offset} "
                    f"(budget={budget}, ceiling={ceiling}) — should_rewind becomes reachable"
                )
                assert not should_rewind(result, offset)
            if result.safe_end_offset <= offset:
                break
            offset = result.safe_end_offset
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./.venv/bin/python -m pytest tests/test_transcript/test_parser.py -k "raw_ceiling or capped_always" -v
```

Expected: FAIL — `TypeError: parse_transcript() got an unexpected keyword argument 'max_raw_bytes'`.

- [ ] **Step 3: Add the parameter**

In `parse_transcript`'s signature, after `max_conversation_chars`:

```python
    max_raw_bytes: int | None = None,
```

Append to the docstring, right after the `max_conversation_chars` paragraph:

```
    *max_raw_bytes* is a SECOND, independent budget on the raw span consumed
    (``safe_end_offset - start_offset``). It exists for resource safety, not recall: a pure
    content budget leaves the raw span unbounded (measured p99 ~16 MB for a 60000-char slice).
    Whichever budget binds first closes the Batch. It keeps the same progress guard as the
    content budget and is therefore NOT a ceiling in the ``stop_offset`` sense — see below.
```

- [ ] **Step 4: Add the second predicate**

Immediately after `_would_overshoot` from Task 1, add:

```python
    def _would_exceed_raw(new_safe_end: int) -> bool:
        # Same progress guard as the content budget, deliberately: making this absolute would
        # let a cap occur with no forward progress, which is exactly the state should_rewind
        # (ADR-0003) triggers on. `stop_offset` is the only absolute limit in this parser.
        return (
            max_raw_bytes is not None
            and _safe_len > 0
            and (new_safe_end - start_offset) > max_raw_bytes
        )
```

- [ ] **Step 5: Wire it into the three commit sites**

Each site already tests the content budget. Add the raw test with `or`, keeping `_exceeds_ceiling`
first (it is absolute and must win).

`parser.py` Codex `task_complete` site:

```python
                    if _would_overshoot() or _would_exceed_raw(f.tell()):
                        _capped = True
                        break
```

`parser.py` new-user-turn site (the boundary is the start of this user line):

```python
                        if _would_overshoot() or _would_exceed_raw(pos_before):
                            _capped = True
                            break
```

`parser.py` terminal-assistant site:

```python
                    if _assistant_is_terminal(entry) and (
                        _would_overshoot(pending) or _would_exceed_raw(f.tell())
                    ):
                        _capped = True
                        break
```

- [ ] **Step 6: Run the full transcript suite**

```bash
./.venv/bin/python -m pytest tests/test_transcript/ -v
```

Expected: PASS. Again: the orphan/rewind tests must pass **unedited**.

- [ ] **Step 7: Run the session-watcher suite to catch collateral damage**

```bash
./.venv/bin/python -m pytest tests/test_background/test_session_watcher.py -q
```

Expected: PASS — this suite has 27 `flush_bytes` references but they reach the parser through
`_ingest_session`, which Task 3 rewires. Failures here now mean Task 1/2 changed behaviour beyond the
budget axis.

- [ ] **Step 8: Lint and commit**

```bash
ruff check src/ tests/
git add src/ormah/transcript/parser.py tests/test_transcript/test_parser.py
git commit -m "feat(parser): add an independent raw-byte budget alongside the content budget

Two limits, whichever binds first. The raw budget bounds resource cost (read/parse work),
which is a different concern from recall: a 60000-char slice spans ~1.4 MB p50 and ~16 MB p99
of raw transcript. Defaults to None here; Task 6 sets the value from measurement.

Both budgets keep the _safe_len > 0 progress guard, so a cap still implies an advanced safe
boundary and should_rewind (ADR-0003) stays unreachable from a cap. Pinned as a property test."
```
