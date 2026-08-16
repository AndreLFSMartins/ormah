# 04 — reference regime for store measurements

Type: grilling

## Question

André's store historically runs `llm_provider=ollama` + session watcher; @r-spade runs
`llm_provider="none"` + watcher off — **none of the four pairwise jobs has ever executed on his
machine** (dossier §7.4). Any acceptance test phrased in store measurements is ambiguous until it
names its regime.

Decide: which regime do acceptance criteria and store-derived numbers reference across the
lifecycle work — André's regime, @r-spade's, or both explicitly labeled? Does anything in
#220–#223's acceptance criteria need re-phrasing as a result?
