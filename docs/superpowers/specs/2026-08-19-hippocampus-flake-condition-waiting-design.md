# Design — remove the wall-clock race from `test_hippocampus.py`

**Date:** 2026-08-19
**Status:** approved, pending implementation
**Scope:** `tests/test_background/test_hippocampus.py` only. No production code.
**Upstream target:** clean island from `upstream/main` (FORK-WORKFLOW.md Recipe A).

## Problem

`tests/test_background/test_hippocampus.py::test_new_file_triggers_ingestion` fails
intermittently on CI with `AssertionError: assert 'new_session.md' in {}`.

It is a test defect, not a product bug. Evidence:

| Route | Finding |
|---|---|
| `gh pr view 247 --json files` | The PR that went red touches one file, `src/ormah/pi_instructions.md`, +1/-1, markdown only. No causal path to `background/hippocampus.py`. |
| CI run 32160547915 (sha `fdf8b1b`, PR #234), 2026-08-18 | The same assertion failed on an unrelated, code-heavy branch. Two branches with no shared code, one failure mode. |
| 6 isolated local runs, 2026-08-15 (memory `cbcf96cd`) | 3 PASS / 3 FAIL — a measured 50/50 flake. |
| `upstream/main` baseline, 2026-08-16 (memory `988fca91`) | Already on the known-red list, flagged as polluting baseline comparisons. |

## Root cause

`src/ormah/background/hippocampus.py:159-186`. After the test writes the file, the work
crosses three thread boundaries before the assertion can hold:

```
write_text
  -> watchdog observer thread          (on_created / on_modified)
  -> _schedule_ingest arms threading.Timer(debounce)   [a new thread]
  -> _do_ingest -> _ingest_file        (SQLite write + embedding)
  -> _save_state
```

The test grants a fixed `time.sleep(0.5)` for all of it. Instrumented locally on an idle
machine, the real write-to-state latency is **0.136s** — a margin of only 3.7x. A GitHub
runner (2 shared vCPU, 1838 tests, ~8 min wall clock, fastembed resident) exceeds 3.7x of
thread-scheduling delay routinely. Observed CI failure rate: ~2 in 8 recent runs.

The same defect exists at line 169, which waits `time.sleep(0.5)` for a debounce timer
before asserting `call_count == 1`.

Line 166's `time.sleep(0.05)` is **not** this defect — it is a deliberate interval between
rapid writes, and stays.

## Approach

Condition-based waiting (`superpowers:systematic-debugging`, `condition-based-waiting.md`).
Replace the fixed budget with polling on the condition the test actually cares about.

Rejected alternatives:

- **Synchronization event in production code.** Exposing a `threading.Event` on
  `HippocampusHandler` would be fully deterministic, but changes product code to serve a
  test and widens the upstream diff outside `tests/`.
- **Raise the sleep to 5s.** Still probabilistic, adds 10s to every suite run, and is the
  symptom fix `systematic-debugging` classifies as failure.

## Component

One private helper in the test file. No new dependencies.

```python
def _wait_until(predicate, timeout=10.0, interval=0.01):
    """Poll until predicate() is truthy. Returns its last value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()
```

It returns the last value rather than raising, so the assertion that fails stays the
test's original one. A genuine regression still reports
`assert 'new_session.md' in {}` — not a generic timeout error.

`time.monotonic()` rather than `time.time()`: a wall-clock adjustment mid-run must not
extend or truncate the deadline.

## Call sites

**Line 83 — `test_new_file_triggers_ingestion`.** Poll until the state file names the
ingested file, then assert as before.

**Line 169 — the debounce test.** Half-conversion. `_wait_until(lambda: call_count >= 1)`
removes the racy half; a short bounded settle window then precedes
`assert call_count == 1`.

Proving the negative half ("no second call arrived") inherently requires a waiting window.
The asymmetry is acceptable and deliberate: a slow runner makes that half fail toward a
**false pass**, never a false failure, so it cannot redden CI.

## Error handling

A real regression — the watcher never ingesting — now surfaces after the 10s timeout with
the original assertion message. Slower than today's 0.5s, but only on the failing path;
the passing path gets *faster* (~0.14s instead of a fixed 0.5s), so the suite's total wall
clock drops.

## Testing

Test-first, with a deterministic red. Repetition is not the proof — injected latency is.

1. **RED:** patch the ingest path to sleep longer than the current fixed budget, and show
   `test_new_file_triggers_ingestion` as written today fails under it. This reproduces the
   loaded-runner condition deterministically.
2. **GREEN:** the converted test passes under the same injected latency.
3. **Regression guard:** with the watcher genuinely broken (ingestion disabled), the
   converted test still fails — the helper must not paper over a real defect.
4. Full file green: `pytest tests/test_background/test_hippocampus.py`.

## Verification gates (FORK-WORKFLOW.md)

Both are load-bearing and neither may be skipped — the repo has already retracted a
"98 passed" that came from a leaked `VIRTUAL_ENV`.

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
#   the path MUST contain ormah-wt-<slug>/
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Compare the result against the measured `upstream/main` baseline of 13 known-red tests
(memory `988fca91`), not against a plan's description of it. Expect 12 red, with
`test_new_file_triggers_ingestion` the one removed.

That count is corroboration, not proof. The baseline itself contains this 50/50 flake, so a
single suite run could land on 12 by luck alone. **The decisive evidence is step 2** — the
converted test passing under injected latency that makes the old one fail. A suite run
showing 12 red without that step proves nothing.

## Out of scope

- The other 38 `time.sleep` call sites in `tests/`. Most are legitimate (deliberately
  widened race windows, simulated slow subprocesses) and none has a demonstrated CI failure.
- The other 12 known-red baseline tests, including the `~/.config/ormah/.env` environment
  leak — that deserves its own issue.
- `test_importance_scorer.py::test_importance_range_with_new_signals`, which reddens PR #229
  for an unrelated reason.
- Any change under `src/`.
