# Task 1: Always-on Ingest worker — Observer/reconcile become optional producers

**Files:**
- Modify: `src/ormah/background/session_watcher.py:1279-1425` (`SessionWatch`,
  `start_session_watcher`, `stop_session_watcher`, `run_session_reconcile`)
- Modify: `src/ormah/main.py:244-253` (lifespan wiring) AND `main.py:282-283` (shutdown —
  ⚠️ council R1: it reads `app.state.session_watcher_observers` today; MUST migrate to the
  same attribute the startup writes, or `stop_session_watcher` never runs → use-after-close)
- Test: `tests/test_background/test_session_watcher.py`, `tests/test_main_lifespan_shutdown.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `start_session_watcher(engine) -> list[SessionWatch]` — SAME name/signature, new
    semantics: always builds `SessionHandler` + startup-drain thread per watch dir;
    attaches a watchdog `Observer` ONLY when `settings.session_watcher_enabled` is true.
  - `SessionWatch.observer: Observer | None` (was always an Observer).
  - `app.state.session_watches: list[SessionWatch]` set in lifespan (Task 4's endpoint
    reads it to find the handler for a nudged path).
- **Invariant preserved:** one cursor (`<watch_dir>/.session_watcher_state`), one in-flight
  guard (`SessionHandler._ingesting`), regardless of the enabled flag. The startup drain
  (`_run_startup_reconcile` L1287) runs for EVERY install — it is the ADR's crash-recovery
  path ("Cursor behind EOF → re-enqueue").

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
    assert watches[0].startup_thread is not None
    stop_session_watcher(watches)  # must not raise with observer=None


def test_observer_attached_only_when_enabled(tmp_path):
    """enabled=True keeps today's behavior: Observer scheduled and alive."""
    watches = start_session_watcher(engine_stub_enabled)
    assert watches[0].observer is not None and watches[0].observer.is_alive()
    stop_session_watcher(watches)


def test_disabled_reconcile_ignores_never_seen_transcripts(engine, tmp_path):
    """council R7/R8 consent boundary: with session_watcher_enabled=False the sweep is
    recovery-only. A transcript nobody nudged (no state entry) must NEVER be ingested,
    while one that HAS an entry (a nudge) still is."""
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
        handler = watches[0].handler
        handler.nudge(nudged)                      # the user's own hook asked for this one
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            handler.reconcile()
        state = _load_state(watch_dir)
        assert str(nudged.relative_to(watch_dir)) in state
        assert str(never_seen.relative_to(watch_dir)) not in state, \
            "a disabled watcher must not discover transcripts nobody asked for"
    finally:
        stop_session_watcher(watches)


def test_disabled_reconcile_ignores_appends_to_an_already_known_transcript(engine, tmp_path):
    """council R9 — the transition case the previous test misses. After a nudged
    transcript is fully ingested (cursor reached boundary_target), APPENDING more turns must
    NOT be picked up by reconcile while the watcher is off: the user disabled automatic
    watching, so new content needs a new boundary nudge."""
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
        handler = watches[0].handler
        handler.nudge(jsonl)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            handler.reconcile()
        first_offset = _load_state(watch_dir)[rel]["end_offset"]
        assert first_offset > 0
        assert _load_state(watch_dir)[rel]["end_offset"] >= _load_state(watch_dir)[rel]["boundary_target"]

        _make_jsonl(jsonl, user_turns=12)          # the session grew; nobody nudged
        _mark_idle(jsonl)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as llm:
            handler.reconcile()
            assert not llm.called, "a disabled watcher must not ingest un-nudged growth"
        assert _load_state(watch_dir)[rel]["end_offset"] == first_offset
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
            handler = SessionHandler(...)  # unchanged args, always
            observer = None
            if enabled:
                observer = Observer()
                observer.schedule(handler, str(watch_dir), recursive=True)
                observer.start()
            startup_thread = Thread(...)   # unchanged, always
            startup_thread.start()
            watches.append(SessionWatch(watch_dir=watch_dir, handler=handler,
                                        observer=observer, startup_thread=startup_thread))
            logger.info("Ingest worker started on %s (observer=%s)", watch_dir, bool(observer))
```

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
   `if w.observer is not None`; the trailing `total += w.handler.reconcile()` stays
   unconditional (a caller who invokes it wants a sweep — main.py still gates the periodic job).

- [ ] **Step 4: Implement — main.py lifespan (start AND stop, one attribute)**

Read `main.py:240-290` before editing. Then:

1. Startup (L244-253): call `start_session_watcher(engine)` unconditionally and assign the
   result to **`app.state.session_watches`** — the ONE canonical attribute (Task 4's
   endpoint and the shutdown both read it).
2. **Periodic reconcile job: register ALWAYS, but pass the SCOPE** (council R1 + R7). The
   startup drain is bounded (`session_watcher_reconcile_max_per_tick=50`,
   `_max_seconds=30.0`), so without the periodic sweep a backlog beyond the cap — or a
   nudge lost mid-flight — strands until restart. BUT with `session_watcher_enabled=False`
   the sweep must be **recovery-only**: `SessionHandler.reconcile()` (L1161) takes a new
   `discover: bool`. When False it must NOT walk the tree at all: instead of
   `self.watch_dir.rglob("*.jsonl")` (L1188), iterate `self._state.keys()` and consider
   ONLY entries with unfinished explicit intent — i.e. `end_offset < boundary_target`
   (Task 2). Two reasons, both load-bearing:
   - **Consent (council R9).** "Has a state entry" is too broad: once a transcript has
     been nudged once — or was tracked before the flag was turned off — every later append
     leaves its cursor behind EOF, so reconcile would keep ingesting new content nobody
     asked for, and ship it to a remote extractor. Only an explicit boundary intent counts.
   - **Cost.** `rglob` runs on every tick for every install; the 30s budget caps
     `_do_ingest`, not the scan (L1185-1230). Iterating the state dict makes the disabled
     path proportional to pending work instead of to the size of `~/.claude/projects`.

   ⚠️ **Wire the scope on ALL THREE reconcile call sites** (council R8 — a `discover=True`
   default silently re-opens the consent hole on the path that runs FIRST):
   - `SessionHandler.__init__` takes and stores `discover` (passed in from
     `start_session_watcher`, which already knows `s.session_watcher_enabled`), and
     `reconcile()` defaults to `self.discover`, never to a bare `True`;
   - `_run_startup_reconcile` (L1287) therefore inherits it — the startup drain is the
     first thing to run after an upgrade, so it must not discover on a disabled install;
   - `run_session_reconcile` (L1398) likewise calls `w.handler.reconcile()` with no override.
   Without this, upgrading silently starts ingesting the transcripts of every user who
   deliberately turned the watcher off — a consent change, not a feature. Only the OBSERVER is gated by `session_watcher_enabled`; the
   reconcile sweep is the durable recovery producer for every install. If the scheduler
   is absent (startup failure path, `main.py:210-211`), log
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
Expected: PASS. Two EXISTING tests encode the old contract and MUST be rewritten
(council R5 — they will fail, and silently deleting them would drop real coverage):

- `test_disabled_returns_empty` (test_session_watcher.py:1147) — asserts `== []` when
  disabled. New contract: one watch, `observer is None`, handler live. Rename to
  `test_disabled_yields_worker_without_observer`.
- `test_nonexistent_watch_dir` (test_session_watcher.py:1181) — asserts `== []` for a
  missing dir. New contract: the root is created and a handler exists (that is the
  point of council R4's finding). Rename to `test_absent_watch_dir_is_created`.

Then `grep -rn "session_watcher_enabled\|start_session_watcher" tests/` and update any
other caller of the old contract.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/ tests/
git add src/ormah/background/session_watcher.py src/ormah/main.py tests/
git commit -m "feat(ingest): always-on ingest worker; Observer and reconcile become optional producers (ADR-0004)"
```
