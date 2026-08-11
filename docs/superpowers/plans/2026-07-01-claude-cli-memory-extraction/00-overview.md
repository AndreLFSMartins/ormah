# Claude-CLI memory extraction — Implementation Plan (overview)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Each task lives in its own file (`01-…md` … `06-…md`); dispatch one
> implementer per task, passing that task file + this overview. Steps use `- [ ]` checkboxes.

**Goal:** Replace local-gemma server-side transcript extraction with headless `claude -p` (Haiku,
subscription auth — no paid API), guaranteed by the session watcher, WITHOUT migrating the background
maintenance jobs off their current LLM path.

**Architecture:** Add a `claude_cli` `LLMAdapter` that shells out to `claude -p --model haiku
--output-format json`, feeding the prompt on **stdin** (not argv). Route it via a SEPARATE
`ingest_llm_provider` used only by extraction (`_extract_memories_llm`), so `llm_provider` — which
drives auto_linker/consolidator/conflict_detector/duplicate_merger — is untouched. The session
watcher (reconciler, off-bind-path since #52) is the guarantee; the whisper-out hook is a latency
path that defers to the watcher when the watcher is actually running. Gemma is cut from extraction.

**Tech stack:** Python 3.11, pydantic-settings, httpx, pytest (`asyncio_mode=auto`), the local
`claude` CLI (`~/.local/bin/claude`). Spec: `docs/superpowers/specs/2026-07-01-claude-cli-memory-extraction-design.md`.

## Branch

Feature branch off `origin/main` after the standard upstream-compare (memory
`upstream-compare-before-dev`). Upstream-clean. Do NOT develop on `local-main`.

## File map

| File | Responsibility | Task |
|------|----------------|------|
| `src/ormah/background/llm/claude_cli_adapter.py` (create) | `ClaudeCliAdapter.generate()` — `claude -p`, prompt on stdin, subscription-only, hooks-off, bounded concurrency | 02 |
| `src/ormah/background/llm/__init__.py` (modify) | `get_adapter(settings, provider=None)` + `claude_cli` branch | 03 |
| `src/ormah/background/llm_client.py` (modify) | separate cached ingest adapter + `ingest_llm_generate` | 03 |
| `src/ormah/config.py` (modify) | `claude_cli` in enum; `ingest_llm_provider` + `claude_cli_*` settings | 03 |
| `src/ormah/engine/memory_engine.py` (modify) | `_extract_memories_llm` uses `ingest_llm_generate` | 03 |
| `src/ormah/background/session_watcher.py` (modify) | exclude extractor transcript in the ONE chokepoint `_ingest_session` + `on_created`/`on_modified` | 04 |
| `src/ormah/api/routes_admin.py` + `src/ormah/main.py` + `src/ormah/adapters/cli_adapter.py` (modify) | expose `session_watcher_active` on `/admin/health`; hook defers only to a RUNNING watcher; child extractor no-ops its own hook via `ORMAH_EXTRACTOR_CHILD` | 05 |
| `~/.config/ormah/.env` (modify, not committed) | enablement + end-to-end verify | 06 |

## Task sequence

1. **[01] Spike (GATE)** — confirm `claude -p` **under the real launchd plist env** authenticates via
   subscription (not API), capture the `--output-format json` envelope fixture, settle the hooks-off
   mechanism + extractor workdir. No code ships if the subscription-auth gate fails.
2. **[02] `ClaudeCliAdapter`** — TDD: stdin prompt, envelope parse, `None` on failure,
   `ANTHROPIC_API_KEY` stripped, hooks-off, model pinned, bounded concurrency (semaphore).
3. **[03] Ingest-only provider routing** — `ingest_llm_provider` + `get_adapter(provider=)` +
   `ingest_llm_generate`; `_extract_memories_llm` switches to it. Maintenance stays on `llm_provider`.
4. **[04] Recursion guard** — exclude the extractor's own transcript at the single chokepoint
   (`_ingest_session`) AND in `on_created`/`on_modified`, covering the live FSEvents path (the
   extractor's `claude -p` session is a normal transcript, NOT under `subagents/`). Integration test.
5. **[05] Hook defers to a RUNNING watcher** — the whisper-out hook skips extraction only when the
   server reports the watcher is actually active, not merely when a config flag is set.
6. **[06] Enablement + end-to-end** — set `ingest_llm_provider=claude_cli`, restart, verify: zero
   Ollama `/api/generate` for extraction, extraction via Claude, worker transcript not re-ingested,
   maintenance still on its own provider.

## Non-goals (locked in spec)

No gemma fallback (Claude-or-defer). No agentic SDK worker. No change to whisper-**in**/recall.
**No migration of background maintenance jobs off their current LLM path** — enforced by the separate
`ingest_llm_provider` (Task 03).

## Cross-cutting invariants

- **No API:** the adapter strips `ANTHROPIC_API_KEY` from the child env; Task 01 proves the child then
  uses subscription OAuth **under launchd**. Removing that strip breaks the "no API" guarantee.
- **No privacy/argv leak:** the transcript prompt goes on **stdin**, never argv (avoids leaking
  conversation text to the process list and `ARG_MAX` failures on large transcripts).
- **Maintenance isolation:** extraction uses `ingest_llm_provider`; `llm_provider` (maintenance) is
  never forced to `claude_cli` by this feature.
- **Untrusted-input boundary:** the transcript is untrusted (prompt-injection vector); the `claude -p`
  worker runs with ALL agent tools denied (`_TOOL_DENY_ARGS`) — it can emit text, never act.
- **Fail-to-defer:** any `claude -p` failure returns `None` → ingest does not advance the cursor →
  next watcher scan retries. The hook fallback also refuses to advance its cursor on a 200-with-error
  ingest response (no silent loss).
- **Runtime liveness:** `/admin/health` reports `session_watcher_active` from live observer state
  (`is_alive()`), not a startup flag, so the hook falls back if the watcher thread dies.
- **Bounded concurrency:** at most `claude_cli_max_concurrency` (default 1) `claude -p` at once.
- **Single extraction path when the watcher runs:** the hook defers to a *running* watcher, so one
  cursor governs extraction; if the watcher is down, the hook still extracts (no silent loss).
- **Haiku pinned:** `--model` from `claude_cli_model` (default `haiku`), independent of the session model.
