# Ingest — deferred tracks ledger

Single index of every ingestion path **not pursued now**, so nothing found during design gets lost and
no path has to be re-derived from scratch. Seeded 2026-07-17 from the grilling on
[problemas-de-ingestao.md](problemas-de-ingestao.md) + that doc's still-open "Issues a abrir".

**Decided (not deferred):** the relevance gate (P1) — see [ADR-0002](adr/0002-relevance-gate-provenance.md).
Tracked as **issue [#151](https://github.com/r-spade/ormah/issues/151)**; plan written
([2026-07-17-relevance-gate-provenance](superpowers/plans/2026-07-17-relevance-gate-provenance.md)).
**Shipped in SHADOW to the Beta 2026-07-21** (local-main, commit `e17818c`): the gate labels
`provenance` and records would-drops to a best-effort ledger but **keeps every memory**
(`ingest_relevance_gate_enforce=False`). Live ship-gate eval (claude_cli + haiku, seed corpus 23+23):
**0/23 Product mislabeled material**, product_preserved=1.000 / material_dropped=0.913, PASS.

**Left for a second moment (post-shadow):**
1. **Review the shadow would-drops on real Beta data** — the ledger at
   `memory_dir/relevance_gate_quarantine.jsonl` is the real-store corpus the seed eval could not
   provide. Confirm no real Product is being labeled `material` in messy real text.
2. **Flip the drop on:** set `ORMAH_INGEST_RELEVANCE_GATE_ENFORCE=true` (runtime env, **no code
   change**) once the review is clean. This is the only step that starts actually dropping Material.
3. **Lean upstream PR:** squash the branch into one clean commit on `upstream/main` (feature is
   portable — upstream's prose-JSON extraction carries `provenance`), push to `fork`, `/council-pr`,
   base `r-spade:main`. Deferred until convenient.
4. **Won't do (decided out, not deferred):** durability plumbing — fsync-before-drop, ledger file
   lock, ledger-in-backup, replay command. For a local-first single-user system the dropped data is
   Material (cheap, recurs), so the ledger is a best-effort audit log, not a recoverability guarantee
   (ADR-0002 amendment 2026-07-21).

Everything below waits behind the gate or is independent.

**Status vocabulary:** `needs-grilling` (still a direction, not a design — grill before doing) ·
`ready-for-issue` (verified problem, design-ready — graduate to a GitHub issue) · `issue #N` (tracked) ·
`ready-for-PR` (fix already exists in fork, upstream candidate).

**The `#` column is a stable row ID, not an execution order.** Dependencies form a graph, not a 1→8
line (e.g. track 4 must ship *before* track 1). The real order for planning:

| Order | Track (row id) | Gate |
|-------|----------------|------|
| 1st | **P1 gate** (ADR-0002, #151) | **shipped SHADOW 2026-07-21** (`e17818c`); 2nd moment = review would-drops + flip enforce + upstream PR |
| 2nd (parallel) | **Recovery loop** (5, ADR-0003 / #149) | independent; kills the biggest dup engine |
| 3rd | **Async ingest** (4, ADR-0004) | after the gate; removes the client timeout |
| 4th | **Chunk ≥ batch** (1) | only after ADR-0004 |
| 5th (after measuring) | Vazão (2 / #150), map-reduce tail (1b) | gated on whether the gate already drained the backlog |
| anytime | Truncate PR (6), **bound proposal queue (8a)** | independent of the critical path |
| after the gate | **Honor merge rejection (8b, ADR-0005)** | worthless before the queue is curatable |
| delete | Two-cursor (7) · Catch-up storm (3) · **`duplicate_checked` bug (8)** | 7 dissolved by ADR-0004; 3 & 8-as-bug dissolved by evidence (see Dissolved below) |

> ⛔ **HARD ORDERING — read before planning track 1.** Track 1 (chunk ≥ batch) is `ready-for-issue`
> but **must not be planned or shipped before [ADR-0004](adr/0004-async-ingest-nudge-server-cursor.md)
> lands**. Raising `chunk_chars` to 60K makes extraction a single 60K-char call; while the client
> timeout still exists (135s httpx), that call can time out → freeze-and-re-post loop. ADR-0004 removes
> the client timeout; only then is track 1 safe. Track 1 is also gated behind the **P1 gate**
> ([ADR-0002](adr/0002-relevance-gate-provenance.md), slice-1). Sequence is fixed:
> **P1 gate → ADR-0004 → track 1.** Do not reorder.

| # | Track | What | Why deferred | Trigger to start | Status |
|---|-------|------|--------------|------------------|--------|
| 1 | **Chunk ≥ batch: kill flush-boundary blindness** | Grilled 2026-07-17 ([ADR-0001 amendment 2](adr/0001-batch-size-and-ordering.md)). "Holística" collapsed: its dedup value is already covered (`_is_duplicate_memory` + `duplicate_merger` + ADR-0003 + the gate); its *only* residual value is **coherence of superseded-alone facts (mode b)** — a fact decided then reverted where the reversal was never extracted as its own node, so `conflict_detector` never sees a pair. Root cause is a config mismatch: `ingest_chunk_chars` (40K) < `session_watcher_flush_bytes` (60K) → every size-ceiling batch is split into 2 chunk-blind calls. Fix = invariant `flush_bytes ≤ chunk_chars` (validator) + raise `chunk_chars` default to 60K, so a steady-state batch extracts in one call. | The 40K is a timeout artifact; ADR-0004 must remove the timeout first, else a single 60K call risks the 135s httpx budget. Also ordered after the P1 gate. | After ADR-0004 ships (timeout gone) and the gate. | `ready-for-issue` · ⛔ **BLOCKED BY ADR-0004 + P1 gate** — see ordering callout above |
| 1b | **Holística map-reduce (the overflow tail)** | The residual mode-(b) case that track 1 does *not* fix: a delta genuinely exceeding the recall sweet spot (session-boundary catch-up, huge paste) still splits into multiple chunks, so a reversal spanning chunks can be missed. Map-reduce (map per chunk → reduce reconciles) or carry-forward context would close it. | The tail is already shrunk on three sides (age-flush keeps deltas small, ADR-0003 kills the recovery-loop inflation, the gate cuts volume) — likely near-empty. Building map-reduce before measuring the tail is machinery ahead of evidence. | Only after a transcript audit proves real mode-(b) harm survives in the >60K-delta tail post-track-1. | `needs-grilling` |
| 2 | **Vazão / concorrência multi-janela (P1b)** | Ingestion lane is 100% serial: `session_watcher_catchup_concurrency` is a **dead, unused knob**; zero parallelism primitive in watcher/engine; one `claude -p` at a time, 30s per 5min (10% duty cycle). N transcripts from N concurrent windows fight one serial lane → ingestion drains overnight, late. | It's supply-side; the gate is demand-side and may dissolve the backlog. Parallelizing `claude -p` risks quota/rate-limit. Deserves its own design/ADR. | After measuring whether the gate's reduced arrival already closed the gap. | **issue [#150](https://github.com/r-spade/ormah/issues/150)** |
| 4 | **Ingestão assíncrona / SessionEnd síncrono (P0)** | **Designed ([ADR-0004](adr/0004-async-ingest-nudge-server-cursor.md)):** hook becomes a content-free **Nudge** (path only); the server owns a single **Cursor** and advances it on *job completion*, not on the synchronous response. Cursor + guard + `_ingest_session` extracted into an always-on **Ingest worker**; watchdog Observer + reconcile become **Producers** over it → both lanes converge to one cursor (kills track 7). Client timeout removed; generous server-side timeout with a slow/fast split (TimeoutExpired → cap→quarantine; fast failure → uncapped transient, preserves H1) — this folds the transient-retry loop finding in, not a separate track. Durability: durable cursor + in-memory queue + startup drain. | Bigger structural change; gate reduces the volume that would hit it. Ships after the gate. | Design done — plan (writing-plans from ADR-0004) → issues on `r-spade/ormah`, branch from `upstream/main`. | designed (ADR-0004) · **ready-for-issue** |
| 5 | **Recovery loop (P2b)** | `leading_orphan` false positive on `assistant(end_turn) → assistant("API Error…") → user` re-ingests the whole transcript forever + strands ~530KB tail. **Design decided ([ADR-0003](adr/0003-recovery-drops-orphan-fragment.md)):** guard A — a shared `should_rewind(result, start_offset)` predicate rewinds only when `safe_end <= start_offset` (no forward progress); an orphan-with-progress is dropped, not re-ingested. Marker rejected. Code not yet written. | Pre-existing; already tracked. | Design done — implement (TDD) + upstream PR against #149, merge to `local-main`. | **issue [#149](https://github.com/r-spade/ormah/issues/149)** · designed (ADR-0003) |
| 6 | **Truncate silencioso em 100K (upstream)** | Upstream does `content[:ingest_max_content_chars]` — drops the rest of the session, cursor advances as if all extracted. The fork already fixed this (`_split_for_extraction` never truncates). | Fork is not affected; it's an upstream contribution, not local work. | Open a PR to upstream when convenient. | `ready-for-PR` |
| 7 | **Duas vias sem coordenação de cursor (P0)** | Hook (`whisper-out`) and session_watcher have independent cursors over the same files; ~250–500 nodes (2.5–5% of the overlap window) are double-ingested, dominant cost being extraction paid twice. Decide whether the watcher should skip sessions the hook already covers. | Quantified but low-severity vs. the gate; a design choice, not a bug. | After the gate/vazão; may resolve as part of async redesign. | `needs-grilling` |
| 8a | **Bound the merge-proposal queue** | Grilled 2026-07-17 → [ADR-0005](adr/0005-merge-queue-bounded-and-curated.md). The **`duplicate_checked` "bookkeeping bug" is refuted** (it's a write-only table whose read #81 replaced with the seq-watermark; stagnation since 07-08 = no manual rejections, not a defect). The real defect surfaced under it: **3,160 pending merge proposals, no cap, no TTL** (`duplicate_merger.py` files every sub-`auto_merge_threshold` pair; only `decay` proposals are pruned). Fix = cap/TTL on pending merge proposals. | Independent of the critical path and of the merge model — the queue grows unbounded regardless. | Now. | `ready-for-issue` · **provenance: upstream** (upstream files proposals identically, prunes only decay) |
| 8b | **Honor merge rejection (`duplicate_checked` read)** | Same grilling / [ADR-0005](adr/0005-merge-queue-bounded-and-curated.md). The reject button (`ReviewQueue.tsx`) writes `duplicate_checked` but nothing reads it → the same merge can be re-proposed (broken UI contract). Fix = restore the `not_duplicate` skip in candidate generation, re-activating the dormant write + 5 invalidation DELETEs. | An un-curated queue is a no-op; wiring the read honors a button no one can reach until the gate shrinks the queue. | After the **P1 gate** (ADR-0002). | designed (ADR-0005) · ⛔ **BLOCKED BY P1 gate** · **provenance: fork** (upstream never had the read) |

## Dissolved

- **Catch-up storm (3), 2026-07-17** — premise refuted by code (grilling session): the none→on flood
  is already bounded by design, not "the entire backlog since install". `session_watcher_lookback_hours=72`
  gates every never-ingested file (`_scan_sessions`, `session_watcher.py:1006`), and a provider-wide
  failure returns `TRANSIENT` **before** any state commit, so the file stays lookback-protected. The
  invariant is pinned by `test_ingest_none_is_transient_and_does_not_advance`
  (`tests/test_background/test_session_watcher.py:181`, asserts `rel not in state`). Residual — a
  partial-state file drains with no age bound when the provider returns — accepted as correct H1
  behavior (content that started ingesting is never abandoned); any queue-priority policy belongs to
  the ADR-0004 worker.
- **`duplicate_checked` "bookkeeping bug" (8), 2026-07-17** — premise refuted by code+git (grilling →
  [ADR-0005](adr/0005-merge-queue-bounded-and-curated.md)): it is not a stagnant-bookkeeping bug but a
  **write-only** table. Its read was replaced by the seq-watermark when #81 (`e0b8dd5`/`e5adbbb`) rewrote
  candidate generation; the reject write (`routes_agent.py:409`) survived, its reader did not. Stagnation
  since 2026-07-08 = no manual rejections, not a defect. What survives the refutation is two *different* real
  items — the unbounded queue (8a) and the orphaned read (8b) — not a bookkeeping bug.

## How this ledger stays alive

- A `needs-grilling` row graduates to `ready-for-issue` only after it's been grilled into a design.
- A `ready-for-issue` row graduates to `issue #N` when opened on `r-spade/ormah`.
- When a track ships, delete its row (the ADR/issue is its permanent record) — this file holds only
  what is *not yet done*, so an empty table means nothing is outstanding.
