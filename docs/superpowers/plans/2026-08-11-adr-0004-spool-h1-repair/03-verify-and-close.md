# Task 03 — Prove no other ENOENT sink survives, then verify everything

Read `00-overview.md` first: it carries the global constraints and the shell prefix
(`$WT`, `$PY`) every command here assumes. Tasks 01 and 02 must be committed first.

**Files:** none, unless Step 1 finds another sink — then `src/ormah/background/session_watcher.py`.

**Interfaces:**
- Consumes: everything tasks 01 and 02 produced (`_BACKOFF_MAX_SHIFT`, `IngestResult.GONE`).
- Produces: nothing new. This task is evidence, not code.

## What changed here after the council

The original version of this task asked you to hunt for handlers that misclassify a deleted
transcript as `"external"`. **That criterion was wrong and would have passed a broken tree.**
The dangerous sink does not classify as `external` at all — it returns `NO_PROGRESS`, and the
drain then *completes* the job (`:1499`), erasing it with no `failed/` record. An implementer
following the old criterion could have inspected the generic `except Exception`, seen no
`external`, and marked the spec's assumption "verified" while the silent-loss path stayed open.

Task 02 now closes that specific sink. This task's job is to prove **no other one survives**.

- [ ] **Step 1: Enumerate every exception sink on the drain path and check each returns `GONE`**

The criterion is inverted from the original: **any** handler that can catch a
`FileNotFoundError` for the transcript and return something other than `IngestResult.GONE` is
a blocker — whatever it returns.

```bash
set -o pipefail
PYTHONPATH=$WT/src $PY - <<'PY'
import inspect, re
from ormah.background import session_watcher as sw

for fn in (sw._ingest_session, sw.SessionHandler._run_job, sw.SessionHandler._idle_with_unsafe_tail):
    src, start = inspect.getsourcelines(fn)
    print(f"=== {fn.__qualname__} (from line {start}) ===")
    for i, line in enumerate(src, start):
        if re.search(r'except\s', line):
            # show the handler and the next 3 lines, which carry the return
            body = "".join(src[i - start + 1: i - start + 4]).rstrip()
            print(f"{i}: {line.rstrip()}\n{body}\n")
PY
```

For each handler printed, answer explicitly in your report: *can a missing transcript reach
it, and what does it return?* Expected after task 02: every reachable one either returns
`IngestResult.GONE` or cannot see a `FileNotFoundError` for the transcript.

`_idle_with_unsafe_tail` returning `False` on `except OSError` (`:1512`) is **fine and must not
be changed** — it is a predicate, not a classifier; the `GONE` decision has already been made
upstream by the time it runs.

If any other sink can swallow a transcript `ENOENT`: **report it and stop.** Widening the fix
further is a scope decision for André, not an automatic edit.

- [ ] **Step 2: Run the full fast suite, preserving pytest's exit status**

```bash
set -o pipefail
PYTHONPATH=$WT/src $PY -m pytest tests/ > /tmp/adr4-suite.log 2>&1; RC=$?
echo "pytest rc=$RC"; tail -15 /tmp/adr4-suite.log; grep -c "^FAILED" /tmp/adr4-suite.log || true
```

**Never** `pytest ... | tail` — the pipe returns `tail`'s status and reports a red suite as
green. That exact mistake showed "suite verde" during this plan's council Pre-Flight while 7
tests were failing.

Known-failing at baseline, unrelated to this change (do **not** try to fix them):
`tests/test_cloud_settings.py::test_cloud_setting_preserves_unrelated_env_lines_and_updates_runtime`,
3 in `tests/test_setup.py::TestConfigureCodexMcp`, 3 in `tests/test_setup.py::TestRemoveFastembedCache`
— 7 in total. Anything beyond those 7 is a regression from this work: quote it verbatim.

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

Expected: two commits (01 and 02); `src/` touched in exactly two files; `graphify-out/` may be
dirty (background rebuild noise) and must not be committed.

- [ ] **Step 5: Report**

State, with command output as evidence:

1. Every exception sink from Step 1 and what each returns — the explicit answer to "can a
   missing transcript reach it?".
2. `pytest rc=` from Step 2 and the failure count, confirming it is exactly the 7 known
   baseline failures and naming any extra.
3. That the three regression guards stayed green:
   `test_requeue_external_retries_forever_with_persisted_growing_backoff`,
   `test_requeue_deterministic_failure_dead_letters_with_original_bytes`, and
   `test_idle_file_with_no_safe_boundary_is_dead_lettered`.

No commit in this task unless Step 1 produced a fix that André approved.
