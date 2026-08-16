# 05 — validating the `auto_llm_judge` confirmed-use path with the watcher off

Type: grilling

## Question

#191 admits `auto_llm_judge` as confirmed use, but André turned the session watcher off, so his
store converges to the all-implicit regime — the `auto_llm_judge` path in #220 will be
**effectively untested on live data** on his side (dossier §7.5).

Decide: is synthetic/integration coverage enough for that path, or does validation require turning
the watcher back on for a bounded window (or another route entirely)? Whose store, for how long,
and what would count as the path "surviving contact"?
