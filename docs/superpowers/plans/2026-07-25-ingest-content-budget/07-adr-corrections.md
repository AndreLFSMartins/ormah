# Task 7: Correct the three statements this work falsified in ADR-0001

**Files:**
- Modify: `docs/adr/0001-batch-size-and-ordering.md` (Amendment 3, lines 123-165)

**Interfaces:**
- Consumes: the measurements from Task 6 and the property test from Task 2.
- Produces: an ADR whose Amendment 3 matches what was actually built and measured.

An ADR that keeps a falsified claim is worse than no ADR: the next person re-derives from it. All three
corrections are load-bearing — each one changed a decision in this plan.

- [ ] **Step 1: Correct the resource-protection claim**

In the Decision section, the third bullet currently ends:

> This replaces the accidental resource protection the byte budget was providing.

Replace that sentence with:

```markdown
  The byte budget was **not** providing this protection, contrary to what this amendment first
  assumed: the progress guard (`_safe_len > 0`) commits a single oversized turn regardless, so the
  realised raw span per slice was already p99 **3.5 MB** under `flush_bytes = 60000` — 58× the
  budget (measured 2026-07-25, 1400 slices over the 40 largest transcripts). The raw ceiling is
  therefore a **new** constraint, deliberately set at the measured p99 so it bounds pathological
  cost without competing with the content budget in normal operation.
```

- [ ] **Step 2: Correct the "constraint dissolved" claim**

The Consequences section currently claims Amendment 2's ordering precondition is fully satisfied:

> The constraint that forced sub-sweet-spot chunking is dissolved.

Replace that sentence with:

```markdown
  The **client-side** constraint is dissolved. The **provider** timeout is not:
  `claude_cli_timeout_seconds = 120` and `llm_timeout_seconds = 60` are still live, and the ingest
  path sent a variable payload against them without ever using the `timeout_hint_seconds` seam that
  the base protocol defines and all three adapters honour — which is exactly what the
  `# timeout-safe payload per claude_cli call` comment on `ingest_chunk_chars = 40000` was
  protecting. Raising the payload to ~60000 chars therefore requires deriving the timeout from the
  payload (base + rate, the `pair_batch.py` idiom), bounded for a hung provider. Measured on a local
  12B: 24.7s of prompt evaluation alone for 55,890 chars, before generating a token.
```

- [ ] **Step 3: Correct the migration claim**

The Decision section currently says the old env var must be honoured:

> old env var honoured as a deprecated alias for one release, since it is set in live installs

Replace with:

```markdown
  renamed outright. The old name is set in **no** install: it appears nowhere outside tests, no
  installer or template writes it, and it is absent from the live `~/.config/ormah/.env`. A
  transparent alias would also be wrong on its own terms — it would reinterpret a *tuned* value
  across incomparable units (a deliberate `200000` bytes would silently become 200000 chars, 3.3×
  the sweet spot). The old variable is therefore ignored, with an explicit startup warning, since
  `extra: "ignore"` would otherwise swallow it with no signal at all.
```

- [ ] **Step 4: Close the ⚠️ open question**

The Consequences section ends with an unverified item about ADR-0003. Replace that bullet with:

```markdown
- ✅ **Resolved: the budget cannot interact with `should_rewind` / leading-orphan.**
  `should_rewind == leading_orphan AND safe_end_offset <= start_offset`. A cap only fires with
  `_safe_len > 0`, which implies the safe boundary already advanced past the cursor, so **no budget
  on either axis can produce a rewind**; and `leading_orphan` is detected before any commit, so no
  cap can precede it. This holds for the raw ceiling **only because it keeps the same progress
  guard** — making either budget absolute would break it, and `stop_offset` remains the only
  absolute limit. Verified on 1400 real slices (0 violations) and pinned as a property test.
```

- [ ] **Step 5: Add a provenance line to the measurement table**

Under the Amendment 3 evidence table, add:

```markdown
Corpus figures above are `chars/4` estimates over 92 of 1279 files. The 2026-07-25 replay
(40 largest transcripts, 1400 slices) corroborates them at a different sample: median cleaned
chars 3,958 vs the 842-token (≈3,368-char) median reported here.
```

- [ ] **Step 5b: Record the two capacity residuals the plan could not close**

Both were raised by the council and accepted; an ADR that omits them would overstate the guarantee.
Add to Consequences:

```markdown
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
```

- [ ] **Step 6: Verify no other claim in the amendment is now stale**

```bash
./.venv/bin/python -m pytest tests/ -q
grep -n "flush_bytes\|max_bytes" docs/adr/0001-batch-size-and-ordering.md
```

Every remaining mention of the old names must be historical (describing what *was* the case), not
prescriptive. Reword any that reads as a live instruction.

- [ ] **Step 7: Commit**

```bash
git add docs/adr/0001-batch-size-and-ordering.md
git commit -m "docs(adr-0001): correct three falsified claims in Amendment 3

Implementing the amendment falsified three of its own statements: the byte budget provided no
accidental resource protection to replace (realised raw span was already p99 3.5 MB); ADR-0004
dissolved the client timeout but not the provider timeout; and the old env var is set in no
install, so honouring it as an alias would translate a tuned value across incomparable units.

Also closes the amendment's open ADR-0003 question: a cap always implies an advanced safe
boundary, so should_rewind is unreachable from a cap -- verified on 1400 real slices and pinned
as a property test."
```

- [ ] **Step 8: Final gate before merge**

```bash
./.venv/bin/python -m pytest tests/ -q
ruff check src/ tests/
git log --oneline upstream/main..HEAD
```

Then `/council-pr`. Per `FORK-WORKFLOW.md` this work is **Beta-only** — there is no upstream PR,
because `upstream/main` has neither the parser budget nor the config field. Merge into `local-main`
with `git merge`, keeping the parser commit isolated for a future cherry-pick.
