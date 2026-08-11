# Design: Claude-CLI memory extraction (replace local gemma)

**Date:** 2026-07-01
**Status:** Design — awaiting review
**Author:** André + Claude

## Problem

Server-side transcript extraction (`/ingest/conversation` → `ingest_conversation` →
`_extract_memories_llm` → `llm_generate`) runs on the local Ollama `gemma3:12b-it-qat`.
Each extraction stalls 30–140s, pins ~8.6 GB of VRAM, and today runs continuously
(23 calls / 95 memories on 2026-07-01) via two triggers: the client-side whisper-out
hook and (when enabled) the server-side session watcher.

Goal: extract memories with **Claude via the local `claude` CLI** (`claude -p`,
subscription auth — **no paid API**), pinned to **Haiku** even when the interactive
session runs a larger model, while guaranteeing that content is eventually consumed
even if a session closes abruptly (VSCode/Claude Code closed, crash, `kill -9`).

## Goals

- Extraction LLM = `claude -p --model haiku`, subscription auth, not the Anthropic API.
- Haiku pinned regardless of the user's interactive model (extraction is a cheap
  mechanical task).
- Guaranteed eventual consumption of transcript content (no orphaned tails).
- Reuse existing server-side dedup; minimal new surface.

## Non-goals

- No gemma fallback. On Claude failure the extraction **defers** (cursor not advanced,
  retried on the next scan). Gemma is cut entirely.
- No change to the whisper-**inject**/recall path (whisper-in). Only extraction (whisper-out).
- Not building an agentic tool-calling extractor (Approach B) — deterministic shell-out.

## Architecture (Approach A, refined)

Model the shell-out as a **new LLM provider `claude_cli`** in the existing `get_adapter`
switch (`src/ormah/background/llm/__init__.py`), alongside `ollama` / `litellm` / `none`.
Because `_extract_memories_llm` already calls `llm_generate` → adapter, **both extraction
callers route through Claude with zero call-site changes**:

1. **Session watcher (reconciler)** — the guarantee. `watchdog` real-time events
   (near-real-time, debounced) + catch-up `_scan_sessions` on server boot. Already handles
   in-flight/idle/shrink/legacy-cursor cases. Revived, now extracting via `claude_cli`.
2. **Whisper-out hook** (`cmd_whisper_store`, UserPromptSubmit-periodic / PreCompact /
   SessionEnd) — the latency optimization. Unchanged; POSTs `content`, server extracts
   via `claude_cli`.

Both kept (user decision). Both hit a **metered** LLM now, so they share **one cursor**
to avoid redundant extraction (see Cursor unification).

## Components

### 1. `ClaudeCliAdapter` (new)
`src/ormah/background/llm/claude_cli_adapter.py`, registered under `provider="claude_cli"`.
- `.generate(prompt, json_mode, ...)` builds argv:
  `claude -p <prompt> --model <claude_cli_model> --output-format json`
- Runs `subprocess.run(..., timeout=claude_cli_timeout, env=<child_env>)`.
- Parses the `--output-format json` envelope → assistant text → reuse `_extract_json`.
- Returns text, or `None` on nonzero exit / timeout / invalid JSON.

### 2. Provider wiring
Add `claude_cli` to the `get_adapter` switch and to the `llm_provider` enum validator
(`config.py:_llm_provider_enum`). No changes to `_extract_memories_llm` or `llm_generate`.

### 3. Session watcher revival
Re-enable via `ORMAH_SESSION_WATCHER_ENABLED=true`. No logic change — it calls
`ingest_conversation(content=...)`, which now uses `claude_cli`.

## Recursion & exclusion (critical)

`claude -p` writes its own transcript under `~/.claude/projects` and fires Claude Code
hooks → the reconciler would ingest the worker's own transcript, and the worker's hooks
would spawn more extraction. Two defenses (exact CC mechanism confirmed during the spike):
- **Hooks off in the child:** run `claude -p` with ormah hooks disabled (settings profile
  without the plugin, or an env flag the hook `bin/` scripts check to no-op).
- **Exclude the worker's transcript:** run the worker in a dedicated cwd/project the
  watcher ignores, or tag its `session_id` and skip it in `_scan_sessions`.

## Auth / no-API gate (spike — before implementation)

Confirm `claude -p` in the launchd server context authenticates via **subscription OAuth**
(`~/.claude/`), not `ANTHROPIC_API_KEY`. If `ANTHROPIC_API_KEY` is present in the server
env, the child may use the paid API → violates the core requirement. Mitigation: the
adapter strips `ANTHROPIC_API_KEY` from the child env and verifies subscription mode.
**This spike gates the whole design.**

## Cursor unification

Today: hook cursor `~/.cache/ormah/whisper-cursors.json` (keyed by `session_id`) and
watcher cursor `<watch_dir>/.session_watcher_state` (keyed by relative path) are separate.
With a metered LLM, running both against separate cursors risks double extraction.
**Decision:** unify on a single `session_id`-keyed cursor store shared by both paths.
Whichever fires first extracts the safe slice and advances; the other sees "nothing new"
and skips. A per-session advisory lock (cross-process: hook subprocess vs server watcher)
prevents the simultaneous-fire race; worst case without the lock is one redundant,
dedup-safe extraction.

## Config surface (new)

- `ORMAH_LLM_PROVIDER=claude_cli`
- `ORMAH_CLAUDE_CLI_MODEL=haiku` (or full id)
- `ORMAH_CLAUDE_CLI_TIMEOUT_SECONDS=120`
- `ORMAH_CLAUDE_CLI_BIN` (optional; default `shutil.which("claude")`)
- `ORMAH_SESSION_WATCHER_ENABLED=true`

## Error handling

- Adapter `None` → `_extract_memories_llm` returns "No LLM available" → ingest defers,
  cursor not advanced → next watcher scan retries. No gemma fallback.
- Server/`claude` binary missing → same defer path; watcher catch-up recovers on next boot.

## Testing

- **Unit:** adapter builds correct argv; parses the JSON envelope; returns `None` on
  exit≠0 / timeout / bad JSON (mock subprocess). Recursion guard: child invoked with
  hooks-off flag/env and `ANTHROPIC_API_KEY` stripped.
- **Integration:** reconciler does not re-ingest the worker's own transcript; unified
  cursor makes the second path skip an already-extracted slice.
- **Contract:** recorded real `claude -p --output-format json` envelope fixture →
  parser extracts the memory list.
- **Manual spike:** real `claude -p` under launchd authenticates via subscription.

## Open risks / spikes

1. Subscription-auth propagation under launchd (gating spike).
2. Exact Claude Code flag/env to disable hooks in the `claude -p` child.
3. `claude -p --output-format json` envelope shape (fixture for the contract test).

## Out of scope

- Agentic SDK worker (Approach B), in-session subagent extraction (Approach C).
- Migrating background maintenance jobs off their current LLM path.
- Cursor unification beyond the two extraction paths.

## Branching

Upstream-clean feature branch off `origin/main` after the standard upstream-compare
(local-main vs origin/main). Genuine upstream feature.
