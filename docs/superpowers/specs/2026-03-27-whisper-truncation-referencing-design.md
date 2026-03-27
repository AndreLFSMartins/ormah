# Whisper: Flat Ranked Display with Truncation and Referencing

**Date:** 2026-03-27
**Branch:** `feature/whisper-truncation-and-referencing`
**Status:** Approved

---

## Problem

The current whisper output has two issues:

1. **Category noise** — memories are split into `## About the User`, `## Core Memories`, and `## Project: <space>` sections. These headers are formatting artifacts that add visual noise and waste context. The underlying search already ranks by relevance — category labels carry no additional signal.

2. **Truncation renders memories meaningless** — with a fixed total budget divided evenly across all nodes, any session with 5+ results produces heavily truncated content. A memory truncated mid-sentence is often worse than no memory at all: it consumes context without conveying meaning.

---

## Design

### Output Format

A single flat list, ordered by relevance score, capped at **6 nodes**.

**Top 2 nodes — full content + node ID:**
```
- **[decision]** Whisper quality is #1 priority — quiet when irrelevant (id: ffdf91e1)
  Whisper quality is the #1 priority for ormah right now. User said "this is core." The focus
  is: whisper should show relevant memories when they exist, and be completely quiet when
  nothing is relevant. "A whisper, not noise."
```

**Nodes 3–6 — title + type + node ID only:**
```
- **[decision]** Strategic bet: whisper as ormah's core differentiator (id: b4952edc)
- **[fact]** User's home PC specs (id: 99eccdc3)
```

### Framing Text

```
# Ormah whispers
The 2 most relevant memories are shown in full. The rest are titles only. If any memory
looks relevant or interesting, use recall with its node ID to get the full content and
related memories.
```

### Recall as the Referencing Mechanism

Node IDs are shown on all 6 entries. The model can call `recall` on any of them:
- On a title-only entry: to read the full content
- On a full entry: to get spreading activation results (graph neighbors, related memories)

This makes whisper a ranked index. The model decides what to probe further — whisper doesn't try to guess what content depth is needed.

### Title as Summary

For nodes 3–6, the title is the only signal. This means **titles must be descriptive and self-contained**. A title like `"Whisper quality is #1 priority — quiet when irrelevant"` works. A title like `"Memory note"` does not.

The `remember` tool description will be updated to emphasize: **the title is shown as a one-line summary when the memory isn't in the top 2 — write it so it stands alone**.

---

## Code Changes

### `src/ormah/engine/context_builder.py`

- Remove the identity/core/working split (lines ~452–506)
- Build a single ordered list from `search_results` (already ranked by score)
- Add `full_content_count: int = 2` parameter to `build_whisper_context`
- Format inline: top `full_content_count` nodes get full content + ID; rest get title + type + ID only
- Remove all calls to `format_identity_section`, `format_context`, `format_context_with_project`
- Update `_WHISPER_FRAMING` to the new text above

### `src/ormah/engine/traversal.py`

- Check if `format_identity_section`, `format_context`, `format_context_with_project` are used outside `context_builder.py`
- Delete any that are now dead code

### `src/ormah/config.py`

- `whisper_max_nodes`: 8 → 6
- Remove `whisper_identity_max_nodes` (no longer meaningful without the split)
- Remove `whisper_content_total_budget`, `whisper_content_min_per_node`, `whisper_content_max_per_node` (replaced by fixed full/title logic)

### MCP tool schema (`src/ormah/adapters/tool_schemas.py`)

- Update `remember` tool description to emphasize: title must be a self-contained one-line summary

---

## What Does Not Change

- Relevance scoring, reranker, affinity boost, injection gate — unchanged
- Topic-shift detection, intent classification — unchanged
- Session/space scoping — unchanged
- whisper_log logging — unchanged
- The `get_self` tool — unchanged (still uses `format_identity_section` if that formatter is kept)
- Review candidate mechanism (first-message surfacing) — unchanged

---

## Success Criteria

- Whisper output never shows truncated mid-sentence content
- Top 2 memories are always readable and complete
- Nodes 3–6 have enough signal (title) to decide whether to call `recall`
- Total whisper token footprint is reduced compared to current (fewer nodes, no section headers, title-only for 4 of 6)
