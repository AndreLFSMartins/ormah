# LLM Cancellation Epoch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-place, two-phase LLM cancellation model with a single global monotonic epoch, so the non-atomicity defect that produced findings in council rounds R3–R7 becomes inexpressible.

**Architecture:** A new module `llm_cancel.py` is the sole authority for cancellation state. Every transition writes all its fields inside one critical section and performs no work outside the lock. The adapter becomes a pure epoch *consumer* — it reads the epoch and kills its own child from its own thread. Process killing stops being a cross-thread sweep over an adapter cache and becomes an in-thread effect, which is what lets the state transition be atomic.

**Tech Stack:** Python 3.11+, `threading`, `subprocess`, pytest (`asyncio_mode = auto`).

**Spec:** [`docs/superpowers/specs/2026-07-24-llm-cancel-epoch-design.md`](../specs/2026-07-24-llm-cancel-epoch-design.md)

## Global Constraints

- **Worktree:** all work happens in `/Users/andre/Documents/GitHub/Tools/ormah-wt-adr4-s2` on branch `feat/adr-0004-slice2-bounded-shutdown`. Never in the main clone (`Tools/ormah` is the live Beta).
- **Never merge to the Beta.** No `git merge`, no push to `local-main`. A merge requires André's explicit GO.
- **Race tests use `threading.Event` / `threading.Barrier` barriers, never `sleep`.** A timing-dependent race test is not evidence and will be rejected in review.
- **Lint:** ruff, `target-version = py311`, `line-length = 100`. Run `ruff check src/ tests/` before every commit.
- **Test baseline:** 2029 passed, 6 pre-existing environmental failures in `tests/test_setup.py`, 4 pre-existing ruff errors. Any *new* failure or ruff error is a regression.
- **Fast suite:** `python -m pytest tests/ -q` (the `integration` marker is excluded by default via `addopts`).
- **Python:** use the worktree venv interpreter, `/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python`, with `PYTHONPATH=src` when running scripts directly.
- Every state-mutating function in `llm_cancel.py` must write **all** of its fields inside **one** `with _lock:` block and must perform **no** work (no I/O, no callbacks, no process signalling) inside or after the lock. This is the invariant the whole redesign rests on.
- **Lifespan is serial (precondition, from council R1 HIGH-3).** A single uvicorn app runs one lifespan startup then one shutdown, strictly serialized by the ASGI contract — never two overlapping in the same process. The process-global epoch is safe under exactly this precondition. We do NOT add a per-lifespan ownership token (that would re-introduce the per-entity state coupling this redesign exists to remove); instead we keep the assumption explicit and keep `reset_adapter()` (test-only) decoupled from lifecycle state. If ormah ever runs two app instances in one process, revisit this.
- **Admission and accounting live at the facade seam (council R1 HIGH-2 + Cursor #1), not inside one adapter.** `llm_generate` / `ingest_llm_generate` gate admission and reject cancelled-era output for EVERY provider; only the subprocess kill (poll-loop + spawn race) is claude-specific. Mid-flight interruption of Ollama/LiteLLM stays out of scope — they remain bounded by their own HTTP timeout, unchanged from today — but they no longer return stale output produced after a cancel.

---

## Setup (before Task 1)

- [ ] Copy the design spec into the worktree so implementers see the source of truth (`docs/superpowers/` is gitignored, so it is not carried by the branch):

```bash
cp /Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/specs/2026-07-24-llm-cancel-epoch-design.md \
   /Users/andre/Documents/GitHub/Tools/ormah-wt-adr4-s2/docs/superpowers/specs/2026-07-24-llm-cancel-epoch-design.md
```

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/ormah/background/llm_cancel.py` | **New.** The sole authority for cancellation state: the epoch, the cancelled flag, the final flag, the in-flight counter. Pure state, zero I/O. |
| `src/ormah/background/llm/claude_cli_adapter.py` | **Modify.** Loses all cancellation state; becomes an epoch consumer that kills its own child in-thread. |
| `src/ormah/background/llm_client.py` | **Modify.** The facade's `cancel_active_llm_calls` / `resume_llm_adapters` delegate to `llm_cancel`; the shutdown gate and adapter-cache sweep are deleted. |
| `src/ormah/main.py` | **Modify.** Owns the lifespan transitions: `begin_lifespan()` at startup, unconditional `begin_cancel(final=True)` at shutdown. |
| `src/ormah/background/session_watcher.py` | **Modify.** `_stop_and_drain` keeps its join fence, stops re-cancelling per turn. |
| `tests/test_background/test_llm_cancel.py` | **New.** Epoch semantics and linearizability. |
| `tests/test_background/test_claude_cli_adapter.py` | **Modify.** Adapter tests moved onto the epoch; the R5 repro promoted to a regression. |
| `tests/test_background/test_llm_client.py` | **Modify.** Facade tests; the R6 repro promoted to a regression. |
| `tests/test_main_lifespan_shutdown.py` | **Modify.** R7 HIGH-2 (watcher startup failure) and consecutive lifespans. |

---

### Task 1: The epoch module

Nothing depends on this yet, so it lands standalone and green.

**Files:**
- Create: `src/ormah/background/llm_cancel.py`
- Test: `tests/test_background/test_llm_cancel.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `begin_cancel(*, final: bool) -> int` — returns the number of in-flight calls invalidated
  - `resume() -> int` — returns the current epoch
  - `begin_lifespan() -> int` — returns the new epoch
  - `snapshot() -> tuple[int, bool]` — `(epoch, cancelled)`
  - `epoch_changed(gen: int) -> bool`
  - `aborted(gen: int) -> bool`
  - `note_call_started() -> None`, `note_call_finished() -> None`, `in_flight() -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background/test_llm_cancel.py`:

```python
"""Epoch semantics for LLM cancellation (ADR-0004 slice 2 redesign).

These tests encode the invariant that seven council rounds failed to hold: the cancel
state is written AND read atomically, and no interleaving of transitions produces a
state that no single transition could have produced.
"""
import threading

import pytest

from ormah.background import llm_cancel


@pytest.fixture(autouse=True)
def _clean_epoch():
    llm_cancel.begin_lifespan()
    yield
    llm_cancel.begin_lifespan()


def test_begin_cancel_bumps_the_epoch_and_marks_cancelled():
    gen, cancelled = llm_cancel.snapshot()
    assert cancelled is False
    llm_cancel.begin_cancel(final=False)
    new_gen, new_cancelled = llm_cancel.snapshot()
    assert new_gen != gen
    assert new_cancelled is True


def test_resume_bumps_the_epoch_so_an_in_flight_call_stays_cancelled():
    """R4 regression. A resume() re-admits NEW calls; it must never un-cancel a call
    already in flight."""
    gen, _ = llm_cancel.snapshot()
    llm_cancel.begin_cancel(final=False)
    llm_cancel.resume()
    _, cancelled = llm_cancel.snapshot()
    assert cancelled is False          # new calls are admitted again
    assert llm_cancel.epoch_changed(gen) is True   # the in-flight call still aborts


def test_resume_is_a_noop_after_a_final_cancel():
    llm_cancel.begin_cancel(final=True)
    llm_cancel.resume()
    _, cancelled = llm_cancel.snapshot()
    assert cancelled is True


def test_begin_lifespan_clears_final():
    """A final cancel must not outlive its lifespan: the llm_client adapter caches are
    module-level and a second lifespan runs in the same process."""
    llm_cancel.begin_cancel(final=True)
    llm_cancel.begin_lifespan()
    _, cancelled = llm_cancel.snapshot()
    assert cancelled is False


def test_a_final_cancel_is_never_reopened_by_a_concurrent_resume():
    """R7 HIGH-1 regression — the linearizability assertion.

    Whichever order the two transitions take, the settled state is the same:
      * resume first  -> it succeeds (final not yet set), then the final cancel lands;
      * cancel first  -> resume sees `final` and is a no-op.
    The old model could settle on "gate open + adapter cancelled" because the state was
    mutated under a lock but APPLIED outside it. Here there is nothing outside the lock.
    """
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def cancel():
        try:
            barrier.wait(timeout=5)
            llm_cancel.begin_cancel(final=True)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    def resume():
        try:
            barrier.wait(timeout=5)
            llm_cancel.resume()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=cancel), threading.Thread(target=resume)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive()
    assert not errors

    _, cancelled = llm_cancel.snapshot()
    assert cancelled is True, "a final cancel was reopened by a concurrent resume"


def test_aborted_is_one_atomic_read_of_both_questions():
    """R5 regression. `aborted` answers "is the world cancelled NOW, or was THIS call's
    era superseded?" — it must be one read, never two."""
    gen, _ = llm_cancel.snapshot()
    assert llm_cancel.aborted(gen) is False
    llm_cancel.begin_cancel(final=False)
    assert llm_cancel.aborted(gen) is True
    llm_cancel.resume()
    assert llm_cancel.aborted(gen) is True      # (b): our era is over
    fresh, _ = llm_cancel.snapshot()
    assert llm_cancel.aborted(fresh) is False   # a NEW call is admitted


def test_begin_cancel_reports_how_many_calls_it_invalidated():
    """The watcher logs this count; it replaces the old "processes terminated" number."""
    assert llm_cancel.in_flight() == 0
    llm_cancel.note_call_started()
    llm_cancel.note_call_started()
    assert llm_cancel.begin_cancel(final=False) == 2
    llm_cancel.note_call_finished()
    llm_cancel.note_call_finished()
    assert llm_cancel.in_flight() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-adr4-s2
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/test_background/test_llm_cancel.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'ormah.background.llm_cancel'`.

- [ ] **Step 3: Write the module**

Create `src/ormah/background/llm_cancel.py`:

```python
"""Single authority for LLM call cancellation (ADR-0004 slice 2 redesign).

Cancellation is a monotonic EPOCH, not a flag. Every transition bumps it inside ONE
critical section that writes every field, and performs NO work outside the lock — so
concurrent transitions serialise into a total order and no mixed state is observable.

That constraint is the whole design. The previous model split each transition into
"mutate state under a lock" + "apply it outside the lock", because applying it meant
killing child processes (`p.wait(timeout=5)` each) and that cannot hold a lock every
caller needs. Seven council rounds each found a different way for those two phases to
disagree.

Here the epoch is the STATE and killing a child is a separate EFFECT, performed by the
thread that owns the call (see ``ClaudeCliAdapter.generate``). Nothing in this module
does I/O, which is what lets every transition stay atomic.

Two distinct readings, both single atomic reads:
  * ``aborted(gen)``       — "is the world cancelled NOW, or was THIS call's era superseded?"
  * ``epoch_changed(gen)`` — "was THIS call's era superseded?" — immune to a later resume()
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_epoch: int = 0
_cancelled: bool = False
_final: bool = False
_in_flight: int = 0


def begin_cancel(*, final: bool) -> int:
    """Cancel the current epoch. Returns how many calls were in flight when it landed.

    ``final=True`` marks a shutdown cancel that ``resume()`` must not undo; only
    ``begin_lifespan()`` clears it.
    """
    global _epoch, _cancelled, _final
    with _lock:
        _epoch += 1
        _cancelled = True
        _final = _final or final
        return _in_flight


def resume() -> int:
    """Re-admit NEW calls after a RECOVERABLE cancel (the watcher's startup rollback).

    Bumps the epoch, so a call already in flight keeps observing the cancel that hit it —
    only the admission policy for new calls changes. A no-op after a final cancel.
    """
    global _epoch, _cancelled
    with _lock:
        if _final:
            return _epoch
        _epoch += 1
        _cancelled = False
        return _epoch


def begin_lifespan() -> int:
    """Start a clean era. The ONLY verb that clears ``final``.

    The llm_client adapter caches are module-level and outlive a single lifespan (the repo
    exercises consecutive lifespans in-process), so a final cancel that only ``resume()``
    could clear would leave the SECOND lifespan raising LlmCancelledError on every call for
    the life of the process.
    """
    global _epoch, _cancelled, _final
    with _lock:
        _epoch += 1
        _cancelled = False
        _final = False
        return _epoch


def snapshot() -> tuple[int, bool]:
    """This call's era AND whether the world is cancelled — from ONE critical section."""
    with _lock:
        return _epoch, _cancelled


def epoch_changed(gen: int) -> bool:
    """Was THIS call's era superseded? Immune to a later resume(), unlike ``snapshot()[1]``."""
    with _lock:
        return _epoch != gen


def aborted(gen: int) -> bool:
    """``epoch_changed(gen) or cancelled`` — as one atomic read, never two."""
    with _lock:
        return _epoch != gen or _cancelled


def note_call_started() -> None:
    global _in_flight
    with _lock:
        _in_flight += 1


def note_call_finished() -> None:
    global _in_flight
    with _lock:
        _in_flight = max(0, _in_flight - 1)


def in_flight() -> int:
    with _lock:
        return _in_flight
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/test_background/test_llm_cancel.py -q
ruff check src/ormah/background/llm_cancel.py tests/test_background/test_llm_cancel.py
```

Expected: 7 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/llm_cancel.py tests/test_background/test_llm_cancel.py
git commit -m "feat(shutdown): single-authority cancellation epoch"
```

---

### Task 2: Swap the adapter and the facade onto the epoch

**These two must land together.** The adapter's `cancel_active()`/`resume()` protocol and the facade's cache sweep are two halves of one contract — a reviewer cannot approve replacing one while the other still calls it, and landing either alone leaves the suite red.

**Files:**
- Modify: `src/ormah/background/llm/claude_cli_adapter.py`
- Modify: `src/ormah/background/llm_client.py`
- Test: `tests/test_background/test_claude_cli_adapter.py`, `tests/test_background/test_llm_client.py`

**Interfaces:**
- Consumes: everything Task 1 produces.
- Produces:
  - `llm_client.cancel_active_llm_calls(*, final: bool = True) -> int` (count of in-flight calls invalidated)
  - `llm_client.resume_llm_adapters() -> None`
  - `llm_client.begin_llm_lifespan() -> None`
  - `ClaudeCliAdapter` no longer has `cancel_active`, `resume`, `_cancel_event`, `_cancel_generation`, `_cancel_lock`, `_active_procs`, `_active_lock`, `_capture_era`, `_cancelled_since`, `_aborted`, `_cancel_tracked_procs`.

- [ ] **Step 1: Write the failing regression tests**

Append to `tests/test_background/test_claude_cli_adapter.py` (promotes the R5 reproduction — it currently lives as a scratch script at `/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah/29814784-0d46-4003-b29b-1765bff7b56b/scratchpad/adr4-s2/repro-torn-generation-race.py`):

```python
def test_a_cancelled_call_never_has_its_partial_output_accepted(monkeypatch):
    """R3 + R5 regression. A child that HANDLES SIGTERM and exits 0 emits partial
    buffered JSON. Accepting it made the engine advance the cursor on a cancelled
    extraction. The final gate must consult the epoch, not the return code."""
    from ormah.background import llm_cancel
    from ormah.background.llm import claude_cli_adapter as mod

    llm_cancel.begin_lifespan()
    adapter = mod.ClaudeCliAdapter(model="haiku", timeout=30)
    spawned = threading.Event()
    may_return = threading.Event()

    class _SigtermHandlingProc:
        returncode = 0
        pid = None

        def communicate(self, input=None, timeout=None):
            spawned.set()
            if not may_return.wait(timeout=5):
                raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)
            return json.dumps({"result": "PARTIAL buffered output"}), ""

        def terminate(self): pass
        def kill(self): pass          # handled the signal: returncode stays 0
        def wait(self, timeout=None): return 0
        def poll(self): return 0
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(mod, "_capture_pgid", lambda proc: None)
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: _SigtermHandlingProc())

    outcome: dict = {}

    def run():
        try:
            outcome["result"] = adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["raised"] = e

    t = threading.Thread(target=run)
    t.start()
    assert spawned.wait(timeout=5), "the child never spawned"
    llm_cancel.begin_cancel(final=True)
    may_return.set()
    t.join(timeout=10)
    assert not t.is_alive()

    assert "raised" in outcome, f"cancelled output was accepted: {outcome.get('result')!r}"
    llm_cancel.begin_lifespan()
```

Append to `tests/test_background/test_llm_client.py` (promotes the R6 reproduction from `.../scratchpad/adr4-s2/repro-cache-boundary-cancel-gap.py`):

```python
def test_an_adapter_built_during_a_shutdown_is_born_cancelled(monkeypatch):
    """R6 regression. A factory holds _adapter_lock across get_adapter(), and during that
    window the cache global is still None. The old sweep enumerated the cache, saw nothing,
    returned 0 — and the factory then published an UNCANCELLED adapter that spawned a child.

    HONEST fake (council R1 HIGH-2): the adapter does NOT read llm_cancel — real Ollama/LiteLLM
    adapters don't either. The FACADE seam is what rejects the call: `llm_generate` snapshots
    the epoch AFTER `_get_or_create_adapter` returns, so it observes the cancel that landed
    while the factory held _adapter_lock, and admission raises before the fake ever runs a
    cancelled call. This is exactly the provider-independent gate the old design lacked."""
    from ormah.background import llm_cancel, llm_client

    llm_client.reset_adapter()
    llm_cancel.begin_lifespan()

    in_factory = threading.Event()
    may_finish = threading.Event()

    class _FakeAdapter:
        def generate(self, *a, **kw):
            return "UNCANCELLED_SUCCESS"   # dumb adapter; the facade seam does the gating

    def slow_get_adapter(settings, provider=None, model=None):
        in_factory.set()
        may_finish.wait(timeout=5)      # holds _adapter_lock, as the real factory does
        return _FakeAdapter()

    monkeypatch.setattr(llm_client, "get_adapter", slow_get_adapter)

    class _S:
        llm_provider = "claude_cli"
        llm_model = "haiku"
        ingest_llm_provider = None
        ingest_llm_model = None

    result: dict = {}

    def first_call():
        result["out"] = llm_client.llm_generate(_S(), "hi")

    t = threading.Thread(target=first_call)
    t.start()
    assert in_factory.wait(timeout=5), "the factory never entered"

    llm_client.cancel_active_llm_calls()   # the shutdown lands exactly in the window
    may_finish.set()
    t.join(timeout=10)
    assert not t.is_alive()

    assert result.get("out") != "UNCANCELLED_SUCCESS", (
        "an adapter published during a shutdown ran an uncancelled call"
    )
    llm_client.reset_adapter()
```

Ensure both test modules import what they use at the top: `import json`, `import subprocess`, `import threading`, and `from ormah.background.llm_errors import LlmCancelledError`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_claude_cli_adapter.py::test_a_cancelled_call_never_has_its_partial_output_accepted \
  tests/test_background/test_llm_client.py::test_an_adapter_built_during_a_shutdown_is_born_cancelled -q
```

Expected: both FAIL. The adapter one fails because `generate()` still reads its own instance flag, which `llm_cancel.begin_cancel` does not touch, so the partial output is accepted. The facade one fails because `cancel_active_llm_calls()` still sweeps the cache and the epoch is never consulted by `_FakeAdapter`'s caller.

- [ ] **Step 3: Strip the cancellation state out of the adapter**

In `src/ormah/background/llm/claude_cli_adapter.py`:

Add the import near the other `ormah` imports:

```python
from ormah.background import llm_cancel
```

Replace the tail of `__init__` (the block from the `# ADR-0004 slice 2: instance-scoped` comment through `self._active_lock = threading.Lock()`) with nothing — the adapter holds no cancellation state at all. `__init__` ends at:

```python
        self.max_concurrency = max(1, max_concurrency)
```

Delete these methods entirely: `cancel_active`, `resume`, the `# --- cancel-state reads` comment block, `_capture_era`, `_cancelled_since`, `_aborted`, `_cancel_tracked_procs`.

- [ ] **Step 4: Rewire `generate()` onto the epoch**

Replace the era capture at the top of `generate()`:

```python
        # A call belongs to the era it ENTERED, not the era in which it happened to win the
        # semaphore: a waiter queued BEFORE a cancel is a call that cancel should reach.
        gen, shutting_down = llm_cancel.snapshot()
        if shutting_down:
            raise LlmCancelledError("llm call aborted: shutdown in progress")
```

Replace the post-semaphore admission check:

```python
        with sem:
            if llm_cancel.aborted(gen):
                # (a) is the world cancelled NOW — a waiter that acquired the semaphore after
                # the cancel must not spawn a replacement child. PLUS (b) did a cancel land while
                # we sat on the semaphore? A waiter from the previous era aborts even if a
                # resume() has since re-admitted new calls.
                raise LlmCancelledError("llm call aborted: shutdown in progress")
```

Replace the registration block (everything from `pgid = _capture_pgid(proc)` through the `raise LlmCancelledError` that followed it) with:

```python
            pgid = _capture_pgid(proc)  # snapshot NOW, while the group leader is alive
            if llm_cancel.aborted(gen):
                # A cancel that landed during Popen() construction: kill the newborn child
                # immediately rather than let the poll loop notice it a tick later. There is
                # no creation/registration race left to close — nothing kills our child from
                # another thread, so there is no cross-thread process set to miss it.
                _kill_group_or_proc(proc, pgid)
                with contextlib.suppress(Exception):
                    proc.wait()
                raise LlmCancelledError("llm call aborted: shutdown in progress")
```

The `with proc:` block and the old `finally:` that popped `_active_procs` both simplify: there is
no registry to pop and no per-adapter accounting here — in-flight accounting now lives at the
facade seam (Step 5). Remove the `self._active_procs.pop(...)` finally entirely; keep `with proc:`
exactly as it was so `__exit__` still reaps the child on every exit path.

**Accounting is NOT in the adapter (council R1 HIGH-2).** Do not call `llm_cancel.note_call_started`/
`note_call_finished` here — those wrap the adapter call at the facade so the in-flight count is
provider-independent. The adapter only reads the epoch to manage its own subprocess.

Inside the poll loop, replace the cancel check:

```python
                            if llm_cancel.epoch_changed(gen):  # (b) was THIS call cancelled?
```

Replace the final gate:

```python
        if (proc.returncode or 0) < 0 or llm_cancel.epoch_changed(gen):
```

Leave every surrounding comment that explains *why* each check exists — the reasons (R3 data integrity, the setsid grandchild, the CPython `communicate()` retry contract) are unchanged and still load-bearing. Only the mechanism moved.

- [ ] **Step 5: Rewrite the facade**

In `src/ormah/background/llm_client.py`:

Add the import:

```python
from ormah.background import llm_cancel
```

Delete `_shutdown_started`, `_cancel_newborn_if_shutting_down()`, `_snapshot_adapters()`, and the two `_cancel_newborn_if_shutting_down(...)` call sites inside `_get_or_create_adapter` and `_get_or_create_ingest_adapter`. `_adapter_lock` stays — it still serialises lazy init so at most one adapter per cache is built.

In `reset_adapter()`, delete the `_shutdown_started = False` line and drop it from the `global`
declaration. **Do NOT call `llm_cancel.begin_lifespan()` here (council R1 HIGH-3):** `reset_adapter`
is test-only cache clearing and must stay decoupled from lifecycle state, or a test could clear the
`final` flag outside the declared lifespan owner. Tests that need a clean epoch call
`llm_cancel.begin_lifespan()` themselves (the R6 regression already does exactly this pair:
`reset_adapter()` then `begin_lifespan()`).

**Move admission + accounting + output rejection to the facade seam (council R1 HIGH-2 + Cursor #1).**
Add a shared helper and route both public entry points through it, so EVERY provider — not just
`claude_cli` — is admission-gated and has its cancelled-era output rejected:

```python
def _guarded_generate(adapter, prompt, **kwargs) -> str | None:
    """Provider-independent cancellation seam. Admission at entry, in-flight accounting around
    the call, and rejection of any output produced in a cancelled era.

    Only the SUBPROCESS kill is claude-specific (the adapter does that from its own thread).
    Ollama/LiteLLM are not interruptible mid-flight — they still block until their HTTP timeout,
    unchanged — but this seam stops them RETURNING output that a shutdown already invalidated,
    and stops a NEW call starting once shutdown began."""
    gen, cancelled = llm_cancel.snapshot()
    if cancelled:
        raise LlmCancelledError("llm call aborted: shutdown in progress")
    llm_cancel.note_call_started()
    try:
        result = adapter.generate(prompt, **kwargs)
        if llm_cancel.epoch_changed(gen):
            # An in-flight call whose era was superseded while it ran: reject its output for
            # every provider (the claude adapter also rejects internally; this covers the rest).
            raise LlmCancelledError("llm call cancelled: shutdown in progress")
        return result
    finally:
        llm_cancel.note_call_finished()
```

Rewire the two entry points to preserve their DIFFERENT cancel contracts:

```python
def llm_generate(settings, prompt, json_mode=True, *, response_format=None, temperature=None,
                 max_tokens=None, timeout_hint_seconds=None) -> str | None:
    """Maintenance path: swallow cancel/timeout to None (unchanged contract)."""
    adapter = _get_or_create_adapter(settings)
    if adapter is None:
        return None
    try:
        return _guarded_generate(
            adapter, prompt, json_mode=json_mode, response_format=response_format,
            temperature=temperature, max_tokens=max_tokens,
            timeout_hint_seconds=timeout_hint_seconds,
        )
    except (LlmCancelledError, LlmTimeoutError):
        return None


def ingest_llm_generate(settings, prompt, json_mode=True, **kwargs) -> str | None:
    """Ingest path: PROPAGATE LlmCancelledError. The engine maps it to a provider-wide transient
    so a cancelled extraction never advances the cursor nor burns the per-slice failure cap — do
    NOT swallow it here (that safety is the whole point of the slice)."""
    adapter = _get_or_create_ingest_adapter(settings)
    if adapter is None:
        return None
    return _guarded_generate(adapter, prompt, json_mode=json_mode, **kwargs)
```

This is why the R6 regression's fake adapter is dumb: the facade — not the adapter — sees the
cancel that landed during the factory and refuses to return its output.

Replace `cancel_active_llm_calls` and `resume_llm_adapters` wholesale:

```python
def cancel_active_llm_calls(*, final: bool = True) -> int:
    """Cancel every in-flight LLM call. Returns how many calls the cancel invalidated.

    ADR-0004 slice 2 redesign: this is now a single epoch bump — no adapter-cache sweep, no
    lock held across process I/O. An adapter built after this returns still reads the
    cancelled epoch at generate() entry, so there is no cache-boundary window (R6) and no
    two-phase transition to interleave (R7).

    ``final=True`` (the default) is a shutdown cancel that resume() must not undo. The
    watcher's startup rollback passes ``final=False``, because that process keeps serving.
    """
    return llm_cancel.begin_cancel(final=final)


def resume_llm_adapters() -> None:
    """Re-admit new LLM calls after a RECOVERABLE cancel (the watcher's startup rollback).

    A no-op after a final cancel. Calls already in flight are NOT un-cancelled — the epoch
    bump keeps them aborting (R4).
    """
    llm_cancel.resume()


def begin_llm_lifespan() -> None:
    """Start a clean cancellation era. Called once per lifespan startup.

    The adapter caches here are module-level and outlive a lifespan, so a final cancel from
    the previous one must be cleared or every call in this process stays dead until restart.
    """
    llm_cancel.begin_lifespan()
```

- [ ] **Step 6: Run the regressions, then the full suite**

```bash
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_claude_cli_adapter.py::test_a_cancelled_call_never_has_its_partial_output_accepted \
  tests/test_background/test_llm_client.py::test_an_adapter_built_during_a_shutdown_is_born_cancelled -q
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/ -q
ruff check src/ tests/
```

Expected: both regressions PASS. Full suite at baseline (2029 passed, the 6 `tests/test_setup.py` environmental failures, 4 pre-existing ruff errors, nothing new).

Existing adapter/facade tests that call `adapter.cancel_active()`/`adapter.resume()` or read `_shutdown_started`/`adapter.cancelled` will fail — those are gone by design. **Explicit migration checklist (council R1, Cursor MEDIUM 1-2) — map each old assertion to the epoch; do NOT silently delete a failing test:**

| Test (file:line) | Old contract | Migrate to |
|---|---|---|
| `test_cancel_and_resume_isolate_a_raising_adapter` (`test_llm_client.py:31-41`) | per-adapter isolation (one adapter raising must not stop the other being cancelled) | **Remove** — there is no per-adapter sweep now; a single epoch bump cannot partially fail. Note the removal in the report. |
| `test_adapter_built_during_shutdown_is_born_cancelled` (`test_llm_client.py:111-193`) | `_shutdown_started` gate + `adapter.cancelled` | **Replace** with the new `test_an_adapter_built_during_a_shutdown_is_born_cancelled` (Step 1) — same intent, epoch + facade seam. |
| `test_gate_is_lowered_by_resume_so_later_adapters_are_not_born_cancelled` (`test_llm_client.py:111-193`) | `_shutdown_started` lowered by resume | **Replace** with a `llm_cancel`-level assertion: after `begin_cancel(final=False)` + `resume()`, `snapshot()[1] is False` (already covered by `test_llm_cancel.py`); delete the obsolete facade-gate version. |

Add a `llm_cancel.begin_lifespan()` at the start and end of any test that cancels, so the module-global epoch cannot leak into the next test. Do not reintroduce the removed methods to keep a test passing.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/llm/claude_cli_adapter.py src/ormah/background/llm_client.py \
        tests/test_background/test_claude_cli_adapter.py tests/test_background/test_llm_client.py
git commit -m "refactor(shutdown): adapter and facade consume the cancellation epoch"
```

---

### Task 3: Move ownership out of the watcher

This is the R7 HIGH-2 fix: global LLM cancellation stops being reachable only through the watcher's lifecycle.

**Files:**
- Modify: `src/ormah/main.py` — startup (`begin_llm_lifespan()`, ~L200-202) and shutdown (wrap `yield` at ~L277 in `try/finally`, cancel first in the finally)
- Modify: `src/ormah/background/session_watcher.py` — `_stop_and_drain` (~L1577-1593): cancel only on `rearm=True`, keep the join fence
- Test: `tests/test_main_lifespan_shutdown.py` (R7 HIGH-2, abnormal-path HIGH-1, consecutive lifespans), `tests/test_background/test_session_watcher.py` (migrate the HIGH-C bound test)

**Interfaces:**
- Consumes: `llm_client.begin_llm_lifespan()`, `llm_client.cancel_active_llm_calls(final=...)`, `llm_client.resume_llm_adapters()` from Task 2.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_lifespan_shutdown.py`. First the harness — it mirrors the fake-module
pattern that `test_each_lifespan_gets_its_own_stop_event` (same file, L234) already uses, so the
lifespan runs hermetically without touching real I/O:

```python
@contextlib.contextmanager
def _fake_lifespan_deps(tmp_path, monkeypatch, *, watcher_raises: bool = False):
    """Patch main.lifespan's heavy dependencies. Mirrors the fakes at L249-288."""
    import sys

    class _FakeEngine:
        def startup(self): pass
        def shutdown(self): pass

    class _FakeScheduler:
        def shutdown(self, wait=True): pass

    monkeypatch.setattr("ormah.main.MemoryEngine", lambda settings: _FakeEngine())
    monkeypatch.setattr(
        "ormah.main.settings",
        type("S", (), {"port": 8787, "memory_dir": str(tmp_path)})(),
    )
    monkeypatch.setattr("ormah.main.MaintenanceManager", lambda *a, **kw: object())

    _fake_hippocampus = type(sys)("_fake_hippo")
    _fake_hippocampus.start_hippocampus = lambda engine: []
    _fake_hippocampus.stop_hippocampus = lambda obs: None
    monkeypatch.setitem(sys.modules, "ormah.background.hippocampus", _fake_hippocampus)

    def _raise(engine):
        raise RuntimeError("watcher down")

    _fake_session_watcher = type(sys)("_fake_sw")
    _fake_session_watcher.start_session_watcher = _raise if watcher_raises else (lambda engine: [])
    _fake_session_watcher.stop_session_watcher = lambda obs: None
    monkeypatch.setitem(sys.modules, "ormah.background.session_watcher", _fake_session_watcher)

    _fake_scheduler_mod = type(sys)("_fake_sched")
    _fake_scheduler_mod.start_scheduler = lambda engine, stop_event=None: (
        _FakeScheduler(), object()
    )
    monkeypatch.setitem(sys.modules, "ormah.background.scheduler", _fake_scheduler_mod)
    yield


@pytest.mark.asyncio
async def test_shutdown_cancels_llm_calls_even_when_the_watcher_failed_to_start(
    tmp_path, monkeypatch
):
    """R7 HIGH-2 regression.

    When start_session_watcher() raises, main.lifespan catches it at L274 and
    app.state.session_watches is never assigned — so the `if hasattr(...)` guard at L302
    skips stop_session_watcher(), which used to be the ONLY path calling
    cancel_active_llm_calls(). A scheduler-owned maintenance call then ran to its full
    provider timeout. The scheduler is an independent consumer of LLM calls; global
    cancellation must not depend on the watcher.
    """
    cancels: list[bool] = []

    def _record_cancel(*, final: bool = True) -> int:
        cancels.append(final)
        return 0

    monkeypatch.setattr(
        "ormah.background.llm_client.cancel_active_llm_calls", _record_cancel
    )

    with _fake_lifespan_deps(tmp_path, monkeypatch, watcher_raises=True):
        app = FastAPI(lifespan=main.lifespan)
        async with main.lifespan(app):
            assert not hasattr(app.state, "session_watches"), (
                "the fake watcher was supposed to raise before the assignment"
            )

    assert cancels, "shutdown never cancelled in-flight LLM calls"
    assert cancels[0] is True, "the lifespan's shutdown cancel must be final"


@pytest.mark.asyncio
async def test_a_second_lifespan_can_still_run_llm_calls(tmp_path, monkeypatch):
    """The adapter caches and the cancellation epoch are module-level and outlive a
    lifespan. A final cancel from the first shutdown must not poison the second."""
    from ormah.background import llm_cancel

    with _fake_lifespan_deps(tmp_path, monkeypatch):
        app = FastAPI(lifespan=main.lifespan)

        async with main.lifespan(app):
            pass
        _, cancelled_after_first = llm_cancel.snapshot()
        assert cancelled_after_first is True, "the first shutdown never cancelled"

        async with main.lifespan(app):
            _, cancelled_in_second = llm_cancel.snapshot()
            assert cancelled_in_second is False, (
                "the second lifespan started with a poisoned cancellation epoch"
            )


@pytest.mark.asyncio
async def test_shutdown_cancels_llm_calls_when_the_lifespan_body_raises(tmp_path, monkeypatch):
    """Council R1 HIGH-1 regression.

    @asynccontextmanager throws a body exception at the `yield`, so teardown after a BARE yield is
    skipped. The cancel must sit in a `finally` so it still runs on the abnormal-shutdown path —
    exactly when a bounded shutdown matters. A bare-yield placement passes the normal-exit tests
    above and silently fails here."""
    cancels: list[bool] = []

    def _record_cancel(*, final: bool = True) -> int:
        cancels.append(final)
        return 0

    monkeypatch.setattr(
        "ormah.background.llm_client.cancel_active_llm_calls", _record_cancel
    )

    class _Boom(RuntimeError):
        pass

    with _fake_lifespan_deps(tmp_path, monkeypatch):
        app = FastAPI(lifespan=main.lifespan)
        with pytest.raises(_Boom):
            async with main.lifespan(app):
                raise _Boom("the app crashed mid-serve")

    assert cancels, "an abnormal shutdown skipped the LLM cancel (cancel not in a finally)"
    assert cancels[0] is True
```

Add `import contextlib` to the module's imports if it is not already there. The
`monkeypatch.setattr` on `ormah.background.llm_client.cancel_active_llm_calls` works because
`main.lifespan` imports that name *inside* the shutdown block, so the attribute is resolved at
call time.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/test_main_lifespan_shutdown.py -q -k "watcher_failed_to_start or second_lifespan"
```

Expected: `test_shutdown_cancels_llm_calls_even_when_the_watcher_failed_to_start` FAILS on `assert cancels` (nothing cancelled). `test_a_second_lifespan_can_still_run_llm_calls` FAILS on the first assertion, because nothing cancelled at all.

- [ ] **Step 3: Move the transitions into the lifespan**

In `src/ormah/main.py`, replace the startup block at L200-202:

```python
    from ormah.background.llm_client import begin_llm_lifespan

    # ADR-0004 slice 2: start a clean cancellation era. The llm_client adapter caches and the
    # epoch are module-level and outlive an in-process reload, so a previous lifespan's final
    # cancel must be cleared here or every LLM call in this process stays dead until restart.
    begin_llm_lifespan()
```

For the shutdown side, **wrap the `yield` in a `try/finally` and cancel FIRST in the finally** (council R1 HIGH-1). With `@asynccontextmanager`, an exception or cancellation inside the lifespan body is thrown at the `yield`, so any cancel placed after a bare `yield` is skipped on exactly the abnormal shutdown where a bounded shutdown matters most. Replace the bare `yield` (currently `main.py:277`) with:

```python
    try:
        yield
    finally:
        # ADR-0004 slice 2 (council R7 HIGH-2 + council R1 HIGH-1): cancel in-flight LLM calls
        # FIRST and UNCONDITIONALLY — even if the lifespan body raised or was cancelled. This is
        # the ONE piece of teardown that must survive an abnormal shutdown, and only a finally
        # guarantees it. It used to live inside stop_session_watcher(), which the `hasattr` guard
        # below skips when start_session_watcher() raised; the scheduler is an independent LLM
        # consumer and must not depend on the watcher's lifecycle.
        from ormah.background.llm_client import cancel_active_llm_calls

        try:
            invalidated = cancel_active_llm_calls(final=True)
            if invalidated:
                logger.info("Cancelled %d in-flight LLM call(s) for shutdown", invalidated)
        except Exception as e:
            logger.warning("Cancelling in-flight LLM calls for shutdown failed: %s", e)
```

The rest of the shutdown sequence (`remove_job`, `stop_ev.set()`, `stop_session_watcher`,
`engine.shutdown`, …) stays exactly where it is, AFTER the `try/finally`. On a normal shutdown it
runs as before (the finally's cancel simply runs first); on an abnormal shutdown the finally's
cancel runs and then the exception propagates out — the rest is skipped, the same pre-existing
behavior as today for every other teardown step. Do not move the rest into the finally: that is a
larger change than council asked for and the DB-close ordering is bind-sensitive.

- [ ] **Step 4: Simplify the watcher's drain**

In `src/ormah/background/session_watcher.py`, inside `_stop_and_drain`, replace the cancel block and the join loop (the region spanning the first `cancel_active_llm_calls()` call through the `while any(w.handler.drain_alive()...)` loop) with:

```python
        # Cancel ONLY on the rollback path (council R1, Cursor MEDIUM 3). rearm=True means startup
        # failed BEFORE the lifespan's shutdown finally ran, so nothing else has cancelled — and
        # the process keeps serving, so it must be RECOVERABLE (final=False). On the NORMAL
        # shutdown path (rearm=False) the lifespan's finally already issued the final cancel before
        # calling us; re-bumping here is redundant and muddies the invalidated-count log.
        if rearm:
            try:
                invalidated = cancel_active_llm_calls(final=False)
                if invalidated:
                    logger.info("Cancelled %d in-flight LLM call(s) for rollback", invalidated)
            except Exception as e:
                logger.debug("Cancelling in-flight LLM calls for rollback failed: %s", e)
        # The join fence below is LOAD-BEARING (HIGH-3, council-pr R3): an un-joined orphan drain
        # thread can touch the DB after engine.shutdown() closes it (#52). It no longer re-cancels
        # each turn — that existed for HIGH-C (council R2), to reach an adapter built AFTER the
        # first pass. A globally-read epoch removes the reason: whoever cancelled (the lifespan
        # finally on shutdown, or the `if rearm` above on rollback) bumped the ONE global epoch, and
        # a late-built adapter reads that cancelled epoch at generate() entry — so one cancel reaches
        # every call, past and future, and the fence only needs to join.
        while any(w.handler.drain_alive() for w in watches):
            for w in watches:
                w.handler.join_drain(timeout=0.2)
```

**Ordering note for the implementer:** on the normal path the fence works only because the
lifespan's `finally` cancelled the epoch *before* `stop_session_watcher` → `_stop_and_drain` runs.
Verify that ordering holds in `main.py` (the `try/finally` around `yield` precedes the
`stop_session_watcher` call in the shutdown sequence). If a future change moves the cancel after
`stop_session_watcher`, this fence would spin until the provider timeout — add a comment there.

- [ ] **Step 5: Migrate the legacy watcher/lifespan tests, then run the full suite**

Before the suite can reach baseline, these legacy tests encode the OLD contract and will fail
(council R1, Cursor MEDIUM 1-2). Migrate each — do not delete a failing test silently:

| Test (file:line) | Old contract | Migrate to |
|---|---|---|
| `test_late_built_adapter_is_still_cancelled_bounded` (`test_session_watcher.py:2958-3013`) | asserts `_stop_and_drain` calls cancel **≥3 times** (the removed HIGH-C re-cancel loop) | **Replace** with a watcher-level bounded test: a handler whose `generate()` returns only once `llm_cancel.epoch_changed(gen)` is true; drive `_stop_and_drain` after the lifespan-style `begin_cancel(final=True)`; assert it returns and `elapsed < bound` (use a `Barrier`, not `sleep`). Proves a late-built adapter is cancelled by the epoch read, not by repeated cancel passes. |
| `test_second_lifespan_can_generate_after_a_cancelled_first` (`test_main_lifespan_shutdown.py:386-459`) | `FakeAdapter._cancelled` + `resume_llm_adapters()` | **Replace** with `test_a_second_lifespan_can_still_run_llm_calls` (Step 1) — same intent on the epoch. Delete the old one. |

```bash
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/test_main_lifespan_shutdown.py tests/test_background/test_session_watcher.py -q
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/ -q
ruff check src/ tests/
```

Expected: the new tests PASS; the migrated legacy tests PASS; full suite at baseline; no new ruff errors.

- [ ] **Step 6: Verify the setsid bound survived**

The measured win this slice exists for (19.55s → 0.50s on a `setsid` grandchild) must not have regressed. Run the three existing bound tests by name:

```bash
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -q \
  -k "test_cancel_is_bounded_even_with_a_detached_setsid_grandchild or \
      test_group_sigkill_escalation_reaps_sigterm_ignoring_grandchild or \
      test_cancel_during_poll_loop_raises_within_a_poll_interval"
```

Expected: 3 passed. These three (at `test_claude_cli_adapter.py:1088`, `:1023` and `:542`) are the ones that actually measure the bound; they drive real subprocesses, so they need rewriting onto `llm_cancel.begin_cancel(final=True)` in Task 2 Step 6 rather than `adapter.cancel_active()`. Report the wall-clock the setsid test prints — "passed" alone does not establish the bound held.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/main.py src/ormah/background/session_watcher.py tests/test_main_lifespan_shutdown.py
git commit -m "fix(shutdown): own LLM cancellation in the lifespan, not the watcher (council R7 HIGH-2)"
```

---

## Done criteria

All six acceptance criteria from the spec, verified by running them — not by inspection:

1. R5 torn-generation regression passes (Task 2).
2. R6 cache-boundary regression passes (Task 2).
3. R7 HIGH-1 linearizability test passes (Task 1).
4. R7 HIGH-2 watcher-startup-failure test passes (Task 3).
5. Consecutive-lifespans test passes (Task 3).
6. Suite at baseline; no new ruff errors.

**The design's central claim is that criteria 3–5 pass without any task targeting them individually.** Task 1 writes the R7 HIGH-1 test against the new module, and Tasks 2 and 3 do not touch it. If any of 3–5 requires a fix aimed specifically at it, the design is wrong and that is a reason to stop and re-open the spec — not to patch.

**Not in scope:** merging to the Beta, porting the ADR text, rollout. The branch stays unmerged pending André's explicit GO.
