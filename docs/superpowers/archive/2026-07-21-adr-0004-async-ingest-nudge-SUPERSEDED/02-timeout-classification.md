# Task 2: `EXTRACT_ERR_TIMEOUT` — timeout counts toward the per-slice cap

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (constants ~L54-61; `_extract_memories_llm` L2842-2886)
- Modify: `src/ormah/background/session_watcher.py:942-954` (classification)
- Test: `tests/test_background/test_session_watcher.py` (next to `test_provider_wide_call_failure_never_skips_slice` ~L408)

**Interfaces:**
- Consumes: `LlmTimeoutError` from Task 1 (`ormah.background.llm_errors`).
- Produces: module constant `EXTRACT_ERR_TIMEOUT` in `memory_engine.py`, exported alongside
  `EXTRACT_ERR_NO_PROVIDER` / `EXTRACT_ERR_CALL_FAILED` (session_watcher already imports
  those two — extend that import). Returned by `engine.ingest_conversation` as an error
  string, like the other two.

**Semantics (H1 rule + council R1 health gate + R4 shrink):** a timeout MAY be evidence about the
slice — but provider congestion times out every slice, and quarantining during an outage
is exactly the H1 mass-loss scenario. So a timeout counts toward `MAX_EXTRACT_FAILURES`
ONLY with provider-health evidence: **some slice extracted successfully since THIS slice's
previous timeout** (proves the provider was healthy while this slice kept failing).
Without that evidence → uncapped TRANSIENT, like `EXTRACT_ERR_CALL_FAILED`. Mechanism:
- module-level monotonic success marker `_LAST_EXTRACT_OK: float` (time.monotonic()),
  set at the end of every successful `_ingest_session` extraction;
- per-slice state field `extract_fail_at` (monotonic timestamp of this slice's last
  counted-or-not timeout), persisted next to `extract_fail_offset`/`extract_fail_count`;
- on `EXTRACT_ERR_TIMEOUT`: count iff `_LAST_EXTRACT_OK > entry["extract_fail_at"]`;
  always refresh `extract_fail_at`. First timeout of a slice never counts (no bracket yet).
- **Atomicity (council R2):** the decision AND the state write happen in ONE locked
  mutation — read the entry, decide, then a single `_commit_state` that writes the new
  `extract_fail_at` together with the (possibly incremented) `extract_fail_count`. Never
  two commits (a helper re-reading a stale snapshot would restore the old timestamp and
  let ONE success authorize unlimited counts). Regression: one success authorizes AT MOST
  one subsequent timeout count; further timeouts without a new success stay TRANSIENT.
- `extract_fail_at` is `time.monotonic()` and is NOT comparable across restarts: after a
  reboot the marker restarts too, so stale entries fail the bracket test and fall back to
  TRANSIENT — slower quarantine, never lossier (documented fail-safe, council R2).
- `LlmCancelledError` (Task 7 shutdown path) is caught in the engine right next to
  `LlmTimeoutError` and returns `EXTRACT_ERR_CALL_FAILED` — a cancel says nothing about
  the slice, so it must stay uncapped TRANSIENT, never `EXTRACT_ERR_TIMEOUT`.
- **Shrink before quarantine (council R4, decisive).** Health evidence proves the provider
  works; it does NOT prove the slice is corrupt — a big-but-valid slice can time out while
  smaller ones succeed, and quarantining it drops real conversation. So a bracketed timeout
  first HALVES the slice: persist `extract_shrink_level` (int) on the entry and parse with
  `max_bytes = max(floor, flush_bytes >> level)` where
  **`floor = min(MIN_SLICE_BYTES, flush_bytes)`** (`_ingest_session` L776 already takes
  `max_bytes`). Deriving the floor with `min` matters (council R5): a configured
  `flush_bytes=1000` must never be RAISED to a 4000 constant — that would break the
  `flush_bytes <= ingest_max_content_chars` invariant and the existing tests that pass
  300-byte caps. Only when the level is already at that floor does a further bracketed
  timeout count toward `MAX_EXTRACT_FAILURES`.
  A success at any level clears both the level and the counters.
Net effect: a slow-but-valid slice shrinks until it fits; only a slice that cannot be
extracted even at the floor — while the provider demonstrably works — is ever quarantined,
and that quarantine is already recorded replayably in `skipped_slices` (start/end/hash,
L871-877) with an ERROR log.

- [ ] **Step 1: Write the failing tests**

All bodies below are executable against the EXISTING fixtures in
`tests/test_background/test_session_watcher.py` (verified 2026-07-21): `_make_jsonl` (L51),
`_mark_idle` (L68), `_LLM_PATCH = "ormah.background.llm_client.ingest_llm_generate"` (L31),
`_LLM_RESPONSE` (L41), the `engine` fixture, and the
`test_toxic_slice_skipped_after_max_extract_failures` layout (L204). Add to that file:

```python
from ormah.background.llm_errors import LlmCancelledError, LlmTimeoutError
from ormah.background.session_watcher import MIN_SLICE_BYTES  # new in Step 4


def _project(tmp_path, name="abc123.jsonl", turns=6):
    """watch_dir + an idle transcript, mirroring the toxic-slice test's layout."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True, exist_ok=True)
    jsonl = project_dir / name
    _make_jsonl(jsonl, user_turns=turns)
    _mark_idle(jsonl)
    return watch_dir, jsonl, str(jsonl.relative_to(watch_dir))


def _refresh_health(engine, watch_dir, project_dir, state, n):
    """Bump the module's success marker with a DISTINCT transcript each time.

    council R5: re-ingesting the same healthy file returns NO_PROGRESS on the second pass
    (unchanged hash + cursor at EOF, session_watcher.py:770-771), so it would never reach
    the LLM and never refresh _LAST_EXTRACT_OK. Each refresh needs a new file.
    """
    healthy = project_dir / f"healthy{n}.jsonl"
    _make_jsonl(healthy, user_turns=6)
    _mark_idle(healthy)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(
            engine, healthy, state, watch_dir, min_turns=5) == IngestResult.OK


def test_timeout_during_outage_never_quarantines(engine, tmp_path):
    """Outage: every call times out and NO success ever lands, so no health evidence
    exists. The slice must stay TRANSIENT forever — never counted, never quarantined,
    cursor never advanced (H1 mass-loss guard)."""
    watch_dir, jsonl, rel = _project(tmp_path)
    state = {}
    with patch(_LLM_PATCH, side_effect=LlmTimeoutError("timed out")), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for _ in range(MAX_EXTRACT_FAILURES + 2):
            assert _ingest_session(
                engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT
    entry = state.get(rel, {})
    assert entry.get("end_offset", 0) == 0
    assert entry.get("extract_fail_count", 0) == 0
    assert "skipped_slices" not in entry


def test_cancelled_extraction_never_mutates_slice_state(engine, tmp_path):
    """A shutdown cancel says nothing about the slice: EXTRACT_ERR_CALL_FAILED ->
    uncapped TRANSIENT, even with health evidence present. Repeated restarts must never
    quarantine a healthy slice."""
    watch_dir, jsonl, rel = _project(tmp_path)
    state = {}
    with patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        _refresh_health(engine, watch_dir, jsonl.parent, state, 1)  # health evidence
        with patch(_LLM_PATCH, side_effect=LlmCancelledError("shutdown")):
            for _ in range(MAX_EXTRACT_FAILURES + 2):
                assert _ingest_session(
                    engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT
    entry = state.get(rel, {})
    assert entry.get("end_offset", 0) == 0
    assert entry.get("extract_fail_count", 0) == 0
    assert "skipped_slices" not in entry


def test_big_slice_shrinks_before_any_quarantine(engine, tmp_path):
    """council R4: lateness is not toxicity. A bracketed timeout HALVES the slice
    (extract_shrink_level 0->1) instead of counting toward the cap; a later success
    clears the level."""
    watch_dir, slow, rel_slow = _project(tmp_path, "slow.jsonl", turns=12)
    state = {}
    with patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        # 1st timeout: no previous fail timestamp -> no bracket -> plain TRANSIENT
        with patch(_LLM_PATCH, side_effect=LlmTimeoutError("t")):
            assert _ingest_session(
                engine, slow, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT
        assert state[rel_slow].get("extract_shrink_level", 0) == 0
        # a success elsewhere proves the provider works -> health evidence
        _refresh_health(engine, watch_dir, slow.parent, state, 1)
        # 2nd timeout on the slow slice is bracketed -> SHRINK, still no cap
        with patch(_LLM_PATCH, side_effect=LlmTimeoutError("t")):
            assert _ingest_session(
                engine, slow, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT
        assert state[rel_slow]["extract_shrink_level"] == 1
        assert state[rel_slow].get("extract_fail_count", 0) == 0
        assert "skipped_slices" not in state[rel_slow]
        # a success at the smaller size clears the shrink level
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(
                engine, slow, state, watch_dir, min_turns=5) == IngestResult.OK
        assert "extract_shrink_level" not in state[rel_slow]


def test_quarantine_only_at_shrink_floor(engine, tmp_path):
    """Already at the floor (flush_bytes == MIN_SLICE_BYTES) there is nothing left to
    shrink, so bracketed timeouts DO count and the slice quarantines after
    MAX_EXTRACT_FAILURES — the toxic-slice path stays reachable."""
    watch_dir, slow, rel_slow = _project(tmp_path, "slow.jsonl", turns=6)
    state = {}
    with patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        with patch(_LLM_PATCH, side_effect=LlmTimeoutError("t")):  # seed extract_fail_at
            _ingest_session(engine, slow, state, watch_dir,
                            min_turns=5, flush_bytes=MIN_SLICE_BYTES)
        for expected in range(1, MAX_EXTRACT_FAILURES):
            _refresh_health(engine, watch_dir, slow.parent, state, expected)
            with patch(_LLM_PATCH, side_effect=LlmTimeoutError("t")):
                assert _ingest_session(
                    engine, slow, state, watch_dir, min_turns=5,
                    flush_bytes=MIN_SLICE_BYTES) == IngestResult.TRANSIENT
            assert state[rel_slow]["extract_fail_count"] == expected
            assert state[rel_slow]["end_offset"] == 0
        _refresh_health(engine, watch_dir, slow.parent, state, 99)
        with patch(_LLM_PATCH, side_effect=LlmTimeoutError("t")):
            assert _ingest_session(
                engine, slow, state, watch_dir, min_turns=5,
                flush_bytes=MIN_SLICE_BYTES) == IngestResult.OK   # capped -> skip forward
    assert state[rel_slow]["end_offset"] > 0
    assert state[rel_slow]["skipped_slices"][0]["reason"] == "extract_timeout_x3"


def test_one_success_authorizes_at_most_one_count(engine, tmp_path):
    """council R2 atomicity: the fail-timestamp refresh and the count must land in ONE
    commit, so a single success can authorize at most ONE counted timeout. Without a new
    success the next timeout stays uncounted."""
    watch_dir, slow, rel_slow = _project(tmp_path, "slow.jsonl", turns=6)
    state = {}
    with patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        with patch(_LLM_PATCH, side_effect=LlmTimeoutError("t")):
            _ingest_session(engine, slow, state, watch_dir, min_turns=5,
                            flush_bytes=MIN_SLICE_BYTES)
        _refresh_health(engine, watch_dir, slow.parent, state, 1)
        with patch(_LLM_PATCH, side_effect=LlmTimeoutError("t")):
            _ingest_session(engine, slow, state, watch_dir, min_turns=5,
                            flush_bytes=MIN_SLICE_BYTES)
        assert state[rel_slow]["extract_fail_count"] == 1
        # NO new success in between -> the bracket is spent, count must not grow
        with patch(_LLM_PATCH, side_effect=LlmTimeoutError("t")):
            _ingest_session(engine, slow, state, watch_dir, min_turns=5,
                            flush_bytes=MIN_SLICE_BYTES)
        assert state[rel_slow]["extract_fail_count"] == 1


def test_call_failed_still_never_counts(engine, tmp_path):
    """Regression guard: a provider-wide call failure (None from the adapter) stays
    uncapped TRANSIENT after the timeout split."""
    watch_dir, jsonl, rel = _project(tmp_path)
    state = {}
    with patch(_LLM_PATCH, return_value=None), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for _ in range(MAX_EXTRACT_FAILURES + 2):
            assert _ingest_session(
                engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT
    assert "skipped_slices" not in state.get(rel, {})
```

⚠️ `test_quarantine_only_at_shrink_floor` and `test_one_success_authorizes_at_most_one_count`
depend on `MIN_SLICE_BYTES` being >= the transcript slice these fixtures produce; if the
6-turn fixture is smaller than the floor, raise `turns` until `flush_bytes=MIN_SLICE_BYTES`
actually caps the parse (check `result.capped`) — otherwise the floor branch is never hit
and the test passes vacuously.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_background/test_session_watcher.py -v -k \
  "timeout_during_outage or cancelled_extraction or big_slice_shrinks or \
   quarantine_only_at_shrink_floor or one_success_authorizes or call_failed_still"
```

Expected: FAIL — `ImportError` on `ormah.background.llm_errors` / `MIN_SLICE_BYTES`.
(council R5: the filter must match the REAL test names, or Step 2 silently runs nothing.)

- [ ] **Step 3: Implement — engine**

In `memory_engine.py`, next to the existing constants (~L54-61), matching their exact
string style (read them first — format is `"extract_error: ..."`-like; copy the pattern):

```python
EXTRACT_ERR_TIMEOUT = "extract_error_timeout"  # align literal style with the two neighbors
```

In `_extract_memories_llm`, wrap the `ingest_llm_generate` call (L2861-2867):

```python
                from ormah.background.llm_errors import LlmCancelledError, LlmTimeoutError
                try:
                    raw = ingest_llm_generate(
                        self.settings, prompt, json_mode=True,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {"schema": _INGEST_RESPONSE_SCHEMA},
                        },
                    )
                except LlmCancelledError:
                    # codex R3: MUST be caught BEFORE any broader handler — an uncaught
                    # cancel would fall into the generic slice-specific error path and
                    # let repeated shutdowns quarantine a healthy slice. A cancel says
                    # nothing about the slice -> provider-wide transient.
                    logger.warning("ingest extraction: chunk %d/%d cancelled (shutdown)",
                                   i + 1, len(chunks))
                    return EXTRACT_ERR_CALL_FAILED
                except LlmTimeoutError:
                    # A slow/toxic slice, not an outage: bubble a DISTINCT error string so
                    # the watcher counts it toward the per-slice cap (ADR-0004). Partial
                    # chunk results are discarded for the same council-B1 reason as below.
                    logger.warning(
                        "ingest extraction: chunk %d/%d timed out — whole slice retryable, "
                        "counts toward per-slice cap", i + 1, len(chunks),
                    )
                    return EXTRACT_ERR_TIMEOUT
```

(Move the import to the module's import block if `memory_engine` already imports from
`ormah.background` at top level; otherwise keep it local like the existing L2849 pattern.)

- [ ] **Step 4: Implement — watcher classification**

In `session_watcher.py`, extend the import of the error constants (find the existing
`EXTRACT_ERR_NO_PROVIDER` import near the top) with `EXTRACT_ERR_TIMEOUT`, then in the
`isinstance(ingested, str)` block (L942-954) add BEFORE the provider-wide check:

```python
    if isinstance(ingested, str):
        if ingested == EXTRACT_ERR_TIMEOUT:
            # Health gate (council R1): a timeout counts toward the per-slice cap ONLY
            # when some other slice extracted successfully since THIS slice's previous
            # timeout — that brackets the failure as slice-specific. Without that
            # evidence it is indistinguishable from a provider outage -> TRANSIENT
            # (an outage must never quarantine real data, H1).
            # ONE locked read-decide-write (council R2): the same _commit_state call
            # persists the refreshed extract_fail_at AND the count, so one success can
            # authorize at most one counted timeout.
            prev_fail_at = (existing or {}).get("extract_fail_at", None)
            counted = prev_fail_at is not None and _LAST_EXTRACT_OK > prev_fail_at
            level = (existing or {}).get("extract_shrink_level", 0)
            floor = min(MIN_SLICE_BYTES, flush_bytes)
            # council R6: compare the EFFECTIVE size actually used by the parse, not the
            # raw shift — otherwise a flush_bytes just above the floor reports at_floor
            # too early and quarantines before the shrink levels are exhausted.
            at_floor = max(floor, flush_bytes >> level) <= floor
            # council R7: halving cannot split a SINGLE oversized turn — the parser commits
            # it whole because it has no internal safe boundary. If the previous shrink did
            # not actually move payload_offset, more levels are useless: treat it as the
            # floor so the (logged, replayable) quarantine path can eventually run.
            prev_payload = (existing or {}).get("extract_fail_payload_offset")
            if prev_payload is not None and prev_payload == payload_offset and level > 0:
                logger.warning(
                    "Session watcher shrink is a no-op for %s (single oversized turn) — "
                    "treating as floor", path)
                at_floor = True
            if counted and not at_floor:
                # council R4: lateness is not toxicity — halve the slice and retry before
                # even considering the cap. A big-but-valid slice must shrink, not be lost.
                logger.warning("Session watcher slice timeout for %s — shrinking to level %d",
                               path, level + 1)
                _mark_slice_timeout(state, rel, state_lock, watch_dir, shrink_level=level + 1)
                return IngestResult.TRANSIENT
            if counted:
                logger.warning("Session watcher slice timeout at shrink floor for %s", path)
                return _record_extract_failure("extract_timeout_x3", fail_at=time.monotonic())
                # _record_extract_failure gains an optional fail_at kwarg: it writes
                # extract_fail_at in the SAME entry/commit it already performs.
            logger.warning("Session watcher extraction timeout (no health evidence) for %s", path)
            _mark_slice_timeout(state, rel, state_lock, watch_dir)  # single commit: extract_fail_at=now
            return IngestResult.TRANSIENT
        if ingested in (EXTRACT_ERR_NO_PROVIDER, EXTRACT_ERR_CALL_FAILED):
            ...  # existing block unchanged
```

Supporting pieces (same file): module global `_LAST_EXTRACT_OK: float = 0.0` updated via
`time.monotonic()` right before `return IngestResult.OK` in `_ingest_session` (~L995);
helper `_mark_slice_timeout(state, rel, state_lock, state_dir, shrink_level=None)` that
merges `{"extract_fail_at": time.monotonic(), "extract_fail_payload_offset": payload_offset}`
(plus `extract_shrink_level` when given)
into the slice entry via the existing `_commit_state` (L706); module constant
`MIN_SLICE_BYTES = 4000`; the parse call at L776 becomes
`max_bytes=max(min(MIN_SLICE_BYTES, flush_bytes), flush_bytes >> (existing or {}).get("extract_shrink_level", 0))`
— use `(existing or {})`, the variable loaded at L765; there is no `entry` in scope there
(council R5). Compute it into a local (`slice_bytes`) for readability; and a success
clears `extract_fail_at` and `extract_shrink_level` alongside
`extract_fail_offset`/`extract_fail_count` (L982-983). Note `_LAST_EXTRACT_OK` is
in-memory only — after a restart the bracket restarts, which only makes quarantine
SLOWER, never lossier (fail-safe direction).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_background/test_session_watcher.py tests/test_engine/test_ingest.py -v`
Expected: PASS — new tests green, all existing cap/transient tests untouched and green.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/ tests/
git add src/ormah/engine/memory_engine.py src/ormah/background/session_watcher.py \
        tests/test_background/test_session_watcher.py
git commit -m "feat(ingest): extraction timeout counts toward per-slice quarantine cap (ADR-0004)"
```
