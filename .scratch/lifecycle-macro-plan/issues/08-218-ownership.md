# 08 — ownership of #218 fixes 1–2

Type: grilling
Blocked by: 02

## Question

[#218](https://github.com/r-spade/ormah/issues/218)'s fixes 1 (`submit_feedback` records a real
strength) and 2 (`token_overlap` varies with `overlap_ratio`) **stand** per the Discord ruling,
but have no owner and no PR (fix 3, cross-channel comparability, is deferred until #220–#223
produce better data). They are not blockers for #220–#223, but #220's `auto_heuristic` exclusion
is explicitly *conditional* on #218 — the interim source-qualification rule discards the 45
verbatim `node_id`/`title`/`sentence` matches, the strongest use evidence in the system.

Decide: does André pick fixes 1–2 up, and if so where in the sequence (after #223? interleaved?),
or do they stay unowned upstream? Blocked by ticket 02 because the #218 ruling itself is an
unconfirmed transcription.
