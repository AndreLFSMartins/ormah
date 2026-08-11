# Design — ingest Batch budgeted on conversation length (ADR-0001 Amendment 3)

Date: 2026-07-25 · Target: `local-main` (Beta-only) · Status: awaiting review

Implements **ADR-0001 Amendment 3** plus the ⛔ Amendment 2 invariant it declares indivisible,
plus the minimum provider-fit work that makes the new default safe on any LLM.

## Provenance of every number

| label | meaning |
|---|---|
| `[ADR]` | measured in the Amendment 3 session: 92 files / 65 MB sampled from a 1279-file, 899.5 MB corpus; tokens are `chars/4` estimates |
| `[M1]` | measured 2026-07-25 in this session: 40 largest transcripts of 2973, replayed through `parse_transcript` at `flush_bytes=60000`, 1400 slices |
| `[M2]` | arithmetic extrapolation over the same 40 files — not simulation; realised values will differ |
| `[M3]` | live probe against the local Ollama server, `gemma3:12b-it-qat` |
| `[C]` | read directly from the code |

## Problem

`parse_transcript` budgets **raw transcript bytes** (`_would_overshoot`, `parser.py:255-262`) while the
Extractor only ever receives `safe_conversation` — what survives after `tool_use`, `thinking`,
`tool_result`, `progress` and `system` stripping. The budget spends itself on bytes no model reads.
Median payload is 842 tokens ≈ 5.6% of the 15K floor; 99.7% of slices land below the sweet spot and
none inside it `[ADR]`. Batching is not degraded — it is not happening.

## Decisions

1. **Budget on conversation length**, in cleaned chars, not byte offsets.
2. **Target stays 60000 chars (~15K tokens).** The sweet spot is a *quality* bound (multi-item recall
   under context rot), not a capacity bound — ADR-0001 Amendment 1 already rejected window-fraction
   sizing twice. Moving to ~30K is a **measured** follow-up (A/B on `eval/`), never speculative: the
   failure mode of overshooting is silently dropped memories.
3. **A second, independent raw-byte ceiling**, whose default comes from measurement (Task 1).
4. **`ingest_chunk_chars ≥ flush_chars`, enforced by a validator** — the ⛔ from Amendment 2, in this
   same change.
5. **Provider-fit minimum**, so the 60000 default is safe on any provider (see §Provider-fit).
6. **Rename with a loud warning**, not a transparent alias (see §Migration).

## Design

### 1 · Parser predicate (`src/ormah/transcript/parser.py`)

`_would_overshoot` splits into two predicates, both keeping the existing progress guard
(`_safe_len > 0`, i.e. a first turn is never refused):

```
_would_exceed_content(candidate_len)  ->  candidate_len > flush_chars
_would_exceed_raw(new_safe_end)       ->  (new_safe_end - start_offset) > max_raw_bytes
capped = either
```

`stop_offset` remains the only **absolute** limit (it refuses even the first turn) — unchanged.

**Candidate length** is tracked as an incremental prefix sum `_len_after[k]`, equal to
`len(_conversation_from_turns(turns[:k]))`, updated on every append. O(1) per boundary and exact.
This requires extracting a `_format_turn(turn)` helper from `_conversation_from_turns` so the two
cannot drift, guarded by a test asserting equality for every k.

**Commit-site asymmetry — the trap.** The three commit sites are not symmetric:

| site | candidate |
|---|---|
| `parser.py:301` (Codex `task_complete`) | `turns` as-is |
| `parser.py:332` (new user turn) | `turns` as-is |
| `parser.py:356` (terminal assistant) | `turns` **+ the pending turn** — the check runs *before* the append at `:359`, but the commit includes it |

Missing the third case under-counts the budget by a whole turn.

Rejected alternatives: recomputing `len(_conversation_from_turns(turns))` per boundary (loses the
anti-drift anchor); summing bare `len(turn.text)` (ignores the `"Role: "` prefix and `"\n\n"`
separators, so it budgets a quantity that is again not what the Extractor receives).

### 2 · Config surface (`src/ormah/config.py`)

| field | before | after |
|---|---|---|
| `session_watcher_flush_bytes` | 60000 bytes | **removed** |
| `session_watcher_flush_chars` | — | 60000 cleaned chars |
| `session_watcher_max_raw_bytes` | — | from Task 1 measurement |
| `ingest_chunk_chars` | 40000 | ≥ `flush_chars` (default decided in Task 1) |
| `ingest_timeout_per_10k_chars` | — | payload→timeout rate (see §Provider-fit) |
| `ingest_timeout_max_seconds` | — | absolute ceiling for a hung provider |

Validators: `flush_chars >= 1000`; **`flush_chars <= ingest_chunk_chars <= ingest_max_content_chars`**;
`max_raw_bytes >= flush_chars` (raw is always ≥ cleaned).

Call sites to update in `src/ormah/background/session_watcher.py`: `:803`, `:864`, `:889`, `:1105`,
`:1116`, `:1258`, `:1475`, plus the `_should_flush` docstring at `:785-793` (semantics unchanged —
still "idle or capped").

### 3 · Provider-fit (the part that makes 60000 safe on any LLM)

The batch size is provider-independent by decision (2). What *is* provider-dependent is **latency**
and **effective input window**. Three contained changes:

- **Payload-derived timeout.** `_extract_memories_llm` (`memory_engine.py:2862`) sends a variable
  payload against a fixed timeout and never uses the `timeout_hint_seconds` seam — even though that
  seam is in the base protocol (`llm/base.py:20`) and honoured by all three adapters `[C]`. Fix
  follows the existing idiom at `llm/pair_batch.py:86`:
  `hint = llm_timeout_seconds + rate * (len(chunk) / 10000)`, bounded by `ingest_timeout_max_seconds`.
  Provider-agnostic by construction: a slower provider simply gets proportionally more time.
- **Pin `num_ctx` in `OllamaAdapter`.** It sets `num_predict` (output) and never `num_ctx` (input)
  `[C]`, so the effective input window is the Ollama server's default — outside our control and
  unversioned. If a user's default is below the batch, the payload truncates **silently** and recall
  dies with no signal. That is the exact failure class this ADR chain exists to kill.
- **Document ~16K tokens of usable input window as the ingest minimum.** This is a far weaker and safer
  assumption than "assume 256K for everyone": `gemma3:12b-it-qat` advertises 131,072 `[M3]`, not 256K,
  and advertised ≠ effective. Enforcement is best-effort and per-adapter, not a uniform startup gate:
  for `ollama` the window is queryable (`/api/show` + the pinned `num_ctx`) so it can be checked and
  warned about; for `claude_cli` and `litellm` it is not introspectable, so the requirement is
  documentation only. Do not fabricate a check that cannot be performed.

### 4 · Migration

`session_watcher_flush_bytes` appears **nowhere outside tests** — not in the live `~/.config/ormah/.env`,
and no installer or template writes it `[C]`. The ADR's premise ("it is set in live installs") does not
hold. More importantly, a transparent alias would reinterpret a tuned value across incomparable units:
someone who set `200000` bytes would silently receive 200000 *chars*, 3.3× the sweet spot.

Decision: rename, and if `ORMAH_SESSION_WATCHER_FLUSH_BYTES` is present in the environment, emit an
explicit startup `WARNING` that the unit changed and the value was ignored. Today `extra: "ignore"`
swallows it with no signal, so this is strictly better than the status quo. Fire once (module-level
flag) — `Settings()` is constructed many times.

## The ADR's ⚠️ — resolved

The ADR marks the interaction with ADR-0003 `should_rewind` / leading-orphan as unverified and in scope
before implementation.

**Argument.** `should_rewind = leading_orphan AND safe_end_offset <= start_offset`. A cap only fires
with `_safe_len > 0`, which implies the safe boundary already advanced past the cursor. Therefore no
budget, on either axis, can produce a rewind. And `leading_orphan` is detected before any commit, so no
cap can precede it. The rule holds for the raw ceiling **only because it keeps the same progress
guard** — making either limit absolute would break it.

**Evidence.** 1400 real slices from the 40 largest transcripts: 0 violations of
`capped ⇒ safe_end_offset > start_offset`, 0 rewinds under cap `[M1]`.

This becomes a property test. The existing orphan/rewind tests must pass **unedited** — if any needs
changing, the premise has failed and the design must stop.

## Corrections owed to ADR-0001

Three statements in Amendment 3 are wrong and must be amended when this lands:

1. *"This replaces the accidental resource protection the byte budget was providing."* — There is no
   such protection to replace. The progress guard already lets a single oversized turn through: raw
   span per slice is p99 **3.5 MB** today `[M1]`, 58× the 60000 budget. The raw ceiling is a **new**
   constraint, not a replacement.
2. *"The constraint that forced sub-sweet-spot chunking is dissolved."* — Half true. ADR-0004 removed
   the **client** wait (202 Accepted). The **provider** timeout is alive: `claude_cli_timeout_seconds
   = 120`, `llm_timeout_seconds = 60` `[C]` — which is precisely what the `# timeout-safe payload per
   claude_cli call` comment on `ingest_chunk_chars = 40000` was protecting. Hence §Provider-fit.
3. *"Old env var honoured as a deprecated alias for one release, since it is set in live installs."* —
   It is set in no install, and honouring it across a unit change would be silently wrong. See
   §Migration.

## Measurements

Under today's byte budget, 1400 slices `[M1]`:

| | p50 | p90 | p99 |
|---|---|---|---|
| raw span per slice | 113,729 | 777,977 | 3,519,717 |
| cleaned chars per slice | 3,958 | 17,865 | 39,719 |

Estimated under a 60000-char content budget, same files `[M2]`: 1400 → 199 slices (**7.0× fewer
calls**; the `[ADR]` corpus-wide figure is 17.8×, this sample is biased toward large files). Raw span
per slice p50 1.4 MB · p90 5.4 MB · p95 6.5 MB · p99 16.3 MB · max 38.4 MB — which is what sizes the
ceiling in Task 1.

Live provider probe `[M3]`: 55,890 chars → 13,212 tokens evaluated, **no truncation**, 24.7s wall clock
with `num_predict=1` (prompt ingestion alone, before generating anything).

## Testing strategy

TDD. Existing tests assert on the **byte** axis and must be re-expressed in the new unit, not merely
kept green — 27 occurrences in `tests/test_background/test_session_watcher.py`, 33 in
`tests/test_background/test_session_watcher_flush.py`, 3 `max_bytes` in `tests/test_transcript/test_parser.py`.
A test that silently passes under both units is not testing the budget.

New tests:

1. `_len_after[k] == len(_conversation_from_turns(turns[:k]))` for every k — anti-drift.
2. The terminal-assistant site counts the pending turn (the asymmetry trap).
3. A tool-heavy transcript now batches **multiple user turns** into one slice, where today it yields one.
4. Committed conversation ≤ `flush_chars`, except the single-oversized-turn escape.
5. The raw ceiling binds independently: tiny content, huge raw span → capped by raw.
6. Property: `capped ⇒ safe_end_offset > start_offset`, on **both** axes.
7. Orphan/rewind suite passes unedited.
8. Validators: `flush_chars > ingest_chunk_chars` raises; deprecated env var warns.
9. Ingest passes a payload-proportional `timeout_hint_seconds`, bounded by the max.

## Sequencing

1. **Task 1 — measure, then choose numbers.** Implement the content predicate (TDD), replay the corpus
   with the real implementation, set `max_raw_bytes` from the realised p99, and time one real 60000-char
   extraction end-to-end against the configured provider. If it does not fit, the timeout rate — not the
   batch — is what adjusts.
2. Content predicate + re-expressed tests.
3. Raw ceiling + validators + migration warning.
4. `ingest_chunk_chars` + the Amendment 2 validator — **same change**, or every full batch splits into
   two chunk-blind calls.
5. Provider-fit: payload-derived timeout, `num_ctx` pin, minimum-window check.
6. Amend ADR-0001 with the three corrections above.

## Risks

- **Provider timeout** — the real gate; mitigated by step 5, measured in step 1.
- **Landing mid-drain.** ~408 stranded transcripts are still draining; landing this changes payload
  size mid-flight. Prefer landing after the drain completes.
- **Oversized single turn** still splits into chunks — inherent, pre-existing, and explicitly out of
  scope per Amendment 2 ("a delta that genuinely exceeds the sweet spot still splits").

## Where the work happens

Worktree cut from `local-main`; merge back to `local-main`. **Beta-only by impossibility**, not
preference: `upstream/main` has no `max_bytes`/`_would_overshoot` in the parser and no
`session_watcher_flush_bytes` in config `[C]` (local-main is 521 commits ahead). No upstream PR is
possible. Keep the parser change as an isolated commit so it can be cherry-picked once the ADR-0004
seam lands upstream. `Tools/ormah` is the live Beta — never `git checkout` a branch in it.

## Out of scope (registered, not lost)

- ADR-0004 slice 3 — **descoped 2026-07-25**, do not replan. Memory `15575ebe`.
- `claude_cli_adapter` cancellation-epoch/deadline race — open defect, unfiled. Memory `e9251cba`.
- Raising the target to ~30K tokens — needs an `eval/` A/B first.
- pytest contamination of the production log; `ORMAH_DELETION_ENABLED=false`.
