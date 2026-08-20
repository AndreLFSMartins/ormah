# Claude CLI Judge Workspace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Each task file is self-contained — an implementer gets
> this overview plus their own task file, nothing else.

**Goal:** Stop `claude -p` judge calls from inheriting the operator's `~/.claude/CLAUDE.md`, by
pointing the child's `cwd` at a workspace Ormah owns and loading it with `--setting-sources project`.

**Architecture:** A new module materialises and guards a workspace directory holding a
Ormah-authored `CLAUDE.md`. `get_adapter` resolves the path and hands it to `ClaudeCliAdapter`,
which passes `--setting-sources project` and runs the child with `cwd` set to that directory. The
Claude Code default system prompt is deliberately kept.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode = auto`), ruff (line-length 100), Claude Code
CLI 2.1.237.

**Spec:** `docs/superpowers/specs/2026-08-20-claude-cli-judge-workspace-design.md` — read it first.

## Global Constraints

- Every task is TDD: failing test first, then minimal implementation. Mandated by project `CLAUDE.md`.
- ruff must stay clean: `ruff check src/ tests/` → `All checks passed!`.
- **Suite baseline before this plan: `1 failed, 2628 passed, 12 deselected`.** The single failure is
  `tests/test_conflict_claims_investigation.py::test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports`,
  which fails deterministically on `local-main` and is NOT a regression. Any other FAILED line is.
- **Expected baseline after this plan: `1 failed, 2642 passed, 13 deselected`.** Tasks 1–3 add 14
  passing tests (8 + 3 + 3); Task 4 adds one `integration`-marked test, which raises the deselected
  count from 12 to 13 and leaves the passed count alone.
  Assert the exact numbers, never "at least" — an inequality lets tests vanish unnoticed.
- No numeric threshold on judge output language, anywhere. The control arm was measured varying
  2.5x between two identical runs, so any such gate produces a verdict without information.
- Never pass `--setting-sources ""` and never pass `--bare` or `--system-prompt-file`: the first
  caused the reverted regression, the other two are recommended by the docs and rejected by this
  binary (spec §"What was tried and rejected", and session-12 handoff §5).

## Task order

| Task | Deliverable | File |
|---|---|---|
| 0 | Isolated worktree, venv, green baseline | `01-precondition-and-worktree.md` |
| 1 | `cli_workspace.py`: instructions, materialisation, guard | `02-cli-workspace-module.md` |
| 2 | Adapter: `workspace_dir`, `--setting-sources project`, `cwd`, thinking off | `03-adapter-wiring.md` |
| 3 | `get_adapter`: route name, path resolution, fail-closed → `None` | `04-factory-fail-closed.md` |
| 4 | Live `integration` smoke: `thinking_tokens == 0` on a real judge prompt | `05-live-thinking-smoke.md` |
| 5 | Full verification + the manual BEFORE/AFTER detector | `06-verify-and-detector.md` |

Tasks 1→3 are strictly ordered: each consumes names the previous one produces. Task 4 needs Task 3
landed. Task 5 is last.

## Blocking precondition — read before Task 0

`make server` runs uvicorn with `reload=True` (`src/ormah/main.py:452`), and the running Beta daemon
serves the `Tools/ormah` working tree. Editing the adapter in that tree puts unvalidated code into
production while `duplicate_merger` performs **irreversible** merges.

**This plan closes that by isolation, not by shutdown:** all work happens in a git worktree, so the
live tree is never edited and the daemon keeps serving the known-good reverted code. This supersedes
the earlier recommendation to stop the LaunchAgent, and is better because it costs no downtime for
the whisper hooks the operator uses every turn.

The alternative — `launchctl bootout` the `com.ormah.server.dev` agent and edit `Tools/ormah`
directly, which is how `34c41cd` landed — remains valid if the operator prefers it. It trades
whisper downtime for skipping the worktree venv setup. **Do not mix the two.**

Per FORK-WORKFLOW golden rule 1, `Tools/ormah` stays parked on `local-main` either way.

## Landing

`34c41cd`, the previous implementation of this same work, landed directly on `local-main` with no
clean island and no upstream PR. This plan assumes the same: the branch merges into `local-main`.
If it should instead become an upstream PR, the island must be cut from `upstream/main` per
FORK-WORKFLOW Recipe A — that is a different Task 0 and the operator must say so before Task 0 runs.
