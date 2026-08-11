# LLM Cancellation Redesign — Single Global Epoch

**Date:** 2026-07-24
**Supersedes:** the cancellation model built incrementally across `/council-pr` R1–R7 on
`feat/adr-0004-slice2-bounded-shutdown` (head `16c4d5c`).
**Status:** design approved (Option A). Not implemented.

## Why this exists

ADR-0004 slice 2 ("bounded shutdown") went through seven council rounds. Roughly half the
findings were regressions introduced by the previous round's fix. The findings were not
independent bugs — they were four incarnations of one defect:

| Round | Finding | Incarnation |
|---|---|---|
| R3 | a SIGTERM-handling child exiting 0 had its partial output accepted | cancel state not consulted on the success path |
| R4 | `resume()` erased the cancel flag out from under an in-flight call | cancel state rolled back |
| R5 | torn read between `_cancel_generation` and `_cancel_event` | cancel state read non-atomically |
| R6 | a factory holding `_adapter_lock` across `get_adapter()` made the adapter invisible to the sweep | cancel state applied by enumerating a mutable cache |
| R7 | `cancel`/`resume` interleaving leaves `gate=False` with the adapter cancelled | cancel state mutated under lock, applied outside it |

**Root cause:** cancellation state lives in three places — the adapter's
`_cancel_event`/`_cancel_generation`, the facade's `_shutdown_started` gate, and the
watcher's implicit ownership of *when* to cancel — and every transition is two-phase
(mutate under a lock, then act outside it).

The two-phase shape is not incidental. `cancel_active()` does two things at once: it flips
a flag (cheap, pure) and it kills child processes (`p.wait(timeout=5)` per child, I/O). The
expensive half cannot hold `_adapter_lock` without stalling every thread that merely wants
an adapter, so R6's fix moved it outside — which is precisely what broke atomicity in R7.

## The design

**Separate the epoch (state) from the reaping (effect).**

A new module, `src/ormah/background/llm_cancel.py`, becomes the single authority. Nothing
else owns cancellation state.

```python
_lock = threading.Lock()
_epoch: int = 0          # monotonic; bumped on EVERY transition
_cancelled: bool = False # is the current epoch a cancelled one?
_final: bool = False     # a shutdown cancel; resume() must not undo it
```

### Transitions — one critical section, no action outside it

- `begin_cancel(*, final: bool) -> int` — under the lock: `_epoch += 1`, `_cancelled = True`,
  `_final |= final`. Returns the new epoch.
- `resume() -> int` — under the lock: if `_final`, no-op and return the current epoch;
  otherwise `_epoch += 1`, `_cancelled = False`.
- `begin_lifespan() -> int` — under the lock: `_epoch += 1`, `_cancelled = False`,
  `_final = False`. The only verb that clears `_final`.
- `snapshot() -> tuple[int, bool]` — under the lock: one tuple read of `(_epoch, _cancelled)`.
- `epoch_changed(gen: int) -> bool` — under the lock: `_epoch != gen`. Answers "was *this*
  call's era superseded?", which a later `resume()` cannot undo.
- `aborted(gen: int) -> bool` — under the lock: `_epoch != gen or _cancelled`. Both questions
  as ONE read. Used where both matter: admission after the semaphore (a waiter queued before
  the cancel must not spawn a replacement child) and the post-spawn re-check. Reading
  `epoch_changed()` and `snapshot()[1]` separately would reintroduce exactly the torn read
  that R5 was.
- `note_call_started()` / `note_call_finished()` / `in_flight()` — a counter under the same
  lock, so `begin_cancel()` can return how many calls it invalidated. This preserves the
  observability of today's `cancel_active_llm_calls() -> int` (the watcher logs the count);
  without it, dropping the process registry would silently delete a working affordance.

Both mutating verbs write *every* field inside *one* critical section and perform no work
outside it. Concurrent transitions therefore serialize into a total order and the final
state is that of whichever took the lock last. There is no mixed state to observe.

### The adapter becomes a pure epoch consumer

`ClaudeCliAdapter` loses `_cancel_lock`, `_cancel_generation`, `_cancel_event`, `_active_lock`
and its tracked-process registry. `generate()` becomes:

1. `gen, cancelled = llm_cancel.snapshot()` at entry — if `cancelled`, raise
   `LlmCancelledError` before spawning anything.
2. Spawn, capturing `pgid` at spawn time (unchanged — this is what bounds the `setsid`
   grandchild).
3. The bounded poll loop (`_CANCEL_POLL_INTERVAL = 0.5`) checks
   `llm_cancel.epoch_changed(gen)`; on change, `killpg` + `wait()` + raise `LlmCancelledError`.
4. The final gate re-checks `epoch_changed(gen)` before accepting output, so a child that
   handled SIGTERM and exited 0 still never has its partial output accepted (the R3 fix,
   preserved).

**The kill happens on the owning thread**, which is where it already happens today. That is
what preserves the measured `setsid` bound (19.55s → 0.50s) and what makes cancellation
cost nothing at the caller: `cancel` is now a single integer bump.

### Consequences

`cancel_active_llm_calls()` reduces to `llm_cancel.begin_cancel(final=...)`. It no longer
traverses the adapter cache, holds no lock during I/O, and needs no
`_cancel_newborn_if_shutting_down`. `_shutdown_started`, `_snapshot_adapters()` and the
per-adapter `cancel_active`/`resume` protocol are deleted.

The `while any(w.handler.drain_alive())` loop in `_stop_and_drain` (`session_watcher.py:1587`)
keeps its role as the **join fence** but stops re-cancelling on every turn. Its repeated cancel
existed for HIGH-C (council R2): to reach an adapter built *after* the first pass. A globally-read
epoch removes that reason — a late-built adapter reads the cancelled epoch at `generate()` entry.
The implementer should not preserve the repeated cancel as dead complexity.

What this closes **by construction**, not by patch:

- **R4** — `resume()` bumps the epoch too, so an in-flight call from the cancelled era still
  sees `epoch_changed` and aborts. Cancellation is never rolled back for a call already in
  flight; only the admission policy for *new* calls changes.
- **R5** — one tuple, one lock. A torn read is not expressible.
- **R6** — there is no cache traversal. A newly built adapter reads the same global epoch at
  `generate()` entry, so an adapter cannot be invisible to a cancel.
- **R7 HIGH-1** — one critical section, zero action outside it.

## Ownership: who cancels, and when

**R7 HIGH-2 is a boundary error, not an implementation bug.** Global LLM cancellation is
currently reachable only through `stop_session_watcher()`, which `main.lifespan` guards with
`if hasattr(app.state, "session_watches")` (`main.py:302`). When `start_session_watcher()`
raises, that attribute is never assigned, the guard skips the call, and nothing cancels — so
a scheduler-owned maintenance LLM call runs to its full provider timeout. The scheduler is an
independent consumer of LLM calls; it must not depend on the watcher's lifecycle.

New ownership:

| Call site | Verb | Notes |
|---|---|---|
| `main.lifespan` startup (replaces `resume_llm_adapters()` at `main.py:202`) | `begin_lifespan()` | new lifespan = clean world; the only clearer of `_final` |
| `main.lifespan` shutdown, **unconditional**, before the `session_watches` guard | `begin_cancel(final=True)` | the fix for R7 HIGH-2 |
| `_stop_and_drain(rearm=False)` (normal shutdown) | `begin_cancel(final=True)` | idempotent with the above |
| `_stop_and_drain(rearm=True)` (startup rollback) | `begin_cancel(final=False)` then `resume()` | the process keeps serving; adapters must not stay dead |
| `llm_client.reset_adapter()` (test isolation) | `begin_lifespan()` | same clean-world semantics |

`final` binds to `rearm`: whoever is not going to re-arm cancels definitively.

### Verified risk: `_final` must not be process-global-permanent

The `llm_client` adapter caches are module-level and outlive a single lifespan — the repo
already exercises consecutive lifespans in-process (`main.py:196-199` documents this). A
`_final` that only `resume()` could not clear would leave the *second* lifespan with every
LLM call raising `LlmCancelledError` for the life of the process. This is why the design has
**two distinct clearing verbs**: `resume()` (rollback; honours `_final`) and
`begin_lifespan()` (startup; clears it). A single `resume()` verb would have shipped this bug.

Confirmed by inspection: the only production callers of `resume_llm_adapters()` are
`main.py:202` (lifespan startup) and `session_watcher.py:1608` (rollback). No other path
depends on resuming after a shutdown has begun.

## Acceptance criteria

The design is correct if these pass **without the implementation targeting them individually**:

1. `repro-torn-generation-race.py` (R5, already reproduced) — promoted to a regression test.
2. `repro-cache-boundary-cancel-gap.py` (R6, already reproduced) — promoted to a regression test.
3. **New:** R7 HIGH-1 — concurrent `begin_cancel()` / `resume()` never yields a state where the
   admission gate is open while an in-flight call is cancelled, in either interleaving.
4. **New:** R7 HIGH-2 — `start_session_watcher()` raising during lifespan startup still results
   in `begin_cancel(final=True)` running at shutdown.
5. **New:** two consecutive lifespans in one process — the second can complete an LLM call
   after the first shut down with `final=True`.
6. Existing suite at baseline: 2029 passed, 6 pre-existing environmental failures in
   `tests/test_setup.py`, no new ruff errors.

Race tests use `threading.Event` barriers, never `sleep` — a timing-dependent race test is
not evidence.

## Out of scope

- Merging to the Beta. Slice 2 remains unmerged; a merge needs André's explicit GO.
- Porting the ADR text, and rollout.
- Cancellation for non-`claude_cli` providers. They remain bounded only by their own HTTP
  timeouts, as today — the epoch is available to them but no adapter is being changed here.

## Known risks

- The epoch is **global**, not per-consumer. A cancel from any consumer aborts every in-flight
  call. That matches today's behaviour and the shutdown use case, but it means there is no way
  to cancel only ingest while maintenance keeps running. Accepted; a per-scope epoch is a
  later refinement if a use case appears.
- A call blocked outside the poll loop (inside `subprocess.Popen()` construction, or between
  `communicate()` returning and the final gate) is not interruptible. Both windows are short
  and bounded; the only previously-unbounded blocker was `communicate()`, which the poll loop
  already covers.
- The claim "R3–R7 close by construction" is an argument from the design, verified against the
  two reproductions I already have. Criteria 3–5 are the ones that would falsify it, and they
  are not yet written.
