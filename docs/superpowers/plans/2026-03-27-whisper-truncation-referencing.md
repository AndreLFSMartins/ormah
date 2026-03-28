# Whisper Flat Ranked Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace whisper's category-split, truncation-heavy output with a flat ranked list — top 2 nodes shown in full, nodes 3–6 shown as title + node ID only — so memories are either readable or referenceable, never broken mid-sentence.

**Architecture:** Single flat list built directly from `search_results` (already ranked by score). Remove the identity/core/working split from `context_builder.py`. Remove unused budget config params. Keep `format_identity_section` in `traversal.py` (still used by `get_self`); delete `format_context` and `format_context_with_project`.

**Tech Stack:** Python, pytest. All changes in `src/ormah/`. Tests in `tests/test_engine/test_whisper_context.py`.

**Working directory:** `/home/r2205/Projects/ormah/.worktrees/whisper-truncation-and-referencing`

---

## File Map

| File | Change |
|------|--------|
| `src/ormah/config.py` | Remove 5 obsolete whisper params, change `whisper_max_nodes` default 8→6 |
| `src/ormah/engine/context_builder.py` | Rewrite formatting section; new `full_content_count` param; update framing |
| `src/ormah/engine/memory_engine.py` | Remove removed params from `get_whisper_context` call |
| `src/ormah/engine/traversal.py` | Delete `format_context` and `format_context_with_project` |
| `src/ormah/adapters/tool_schemas.py` | Update `remember` tool `title` description |
| `tests/test_engine/test_whisper_context.py` | Add new flat-format tests; remove/update tests for deleted behaviour |

---

## Task 1: Update config defaults

**Files:**
- Modify: `src/ormah/config.py`

- [ ] **Step 1: Read the current whisper config block**

Open `src/ormah/config.py` and find the whisper section (around line 146). The current params are:

```python
whisper_max_nodes: int = 8
whisper_min_relevance_score: float = 0.45
whisper_identity_max_nodes: int = 5
whisper_content_max_chars: int = 150
...
whisper_content_total_budget: int = 1500
whisper_content_min_per_node: int = 100
whisper_content_max_per_node: int = 600
```

- [ ] **Step 2: Apply changes**

Make these edits:
- Change `whisper_max_nodes: int = 8` → `whisper_max_nodes: int = 6`
- Delete the line `whisper_identity_max_nodes: int = 5`
- Delete the line `whisper_content_max_chars: int = 150`
- Delete the line `whisper_content_total_budget: int = 1500`
- Delete the line `whisper_content_min_per_node: int = 100`
- Delete the line `whisper_content_max_per_node: int = 600`

- [ ] **Step 3: Verify no remaining references to deleted fields**

```bash
grep -rn "whisper_identity_max_nodes\|whisper_content_max_chars\|whisper_content_total_budget\|whisper_content_min_per_node\|whisper_content_max_per_node" src/
```

Expected: no output (we'll fix any remaining references in later tasks).

- [ ] **Step 4: Commit**

```bash
git add src/ormah/config.py
git commit -m "config: remove obsolete whisper budget params, set max_nodes=6"
```

---

## Task 2: Write failing tests for flat ranked display

**Files:**
- Modify: `tests/test_engine/test_whisper_context.py`

- [ ] **Step 1: Add a new test class at the end of the file**

Append this class to `tests/test_engine/test_whisper_context.py`:

```python
class TestWhisperFlatRankedDisplay:
    """Whisper outputs a flat ranked list — top 2 full, rest title+ID only."""

    def test_top_two_nodes_shown_in_full(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        nodes = [
            {**_make_node_dict(f"node-{i}", f"Title {i}"), "content": f"Full content for node {i}, longer than a title."}
            for i in range(4)
        ]
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.9, "source": "hybrid"},
            {"node": nodes[1], "score": 0.8, "source": "hybrid"},
            {"node": nodes[2], "score": 0.7, "source": "hybrid"},
            {"node": nodes[3], "score": 0.6, "source": "hybrid"},
        ]

        result = builder.build_whisper_context(
            prompt="tell me about nodes",
            injection_gate=0.0,
        )

        # Top 2 show full content
        assert "Full content for node 0" in result
        assert "Full content for node 1" in result
        # Nodes 3-4 do NOT show content
        assert "Full content for node 2" not in result
        assert "Full content for node 3" not in result

    def test_remaining_nodes_show_title_and_id_only(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        nodes = [
            {**_make_node_dict(f"abcd{i:04d}", f"Title {i}"), "content": f"Full content for node {i}."}
            for i in range(4)
        ]
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.9, "source": "hybrid"},
            {"node": nodes[1], "score": 0.8, "source": "hybrid"},
            {"node": nodes[2], "score": 0.7, "source": "hybrid"},
            {"node": nodes[3], "score": 0.6, "source": "hybrid"},
        ]

        result = builder.build_whisper_context(
            prompt="tell me about nodes",
            injection_gate=0.0,
        )

        # Nodes 3-4 show title and ID
        assert "Title 2" in result
        assert "abcd0002" in result
        assert "Title 3" in result
        assert "abcd0003" in result

    def test_all_nodes_have_node_id(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        nodes = [
            _make_node_dict(f"nodeid{i:02d}", f"Title {i}")
            for i in range(3)
        ]
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.9, "source": "hybrid"},
            {"node": nodes[1], "score": 0.8, "source": "hybrid"},
            {"node": nodes[2], "score": 0.7, "source": "hybrid"},
        ]

        result = builder.build_whisper_context(
            prompt="tell me about nodes",
            injection_gate=0.0,
        )

        # All nodes show their IDs
        assert "nodeid00" in result
        assert "nodeid01" in result
        assert "nodeid02" in result

    def test_no_section_headers(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        # Mix of tiers and types
        nodes = [
            {**_make_node_dict("core-001", "Core fact", tier="core"), "content": "Some core content."},
            {**_make_node_dict("work-001", "Working fact", tier="working"), "content": "Some working content."},
        ]
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.9, "source": "hybrid"},
            {"node": nodes[1], "score": 0.8, "source": "hybrid"},
        ]

        result = builder.build_whisper_context(
            prompt="tell me something",
            injection_gate=0.0,
        )

        assert "## About the User" not in result
        assert "## Core Memories" not in result
        assert "## Project:" not in result

    def test_flat_list_preserves_search_result_order(self, mock_graph):
        # recall_search_structured always returns results sorted by score descending.
        # Whisper should preserve that order — first result in list = first in output.
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        nodes = [
            _make_node_dict("high-score", "High score title"),
            _make_node_dict("low-score", "Low score title"),
        ]
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.9, "source": "hybrid"},
            {"node": nodes[1], "score": 0.6, "source": "hybrid"},
        ]

        result = builder.build_whisper_context(
            prompt="tell me something",
            injection_gate=0.0,
        )

        # First result in search appears first in output
        high_pos = result.index("High score title")
        low_pos = result.index("Low score title")
        assert high_pos < low_pos

    def test_framing_text_updated(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        nodes = [_make_node_dict("node-x", "Some title")]
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.9, "source": "hybrid"},
        ]

        result = builder.build_whisper_context(
            prompt="something",
            injection_gate=0.0,
        )

        assert "The 2 most relevant memories are shown in full" in result
        assert "use recall with its node ID" in result
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
cd /home/r2205/Projects/ormah && uv run pytest tests/test_engine/test_whisper_context.py::TestWhisperFlatRankedDisplay -v 2>&1 | tail -30
```

Expected: All 6 tests FAIL (old behaviour still in place).

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_engine/test_whisper_context.py
git commit -m "test: add failing tests for flat ranked whisper display"
```

---

## Task 3: Rewrite `build_whisper_context` formatting section

**Files:**
- Modify: `src/ormah/engine/context_builder.py`

- [ ] **Step 1: Update the framing constant (line 20–25)**

Replace the `_WHISPER_FRAMING` constant:

```python
_WHISPER_FRAMING = (
    "# Ormah whispers\n"
    "The 2 most relevant memories are shown in full. The rest are titles only. "
    "If any memory looks relevant or interesting, use recall with its node ID "
    "to get the full content and related memories."
)
```

- [ ] **Step 2: Add `full_content_count` parameter to `build_whisper_context`**

In the method signature (around line 197), add after `max_nodes: int = 8`:

```python
full_content_count: int = 2,
```

And remove these parameters entirely from the signature:
- `identity_max: int = 5`
- `max_content_len: int = 150`
- `content_total_budget: int = 0`
- `content_min_per_node: int = 100`
- `content_max_per_node: int = 500`

- [ ] **Step 3: Remove the identity/core/working split and replace with flat list**

Find the block starting at `# Separate identity nodes from search results` (~line 447) through to the end of the formatting section (~line 555), and replace the entire block with:

```python
        # Cap to max_nodes (already ordered by relevance score, or by recency for temporal queries)
        search_results = search_results[:max_nodes]

        # Build flat ranked list — top full_content_count get full content,
        # rest get title + type + node ID only.
        lines = []
        for i, r in enumerate(search_results):
            node = r["node"]
            node_id = node.get("id", "")
            short_id = node_id[:8] if node_id else ""
            title = node.get("title") or (node.get("content", "")[:60].strip() + "…")
            node_type = node.get("type", "fact")
            id_suffix = f" (id: {short_id})" if short_id else ""

            lines.append(f"- **[{node_type}]** {title}{id_suffix}")

            if i < full_content_count:
                content = node.get("content", "").strip()
                if content and content != title:
                    lines.append(f"  {content}")

            lines.append("")

        body = "\n".join(lines).rstrip()
```

- [ ] **Step 4: Remove the old imports of the three traversal formatters**

At the top of `context_builder.py` (lines 11–15), remove:

```python
from ormah.engine.traversal import (
    format_context,
    format_context_with_project,
    format_identity_section,
)
```

These are no longer used in this file.

- [ ] **Step 5: Run the new tests**

```bash
cd /home/r2205/Projects/ormah && uv run pytest tests/test_engine/test_whisper_context.py::TestWhisperFlatRankedDisplay -v 2>&1 | tail -20
```

Expected: All 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/engine/context_builder.py
git commit -m "feat: rewrite whisper output as flat ranked list, top 2 full + rest title-only"
```

---

## Task 4: Fix broken existing tests

**Files:**
- Modify: `tests/test_engine/test_whisper_context.py`

- [ ] **Step 1: Run the full whisper test suite to see what's broken**

```bash
cd /home/r2205/Projects/ormah && uv run pytest tests/test_engine/test_whisper_context.py -v 2>&1 | grep -E "PASSED|FAILED|ERROR" | head -60
```

- [ ] **Step 2: Remove `TestWhisperIdentityCap` entirely**

The identity cap (`identity_max`) no longer exists. Delete the entire class:

```python
class TestWhisperIdentityCap:
    """Tests that identity nodes are capped to identity_max."""
    ...
```

- [ ] **Step 3: Remove `TestWhisperDynamicContentBudget` entirely**

The content budget params no longer exist. Delete the entire class:

```python
class TestWhisperDynamicContentBudget:
    ...
```

- [ ] **Step 4: Remove `TestWhisperIdentityGating` entirely**

The identity/other split is gone. Delete the entire class:

```python
class TestWhisperIdentityGating:
    ...
```

- [ ] **Step 5: Update `TestWhisperCompactFormatting`**

`test_content_truncated_to_max_content_len` tests the old truncation behaviour. Replace it:

```python
class TestWhisperCompactFormatting:
    """Whisper formatting: flat list, top 2 full, rest title-only."""

    def test_top_node_content_not_truncated(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        long_content = "A" * 600
        node = {**_make_node_dict("node-1", "Some title"), "content": long_content}
        mock_engine.recall_search_structured.return_value = [
            {"node": node, "score": 0.9, "source": "hybrid"},
        ]

        result = builder.build_whisper_context(
            prompt="something",
            injection_gate=0.0,
        )

        assert long_content in result
```

- [ ] **Step 6: Update `TestWhisperNodeLimit`**

The max is now 6. Find `test_respects_max_nodes` and update the assertion:

```python
def test_respects_max_nodes(self, mock_graph):
    mock_engine = MagicMock()
    builder = ContextBuilder(mock_graph, engine=mock_engine)

    nodes = [_make_node_dict(f"node-{i}", f"Fact {i}") for i in range(10)]
    mock_engine.recall_search_structured.return_value = [
        {"node": n, "score": 0.9 - i * 0.05, "source": "hybrid"}
        for i, n in enumerate(nodes)
    ]

    result = builder.build_whisper_context(
        prompt="tell me everything",
        max_nodes=6,
        injection_gate=0.0,
    )

    shown = sum(1 for i in range(10) if f"Fact {i}" in result)
    assert shown <= 6
```

Remove `test_total_budget_respected` — the budget concept no longer exists.

- [ ] **Step 7: Update `TestWhisperWithProject`**

`test_with_space_formats_project_section` checks for `## Project: myproject` which no longer appears. Replace it:

```python
class TestWhisperWithProject:
    """Space param still filters results correctly."""

    def test_with_space_passes_space_to_search(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        node = _make_node_dict("node-1", "Project fact", space="myproject")
        mock_engine.recall_search_structured.return_value = [
            {"node": node, "score": 0.9, "source": "hybrid"},
        ]

        builder.build_whisper_context(
            prompt="project stuff",
            space="myproject",
            injection_gate=0.0,
        )

        call_kwargs = mock_engine.recall_search_structured.call_args[1]
        assert call_kwargs["default_space"] == "myproject"
```

- [ ] **Step 8: Run the full test suite again**

```bash
cd /home/r2205/Projects/ormah && uv run pytest tests/test_engine/test_whisper_context.py -v 2>&1 | tail -30
```

Expected: All remaining tests PASS.

- [ ] **Step 9: Commit**

```bash
git add tests/test_engine/test_whisper_context.py
git commit -m "test: remove obsolete whisper tests, update for flat ranked display"
```

---

## Task 5: Remove dead params from `memory_engine.py` caller

**Files:**
- Modify: `src/ormah/engine/memory_engine.py`

- [ ] **Step 1: Find the `get_whisper_context` method (around line 740)**

The call to `build_whisper_context` currently passes these params that no longer exist:

```python
identity_max=self.settings.whisper_identity_max_nodes,
max_content_len=self.settings.whisper_content_max_chars,
content_total_budget=self.settings.whisper_content_total_budget,
content_min_per_node=self.settings.whisper_content_min_per_node,
content_max_per_node=self.settings.whisper_content_max_per_node,
```

Remove all five lines.

- [ ] **Step 2: Run the full test suite**

```bash
cd /home/r2205/Projects/ormah && uv run pytest tests/ -x -q 2>&1 | tail -20
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/ormah/engine/memory_engine.py
git commit -m "feat: remove obsolete whisper params from memory_engine caller"
```

---

## Task 6: Delete dead traversal formatters

**Files:**
- Modify: `src/ormah/engine/traversal.py`

- [ ] **Step 1: Confirm `format_identity_section` is still needed**

```bash
grep -rn "format_identity_section" src/
```

Expected: one hit in `memory_engine.py` (used by `get_self`). Do NOT delete it.

- [ ] **Step 2: Confirm `format_context` and `format_context_with_project` are unused**

```bash
grep -rn "format_context\b\|format_context_with_project" src/
```

Expected: only their definitions in `traversal.py`. If any other file imports them, stop and investigate before deleting.

- [ ] **Step 3: Delete the two functions from `traversal.py`**

Delete `def format_context(...)` (lines ~143–163) and `def format_context_with_project(...)` (lines ~166–207) entirely.

- [ ] **Step 4: Run full test suite**

```bash
cd /home/r2205/Projects/ormah && uv run pytest tests/ -x -q 2>&1 | tail -20
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/traversal.py
git commit -m "refactor: delete unused traversal formatters format_context and format_context_with_project"
```

---

## Task 7: Update `remember` tool description

**Files:**
- Modify: `src/ormah/adapters/tool_schemas.py`

- [ ] **Step 1: Find the `title` field description (around line 43)**

Current:
```python
"title": {
    "type": "string",
    "description": "Short descriptive title for the memory.",
},
```

Replace with:
```python
"title": {
    "type": "string",
    "description": (
        "Short descriptive title for the memory. "
        "Write it as a self-contained one-line summary — "
        "whisper shows only the title when this memory is not in the top 2 results, "
        "so it must convey the key fact on its own."
    ),
},
```

- [ ] **Step 2: Run the full test suite**

```bash
cd /home/r2205/Projects/ormah && uv run pytest tests/ -q 2>&1 | tail -10
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/ormah/adapters/tool_schemas.py
git commit -m "feat: update remember tool title description to emphasize self-contained summary"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run full test suite clean**

```bash
cd /home/r2205/Projects/ormah && uv run pytest tests/ -q 2>&1 | tail -10
```

Expected: All tests pass, 0 errors.

- [ ] **Step 2: Reinstall and smoke test**

```bash
cd /home/r2205/Projects/ormah && uv tool install . --reinstall
```

Start the server and check a whisper response manually to confirm flat output with no section headers.

- [ ] **Step 3: Verify no orphaned references to removed config fields**

```bash
grep -rn "whisper_identity_max_nodes\|whisper_content_max_chars\|whisper_content_total_budget\|whisper_content_min_per_node\|whisper_content_max_per_node" src/ tests/
```

Expected: no output.
