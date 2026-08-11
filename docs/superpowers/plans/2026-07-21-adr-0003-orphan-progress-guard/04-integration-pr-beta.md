# Task 4: Verify, PR upstream, merge into the Beta

**Files:**
- No new source files. Operations: full test run, lint, push to `fork`, /council-pr,
  merge into `local-main`, Beta restart + live verification.

**Interfaces:**
- Consumes: the three commits from Tasks 1–3 on branch `fix/leading-orphan-progress-guard`.
- Produces: an upstream PR against issue #149 (base `r-spade:main`,
  head `fork:fix/leading-orphan-progress-guard`) and the fix live on the Beta.

- [ ] **Step 1: Full fast suite + lint in the worktree**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-149/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/ -q )
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m ruff check src/ tests/ )
```

Expected: 0 failures, 0 ruff errors. Known caveat: a handful of failures can be
environmental (global `~/.config/ormah/.env` leaking into bare `Settings()`); compare
against the same failure set on a clean `upstream/main` checkout before blaming the branch.

- [ ] **Step 2: Push the branch to the fork**

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah-wt-149 push fork fix/leading-orphan-progress-guard
```

Never push to `upstream`/`origin` (both point to r-spade). If a council guard blocks a push,
the explicit command above bypasses it (the guard is council's, not git's).

- [ ] **Step 3: /council-pr (review + open the PR)**

Run `/council-pr` from the worktree. Note (memória `ormah-council-pr-on-beta`): council from a
worktree needs the untracked `.council/` + `CLAUDE.md` bridged via symlink from the main clone:

```bash
ln -s /Users/andre/Documents/GitHub/Tools/ormah/.council /Users/andre/Documents/GitHub/Tools/ormah-wt-149/.council
ln -s /Users/andre/Documents/GitHub/Tools/ormah/CLAUDE.md /Users/andre/Documents/GitHub/Tools/ormah-wt-149/CLAUDE.md
```

PR: base `r-spade:main`, head `AndreLFSMartins:fix/leading-orphan-progress-guard`, body says
`Fixes #149`, summarizes the guard (rewind only on `safe_end_offset <= start_offset`; orphan
with progress is dropped; tail un-stranded) and cites the 36×/14h replay evidence from #149.

- [ ] **Step 4: Merge into `local-main` (Recipe B — run in the MAIN clone)**

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah merge fix/leading-orphan-progress-guard --no-edit
```

Expected conflicts: likely in `src/ormah/background/session_watcher.py` (local `_ingest_session`
has extra params `flush_bytes=`/`on_defer_active=` and calls
`parse_transcript(path, start_offset=prev_offset, max_bytes=flush_bytes)`). Resolution: keep the
local call shape and apply the guard onto it —

```python
        result = parse_transcript(path, start_offset=prev_offset, max_bytes=flush_bytes)
        if should_rewind(result, prev_offset):
```

`parser.py` and `cli_adapter.py` should merge clean; if not, same rule: local call shape +
`should_rewind` gate.

**Council ajuste #2 (Cursor M2 + Codex R2) — Beta-only bounded regression.** Before
committing the merge, add to `tests/test_background/test_session_watcher.py` (local-main
only — upstream has no `flush_bytes`) a regression proving the byte-cap path cannot
resurrect the rewind (`safe_end_offset == start_offset` under a small cap):

```python
def test_large_orphan_beyond_flush_bytes_does_not_rewind(engine, tmp_path, caplog):
    """Beta byte-cap path (council R2): an orphan larger than flush_bytes must not make
    should_rewind true (the first boundary commit ignores the cap while _safe_len == 0,
    parser.py). Cursor advances monotonically across ticks; no recovery rewind ever."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    big = "x" * 30_000
    first_turn = [
        {"type": "user", "message": {"content": "Prompt one"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer one"}]}},
    ]
    tail = [
        {"type": "assistant", "message": {"stop_reason": "tool_use",
            "content": [{"type": "text", "text": big}]}},
        {"type": "user", "message": {"content": "continue"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer two"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in first_turn:
            f.write(json.dumps(line) + "\n")
    boundary = parse_transcript(jsonl).safe_end_offset
    with open(jsonl, "a") as f:
        for line in tail:
            f.write(json.dumps(line) + "\n")
    _mark_idle(jsonl)

    rel = str(jsonl.relative_to(watch_dir))
    state = {rel: {"end_offset": boundary, "hash": "stale", "user_turns": 1, "node_ids": []}}

    offsets = [boundary]
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         caplog.at_level(logging.INFO, logger="ormah.background.session_watcher"):
        for _ in range(10):  # bounded drain: several capped ticks may be needed
            r = _ingest_session(engine, jsonl, state, watch_dir, 1, flush_bytes=8000)
            offsets.append(state[rel]["end_offset"])
            if r == IngestResult.NO_PROGRESS:
                break
    assert "recovering legacy mid-response cursor" not in caplog.text
    assert offsets == sorted(offsets)                      # strictly non-regressing cursor
    assert state[rel]["end_offset"] == jsonl.stat().st_size  # fully drained
```

(If the local `_ingest_session` signature rejects `flush_bytes` as the 7th kwarg, align with
the local signature — it is a keyword param on local-main.) Then run, INCLUDING the Beta
flush suite:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && .venv/bin/python -m pytest \
  tests/test_transcript/test_parser.py tests/test_background/test_session_watcher.py \
  tests/test_background/test_session_watcher_flush.py \
  tests/test_whisper/test_whisper_out.py -q && .venv/bin/python -m ruff check src/ tests/ )
git -C /Users/andre/Documents/GitHub/Tools/ormah add tests/test_background/test_session_watcher.py
git -C /Users/andre/Documents/GitHub/Tools/ormah commit --no-edit  # if the merge paused on conflicts
```

Expected: all green; ruff shows only the 4 pre-existing local-main errors (memory_engine F811,
main.py E402, conftest F401, test_backfill F841) — nothing new.

**Caveat local-main:** o teste do watcher usa `_ingest_session(engine, jsonl, state, watch_dir, 1)`
posicional; na versão local a assinatura tem os mesmos 5 primeiros parâmetros posicionais, então
os testes novos aplicam sem edição. Se o merge reclamar de `min_turns`, alinhar com a assinatura
local (`min_turns=1` como keyword).

- [ ] **Step 5: Restart the Beta and verify the loop is dead**

```bash
launchctl kickstart -k gui/501/com.ormah.server.dev
sleep 5 && curl -s http://localhost:8787/admin/health | head -c 200   # expect {"status":"ok",...}
```

Live verification (the actual bug): watch the server log for ~30–60 min of normal use and
confirm `"recovering legacy mid-response cursor"` does NOT reappear for the transcript that
looped (before the fix it fired every ~27 min). Also confirm the previously-stranded tail was
ingested: the affected file's state entry `end_offset` reaches EOF in
`~/.claude/projects/**/.session_watcher_state`. Report the grep/count output, not a verdict.

- [ ] **Step 6: Cleanup**

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah worktree remove /Users/andre/Documents/GitHub/Tools/ormah-wt-149
```

Keep the branch until the upstream PR lands; delete it on the next Recipe C sync.
