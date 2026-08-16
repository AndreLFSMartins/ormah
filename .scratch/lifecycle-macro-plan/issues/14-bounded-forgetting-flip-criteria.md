# 14 — flip criteria for bounded forgetting (#28 / PR #31)

Type: grilling

## Question

Bounded forgetting is fully built (7 protection gates, cap backstop, soft-delete + retention
window, hard purge) but ships `False` and has **never been exercised on either store**. The gate
is explicit: it waits until the lifecycle signals are corrected — flipping early would
protect/delete nodes on bad data (dossier §6). PR #31 is now a draft with the gate documented.

Decide the *criteria*, not the flip: what measurable conditions after #220–#223 land make the
flag safe to enable, and what un-drafts PR #31 (e.g., N days of corrected signals on a live
store, promotion path observed working, specific store metrics)? Which store proves it, given the
two regimes (see ticket 04)?
