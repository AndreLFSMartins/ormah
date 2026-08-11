---
status: accepted
---

# The relevance gate is a provenance label the Extractor emits and code drops — no per-user calibration

The **Ingest** had no relevance gate: the extraction prompt *asked* for valuable memories but nothing
*rejected* anything, so whatever the **Extractor** returned that was not a near-duplicate got stored.
One dogfood day produced **461 nodes (16.5%) of third-party API/SDK documentation** memorized as
`fact` — material the session was *processing*, not knowledge the user produced. The root cause is that
the extractor cannot tell **what the user produced** from **what merely passed through the session**.

We add a gate on the **provenance** axis — **Material** (input restated as knowledge; findable in
docs/code regardless of this conversation) vs **Product** (a decision, correction, discovered bug,
complaint, outcome the session itself produced, even about an external tool). See
[CONTEXT.md](../../CONTEXT.md). The **Extractor** labels every candidate `provenance=material|product`
*inside the same extraction call* (no extra LLM call); a trivial deterministic filter drops `material`
before write. The gate **errs toward keeping Product**: Material recurs (the same fact re-extracts
later, so a false drop self-heals), but a Product often happens once and never recurs, so dropping it
is the expensive error.

The load-bearing decision is what we **do not** build: **no per-model calibration, no shipped safe-list,
no model detection, no setup-time eval.** We trust the label unconditionally for whatever provider is
configured, guarded only by one kill-switch env var (`ORMAH_INGEST_RELEVANCE_GATE`, drop **on** by
default). This reverses an earlier design in this same discussion that gated the drop behind an offline
per-model calibration and a live safe-list lookup — machinery that (a) an end-user installing a wheel
cannot run, (b) freezes at release time and silently disables the gate for every model not pre-blessed,
and (c) exists to prevent a false-drop whose cost is low because memory is *over*-abundant and Material
*recurs*. The only residual risk trust-the-label leaves is **systematic bias** (a model that always
mislabels a whole category of Product as Material) — which recurrence does *not* heal — and that is
exactly what the pre-ship eval catches, with the kill-switch covering an exotic model in the field.

This ADR exists because this exact trade-off keeps getting re-litigated ("não é a primeira vez que
fazemos essa discussão"); the calibration/safe-list instinct is the thing that returns, and this
record is meant to stop the loop.

## Considered options

- **Per-memory salience score (0–1) from the same model, drop below threshold:** rejected — the model
  that over-extracted the documentation also thinks it is valuable, so it scores Material high. The
  fox guards the henhouse; "is this valuable?" is the wrong question.
- **Session budget (max N memories per slice):** rejected as the *gate* — it caps volume uniformly,
  cutting a rich real session alongside a doc-dump, and still leaves N pieces of the same garbage. It
  attacks volume, not provenance. (May return as an orthogonal anti-storm ceiling, not as relevance.)
- **Type-by-source filter (doc/subagent sessions may only emit decision/preference):** rejected — its
  intent (provenance) is right, but it needs to *detect* "this is a material-processing session," and
  the user works with others' docs/code all day, so that detection is the undetectable part.
- **Offline per-model calibration + shipped safe-list, drop only for blessed models:** built, then
  rejected — see above. Over-engineering: elaborate machinery that lands OFF for the median user.
- **Provenance label in-prompt, code drops Material, trust the label + kill-switch:** accepted —
  smallest diff that attacks the root, auditable (labels are emitted, not self-suppressed), and honest
  about the cheap-false-drop economics.

## Consequences

- Gate correctness is validated **offline, pre-ship**, not at runtime and not by anyone reading a
  production log (nobody does). The eval is a **regression fixture of real store nodes** hand-labeled
  Material/Product, with **asymmetric thresholds**: Product preserved ≥98% (the expensive error is a
  hard gate), Material dropped ≥80% (the cheap error is a soft target).
- Post-ship validation on the Beta re-runs the doc's own queries: the 461 Material nodes fall toward
  zero while `decision`/`preference` types stay flat.
- The drop is **auditable**: labels are emitted for every candidate and the drop happens in code, so a
  false-drop of Product is recoverable/measurable — the reason self-suppression by the model was
  rejected.
- The gate is **demand-side**. It reduces how much the (fully serial) ingestion lane must process, but
  does not change the ingestion architecture; multi-window throughput/concurrency is a separate,
  committed next track, to be designed *after* measuring whether the reduced arrival already closed the
  backlog.

## Amendment 2026-07-20 — ship in SHADOW mode, not drop-on-by-default

Dev Council PR review (Cursor + Codex, both NO-SHIP) sharpened the rollout: shipping with the drop
**on by default** exposes real memory to an *unvalidated* label on the active provider/model before any
real-store evaluation or restore path exists. The trust-the-label decision above stands; what changes is
the **activation default**:

- The gate ships **on by default but in SHADOW mode** (`ingest_relevance_gate_enforce=False`): it emits
  the label and **records every would-drop to the quarantine ledger, but keeps the memory.** Zero
  irreversible risk; the shadow ledger becomes the real-store evaluation data for the active
  provider/model. This reconciles the ADR's "gate on by default" with "do not destroy before you have
  validated on real data."
- Enforcement (actually dropping) is **code-disabled** for this release: a module constant
  `_RELEVANCE_ENFORCE_AVAILABLE = False` gates the drop, so setting `ingest_relevance_gate_enforce=true`
  logs a warning and stays in shadow. This ships the release **shadow-only** — no reachable destructive
  path — rather than trusting a default + docs to hold back a loaded gun (Dev Council NO-SHIP, 2026-07-20).
  The ship-gate scorer was also fixed here so mixed material+product labels cannot false-pass, and
  quarantine records carry a `mode` (`shadow`|`enforced`) field so the canary can separate would-drops
  from real drops.
- Enforcement is enabled only **after** an **enforce-gate** — flip `_RELEVANCE_ENFORCE_AVAILABLE=True`
  once: (a) the in-context eval passes on a **real-store** corpus for the active provider/model (the seed
  corpus is not enough), (b) the quarantine ledger is included in Ormah's **backup/restore** with an
  idempotent re-ingestion command AND the append is crash-durable (flush+fsync before the drop commits),
  and (c) representative validation exists for each shipped provider/model.
- When enforcing, the drop is **fail-open**: a candidate is dropped **only if** its recovery record was
  durably written; if the quarantine write fails, the memory is **kept** (a false-drop-without-trail is
  the exact irreversible loss the ledger exists to prevent; Material self-heals via re-extraction).

This does not reopen calibration/safe-list (still rejected). It gates *when* the trusted label is allowed
to destroy, not *how* the label is produced.

## Amendment 2026-07-21 — lean the rollout: runtime flag, no code guard, best-effort ledger

The 2026-07-20 amendment above over-corrected. Re-grilling it against **what this system actually is**
(local-first, single-user, periodic backups) collapsed most of the enforce-gate machinery, and a live
ship-gate run supplied the missing evidence. What supersedes the section above:

- **No `_RELEVANCE_ENFORCE_AVAILABLE` code guard.** It made the gate *inert* — shipping a feature whose
  entire purpose (dropping Material) is disabled by a constant no user can flip. Removed. The **runtime
  flag `ingest_relevance_gate_enforce` is the switch**: default `False` = SHADOW (record the would-drop,
  keep the memory), `true` = actually drop. The flag is flipped only **after** a shadow run's would-drops
  are reviewed on real data — that review, not a code constant, is the enforce-gate.
- **The heavy durability plumbing is dropped, because it guards a loss this system does not fear.** The
  gate drops **only Material**, and Material is the *cheap* category by this ADR's own economics: it
  recurs and a false drop self-heals via re-extraction. So the ledger is a **best-effort measurement
  log** (audit / false-drop canary), **not** a recoverability guarantee. fsync-before-drop, a file lock,
  backup inclusion, and a replay command — the 2026-07-20 enforce-gate prerequisites — are **not built**:
  they are durability redundancy for precious data, and the dropped data is not precious. (They were
  never implemented; `record_dropped` was always a plain best-effort append.)
- **Kept: fail-open on an exception.** If the best-effort ledger write *raises*, the Material is **kept,
  not dropped**. This is one cheap branch, not plumbing — the single guard against a drop-with-no-record
  — and it costs nothing on a system where keeping an extra Material is free.
- **Kept and fixed: the ship-gate eval.** It remains the *only* real safeguard of trust-the-label (it
  catches systematic bias — the one error recurrence does not heal). The scorer had a second bug beyond
  the mixed-label fix: it scored `product_preserved` as "the extractor emitted a clean product label,"
  conflating **extraction recall** with the **gate's action**. The gate drops a product only if it is
  labeled `material`; an extraction *miss* (`[]`) is not a false-drop. Fixed to `product_preserved :=
  "material" not in labels` (a mixed `[material, product]` emission still counts as not-preserved, so the
  mixed-label fix survives).

**Evidence (why lean is safe here).** Live ship-gate run, `claude_cli` + `claude-haiku-4-5`, seed corpus
(23 material + 23 product): **0/23 Product mislabeled as `material`** — zero drops in the dangerous
direction. `material_dropped = 0.913`. The mechanical FAIL (`product_preserved 0.957 < 0.98`) was one
extraction *miss* (a vague complaint the extractor didn't store), not a gate false-drop — the scorer
artifact fixed above. With the corrected scorer the run PASSES (`product_preserved 1.000`,
`material_dropped 0.913`). Caveat: the seed corpus is clean and small (n=23/class); the **shadow run on
the Beta generates the real-store corpus for free**, and its would-drops are reviewed before the flag is
flipped to `true`. Calibration/safe-list stays rejected.
