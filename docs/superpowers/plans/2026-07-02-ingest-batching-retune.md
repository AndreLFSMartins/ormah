# Ingest Batching Retune — Implementation Plan (rev. 2, post-council)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make server-side extraction flush a **Batch** by accumulated byte-size (not per-turn), so `claude -p` runs on ~15–20K-token batches instead of one call per turn — collapsing the Max-quota burn while preserving recall **and never silently dropping a batch tail**.

**Architecture:** A **retune of the existing `session_watcher`**, not a new subsystem. The per-file byte cursor, incremental parse, debounce, idle-flush and reconcile machinery already exist. We (1) add a byte-size dimension to the flush gate, (2) **cap each flush at `flush_bytes` at a real turn boundary** so an oversized pending delta is drained in slices instead of truncated, (3) raise the idle threshold to 600s **and decouple the retry timer from it**, (4) reorder the extraction prompt delta-first ([ADR 0001](../../adr/0001-batch-size-and-ordering.md)), (5) fix the suite regressions the byte gate + idle change cause, then (6–7) **measure** recall and quota.

**Flush policy (André's call — policy A):** single high idle (600s) + byte gate + the existing session-boundary hook. NOT the short-idle variant.

**Execution branch:** implement Tasks 1–5 on `feat/ingest-claude-cli-extraction` (the PR #79 head branch) — a subagent-driven worktree is created **from that branch**, not `local-main` — so the batching fix consolidates into **PR #79 as one coherent change** (the `claude_cli` extraction + its quota-safe batching ship together, never the burn-prone version alone). `local-main` (Beta integration) is used only for Task 6's live dev-server quota test (merge `feat` → `local-main`). PR #79 is a **draft at `1811b2f`**; local branch commits are fine, but do NOT push `fork/feat` until Task 6 measures and André signs off.

**Tech Stack:** Python 3.11, pydantic-settings, pytest (`asyncio_mode=auto`). Run tests with `.venv/bin/python -m pytest`.

**Council context (2 rounds, [.council/council-result.md](../../../.council/council-result.md)):** Round 1 found 2 criticals (validator not enforced; boundary trigger) — fixed. Round 2 (this revision) found the decisive one: **the byte gate decides *when* to flush, not *how much* to send.** The flush sends the whole `safe_conversation`; `_extract_memories_llm` truncates at `ingest_max_content_chars` ([memory_engine.py:2216](../../../src/ormah/engine/memory_engine.py#L2216)) and the cursor advances to the full boundary ([session_watcher.py:846](../../../src/ormah/background/session_watcher.py#L846)) → any tail beyond the cap is **silently lost**. Deterministic with `debounce=60s`, restart-backlog, or a large paste. So the **cap is non-deferrable** (André chose option A). Also corrected: critical #2's boundary flush **already exists for Claude Code** via `cmd_whisper_store` ([cli_adapter.py:424](../../../src/ormah/adapters/cli_adapter.py#L424)) (PreCompact/SessionEnd hook); only Codex lacks it, and that gate is made an objective test, not a manual watch.

---

## Scope contract (revised ledger, rev. 2)

- **Tasks 1–5** — the necessary fixes: config invariants (R1 critical #1), byte gate + **cap/slicing** (R2 critical) + retry decouple (R1 #3), prompt delta-first, suite regression (idle **and** byte-gate) + min_turns.
- **Tasks 6–7** — measure: calibrate `flush_bytes`/idle, then the quota test gate (no push, objective Codex-boundary check).
- **Conditional follow-ups (NOT tasks yet)** — the parser `max_bytes` *optimization* beyond the minimal cap (smarter multi-slice-per-scan), and a dedicated **Codex boundary hook** — built only if Task 6's objective check fails. Named, not dropped.
- **Deferred (ledger e)** — maintenance seam dead (`llm_provider=none`); Ollama-removal loose-ends #1–#4. **#1 (bin-path under launchd) is a prerequisite of Task 7.**

---

## File Structure

- **Modify** `src/ormah/config.py` — `session_watcher_flush_bytes`, `session_watcher_retry_seconds`, idle→600, cross-field validator (Task 1)
- **Modify** `src/ormah/transcript/parser.py` — optional `max_bytes` cap on `parse_transcript` (Task 2)
- **Modify** `src/ormah/background/session_watcher.py` — byte gate + capped parse in `_ingest_session`; thread `flush_bytes`/`retry_seconds`; fix `_schedule_retry` (Tasks 2, 5)
- **Modify** `src/ormah/engine/memory_engine.py` — reorder `_INGEST_LLM_PROMPT` delta-first (Task 4)
- **Modify** `tests/test_background/test_session_watcher.py` — repair idle + byte-gate regressions (Task 5)
- **New** `tests/test_background/test_session_watcher_flush.py`

**Coupling:** `flush_bytes` (60000) < `ingest_max_content_chars` (100000, [config.py:222](../../../src/ormah/config.py#L222)). Task 1 enforces `flush_bytes ≤ cap` with a cross-field validator; Task 2's cap guarantees a *flushed* batch never exceeds `flush_bytes`, so the truncation at extraction is never reached.

---

### Task 1: Config invariants — size gate, decoupled retry, enforced upper bound

**Files:**
- Modify: `src/ormah/config.py` (session_watcher block ~83-90; validator area ~544)
- Test: `tests/test_background/test_session_watcher_flush.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_background/test_session_watcher_flush.py
import pytest
from pydantic import ValidationError
from ormah.config import Settings

def test_flush_defaults():
    s = Settings()
    assert s.session_watcher_flush_bytes == 60000
    assert s.session_watcher_retry_seconds == 30.0     # decoupled from idle
    assert s.session_watcher_idle_threshold == 600.0   # policy A
    assert s.session_watcher_flush_bytes <= s.ingest_max_content_chars

def test_flush_bytes_over_cap_rejected():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_bytes=200000, ingest_max_content_chars=100000)

def test_flush_bytes_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_bytes=500)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher_flush.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'session_watcher_flush_bytes'`

- [ ] **Step 3: Add the settings** (session_watcher block near line 86)

```python
    session_watcher_idle_threshold: float = 600.0  # was 30.0 — 30s flushed 1-turn batches
    session_watcher_retry_seconds: float = 30.0    # FSEvents-miss retry — decoupled from idle
    session_watcher_flush_bytes: int = 60000       # pending-delta bytes that close a Batch (~15-20K tok)
```

- [ ] **Step 4: Add the validators** (near line 544)

```python
    @field_validator("session_watcher_flush_bytes")
    @classmethod
    def _flush_bytes_min(cls, v: int) -> int:
        if v < 1000:
            raise ValueError(f"session_watcher_flush_bytes must be >= 1000, got {v}")
        return v

    @model_validator(mode="after")
    def _flush_bytes_within_cap(self) -> "Settings":
        if self.session_watcher_flush_bytes > self.ingest_max_content_chars:
            raise ValueError(
                "session_watcher_flush_bytes "
                f"({self.session_watcher_flush_bytes}) must be <= "
                f"ingest_max_content_chars ({self.ingest_max_content_chars}); "
                "a larger batch would be silently truncated before extraction"
            )
        return self
```

Ensure the import line near the top of `config.py` includes `model_validator`: `from pydantic import field_validator, model_validator` (add if absent).

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher_flush.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/ormah/config.py tests/test_background/test_session_watcher_flush.py
git commit -m "feat(ingest): flush_bytes + retry_seconds config, enforce flush_bytes<=cap"
```

---

### Task 2: Byte-size flush gate + cap + retry decouple

Replace the turn-count deferral ([session_watcher.py:806-810](../../../src/ormah/background/session_watcher.py#L806)) with a byte gate, **cap each parse at `flush_bytes` so an oversized delta is drained in slices instead of truncated** (R2 critical — silent loss), and point `_schedule_retry` at `retry_seconds` instead of `idle_threshold` (R1 #3).

**Files:**
- Modify: `src/ormah/transcript/parser.py` — `parse_transcript` gets `max_bytes`
- Modify: `src/ormah/background/session_watcher.py` — helpers, `_ingest_session`, `SessionHandler`, `_schedule_retry`, `_do_ingest`, `start_session_watcher`
- Test: `tests/test_background/test_session_watcher_flush.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_background/test_session_watcher_flush.py
from ormah.background.session_watcher import _pending_bytes, _should_flush

def test_byte_gate():
    assert _pending_bytes(prev_offset=0, payload_offset=5000) == 5000
    assert _should_flush(pending=5000, is_idle=False, flush_bytes=60000) is False
    assert _should_flush(pending=60000, is_idle=False, flush_bytes=60000) is True
    assert _should_flush(pending=10, is_idle=True, flush_bytes=60000) is True

def test_parse_transcript_max_bytes_caps_at_turn_boundary(tmp_path):
    # 4 closed user/assistant turns of ~20KB each; cap at 60KB -> ~3 turns, boundary <= start+60KB+one turn
    from ormah.transcript.parser import parse_transcript
    p = tmp_path / "big.jsonl"
    lines = []
    for i in range(4):
        lines.append({"type": "user", "message": {"role": "user", "content": f"u{i} " + "x" * 20000}})
        lines.append({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": f"a{i}"}], "stop_reason": "end_turn"}})
    import json
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    full = parse_transcript(p)
    capped = parse_transcript(p, max_bytes=60000)
    assert 0 < capped.safe_end_offset < full.safe_end_offset          # stopped early at a boundary
    assert capped.safe_end_offset - 0 <= 60000 + 25000                 # <= cap + at most one ~20KB turn
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher_flush.py -k "byte_gate or max_bytes" -v`
Expected: FAIL — `ImportError: cannot import name '_should_flush'` / `parse_transcript() got an unexpected keyword argument 'max_bytes'`

- [ ] **Step 3: Add the gate helpers**

In `src/ormah/background/session_watcher.py`, above `_ingest_session`:

```python
def _pending_bytes(prev_offset: int, payload_offset: int) -> int:
    """Bytes of closed-but-unextracted conversation in the current Batch."""
    return max(0, payload_offset - prev_offset)


def _should_flush(pending: int, is_idle: bool, flush_bytes: int) -> bool:
    """Close the Batch when it reaches the size ceiling or the session goes idle."""
    return is_idle or pending >= flush_bytes
```

- [ ] **Step 4: Cap the parser** (the non-deferrable loss guard)

In `src/ormah/transcript/parser.py`, add an optional cap to `parse_transcript`:

```python
def parse_transcript(path: Path, start_offset: int = 0, max_bytes: int | None = None) -> TranscriptResult:
```

The safe boundary `_safe_end` advances at each turn closure (a terminal assistant [line ~299], a Codex `task_complete` [~254], or a new user line [~274]). Add ONE check at the **end of the `while True` body** (after the user/assistant `if/elif` chain, before the loop repeats):

```python
            # Cap the Batch: stop once the closed boundary reaches the byte budget, so an
            # oversized delta is drained in slices (parse_transcript is re-called from the new
            # cursor) rather than sent whole and truncated at ingest_max_content_chars.
            if max_bytes is not None and _safe_end > start_offset and (_safe_end - start_offset) >= max_bytes:
                break
```

`max_bytes=None` (the default) preserves current behavior for every other caller (`cmd_whisper_store`, tests).

- [ ] **Step 5: Rewire the gate + pass the cap** in `_ingest_session`

Change the signature (raise idle default, add `flush_bytes`):

```python
def _ingest_session(
    engine: MemoryEngine,
    path: Path,
    state: dict,
    watch_dir: Path,
    min_turns: int,
    idle_threshold: float = 600.0,   # was 30.0
    flush_bytes: int = 60000,        # NEW
    on_defer_active=None,
    state_lock=None,
) -> IngestResult:
```

Pass the cap to **both** `parse_transcript` calls (the main parse [~767] and the leading_orphan re-parse [~774]): add `max_bytes=flush_bytes` to each. Then replace the turn-count deferral block at lines 806-810 with the byte gate:

```python
    # Hold the Batch open until it reaches flush_bytes, unless the session has gone idle.
    if not _should_flush(_pending_bytes(prev_offset, payload_offset), is_idle, flush_bytes):
        if on_defer_active is not None:
            on_defer_active()  # re-check after retry_seconds or the next append
        return IngestResult.TRANSIENT
```

Because the parse is now capped at `flush_bytes`, `payload_offset - prev_offset` never exceeds ~`flush_bytes` (+ at most one closing turn, still < the truncation cap). A backlog drains one slice per scan/retry — loss-free. `IngestResult.OK` after a capped flush leaves the remaining pending for the reconcile scan.

- [ ] **Step 6: Thread the settings + fix the retry timer**

In `SessionHandler.__init__` ([session_watcher.py:918](../../../src/ormah/background/session_watcher.py#L918)) add two params after `idle_threshold` and store them:

```python
        idle_threshold: float = 600.0,
        retry_seconds: float = 30.0,
        flush_bytes: int = 60000,
        ...
        self.idle_threshold = idle_threshold
        self.retry_seconds = retry_seconds
        self.flush_bytes = flush_bytes
```

In `_schedule_retry` ([session_watcher.py:969](../../../src/ormah/background/session_watcher.py#L969)) change the timer interval from `self.idle_threshold` to `self.retry_seconds`:

```python
            timer = Timer(self.retry_seconds, self._do_ingest, args=(path,))
```

In `_do_ingest` ([session_watcher.py:992](../../../src/ormah/background/session_watcher.py#L992)) pass `flush_bytes`:

```python
            result = _ingest_session(
                self.engine, path, self._state, self.watch_dir, self.min_turns,
                idle_threshold=self.idle_threshold,
                flush_bytes=self.flush_bytes,
                on_defer_active=lambda: self._schedule_retry(path),
                state_lock=self._state_lock,
            )
```

In `start_session_watcher` ([session_watcher.py:1157](../../../src/ormah/background/session_watcher.py#L1157)) pass the settings:

```python
        idle_threshold=engine.settings.session_watcher_idle_threshold,
        retry_seconds=engine.settings.session_watcher_retry_seconds,
        flush_bytes=engine.settings.session_watcher_flush_bytes,
```

- [ ] **Step 7: Add the batch-size contract test** (automated gate for the cap)

```python
def test_flush_never_exceeds_flush_bytes(tmp_path, monkeypatch):
    # A pending delta far larger than flush_bytes AND larger than the truncation cap must be
    # sent in capped slices: every ingest_conversation call sees <= flush_bytes (+one turn),
    # and the slices together cover the whole delta (no silent loss).
    # Build a >150KB transcript, set flush_bytes=60000, ingest_max_content_chars=100000.
    # Capture content lengths passed to engine.ingest_conversation across repeated _ingest_session
    # calls; assert each <= ~85000 and the union of covered offsets == full safe boundary.
    ...  # concrete fixture mirrors test_parse_transcript_max_bytes_caps_at_turn_boundary + a fake engine
```

Flesh this out against a fake `engine` whose `ingest_conversation` records `len(content)` and returns `[{"node_id": "n"}]`. Loop `_ingest_session` until it stops progressing; assert (a) `max(recorded_lengths) <= flush_bytes + one_turn`, (b) final cursor == full `safe_end_offset` (complete coverage).

- [ ] **Step 8: Run the flush tests**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher_flush.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/ormah/transcript/parser.py src/ormah/background/session_watcher.py tests/test_background/test_session_watcher_flush.py
git commit -m "feat(ingest): byte-size flush gate with flush_bytes cap; decouple retry timer"
```

---

### Task 3: (was Task 3) Reorder extraction prompt delta-first (ADR 0001)

`_INGEST_LLM_PROMPT` ([memory_engine.py:2492](../../../src/ormah/engine/memory_engine.py#L2492)) is instructions-first, `{conversation}` last. ADR 0001 + Anthropic long-context guidance: conversation delta at the **top**, instructions after → up to +30% recall.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:2492`
- Test: `tests/test_background/test_session_watcher_flush.py`

- [ ] **Step 1: Write the failing test**

```python
def test_prompt_is_delta_first():
    from ormah.engine.memory_engine import _INGEST_LLM_PROMPT
    filled = _INGEST_LLM_PROMPT.format(conversation="SENTINEL_CONVO")
    assert filled.index("SENTINEL_CONVO") < filled.index("What to extract")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher_flush.py::test_prompt_is_delta_first -v`
Expected: FAIL — conversation currently comes last.

- [ ] **Step 3: Restructure the template**

Split the existing instruction body (quality-bar → "What to extract" → output format, from ~line 2497 on) into a `_INGEST_LLM_RULES` constant, verbatim — do not rewrite the rules. Then:

```python
_INGEST_LLM_PROMPT = """\
You are a memory curator for a persistent knowledge graph. Read the conversation below and extract memories valuable in future sessions.

<conversation>
{conversation}
</conversation>

Now extract the memories, following these rules:
""" + _INGEST_LLM_RULES
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher_flush.py::test_prompt_is_delta_first -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_background/test_session_watcher_flush.py
git commit -m "feat(ingest): order extraction prompt conversation-first per ADR 0001"
```

---

### Task 4: (was Task 4) Repair suite regressions — idle **and** byte gate

Two regressions, not one. (a) Idle default 30→600: `_mark_idle` recedes mtime only 120s ([test_session_watcher.py:61-68](../../../tests/test_background/test_session_watcher.py#L61)), so `age=120 < 600` is no longer idle. (b) The byte gate itself: a small **active** file (<`flush_bytes`) now returns `TRANSIENT` even with 6+ turns, where it used to pass via `payload_users >= min_turns`.

**Files:**
- Modify: `tests/test_background/test_session_watcher.py`
- Modify: `docs/12 - Configuration Reference.md` (min_turns note)

- [ ] **Step 1: Enumerate ALL failures**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher.py -v 2>&1 | grep FAILED`
Expect breakage in both classes: idle-dependent (`_mark_idle`) **and** byte-gate-dependent. Cursor named these to check for: `test_ingest_session_basic` (~147-157), `test_unchanged_session_skipped` (~692-703), `test_scan_skips_subagents_keeps_primary` (~190-200), `test_scan_respects_lookback` (~708-727), `test_shrink_resets_cursor` (~923-944), `test_min_turns_filter` (~672-686).

- [ ] **Step 2: Fix idle-dependent tests**

Make `_mark_idle` recede past whatever idle threshold the test uses (e.g. `idle_threshold + 60`s) instead of a hardcoded 120s, or pass `idle_threshold=30.0` explicitly in the affected calls. Smallest diff that keeps the intent “this file is idle”.

- [ ] **Step 3: Fix byte-gate-dependent tests**

Tests that expected `IngestResult.OK` from a small active session (relying on `min_turns`) must now either mark the file idle (`_mark_idle`) or set a low `flush_bytes` so the gate fires. Add one integration test making the new semantics explicit:

```python
def test_small_active_session_holds_until_idle(tmp_path):
    # <flush_bytes, not idle -> TRANSIENT; once idle -> OK
    ...  # write a 2-turn ~2KB session; assert _ingest_session(..., flush_bytes=60000) is TRANSIENT
         # then _mark_idle(path, idle_threshold=600) and assert OK
```

- [ ] **Step 4: Resolve min_turns**

The byte gate subsumes `min_turns` for active sessions. Update `test_min_turns_filter` so it asserts the **byte gate** behavior (not a false positive via `min_turns`). Keep the setting (distinct from `whisper_out_min_turns`, which still floors the boundary hook); add a one-line note in `docs/12 - Configuration Reference.md` that `session_watcher_min_turns` no longer gates the active-flush path.

- [ ] **Step 5: Green suite**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher.py tests/test_background/test_session_watcher_flush.py -v`
Expected: PASS (batching + watcher suites). The ~20 pre-existing setup-test failures are environmental, out of scope.

- [ ] **Step 6: Commit**

```bash
git add tests/test_background/test_session_watcher.py "docs/12 - Configuration Reference.md"
git commit -m "test(ingest): repair idle + byte-gate regressions; document min_turns change"
```

---

### Task 5: (was Task 5) Calibrate `flush_bytes` and `idle_threshold` (measured)

The ~15–20K-token bracket is from the literature; the exact point is measured on ormah's own prompt + transcripts.

- [ ] **Step 1: Recall across batch sizes.** Pick 3 real transcripts. For byte sizes {30000, 60000, 90000}, run `_extract_memories_llm` on the first N bytes; record memory count + a manual spot-check of obviously-missed memories. Use `.venv/bin/python` with `ORMAH_INGEST_LLM_PROVIDER=claude_cli` in the shell only (not `.env`).
- [ ] **Step 2: Decide flush_bytes** = the largest size where recall stays clean. Update the default in `config.py` if it differs from 60000. (The cap in Task 2 already prevents oversized *loss*; this tunes for *recall*.)
- [ ] **Step 3: Confirm idle 600s** stops per-turn flushes without stranding finished short sessions beyond acceptable.
- [ ] **Step 4: Record measured values** as a note appended to ADR 0001 (Consequences); commit any default change.

```bash
git add src/ormah/config.py docs/adr/0001-batch-size-and-ordering.md
git commit -m "chore(ingest): calibrate flush_bytes/idle_threshold from recall measurement"
```

---

### Task 6: (was Task 6) Quota test gate — measure before merge (do NOT push)

Prove batching collapses the Max-quota burn, and prove the Codex boundary path with an **objective** check (not a manual watch).

- [ ] **Step 0 (prereq):** Confirm `ORMAH_CLAUDE_CLI_BIN` is still set in `~/.config/ormah/.env` so `claude` resolves under launchd — OR land loose-end #1 first. Do not proceed without a resolvable bin.
- [ ] **Step 1:** Merge Tasks 1–5 into `local-main` (`git merge --no-ff`), restart: `launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev`.
- [ ] **Step 2:** Re-enable extraction **for the test only**: `ORMAH_INGEST_LLM_PROVIDER=claude_cli` in `~/.config/ormah/.env` (no inline comments — the launchd wrapper `export`s whole lines), restart.
- [ ] **Step 3 (quota):** Over one working day, measure vs baseline (764 calls/15h): grep `~/.local/share/ormah/logs/ormah.log` for `memories extracted` per hour; watch `pgrep -fc "claude -p"`. Success = order-of-magnitude fewer calls, recall intact.
- [ ] **Step 4 (objective Codex boundary):** Deterministic reproduction — finalize a Codex session with a closed delta < `flush_bytes`, then assert the memory is extracted within the expected window (idle or reconcile), before the next Whisper would need it. If it strands beyond the documented 600s SLA → the **Codex boundary hook follow-up** becomes a real task. Also verify whisper-out failure recovery: if `cmd_whisper_store` exits silently ([cli_adapter.py:499-504](../../../src/ormah/adapters/cli_adapter.py#L499)), confirm the session watcher still ingests the same delta within ≤ idle (no permanent gap).
- [ ] **Step 5:** If numbers are bad, tune via Task 5 and re-measure. **Do NOT push** — PR #79 / `fork/feat` stays at `1811b2f` until André signs off. This branch stays a test.

---

## Conditional follow-ups (built only if Task 6 fails — named, not dropped)

- **Parser `max_bytes` optimization beyond the minimal cap.** Trigger: calibration shows the one-slice-per-scan drain is too slow for real backlogs. Fix: multi-slice loop inside `_ingest_session` (bounded, anti-storm-aware) instead of one slice per reconcile cycle.
- **Dedicated Codex boundary hook.** Trigger: Task 6 Step 4 shows a real strand beyond the SLA. Today CC compaction/end is covered by `cmd_whisper_store`; Codex has none. Fix: a Codex boundary signal or a forced flush on file-shrink independent of the byte gate.

## Deferred (ledger e — named, not dropped)

- **Maintenance seam still dead** (`llm_provider=none` → 4 semantic jobs + feedback judge no-op). Separate decision; revisit as its own plan (council option-A/C debate).
- **Ollama-removal loose ends #1–#4** ([2026-07-02-ingest-ollama-removal-loose-ends.md](2026-07-02-ingest-ollama-removal-loose-ends.md)). **#1 is a Task 6 prerequisite** (bin-path under launchd). #2/#3/#4 deferred.

---

## Self-Review

- **Council coverage (both rounds):** R1 #1 validator → Task 1 cross-field + `test_flush_bytes_over_cap_rejected`; R1 #2 boundary → CC covered by `cmd_whisper_store`, Codex objective-checked in Task 6 Step 4; R1 #3 retry decouple → Task 2 Step 6; **R2 critical silent-loss → Task 2 Steps 4-7 (parser cap + contract test)** — the decisive fix; R2 Task-4-incomplete → Task 4 Steps 1/3 (byte-gate regressions enumerated); R2 whisper-out-partial → Task 6 Step 4; min_turns → Task 4 Step 4.
- **Silent loss closed:** the cap makes a flushed batch ≤ `flush_bytes` (+one turn) < the truncation cap; the contract test asserts every `ingest_conversation` payload is bounded AND slices cover the full delta.
- **Policy A honored:** idle 600 kept; retry decoupled so 600s never slows recovery.
- **No silent drops:** the two remaining expensive items are conditional follow-ups with explicit triggers.
- **Ledger:** 6 tasks + 2 conditional follow-ups + deferred(e). Task 6 prereq (#1) surfaced.
