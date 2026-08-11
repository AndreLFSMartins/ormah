# Task 3: SessionHandler.reconcile() — the disk-truth safety net

The mechanism-agnostic recovery. A **stat-only** scan finds files that still need work —
never-seen (within lookback) or a state cursor not at EOF (`end_offset != size`) — then routes up
to `reconcile_max_per_tick` through the existing `_do_ingest`. There is **no mtime cache**: a file
with a pending or failed tail is re-checked every tick until fully consumed, so a transient ingest
failure never strands it (council R1, HIGH). Fully-consumed files are skipped via a cheap size
compare (no hash, no `_do_ingest`).

**Files:**
- Modify: `src/ormah/background/session_watcher.py` (add `reconcile` to `SessionHandler`, after `_do_ingest`)
- Test: `tests/test_background/test_session_watcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_session_watcher.py` (note: `os` and `_ingest_session` are
already imported at the top of the file):

```python
def test_reconcile_ingests_file_the_live_path_missed(engine, tmp_path):
    """A changed, idle transcript whose fsevent never reached the handler is recovered."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    rel = str(jsonl.relative_to(watch_dir))
    assert rel not in handler._state  # simulate the dropped event: handler never saw it

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        recovered = handler.reconcile()

    assert recovered == 1
    assert rel in handler._state
    assert handler._state[rel]["user_turns"] == 6


def test_reconcile_skips_fully_consumed_file_on_second_pass(engine, tmp_path):
    """A second reconcile does not re-ingest a file already consumed to EOF (cheap skip)."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1
        assert handler.reconcile() == 0


def test_reconcile_does_not_reingest_what_live_path_already_took(engine, tmp_path):
    """reconcile shares handler state, so a file ingested live is not re-ingested."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._do_ingest(jsonl)                      # live path ingests it
        rel = str(jsonl.relative_to(watch_dir))
        node_count = len(handler._state[rel]["node_ids"])
        recovered = handler.reconcile()

    assert recovered == 0
    assert len(handler._state[rel]["node_ids"]) == node_count


def test_reconcile_logs_recovery_heartbeat(engine, tmp_path, caplog):
    """reconcile emits the functional heartbeat when it recovers >0 transcripts."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        with caplog.at_level("INFO", logger="ormah.background.session_watcher"):
            handler.reconcile()
    assert any("reconcile recovered" in r.message for r in caplog.records)


# --- Adversarial regressions for the two HIGH council findings ---

def test_reconcile_retries_seen_file_when_first_do_ingest_fails(engine, tmp_path):
    """A transient ingest failure must NOT strand a seen file: the next tick retries it."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    # Seed state as a seen file with a pending tail (cursor behind EOF).
    rel = str(jsonl.relative_to(watch_dir))
    handler._state[rel] = {"hash": "stale", "end_offset": 0, "node_ids": [], "user_turns": 0}

    calls = {"n": 0}
    real = _ingest_session

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return False                      # transient failure on the first reconcile
        return real(*a, **k)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
            patch("ormah.background.session_watcher._ingest_session", side_effect=flaky):
        assert handler.reconcile() == 0       # first tick: ingest "fails"
        assert handler.reconcile() == 1       # second tick retries (not skipped) and recovers


def test_reconcile_recovers_partial_tail_without_mtime_change(engine, tmp_path):
    """A grown tail with an UNCHANGED mtime is still recovered (cursor != size, not mtime)."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1               # consumes the first 6 turns
        old_mtime = jsonl.stat().st_mtime
        _make_jsonl(jsonl, user_turns=12)             # append 6 more (size grows)
        os.utime(jsonl, (old_mtime, old_mtime))       # mtime unchanged on purpose
        recovered = handler.reconcile()

    assert recovered == 1                             # picked up via end_offset != size


def test_reconcile_while_live_ingesting_defers_then_retries(engine, tmp_path):
    """If the live path owns the path mid-ingest, reconcile defers, then retries next tick."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    handler._ingesting.add(str(jsonl))                # simulate live path mid-ingest

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 0               # deferred: live path owns it

    handler._ingesting.discard(str(jsonl))            # live path finished without ingesting
    handler._pending.discard(str(jsonl))
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1               # not poisoned -> retried and recovered
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher.py -k reconcile -v`
Expected: FAIL — `SessionHandler` has no `reconcile`.

- [ ] **Step 3: Implement `reconcile()`**

Add to `SessionHandler`, right after `_do_ingest`:

```python
    def reconcile(self) -> int:
        """Disk-truth safety net: ingest transcripts the live FSEvents path dropped.

        Mechanism-agnostic and cheap: a stat-only scan finds files that still need work —
        never-seen (within lookback) or a state cursor not at EOF — then routes up to
        ``session_watcher_reconcile_max_per_tick`` of them through ``self._do_ingest`` (the
        single state owner, so no clobber / no double-ingest). A file with a pending or failed
        tail (``end_offset != size``) is re-checked every tick until fully consumed, so a
        transient ingest failure never strands it. Returns transcripts recovered.
        """
        cutoff = time.time() - (self.lookback_hours * 3600) if self.lookback_hours > 0 else 0
        cap = self.engine.settings.session_watcher_reconcile_max_per_tick
        candidates: list[Path] = []
        for jsonl_file in sorted(self.watch_dir.rglob("*.jsonl")):
            if _is_subagent_transcript(jsonl_file):
                continue
            try:
                st = jsonl_file.stat()
            except OSError:
                continue
            rel = str(jsonl_file.relative_to(self.watch_dir))
            entry = self._state.get(rel)
            if entry is None:
                # Never-seen: lookback cutoff applies (mirrors _scan_sessions).
                if cutoff > 0 and st.st_mtime < cutoff:
                    continue
                candidates.append(jsonl_file)
            elif entry.get("end_offset", 0) != st.st_size:
                # Seen but the cursor is not at EOF: pending/failed tail (or a rewrite).
                candidates.append(jsonl_file)
            # else: fully consumed -> skip cheaply (no hash, no _do_ingest).
        recovered = 0
        for jsonl_file in candidates[:cap]:
            if self._do_ingest(jsonl_file):
                recovered += 1
        if recovered:
            logger.info(
                "Session watcher reconcile recovered %d transcript(s) the live path missed",
                recovered,
            )
        return recovered
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher.py -k reconcile -v`
Expected: all PASS (including the three adversarial regressions).

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "feat(session-watcher): add reconcile() disk-truth safety net (state-cursor based)"
```
