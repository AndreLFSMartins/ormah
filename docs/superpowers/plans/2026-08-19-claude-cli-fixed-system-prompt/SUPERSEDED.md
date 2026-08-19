# SUPERSEDED — do not execute this plan

**Date:** 2026-08-19
**Replaced by:** [`../2026-08-19-claude-cli-stable-cache-prefix/`](../2026-08-19-claude-cli-stable-cache-prefix/00-overview.md)

This plan (6 files, 1592 lines) was written against a design that has since been withdrawn. Two independent reasons, both established by measurement rather than review:

1. **Its premise does not reproduce.** It targeted a 3.0× saving from `--system-prompt` alone (7,726 → 110 `cache_write`). Re-measured on `claude-haiku-4-5` with the adapter's real argv: `--system-prompt` alone is **1.19×**. The saving lives in `--setting-sources ""`, and the two flags together are **2.19×**. The spec's five-arm matrix carries the numbers.

2. **Its quality gate approves without measuring.** An independent audit extracted all 26 code blocks, compiled and ran the 5 Python ones against synthetic corpora. Findings: `set -- $spec` does not word-split under zsh, so a leg could compare a file with itself and PASS (`B1_after_identical_to_before → PASS`); total AFTER regressions read as clean because the ingest arm anchors on a flawless BEFORE; injection detection matched titles only, never content, so `PWNED!` scored clean; refusals scored as the safe label on all four batched arms; up to 8% of judgment flips passed, i.e. ~5 irreversible merges per 100 pairs; `combine({})` returned PASS.

**Do not reuse its Task 2 tests.** Three of the five assert that the prompt constant contains the substring the constant contains — rewriting the sentence with the same meaning breaks them, inverting the meaning while keeping the substring passes them. The replacement plan explains what to test instead.

**Still valid inside this directory, if any part is ever revived:** the distance→similarity conversion (`1 - d²/2`), the vector query shape, the pair-shape keys, every CLI entry point and flag, and `combine()`'s failure-over-invalidity precedence — all audited and found correct. Everything else in the gate is superseded, and the audit findings above apply before any of it is reused.
