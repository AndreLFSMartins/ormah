# Ormah — Maintenance Context

How the graph is curated *after* nodes exist: what gets linked, merged, flagged as contradictory,
consolidated, decayed and forgotten. Distinct from the **Ingest** seam, which produces the nodes
(see [`CONTEXT-MAP.md`](../../../CONTEXT-MAP.md)).

## Language

**Maintenance**:
The set of background jobs that curate an existing graph rather than grow it. Each job is
independent, runs on its own schedule, and fails on its own without blocking the others.
_Avoid_: cleanup, housekeeping, GC (those name only the destructive half)

**Pair**:
Two memory nodes considered together — the unit of work for linking, dedup and conflict detection.
A Pair is **unordered**: it is normalized to a sorted `(a, b)` before anything is recorded about it,
so the same two nodes never produce two records.
_Avoid_: couple, tuple, match

**Candidate filter**:
The cheap, LLM-free pre-selection that decides which **Pairs** are worth asking about: vector
neighborhood plus a **Composite score** threshold, plus same-type and same-space rules. It answers
*"is this worth a question?"*, never *"is this a duplicate?"*.
_Avoid_: pre-filter (ambiguous — it also names the similarity cutoff inside it)

**Composite score**:
The similarity number the **Candidate filter** computes from embedding similarity, title similarity
and token overlap. It is a **pre-verdict** signal — it exists to rank candidates cheaply, and it
knows nothing the **Pair verdict** does not know better.
_Avoid_: confidence, certainty (it measures resemblance, not the correctness of a judgement)

**Pair verdict**:
The LLM's judgement about one **Pair** — today a *boolean* (`is_duplicate` true/false for dedup;
an edge type or `none` for linking). It carries no gradation: the judge either says duplicate or it
does not. Distinct from the **Composite score**, which is what got the Pair to the judge.
_Avoid_: score, confidence, LLM score (there is no number)

**Auto-merge threshold**:
The **Composite score** above which a confirmed duplicate is merged without asking anyone. Its role
is to decide *how much automation a Pair earns* — it is a bar applied **after** the **Pair verdict**,
using a signal computed **before** it.
_Avoid_: confidence threshold, merge score

**Merge proposal** *(retired — ADR-0006)*:
Was a stored request for a human to decide a **Pair** the **Pair verdict** called a duplicate but
whose **Composite score** fell under the **Auto-merge threshold**. No longer produced: a Pair either
clears the threshold and merges, or nothing happens. The term survives only to read older decisions.
_Avoid_: suggestion, candidate (a candidate has not been judged yet; a proposal had been)

**Review queue**:
The surface where a human resolves proposals by approving or rejecting them. Its usefulness is
entirely a function of whether a human actually works it — an unworked queue is behaviorally a
**no-op**, because an unresolved proposal leaves the graph exactly as a discarded one would. Since
ADR-0006 it carries only synthetic-pattern proposals.
_Avoid_: inbox, backlog

**Veto** *(retired — ADR-0006)*:
A human's recorded "no" on a **Pair** — a decision of a different *kind* from a **Pair verdict**, not
a more confident version of one. A Veto was valid **only while both memories were unchanged**: any
edit to either node's content ended it, because the Veto was about those texts, not about those ids.
Retired with the **Merge proposal** that produced it: with nothing to reject, there is no Veto. The
definition is kept because the concept is the one the dead memo tables were really built for, and
naming it is what let the real defect be seen.
_Avoid_: rejection (names the click, not the standing decision), not_duplicate

**Watermark**:
The `seq` of the last fully-processed node for one job, used to select only newer nodes on the next
run so coverage **converges** instead of rescanning the store. It solves *cost and convergence* —
"have we looked at everything yet" — and solves nothing about *authority*: it cannot express that a
**Pair** was decided, only that it was reached.
_Avoid_: cursor (that is the Ingest term for a different thing), checkpoint, offset

**Pair memo**:
A per-**Pair** record of a past decision, kept so the decision is not re-made. Distinct from a
**Watermark**: a memo remembers *what was decided about this Pair*, a Watermark remembers *how far
the scan got*. Conflating the two is what produced write-only memo tables — machinery built for
authority, then replaced by a mechanism that only ever addressed convergence.
_Avoid_: cache, checked table

## Relationships

- The **Candidate filter** proposes **Pairs**; the LLM issues a **Pair verdict**; the
  **Auto-merge threshold** decides whether a confirmed duplicate is merged or dropped (ADR-0006 —
  there is no third outcome).
- A **Watermark** bounds *which nodes are scanned*. A **Pair memo** bounds *which Pairs are
  re-judged*. Neither substitutes for the other — and since ADR-0006 dedup and conflict keep no memo
  at all, relying on the Watermark alone.
- No signal in this context carries human authority any more. That is the deliberate outcome of
  ADR-0006, not an oversight: the only human decision the graph accepts is the value of the
  **Auto-merge threshold**.

## Where the vocabulary already caused a wrong diagnosis

The **Pair memo** tables for dedup and conflict were written but never read, and the first reading of
that was "the memo lost its reader". It had not: the **Watermark** deliberately replaced the memo for
*convergence*, which is all background dedup needed. What was actually missing was a home for the
**Veto** — a different concept that happened to share the table. One word for two ideas hid the real
defect for two ADR revisions.

## Flagged ambiguities

- **"Confidence"** is used loosely across this area for the **Composite score**, which is not a
  confidence in any judgement. The glossary keeps the two apart deliberately.
- **Resolved (ADR-0006):** the **Review queue** no longer holds **Merge proposals**. A Pair either
  clears the **Auto-merge threshold** or nothing happens to it.
- **Open decision:** whether the **Auto-merge threshold** — a **Composite score** bar — is the right
  gate at all, given that it overrides a **Pair verdict** using a signal computed before the verdict
  existed. Deferred deliberately by ADR-0006: the coherent answer (let the verdict decide) is blocked
  by the verdict's measured error rate, so the gate stays until the judge is better or better
  measured.
