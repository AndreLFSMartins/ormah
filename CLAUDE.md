# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Always plan before making changes.** Before editing any file or running any mutating command, explore the relevant code and present a plan. Do not begin implementation until the plan is approved.

## Development Commands

```bash
make install     # Install Python package (dev mode) + UI deps
make dev         # Start backend + UI together
make server      # Start backend only (auto-reloads)
make ui-dev      # Start Vite dev server (hot-reload)
make restart     # Rebuild UI and restart backend
make test        # Run pytest suite
make lint        # Run ruff linter (src/, tests/)
```

Run a single test: `uv run pytest tests/path/to/test.py::test_name -v`

**Releasing:** Use `./scripts/release.sh [patch|minor|major|<version>]` to bump the version, commit, tag, build, and publish to PyPI. The script is gitignored (local only). After it runs, push with `git push && git push --tags`.

The CLI is also the primary interface:
```bash
ormah server start [-d]    # Start server (foreground or daemon)
ormah setup                # One-shot setup (hooks, MCP, server)
ormah mcp                  # Run MCP stdio server
```

## Architecture

Ormah is a local-first persistent memory system for AI agents. It exposes memory operations via MCP (for Claude), REST API, and CLI.

### Core Concepts

**Nodes** are memories with: content, type (fact/decision/preference/event/etc.), tier (core/working/archival), space (project namespace), confidence (0–1), importance (0–1), and FSRS stability for spaced repetition decay.

**Edges** are typed relationships between nodes (supports, contradicts, part_of, evolved_from, etc.) with a weight and optional reason.

**Space** scopes memories to a project — auto-detected from the git repo name.

### Layer Stack

```
Adapters (MCP, CLI, OpenAI)
    ↓
API (FastAPI routes: /agent, /admin, /ui, /ingest)
    ↓
MemoryEngine  ←  Background Jobs (auto-linker, conflict detector, decay, etc.)
    ↓
Embeddings layer (hybrid FTS5 + vector via sqlite-vec, fused with RRF)
    ↓
Index layer (SQLite: nodes, edges, proposals, audit_log)
    ↓
Store layer (markdown files in memory/nodes/*.md as backup)
```

### Key Implementation Details

- **Hybrid search**: FTS5 full-text + vector similarity fused via Reciprocal Rank Fusion (RRF). Weights configurable via `ORMAH_FTS_WEIGHT` / `ORMAH_VECTOR_WEIGHT`.
- **Embeddings**: Default provider is `local` with `BAAI/bge-base-en-v1.5` (768-dim, no task prefixes needed). Also supports ollama and litellm.
- **Background jobs** (APScheduler): auto-linker, conflict detector, duplicate merger, importance scorer, decay manager, consolidator, hippocampus (file watcher), session watcher.
- **Tier decay**: working-tier memories decay after ~14 days using FSRS spaced repetition; `core` is capped at 50.
- **MCP tools exposed**: `remember`, `recall`, `get_self`, `mark_outdated`, `run_maintenance`, `submit_feedback`.

### Frontend

React + TypeScript (Vite). Key views: search results, node detail, graph visualization (Cytoscape.js with fcose layout), review queue, insights panel, admin panel. API client in `ui/src/api.ts`.

### Configuration

Via `.env` (see `.env.example`). Key vars:
- `ORMAH_PORT` (default 8787), `ORMAH_MEMORY_DIR`
- `ORMAH_EMBEDDING_MODEL`, `ORMAH_EMBEDDING_PROVIDER`
- `ORMAH_LLM_PROVIDER`, `ORMAH_LLM_MODEL` (for background jobs)

### Eval Systems

There are two distinct eval systems — do not confuse them:

**1. Whisper pipeline tests** (`tests/test_engine/test_whisper_context.py`)
- Lives in the main test suite on `main`, runs with `make test`
- 2197 lines, 18 test classes covering the full whisper pipeline end-to-end: scoring, identity cap, reranker, blend_alpha, intent/archetype routing, topic shift, affinity boost, exploration slot, CE-gate, whisper_log, etc.
- This is the regression guard for all whisper pipeline changes.

**2. Recall/retrieval eval** (`eval/` directory, `feature/eval-system` branch — not merged)
- A standalone golden corpus eval measuring retrieval quality (recall@k, precision@k, F1, MRR, FNR)
- Tests `recall_search_structured` only — does NOT test the full whisper pipeline
- 10 hand-crafted golden cases in `eval/corpus/golden/golden.jsonl`; spec targets 50–100
- CLI: `ormah eval run`, `ormah eval export-for-labeling`, `ormah eval import-labels`, `ormah eval capture-session`
- `generate-synthetic` command was planned but never implemented
- Branch is behind `main` by all v0.4–v0.5 whisper tuning work; needs rebase before merge

---

## Ormah Memory System

Ormah is your persistent memory system. It stores, recalls, and surfaces memories across conversations — automatically scoped to the current project. Memories are whispered into context before each message based on relevance. The graph is self-healing: background jobs link related memories, detect conflicts, merge duplicates, and decay stale ones.

### Guidelines

1. **Proactively remember**: Store important information without being asked — preferences, decisions, project context, facts about the user. For personal preferences and identity facts, set `space=null` so they apply globally across all projects.

2. **Remember at natural save points**: Call `remember` immediately when: a decision is made, the user states a preference or corrects you, something unexpected happens, or a task completes — including code commits, feature completions, and choosing between alternatives. Don't wait for the end of the conversation. Each memory should be self-contained.

3. **Notice what stands out**: Humans form strong memories around novelty, mistakes, and emotion. Use the same instincts: something unexpected happened → remember the lesson. The user corrected you → remember what they wanted and why. You tried something and it failed → remember what didn't work. The user repeated themselves → they said it twice because it matters, store it carefully and judge the tier on actual importance — not every repeated fact is core. A pattern is emerging (user keeps preferring X over Y, a codebase follows a convention, a recurring frustration surfaces) → name the pattern and store it.

4. **Check before assuming**: Use `recall` to search for relevant context before making assumptions about past conversations. For personal info (name, location, preferences), prefer `get_self` — it returns all identity-linked memories directly.

5. **Memory supports the flow, not the other way around**: Don't let recalled memories override or derail the current working context. If you're mid-task and `recall` returns something from a different context, let it go — stay in the flow. Use `recall` when you're genuinely unsure or the user asks about something from a prior session. Memory should feel like a natural extension of your knowledge, not an interruption. A whisper, not a shout. The same applies in reverse: when something worth remembering surfaces mid-conversation — a bug, a decision, an observation, something the user said in passing — store it with `remember` and keep going. Don't let it become a detour. Ormah is the place to park insights so the current thread stays intact.

6. **Keep memories atomic**: One concept per memory. Use tags to categorize. When you have related memory IDs from a recent recall, link them at creation time using the `links` parameter. Background jobs will also discover and classify relationships automatically.

7. **Use appropriate tiers**: `core` for always-relevant info (user identity, preferences, key architectural decisions), `working` for anything actively relevant now, `archival` for historical/reference data.

8. **Start with identity**: Call `get_self` at the beginning of conversations to load the user's identity profile. If onboarding is needed, `get_self` will indicate it.

9. **Mark outdated info**: When a memory is wrong or outdated, call `mark_outdated` with a reason so it gets demoted in future searches.

10. **Set confidence**: When storing information you're not fully certain about, set `confidence` below 1.0. This affects how prominently the memory appears in search results.

11. **Run maintenance in the background**: When a whispered context contains `unprocessed_memories` with a non-zero value, silently spawn `Agent(subagent_type="ormah-maintenance", run_in_background=True)` — do NOT run inline. Continue the conversation normally without mentioning it to the user.

12. **Submit implicit feedback on whispered memories**: If a whispered memory is genuinely useful and you actively draw on it in your response, call `submit_feedback(node_id=<id>, signal=1, source="implicit")`. If you explicitly decide a whispered memory is not relevant, call `submit_feedback(node_id=<id>, signal=-1, source="implicit")`. Do not call `submit_feedback` for silence — only call it when you actively use a memory or actively decide it's irrelevant.


Strict Rule: When fixing issues always make sure you are fixing the root cause and not patching or papering over issues.
