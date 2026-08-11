---
status: accepted
---

# Recovery drops an orphan fragment rather than re-ingesting the whole transcript

The `leading_orphan` recovery existed to handle a **Cursor** left mid-response by an older version:
it rewound to offset 0 and re-ingested the *whole* transcript to re-pair a dropped response fragment
with its prompt (`session_watcher.py`, `cli_adapter.py`). Its trigger — the first assistant text in a
slice having no preceding user record — is *also* produced by a benign, permanent byte pattern:
an `assistant(stop_reason=end_turn)` **Safe boundary** followed by an
`assistant("API Error: Connection closed mid-response")` record *before* the next user turn. Because
the trigger is a permanent property of the file's bytes and no recovery marker was persisted, the
rewind fired every tick: one transcript re-extracted its 788K-char payload **36 times in 14 hours**
(bug [#149](https://github.com/r-spade/ormah/issues/149)), and the ~530KB tail past the boundary was
never ingested.

We gate recovery on **forward progress**: rewind only when a parse from the current offset yields
*no* progress (`safe_end_offset <= start_offset`). When the parse still advances the **Safe boundary**
past the cursor, the orphan fragment is **dropped and the cursor advances** — it is not recovered by
re-ingesting the file. A single shared predicate `should_rewind(result, start_offset)` in `parser.py`
gates both the watcher and the hook path so the two cannot diverge.

The load-bearing acceptance: we lose the tail of *one* mid-response fragment (its head was already
ingested before the cursor; the loss is bounded and self-limited) rather than pay a whole-file
re-ingest — which was the bug, not the cure. This ADR exists because "why don't we recover the tail?"
is a natural question that will re-open the choice; recording it stops the loop (cf. ADR-0002).

## Considered options

- **One-shot `legacy_recovered` marker (rewind once, persist, never again):** rejected — it stops the
  loop but still pays one whole-file re-ingest, still strands the tail (the fragment is dropped wrong),
  and adds a new state field to persist and migrate. Guard-on-progress needs none of that, and was
  verified not to loop: a genuinely no-forward-progress transcript parks via `NO_PROGRESS` (the
  reconcile park counter), it does not re-extract.
- **Bounded rewind to the previous safe boundary instead of 0:** rejected — in the genuinely-broken
  case there is no forward boundary to rewind *to*, and in the false-positive case there is nothing
  worth recovering; it adds machinery for a fragment not worth keeping.
- **Guard on forward progress, drop the fragment (accepted):** smallest diff, stateless, kills the
  expensive loop for both the small (observed) and the large (`> flush_bytes`) orphan — even a giant
  orphan advances the Safe boundary to the start of the first user line and so does not rewind — and
  recovers the previously-stranded tail as a side effect.

## Consequences

- The `leading_orphan` flag stays on `TranscriptResult`, but its *reaction* moves behind
  `should_rewind`; a false positive no longer costs anything.
- Provenance is **upstream**: the flag and the recovery live in `upstream/main` (`parser.py`,
  `session_watcher.py`, `cli_adapter.py`), so the fix is an upstream PR against #149, merged into the
  Beta (`local-main`) so the live runtime stops burning subscription immediately.
- Residual, far smaller than the bug: an advanced-but-below-`min_turns` payload can re-parse as a
  cheap no-op (parse only, no LLM, no duplication) until the cursor clears the threshold — covered by
  the regression test, not by new production code.
- Regression fixture (TDD, red first):
  `user → assistant(end_turn) → assistant(stop_sequence "API Error…") → user("continue")` asserts
  `should_rewind` is `False`, the cursor is monotonic across two ticks, no slice is extracted twice,
  and a large-orphan variant (`> flush_bytes` before the first user turn) still does not rewind.
