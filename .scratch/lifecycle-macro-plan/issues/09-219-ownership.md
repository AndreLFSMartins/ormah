# 09 — ownership of #219 (audit_log retention + VACUUM)

Type: grilling
Blocked by: 02

## Question

[#219](https://github.com/r-spade/ormah/issues/219) has a clear ruling (retention differs by
operation; `delete` snapshots get a configurable recovery window for privacy; `update`/
`mark_outdated` get a shorter default; operator-triggered VACUUM) but **no owner**. It is
independent of everything else in the cluster — cheap and self-contained (dossier §7.3), with
`whisper_log_cleanup.py` as the ready-made pattern.

Decide: does André take it, and where does it slot (it needs nothing from #220–#223, so it could
land any time)? Blocked by ticket 02 because the #219 ruling is an unconfirmed transcription.
