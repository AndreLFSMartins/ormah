---
status: accepted
---

# Ingest batches are sized to a recall sweet spot, not the context window; delta ordered first

When ormah moved server-side extraction to `claude -p` (Haiku, 200K window), the naive instinct
was to fill the window per **Batch** to amortize the fixed extraction-prompt overhead. We decided
instead to size each **Batch** to a **recall sweet spot of ~15–20K tokens of conversation** — far
below the window — and to place the accumulated conversation **delta at the top of the prompt** with
the extraction instructions last. Reason: extraction is multi-item (extract *all* memories), and
"context rot" degrades multi-item recall well before the window fills (>20% degradation is measured
by 8K tokens on frontier models; extraction stays clean below ~15K and only mildly degrades to ~30K).
Filling the window would silently drop memories. The exact size is a **measured, tunable knob**
(`session_watcher_flush_bytes`), not a hardcoded constant — the literature gives the ~15–20K bracket;
the test calibrates the point on ormah's own extraction prompt and transcript shape.

## Considered options

- **Near the context window (~60K+ / "30% of 200K"):** rejected — maximizes overhead amortization but
  lands in the region where multi-item recall drops, so batches silently miss memories.
- **Very small batches (per-turn / a few K):** rejected — this is the status quo that burned Max quota;
  the fixed `claude -p` prompt overhead dominates each call.
- **~15–20K sweet spot + delta-first ordering:** accepted — big enough that the fixed prompt overhead
  is a small fraction, small enough to keep extraction recall high.

## Consequences

- The flush trigger's **size** dimension is bounded by this sweet spot as a ceiling; **age** (~10 min)
  and **session boundary** (compaction/end) drive freshness. See [CONTEXT.md](../../CONTEXT.md).
- Prompt assembly is **order-sensitive**: conversation delta first, instructions last (Anthropic's
  long-context guidance reports up to +30% quality from this ordering). A later refactor that reorders
  the extraction prompt must preserve delta-first.
- A session whose pending delta exceeds the sweet spot is split into multiple batches, not sent as one
  oversized call.

## Amendment (2026-07-17): the sweet spot is a model-agnostic conservative default, not a per-model window

Two clarifications from a later grilling, prompted by "with Haiku I can send a bigger window" and "how
do we size for a user's unknown model":

- The ~15–20K number was **never calibrated on ormah's own extraction** — it rests on frontier-model
  literature. That gap is **moot**, not blocking: the conservative default (`flush_bytes = 60000` ≈ 15K
  tokens) is safe on *any* real provider (any Claude tier, any Ollama model with ≥32K window), so
  shipping it needs zero knowledge of the user's model. Upstream ships `llm_provider = "none"`, so it
  dictates no model at all — the default *must* be model-agnostic.
- Do **not** size the batch by the model's advertised window (the instinct this ADR already rejected as
  "near the context window"): a bigger window does not buy cleaner multi-item extraction. Per-model
  tuning, if ever wanted, is **documentation in `.env`** ("for model X we measured Y"), never automatic
  window-fraction sizing and never a runtime per-user calibration.

## Amendment 2 (2026-07-17): the extraction chunk must be ≥ the flush batch — `chunk_chars ≥ flush_bytes`

From the Track 1 ("holística", deferred-tracks ledger) grilling. The batch is sized to the recall
sweet spot so the **Extractor** sees the whole delta *in one reasoning context*. But
`_extract_memories_llm` then splits that batch again at `ingest_chunk_chars = 40000`, and
`session_watcher_flush_bytes = 60000` > 40000 — so **every batch that closes at the size ceiling is
chopped into 2 chunks by design**, and each chunk is extracted with a **chunk-blind prompt**
(`_INGEST_LLM_PROMPT.format(conversation=chunk)`). That re-introduces exactly the cross-chunk blindness
the sweet-spot sizing existed to avoid: a fact decided in chunk 1 and superseded in chunk 2 is extracted
stale, because the second call never sees the first.

- The 40000 `chunk_chars` is a **timeout artifact**, not a recall choice — the comment says
  "timeout-safe payload per `claude_cli` call". [ADR-0004](0004-async-ingest-nudge-server-cursor.md)
  removes the client timeout and sizes the server timeout generously, which **dissolves the constraint**
  that forced sub-sweet-spot chunking. Once it ships, a full 60000-char batch (~15K tokens = this ADR's
  own clean-recall target) can extract in a single call.
- The durable fix is the **invariant `flush_bytes ≤ chunk_chars`**, enforced by a `config.py` validator
  (today's validator only guards `flush_bytes ≤ ingest_max_content_chars`, so the mismatch returned
  silently). Raise `ingest_chunk_chars` default to ≥ `session_watcher_flush_bytes` (60000). A future
  larger sweet spot must raise both together — chunking below the batch is never correct.
- ⛔ **Ordering (hard — for planning):** fixed sequence **P1 gate ([ADR-0002](0002-relevance-gate-provenance.md)) →
  [ADR-0004](0004-async-ingest-nudge-server-cursor.md) → this change.** Do **not** plan or ship this
  before ADR-0004 lands: while the client timeout still exists (135s httpx), a single 60K-char call can
  time out → the freeze-and-re-post loop ADR-0004 is fixing. Raising `chunk_chars` is safe *only* once
  the client no longer waits.
- **Scope:** this only removes multi-chunk blindness for steady-state batches (≤ sweet spot). A delta
  that genuinely exceeds the sweet spot (session-boundary catch-up, huge paste) still splits — that
  residual "tail" is left as a measurement-gated sub-track (holística map-reduce), not solved here.
  The Track 1 value is **coherence of superseded-alone facts (mode b)**, *not* dedup — dedup is already
  covered by `_is_duplicate_memory`, the `duplicate_merger`, and ADR-0003.

## Amendment 3 (2026-07-25): the budget is measured on the wrong quantity — bytes of transcript, not conversation the Extractor sees

This ADR's whole premise is that a Batch should hold ~15–20K tokens *of conversation*. The
implementation budgets **raw transcript bytes** instead: `parse_transcript`'s `_would_overshoot`
(`parser.py:255-261`) compares `(new_safe_end - start_offset) > max_bytes` — a byte-offset delta —
while the Extractor only ever receives `safe_conversation`, i.e. what survives after `tool_use`,
`thinking`, `tool_result`, `progress` and `system` content is stripped. The budget therefore spends
itself on bytes no model ever reads, and **the sweet-spot target this ADR exists to hit is missed by
more than an order of magnitude.**

**Measured 2026-07-25** on the live corpus — 337 slices produced by replaying `parse_transcript` with
the production `flush_bytes = 60000`, over 92 files / 65 MB sampled across every size decile of the
1279-file, 899.5 MB non-subagent corpus:

| quantity | p10 | median | p90 |
| --- | --- | --- | --- |
| payload (~tokens) | 277 | **842** | 4,722 |
| user turns per slice | 1 | **1** | 2 |
| raw bytes ÷ conversation chars | — | **27.6×** | 93.6× |

Corpus figures above are `chars/4` estimates over 92 of 1279 files. The 2026-07-25 replay
(40 largest transcripts, 1400 slices) corroborates them at a different sample: median cleaned
chars 3,958 vs the 842-token (≈3,368-char) median reported here.

- **75.1% of extraction calls carry exactly one user turn**; 92.6% carry one or two.
- The median payload is **842 tokens ≈ 5.6% of the 15K floor**. **99.7% of slices land below the
  sweet spot; none land inside it.** Batching is not degraded — it is **not happening**. The rejected
  option "very small batches (per-turn / a few K)" is what actually ships today.
- Extrapolated over the corpus: **~9,843 extraction calls, against ~552 if each Batch filled the
  sweet spot — ~17.8× the intended call volume**, each call below the recall target. Both goals of
  this ADR are missed at once, and the second (recall) silently.

**Mechanism.** Median raw bytes consumed per slice is 91,382 — *above* the 60000 budget. That is not a
bug in the cap; it is `_would_overshoot`'s `_safe_len > 0` guard, i.e. this ADR's own "a single turn
larger than max_bytes is committed anyway" rule. One tool-heavy turn exhausts the entire byte budget
by itself, so **no second turn can ever join the batch.** The flush trigger's size dimension is
bounded by a quantity uncorrelated with the thing it means to bound.

**Why tuning cannot fix it.** The raw→clean ratio ranges from ~3× (prose-heavy session) to ~93×
(tool-heavy session). No single `flush_bytes` value in raw bytes serves both: a value large enough to
fill the sweet spot on a tool-heavy session overshoots a prose-heavy one by ~30×. This is an **axis
error, not a calibration error** — consistent with the Amendment above ("do not size the batch by the
model's advertised window"), the batch must be sized by the quantity that actually drives recall.

### Decision

Budget the Batch on **conversation length the Extractor will receive**, not on transcript bytes.

- `parse_transcript` gains a conversation-length budget; `_would_overshoot` tests the accumulated
  cleaned length at each candidate safe boundary instead of the byte delta. The information is already
  in scope at the decision point (`turns` / `_conversation_from_turns`, `parser.py:199`).
- **The number 60000 was right; the unit was wrong.** ~60000 *chars of conversation* ≈ 15K tokens =
  this ADR's clean-recall target. Because the unit changes, `session_watcher_flush_bytes` becomes a
  misnomer and must be renamed outright. The old name is set in **no** install: it appears nowhere
  outside tests, no installer or template writes it, and it is absent from the live
  `~/.config/ormah/.env`. A transparent alias would also be wrong on its own terms — it would
  reinterpret a *tuned* value across incomparable units (a deliberate `200000` bytes would silently
  become 200000 chars, 3.3× the sweet spot). The old variable is therefore ignored, with an explicit
  startup warning, since `extra: "ignore"` would otherwise swallow it with no signal at all.
- **Keep a second, independent raw-byte ceiling.** A pure content budget leaves the raw span
  unbounded: at the measured p90 ratio, 60000 clean chars spans ~5.6 MB of transcript. Resource safety
  (read/parse cost, memory) is a *different* concern from recall and needs its own bound — two limits,
  whichever binds first.
  The byte budget was **not** providing this protection, contrary to what this amendment first
  assumed: the progress guard (`_safe_len > 0`) commits a single oversized turn regardless. A
  design-time replay (2026-07-25, 1400 slices over the 40 largest transcripts) found the realised
  raw span per slice was already p99 **3.5 MB** under `flush_bytes = 60000` — 58× the budget. The
  raw ceiling is therefore a **new** constraint, not a preserved one, and it is not set at that
  design-time p99: an implementation resampling (2026-07-26, 420 slices from the 200 largest of
  2919 live transcripts, 0 invariant violations) put p99 there at **9,844,378 B**, and the ceiling
  is set at **`session_watcher_max_raw_bytes = 10,000,000`**. It binds on 4/420 (0.95%) of
  large-file slices and 4/2562 (0.16%) corpus-wide — 10 MB is only the 5th-largest of those 420
  slices, and corpus-wide it is p99.84, not p99 (corpus p99 = **3,809,368 B**), so the tail it
  guards is thin, not densely sampled. (For scale, the corpus's single largest transcript is 38.4 MB.) The ceiling bounds
  pathological cost without competing with the content budget in normal operation.

### Consequences and sequencing

- ✅ **Amendment 2's invariant landed in this change.** `ingest_chunk_chars = 40000 < flush_bytes =
  60000` held in the live config until this change: the prescribed `flush_bytes ≤ chunk_chars`
  validator had never been added, and the only one that existed guarded `flush_bytes ≤
  ingest_max_content_chars` (100000) — exactly the silent gap Amendment 2 named. `ingest_chunk_chars`
  is now `60000` (≥ the renamed `session_watcher_flush_chars`), with a `config.py` validator
  enforcing `session_watcher_flush_chars ≤ ingest_chunk_chars`, so the cross-chunk blindness
  Amendment 2 named cannot silently re-open.
- ✅ **Amendment 2's ordering precondition is now satisfied.** It required ADR-0004 to land first,
  because a 60K-char call under the old 135s client timeout would time out. ADR-0004 slice 1 (merge
  `7cd15cb`) made the nudge return **202 Accepted** with durability before the response
  (`routes_ingest.py:42`), so the client no longer waits on extraction.
  The **client-side** constraint is dissolved. The **provider** timeout is not:
  `claude_cli_timeout_seconds = 120` and `llm_timeout_seconds = 60` are still live, and the ingest
  path sent a variable payload against them without ever using the `timeout_hint_seconds` seam that
  the base protocol defines and all three adapters honour — which is exactly what the
  `# timeout-safe payload per claude_cli call` comment on `ingest_chunk_chars = 40000` was
  protecting. Raising the payload to ~60000 chars therefore requires deriving the timeout from the
  payload (base + rate, the `pair_batch.py` idiom), bounded for a hung provider. Measured on a local
  12B: 24.7s of prompt evaluation alone for 55,890 chars, before generating a token.
  What shipped: `ingest_timeout_per_10k_chars = 17.5`, `ingest_timeout_max_seconds = 900`, with the
  hint computed as `min(max(baseline, derived), max)`. The strongest evidence for the rate is a real
  timed `_extract_memories_llm` call on `ollama` (`gemma3:12b-it-qat`, 2026-07-26): 75.2 s on a
  50,577-char slice against its own derived hint of 87.8 s — 85.7% of budget consumed. Scaled by
  size to a full 60000-char Batch, that observation projects to 87.7 s against a 92.4 s budget (5.4%
  headroom) at the earlier rate of 4.9; raising the rate to 17.5 gives 175.7 s for a full Batch —
  **2.00×** that scaled observation (not the 2.31× min→max spread; full 2.31× coverage would need
  rate 21.6 / 202.6 s).
  This rate is **not a fitted slope**, and should not read as one: the `claude_cli` sample is n=5
  (max 74.6 s, 0 failures), the `ollama` sample is n=1, cold-vs-warm was never established, and
  across the `claude_cli` sample r = −0.274 — latency spread 131% against payload spread 17%, with
  the slowest call carrying the *smallest* payload. It is a conservative bound on worst-case excess,
  not a measured payload→latency relationship; real slices cluster at 50–58K chars, so the missing
  correlation is plausibly a lack of lever rather than noise.
  The cost: 175.7 s exceeds `claude_cli`'s 120 s adapter baseline, so the live provider now waits
  ~176 s instead of 120 s (still under the 900 s cap). The measurement was not taken at steady state
  — a drain was active (1 running, 39 pending) — though all 427 recorded failures in that run were
  pre-provider `no_safe_boundary`, not timeouts. None of `ingest_timeout_per_10k_chars`,
  `session_watcher_max_raw_bytes`, or `session_watcher_flush_chars` existed at the base commit
  `bfc34fa`; the derived-timeout axis is new in this change, so every value here is a raise against
  what actually ships (the `ollama` adapter's 60 s baseline), not a tightening.
- Expect **~18× fewer extraction calls** on the same corpus, with each call inside the recall bracket
  rather than far below it — a cost *and* a quality change in the same direction. The ~552-call figure
  is arithmetic, not simulation: short sessions cannot fill a Batch, so the realised gain is lower.
- Tests that previously passed small caps (e.g. 300-byte `flush_bytes`) asserted on the byte axis and
  were re-expressed in the new unit (e.g. `flush_chars=300`). This was the intended blast radius: no
  test that exercises the cap kept passing unmodified across the unit change.
- ✅ **Resolved: the budget cannot interact with `should_rewind` / leading-orphan.**
  `should_rewind == leading_orphan AND safe_end_offset <= start_offset`. A cap only fires with
  `_safe_len > 0`, which implies the safe boundary already advanced past the cursor, so **no budget
  on either axis can produce a rewind**; and `leading_orphan` is detected before any commit, so no
  cap can precede it. This holds for the raw ceiling **only because it keeps the same progress
  guard** — making either budget absolute would break it, and `stop_offset` remains the only
  absolute limit. Verified on 1400 real slices (0 violations) and pinned as a property test.
- The token figures use a `chars/4` estimate, not a tokenizer. The conclusion survives a ±50% error in
  that constant; the exact "5.6%" does not.
- ⚠️ **Residual: the capacity guard is a heuristic, not a proof.** Ingest refuses to send a prompt it
  estimates cannot fit the configured `ollama` window, and a boot validator rejects a window too small
  for the largest emittable payload — so a *misconfiguration* cannot produce silent truncation. But the
  estimate counts characters (2.0 chars/token), and a tokenizer can spend more than one token on a
  single code point (emoji, rare scripts), so no character-based divisor is an upper bound. An
  adversarially token-dense transcript can still overflow. Closing this needs model-aware token
  counting — a tokenizer dependency and per-model handling — and is deliberately out of scope here.
- ⚠️ **Residual: only `ollama` is guarded.** It is the one provider whose window this project pins.
  `claude_cli` and `litellm` windows are not introspectable from here, so for them the ~16–18K-token
  requirement is documentation only: a `litellm` model configured below it can still truncate silently
  and advance the cursor. A `litellm` guard needs a model-registry lookup, which is its own change.
- ⚠️ **Open question: is the payload-derived timeout the right abstraction at all?**
  `ingest_timeout_max_seconds = 900` is already the liveness backstop against a wedged provider, and
  [ADR-0004](0004-async-ingest-nudge-server-cursor.md)'s cancellation epoch removed the *shutdown*
  reason for a per-call timeout — `session_watcher.py` now cancels an in-flight call via the epoch
  rather than waiting the provider out. So the payload-derived term protects nothing that is
  otherwise unprotected; it only decides how early to give up on a call that may still be working, on
  the calibration above. Deliberately not pivoted mid-plan — the cleanest expression of "let it run"
  would be for the derived term never to bind.
