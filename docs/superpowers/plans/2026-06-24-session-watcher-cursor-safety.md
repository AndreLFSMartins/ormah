# Session Watcher Cursor Safety Implementation Plan (v3 — post-council x2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two cursor edge cases in the session watcher — mid-turn race (cursor advances past a dangling user turn) and session tail loss (final turns below `min_turns` are never ingested) — without duplicating or dropping the final user+assistant pair, and without concurrent double-ingestion.

**Architecture:** The parser exposes a *safe* boundary (`safe_end_offset`) plus a *safe payload* (`safe_conversation` / `safe_user_turn_count`) covering only completed pairs, where a pair completes at an assistant turn **that has text**. The watcher ingests the safe payload and saves `safe_end_offset` as its cursor, so ingested content and cursor always share the same completion boundary (no duplication). A short tail below `min_turns` is flushed once the file is idle; while the file is still active the handler schedules a delayed retry. A per-path in-flight guard prevents the retry and the debounce from ingesting the same slice concurrently.

**Tech Stack:** Python 3.11, pytest, `src/ormah/transcript/parser.py`, `src/ormah/background/session_watcher.py`, `src/ormah/config.py`

**Council decisions (v3):**
- **C1** (dup user) → safe payload; ingested content and cursor share the boundary.
- **C2** (tail loss) → idle flush + scheduled retry.
- **I1** (first-wins `source`) → preserved in the rewritten loop.
- **I2 REVERTED** → `safe_end_offset` advances only after an assistant turn **with text** (avoids fragmenting `tool_use → text` and avoids false recovery triggers).
- **E1 DEFERRED (signed off by André)** → no corrupted-cursor recovery. Known limitation documented below.
- **Concurrency** → per-path in-flight guard in `SessionHandler`.

**Known limitations (accepted):**
- *Pre-existing corrupted cursors* written by the old bug (a session that was exactly mid-turn at upgrade time) are not repaired; the user side of that one final pair may be lost. Local single-user impact only.
- *Terminal tool-only assistant*: if a session ends on an assistant turn that has no text at all (only `tool_use`), that final pair stays pending and is not ingested. Pathological/rare.

---

## File map

| File | What changes |
| --- | --- |
| `src/ormah/transcript/parser.py` | `readline()` loop preserving first-wins `source` + existing guards; add `safe_end_offset`, `safe_conversation`, `safe_user_turn_count`; boundary advances only after an assistant turn **with text** |
| `src/ormah/config.py` | add `session_watcher_idle_threshold: float = 30.0` |
| `src/ormah/background/session_watcher.py` | guard on `safe_end_offset == prev_offset`; idle flush with `on_defer_active` callback; ingest `safe_conversation`; save `safe_end_offset`; `SessionHandler` gets `idle_threshold`, `_schedule_retry`, and a per-path in-flight guard |
| `tests/test_transcript/test_parser.py` | 4 new tests (safe boundary, safe payload, `user→tool_use→text` single pair, terminal tool-only does NOT advance) |
| `tests/test_background/test_session_watcher.py` | 5 new tests (mid-turn race, idle no-dup tail, idle tail flush, retry fires & ingests after idle, concurrent ingest skipped) |

---

## Task 1: Parser — safe boundary tests (failing)

**Files:**
- Test: `tests/test_transcript/test_parser.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transcript/test_parser.py`:

```python
class TestSafeBoundary:
    def test_safe_offset_and_payload_stop_at_last_complete_pair(self, tmp_path):
        """safe_* must exclude a dangling user turn; raw fields still include it."""
        lines = [
            {"type": "user",      "message": {"content": "Turn 1 user"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Turn 1 assistant"}]}},
            {"type": "user",      "message": {"content": "Turn 2 user"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Turn 2 assistant"}]}},
            {"type": "user",      "message": {"content": "Turn 3 dangling user"}},
        ]
        path = _write_jsonl(tmp_path, lines)
        result = parse_transcript(path)

        assert result.user_turn_count == 3
        assert "Turn 3" in result.conversation

        assert result.safe_user_turn_count == 2
        assert "Turn 3" not in result.safe_conversation
        assert "Turn 2 assistant" in result.safe_conversation
        assert 0 < result.safe_end_offset < result.end_offset

        tail = parse_transcript(path, start_offset=result.safe_end_offset)
        assert tail.user_turn_count == 1
        assert "Turn 3" in tail.conversation

    def test_safe_equals_full_when_last_turn_is_assistant(self, tmp_path):
        lines = [
            {"type": "user",      "message": {"content": "U1"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "A1"}]}},
        ]
        path = _write_jsonl(tmp_path, lines)
        result = parse_transcript(path)
        assert result.safe_end_offset == result.end_offset
        assert result.safe_user_turn_count == result.user_turn_count
        assert result.safe_conversation == result.conversation

    def test_user_then_tooluse_then_text_is_one_pair(self, tmp_path):
        """I2 reverted: tool_use followed by a text assistant must form ONE pair, not fragment."""
        lines = [
            {"type": "user",      "message": {"content": "Please read the file"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "read", "input": {}}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Here is the summary"}]}},
        ]
        path = _write_jsonl(tmp_path, lines)
        result = parse_transcript(path)
        # The boundary is the text-bearing assistant; the whole thing is the safe payload.
        assert result.safe_end_offset == result.end_offset
        assert "Please read the file" in result.safe_conversation
        assert "Here is the summary" in result.safe_conversation
        assert result.safe_user_turn_count == 1

    def test_terminal_toolonly_assistant_does_not_advance_boundary(self, tmp_path):
        """A trailing tool-only assistant (no text) leaves the pair pending (known limitation)."""
        lines = [
            {"type": "user",      "message": {"content": "U1"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "A1"}]}},
            {"type": "user",      "message": {"content": "U2 asks for a tool"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "read", "input": {}}]}},
        ]
        path = _write_jsonl(tmp_path, lines)
        result = parse_transcript(path)
        # Boundary stops at the U1/A1 pair; U2 + its tool-only assistant are not in the safe payload.
        assert result.safe_user_turn_count == 1
        assert "U2" not in result.safe_conversation
        assert result.safe_end_offset < result.end_offset
```

- [ ] **Step 2: Run to confirm they fail**

```
python -m pytest tests/test_transcript/test_parser.py::TestSafeBoundary -v
```

Expected: `AttributeError: 'TranscriptResult' object has no attribute 'safe_end_offset'`

---

## Task 2: Parser — safe boundary implementation

**Files:**
- Modify: `src/ormah/transcript/parser.py`

- [ ] **Step 1: Add safe fields to `TranscriptResult`**

In `TranscriptResult`, after the `end_offset` field:

```python
    end_offset: int = 0            # byte position after last line read (EOF of slice)
    safe_end_offset: int = 0       # byte position after last text-bearing assistant turn
    safe_conversation: str = ""    # conversation text up to safe_end_offset only
    safe_user_turn_count: int = 0  # user turns within the safe boundary
```

- [ ] **Step 2: Rewrite the loop with `readline()`, preserving first-wins `source` + guards, advancing the boundary only after a text-bearing assistant**

Replace the `with open(path) as f:` block in `parse_transcript` with:

```python
    _safe_end = start_offset
    _safe_len = 0  # len(turns) captured at the last safe boundary
    _safe_users = 0
    with open(path) as f:
        if start_offset > 0:
            f.seek(start_offset)
        while True:
            line = f.readline()
            if not line:
                break
            stripped = line.strip()
            if not stripped:
                continue

            try:
                entry = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                continue

            entry_source = _source_for_entry(entry)
            if source == "agent_jsonl" and entry_source is not None:
                source = entry_source  # first-wins (preserved from original)

            entry_type, content = _coerce_entry(entry)
            if entry_type not in ("user", "assistant"):
                continue
            if content is None:
                continue

            if entry_type == "user":
                text = _extract_user_text(content)
                if text and not _is_bootstrap_user_text(text):
                    turns.append(TranscriptTurn(role="user", text=text))
                    user_turn_count += 1

            elif entry_type == "assistant":
                text = _extract_assistant_text(content)
                if text:
                    turns.append(TranscriptTurn(role="assistant", text=text))
                    # Boundary advances only after a text-bearing assistant turn (I2 reverted):
                    # tool-only assistant lines do not complete a pair, so a later text
                    # assistant for the same turn is not misread as a new slice.
                    _safe_end = f.tell()
                    _safe_len = len(turns)
                    _safe_users = user_turn_count

        end_offset = f.tell()
```

- [ ] **Step 3: Build the safe payload and pass it in the return value**

After the `with` block, replace the `conversation = ...` / `return TranscriptResult(...)` tail with:

```python
    conversation = _conversation_from_turns(turns)
    safe_turns = turns[:_safe_len]
    safe_conversation = _conversation_from_turns(safe_turns)
    return TranscriptResult(
        conversation=conversation,
        user_turn_count=user_turn_count,
        total_chars=total_chars,
        cleaned_chars=len(conversation),
        session_id=path.stem,
        end_offset=end_offset,
        safe_end_offset=_safe_end,
        safe_conversation=safe_conversation,
        safe_user_turn_count=_safe_users,
        turns=turns,
        source=source,
    )
```

- [ ] **Step 4: Run the parser tests**

```
python -m pytest tests/test_transcript/ -v
```

Expected: all existing tests pass + 4 new `TestSafeBoundary` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/transcript/parser.py tests/test_transcript/test_parser.py
git commit -m "feat(parser): safe boundary payload (text-bearing assistant completes a pair)"
```

---

## Task 3: Config — idle threshold

**Files:**
- Modify: `src/ormah/config.py`

- [ ] **Step 1: Add the setting**

After `session_watcher_lookback_hours` (line 78):

```python
    session_watcher_idle_threshold: float = 30.0
```

(Default 30 s < the 60 s debounce: when the debounce fires after a quiet period the file is already idle, so the tail flushes on the natural debounce; the scheduled retry in Task 5 covers any other config.)

- [ ] **Step 2: Commit**

```bash
git add src/ormah/config.py
git commit -m "feat(config): session_watcher_idle_threshold (default 30s)"
```

---

## Task 4: Watcher — behaviour tests (failing)

**Files:**
- Test: `tests/test_background/test_session_watcher.py`

- [ ] **Step 1: Add shared helpers + the five failing tests**

Append to `tests/test_background/test_session_watcher.py` (`import os` and `time` are already imported at module top):

```python
def _append_pair(path, i):
    with path.open("a") as f:
        f.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": f"User message {i} with enough text to parse"},
        }) + "\n")
        f.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": f"Assistant response {i} with some detail"},
            ]},
        }) + "\n")


def _append_user(path, i):
    with path.open("a") as f:
        f.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": f"User message {i} with enough text to parse"},
        }) + "\n")


def _append_assistant(path, i):
    with path.open("a") as f:
        f.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": f"Assistant response {i} with some detail"},
            ]},
        }) + "\n")


# --- Test 14: Mid-turn race — dangling user does not advance cursor ---

def test_mid_turn_race(engine, tmp_path):
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    rel = str(jsonl.relative_to(watch_dir))

    _make_jsonl(jsonl, user_turns=5)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True
    cursor1 = state[rel]["end_offset"]

    _append_user(jsonl, 5)  # dangling user, no assistant yet
    calls = 0
    real_ingest = engine.ingest_conversation

    def counting(content, **kwargs):
        nonlocal calls
        calls += 1
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=counting):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is False
    assert calls == 0
    assert state[rel]["end_offset"] == cursor1

    _append_assistant(jsonl, 5)  # complete the pair
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=counting):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is True
    assert calls == 1
    assert state[rel]["end_offset"] > cursor1


# --- Test 15: Idle tail with trailing dangling user — no duplication (C1) ---

def test_idle_tail_with_dangling_user_no_duplicate(engine, tmp_path):
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    rel = str(jsonl.relative_to(watch_dir))

    _make_jsonl(jsonl, user_turns=6)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    _append_pair(jsonl, 6)
    _append_pair(jsonl, 7)
    _append_user(jsonl, 8)  # dangling
    now = time.time()
    os.utime(jsonl, (now, now - 120))

    captured = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=5, idle_threshold=30
        ) is True
        assert "User message 8 " not in captured[-1]

        _append_assistant(jsonl, 8)
        now2 = time.time()
        os.utime(jsonl, (now2, now2 - 120))
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=1, idle_threshold=30
        ) is True

    joined = "\n".join(captured)
    assert joined.count("User message 8 ") == 1


# --- Test 16: Short tail flushed when idle ---

def test_session_tail_idle_ingested(engine, tmp_path):
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"

    _make_jsonl(jsonl, user_turns=6)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    _append_pair(jsonl, 6)
    _append_pair(jsonl, 7)  # 2 new pairs < min_turns=5
    now = time.time()
    os.utime(jsonl, (now, now - 120))

    calls = 0
    real_ingest = engine.ingest_conversation

    def counting(content, **kwargs):
        nonlocal calls
        calls += 1
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=counting):
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=5, idle_threshold=30
        ) is True
    assert calls == 1


# --- Test 17: Retry fires and ingests the tail after idle (C2 end-to-end) ---

def test_retry_fires_and_ingests_after_idle(engine, tmp_path):
    """Active short tail defers, schedules a retry; when the retry fires on an idle file it ingests."""
    from ormah.background import session_watcher as sw

    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"

    _make_jsonl(jsonl, user_turns=6)

    captured_timers = []

    class FakeTimer:
        def __init__(self, delay, fn, args=()):
            self.delay = delay
            self.fn = fn
            self.args = args
            self.daemon = False
        def start(self):
            captured_timers.append(self)
        def cancel(self):
            pass

    calls = 0
    real_ingest = engine.ingest_conversation

    def counting(content, **kwargs):
        nonlocal calls
        calls += 1
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=counting), \
         patch.object(sw, "Timer", FakeTimer):
        handler = sw.SessionHandler(
            engine, watch_dir, debounce_seconds=60, min_turns=5, idle_threshold=30,
        )
        # First ingest (6 pairs) via direct catch-up so state has a cursor
        sw._ingest_session(engine, jsonl, handler._state, watch_dir, min_turns=5)

        # Append a short, still-active tail
        _append_pair(jsonl, 6)
        _append_pair(jsonl, 7)

        handler._do_ingest(jsonl)  # defers (active), schedules a retry Timer
        assert calls == 0
        assert len(captured_timers) == 1
        assert captured_timers[0].delay == 30  # idle_threshold

        # Simulate time passing: file becomes idle, then the retry timer fires
        now = time.time()
        os.utime(jsonl, (now, now - 120))
        timer = captured_timers[0]
        timer.fn(*timer.args)  # invoke the retry's _do_ingest

    assert calls == 1


# --- Test 18: Concurrent ingest is skipped by the in-flight guard (I1) ---

def test_concurrent_ingest_skipped(engine, tmp_path):
    """A second _do_ingest for the same path is skipped while the first is in flight."""
    import threading
    from ormah.background import session_watcher as sw

    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    _make_jsonl(jsonl, user_turns=6)

    started = threading.Event()
    release = threading.Event()
    calls = 0

    def blocking_ingest(content, **kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return []

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=blocking_ingest):
        handler = sw.SessionHandler(
            engine, watch_dir, debounce_seconds=60, min_turns=5, idle_threshold=30,
        )
        t1 = threading.Thread(target=handler._do_ingest, args=(jsonl,))
        t1.start()
        assert started.wait(timeout=5)   # first ingest is in flight
        handler._do_ingest(jsonl)        # second call must be skipped, not block
        release.set()
        t1.join(timeout=5)

    assert calls == 1
```

- [ ] **Step 2: Run to confirm they fail**

```
python -m pytest tests/test_background/test_session_watcher.py -k "mid_turn_race or dangling_user or tail_idle or retry_fires or concurrent_ingest" -v
```

Expected: failures — `TypeError: _ingest_session() got an unexpected keyword argument 'idle_threshold'` (and missing `idle_threshold`/in-flight handling on `SessionHandler`).

---

## Task 5: Watcher — implementation

**Files:**
- Modify: `src/ormah/background/session_watcher.py`

- [ ] **Step 1: Extend `_ingest_session` signature**

Change the signature (line 691) to:

```python
def _ingest_session(
    engine: MemoryEngine,
    path: Path,
    state: dict,
    watch_dir: Path,
    min_turns: int,
    idle_threshold: float = 30.0,
    on_defer_active=None,
) -> bool:
```

- [ ] **Step 2: Replace the `min_turns` guard with the safe-boundary + idle + retry logic**

Find:

```python
    if result.user_turn_count < min_turns:
        return False  # too few NEW turns; offset unchanged so they're reconsidered later
```

Replace with:

```python
    # Bug 1: no complete new user+assistant pair — cursor stays put.
    if result.safe_end_offset == prev_offset:
        return False

    # Bug 2: short tail — defer unless the session looks idle/finished.
    if result.safe_user_turn_count < min_turns:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = idle_threshold + 1  # treat unstatable file as idle
        if age <= idle_threshold:
            if on_defer_active is not None:
                on_defer_active()  # schedule a retry so the tail is not lost
            return False
```

- [ ] **Step 3: Ingest the safe payload and save `safe_end_offset` as the cursor**

Find the `engine.ingest_conversation(content=result.conversation, ...)` call and change `content`:

```python
        ingested = engine.ingest_conversation(
            content=result.safe_conversation,
            space=space,
            agent_id=result.source,
            extra_tags=["session-transcript"],
        )
```

Then in the `state[rel] = { ... }` dict, change two values (leave every other key as-is):

```python
        "end_offset": result.safe_end_offset,
        ...
        "user_turns": prev_turns + result.safe_user_turn_count,
```

(The state key stays `"end_offset"` for backward compatibility — only the value source changes.)

- [ ] **Step 4: Give `SessionHandler` an idle threshold, a retry scheduler, and a per-path in-flight guard**

Update `SessionHandler.__init__`:

```python
    def __init__(
        self,
        engine: MemoryEngine,
        watch_dir: Path,
        debounce_seconds: float,
        min_turns: int,
        idle_threshold: float = 30.0,
    ) -> None:
        self.engine = engine
        self.watch_dir = watch_dir
        self.debounce_seconds = debounce_seconds
        self.min_turns = min_turns
        self.idle_threshold = idle_threshold
        self._state = _load_state(watch_dir)
        self._timers: dict[str, Timer] = {}
        self._ingesting: set[str] = set()
        self._lock = Lock()
```

Add the retry scheduler (mirrors `_schedule_ingest`, delays by `idle_threshold`):

```python
    def _schedule_retry(self, path: Path) -> None:
        """Re-attempt ingestion after idle_threshold so an active short tail is not lost."""
        key = str(path)
        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
            timer = Timer(self.idle_threshold, self._do_ingest, args=(path,))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()
```

Replace `_do_ingest` with a version that holds a per-path in-flight guard and wires the retry callback:

```python
    def _do_ingest(self, path: Path) -> None:
        """Actually ingest the session (called after debounce or retry)."""
        key = str(path)
        with self._lock:
            self._timers.pop(key, None)
            if key in self._ingesting:
                return  # an ingest for this path is already running; skip
            self._ingesting.add(key)
        try:
            _ingest_session(
                self.engine, path, self._state, self.watch_dir, self.min_turns,
                idle_threshold=self.idle_threshold,
                on_defer_active=lambda: self._schedule_retry(path),
            )
        finally:
            with self._lock:
                self._ingesting.discard(key)
```

- [ ] **Step 5: Pass the config setting when constructing the handler**

In `start_session_watcher`, update the `SessionHandler(...)` construction:

```python
        handler = SessionHandler(
            engine, watch_dir, s.session_watcher_debounce_seconds,
            s.session_watcher_min_turns, s.session_watcher_idle_threshold,
        )
```

- [ ] **Step 6: Run the new watcher tests**

```
python -m pytest tests/test_background/test_session_watcher.py -k "mid_turn_race or dangling_user or tail_idle or retry_fires or concurrent_ingest" -v
```

Expected: all 5 PASS.

- [ ] **Step 7: Run the full suite (regression check)**

```
python -m pytest tests/ -v
```

Expected: no regressions. `test_incremental_only_new_turns`, `test_incremental_defers_small_append`, and `test_shrink_resets_cursor` must still pass.

- [ ] **Step 8: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(session-watcher): safe-payload ingest, idle flush + retry, in-flight guard (#34)"
```

---

## Coverage map (council findings → tasks)

| Finding | Severity | Resolution |
| --- | --- | --- |
| C1 dup user via raw payload | critical | Task 2 (safe payload) + Task 5 step 3; Test 15 |
| C2 idle flush no retry | critical | Task 3 + Task 5 steps 2,4; Test 17 (e2e) |
| I1 first-wins source regression | important | Task 2 step 2 |
| I2 boundary on tool-only assistant | important | Task 2 step 2 (advance only on text); Tests `user_then_tooluse_then_text`, `terminal_toolonly` |
| Concurrent double-ingestion | high | Task 5 step 4 (in-flight guard); Test 18 |
| E1 corrupted cursor | medium | **Deferred (signed off)** — known limitation documented |
| Retry test was callback-only | important | Task 4 Test 17 fires the timer e2e |
