# ADR-0004 Slice 2 — Bounded shutdown: cancel in-flight extractions

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans. Each task is its own file; steps use checkboxes.

**Goal:** Make server shutdown finish promptly again. Slice 1 made the ingest worker
always-on, so `stop_session_watcher`'s (deliberately uncapped) drain now waits on a running
`claude -p` extraction for **every** install — up to `claude_cli_timeout_seconds`
(~40 min at the Beta's sizing). Fix the cause, not the symptom: cancel the child process,
keep the drain uncapped.

**Why cancelling is safe:** a killed extraction never advances the cursor, so the slice is
simply re-ingested by the next startup drain. Durability comes from the cursor, which is
exactly what ADR-0004 established — no durable job table needed.

**Tech Stack:** Python 3.11, `subprocess.Popen`, threading, pytest.

## ⚠️ Refreshed 2026-07-23 — re-verified against the MERGED slice 1

This plan's original anchors were verified at `66405d9`, **before** slice 1 merged into the
Beta (merge `7cd15cb`). Slice 1 reworked exactly the shutdown/worker/adapter seams this slice
touches. Every anchor below was re-verified against the merged `local-main`. What changed:

- **The shutdown wait moved.** There is no longer a `startup_thread` join. The startup
  discovery sweep is a daemon thread (`session_watcher.py:1478-1481`). The uncapped wait is
  now **`SessionWatch.handler.join_drain()`** (`stop_session_watcher` L1538-1539, "waits out
  the one running ingest") followed by `_drain_handlers` polling `in_flight_count()` (L1507).
  `cancel_active_llm_calls()` must fire **after `_stop_event.set()` + `wake()`, before
  `join_drain()`** — see Task 2.
- **The R1 `app.state.session_watches` fix already landed in slice 1** (`main.py:250` at
  startup, `main.py:293-294` at shutdown). It is NO LONGER part of this slice's scope; only
  the `resume_llm_adapters()` startup call remains a Task-2 change to `main.py`.
- **🔴 CRITICAL — a per-slice failure cap now exists, and a naive cancel would burn it.**
  Slice 1 added `_ingest_session._record_extract_failure` (`session_watcher.py:947-1001`):
  after `MAX_EXTRACT_FAILURES` failures at the same byte offset it **advances the cursor past
  the slice and records `skipped_slices` — observable data loss** (L981-991). The adapter
  today NEVER raises (it returns `None`); this slice makes it **raise** `LlmCancelledError`.
  That exception propagates through `ingest_llm_generate` → is caught by
  `_extract_memories_llm`'s broad `except Exception` (`memory_engine.py:2903`) → returns the
  **generic** "LLM extraction failed" string (NOT `EXTRACT_ERR_CALL_FAILED`) → passed through
  by `ingest_conversation` (L2701-2702) → `_ingest_session` L1044 routes any non-sentinel
  string to `_record_extract_failure`. **Net effect: N restarts during the same slice's
  extraction would SKIP that healthy slice.** This voids the original plan's claim that a
  cancel routed through the broad handler is "acceptable for now because nothing consumes a
  per-slice failure budget yet" — that budget now exists. **The fix is mandatory and ships in
  Task 2:** `_extract_memories_llm` must catch `LlmCancelledError` and return
  `EXTRACT_ERR_CALL_FAILED` (provider-wide transient → `IngestResult.TRANSIENT` → requeue, no
  cap) BEFORE the generic handler. This is what makes the slice's own safety claim ("a killed
  extraction never advances the cursor") actually true under the merged code.
- **The adapter already has a shared concurrency semaphore** (`_semaphore(self.max_concurrency)`
  `claude_cli_adapter.py:134`) — the original plan already anticipated it (the
  semaphore-waiter test), and the `subprocess.run` anchor (L137-140) is still exact. The
  Popen migration must also preserve `_cleanup_persisted_stub(...)` (L157).
- **The seed patch is superseded.** `seed/task2-implementer-shutdown-cancel-seed.patch`
  predates slice 1 and is about `start_scheduler(stop_event=...)` + backfill-thread join —
  all of which already landed in slice 1 (`main.py:198,205`; `scheduler.shutdown(wait=True)`).
  It is NOT the LLM-cancellation change this slice delivers. Ignore or delete it.

The design principles from the council review (below) all survive; only the wiring moved and
the cap finding was added.

## Prerequisite

**Slice 1 must be merged first** (`../2026-07-21-adr-0004-slice1-nudge-core/`). This slice
exists because of it — and it IS now merged (`7cd15cb`), so this slice is unblocked and
ready. If slice 1 had slipped, this one would be optional — the unbounded wait then only
affects watcher-enabled installs, as it always has.

Slice 3 (`../2026-07-21-adr-0004-slice3-timeout-quarantine/`) builds on the error module
this slice creates, but does not otherwise depend on it.

## Global Constraints

- **Never checkout a branch in `Tools/ormah`** — it is the live Beta. Work in a worktree
  cut from `local-main`; run tests with that worktree's venv.
- **Beta-only.** `src/ormah/background/llm/` (the `claude_cli` adapter) does not exist in
  `upstream/main` — verified 2026-07-21. Nothing here is cherry-picked upstream.
- **Out of scope:** extraction-failure classification and quarantine (slice 3); worker
  concurrency (#150).
- Lint: `ruff check src/ tests/` (line-length 100, py311).

## Design decisions carried from the council review (all findings accepted)

- **Cancellation is NOT a timeout.** It raises its own `LlmCancelledError`, which the
  ingest path treats as a provider-wide transient failure. A cancel says nothing about the
  slice being processed, so repeated restarts must never be able to burn a per-slice
  failure budget. (This matters even before slice 3 exists — it is why the two exception
  types are introduced together, in one module.)
- **Cancellation state is INSTANCE-scoped, never a module global.** `main.lifespan` catches
  a watcher startup failure and keeps serving, and nothing calls `reset_adapter()` on
  startup, so a module-level "cancelled" flag would survive and poison every later ingest
  AND maintenance call for the life of the process.
- **Normal shutdown must be undone at the next startup.** The `llm_client` adapter caches
  are module-level and outlive an in-process lifespan restart (the repo already tests
  consecutive lifespans), so this slice ships `resume_llm_adapters()` AND its
  lifespan-startup call in the same commit.
- **Order matters more than the cancel itself.** (Anchors refreshed for merged slice 1.)
  `stop_session_watcher` (`session_watcher.py:1523`) sets `_stop_event`, stops observers,
  cancels timers and `wake()`s the drain, then **`join_drain()` (L1538-1539)** — the uncapped
  wait on the running extraction — then `_drain_handlers` (L1540) polls `in_flight_count()`.
  There is no `startup_thread` join anymore. Cancellation must fire **after `wake()`, before
  `join_drain()`**, and the **transactional startup-rollback block (L1487-1503) must use the
  same sequence** — with several watch roots, an Observer failure on root 2 while root 1 is
  mid-extraction would otherwise `join_drain()`-wait out the whole budget. Because the two
  blocks are now near-identical, extract one `_stop_and_drain(watches)` helper and call it
  from both.
- **🔴 A cancel must NOT count against the per-slice failure cap** (new, merged-slice-1 only).
  `_ingest_session` skips a slice after `MAX_EXTRACT_FAILURES` (`session_watcher.py:947-1001`).
  A raised `LlmCancelledError` reaching `_extract_memories_llm`'s generic handler
  (`memory_engine.py:2903`) becomes a non-sentinel error string → counts toward that cap →
  data loss on repeated restarts. Task 2 adds `except LlmCancelledError: return
  EXTRACT_ERR_CALL_FAILED` in `_extract_memories_llm`, mapping cancel → provider-wide
  transient → requeue, no cap. See the CRITICAL note in the refresh section above.
- **A missing binary must stay a fast failure.** Constructing the `Popen` inside its own
  `try` is load-bearing: a `FileNotFoundError` escaping into the engine's broad handler
  would be classified as a slice-specific error and (once slice 3 lands) could quarantine
  real data.
- **Late-built adapter: closed deterministically (was "residual").** An adapter built *after*
  the cancellation snapshot is not cancelled by that pass. Council 2026-07-23 (Codex HIGH-C)
  rejected "document the residual" — `_stop_and_drain` now loops `cancel + join_drain(timeout)`
  until every drain thread exits, so a late adapter is killed on the next iteration. See the
  Council-round note below.

## Council round on the refresh (2026-07-23, R1 — cursor + codex, all findings accepted)

Both peers confirmed the core (cancel + Step 3b cap mapping) is correct and verified in the
merged code. Neither approved clean; 3 HIGH accepted as implementation blockers, folded into
Tasks 2/3:

- **HIGH-A (Cursor)** — `_stop_and_drain` (shared shutdown+rollback) must `resume_llm_adapters()`
  on the ROLLBACK path only (the process keeps serving; the scheduler is already live), never on
  normal shutdown. → `_stop_and_drain(watches, *, rearm=False)`.
- **HIGH-B (Codex)** — rollback must OWN the root it is constructing: `start_drain()` runs before
  `observer.start()` but the `SessionWatch` is appended only after, so an `observer.start()`
  failure strands a draining handler outside `watches` → post-close DB access (#52). → register a
  provisional `SessionWatch` before `observer.start()`.
- **HIGH-C (Codex)** — a single timed second cancel pass does not bound a late-built adapter. →
  deterministic fence loop `while any drain alive: cancel; join_drain(timeout)`.
- Plus **MEDIUM (Codex)**: keep a provider timeout returning `None` in this slice (raising
  `LlmTimeoutError` now would re-open the cap burn); **MEDIUM (Cursor)**: snippet indentation;
  **LOW (Cursor)**: test-name fix. Full record: `$COUNCIL_HOME/council-result.md`
  (run 66405d98-7cd15cb5-e20eaa87).

## Task Map

| # | File | Delivers | Depends on |
|---|------|----------|------------|
| 1 | `01-cancel-seam.md` | `llm_errors.py` with `LlmCancelledError`/`LlmTimeoutError`; `llm_generate` swallows both | — |
| 2 | `02-shutdown-cancellation.md` | Tracked `Popen` + `cancel_active()`/`resume()`; dispatchers; `_stop_and_drain` helper (stop ordering + rollback parity); 🔴 `_extract_memories_llm` maps cancel → `EXTRACT_ERR_CALL_FAILED` (no cap burn); `resume_llm_adapters()` at startup | 1 |
| 3 | `03-verification.md` | Suite green, restart timing evidence, Beta merge | 1-2 |

## Key Anchors (RE-VERIFIED 2026-07-23 on merged local-main, post-`7cd15cb`)

- Adapter: `src/ormah/background/llm/claude_cli_adapter.py` — `generate()` L104-172,
  `self.max_concurrency` L102, `sem = _semaphore(self.max_concurrency)` L134 + `with sem:`
  L135, `subprocess.run` L137-140 (✅ still exact), `except subprocess.TimeoutExpired`
  L141-143, generic `except Exception` L144-146, non-zero exit L147-149,
  `_cleanup_persisted_stub(...)` L157 (⚠️ preserve across the Popen migration),
  schema/`structured_output` fallback L161-172.
- LLM boundary: `src/ormah/background/llm_client.py` (✅ all anchors unchanged) —
  `_cached_adapter` L57, `_cached_ingest_adapter` L60, `reset_adapter` L64,
  `_get_or_create_adapter` L73, `_get_or_create_ingest_adapter` L89,
  `ingest_llm_generate` L101-107 (propagates by construction), `llm_generate` L119-140
  (adapter call L133-140).
- Ingest classification (🔴 the cap): `src/ormah/background/session_watcher.py` —
  `_ingest_session` L792, `_record_extract_failure` L947-1001 (per-slice cap;
  `MAX_EXTRACT_FAILURES`; skip-forward + `skipped_slices` L959-991), the two provider-wide
  sentinels → TRANSIENT L1040-1043, non-sentinel string → `_record_extract_failure` L1044,
  broad ingest-exception → `_record_extract_failure` L1023-1031.
- Engine extraction: `src/ormah/engine/memory_engine.py` — `EXTRACT_ERR_NO_PROVIDER` L54,
  `EXTRACT_ERR_CALL_FAILED` L58, `ingest_conversation` L2680 (string passthrough L2701-2702),
  `_extract_memories_llm` L2842 (adapter call L2861, `raw is None` → CALL_FAILED L2868-2886,
  🔴 generic `except Exception` → generic string L2903-2908 ← ADD the `LlmCancelledError`
  catch here).
- Always-on worker + shutdown: `src/ormah/background/session_watcher.py` — `_drain_forever`
  L1180 (loop `while not self._stop_event.is_set()`; per-job `except` requeue L1201-1216),
  `_ingesting_guard` L1218-1229, `_run_job` L1231 (stop-check L1235, TRANSIENT→requeue
  L1253-1256), `wake` L1172, `start_session_watcher` L1434 (`handler.start_drain()` L1470;
  daemon discovery thread L1478-1481; transactional rollback L1487-1503 with `join_drain`
  L1497-1498), `_drain_handlers` L1507-1520 (uncapped `in_flight_count()` poll),
  `stop_session_watcher` L1523-1545 (`_stop_event.set()` L1531-1532; observer/timers/`wake`
  L1533-1537; ⚠️ `join_drain()` L1538-1539 — the uncapped wait; `_drain_handlers` L1540).
- Lifespan: `src/ormah/main.py` — `lifespan` L186, `engine.startup()` L191 (insert
  `resume_llm_adapters()` right after, before scheduler/watcher start), session watcher start
  L246, `app.state.session_watches` set L250, shutdown reads it L293-294 (✅ R1 fix already
  merged — no longer this slice's job).
- Tests: `tests/test_background/test_claude_cli_adapter.py` — grep `subprocess.run` for the
  patch sites that must migrate to a fake `Popen` (line numbers shifted; verify at impl time).
  `tests/test_main_lifespan_shutdown.py` — the double-lifespan pattern (grep for the second
  `async with`); `tests/test_background/test_session_watcher.py` for the cap/skip regressions
  (`_record_extract_failure` neighbours ~L2232+).

## Rollout note

After merge, measure the win: restart the Beta while an extraction is running
(`launchctl kickstart -k gui/501/com.ormah.server.dev`) and confirm the process exits in
seconds rather than minutes. That timing IS the acceptance evidence for this slice.
