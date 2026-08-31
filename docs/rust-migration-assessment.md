# Rust and ormah: what the measurements say

2026-08-31 · André Martins (analysis and profiling run with Claude Code) · draft for discussion with r-spade

The question on the table: should ormah's engine move to Rust — fully, partially, or not at all — to
(1) shrink the server's resident memory, (2) speed up the slow paths, (3) harden production error
behavior, and (4) improve testability. UI, desktop shell and TypeScript plugins are out of scope.

Every number below is either measured this week on a live instance, cited to a dated source, or
marked `~` as an estimate. Where the evidence is secondhand, the text says so.

## The short version

We profiled the running server before writing any of this, and the profile overturned the premise.
The memory footprint is not a Python problem: 91% of it (1,169 of 1,285 MB) sits in ONNX Runtime
sessions and their allocator arena — C++ memory that a Rust engine would load unchanged. A full
rewrite would recover the CPython residual, about 89 MB, or 7% of the process.

The latency complaints trace to architecture, not interpreter speed: one coarse write lock, a
serial ingestion lane, a full-corpus re-embed triggered by a single missing vector. These trace
to open issues #150, #32 and #109, and none of them is interpreter-bound.

So the recommendation is neither "rewrite" nor "do nothing." It is: fix the memory with process
isolation and the latency with concurrency work, both in Python, as a short series of small PRs;
get the whisper eval corpus into the repo so that any future port has a fidelity instrument; and
keep a narrow Rust extension as a real option that gets exercised only when profiling — not
intuition — shows the scoring path hot. The full rewrite doesn't survive contact with the numbers.

## 1. Where the memory actually goes

Measured 2026-08-31 on the dev server (~21 h uptime): RSS 1.31 GB at sampling, `phys_footprint`
1,285 MB, peak 1,464 MB. We have seen readings above 1.3 GB in day-to-day use, which is consistent
with that peak; no reading above ~1.46 GB has been recorded so far.

To find out who owns that memory, we rebuilt the footprint from zero in a throwaway process — no
ormah code, no SQLite, no uptime:

| Step | phys_footprint |
| --- | ---: |
| bare CPython | 17 MB |
| + numpy, onnxruntime, fastembed imports | 77 MB |
| + `bge-base-en-v1.5` ONNX session | 735 MB |
| + ms-marco reranker session | 821 MB |
| + six rounds of inference at 512-char texts, 60-doc rerank | 1,169 MB, flat from round 2 |

The probe's 60-doc rerank is deliberately 2× the configured whisper pool
(`whisper_max_nodes` 6 × `whisper_candidate_pool_multiplier` 5 = 30 candidates), so the plateau is
an upper bound on production shapes. Even so: that is 91% of the production footprint reproduced
in under a minute, before a single ormah module loads. The decomposition of the live 1,285 MB:

- **821 MB — two ONNX Runtime sessions.** The embedding export on disk is 217,824,172 bytes
  (218 MB decimal, 208 MiB) of pure fp16 — all 149 graph initializers are FLOAT16, and 108.9M
  parameters × 2 bytes accounts for the file to within 0.1%. It becomes a 658 MB session: a ~3×
  expansion whichever unit base the footprint tooling uses. The leading explanation is upcasting
  at load — ORT materializing the fp16 initializers as fp32 (218 → 436 MB, the right ballpark
  once working copies are added). The discriminating evidence is the reranker row above: the
  already-fp32 ms-marco model (90,992,115 bytes on disk) costs 86 MB of session — no expansion
  (0.9–1.0×, depending on the same unit base). fastembed's hardcoded `ORT_ENABLE_ALL` graph
  optimization may add on top, but it is unlikely to be the main driver, since both models pass
  through it. Either way this is C++ memory: the Rust `ort` crate links the same library and
  pays the same bill.
- **~348 MB — ONNX Runtime's arena high-water mark.** A doubling allocator that never returns its
  peak (the power-of-two allocation histogram in `heap` output is textbook). vmmap shows 160 MB of
  it swapped out: dead pages, not working set. Two plausible fixes were tested and failed —
  disabling the arena made things worse (3,316 vs 2,520 MB at batch 32), and capping threads
  changed nothing. Batch size is the one lever that works, and ormah already truncates content to
  512 chars (`embedding_max_content_chars`), so it sits near the floor already.
- **~27 MB — SQLite page caches.** Twelve per-thread connections at the default cache size.
  Bounded.
- **~89 MB — the residual: CPython object heap plus thread stacks** (1,285 − 821 − 348 − 27).
  This slice, about 7% of the process, is the entire memory upside of a Rust rewrite.

Two further findings rule out a leak. RSS is not monotonic: it dropped 318 MB unprompted during a
ten-minute observation window (what ratchets is the *peak*, because the arena keeps its high-water
mark). And the whole vector corpus — 6,941 vectors × 768 floats at measurement time — is about
21 MB; the process is 60× the size of the dataset it serves, so data growth cannot be the driver.
No unbounded accumulator was found in the session watcher, the scheduler, or the engine facade.

**Falsifier, stated up front:** this analysis rests on one long-horizon check we could not run in a
day. If `phys_footprint_peak` climbs meaningfully past ~1.46 GB over a multi-day watch, there is a
slow accumulator we missed, and section 6 changes. Watching that one number is cheap and should
happen regardless.

What would shrink the footprint — all of it language-agnostic:

1. **Move inference out of the server process.** A small sidecar owns the two ONNX sessions,
   loads lazily, unloads after an idle TTL. Steady-state server memory drops to ~120–180 MB
   (the SQLite caches plus the CPython residual, 27 + 89, with slack for allocator overhead; to
   be verified by building it). The costs are priced in section 6 — this is not free.
2. **A smaller embedding model.** bge-small is ~3.3× smaller by parameter count, but switching
   invalidates all stored vectors and forces a full re-embed — which today costs ~25 minutes and
   is exactly the failure mode of #32. Worth considering only after #32 is fixed.
3. **A one-day spike on the runtime.** The export is confirmed fp16 on disk; the open question is
   what ORT does with it at session init. Try an fp16-preserving execution path or serializing
   the optimized graph to disk, and measure the session. Uncertain payoff, cheap to find out, and
   it would confirm or kill the leading explanation for the 658 MB.

## 2. Where the time goes

The slow paths users feel are not compute. They are waiting:

- **Writes serialize on one lock.** We have recorded `remember` calls timing out at 25–30 s in
  real sessions while ingestion held the shared write lock (`_memory_operation_lock`). #150
  documents the serial ingestion lane.
- **One missing embedding triggers a ~25-minute full re-embed at startup** (#32), and the backfill
  buffers every vector in memory while doing it (#109).

The arithmetic on the hot path — reciprocal rank fusion plus score shaping over a 30-candidate
whisper pool — is microseconds of work in any language. Interpreter overhead is not where the
seconds go.

What Rust would contribute on speed: shared-memory parallelism for batch encoding jobs without
free-threading caveats, and lower constant factors on scoring. Both real, neither relevant to the
issues above, which are design problems. Port them as-is and they are design problems in Rust.

## 3. Production errors and tests

Rust's type system and `Result`-based error handling would eliminate a class of runtime failures
(attribute errors, silent `None` propagation) at compile time. That advantage is real, and it
compounds when an LLM agent writes the code — see section 5. But ormah's known production
failures don't live in that class. They are resource-management and observability defects, and a
port carries them along:

- **#83, per-thread SQLite connections exhausting file descriptors.** Open upstream and untouched
  since the day it was filed. Our fork has carried the fix since that same day — commit
  `8c3cd1e`, 2026-07-05, a `weakref.finalize` hook that retires each thread's connection at
  thread death — and we never sent it upstream. The first #83 PR is porting that across, not new
  diagnosis.
- The sleep cycle reports `completed` while `ORMAH_LLM_PROVIDER=none` silently disables five
  subsystems. No compiler catches a green status report.

On tests, the suite is already substantial: 2,714 test functions across 165 files (61,683 LOC of
test code against 36,365 LOC of engine). The real gap is that the eval harness — the instrument
that would catch a port that compiles but ranks differently — keeps its corpora local-only and
gitignored. The repo's recorded baseline (Makefile, 2026-07-06): whisper F1 0.69 with suppression
0.95 over 100 prompts; recall@8 0.99 with F1 0.57 over 25 cases. **Making a shareable eval corpus
a repo artifact is a prerequisite for any port work, and is valuable even if no Rust work ever
happens.**

## 4. What Rust would buy, and what it would cost here

The buys: the ~89 MB CPython slice; compile-time error gating; parallel batch encoding without
free-threading caveats; and one strategic simplification for the desktop app. Today the desktop
ships a bundled `uv` binary that installs a version-pinned `ormah` wheel from PyPI on first
launch; a compiled engine would remove that install step and the Python runtime dependency from
end users' machines. Worth noting: the repo already contains 2,687 lines of Rust (the Tauri
shell) and CI already builds a stable Rust toolchain. Rust is not a foreign toolchain in this
project. A Rust *engine*, however, is a foreign architecture — nothing in the issue or PR history
has ever proposed one.

The costs, specific to this codebase:

- **The LLM boundary is Python's home turf.** litellm has no Rust equivalent; the
  `ollama | litellm | claude_cli` provider matrix feeds five subsystems; and while an official
  Rust MCP SDK exists, the Python SDK is far more mature (roughly 24k vs 3.9k GitHub stars as of
  this week). The LLM-bound jobs — auto-linker, conflict detector, duplicate merger,
  consolidator, feedback judge — are network-bound anyway; Rust buys them nothing measurable.
- **Two domain-relevant crates are pre-1.0** as of August 2026: `ort` at 2.0.0-rc.13 and the
  `sqlite-vec` crate at 0.1.10-alpha.4. (The sqlite-vec C extension itself loads from rusqlite
  the same way it loads from Python — the alpha is the packaging, not the engine.)
- **Release infrastructure is wheel-only and single-keyed.** Releases run `uv build --wheel` and
  are gated to `RELEASE_ALLOWED_ACTOR: r-spade`. A PyO3 extension turns one pure-Python wheel
  into a per-platform build matrix (macOS arm64, Linux x86_64 at minimum, matching the desktop
  targets), and that operational load lands on the only person who can cut a release.
- **A rewrite competes with the project's own velocity.** ormah is at 0.14.11, self-labeled
  Alpha, and shipped 24 core releases in the seven weeks to 2026-08-14 (quieter since
  mid-August). A multi-month port chases a moving target, and the contribution model — fresh branches
  cut from upstream, small reviewable diffs — is structurally hostile to big-bang changes, by
  design.

PyO3 and maturin themselves are not the obstacle. PyO3 0.29 (June 2026) supports the new stable
free-threaded ABI and maturin's mixed Rust/Python layout ships Python source and a native
extension in one wheel; this is the pydantic-core/polars path and it is well-trodden. The door is
open. The question is whether walking through it buys anything, and today the measurements say:
not for memory, not for the filed latency issues.

## 5. Can Claude Code do the port? The evidence cuts both ways

Since the working assumption is that we do the implementation (Claude Code as the coding agent)
and send PRs upstream, the honest state of the evidence on agentic Python→Rust ports, as of
August 2026:

- **A verified failure with an instructive shape.** ScanCode Toolkit was ported to Rust by an LLM
  orchestration harness in early 2026, with "10×–100×" benchmarks attached. The AboutCode
  maintainers audited it: the port was faster *and wrong* — missed detections, skipped files —
  and when they applied equivalent optimizations to the Python original, it matched or beat the
  port while staying correct (aboutcode.org, read directly). Their conclusion applies verbatim
  here: a strong test suite and curated reference data are what make automated porting possible
  at all.
- **A self-reported success.** Qwen3-TTS's inference engine: 7,000+ lines of Rust from Claude
  Code, zero compiler warnings (secondstate.io, 2026-01-28). The author's claim that "the
  compiler catches 90% of AI hallucinations" is opinion, not measurement.
- **An academic middle case, secondhand.** The DFRWS 2026 "Rusting Volatility" study reports an
  LLM-assisted port of 38 forensic plugins: ~29k LOC, ~68 hours of active work, ~US$3k in tokens
  — and only 68.9% exact output equivalence against the original. (Primary source returned 403;
  the numbers come from search snippets and should be confirmed before anyone quotes them.)
- **A calibration point.** The Rust project itself adopted a policy in 2026 restricting
  non-trivial AI-generated code in its core repo (reported secondhand) — useful perspective on
  "the compiler will catch it."

The pattern: agentic ports fail on semantic fidelity, not syntax. The compiler rejects what
doesn't compile; it happily accepts a scoring function that compiles and ranks differently.
ormah's defense would be its test suite plus the eval harness — which is precisely why section
3's corpus-in-repo prerequisite comes before any port work.

## 6. Options, priced

Effort estimates assume the work happens on our side with Claude Code, arriving as clean-island
PRs for upstream review. They are calendar estimates at part-time intensity, marked `~` because
review latency is outside our control.

**Option A — fix it in Python.** In order: a `phys_footprint_peak` probe in the health endpoint
(one afternoon, doubles as the falsifier watch); the inference sidecar; then #150 (write-path
concurrency), #83 (upstreaming the fork's connection-retirement fix), #32 + #109 (incremental
re-embed, streaming backfill); plus the eval-corpus PR.
The sidecar's real costs: per-call IPC on every whisper (serializing 768-float vectors across a
local socket); process supervision and crash/restart semantics; and a cold reload of both ONNX
sessions on the first whisper after an idle window — seconds, not milliseconds (the clean-room
probe built both sessions and ran six inference rounds in under a minute, but the reload was not
separately timed; time it before choosing the TTL). Two boundaries keep that manageable: the
sidecar owns only the ONNX sessions and never touches the memory directory, so #238's
cross-process race does not extend to it; and if it dies at runtime, the server degrades to
FTS-only search instead of failing (the vector leg already runs inside a try/except,
`hybrid_search.py:117-127`) — a property the sidecar PR must preserve deliberately, since the
construction-time fallback is gated on `ImportError` only.
Expected effect overall: server steady-state ~120–180 MB (−86–91%), write stalls gone, restart
cost bounded.
Effort: ~3–5 weeks as 4–6 independent PRs, each mapped to an issue already triaged upstream.
Risk: low; every piece is separately shippable and separately revertible.

**Option B — hybrid core.** An `ormah-core` PyO3 extension owning hybrid search scoring and the
index builder (~1.5–3k LOC of Rust replacing the hot arithmetic), maturin build, wheels per
platform. Expected effect on today's measured bottlenecks: approximately none — the scoring path
is not hot. This becomes rational if profiling later shows CPU heat there (say, the corpus grows
100×), and it requires agreeing the release-matrix change with r-spade first.
Effort: ~4–8 weeks including CI/release work. Risk: medium — mostly infrastructural.

**Option C — full rewrite.** 36k LOC of engine plus keeping 61k LOC of tests meaningful, against
an alpha that shipped 24 releases in seven weeks, through a contribution process built for small
diffs, with no upstream signal that a language migration is wanted.
Expected effect: the ~7% memory slice, compile-time error gating, minus litellm/MCP maturity.
Effort: ~4–6 months optimistic. Risk: high, and the ScanCode failure mode is the default outcome
without the eval corpus in place.

## 7. Recommendation

Do Option A, in the order listed. Land the eval-corpus PR early. Pitch each piece against its
existing issue number — small PRs against triaged issues merge fastest here (22 merged PRs from
this side of the fork so far).

Treat Option B as an earned follow-up, not a plan: the trigger is profiling data showing the
scoring path hot, and by then the enabling work — eval corpus, release-matrix conversation — will
already be done. Decline Option C: it spends months on the one slice of the problem that
measurement says is small, while the levers that move all four goals are available in the
language the project is already written in.

## 8. Open questions and what would change this conclusion

- **The question only r-spade can answer:** does he want to write, review, and own a Rust core at
  all? 73 of 96 merged PRs are his. A language the maintainer doesn't want to maintain is a veto
  regardless of benchmarks.
- `phys_footprint_peak` climbing well past 1.46 GB over days → there is an accumulator we missed;
  re-diagnose before touching anything else.
- Profiling showing real CPU time in scoring/fusion as the corpus grows → Option B's trigger
  fires.
- r-spade wanting the no-install desktop story badly enough to own a release-matrix change →
  Option B/C economics shift, and that's his call to make.
- fastembed-rs demonstrating numeric parity with the Python pipeline on ormah's models → a
  Rust-implemented sidecar becomes nearly free to adopt, as an implementation detail of Option A.

## Appendix: evidence register

**Measured this week (2026-08-31, live dev server + clean-room probes + static artifact reads):**
RSS/footprint numbers, the step-by-step reproduction table, the allocation histogram, the failed
arena/thread fixes, the batch-size effect, the 21 MB corpus size, the 12 SQLite connections,
model sizes on disk, a direct read of the embedding export's initializer dtypes via a protobuf
walk — the `onnx` package is not in the venv — finding all 149 FLOAT16 (108,891,648 parameters,
217.8 MB of raw tensor data), absence of torch from the process. Probe shapes: 512-char texts,
60-doc rerank (2× the configured whisper pool of 30).

**Recorded in our sessions before this week (not re-reproduced for this doc):** the 25–30 s
`remember` timeouts under the shared write lock.

**Verified from primary sources (read directly, August 2026):** PyO3 0.29.2 and its free-threaded
ABI support (pyo3.rs changelog); maturin 1.15.0 mixed-layout builds (maturin guide); crate
versions via crates.io API (`rusqlite` 0.40.2, `ort` 2.0.0-rc.13, `sqlite-vec` 0.1.10-alpha.4,
`tantivy` 0.26.1, `axum` 0.8.9); fastembed-rs README (local embedding + reranking in Rust, no
Python, `ort`/`candle` backends); PEP 779 acceptance and the Python 3.14 free-threading status
(peps.python.org, docs.python.org); the 3.14 incremental-GC memory regressions and their revert
in 3.14.5 (discuss.python.org, 2026-04-16; adamj.eu case study, 2026-04-20) — relevant if ormah
ever moves past 3.11/3.12: pin 3.14.5+; the ScanCode port audit (aboutcode.org); upstream repo
state via `gh` (contributor and merged-PR counts, release gating and cadence, issue list); the
whisper/recall eval floors from the repo Makefile (dated 2026-07-06).

**Secondhand, flagged inline:** Volatility3 port numbers (primary source unreachable); the Rust
project's AI-code policy; pydantic-core/polars/ruff speedup figures (widely repeated, originals
not re-read for this doc — none are load-bearing for the recommendation).

**Assumed, would falsify parts of this doc:** that no slow accumulator exists beyond the observed
21 h window (the peak-watch closes this); that ORT materializes the fp16 initializers as fp32 at
session init (the runtime half of the upcasting hypothesis, and what the section 1 spike would
settle — the export itself is already verified fp16); that bge-small materially cuts the 658 MB
(not benchmarked); that fastembed-rs output matches the Python pipeline numerically
(unvalidated).
