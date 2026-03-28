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

Strict Rule: When fixing issues always make sure you are fixing the root cause and not patching or papering over issues.
