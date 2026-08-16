# 06 — draft the #209 failure-mode analysis

Type: research
Status: resolved

## Question

André owes [#209](https://github.com/r-spade/ormah/issues/209) a failure-mode analysis of the
ruled four-way policy (clear duplicate → auto-merge with audit + undo · uncertain → leave both ·
contradiction → preserve and connect · rare core/identity ambiguity → bounded human review)
**before implementing** — promised in-thread, not yet posted (dossier §5/§7).

Research: analyze the four-way policy's failure modes against the actual codebase (proposal
generation, merge machinery, audit log, undo surface) and the measured store state (3,773 pending
rows). For each failure mode: trigger, blast radius, detectability, mitigation. Cover at minimum:
wrong auto-merge of near-duplicates, undo fidelity after downstream edits, proposal invalidation
races on merge/delete, queue re-growth under "leave both alone, reconsider later", and the
interaction with #223's promotion path (active-only candidacy). Deliverable: a draft comment for
#209, ready for André's review.

Asset: `../assets/209-failure-modes.md`

## Answer

Draft comment written to `../assets/209-failure-modes.md` (8 failure modes, each with trigger /
blast radius / detectability / mitigation, every code claim cited file:line). Top failure modes:
(1) contradiction misclassified as clear duplicate — dedup never consults `contradicts` edges or
`conflict_checked`, so one noisy LLM answer stands between a contradiction and a destructive merge;
(2) undo is asymmetric — the kept node's pre-merge content is overwritten by LLM text and never
snapshotted, so "undo" cannot restore it; (3) approve-vs-invalidate race — proposals flip to
`approved` before the merge runs and `execute_merge` returns a string on missing nodes, yielding
silent approved no-ops. Single most important guardrail: **symmetric undo** (snapshot + restore the
kept node too) before any autonomous-merge widening — it converts every other failure from
permanent loss into a recoverable event. Six open questions for the maintainer are listed at the end.
