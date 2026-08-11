# Task 2: Always-on Ingest worker — drains the spool; Observer becomes optional

**Files:**
- Modify: `src/ormah/background/session_watcher.py` — `SessionHandler` gains the spool drain
  loop (`wake()` + a worker thread)
- Modify: `src/ormah/background/session_watcher.py:1279-1425` (`SessionWatch`,
  `start_session_watcher`, `stop_session_watcher`, `run_session_reconcile`)
- Modify: `src/ormah/main.py:244-253` (lifespan wiring) AND `main.py:282-283` (shutdown —
  ⚠️ council R1: it reads `app.state.session_watcher_observers` today; MUST migrate to the
  same attribute the startup writes, or `stop_session_watcher` never runs → use-after-close)
- Test: `tests/test_background/test_session_watcher.py`, `tests/test_main_lifespan_shutdown.py`

**Interfaces:**
- Consumes: `IngestSpool` from Task 1.
- Produces:
  - `SessionHandler.wake() -> None` — non-blocking signal that the spool has work. Sets an
    `Event`; the drain thread does the rest. The endpoint (Task 3) calls it after enqueuing.
  - **ONE ingestion path.** ⚠️ This is the council's central finding (R12, cursor + codex
    independently) and it changes the shape of this task. An earlier draft had the drain
    calling `_ingest_session` directly while the **Observer kept its own path** through
    `_do_ingest` (which owns the `_ingesting` guard and the `state_lock`). That is two
    producers ingesting the same transcript concurrently whenever
    `session_watcher_enabled=True` — the very overlap the prototype measured between two
    workers (14 with 2, 21 with 4), reintroduced between Observer and drain.

    **The Observer no longer ingests. It enqueues.** On a file event it calls
    `spool.enqueue(path, boundary=<current EOF>, reason="observer")` and returns. So does
    the reconcile sweep (`reason="reconcile"`). Three producers, one queue, one serial
    consumer that owns `_ingesting`, `state_lock`, pending reruns and shutdown accounting.
    The debounce stays where it belongs — on the Observer's enqueue, not on the drain.
    This deletes `_do_ingest` as a second entry point rather than guarding it.
  - **The drain loop**, which replaces the whole cursor-flag machinery:
    `claim_next()` → one path-level `_run_job` → dispose. Disposition rules, in order:
    - `OK` reaching the boundary → `complete(job)`.
    - `OK` **capped** short of the boundary → **enqueue the remainder FIRST, then
      `complete(job)`** (council R12, cursor). The reverse order has a crash window that
      loses the intent; this order's worst case is a duplicate job, which the cursor makes
      a no-op.
    - `TRANSIENT` → `requeue(job, failure_class="external")` — retried forever with
      persisted backoff, never dead-lettered (Task 1).
    - `NO_PROGRESS` on an **idle** file → `complete(job)`: the closed delta is provably
      empty. ⚠️ If the file is idle and the parser still finds **no safe boundary** (a
      single unterminated turn), completing would strand those bytes forever. Detect that
      case explicitly and dead-letter it with a distinct reason rather than silently
      completing — slice 3 owns the real policy, but it must not vanish here.
  - `spool.recover()` runs **once per watch, at startup, before the drain thread starts** —
    a job left in `running/` by a crash returns to `pending/`.
  - `start_session_watcher(engine) -> list[SessionWatch]` — SAME name/signature, new
    semantics: always builds `SessionHandler` + spool + drain thread per watch root;
    attaches a watchdog `Observer` ONLY when `settings.session_watcher_enabled` is true.
  - `SessionWatch.observer: Observer | None` (was always an Observer);
    `SessionWatch.spool: IngestSpool` (new); `SessionWatch.startup_thread` is **removed**.
  - `app.state.session_watches: list[SessionWatch]` set in lifespan (Task 3's endpoint
    reads it to find the spool + handler for a nudged path).
- **Invariant preserved:** one cursor (`<watch_dir>/.session_watcher_state`), one in-flight
  guard (`SessionHandler._ingesting`), one spool per root, regardless of the enabled flag.
- **Invariant CHANGED — read this.** Crash recovery is no longer "walk the tree and find
  cursors behind EOF" (`_run_startup_reconcile` L1287): it is `spool.recover()`, which is a
  directory rename and costs microseconds. `_run_startup_reconcile` therefore becomes part
  of the *discovery* producer and runs only when the watcher is enabled. This is the change
  that removes the startup tree walk from every disabled install.

## Test disposition — the plan undercounted the fallout (re-plan 2026-07-23)

⚠️ **This section supersedes the "two existing tests to rewrite" claim in Step 5.** The
first draft of Step 5 said the suite passes after rewriting exactly two tests. That is
false: deleting `_do_ingest` and making the Observer/reconcile enqueue-only structurally
breaks **26 existing tests** in `test_session_watcher.py` (AST-span + symbol grep verified,
2026-07-23). Council R5's own warning — "silently deleting a test drops real coverage" —
applies with far more force to 26 than to 2. André paused execution here to sign off on the
coverage decision before any code. Architecture **A** (delete `_do_ingest`; the drain thread
is the only consumer) is fixed — it is council R12's central finding, and the "hybrid B"
that keeps `_do_ingest` synchronous inside `reconcile()` reintroduces the two-path defect.
What is being decided is the **per-test disposition** below.

**One decision shrinks the loss (D3):** `reconcile_max_per_tick` (config.py, default 50) is
**kept as a producer-side ENQUEUE cap** — reconcile enqueues at most N jobs per sweep,
oldest-first by mtime. That preserves the per-tick budget (#19) AND the never-seen
starvation guard (#20) cheaply, turning both from DELETE into REWRITE. The serial drain
still paces *consumption*; the cap now paces *production* so one sweep of a 10k-transcript
backlog cannot enqueue 10k files at once.

| # | Test (line) | Disposition | Rationale / where coverage moves |
|---|---|---|---|
| 1 | `test_retry_fires_and_ingests_after_idle` L1573 | REWRITE | idle-refire now ENQUEUES; assert ingest via the drain path |
| 2 | `test_concurrent_ingest_skipped` L1631 | DELETE | dedup is structural now → `test_ingest_spool.py::test_claim_is_exclusive_across_threads` + serial drain |
| 3 | `test_inflight_skip_reschedules` L1887 | DELETE | → `test_ingest_spool.py::test_nudge_during_an_in_flight_job_survives_its_completion` |
| 4 | `test_do_ingest_returns_ok_when_it_ingests` L1969 | DELETE | `_do_ingest` gone; OK/NO_PROGRESS contract belongs to `_ingest_session`, covered by `test_ingest_session_basic` etc. |
| 5 | `test_do_ingest_rejected_after_stop_event` L2507 | REWRITE | use-after-close guard moves to the drain claim step; assert the drain refuses to ingest once `_stop_event` is set |
| 6 | `test_stop_session_watcher_drains_inflight_ingest` L2528 | REWRITE | same #52 guarantee, proven against the drain thread; drop the `startup_thread=None` ctor kwarg |
| 7 | `test_start_session_watcher_runs_catchup_off_bind` L2576 | REWRITE | "observer live immediately, backlog eventually recovered" via reconcile-enqueue + drain, not `startup_thread` |
| 8 | `test_reconcile_ingests_file_the_live_path_missed` L1984 | REWRITE | assert `reconcile()` ENQUEUES the missed file; post-drain assert `_state` advanced |
| 9 | `test_reconcile_skips_fully_consumed_file_on_second_pass` L2005 | REWRITE | assert the second sweep does not enqueue a duplicate once drained |
| 10 | `test_reconcile_does_not_reingest_what_live_path_already_took` L2020 | REWRITE | drive via enqueue+drain, then assert reconcile does not re-enqueue |
| 11 | `test_reconcile_retries_seen_file_when_first_do_ingest_fails` L2058 | DELETE | tick-cadence retry → backoff-cadence: `test_requeue_external_retries_forever_with_persisted_growing_backoff` |
| 12 | `test_reconcile_recovers_partial_tail_without_mtime_change` L2087 | REWRITE | offset≠size detection still gates enqueue; assert it enqueues despite unchanged mtime |
| 13 | `test_reconcile_while_live_ingesting_defers_then_retries` L2107 | REWRITE | reconcile no longer touches `_ingesting`; assert it does not double-enqueue a path already pending/running |
| 14 | `test_reconcile_skips_never_seen_when_lookback_negative` L2472 | REWRITE | same policy; assert reconcile does not enqueue the never-seen file |
| 15 | `test_reconcile_never_parks_transient_failures` L2232 | DELETE | `_reconcile_attempts`/`MAX_RECONCILE_RETRIES` gone; "external retries forever, never capped" → Task 1 requeue test |
| 16 | `test_reconcile_unparks_after_same_size_content_change` L2266 | DELETE | **efficiency dropped (D5)**: correctness preserved by producer re-enqueue on the next content change; only the same-size fast-path is lost |
| 17 | `test_reconcile_deprioritizes_persistent_transient_behind_valid` L2315 | DELETE | **(D4)** in-memory deprioritization → `not_before` gating; replaced by new test T-N1 below |
| 18 | `test_reconcile_deprioritized_transients_retried_oldest_first` L2381 | DELETE | **(D4)** strict FIFO among backed-off jobs dropped; serial drain processes all; no-starvation proven by T-N1 |
| 19 | `test_reconcile_respects_per_tick_time_budget` L2428 | REWRITE | **(D3)** budget survives as the producer-side enqueue cap; assert reconcile enqueues ≤ cap per sweep |
| 20 | `test_reconcile_does_not_starve_valid_file_behind_stuck_never_seen_files` L2202 | REWRITE | **(D3)** assert the enqueue cap + oldest-first still lets a valid file through |
| 21 | `test_disabled_returns_empty` L1147 | REWRITE | → `test_disabled_yields_worker_without_observer` (already slated) |
| 22 | `test_nonexistent_watch_dir` L1181 | REWRITE | → `test_absent_watch_dir_is_created` (already slated) |
| A | `test_reconcile_logs_recovery_heartbeat` L2040 | REWRITE | heartbeat counts "enqueued" now, not "ingested"; adjust the log assertion |
| B | `test_reconcile_bounds_retries_for_abandoned_inflight_tail` L2128 | DELETE | **(D6)** INVERTED by design: ADR-0004 H1 retries external failures forever with backoff; the "must cap" assertion is now false-by-design |
| C | `test_run_session_reconcile_recreates_dead_observer` L2158 | REWRITE (verify-only) | observer-recreation is architecture-agnostic; only the return-count contract (ingested→enqueued) may shift |
| D | `test_run_session_reconcile_runs_reconcile_even_when_recreate_fails` L2182 | REWRITE (verify-only) | `handler.reconcile` is mocked; likely a sanity check of the mocked return type only |

**Totals: 17 REWRITE, 9 DELETE (26 rows).** Every DELETE names where its behavior went or
that it is intentionally dropped. Each DELETE must carry a one-line rationale in the commit
message (council R5).

**New tests this task must ADD to close the gaps the disposition opens:**
- **T-N1** `test_a_due_job_is_claimed_ahead_of_a_backed_off_one` — with one valid job and one
  external-failure job whose `not_before` is in the future, the drain ingests the valid one
  and does not stall behind the backed-off one (replaces the deprioritization FIFO coverage,
  #17/#18).
- **T-N2** `test_reconcile_enqueues_at_most_the_per_tick_cap` — a sweep over more than
  `reconcile_max_per_tick` candidates enqueues exactly the cap, oldest-first (preserves #19/#20).
- **T-N3** `test_idle_file_with_no_safe_boundary_is_dead_lettered` — the NO_PROGRESS-on-idle
  path that finds no safe boundary (single unterminated turn) dead-letters with a distinct
  reason instead of silently completing (the `_run_job` rule already stated above; it needs a test).

**Coverage GENUINELY dropped, signed off as acceptable (not merely relocated):**
- Same-size content-change *fast-path* un-parking (#16) — correctness preserved by producer
  re-enqueue; only the "repaired file retries slightly sooner than backoff" optimization is lost.
- Strict oldest-first ordering among multiple backed-off jobs (#18) — the serial drain still
  processes all of them; only the deterministic order is gone (T-N1 proves no starvation).

**Sanctioned deviation (D8):** add a module-level `_default_acceptance_roots() -> list[Path]`
so the "acceptance roots = discovery ∪ default Claude ∪ Codex" set is patchable, and an
**autouse fixture** in `test_session_watcher.py` that patches it to `[]` by default (the real
`~/.claude/projects` and `~/.codex/sessions` exist on the Beta dev machine — without this the
suite would build watches over real home and violate the never-touch-`~/.claude` constraint).
The two acceptance-root regressions set it explicitly.

- [ ] **Step 1: Write the failing tests**

Mirror the existing start/stop test fixtures in `test_session_watcher.py` (find the tests
that call `start_session_watcher` with a settings stub; reuse their engine/settings fakes):

```python
def test_worker_starts_with_watcher_disabled(tmp_path):
    """session_watcher_enabled=False still yields a live handler + startup drain,
    but NO Observer (ADR-0004 always-on worker)."""
    # settings stub: session_watcher_enabled=False, session_watcher_dir=str(tmp_path)
    watches = start_session_watcher(engine_stub)
    assert len(watches) == 1
    assert watches[0].observer is None
    assert watches[0].handler is not None
    assert watches[0].spool is not None
    assert watches[0].handler._drain_thread.is_alive()
    stop_session_watcher(watches)  # must not raise with observer=None


def test_observer_attached_only_when_enabled(tmp_path):
    """enabled=True keeps today's behavior: Observer scheduled and alive."""
    watches = start_session_watcher(engine_stub_enabled)
    assert watches[0].observer is not None and watches[0].observer.is_alive()
    stop_session_watcher(watches)


def test_disabled_worker_ingests_only_what_the_spool_holds(engine, tmp_path):
    """The consent boundary, now structural: with session_watcher_enabled=False the worker
    drains the queue and nothing else. A transcript nobody nudged is never touched — no
    reconcile scope rule, no discover flag; the queue IS the intent."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    never_seen = proj / "never.jsonl"
    _make_jsonl(never_seen, user_turns=6)
    _mark_idle(never_seen)
    nudged = proj / "nudged.jsonl"
    _make_jsonl(nudged, user_turns=6)
    _mark_idle(nudged)

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        w.spool.enqueue(nudged, boundary=nudged.stat().st_size, reason="nudge")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            w.handler.wake()
            _wait_until(lambda: w.spool.pending_count() == 0, timeout=5)
        state = _load_state(watch_dir)
        assert str(nudged.relative_to(watch_dir)) in state
        assert str(never_seen.relative_to(watch_dir)) not in state, \
            "a disabled watcher must not ingest transcripts nobody asked for"
    finally:
        stop_session_watcher(watches)


def test_disabled_worker_ignores_growth_after_the_accepted_boundary(engine, tmp_path):
    """The transition case: after a nudged transcript drains, APPENDING more turns must
    not be ingested while the watcher is off — new content needs a new nudge. Here this is
    enforced by the boundary ceiling plus an empty queue, not by a reconcile scope rule."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "known.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        w.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            w.handler.wake()
            _wait_until(lambda: w.spool.pending_count() == 0, timeout=5)
        first_offset = _load_state(watch_dir)[rel]["end_offset"]
        assert first_offset > 0

        _make_jsonl(jsonl, user_turns=12)          # the session grew; nobody nudged
        _mark_idle(jsonl)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as llm:
            w.handler.wake()
            time.sleep(0.5)
            assert not llm.called, "an empty queue means no work, even with new bytes on disk"
        assert _load_state(watch_dir)[rel]["end_offset"] == first_offset
    finally:
        stop_session_watcher(watches)


def test_a_capped_batch_re_enqueues_the_remainder(engine, tmp_path):
    """The drain must finish a boundary larger than flush_bytes on its own. This is what
    the superseded design needed a sticky, carefully-cleared flag for."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "big.jsonl"
    _make_jsonl(jsonl, user_turns=12)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    boundary = jsonl.stat().st_size

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    engine.settings.session_watcher_flush_bytes = 400        # force several capped batches
    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        w.spool.enqueue(jsonl, boundary=boundary, reason="nudge")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            w.handler.wake()
            _wait_until(lambda: w.spool.pending_count() == 0, timeout=20)
        assert _load_state(watch_dir)[rel]["end_offset"] >= boundary, \
            "the drain must reach the accepted boundary across capped batches"
        assert not list((w.spool.root / "running").iterdir())
    finally:
        stop_session_watcher(watches)


def test_a_transient_failure_keeps_the_job_queued(engine, tmp_path):
    """Durability is the point: a failed attempt must not consume the intent, and an
    OUTAGE must never dead-letter (ADR-0004 H1)."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        w.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
        with patch(_LLM_PATCH, return_value=None), \
             patch("ormah.background.session_watcher.ingest_provider_configured",
                   return_value=True):
            w.handler.wake()
            _wait_until(lambda: w.spool.pending_count() == 1, timeout=10)
        assert rel not in _load_state(watch_dir) or \
            _load_state(watch_dir)[rel].get("end_offset", 0) == 0
        assert not list((w.spool.root / "failed").iterdir()), \
            "an outage must never dead-letter an accepted job"
    finally:
        stop_session_watcher(watches)


def test_crash_recovery_requeues_an_in_flight_job(engine, tmp_path):
    """A job left in running/ by a killed process must come back on the next start."""
    from ormah.background.ingest_spool import IngestSpool, root_key, spool_root

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    # simulate the previous process: enqueue, claim, then die without completing
    pre = IngestSpool(spool_root(engine.settings) / root_key(watch_dir))
    pre.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    assert pre.claim_next() is not None
    assert pre.pending_count() == 0

    watches = start_session_watcher(engine)          # <- the restart
    try:
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _wait_until(lambda: watches[0].spool.pending_count() == 0, timeout=10)
        assert _load_state(watch_dir)[rel]["end_offset"] > 0, \
            "a job orphaned in running/ must be recovered and drained"
    finally:
        stop_session_watcher(watches)


def test_observer_and_drain_never_ingest_the_same_transcript(engine, tmp_path):
    """council R12 (cursor+codex): the Observer must ENQUEUE, not ingest. With both a file
    event and a nudge racing on one transcript, exactly ONE extraction may run at a time."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    engine.settings.session_watcher_enabled = True       # Observer ON -- the risky config
    engine.settings.session_watcher_dir = watch_dir
    engine.settings.session_watcher_debounce_seconds = 0.05
    concurrent, active = [], []
    lock = threading.Lock()

    def _slow_llm(*a, **kw):
        with lock:
            if active:
                concurrent.append(1)
            active.append(1)
        time.sleep(0.3)
        with lock:
            active.pop()
        return _LLM_RESPONSE

    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        with patch(_LLM_PATCH, side_effect=_slow_llm):
            w.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
            w.handler.wake()
            _make_jsonl(jsonl, user_turns=12)        # file event -> Observer produces too
            time.sleep(2.0)
        assert not concurrent, \
            f"two extractions overlapped on one transcript ({len(concurrent)} times)"
    finally:
        stop_session_watcher(watches)


def test_acceptance_only_root_is_never_swept_while_enabled(engine, tmp_path):
    """council R12 (codex): with a CUSTOM session_watcher_dir, the default roots exist only
    so an explicit nudge is not 422'd. They must get no Observer and no reconcile."""
    custom = tmp_path / "custom"
    (custom / "p").mkdir(parents=True)
    default_root = tmp_path / "claude-projects"
    (default_root / "p").mkdir(parents=True)
    stray = default_root / "p" / "nobody-nudged.jsonl"
    _make_jsonl(stray, user_turns=6)
    _mark_idle(stray)

    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = custom
    # point the default-root resolver at default_root for the test (monkeypatch the
    # helper that _configured_watch_roots uses), then:
    watches = start_session_watcher(engine)
    try:
        acc = next(w for w in watches if w.watch_dir == default_root)
        assert acc.discover is False
        assert acc.observer is None
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as llm:
            run_session_reconcile(watches)
            assert not llm.called, "an acceptance-only root must never be swept"
        assert str(stray.relative_to(default_root)) not in _load_state(default_root)
    finally:
        stop_session_watcher(watches)


def test_configured_but_absent_dir_still_yields_a_handler(engine, tmp_path):
    """council R4/R5: session_watcher_dir points at a path that does not exist yet.
    start_session_watcher must still return one SessionWatch (root created, handler live)
    so a later nudge for a transcript under it is accepted instead of 422'd forever."""
    missing = tmp_path / "does-not-exist"
    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = missing
    watches = start_session_watcher(engine)
    try:
        assert len(watches) == 1
        assert watches[0].watch_dir == missing
        assert missing.is_dir()               # created, not skipped
        assert watches[0].handler is not None
        assert watches[0].observer is None    # disabled -> worker only
    finally:
        stop_session_watcher(watches)


def test_run_session_reconcile_skips_observer_recreation_when_none(tmp_path):
    """run_session_reconcile on an observer-less watch reconciles the handler and does
    NOT create an Observer (only the Observer is opt-in; the sweep itself always runs)."""
    watches = start_session_watcher(engine_stub)  # disabled
    run_session_reconcile(watches)
    assert watches[0].observer is None
    stop_session_watcher(watches)
```

And in `tests/test_main_lifespan_shutdown.py` (council R1 — today it mocks
`start_session_watcher → []`, which would hide a shutdown-attribute bug):

```python
async def test_lifespan_shutdown_drains_always_on_worker(monkeypatch, tmp_path):
    """council R1: with the always-on worker, start_session_watcher returns a non-empty
    list even when disabled. The lifespan must store it and shutdown must hand EXACTLY
    that list to stop_session_watcher — the bug this guards is the startup writing
    `session_watches` while shutdown still reads `session_watcher_observers`."""
    # Reuse this file's existing fake-module fixture wiring (sys.modules setitem for
    # ormah.background.hippocampus / session_watcher / scheduler, the _FakeEngine and
    # ormah.main.settings monkeypatches around L265-290) verbatim, but make the fake
    # session_watcher module record its calls instead of returning []:
    sentinel = ["watch-sentinel"]
    stopped = []
    _fake_session_watcher = type(sys)("_fake_sw")
    _fake_session_watcher.start_session_watcher = lambda engine: sentinel
    _fake_session_watcher.stop_session_watcher = lambda w: stopped.append(w)
    _fake_session_watcher.run_session_reconcile = lambda w: 0
    monkeypatch.setitem(sys.modules, "ormah.background.session_watcher", _fake_session_watcher)

    app = FastAPI(lifespan=main.lifespan)
    async with main.lifespan(app):
        assert app.state.session_watches is sentinel
    assert stopped == [sentinel], "shutdown must drain the always-on worker"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "worker_starts or observer_attached or skips_observer" -v`
Expected: FAIL — disabled path returns `[]` today (L1308-1309).

- [ ] **Step 3: Implement — session_watcher.py**

1. `SessionWatch` (L1279): `observer: "Observer | None"`.
2. `start_session_watcher` (L1299): delete the early-return at L1308-1309. In the loop,
   build the handler + startup thread unconditionally; wrap ONLY the Observer part:

```python
            enabled = s.session_watcher_enabled
            spool = IngestSpool(spool_root(s) / _root_key(watch_dir))  # one spool per root
            requeued = spool.recover()          # BEFORE the drain thread starts
            if requeued:
                logger.info("Recovered %d in-flight ingest job(s) on %s", requeued, watch_dir)
            handler = SessionHandler(..., spool=spool)   # otherwise unchanged args, always
            handler.start_drain()               # the always-on worker thread
            observer = None
            if enabled:
                observer = Observer()
                observer.schedule(handler, str(watch_dir), recursive=True)
                observer.start()
            watches.append(SessionWatch(watch_dir=watch_dir, handler=handler,
                                        observer=observer, spool=spool))
            logger.info("Ingest worker started on %s (observer=%s)", watch_dir, bool(observer))
```

The `startup_thread` disappears: its job was the startup drain, which is now
`spool.recover()` (synchronous, microseconds) plus the drain thread picking the work up. Do
not keep both — two producers racing at bind time is how the original bind-blocking bug
(`_scan_sessions` at startup) was born. `SessionWatch` gains `spool` and drops
`startup_thread`; update `stop_session_watcher` accordingly (it joins `startup_thread` at
L1388-1390 today) and make it stop the drain thread **before** `_drain_handlers`.

### The drain loop

```python
    def start_drain(self) -> None:
        self._wake = threading.Event()
        self._drain_thread = Thread(target=self._drain_forever, daemon=True,
                                    name=f"ingest-drain-{self.watch_dir.name}")
        self._drain_thread.start()

    def wake(self) -> None:
        """Signal that the spool has work. Never blocks -- the request path calls this."""
        self._wake.set()

    def _drain_forever(self) -> None:
        while not self._stop_event.is_set():
            job = self.spool.claim_next()
            if job is None:
                self._wake.wait(timeout=self._idle_poll_seconds)  # belt and braces
                self._wake.clear()
                continue
            self._run_job(job)

    def _run_job(self, job) -> None:
        """The ONE place a transcript is ingested. Owns the guard and the state lock.

        Every producer (nudge, Observer, reconcile) reaches ingestion through here, so
        there is exactly one writer per path and one writer of the cursor.
        """
        with self._ingesting_guard(job.path):        # the existing _ingesting semantics
            result = _ingest_session(
                self.engine, job.path, self._state, self.watch_dir,
                min_turns=self.min_turns,
                boundary=job.boundary,
                state_lock=self._state_lock,   # council R12: the drain MUST hold this too
            )
        if result is IngestResult.TRANSIENT:
            # external failure class -> retried forever with persisted backoff, never
            # dead-lettered (an outage must not discard accepted work: ADR-0004 H1)
            self.spool.requeue(job, failure_class="external")
            return
        if result is IngestResult.OK:
            rel = str(job.path.relative_to(self.watch_dir))
            if (self._state.get(rel, {}).get("end_offset") or 0) < job.boundary:
                # Capped batch: the boundary is not drained yet. ENQUEUE FIRST, COMPLETE
                # SECOND (council R12, cursor) -- the reverse order loses the intent if the
                # process dies between the two calls. A duplicate job is a harmless no-op.
                self.spool.enqueue(job.path, boundary=job.boundary, reason="drain")
        self.spool.complete(job)
```

⚠️ **Do not "fix" the hot-loop risk with an attempt cap.** An earlier draft capped retries
and dead-lettered the rest; that turns a provider outage into data loss, which is exactly
what ADR-0004's H1 rule forbids. The hot loop is prevented by the **persisted backoff**
(Task 1), not by giving up. Only deterministic failures are dead-lettered.

⚠️ **`state_lock` is not optional.** `_do_ingest` passes `self._state_lock` today; a drain
that omits it writes the cursor from a second thread while the Observer's enqueue path
reads it. Combined with a non-atomic `_save_state` that is silent corruption of every
cursor in the watch dir — see the atomic-write step below, which this task now owns.

   ⚠️ **council R4 — this needs `_session_watch_dirs` changed too (L669-681):** it returns
   only candidates where `candidate.exists()` (L679), so merely deleting the `return []`
   still yields an empty loop. Add a sibling `_configured_watch_roots(settings) -> list[Path]`
   that returns the SAME candidate list WITHOUT the exists() filter, and have
   `start_session_watcher` iterate that, calling `mkdir(parents=True, exist_ok=True)` per
   root (skipping only roots whose creation raises). Keep `_session_watch_dirs` as-is for
   its other callers. Rationale below.

   ⚠️ **Do NOT keep the bare `return []` at L1311-1314.** An absent
   `~/.claude/projects` (first-ever install, or a dir that appears minutes later) would
   otherwise store an empty watches list forever: `/ingest/nudge` then answers 422 for the
   real transcript, the hook does not retry, and the session is stranded until a restart.
   Instead: still build a handler for every root (creating the directory with
   `mkdir(parents=True, exist_ok=True)` when it is missing — it is our own watch root),
   log a warning, and only skip a root whose creation raises. `return []` stays only when
   no root resolves at all.

   ⚠️ **Separate "where I discover" from "what I accept"** (council R10 + R11). Two
   opposing findings meet here and the resolution is to stop conflating the two sets:
   - **Discovery roots** = today's `_session_watch_dirs` semantics, unchanged. A custom
     `session_watcher_dir` REPLACES the defaults on purpose; re-adding them would make the
     enabled watcher crawl directories the user deliberately swapped out (council R11).
   - **Nudge-acceptance roots** = discovery roots ∪ the default Claude root ∪ the Codex
     root. A nudge is an explicit, user-originated request, so accepting a path under the
     standard hook locations is safe regardless of where discovery points. Without this,
     a custom `session_watcher_dir` gives every `~/.codex/sessions` transcript a permanent
     422 — a REGRESSION, since the old hook ingested those independently of watcher config
     (council R10).

   Build a handler per ACCEPTANCE root (that is what `/ingest/nudge` matches against), and
   pass each handler its `discover` flag: True only for roots that are also discovery
   roots AND `session_watcher_enabled`. Deduplicate by resolved path and **drop any root
   that is an ancestor or descendant of one already kept** (council R11: `~/.claude` and
   `~/.claude/projects` would otherwise both match a nudge and give it two cursors —
   breaking the ADR's single-cursor invariant). Regressions:
   `test_custom_watch_dir_still_accepts_default_root_nudges` and
   `test_overlapping_roots_are_collapsed_to_one`.
3. Transactional-rollback block (L1339-1354) and `stop_session_watcher` (L1374-1395):
   guard every observer touch with `if w.observer is not None:`. Handler drain/timer logic
   unchanged.
4. `run_session_reconcile` (L1398): recreate-dead-Observer branch only
   `if w.observer is not None`; and **`w.handler.reconcile()` is gated on `w.discover`, not
   called unconditionally** (council R12, codex). This is the finding that a global
   `session_watcher_enabled` check would have hidden: with a custom `session_watcher_dir`,
   the acceptance-only roots (the default Claude root, the Codex root) exist purely so an
   explicit nudge is not 422'd. If the sweep runs on them, the watcher discovers and
   ingests transcripts under directories the user deliberately swapped out — while
   believing it is only watching their custom dir. `discover` is a **per-watch property**,
   and it must gate BOTH Observer creation and `reconcile()`. A single global flag is not
   equivalent. Regression: `test_acceptance_only_root_is_never_swept_while_enabled`.

5. **Startup discovery must not wait for the first periodic tick** (council R12, cursor).
   Removing `startup_thread` moved crash recovery to `spool.recover()`, which is correct —
   but `recover()` only moves `running/ → pending/`. It does **not** discover a transcript
   whose cursor is behind EOF, which is what `_run_startup_reconcile` did at bind. With the
   watcher enabled, that is a real regression: up to one reconcile interval (default 5 min,
   `config.py:100`) of delay after every restart. Keep a startup sweep for roots where
   `discover` is true — either call `handler.reconcile()` once on a short-lived thread, or
   register the periodic job with `next_run_time=now`. It must **not** run at bind on the
   request path: `_scan_sessions` blocking the bind is the original upstream bug.

6. **Make `_save_state` atomic — this task owns it** (council R12, cursor). The rule is
   stated in `00-overview.md` but the implementation step was lost when the tasks were
   renumbered. With an always-on worker it is not optional: a torn `write_text` discards
   every cursor in the watch dir, and `_load_state` treats corrupt JSON as "start fresh".
   Measured: a direct write of a 400 KB file under a concurrent reader produced **7081 torn
   reads**; via `os.replace`, zero.

```python
def _save_state(watch_dir: Path, state: dict) -> None:
    """Persist state atomically — a torn write would discard every cursor in this dir."""
    state_path = watch_dir / _STATE_FILENAME
    tmp = state_path.with_suffix(state_path.suffix + f".tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, state_path)
    with contextlib.suppress(OSError):          # durability of the rename itself
        dir_fd = os.open(state_path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
```

   Regression: `test_save_state_is_atomic_under_a_torn_write` — write a large state, patch
   `os.replace` to raise, and assert the ORIGINAL file is still valid JSON with every prior
   entry intact.

- [ ] **Step 4: Implement — main.py lifespan (start AND stop, one attribute)**

Read `main.py:240-290` before editing. Then:

1. Startup (L244-253): call `start_session_watcher(engine)` unconditionally and assign the
   result to **`app.state.session_watches`** — the ONE canonical attribute (Task 3's
   endpoint and the shutdown both read it).
2. **The reconcile sweep is gated by the per-watch `discover` property, like the Observer.**
   This is the simplification the spool buys. In the superseded design the sweep had to run
   for every install (it was the only recovery path for a lost in-memory job) while being
   scope-restricted so a disabled install would not ingest un-nudged content — a `discover`
   flag threaded through three call sites, plus an `rglob` on every tick for everyone.

   With a durable queue, **recovery is `spool.recover()`**, not a tree walk. So:
   - `discover=False` (watcher disabled, **or** an acceptance-only root) → no Observer, no
     sweep, no `rglob`. The worker drains the spool. Consent is structural, and the
     disabled path costs nothing.
   - `discover=True` → Observer + periodic reconcile exactly as today, both acting as
     *producers* that enqueue into the spool rather than ingesting directly.

   ⚠️ **`discover` is per watch, never a global read of `session_watcher_enabled`**
   (council R12, codex). `enabled` is one of its inputs; the other is whether that root is a
   discovery root at all. Collapsing them re-opens the hole where a custom
   `session_watcher_dir` still sweeps the default Claude/Codex roots.

   Register the periodic job when ANY watch has `discover=True`. If the scheduler is absent (startup failure
   path, `main.py:210-211`), log
   `logger.warning("Ingest recovery degraded: scheduler unavailable, periodic reconcile "
   "disabled — backlog beyond the startup drain waits for a restart")` — documented
   degraded mode (council R2), consistent with every other background job.
3. Shutdown (L282-283): today it reads `app.state.session_watcher_observers` — migrate it
   to `app.state.session_watches` (same guard shape). Then
   `grep -rn "session_watcher_observers" src/ tests/` and migrate every remaining
   reference; zero hits of the old name must remain.
   Ordering unchanged: `stop_session_watcher` runs BEFORE `engine.shutdown()`, and now
   runs even when the flag is off.
4. **Nothing about LLM-call cancellation belongs in this slice.** Slice 2
   (`../2026-07-21-adr-0004-slice2-bounded-shutdown/`) adds `cancel_active_llm_calls()`,
   `resume_llm_adapters()`, and the lifespan-startup re-arm in one commit. Until it lands,
   nothing cancels anything, so there is nothing to re-arm — but be aware that making the
   worker always-on (this task) is exactly what makes slice 2 urgent: shutdown now waits
   on a running extraction for EVERY install, not only watcher-enabled ones.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_background/test_session_watcher.py tests/test_background/test_session_watcher_flush.py -v`
Expected: PASS. ⚠️ **The success criterion is the full disposition, not two rewrites** —
see "Test disposition" above. **26** existing tests break: **17 REWRITE, 9 DELETE**, plus
**3 new tests** (T-N1/T-N2/T-N3). Each DELETE carries its one-line rationale in the commit
message (council R5). The two originally-named rewrites are rows 21/22 of that table
(`test_disabled_returns_empty` → `test_disabled_yields_worker_without_observer`;
`test_nonexistent_watch_dir` → `test_absent_watch_dir_is_created`).

Then `grep -rn "session_watcher_enabled\|start_session_watcher\|_do_ingest\|startup_thread\|_reconcile_attempts\|_reconcile_transient" tests/`
and confirm every hit is either an intended rewrite from the table or gone. Zero references
to `_do_ingest`, `startup_thread`, `_reconcile_attempts`, `_reconcile_transient` may remain.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/ tests/
git add src/ormah/background/session_watcher.py src/ormah/main.py tests/
git commit -m "feat(ingest): always-on ingest worker; Observer and reconcile become optional producers (ADR-0004)"
```
