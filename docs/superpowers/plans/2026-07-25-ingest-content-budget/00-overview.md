# Ingest Batch Content Budget — Implementation Plan (overview)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
> Each task lives in its own file; give a worker **only its task file plus this overview**.

**Goal:** Budget each ingest Batch on the conversation length the Extractor actually receives, instead
of raw transcript bytes, so batches hit the ~15K-token recall sweet spot instead of landing at 5.6% of it.

**Architecture:** `parse_transcript`'s single byte-delta predicate splits into two progress-guarded
budgets — cleaned-conversation length and an independent raw-byte ceiling — either of which closes a
Batch. The config surface is renamed to the new unit, the `flush ≤ chunk` invariant that Amendment 2
prescribed is finally enforced, and the ingest path stops sending a variable payload against a fixed
provider timeout.

**Tech Stack:** Python 3.11+, pydantic-settings, pytest (`asyncio_mode = auto`), ruff.

**Spec:** [`../../specs/2026-07-25-ingest-batch-content-budget-design.md`](../../specs/2026-07-25-ingest-batch-content-budget-design.md) — read it first; it carries the evidence and the rejected alternatives.

## Global Constraints

- **Never `git checkout` a branch inside `/Users/andre/Documents/GitHub/Tools/ormah`** — it is the live
  Beta and a branch switch breaks every whisper hook. Work in a worktree cut from `local-main`.
- **Beta-only by impossibility.** `upstream/main` has no `max_bytes`/`_would_overshoot` in the parser and
  no `session_watcher_flush_bytes` in config. No upstream PR. Read `FORK-WORKFLOW.md` before any branch op.
- Code, comments, identifiers and commit messages in **English**.
- ruff: `target-version = py311`, `line-length = 100`. Run `ruff check src/ tests/` before every commit.
- Tests run from the **worktree's own venv**: `./.venv/bin/python -m pytest`. Default run excludes
  `integration`-marked tests.
- **Batch target is 60000 cleaned chars (~15K tokens) and does not move in this plan.** It is a quality
  bound (context rot on multi-item extraction), not a capacity bound. Raising it needs an `eval/` A/B.
- **Both budgets keep the progress guard (`_safe_len > 0`).** Making either absolute breaks the ADR-0003
  rewind invariant proved in Task 2. `stop_offset` remains the only absolute limit.
- Never claim a step passed without pasting the command output.

## File structure

| file | responsibility | tasks |
|---|---|---|
| `src/ormah/transcript/parser.py` | boundary selection + both budgets | 1, 2 |
| `src/ormah/config.py` | settings, validators, deprecation warning | 3, 4, 6 |
| `src/ormah/background/session_watcher.py` | plumbs settings into `_ingest_session` | 3 |
| `src/ormah/engine/memory_engine.py` | chunking + payload-derived timeout | 4, 5 |
| `src/ormah/background/llm/ollama_adapter.py` | pin `num_ctx` | 5 |
| `tests/test_transcript/test_parser.py` | parser-level budget behaviour | 1, 2 |
| `tests/test_background/test_session_watcher_flush.py` | config + end-to-end flush gate | 3, 4 |
| `tests/test_engine/test_ingest_extraction.py` | chunking + timeout hint | 4, 5 |
| `docs/adr/0001-batch-size-and-ordering.md` | three factual corrections | 7 |

## Tasks

| # | file | deliverable |
|---|---|---|
| 1 | [01-content-budget.md](01-content-budget.md) | `_format_turn` + prefix sums + content predicate replaces the byte predicate |
| 2 | [02-raw-ceiling.md](02-raw-ceiling.md) | independent raw-byte ceiling + the `capped ⇒ progress` property test |
| 3 | [03-config-surface.md](03-config-surface.md) | rename to `flush_chars`, deprecation warning, watcher plumbing |
| 4 | [04-chunk-invariant.md](04-chunk-invariant.md) | ⛔ Amendment 2: `flush_chars ≤ ingest_chunk_chars ≤ ingest_max_content_chars` |
| 5 | [05-provider-fit.md](05-provider-fit.md) | payload-derived timeout, `num_ctx` pinned, minimum-window documented |
| 6 | [06-measure-defaults.md](06-measure-defaults.md) | measure the corpus and a real extraction; set `max_raw_bytes` and the timeout rate from evidence |
| 7 | [07-adr-corrections.md](07-adr-corrections.md) | amend ADR-0001 with the three statements this work falsified |

Tasks 1→5 are strictly ordered. Task 6 must run **after** 5 (it needs the real predicate and the real
timeout path) and **before** merge — it is what turns two provisional defaults into measured ones.
Task 7 can run any time after 6.

## The trap that will bite

Existing flush tests pass `_write_turns(path, turns=4, pad=20000)`, whose padding is **plain user text**
— so raw bytes ≈ cleaned chars and the test passes identically under both units. A test that survives
the axis change unchanged is not testing the budget. Every discriminating fixture in this plan pads with
`tool_use` / `tool_result` content, so raw ≫ cleaned.

## What the raw budget does and does NOT bound (council R1, Codex)

The raw budget bounds **multi-turn accumulation within a slice**. It does **not** bound the cost of a
single pathological record, for two structural reasons: the predicate runs at commit sites, *after*
`readline()` + `json.loads` have already processed the record, and the `_safe_len > 0` progress guard
deliberately exempts the first closed turn.

That limitation is **pre-existing and unchanged by this plan**: today's `max_bytes` predicate has the
identical structure and the identical exemption, and `session_watcher.py:880` parses the whole file
**uncapped** on the rewind-probe path by design (a capped probe mis-parks recoverable files). Measured,
raw span per slice already reaches p99 3.5 MB under the current byte budget.

Do not "fix" it inside this plan. A pre-decode line-size limit would make a legitimately huge single
turn permanently un-ingestable — silent data loss, the failure class this ADR chain exists to remove —
and a quarantine state was explicitly descoped on 2026-07-25. Single-record parse cost belongs to its
own ADR, where that trade-off can be decided deliberately. State the narrow claim in the ADR (Task 7)
rather than widening the mechanism here.

## Out of scope (registered elsewhere, do not pick up)

- ADR-0004 slice 3 — **descoped 2026-07-25**, do not replan it.
- The `claude_cli_adapter` cancellation-epoch/deadline race — a real open defect, but a different axis.
- Raising the batch target to ~30K tokens — needs an `eval/` A/B first, never a speculative bump.
- pytest contamination of the production log; `ORMAH_DELETION_ENABLED=false`.

## Rollout note

~408 stranded transcripts were still draining as of 2026-07-25. Landing this mid-drain changes payload
size in flight, which muddies both the measurement in Task 6 and any post-merge observation. Prefer
landing after the drain completes; if you cannot wait, say so explicitly in the PR rather than letting
the numbers be read as steady-state.

## Definition of done

- `./.venv/bin/python -m pytest tests/ -q` green in the worktree.
- `ruff check src/ tests/` clean.
- The orphan/rewind tests in `tests/test_transcript/test_parser.py` and
  `tests/test_background/test_session_watcher.py` pass **unedited** (Task 2 depends on this).
- Task 6's measurement output is pasted into the PR description.
- `/council` on this plan **before** any code; `/council-pr` before merging to `local-main`.
