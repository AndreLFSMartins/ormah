# Review relevance is not confirmed use

**Date:** 2026-08-16 · **Issue:** #220 · **Branch:** `fix/220-confirmed-use` (worktree `../ormah-wt-220`)
**Origin:** council-pr round of 2026-08-16, RUN_ID `a28837bc-a0350936-d4eab805`, Codex finding #1
(`high`, conf. 0.99), accepted and re-verified at source.

## The defect

`_claim_confirmed_use` accepts the claim for *any* whisper event. Only an **injected** event
represents use. The session-start review path deliberately hands the agent a **non-injected**
event, and the claim takes it — so judging a memory that was never shown reinforces it as if it
had been used.

Three legs, each verified at source:

1. `_find_review_candidate` (`context_builder.py:94`) selects `whisper_log` rows with
   `was_injected = 0` — memories Ormah held back and never surfaced.
2. `_REVIEW_FRAMING` (`context_builder.py:26-36`) hands that `whisper_log_id` to the agent and asks
   for `submit_feedback(..., signal=1, source="implicit")`. The question posed is *"would this have
   been useful?"* — a relevance adjudication, not a use.
3. `_claim_confirmed_use` (`memory_engine.py:2554`) filters only on `whisper_log_id is not None`,
   `signal == 1` and `source in _CONFIRMED_USE_SOURCES`. `implicit` is on that allowlist and
   **nothing checks `was_injected`**. The claim is taken and `_record_confirmed_use` advances
   `access_count`, `last_accessed`, `last_review` and `stability`.

This is fabricated retention entering through the review door — precisely what #220 exists to close.

**Introduced by this branch.** Before `e8675bb` (`fix(lifecycle): record confirmed use from
qualified positive feedback`), `submit_feedback` did not reinforce at all. This is a regression of
the PR itself, not inherited debt, which is why it blocks the merge.

Live surface: the 2026-08-15/16 session received this review framing twice (`whisper_log_id` 20100
and 20645).

## The invariant already exists in prose

`schema.sql:229-230` states that `_log_feedback_candidates` hardcodes `was_injected = 1` and that
both claiming callers write an affinity row in the same transaction. Measured against the code, two
of the three callers already satisfy `was_injected = 1` and only `submit_feedback` does not:

| Caller | Event it passes | Guarantee today |
|---|---|---|
| `recall_node` (`memory_engine.py:691`) | created by `_log_feedback_candidates` | `was_injected = 1` hardcoded (`memory_engine.py:618`) |
| `session_watcher` (`session_watcher.py:591`) | rows from its own query | `AND wl.was_injected = 1` (`session_watcher.py:447`) |
| `submit_feedback` (`memory_engine.py:2631`) | whatever the agent supplies | **none** |

`was_injected = 1` is therefore already the de-facto precondition of the claim. It was never
written as code.

## The fix

One condition, in the single place that writes a claim — `_claim_confirmed_use`:

```sql
INSERT INTO confirmed_use_claims (whisper_log_id, node_id, claimed_at)
SELECT wl.id, ?, datetime('now')
FROM whisper_log wl
WHERE wl.id = ? AND wl.was_injected = 1
ON CONFLICT DO NOTHING
```

`SELECT changes()` remains the verdict. It returns `0` when the event is `was_injected = 0` (no row
selected) and `0` when the claim already existed (`ON CONFLICT`). Both mean the same thing to the
caller — *do not reinforce* — and neither needs to be distinguished from the other.

### Why here and not elsewhere

Rejected alternatives, both considered and declined:

- **Gate inside `submit_feedback`** (load `wl.was_injected` in `_load_feedback_whisper_log_row`,
  which already runs the SELECT, and skip the claim when it is `0`). Narrower and free of a query,
  but leaves the invariant unenforced centrally — a fourth caller reopens the hole.
- **A distinct `source` for review** (`_REVIEW_FRAMING` asks for `source="review"`, kept off the
  allowlist). A barrier by convention, not by construction: the global instructions and three
  surface instruction files all teach `implicit`, and an agent that types `implicit` reopens the
  hole silently, with no test that would catch it.

The chosen fix is fail-closed by construction, atomic, costs no extra round-trip, and covers every
present and future caller.

## Blast radius

- `recall_node` — unchanged. Its events are `was_injected = 1` by construction.
- `session_watcher` — unchanged. Its query already filters to injected rows.
- `submit_feedback` on an **injected** event — unchanged. Still claims, still reinforces.
- `submit_feedback` on a **review** event — claims nothing, reinforces nothing. This is the fix.

### What deliberately does not change

`affinity`, `signals` and `review_log.answered` are still written for review feedback. Judging
relevance still teaches Ormah; only the four lifecycle fields stop moving. The return message to
the agent is unchanged: the feedback *was* recorded.

### Accepted consequence — the legacy fallback

`submit_feedback` without `whisper_log_id` resolves to the node's most recent whisper row, injected
or not. Under this fix, when that most recent row is `was_injected = 0`, no claim is taken even if
an older injected row exists — a legitimate reinforcement is silently lost.

**Accepted, deliberately** (André, 2026-08-16). Failing closed is the correct side to err on under
the at-most-once contract, and the fallback already documents itself as not exact. Changing the
fallback's selection would also move which event `affinity` and `signals` attach to, which is a
distinct defect from this one and would ride into the PR uninvited. A test fixes the consequence as
expected behavior.

## Tests

RED before any `src` change, in `tests/test_engine/test_submit_feedback.py`:

1. **The defect.** A `was_injected = 0` event plus `submit_feedback(+1, "implicit",
   whisper_log_id=...)` → no row in `confirmed_use_claims`, and all four lifecycle fields unchanged
   in SQLite **and** in the markdown. This is the test that fails today.
2. **The control.** The same with `was_injected = 1` → claim taken, lifecycle advances. Without it,
   deleting the whole function would still pass test 1.
3. **The legacy-fallback consequence.** Newer rejected row, older injected row, no `whisper_log_id`
   → `affinity` still attaches to the newer row (unchanged), no claim, no lifecycle movement.
4. **Neighbour regression.** `recall_node` and the watcher still reinforce — existing coverage,
   re-run rather than rewritten.

## Scope

- `src/ormah/engine/memory_engine.py` — the SQL, plus the `_claim_confirmed_use` docstring, which
  today enumerates the fail-closed conditions and must name this one.
- `tests/test_engine/test_submit_feedback.py` — the four tests above.

Out of scope: the legacy fallback's event selection; the evidence gate's `NO_REPRO_COMMAND`
discards; the missing `run-evidence` stage in the installed council `dist`.

## Verification

- `./.venv/bin/python -m pytest tests/ -v` from the worktree. **Never** bare `python -m pytest` and
  **never** `make test` — both resolve to the `Tools/ormah` venv and measure `local-main`, not the
  worktree. Confirm first: `./.venv/bin/python -c "import ormah; print(ormah.__file__)"` must print
  a path under `ormah-wt-220/src/`.
- `make lint` (`ruff check src/ tests/`) before the commit.
- Re-invoke `/council-pr` from inside the worktree after the fix, as a fresh round 1.

## Related

- `docs/superpowers/plans/2026-08-14-issue-220-confirmed-use/00-overview.md` — the at-most-once
  contract and why `affinity`/`signals` cannot derive confirmation.
- `~/.council/state/r-spade-ormah-683b05e/council-result.md` — the 2026-08-16 round, including the
  refutation of Codex finding #2 and the caveats about the evidence gate.
