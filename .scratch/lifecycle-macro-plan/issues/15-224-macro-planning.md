# 15 — macro planning for #224 (system-level conflict owner)

Type: grilling
Blocked by: 03

## Question

[#224](https://github.com/r-spade/ormah/issues/224) carries the Q3 conflict rulings and is
**blocked by #81 (incremental watermarks) and #87 (batched pairwise LLM calls)** — do not expand
the candidate space before those land. André's implementations are already up as PRs #133 and #95
(ticket 03).

Once ticket 03 resolves (#133 landed, #95 rebased): decide the macro plan for #224 — sequencing
relative to the #220–#223 wave, whether André owns it, how the acceptance criteria in the dossier
(§5) split into PRs, and whether #194's date fix folds in (ticket 13).
