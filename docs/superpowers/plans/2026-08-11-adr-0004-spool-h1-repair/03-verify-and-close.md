# Task 03 — Close the spec's open assumption, then verify everything

Read `00-overview.md` first: it carries the global constraints and the shell prefix
(`$WT`, `$PY`) every command here assumes. Tasks 01 and 02 must be committed first.

**Files:** none, unless Step 1 finds something — then `src/ormah/background/session_watcher.py`.

**Interfaces:**
- Consumes: everything tasks 01 and 02 produced (`_BACKOFF_MAX_SHIFT`, `IngestResult.GONE`).
- Produces: nothing new. This task is evidence, not code.

- [ ] **Step 1: Check whether any other handler on the drain path swallows `FileNotFoundError`**

The spec records this as **assumed**, not verified: that `_file_hash` and `path.stat()` are
the only places a deleted transcript surfaces as `FileNotFoundError` on the drain path. Task
02's test cannot prove it — the file is already gone when `_file_hash` runs, so the parser
below is never reached. A transcript deleted *mid-drain* would take a different route.

```bash
PYTHONPATH=$WT/src $PY - <<'PY'
import inspect, re
from ormah.background import session_watcher as sw
src, start = inspect.getsourcelines(sw._ingest_session)
for i, line in enumerate(src, start):
    if re.search(r'except .*(OSError|Exception|IOError)', line):
        print(f"{i}: {line.rstrip()}")
PY
```

Read every hit. Any `except OSError` / `except Exception` that wraps a file read **after**
the hash/stat can still misclassify a transcript deleted mid-drain as `external`.

If one exists: **report it and stop.** Widening the fix is a scope decision for André, not
an automatic edit. Record the exact line numbers in your report.

If none exists: say so explicitly, citing the command output — that promotes the spec's
*assumed* to *verified*.

- [ ] **Step 2: Run the full fast suite**

```bash
PYTHONPATH=$WT/src $PY -m pytest tests/ 2>&1 | tail -15
```

Expected: no new failures relative to the baseline. Record the exact pass/fail counts. If
anything fails, quote the failure output verbatim rather than summarising it — a summarised
failure has hidden a real regression in this project before.

- [ ] **Step 3: Lint**

```bash
cd $WT && /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ruff check src/ tests/
```

Expected: clean, or only pre-existing warnings unrelated to `ingest_spool.py` and
`session_watcher.py`. Do not "fix" unrelated pre-existing warnings.

- [ ] **Step 4: Confirm the working tree holds exactly the intended change**

```bash
git -C $WT status --short
git -C $WT log --oneline -3
git -C $WT diff --stat HEAD~2..HEAD -- src/ tests/
```

Expected: two commits (01 and 02); `src/` touched in exactly two files; `graphify-out/` may
be dirty (background rebuild noise) and must not be committed.

- [ ] **Step 5: Report**

State, with the command output as evidence:

1. Whether Step 1 found any additional `FileNotFoundError` sink (and which lines).
2. The full-suite pass/fail counts from Step 2.
3. Confirmation that both regression guards stayed green:
   `test_requeue_external_retries_forever_with_persisted_growing_backoff` and
   `test_requeue_deterministic_failure_dead_letters_with_original_bytes`.

No commit in this task unless Step 1 produced a fix that André approved.
