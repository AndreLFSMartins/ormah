# Issue #218 — `signals.strength` becomes an ordinal evidence scale

**Date:** 2026-08-26
**Issue:** [#218](https://github.com/r-spade/ormah/issues/218) — *signals.strength has no variance in any channel*
**Base:** `upstream/main` @ `90c431e`. Every code claim below was read from that tree.
**Unblocks:** [#272](https://github.com/r-spade/ormah/issues/272) (heuristic never claims confirmed use), [#191](https://github.com/r-spade/ormah/issues/191) (strength-threshold promotion)

---

## 1. Why this exists, and why now

`signals.strength` is declared as a per-event confidence score. In practice it is a tier label
stored as a float: `submit_feedback` hardcodes `1.0`, three of the four heuristic match kinds
return fixed constants, and the fourth saturates before its own entry gate can admit it.

This was reached from #272, not from #218 directly. #272 reports that the heuristic usage
detector never claims confirmed use — 0 of 1,629 positive whisper references reinforce a memory.
Its premise is that two lines are missing. **That premise is wrong**, and the correction is what
routed the work here:

- `_CONFIRMED_USE_SOURCES = frozenset({"explicit", "implicit", "auto_llm_judge"})`
  (`memory_engine.py:56`) deliberately omits `auto_heuristic`. `_claim_confirmed_use` fail-closes
  on `source not in _CONFIRMED_USE_SOURCES`, so #272's "minimal fix" — calling the claim from the
  heuristic block — would return `False` silently.
- The #220 design states the reason: *"`auto_heuristic` stays excluded until #218 provides signal
  calibration"*, and lists `auto_heuristic` admission (#218) under **Out of scope**.
- Contract 9 pins it: `test_confirmed_use_contract.py:247` and `test_session_watcher.py:2432`
  (`"auto_heuristic confirmed use — it must not"`).

So #272 is a design debt coming due, and #218 is the stated precondition. **#218 has no owner and
no work**: no PR, no branch, none of the 26 worktrees, no spec, and both defects it names are
still live even on the Beta (`session_watcher.py:170`, `memory_engine.py:3802` on `local-main`).

## 2. Measurements

Read-only snapshot of the Beta store, 2026-08-26. `_node_usage_evidence` is **byte-identical**
between `local-main` and `upstream/main`, so the match distribution describes upstream behaviour
(FORK-WORKFLOW evidence gate).

Positive heuristic pairs on injected whispers, by match kind:

| match | pairs | share |
|---|---|---|
| `token_overlap` | 1,587 | 97.4% |
| `node_id` | 29 | 1.8% |
| `sentence` | 13 | 0.8% |
| `title` | 0 | 0% |

`overlap_ratio` over those 1,587 rows: **min 0.50, max 7.583, mean 1.452, median 1.167**, with
**602 rows (38%) at ≥ 1.50**.

Evidence coverage, all `signals` rows:

| source | rows | rows without `evidence` | recomputable from `evidence` |
|---|---|---|---|
| `transcript_watcher_heuristic` | 3,538 | 0 | 3,538 |
| `transcript_watcher_llm_judge` | 1,698 | 0 | 1,698 |
| `implicit` | 118 | 0 | 118 |

## 3. `strength` has no readers

Swept `src/`, `ui/`, `schema.sql` and `db.py` on `upstream/main`. Every occurrence of `strength`
is a write path (INSERT column list, parameter passing) or an unrelated concept (`belief strength`
in `tool_schemas.py`, the force-simulation local in `GraphView.tsx`). There is no `SELECT` over it
and no `row["strength"]`.

Two consequences that shape this spec:

- **Regression risk is near zero** — there is no consumer to break.
- **#218 alone produces no observable behaviour change.** Its entire value is unblocking #272 and
  #191. Acceptance is therefore about the stored distribution and the tests that pin it, never
  about a promotion that starts happening. The behavioural proof arrives with #272.

## 4. Design

### 4.1 Semantics

**`strength` is the strength of the evidence backing that row's polarity, on a single ordinal
scale, comparable in rank across channels.** It is not a calibrated probability, and the module
docstring says so explicitly.

**Load-bearing assertion: the channel dominates within-channel confidence.** A verbatim match
outranks any LLM judgment however confident; an LLM judgment outranks any agent self-report. This
is #218's own argument (*"a judge reading the finished response is stronger evidence than a
model's in-flight claim about its own retrieval"*) carried to its conclusion. Bands are disjoint
per channel; native confidence modulates **within** a band.

This is the point a reviewer should attack first. It is a design judgment, not a measurement.

### 4.2 The ladder

| band | channel / evidence | mapping |
|---|---|---|
| `1.00` | `explicit` — the user was actually asked | constant |
| `0.98` | heuristic `node_id` — short id printed verbatim | constant |
| `0.94` | heuristic `title` verbatim | constant |
| `0.92` | heuristic `sentence` verbatim | constant |
| `0.82–0.90` | `auto_llm_judge` | affine `[min_confidence, 1.0] → [0.82, 0.90]` |
| `0.80` | `implicit` — agent self-assessment | constant |
| `0.40–0.78` | heuristic `token_overlap` | asymptotic, see 4.3 |
| `0.00` | any row with `polarity = 0` | convention |

Four embedded decisions:

1. **The judge's domain is `min_confidence`, not the literal `0.75`** — the band re-anchors if the
   setting moves. An affine rescale preserves all rank information; only the absolute reading is
   lost, which this design already declines to claim.
2. **`polarity = 0` stores `0.00`.** Today the judge writes its confidence on those rows
   (`MIN(strength) = 0.35` in the store). A row that asserts nothing has no evidence strength. The
   raw confidence survives in `evidence.confidence` — nothing is lost.
   This is safe because `polarity` is set only when `promoted = confidence >= min_confidence`, so
   **every judge row with non-zero polarity already has `confidence >= min_confidence`**. Without
   that property a confidence-0.10 judgment would rank above `implicit`; it cannot arise.
3. **`token_overlap` stays strictly below `implicit`**, even at its best. This is the most
   arguable boundary on the ladder — a 12-token distinctive overlap is plausibly stronger evidence
   than a self-report. The conservative choice is taken, consistent with #220's fail-closed
   posture, and it is what gives #272 a clean floor.
4. **Values are module constants, and `affinity_implicit_weight` is not reused.** That setting is
   the affinity boost weight; coupling them makes changing one silently change the other. #218
   cites it as precedent for the value `0.80`, not as its source.

### 4.3 `token_overlap` must be asymptotic, not clamped

`overlap_ratio = len(overlap) / min(len(candidate_tokens), 12)` is **unbounded above** — the
denominator caps at 12 while the numerator does not. Any linear map therefore needs an arbitrary
clamp, and every clamp recreates the saturation defect #218 reports. A clamp at 1.50 would tie 38%
of observed rows.

```python
_OVERLAP_FLOOR, _OVERLAP_SPAN, _OVERLAP_K = 0.40, 0.38, 1.0

def token_overlap_strength(ratio: float) -> float:
    """Monotone over [gate, +inf), asymptotic to the band ceiling.

    Ties reappear only where float64 can no longer separate the tail: f(36.5) is
    0.7799999999999999 and f(37.0) is exactly the 0.78 supremum. The observed
    overlap_ratio maxes at 7.583, five times below that, so the whole real domain
    is separated -- 344 distinct values over ratios 0.5..39.9 at 0.1 steps.
    """
    return _OVERLAP_FLOOR + _OVERLAP_SPAN * (
        1.0 - math.exp(-_OVERLAP_K * max(ratio - 0.5, 0.0))
    )
```

Against the observed distribution:

| `overlap_ratio` | old | new |
|---|---|---|
| 0.500 (gate) | 0.85 | 0.400 |
| 0.550 | 0.85 | 0.419 |
| 1.167 (median) | 0.85 | 0.585 |
| 1.500 | 0.85 | 0.640 |
| 3.000 | 0.85 | 0.749 |
| 7.583 (max) | 0.85 | 0.780 |

Variance in all seven histogram buckets, and the supremum `0.78` sits below `implicit = 0.80` by
construction rather than by clamp.

The supremum is strict in exact arithmetic but not in float64: `f(36.5) = 0.7799999999999999` and
`f(37.0) = 0.78` exactly. Ties therefore return above `overlap_ratio ~= 37` — five times the
observed maximum of 7.583, and 344 distinct values over ratios 0.5..39.9 at 0.1 steps. Stated
rather than hidden, because "no ties" is the overclaim #218 is about.

### 4.4 Where the ladder lives

New module `src/ormah/signal_strength.py`, holding the constants, the three channel functions, and
the docstring carrying section 4.1.

It is shared between `session_watcher.py` and `memory_engine.py`. Putting it in the engine would
make the watcher import engine internals; putting it in `lifecycle.py` would mix *evidence
strength* with *memory stability*, which is the exact confusion #218 is about. A leaf module with
one purpose, importable by both, is the seam.

### 4.5 The three write sites

| # | site | change |
|---|---|---|
| 1 | `_node_usage_evidence` (`session_watcher.py:111-160`), four `return` | constants + `token_overlap_strength(ratio)` |
| 2 | judge record build (`session_watcher.py:549`) | `confidence` → `judge_strength(confidence, min_confidence, polarity)` |
| 3 | `submit_feedback` signals INSERT (`memory_engine.py:2792`) | literal `1.0` → `feedback_strength(source, signal)` |

```python
def judge_strength(confidence: float, min_confidence: float, polarity: int) -> float:
    if polarity == 0:
        return 0.0
    if min_confidence >= 1.0:
        return _JUDGE_HI
    span = (confidence - min_confidence) / (1.0 - min_confidence)
    return _JUDGE_LO + (_JUDGE_HI - _JUDGE_LO) * max(0.0, min(1.0, span))
```

`polarity = 0` is unreachable through `submit_feedback`'s public surfaces — every external route
passes `FeedbackRequest` with `signal: Literal[1, -1]` (`routes_agent.py:187`), and the MCP
adapter posts to `/agent/feedback` rather than calling the engine. Only a direct Python caller
could pass `0`. The convention is enforced wherever polarity can actually vary — `judge_strength`
and `feedback_strength` take it and return `0.0` for zero. `token_overlap_strength` does not: its
only caller sits in the `referenced` branch, and the no-match branch already returns `0.0`
structurally. A polarity parameter there would be dead code.

### 4.6 Backfill

Existing rows carry old-ladder values. The 1,587 `token_overlap` rows at `0.85` land **inside the
new judge band** (`0.82–0.90`), so the column would go on lying — now about which channel produced
the row. #218 is the issue that the column lies; shipping a fix that leaves 97% of rows lying is
half a fix.

The recompute is **exact, not estimated**, and every row is covered (section 2):

| channel | recompute source |
|---|---|
| `transcript_watcher_heuristic` | `evidence.match` + `evidence.overlap_ratio` |
| `transcript_watcher_llm_judge` | `evidence.confidence` + **the row's own `evidence.min_confidence`** |
| `implicit` / `explicit` | `source` + `polarity` |

The judge records `min_confidence` on every row, so the backfill uses the value in force when the
row was written, not the current setting.

Mechanics: an idempotent migration in `startup()`, alongside `_seed_stability_from_access_count`
and `_migrate_identity_tiers` (the existing pattern of running before the server serves), guarded
by a `meta` version key. Only `strength` is written; `evidence` and `polarity` are untouched.
Because `evidence` survives intact, the migration is **re-runnable**: a later revision of the
ladder recomputes from the same source. There is no lossy path.

Cost accepted: this writes to user data to repair a column with no reader. Nobody is misled today.
The alternative — leave historical rows and document them — keeps #272 correct either way, since
the watcher skips rows that already carry a heuristic signal and history never re-enters the claim
path. Migration is chosen because the cost is low and the benefit is the column ceasing to lie.

## 5. Tests

TDD, red before green.

1. **Disjoint bands** — property test across every channel: each produced `strength` falls inside
   its declared band, and no two bands overlap. Section 4.1's assertion as an executable invariant.
2. **`token_overlap` separates the real domain** — `f(0.5) == 0.40`; strictly increasing over the
   sampled real distribution (0.5, 0.55, 1.167, 1.5, 3.0, 7.583); `f(7.583) < 0.80`; and no tie
   anywhere below `overlap_ratio = 37`, the float64 limit measured above. Plus the test that
   catches the original bug #218 names: `f(0.5) != f(1.8)` — today both are exactly `0.85`.
3. **Judge** — affine over `[min_confidence, 1.0]`; `polarity == 0 ⇒ 0.0`; `min_confidence` read
   from the row, not the global (fixture with two rows carrying different `min_confidence`).
4. **`submit_feedback`** — `explicit` and `implicit` store different values (today both `1.0`);
   `signal == 0 ⇒ 0.0`.
5. **Backfill** — idempotent (run twice, same result); exact against a fixture store of known
   evidence; non-interfering (`evidence` and `polarity` byte-identical afterwards).
6. **#220 regression** — the whole `test_confirmed_use_contract.py` suite stays green. `strength`
   has no reader, so no behaviour may change. A failure there falsifies the write-only premise and
   sends this design back.

**Acceptance**, given that #218 produces no observable behaviour change: those six green, plus the
post-backfill distribution showing real variance in every channel.

## 6. Out of scope

Admitting `auto_heuristic` into `_CONFIRMED_USE_SOURCES` · calling `_claim_confirmed_use` from the
heuristic commit block · the `session_watcher.py:495` judge suppression — all of that is **#272**,
which follows once `strength` means something. Also out: the FSRS reinforcement formula, any
promotion rule, and #191's threshold policy.

## 7. Workflow constraints

Per `FORK-WORKFLOW.md`:

- clean island cut from `upstream/main`, in its own worktree; **never** `git checkout` a
  contribution branch inside `Tools/ormah` (launchd `com.ormah.server.dev` serves it)
- island gets its own `.venv`; run the import gate and a clean `HOME` before trusting any test
  number
- push to `fork`, never `upstream`; remotes keep their current names
- this spec lives under `docs/superpowers/`, inside the pre-push `PROTECTED` allowlist, so it
  cannot leak into the PR

## 8. Register

**Verified** (read from `upstream/main` @ `90c431e` or measured on a read-only store snapshot):
the `_CONFIRMED_USE_SOURCES` allowlist and its fail-closed branch · the #220 design text and
Contract 9 · #218 having no PR, branch, worktree or spec · `strength` having no readers across
`src/`, `ui/`, `schema.sql`, `db.py` · the match-kind and `overlap_ratio` distributions · full
`evidence` coverage · `polarity != 0 ⇒ confidence >= min_confidence` in the judge · `signal:
Literal[1, -1]` on every public surface · `docs/superpowers/` inside `PROTECTED`.

**Inferred:** that the 1,587 `token_overlap` positives are mostly weak evidence — argued from
#218's saturation analysis, not measured against ground truth.

**Assumed:** the ladder's ordering and its specific constants. Defensible design judgment, not
measurement. `implicit` ranking below the judge is inherited from #218's argument and was never
tested.

**Check before trusting:** whether the maintainer accepts "channel dominates confidence" as the
ordering rule — it is the one premise the whole ladder rests on, and rejecting it collapses the
design back to per-source thresholds.
