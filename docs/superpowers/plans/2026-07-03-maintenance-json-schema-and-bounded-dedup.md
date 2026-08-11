# Maintenance JSON-Schema Seam + Bounded/Persisted Dedup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stop the sleep-cycle credit bleed at its roots: schema-valid JSON from `claude -p` (so dedup merges parse) and a bounded + persisted + failure-safe dedup sweep (no thousands of LLM calls, no dead-LLM loop, no dropped merges).

**Architecture:** Reuse existing patterns. (A) The `response_format` seam is already honored by the Ollama adapter; wire the claude_cli adapter to `--json-schema` + read `structured_output` (verified under subscription auth 2026-07-03). (B) Dedup gets its own `duplicate_checked` table (NOT shared `auto_link_checked`), and **persists only terminal outcomes**: `not_duplicate` on a confirmed non-duplicate, `error` (with backoff) on a transient LLM failure — never `duplicate` (the merge's own invalidation + the pending-proposal check cover that side, so a failed/rejected merge is never permanently skipped). Plus a per-run LLM cap and a consecutive-failure circuit breaker.

**Tech Stack:** Python 3.11, pytest (asyncio_mode=auto), sqlite, `claude -p`. Target branch: **local-main**. Out of scope: re-arming `me.ormah.sleepcycle`, pushing PR #79, the other 3 semantic jobs, sizing the cap (calibrate next week).

> **Council history:** R1 (cursor=ressalvas, codex=rejeitou) → fixed startup-break, cross-poison, transient churn. R2 (both rejeitou) → this revision: persist only `not_duplicate`/`error` never `duplicate` (drops-merge critical); error+backoff (breaker starvation); skip in `_find_merge_candidates` (agent-path re-churn); 5 invalidation statements incl. both merge DELETEs; real invalidation test; `-1` cap sentinel (0-is-falsy footgun); reject-invalidation.

---

### Task 1: claude_cli adapter honors `response_format` (schema-enforced JSON)

**Files:** Modify `src/ormah/background/llm/claude_cli_adapter.py:104-153`; Test `tests/test_background/test_claude_cli_adapter.py`

- [ ] **Step 1 — failing test**

```python
def test_response_format_adds_json_schema_and_reads_structured_output(monkeypatch):
    from ormah.background.llm import claude_cli_adapter as mod
    captured = {}
    class _Proc:
        returncode = 0; stderr = ""
        stdout = '{"result": "", "is_error": false, "structured_output": {"is_duplicate": true}}'
    def _fake_run(argv, **kwargs):
        captured["argv"] = argv; return _Proc()
    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    adapter = mod.ClaudeCliAdapter(model="claude-haiku-4-5-20251001")
    schema = {"type": "object", "properties": {"is_duplicate": {"type": "boolean"}}, "required": ["is_duplicate"]}
    raw = adapter.generate("hi", response_format={"type": "json_schema", "json_schema": {"schema": schema}})
    assert "--json-schema" in captured["argv"]
    i = captured["argv"].index("--json-schema")
    assert '"is_duplicate"' in captured["argv"][i + 1]
    import json; assert json.loads(raw) == {"is_duplicate": True}
```

- [ ] **Step 2 — run, expect FAIL** (`--json-schema` not in argv): `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py::test_response_format_adds_json_schema_and_reads_structured_output -v`

- [ ] **Step 3 — implement.** In `generate`, before the semaphore build `schema` and extend argv; then change the return.

```python
        schema = None
        if response_format and response_format.get("type") == "json_schema":
            schema = response_format.get("json_schema", {}).get("schema")
        argv = [
            self.bin_path, "-p", "--model", self.model,
            "--output-format", "json", "--no-session-persistence",
            "--permission-mode", "default", "--settings", _HARDENED_SETTINGS,
        ]
        if schema is not None:
            argv += ["--json-schema", json.dumps(schema)]
```

Replace the final return:

```python
        if schema is not None:
            structured = envelope.get("structured_output")
            # Fail-closed: schema requested but not produced → None (caller retries),
            # never a silent downgrade to free-text `result`.
            return json.dumps(structured) if structured is not None else None
        result = envelope.get("result")
        return result if isinstance(result, str) else None
```

- [ ] **Step 4 — run, expect PASS**: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -v`
- [ ] **Step 5 — commit**: `git commit -am "feat(llm): claude_cli honors response_format via --json-schema/structured_output"`

---

### Task 2: dedup passes a strict schema

**Files:** Modify `src/ormah/background/duplicate_merger.py:104-132`; Test `tests/test_background/test_duplicate_merger.py`

- [ ] **Step 1 — failing test**

```python
def test_llm_check_passes_json_schema_response_format(monkeypatch):
    import ormah.background.llm_client as llm_client
    from ormah.background import duplicate_merger as dm
    captured = {}
    def _fake_generate(settings, prompt, json_mode=True, **kwargs):
        captured.update(kwargs)
        return '{"is_duplicate": false, "merged_title": null, "merged_content": null, "reason": "x"}'
    monkeypatch.setattr(llm_client, "llm_generate", _fake_generate)
    result = dm._llm_check_duplicate(object(),
        {"title": "A", "type": "fact", "content": "a"}, {"title": "B", "type": "fact", "content": "b"})
    rf = captured.get("response_format")
    assert rf and rf["type"] == "json_schema"
    assert "is_duplicate" in rf["json_schema"]["schema"]["properties"]
    assert result == {"is_duplicate": False, "merged_title": None, "merged_content": None, "reason": "x"}
```

- [ ] **Step 2 — run, expect FAIL**: `.venv/bin/python -m pytest tests/test_background/test_duplicate_merger.py::test_llm_check_passes_json_schema_response_format -v`

- [ ] **Step 3 — implement.** Add after `_LLM_DUPLICATE_PROMPT`:

```python
_DUP_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_duplicate": {"type": "boolean"},
        "merged_title": {"type": ["string", "null"]},
        "merged_content": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
    },
    "required": ["is_duplicate", "merged_title", "merged_content", "reason"],
    "additionalProperties": False,
}
```

Change the `llm_generate` call (~line 121):

```python
    raw = llm_generate(settings, prompt, json_mode=True,
        response_format={"type": "json_schema", "json_schema": {"schema": _DUP_RESPONSE_SCHEMA}})
```

- [ ] **Step 4 — run, expect PASS**: `.venv/bin/python -m pytest tests/test_background/test_duplicate_merger.py -v`
- [ ] **Step 5 — commit**: `git commit -am "feat(dedup): pass strict json_schema response_format for duplicate check"`

---

### Task 3: `duplicate_checked` table + COMPLETE invalidation (5 statements) + real test

Rationale (council R1/R2): dedicated table avoids cross-poisoning `auto_linker`/`conflict_detector`. Invalidation must mirror EVERY place that deletes from `auto_link_checked` — including BOTH `execute_merge` deletes (removed node AND the kept node when merge changes its content).

**Files:** Modify `src/ormah/index/schema.sql` (after `auto_link_checked`, ~line 91); Modify `src/ormah/engine/memory_engine.py` (all 5 `DELETE FROM auto_link_checked` statements: node update, node delete, guarded delete, merge-removed `~1410-1413`, merge-kept `~1414-1417`); Test `tests/test_index/test_migrations.py` (or the schema/migration test module already present)

- [ ] **Step 1 — failing test** (real invalidation, not a column check)

```python
def test_duplicate_checked_invalidated_on_node_delete_update_merge(tmp_path):
    # Build an engine on a temp db (mirror the existing engine fixture in the test suite).
    engine = _make_engine(tmp_path)  # helper: returns a MemoryEngine on a fresh db
    a = engine.remember("alpha one", type="fact"); b = engine.remember("alpha two", type="fact")
    def _seed():
        with engine.db.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO duplicate_checked (node_a, node_b, result, checked_at) "
                         "VALUES (?, ?, 'not_duplicate', '2026-01-01T00:00:00+00:00')", tuple(sorted([a, b])))
    def _count():
        return engine.db.conn.execute("SELECT count(*) FROM duplicate_checked").fetchone()[0]
    _seed(); engine.update_node(a, content="alpha one changed"); assert _count() == 0   # update invalidates
    _seed(); engine.delete_node(b); assert _count() == 0                                 # delete invalidates
```

(Add helper `_make_engine(tmp_path)` if the test module lacks one; reuse the suite's existing engine construction.)

- [ ] **Step 2 — run, expect FAIL**: `.venv/bin/python -m pytest tests/test_index/test_migrations.py -k duplicate_checked_invalidated -v` (no such table / no invalidation)

- [ ] **Step 3 — implement.** In `schema.sql` after the `auto_link_checked` block:

```sql
CREATE TABLE IF NOT EXISTS duplicate_checked (
    node_a TEXT NOT NULL,
    node_b TEXT NOT NULL,
    result TEXT NOT NULL,           -- 'not_duplicate' | 'error'
    checked_at TEXT NOT NULL,
    PRIMARY KEY (node_a, node_b)
);
```

In `memory_engine.py`, immediately after EACH of the 5 `DELETE FROM auto_link_checked WHERE node_a = ? OR node_b = ?` statements, add the parallel delete with the SAME params bound at that site:

```python
                conn.execute("DELETE FROM duplicate_checked WHERE node_a = ? OR node_b = ?", (nid, nid))
```

Verify all 5 first: `grep -n "DELETE FROM auto_link_checked" src/ormah/engine/memory_engine.py` — there must be a matching `duplicate_checked` delete after each (the two inside `execute_merge` cover removed + kept).

- [ ] **Step 4 — run, expect PASS**: `.venv/bin/python -m pytest tests/test_index/test_migrations.py -v`
- [ ] **Step 5 — commit**: `git commit -am "feat(dedup): duplicate_checked table + full node-mutation invalidation (5 sites)"`

---

### Task 4: `run_duplicate_detection` + `_find_merge_candidates` — persist terminal outcomes only, backoff, breaker, skip

**Files:** Modify `src/ormah/background/duplicate_merger.py` (`run_duplicate_detection` ~255-370 AND `_find_merge_candidates` ~135-226); Test `tests/test_background/test_duplicate_merger.py`

- [ ] **Step 1 — failing tests**

```python
def test_run_dedup_records_only_not_duplicate_never_duplicate(monkeypatch, tmp_path):
    from ormah.background import duplicate_merger as dm
    monkeypatch.setattr(dm, "_llm_check_duplicate", lambda s, a, b: {"is_duplicate": False})
    engine = _make_engine_with_two_similar_nodes(tmp_path)
    dm.run_duplicate_detection(engine)
    rows = engine.db.conn.execute("SELECT result FROM duplicate_checked").fetchall()
    assert rows and all(r[0] == "not_duplicate" for r in rows)  # never 'duplicate'

def test_run_dedup_records_error_and_circuit_breaks(monkeypatch, tmp_path):
    from ormah.background import duplicate_merger as dm
    calls = {"n": 0}
    def _fail(s, a, b): calls["n"] += 1; return None
    monkeypatch.setattr(dm, "_llm_check_duplicate", _fail)
    engine = _make_engine_with_many_similar_nodes(tmp_path, n=20)
    engine.settings.duplicate_check_max_llm_calls_per_run = 100
    dm.run_duplicate_detection(engine)
    assert calls["n"] <= 3  # breaker aborts after 3 consecutive None
    errs = engine.db.conn.execute("SELECT count(*) FROM duplicate_checked WHERE result='error'").fetchone()[0]
    assert errs >= 1  # failures recorded with backoff (not lost, not re-churned immediately)
```

- [ ] **Step 2 — run, expect FAIL**: `.venv/bin/python -m pytest tests/test_background/test_duplicate_merger.py -k "only_not_duplicate or error_and_circuit" -v`

- [ ] **Step 3 — implement.** Add near the top of `duplicate_merger.py`:

```python
_DEDUP_ERROR_BACKOFF = "-6 hours"  # errored pairs become eligible again after this window
```

In `run_duplicate_detection`, after `nodes = ...` change the query to newest-first and init a breaker counter:

```python
        nodes = engine.db.conn.execute(
            "SELECT id, content, title, type FROM nodes ORDER BY created DESC").fetchall()
        consecutive_failures = 0
        from datetime import datetime, timezone
```

Persistent skip after computing `pair` (skip permanent `not_duplicate`, and `error` still inside backoff):

```python
                skip = engine.db.conn.execute(
                    "SELECT 1 FROM duplicate_checked WHERE node_a = ? AND node_b = ? AND "
                    "(result = 'not_duplicate' OR (result = 'error' AND checked_at > datetime('now', ?)))",
                    (*pair, _DEDUP_ERROR_BACKOFF),
                ).fetchone()
                if skip:
                    continue
```

Replace the `_llm_check_duplicate` call + `if llm_result is None: continue`:

```python
                llm_result = _llm_check_duplicate(settings, node, other)
                _now = datetime.now(timezone.utc).isoformat()
                if llm_result is None:  # transient failure
                    consecutive_failures += 1
                    with engine.db.transaction() as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO duplicate_checked (node_a, node_b, result, checked_at) "
                            "VALUES (?, ?, 'error', ?)", (*pair, _now))
                    if consecutive_failures >= 3:
                        logger.warning("Duplicate detection: 3 consecutive LLM failures, aborting run")
                        break  # abort; see labeled outer break below
                    continue
                consecutive_failures = 0
                if not llm_result.get("is_duplicate"):
                    with engine.db.transaction() as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO duplicate_checked (node_a, node_b, result, checked_at) "
                            "VALUES (?, ?, 'not_duplicate', ?)", (*pair, _now))
                    continue
                # is_duplicate == True: do NOT persist here — execute_merge invalidates on
                # success, and the pending-proposal check below prevents re-churn. A failed
                # merge or a later-rejected proposal is therefore never permanently skipped.
```

Keep the existing auto-merge / pending-proposal-check / proposal-create logic that follows (unchanged). Ensure the `break` on breaker also exits the OUTER node loop — set a flag:

```python
        for node in nodes:
            if consecutive_failures >= 3:
                break
            ...
```

Also add the SAME persistent skip to `_find_merge_candidates` (right where it already checks `auto_link_checked` at ~line 183) so the agent/maintenance batch path does not re-offer background-decided pairs:

```python
                dup_skip = engine.db.conn.execute(
                    "SELECT 1 FROM duplicate_checked WHERE node_a = ? AND node_b = ? AND result = 'not_duplicate'",
                    pair).fetchone()
                if dup_skip:
                    continue
```

- [ ] **Step 4 — run, expect PASS**: `.venv/bin/python -m pytest tests/test_background/test_duplicate_merger.py -v`
- [ ] **Step 5 — commit**: `git commit -am "feat(dedup): persist not_duplicate/error only, backoff, breaker, agent-path skip"`

---

### Task 5: cap knob (sentinel -1) + reject-invalidation + run-summary log

**Files:** Modify `src/ormah/config.py` (declare near `auto_merge_threshold:148`; SEPARATE validator — never the `_threshold_range` 0–1 list at 491); Modify `src/ormah/background/duplicate_merger.py` (cap + log); Modify `src/ormah/api/routes_agent.py` (`resolve_proposal` reject path); Tests `tests/test_config.py`, `tests/test_background/test_duplicate_merger.py`

- [ ] **Step 1 — failing tests**

```python
# tests/test_config.py
def test_dedup_cap_default_sentinel_and_validator():
    from ormah.config import Settings
    import pytest
    assert Settings().duplicate_check_max_llm_calls_per_run == 100
    assert Settings(duplicate_check_max_llm_calls_per_run=-1).duplicate_check_max_llm_calls_per_run == -1  # unlimited
    with pytest.raises(ValueError):
        Settings(duplicate_check_max_llm_calls_per_run=-2)

# tests/test_background/test_duplicate_merger.py
def test_run_dedup_stops_at_cap(monkeypatch, tmp_path):
    from ormah.background import duplicate_merger as dm
    calls = {"n": 0}
    monkeypatch.setattr(dm, "_llm_check_duplicate", lambda s, a, b: (calls.__setitem__("n", calls["n"]+1) or {"is_duplicate": False}))
    engine = _make_engine_with_many_similar_nodes(tmp_path, n=10)
    engine.settings.duplicate_check_max_llm_calls_per_run = 3
    dm.run_duplicate_detection(engine)
    assert calls["n"] == 3
```

- [ ] **Step 2 — run, expect FAIL**: `.venv/bin/python -m pytest tests/test_config.py::test_dedup_cap_default_sentinel_and_validator tests/test_background/test_duplicate_merger.py::test_run_dedup_stops_at_cap -v`

- [ ] **Step 3 — implement.** In `config.py` after `auto_merge_threshold: float = 0.85`:

```python
    # Per-run LLM confirmation cap for dedup. -1 = unlimited, 0 = no calls, N>=1 = cap.
    # Conservative default; calibrate against clean-week growth. NOTE: 0 is a valid
    # "disable dedup calls" value — not unlimited (that is -1).
    duplicate_check_max_llm_calls_per_run: int = 100
```

Separate validator (NOT `_threshold_range`):

```python
    @field_validator("duplicate_check_max_llm_calls_per_run")
    @classmethod
    def _dedup_cap_range(cls, v: int) -> int:
        if v < -1:
            raise ValueError(f"duplicate_check_max_llm_calls_per_run must be >= -1, got {v}")
        return v
```

In `run_duplicate_detection`, init and guard (note `>= 0` so 0 caps at zero, -1 disables the cap):

```python
        llm_calls = 0
        max_calls = getattr(engine.settings, "duplicate_check_max_llm_calls_per_run", -1)
```

At the top of the `for node in nodes:` loop and again just before each `_llm_check_duplicate`:

```python
            if max_calls >= 0 and llm_calls >= max_calls:
                break
```

and `llm_calls += 1` immediately after the `_llm_check_duplicate` call.

Run-summary log at function end (per-run counters for calibration):

```python
        logger.info("Duplicate detection run: llm_calls=%d proposals=%d cap=%d cap_hit=%s",
                    llm_calls, proposals_created, max_calls, bool(max_calls >= 0 and llm_calls >= max_calls))
```

In `routes_agent.py` `resolve_proposal`, when a `merge` proposal is REJECTED, record the pair so it is not re-proposed:

```python
        if proposal["type"] == "merge" and action == "rejected":
            ids = json.loads(proposal["source_nodes"])
            if len(ids) == 2:
                pair = tuple(sorted(ids))
                with engine.db.transaction() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO duplicate_checked (node_a, node_b, result, checked_at) "
                        "VALUES (?, ?, 'not_duplicate', ?)",
                        (*pair, datetime.now(timezone.utc).isoformat()))
```

- [ ] **Step 4 — run, expect PASS**: `.venv/bin/python -m pytest tests/test_config.py tests/test_background/test_duplicate_merger.py -v`
- [ ] **Step 5 — commit**: `git commit -am "feat(dedup): cap sentinel -1, reject-invalidation, run-summary log"`

---

### Task 6: real-binary integration check (skip-guarded)

**Files:** Test `tests/test_background/test_claude_cli_adapter.py`

- [ ] **Step 1 — add skip-guarded integration test**

```python
import shutil, pytest
@pytest.mark.integration
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_real_claude_json_schema_returns_structured_output():
    from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter
    adapter = ClaudeCliAdapter(model="claude-haiku-4-5-20251001", timeout=60)
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"], "additionalProperties": False}
    raw = adapter.generate("Return the integer 7 in a field n.",
        response_format={"type": "json_schema", "json_schema": {"schema": schema}})
    import json; assert json.loads(raw) == {"n": 7}
```

- [ ] **Step 2 — run explicitly**: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -m integration -v` (PASS or SKIP)
- [ ] **Step 3 — commit**: `git commit -am "test(llm): skip-guarded real claude -p --json-schema integration"`

---

## Post-implementation (NOT tasks — for André)

- **Full suite:** `.venv/bin/python -m pytest tests/ -v` (resolve the native-extension crash seen in council pre-flight before merge).
- **Calibration (~2026-07-10):** use the run-summary log + clean-week growth to size `duplicate_check_max_llm_calls_per_run`. Re-arm `me.ormah.sleepcycle` only after.
- **Deferred follow-ups (documented):** O(n) embedding encode per run is only partially bounded (newest-first + early break) — add a `dedup_scanned_at` node cursor if profiling shows it matters (CPU/local, not quota). `conflict_detector`/`consolidator` share the prose-JSON pattern (now fixable via the same seam) and may share unbounded sweeps — audit separately. Fuller merge-persistence sharing between background + agent paths (both writing `duplicate_checked`) beyond the read-skip added here.
- **Upstream:** Task 1's adapter change may later be cherry-picked to `feat/ingest-claude-cli-extraction` (PR #79).
