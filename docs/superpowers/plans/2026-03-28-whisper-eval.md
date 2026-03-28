# Whisper Eval System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone evaluation system that measures whisper pipeline quality end-to-end, broken down by 8 query categories, with a CLI to run it.

**Architecture:** Add `_return_debug` to `build_whisper_context` to return injected node IDs alongside the text; build `eval/whisper/` with seeder, corpus loader, metrics, runner, report, and CLI; wire `ormah eval whisper run` into the main CLI. All code except the two-line debug flag lives outside `src/ormah/`.

**Tech Stack:** Python, pytest, argparse, SQLite (via existing MemoryEngine), JSONL corpus format.

---

## File Map

**Modified:**
- `src/ormah/engine/context_builder.py` — add `_return_debug: bool = False` param, capture `_injected_ids` after cap
- `src/ormah/engine/memory_engine.py` — thread `_return_debug` through `get_whisper_context`
- `src/ormah/cli.py` — add `eval whisper run` subcommand

**Created:**
- `eval/whisper/__init__.py`
- `eval/whisper/seeder.py` — clear eval DB and seed a corpus case
- `eval/whisper/corpus.py` — load + validate JSONL corpus
- `eval/whisper/metrics.py` — injection_recall, precision, f1, top2_recall, suppression_accuracy
- `eval/whisper/runner.py` — orchestrate seeding + pipeline calls + metric collection
- `eval/whisper/report.py` — format per-category table + failure list
- `eval/whisper/cli.py` — cmd_eval_whisper_run handler
- `eval/whisper/corpus/golden/golden.jsonl` — 37 prompts across 8 categories
- `tests/test_eval_whisper/__init__.py`
- `tests/test_eval_whisper/test_metrics.py`
- `tests/test_eval_whisper/test_corpus.py`
- `tests/test_eval_whisper/test_runner.py`
- `tests/test_eval_whisper/test_report.py`
- `tests/test_eval_whisper/test_seeder.py`
- `tests/test_engine/test_whisper_debug.py`

---

## Task 1: `_return_debug` on `build_whisper_context` and `get_whisper_context`

**Context:**

Before this task, `build_whisper_context` returns a `str`. The eval runner needs to know which node IDs were injected without parsing the output text.

**Before:**
```python
# engine.get_whisper_context("what port does ormah run on", space="ormah")
# → "# Ormah whispers\n\n- **[fact]** Ormah runs on port 8787 (id: abcd1234)\n  ..."
```

**After:**
```python
# engine.get_whisper_context("what port...", space="ormah", _return_debug=True)
# → ("# Ormah whispers\n\n- **[fact]** ...", ["full-uuid-of-port-node"])
```

**Files:**
- Modify: `src/ormah/engine/context_builder.py`
- Modify: `src/ormah/engine/memory_engine.py`
- Test: `tests/test_engine/test_whisper_debug.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_whisper_debug.py`:

```python
"""Tests for _return_debug mode on build_whisper_context."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from ormah.engine.context_builder import ContextBuilder
from ormah.index.graph import GraphIndex


def _make_node(node_id, title, node_type="fact"):
    return {
        "id": node_id, "type": node_type, "tier": "working",
        "title": title, "content": f"Content for {title}.",
        "space": None, "importance": 0.5, "confidence": 1.0,
        "valid_until": None, "source": "test", "access_count": 0,
        "last_accessed": "2026-01-01T00:00:00Z",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_graph(tmp_path):
    from ormah.index.db import Database
    db = Database(tmp_path / "index.db")
    db.init_schema()
    return GraphIndex(db.conn)


class TestWhisperDebugMode:
    def test_debug_returns_tuple(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)
        node = _make_node("node-abc12345", "Port fact")
        mock_engine.recall_search_structured.return_value = [
            {"node": node, "score": 0.9, "source": "hybrid"},
        ]
        result = builder.build_whisper_context(
            prompt="what port", injection_gate=0.0, _return_debug=True
        )
        assert isinstance(result, tuple)
        whisper_text, injected_ids = result
        assert isinstance(whisper_text, str)
        assert injected_ids == ["node-abc12345"]

    def test_debug_suppressed_returns_empty_ids(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)
        mock_engine.recall_search_structured.return_value = []
        whisper_text, injected_ids = builder.build_whisper_context(
            prompt="what port", _return_debug=True
        )
        assert whisper_text == ""
        assert injected_ids == []

    def test_debug_multiple_nodes_returns_all_ids(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)
        nodes = [_make_node(f"node-{i:08d}", f"Fact {i}") for i in range(3)]
        mock_engine.recall_search_structured.return_value = [
            {"node": n, "score": 0.9 - i * 0.1, "source": "hybrid"}
            for i, n in enumerate(nodes)
        ]
        _, injected_ids = builder.build_whisper_context(
            prompt="some query", injection_gate=0.0, _return_debug=True
        )
        assert injected_ids == ["node-00000000", "node-00000001", "node-00000002"]

    def test_no_debug_returns_string(self, mock_graph):
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)
        node = _make_node("node-1", "A fact")
        mock_engine.recall_search_structured.return_value = [
            {"node": node, "score": 0.9, "source": "hybrid"},
        ]
        result = builder.build_whisper_context(
            prompt="query", injection_gate=0.0, _return_debug=False
        )
        assert isinstance(result, str)

    def test_debug_ids_respect_gate(self, mock_graph):
        """Nodes that don't clear the injection gate should not appear in injected_ids."""
        mock_engine = MagicMock()
        builder = ContextBuilder(mock_graph, engine=mock_engine)
        nodes = [_make_node(f"node-{i}", f"Fact {i}") for i in range(2)]
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.8, "source": "hybrid"},
            {"node": nodes[1], "score": 0.3, "source": "hybrid"},
        ]
        _, injected_ids = builder.build_whisper_context(
            prompt="query", min_score=0.1, injection_gate=0.55, _return_debug=True
        )
        assert "node-0" in injected_ids
        assert "node-1" not in injected_ids
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/r2205/Projects/ormah/.worktrees/whisper-eval
uv run pytest tests/test_engine/test_whisper_debug.py -v 2>&1 | head -30
```

Expected: `TypeError: build_whisper_context() got an unexpected keyword argument '_return_debug'`

- [ ] **Step 3: Implement `_return_debug` in `context_builder.py`**

In `src/ormah/engine/context_builder.py`, make two changes:

**Change 1** — add param to signature (line ~202, after `session_id: str | None = None,`):

```python
    session_id: str | None = None,
    _return_debug: bool = False,
) -> str | tuple[str, list[str]]:
```

**Change 2** — capture IDs after the cap (line ~430, after `search_results = search_results[:max_nodes]`):

```python
        # Cap to max_nodes (already ordered by relevance score, or by recency for temporal queries)
        search_results = search_results[:max_nodes]
        _injected_ids = [r["node"]["id"] for r in search_results]
```

**Change 3** — at the end of the method, replace `return result` with:

```python
        if _return_debug:
            return result, _injected_ids
        return result
```

- [ ] **Step 4: Thread `_return_debug` through `get_whisper_context` in `memory_engine.py`**

Find `get_whisper_context` (line ~735). Replace:

```python
    def get_whisper_context(
        self,
        prompt: str,
        space: str | None = None,
        recent_prompts: list[str] | None = None,
        session_id: str | None = None,
        _return_debug: bool = False,
    ) -> str | tuple[str, list[str]]:
        """Get compact whisper context for involuntary recall injection."""
        return self.context_builder.build_whisper_context(
            prompt=prompt,
            space=space,
            max_nodes=self.settings.whisper_max_nodes,
            min_score=self.settings.whisper_min_relevance_score,
            reranker_enabled=self.settings.whisper_reranker_enabled,
            reranker_model=self.settings.whisper_reranker_model,
            reranker_min_score=self.settings.whisper_reranker_min_score,
            reranker_blend_alpha=self.settings.whisper_reranker_blend_alpha,
            reranker_max_doc_chars=self.settings.whisper_reranker_max_doc_chars,
            recent_prompts=recent_prompts,
            injection_gate=self.settings.whisper_injection_gate,
            topic_shift_enabled=self.settings.whisper_topic_shift_enabled,
            topic_shift_threshold=self.settings.whisper_topic_shift_threshold,
            session_id=session_id,
            _return_debug=_return_debug,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_engine/test_whisper_debug.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Run full test suite to check no regressions**

```bash
uv run pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all passing (same count as before).

- [ ] **Step 7: Commit**

```bash
git add src/ormah/engine/context_builder.py src/ormah/engine/memory_engine.py tests/test_engine/test_whisper_debug.py
git commit -m "feat: add _return_debug flag to build_whisper_context and get_whisper_context"
```

---

## Task 2: Seeder

**Context:** The eval runner seeds an isolated SQLite DB per corpus case. The seeder clears all existing nodes, then inserts each corpus memory preserving its declared `node_id`. This mirrors the recall eval seeder on `feature/eval-system`.

**Files:**
- Create: `eval/whisper/__init__.py`
- Create: `eval/whisper/seeder.py`
- Create: `tests/test_eval_whisper/__init__.py`
- Create: `tests/test_eval_whisper/test_seeder.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_whisper/__init__.py` (empty).

Create `tests/test_eval_whisper/test_seeder.py`:

```python
"""Tests for eval/whisper/seeder.py."""
from __future__ import annotations
import pytest


@pytest.fixture
def tmp_engine(tmp_path):
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine
    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    yield engine
    engine.shutdown()


_CASE = {
    "id": "t-001",
    "memories": [
        {
            "node_id": "mem-aaa",
            "title": "Port fact",
            "content": "Server runs on port 8787.",
            "type": "fact",
            "tier": "working",
            "space": "ormah",
        },
        {
            "node_id": "mem-bbb",
            "title": "User preference",
            "content": "User prefers dark themes.",
            "type": "preference",
            "tier": "core",
            "space": None,
        },
    ],
}


class TestSeedCase:
    def test_creates_node_files(self, tmp_engine):
        from eval.whisper.seeder import seed_case
        seed_case(tmp_engine, _CASE)
        nodes_dir = tmp_engine.file_store.nodes_dir
        files = list(nodes_dir.glob("*.md"))
        assert len(files) == 2

    def test_preserves_node_ids(self, tmp_engine):
        from eval.whisper.seeder import seed_case
        seed_case(tmp_engine, _CASE)
        node = tmp_engine.file_store.load("mem-aaa")
        assert node is not None
        assert node.title == "Port fact"

    def test_clear_removes_previous_nodes(self, tmp_engine):
        from eval.whisper.seeder import seed_case, clear_eval_db
        seed_case(tmp_engine, _CASE)
        clear_eval_db(tmp_engine)
        nodes_dir = tmp_engine.file_store.nodes_dir
        files = list(nodes_dir.glob("*.md"))
        assert len(files) == 0

    def test_seed_replaces_prior_case(self, tmp_engine):
        from eval.whisper.seeder import seed_case
        seed_case(tmp_engine, _CASE)
        new_case = {
            "id": "t-002",
            "memories": [
                {"node_id": "mem-ccc", "title": "New", "content": "New content.", "type": "fact", "tier": "working"},
            ],
        }
        seed_case(tmp_engine, new_case)
        nodes_dir = tmp_engine.file_store.nodes_dir
        files = list(nodes_dir.glob("*.md"))
        assert len(files) == 1
        assert tmp_engine.file_store.load("mem-aaa") is None
        assert tmp_engine.file_store.load("mem-ccc") is not None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_eval_whisper/test_seeder.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'eval'`

- [ ] **Step 3: Create `eval/whisper/__init__.py`**

```bash
mkdir -p eval/whisper/corpus/golden
touch eval/__init__.py eval/whisper/__init__.py
```

- [ ] **Step 4: Create `eval/whisper/seeder.py`**

```python
"""Seed the isolated whisper eval DB with memories from a corpus case."""
from __future__ import annotations

from ormah.models.node import MemoryNode, NodeType, Tier


def seed_case(engine, case: dict) -> None:
    """Clear eval DB and seed with memories from *case*.

    Memories are inserted with their corpus node_id preserved.
    Skips auto-linking and core-cap enforcement.
    """
    clear_eval_db(engine)
    for mem in case.get("memories", []):
        node = MemoryNode(
            id=mem["node_id"],
            type=NodeType(mem.get("type", "fact")),
            tier=Tier(mem.get("tier", "working")),
            title=mem.get("title"),
            content=mem.get("content", ""),
            space=mem.get("space"),
            tags=mem.get("tags", []),
            source="eval:corpus",
            confidence=float(mem.get("confidence", 1.0)),
        )
        path = engine.file_store.save(node)
        engine.builder.index_single(path)
        engine._index_embedding(node)


def clear_eval_db(engine) -> None:
    """Remove all nodes from the eval DB and file store."""
    nodes_dir = engine.file_store.nodes_dir
    for md_file in nodes_dir.glob("*.md"):
        md_file.unlink()
    engine.file_store._id_cache.clear()
    engine.file_store._cache_built = False
    engine.builder.full_rebuild()
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval_whisper/test_seeder.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add eval/ tests/test_eval_whisper/
git commit -m "feat(eval): whisper seeder — seed isolated eval DB per corpus case"
```

---

## Task 3: Corpus Loader

**Files:**
- Create: `eval/whisper/corpus.py`
- Test: `tests/test_eval_whisper/test_corpus.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_whisper/test_corpus.py`:

```python
"""Tests for eval/whisper/corpus.py."""
from __future__ import annotations
import json
import pytest
from pathlib import Path
from eval.whisper.corpus import load_corpus, validate_case, CorpusError, VALID_CATEGORIES


def _write_jsonl(tmp_path, cases):
    f = tmp_path / "test.jsonl"
    f.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
    return f


_MEM = {"node_id": "m-1", "title": "T", "content": "C", "type": "fact", "tier": "working"}
_PROMPT = {"text": "q", "category": "factual", "expected": {"should_inject": ["m-1"], "should_suppress": False}}
_VALID = {"id": "w-001", "memories": [_MEM], "prompts": [_PROMPT]}


class TestLoadCorpus:
    def test_loads_cases(self, tmp_path):
        f = _write_jsonl(tmp_path, [_VALID])
        cases = load_corpus(f)
        assert len(cases) == 1
        assert cases[0]["id"] == "w-001"

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "t.jsonl"
        f.write_text(json.dumps(_VALID) + "\n\n" + json.dumps(_VALID) + "\n")
        assert len(load_corpus(f)) == 2

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(CorpusError, match="not found"):
            load_corpus(tmp_path / "missing.jsonl")


class TestValidateCase:
    def test_valid_case_passes(self):
        validate_case(_VALID)  # no exception

    def test_missing_node_id_raises(self):
        bad = {"id": "x", "memories": [{"title": "T"}], "prompts": []}
        with pytest.raises(CorpusError, match="missing 'node_id'"):
            validate_case(bad)

    def test_duplicate_node_id_raises(self):
        bad = {
            "id": "x",
            "memories": [
                {"node_id": "dup", "title": "A", "content": "C", "type": "fact", "tier": "working"},
                {"node_id": "dup", "title": "B", "content": "C", "type": "fact", "tier": "working"},
            ],
            "prompts": [],
        }
        with pytest.raises(CorpusError, match="duplicate node_id"):
            validate_case(bad)

    def test_invalid_category_raises(self):
        bad = {
            "id": "x",
            "memories": [_MEM],
            "prompts": [{"text": "q", "category": "bogus", "expected": {}}],
        }
        with pytest.raises(CorpusError, match="invalid category"):
            validate_case(bad)

    def test_unknown_node_ref_in_should_inject_raises(self):
        bad = {
            "id": "x",
            "memories": [_MEM],
            "prompts": [{"text": "q", "category": "factual", "expected": {"should_inject": ["unknown-id"]}}],
        }
        with pytest.raises(CorpusError, match="unknown node_id"):
            validate_case(bad)

    def test_all_valid_categories_accepted(self):
        for cat in VALID_CATEGORIES:
            case = {
                "id": "x", "memories": [_MEM],
                "prompts": [{"text": "q", "category": cat, "expected": {"should_inject": ["m-1"]}}],
            }
            validate_case(case)  # no exception
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_eval_whisper/test_corpus.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'eval.whisper.corpus'`

- [ ] **Step 3: Create `eval/whisper/corpus.py`**

```python
"""Load and validate whisper eval corpus files (JSONL format)."""
from __future__ import annotations

import json
from pathlib import Path

VALID_CATEGORIES = frozenset({
    "preference", "factual", "decision", "technical",
    "identity", "temporal", "noise", "continuation",
})


class CorpusError(Exception):
    """Raised on corpus file or validation errors."""


def load_corpus(path: Path) -> list[dict]:
    """Load a JSONL corpus file. Skips blank lines. Validates each case."""
    if not path.exists():
        raise CorpusError(f"Corpus file not found: {path}")
    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        validate_case(obj)
        cases.append(obj)
    return cases


def validate_case(case: dict) -> None:
    """Validate a single corpus case. Raises CorpusError on structural issues."""
    case_id = case.get("id", "<unknown>")
    seen_ids: set[str] = set()

    for i, mem in enumerate(case.get("memories", [])):
        node_id = mem.get("node_id")
        if not node_id:
            raise CorpusError(f"Case '{case_id}' memory[{i}] missing 'node_id' field")
        if node_id in seen_ids:
            raise CorpusError(f"Case '{case_id}' has duplicate node_id: '{node_id}'")
        seen_ids.add(node_id)

    for i, prompt in enumerate(case.get("prompts", [])):
        category = prompt.get("category")
        if category and category not in VALID_CATEGORIES:
            raise CorpusError(
                f"Case '{case_id}' prompt[{i}] has invalid category '{category}'. "
                f"Valid: {sorted(VALID_CATEGORIES)}"
            )
        expected = prompt.get("expected", {})
        for label_field in ("should_inject", "should_not_inject"):
            for nid in expected.get(label_field, []):
                if nid not in seen_ids:
                    raise CorpusError(
                        f"Case '{case_id}' prompt[{i}] references unknown node_id "
                        f"'{nid}' in '{label_field}'"
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval_whisper/test_corpus.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/whisper/corpus.py tests/test_eval_whisper/test_corpus.py
git commit -m "feat(eval): whisper corpus loader — load and validate JSONL cases"
```

---

## Task 4: Metrics

**Files:**
- Create: `eval/whisper/metrics.py`
- Test: `tests/test_eval_whisper/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_whisper/test_metrics.py`:

```python
"""Tests for eval/whisper/metrics.py."""
from __future__ import annotations
import pytest
from eval.whisper.metrics import (
    injection_recall, injection_precision, f1_score,
    top2_recall, has_false_positive, suppression_correct,
    compute_prompt_metrics,
)


class TestInjectionRecall:
    def test_all_found(self):
        assert injection_recall(["a", "b"], ["b", "a", "c"]) == 1.0

    def test_partial(self):
        assert injection_recall(["a", "b"], ["a", "c"]) == 0.5

    def test_none_found(self):
        assert injection_recall(["a", "b"], ["c", "d"]) == 0.0

    def test_empty_should_inject_returns_none(self):
        assert injection_recall([], ["a", "b"]) is None

    def test_empty_injected(self):
        assert injection_recall(["a"], []) == 0.0


class TestInjectionPrecision:
    def test_all_relevant(self):
        assert injection_precision(["a", "b"], ["a", "b"]) == 1.0

    def test_partial_relevant(self):
        assert injection_precision(["a"], ["a", "b", "c"]) == pytest.approx(1 / 3)

    def test_empty_should_inject_returns_none(self):
        assert injection_precision([], ["a"]) is None

    def test_empty_injected_returns_zero(self):
        assert injection_precision(["a"], []) == 0.0


class TestF1Score:
    def test_perfect(self):
        assert f1_score(1.0, 1.0) == 1.0

    def test_zero_both(self):
        assert f1_score(0.0, 0.0) == 0.0

    def test_none_propagates(self):
        assert f1_score(None, 0.5) is None
        assert f1_score(0.5, None) is None


class TestTop2Recall:
    def test_in_top2(self):
        assert top2_recall(["a"], ["a", "b", "c"]) == 1.0

    def test_not_in_top2(self):
        assert top2_recall(["c"], ["a", "b", "c"]) == 0.0

    def test_empty_should_inject_returns_none(self):
        assert top2_recall([], ["a"]) is None

    def test_second_position(self):
        assert top2_recall(["b"], ["a", "b", "c"]) == 1.0

    def test_third_position_not_counted(self):
        assert top2_recall(["c"], ["a", "b", "c"]) == 0.0


class TestFalsePositive:
    def test_fp_present(self):
        assert has_false_positive(["x"], ["x", "y"]) is True

    def test_no_fp(self):
        assert has_false_positive(["x"], ["a", "b"]) is False

    def test_empty_should_not_inject(self):
        assert has_false_positive([], ["a"]) is False


class TestSuppressionCorrect:
    def test_correctly_suppressed(self):
        assert suppression_correct(should_suppress=True, injection_fired=False) is True

    def test_incorrectly_not_suppressed(self):
        assert suppression_correct(should_suppress=True, injection_fired=True) is False

    def test_non_noise_returns_none(self):
        assert suppression_correct(should_suppress=False, injection_fired=True) is None
        assert suppression_correct(should_suppress=False, injection_fired=False) is None


class TestComputePromptMetrics:
    def test_perfect_result(self):
        m = compute_prompt_metrics(
            should_inject=["a"],
            should_not_inject=["b"],
            should_suppress=False,
            injected_ids=["a"],
            injection_fired=True,
        )
        assert m["injection_recall"] == 1.0
        assert m["injection_precision"] == 1.0
        assert m["f1"] == 1.0
        assert m["top2_recall"] == 1.0
        assert m["false_positive_present"] is False
        assert m["suppression_correct"] is None
        assert m["injection_fired"] is True

    def test_noise_case_suppressed(self):
        m = compute_prompt_metrics(
            should_inject=[],
            should_not_inject=[],
            should_suppress=True,
            injected_ids=[],
            injection_fired=False,
        )
        assert m["suppression_correct"] is True
        assert m["injection_recall"] is None

    def test_noise_case_not_suppressed(self):
        m = compute_prompt_metrics(
            should_inject=[],
            should_not_inject=[],
            should_suppress=True,
            injected_ids=["a"],
            injection_fired=True,
        )
        assert m["suppression_correct"] is False
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_eval_whisper/test_metrics.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'eval.whisper.metrics'`

- [ ] **Step 3: Create `eval/whisper/metrics.py`**

```python
"""Metrics for whisper eval: injection recall, precision, f1, top2_recall, suppression."""
from __future__ import annotations
from typing import Optional


def injection_recall(should_inject: list[str], injected_ids: list[str]) -> Optional[float]:
    """Fraction of should_inject nodes that appeared in injected output."""
    if not should_inject:
        return None
    injected_set = set(injected_ids)
    return sum(1 for nid in should_inject if nid in injected_set) / len(should_inject)


def injection_precision(should_inject: list[str], injected_ids: list[str]) -> Optional[float]:
    """Fraction of injected nodes that were in should_inject."""
    if not should_inject:
        return None
    if not injected_ids:
        return 0.0
    relevant = set(should_inject)
    return sum(1 for nid in injected_ids if nid in relevant) / len(injected_ids)


def f1_score(recall: Optional[float], precision: Optional[float]) -> Optional[float]:
    if recall is None or precision is None:
        return None
    if recall + precision == 0:
        return 0.0
    return 2 * recall * precision / (recall + precision)


def top2_recall(should_inject: list[str], injected_ids: list[str]) -> Optional[float]:
    """Fraction of should_inject nodes in top-2 injected positions (shown in full)."""
    if not should_inject:
        return None
    top2 = set(injected_ids[:2])
    return sum(1 for nid in should_inject if nid in top2) / len(should_inject)


def has_false_positive(should_not_inject: list[str], injected_ids: list[str]) -> bool:
    """True if any should_not_inject node appeared in injected output."""
    injected_set = set(injected_ids)
    return any(nid in injected_set for nid in should_not_inject)


def suppression_correct(should_suppress: bool, injection_fired: bool) -> Optional[bool]:
    """For noise cases: True if pipeline correctly stayed silent. None for non-noise."""
    if not should_suppress:
        return None
    return not injection_fired


def compute_prompt_metrics(
    should_inject: list[str],
    should_not_inject: list[str],
    should_suppress: bool,
    injected_ids: list[str],
    injection_fired: bool,
) -> dict:
    rec = injection_recall(should_inject, injected_ids)
    prec = injection_precision(should_inject, injected_ids)
    return {
        "injection_recall": rec,
        "injection_precision": prec,
        "f1": f1_score(rec, prec),
        "top2_recall": top2_recall(should_inject, injected_ids),
        "suppression_correct": suppression_correct(should_suppress, injection_fired),
        "false_positive_present": has_false_positive(should_not_inject, injected_ids),
        "injection_fired": injection_fired,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval_whisper/test_metrics.py -v
```

Expected: `20 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/whisper/metrics.py tests/test_eval_whisper/test_metrics.py
git commit -m "feat(eval): whisper metrics — injection recall, precision, f1, top2_recall, suppression"
```

---

## Task 5: Runner

**Files:**
- Create: `eval/whisper/runner.py`
- Test: `tests/test_eval_whisper/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_whisper/test_runner.py`:

```python
"""Tests for eval/whisper/runner.py."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from eval.whisper.runner import run_whisper_eval, _aggregate, _aggregate_by_category


_CASES = [
    {
        "id": "w-fact-001",
        "space": "ormah",
        "memories": [
            {"node_id": "mem-001", "title": "Port fact", "content": "Runs on 8787.", "type": "fact", "tier": "working"},
            {"node_id": "mem-002", "title": "Distractor", "content": "Unrelated.", "type": "fact", "tier": "working"},
        ],
        "prompts": [
            {
                "text": "what port does ormah run on",
                "category": "factual",
                "expected": {
                    "should_inject": ["mem-001"],
                    "should_not_inject": ["mem-002"],
                    "should_suppress": False,
                },
            }
        ],
    },
    {
        "id": "w-noise-001",
        "space": "ormah",
        "memories": [
            {"node_id": "mem-003", "title": "Some fact", "content": "Content.", "type": "fact", "tier": "working"},
        ],
        "prompts": [
            {
                "text": "hello",
                "category": "noise",
                "expected": {"should_inject": [], "should_not_inject": [], "should_suppress": True},
            }
        ],
    },
]


class TestRunWhisperEval:
    def test_returns_result_per_prompt(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.side_effect = [
            ("whisper text", ["mem-001"]),  # factual case: hit
            ("", []),                        # noise case: suppressed
        ]
        with patch("eval.whisper.runner.seed_case"):
            result = run_whisper_eval(_CASES, mock_engine)
        assert len(result.prompt_results) == 2

    def test_factual_hit_metrics(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.side_effect = [
            ("whisper text", ["mem-001"]),
            ("", []),
        ]
        with patch("eval.whisper.runner.seed_case"):
            result = run_whisper_eval(_CASES, mock_engine)
        factual = next(r for r in result.prompt_results if r.category == "factual")
        assert factual.metrics["injection_recall"] == 1.0
        assert factual.metrics["false_positive_present"] is False

    def test_noise_suppression_metrics(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.side_effect = [
            ("whisper text", ["mem-001"]),
            ("", []),
        ]
        with patch("eval.whisper.runner.seed_case"):
            result = run_whisper_eval(_CASES, mock_engine)
        noise = next(r for r in result.prompt_results if r.category == "noise")
        assert noise.metrics["suppression_correct"] is True

    def test_engine_called_with_correct_args(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.return_value = ("", [])
        with patch("eval.whisper.runner.seed_case"):
            run_whisper_eval([_CASES[0]], mock_engine)
        call_kwargs = mock_engine.get_whisper_context.call_args
        assert call_kwargs.kwargs["recent_prompts"] == []
        assert call_kwargs.kwargs["session_id"] is None
        assert call_kwargs.kwargs["_return_debug"] is True
        assert call_kwargs.kwargs["space"] == "ormah"

    def test_seed_called_once_per_case(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.return_value = ("", [])
        with patch("eval.whisper.runner.seed_case") as mock_seed:
            run_whisper_eval(_CASES, mock_engine)
        assert mock_seed.call_count == 2

    def test_category_aggregates_split_by_category(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.side_effect = [
            ("text", ["mem-001"]),
            ("", []),
        ]
        with patch("eval.whisper.runner.seed_case"):
            result = run_whisper_eval(_CASES, mock_engine)
        assert "factual" in result.category_aggregates
        assert "noise" in result.category_aggregates


class TestAggregate:
    def _make_result(self, category, recall, suppression_correct=None):
        from eval.whisper.runner import PromptResult
        metrics = {
            "injection_recall": recall,
            "injection_precision": recall,
            "f1": recall,
            "top2_recall": recall,
            "suppression_correct": suppression_correct,
            "false_positive_present": False,
            "injection_fired": recall is not None and recall > 0,
        }
        return PromptResult(
            case_id="x", prompt="q", category=category,
            should_inject=[], injected_ids=[], metrics=metrics,
        )

    def test_mean_recall_across_prompts(self):
        results = [self._make_result("factual", 1.0), self._make_result("factual", 0.5)]
        agg = _aggregate(results)
        assert agg["injection_recall"] == pytest.approx(0.75)

    def test_suppression_accuracy(self):
        results = [
            self._make_result("noise", None, suppression_correct=True),
            self._make_result("noise", None, suppression_correct=False),
        ]
        agg = _aggregate(results)
        assert agg["suppression_accuracy"] == pytest.approx(0.5)

    def test_no_labeled_non_noise_returns_none_for_recall(self):
        results = [self._make_result("noise", None, suppression_correct=True)]
        agg = _aggregate(results)
        assert agg["injection_recall"] is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_eval_whisper/test_runner.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'eval.whisper.runner'`

- [ ] **Step 3: Create `eval/whisper/runner.py`**

```python
"""Whisper eval runner — seeds DB, calls full pipeline, collects metrics per prompt."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from eval.whisper.metrics import compute_prompt_metrics
from eval.whisper.seeder import seed_case


@dataclass
class PromptResult:
    case_id: str
    prompt: str
    category: str
    should_inject: list[str]
    injected_ids: list[str]
    metrics: dict


@dataclass
class WhisperEvalResult:
    prompt_results: list[PromptResult] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    category_aggregates: dict = field(default_factory=dict)


def run_whisper_eval(cases: list[dict], engine) -> WhisperEvalResult:
    """Run the whisper eval pipeline over *cases*."""
    prompt_results: list[PromptResult] = []

    for case in cases:
        seed_case(engine, case)
        space = case.get("space")

        for prompt_obj in case.get("prompts", []):
            text = prompt_obj["text"]
            category = prompt_obj.get("category", "general")
            expected = prompt_obj.get("expected", {})
            should_inject = expected.get("should_inject", [])
            should_not_inject = expected.get("should_not_inject", [])
            should_suppress = expected.get("should_suppress", False)

            whisper_text, injected_ids = engine.get_whisper_context(
                prompt=text,
                space=space,
                recent_prompts=[],
                session_id=None,
                _return_debug=True,
            )

            metrics = compute_prompt_metrics(
                should_inject=should_inject,
                should_not_inject=should_not_inject,
                should_suppress=should_suppress,
                injected_ids=injected_ids,
                injection_fired=bool(whisper_text.strip()),
            )

            prompt_results.append(PromptResult(
                case_id=case["id"],
                prompt=text,
                category=category,
                should_inject=should_inject,
                injected_ids=injected_ids,
                metrics=metrics,
            ))

    aggregate = _aggregate(prompt_results)
    by_cat = defaultdict(list)
    for r in prompt_results:
        by_cat[r.category].append(r)
    category_aggregates = {cat: _aggregate(results) for cat, results in by_cat.items()}

    return WhisperEvalResult(
        prompt_results=prompt_results,
        aggregate=aggregate,
        category_aggregates=category_aggregates,
    )


def _aggregate(prompt_results: list[PromptResult]) -> dict:
    """Aggregate metrics across prompt results. Noise and non-noise are separated."""
    non_noise = [r for r in prompt_results if r.metrics["suppression_correct"] is None]
    noise = [r for r in prompt_results if r.metrics["suppression_correct"] is not None]

    def _avg(key: str, results: list[PromptResult]) -> Optional[float]:
        vals = [r.metrics[key] for r in results if r.metrics.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    result: dict = {
        "total_prompts": len(prompt_results),
        "injection_recall": _avg("injection_recall", non_noise),
        "injection_precision": _avg("injection_precision", non_noise),
        "f1": _avg("f1", non_noise),
        "top2_recall": _avg("top2_recall", non_noise),
        "false_positive_rate": (
            sum(1 for r in prompt_results if r.metrics["false_positive_present"]) / len(prompt_results)
            if prompt_results else None
        ),
    }

    if noise:
        correct = sum(1 for r in noise if r.metrics["suppression_correct"])
        result["suppression_accuracy"] = correct / len(noise)
        result["suppression_correct_count"] = correct
        result["suppression_count"] = len(noise)

    return result


def _aggregate_by_category(prompt_results: list[PromptResult]) -> dict:
    by_cat: dict[str, list[PromptResult]] = defaultdict(list)
    for r in prompt_results:
        by_cat[r.category].append(r)
    return {cat: _aggregate(results) for cat, results in by_cat.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval_whisper/test_runner.py -v
```

Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/whisper/runner.py tests/test_eval_whisper/test_runner.py
git commit -m "feat(eval): whisper runner — orchestrate seeding, pipeline calls, metric collection"
```

---

## Task 6: Report

**Files:**
- Create: `eval/whisper/report.py`
- Test: `tests/test_eval_whisper/test_report.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_whisper/test_report.py`:

```python
"""Tests for eval/whisper/report.py."""
from __future__ import annotations
from eval.whisper.runner import PromptResult, WhisperEvalResult
from eval.whisper.report import format_report


def _make_result(category, recall, suppression_correct=None, fp=False,
                 case_id="c-1", prompt="q", should_inject=None, injected_ids=None):
    prec = recall
    metrics = {
        "injection_recall": recall,
        "injection_precision": prec,
        "f1": recall,
        "top2_recall": recall,
        "suppression_correct": suppression_correct,
        "false_positive_present": fp,
        "injection_fired": bool(recall),
    }
    return PromptResult(
        case_id=case_id, prompt=prompt, category=category,
        should_inject=should_inject or [],
        injected_ids=injected_ids or [],
        metrics=metrics,
    )


def _make_eval_result(prompt_results):
    from eval.whisper.runner import _aggregate
    from collections import defaultdict
    by_cat = defaultdict(list)
    for r in prompt_results:
        by_cat[r.category].append(r)
    return WhisperEvalResult(
        prompt_results=prompt_results,
        aggregate=_aggregate(prompt_results),
        category_aggregates={cat: _aggregate(rs) for cat, rs in by_cat.items()},
    )


class TestFormatReport:
    def test_report_contains_overall(self):
        result = _make_eval_result([_make_result("factual", 0.8)])
        report = format_report(result)
        assert "OVERALL" in report

    def test_report_contains_category_name(self):
        result = _make_eval_result([_make_result("preference", 0.67)])
        report = format_report(result)
        assert "preference" in report

    def test_report_contains_noise_suppression_accuracy(self):
        result = _make_eval_result([
            _make_result("noise", None, suppression_correct=True),
            _make_result("noise", None, suppression_correct=False),
        ])
        report = format_report(result)
        assert "suppression" in report.lower()
        assert "0.50" in report or "50%" in report

    def test_failures_shown_when_flag_set(self):
        result = _make_eval_result([
            _make_result(
                "factual", 0.0,
                case_id="w-fact-001", prompt="what port",
                should_inject=["mem-001"], injected_ids=[],
            )
        ])
        report = format_report(result, show_failures=True)
        assert "w-fact-001" in report
        assert "what port" in report

    def test_failures_hidden_by_default(self):
        result = _make_eval_result([
            _make_result("factual", 0.0, case_id="w-fail-001", prompt="failing prompt")
        ])
        report = format_report(result, show_failures=False)
        assert "failing prompt" not in report

    def test_prompt_count_in_header(self):
        results = [_make_result("factual", 1.0) for _ in range(5)]
        result = _make_eval_result(results)
        report = format_report(result)
        assert "5" in report
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_eval_whisper/test_report.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'eval.whisper.report'`

- [ ] **Step 3: Create `eval/whisper/report.py`**

```python
"""Format whisper eval results as a human-readable table."""
from __future__ import annotations

from eval.whisper.runner import WhisperEvalResult

_CATEGORY_ORDER = [
    "preference", "factual", "decision", "technical",
    "identity", "temporal", "continuation", "noise",
]


def _fmt(val, width=6) -> str:
    if val is None:
        return " " * width
    return f"{val:.2f}".rjust(width)


def format_report(result: WhisperEvalResult, show_failures: bool = False) -> str:
    lines = []
    total = result.aggregate.get("total_prompts", 0)
    n_cats = len(result.category_aggregates)
    lines.append(f"Whisper Eval  ({total} prompts, {n_cats} categories)")
    lines.append("═" * 72)
    lines.append(f"{'':20s}  {'recall':>7}  {'prec':>7}  {'f1':>7}  {'top2':>7}  {'fp_rate':>7}")

    for cat in _CATEGORY_ORDER:
        agg = result.category_aggregates.get(cat)
        if agg is None:
            continue
        count = agg.get("total_prompts", 0)
        label = f"{cat} ({count})"

        if cat == "noise":
            acc = agg.get("suppression_accuracy")
            correct = agg.get("suppression_correct_count", 0)
            total_noise = agg.get("suppression_count", 0)
            lines.append("─" * 72)
            lines.append(
                f"{'noise':20s}  suppression_accuracy: {_fmt(acc).strip()}"
                f"  ({correct}/{total_noise} correctly silent)"
            )
            lines.append("─" * 72)
        else:
            lines.append(
                f"{label:20s}"
                f"  {_fmt(agg.get('injection_recall'))}"
                f"  {_fmt(agg.get('injection_precision'))}"
                f"  {_fmt(agg.get('f1'))}"
                f"  {_fmt(agg.get('top2_recall'))}"
                f"  {_fmt(agg.get('false_positive_rate'))}"
            )

    agg = result.aggregate
    lines.append("═" * 72)
    lines.append(
        f"{'OVERALL':20s}"
        f"  {_fmt(agg.get('injection_recall'))}"
        f"  {_fmt(agg.get('injection_precision'))}"
        f"  {_fmt(agg.get('f1'))}"
        f"  {_fmt(agg.get('top2_recall'))}"
        f"  {_fmt(agg.get('false_positive_rate'))}"
    )

    if show_failures:
        failures = _collect_failures(result)
        if failures:
            lines.append("")
            lines.append(f"FAILURES ({len(failures)}):")
            for f in failures:
                lines.append(f"  {f['case_id']:20s}  [{f['category']}]  \"{f['prompt']}\"")
                expected_str = str(f['should_inject']) if f['should_inject'] else "(suppress)"
                got_str = str(f['injected_ids']) if f['injected_ids'] else "[]"
                lines.append(f"    expected: {expected_str}  injected: {got_str}")

    return "\n".join(lines)


def _collect_failures(result: WhisperEvalResult) -> list[dict]:
    failures = []
    for r in result.prompt_results:
        m = r.metrics
        is_failure = (
            (m["injection_recall"] is not None and m["injection_recall"] < 1.0)
            or m["false_positive_present"]
            or m["suppression_correct"] is False
        )
        if is_failure:
            failures.append({
                "case_id": r.case_id,
                "category": r.category,
                "prompt": r.prompt,
                "should_inject": r.should_inject,
                "injected_ids": r.injected_ids,
            })
    return failures
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval_whisper/test_report.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/whisper/report.py tests/test_eval_whisper/test_report.py
git commit -m "feat(eval): whisper report — per-category table with suppression row and failures"
```

---

## Task 7: CLI

**Files:**
- Create: `eval/whisper/cli.py`
- Modify: `src/ormah/cli.py`
- Test: `tests/test_eval_whisper/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_whisper/test_cli.py`:

```python
"""Tests for eval whisper CLI wiring."""
from __future__ import annotations
import subprocess
import sys


class TestEvalWhisperCLI:
    def test_eval_whisper_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "ormah.cli_entry", "eval", "whisper", "run", "--help"],
            capture_output=True, text=True,
        )
        # Should print help, not traceback
        assert result.returncode == 0
        assert "--category" in result.stdout or "--help" in result.stdout

    def test_ormah_eval_whisper_help(self):
        result = subprocess.run(
            ["uv", "run", "ormah", "eval", "whisper", "run", "--help"],
            capture_output=True, text=True,
            cwd="/home/r2205/Projects/ormah/.worktrees/whisper-eval",
        )
        assert result.returncode == 0
```

Note: the CLI test runs after reinstalling. If a simpler import-based test is preferred, use:

```python
    def test_cmd_eval_whisper_run_importable(self):
        from eval.whisper.cli import cmd_eval_whisper_run
        assert callable(cmd_eval_whisper_run)
```

- [ ] **Step 2: Create `eval/whisper/cli.py`**

```python
"""CLI handler for `ormah eval whisper run`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_EVAL_DIR = Path(__file__).parent
_CORPUS_DIR = _EVAL_DIR / "corpus"
_EVAL_DB_DIR = _EVAL_DIR / "eval_db"


def _make_engine():
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (_EVAL_DB_DIR / "nodes").mkdir(parents=True, exist_ok=True)
    settings = Settings(memory_dir=_EVAL_DB_DIR)
    engine = MemoryEngine(settings)
    engine.startup()
    return engine


def cmd_eval_whisper_run(args):
    from eval.whisper.corpus import load_corpus, CorpusError
    from eval.whisper.runner import run_whisper_eval
    from eval.whisper.report import format_report

    corpus_path = _CORPUS_DIR / "golden" / "golden.jsonl"
    try:
        cases = load_corpus(corpus_path)
    except CorpusError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "category", None):
        filtered = [
            {**c, "prompts": [p for p in c["prompts"] if p.get("category") == args.category]}
            for c in cases
        ]
        cases = [c for c in filtered if c["prompts"]]
        if not cases:
            print(f"No prompts found for category '{args.category}'", file=sys.stderr)
            sys.exit(1)

    engine = _make_engine()
    try:
        result = run_whisper_eval(cases, engine)
    finally:
        engine.shutdown()

    if getattr(args, "json", False):
        print(json.dumps({
            "aggregate": result.aggregate,
            "category_aggregates": result.category_aggregates,
        }, indent=2))
    else:
        show_failures = getattr(args, "show_failures", False)
        print(format_report(result, show_failures=show_failures))
```

- [ ] **Step 3: Wire into `src/ormah/cli.py`**

In `src/ormah/cli.py`, find the import block (line ~135-150) and add:

```python
        cmd_eval_whisper_run,
```

Find `def main():` and locate the whisper subcommand block. After the whisper block, add before `args = p.parse_args()`:

```python
    # eval
    ev = sub.add_parser("eval", help="Run evaluation harnesses")
    ev_sub = ev.add_subparsers(dest="eval_cmd", required=True)

    ev_wh = ev_sub.add_parser("whisper", help="Evaluate whisper pipeline quality")
    ev_wh_sub = ev_wh.add_subparsers(dest="eval_whisper_cmd", required=True)

    ev_wh_run = ev_wh_sub.add_parser("run", help="Run whisper eval against golden corpus")
    ev_wh_run.add_argument("--category", help="Filter by category (e.g. preference, factual)")
    ev_wh_run.add_argument("--show-failures", action="store_true", dest="show_failures",
                           help="Print failure details")
    ev_wh_run.add_argument("--json", action="store_true", help="Output as JSON")
    ev_wh_run.set_defaults(func=cmd_eval_whisper_run)
```

Find the imports section at the top of `main()` (the block that imports all cmd_* functions). Add `cmd_eval_whisper_run` to that import:

```python
    from eval.whisper.cli import cmd_eval_whisper_run
```

The full import block in `main()` (currently at line ~130) should include this new import alongside the others:

```python
def main():
    from ormah.commands import (
        cmd_context,
        cmd_ingest,
        cmd_ingest_session,
        cmd_node,
        cmd_outdated,
        cmd_recall,
        cmd_remember,
        cmd_self,
        cmd_stats,
        cmd_whisper_inject,
        cmd_whisper_store,
        cmd_whisper_setup,
    )
    from eval.whisper.cli import cmd_eval_whisper_run
```

- [ ] **Step 4: Run import test**

```bash
uv run python -c "from eval.whisper.cli import cmd_eval_whisper_run; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_eval_whisper/test_cli.py -v
```

Expected: `1 passed` (import test)

- [ ] **Step 6: Commit**

```bash
git add eval/whisper/cli.py src/ormah/cli.py tests/test_eval_whisper/test_cli.py
git commit -m "feat(eval): wire ormah eval whisper run CLI command"
```

---

## Task 8: Golden Corpus

**Context:** 37 prompts across 8 categories. Each case has an isolated set of memories. The content is modeled on real ormah facts, preferences, and decisions — realistic enough for the embeddings to work.

**Files:**
- Create: `eval/whisper/corpus/golden/golden.jsonl`

- [ ] **Step 1: Create the corpus file**

Create `eval/whisper/corpus/golden/golden.jsonl` with the following content (one JSON object per line):

```jsonl
{"id":"whisper-pref-001","space":"ormah","memories":[{"node_id":"pref-001-dark","title":"User prefers minimal dark-themed UIs with gold accent colour","content":"The user prefers minimal, dark-themed UIs with monospace fonts and warm accent colors (gold/bronze #d4a574). Applies to all front-end work.","type":"preference","tier":"core","tags":["ui","design"],"space":null},{"node_id":"pref-001-port","title":"Ormah FastAPI server runs on port 8787","content":"The FastAPI server runs on port 8787 by default, configurable via ORMAH_PORT.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"let's build a settings page for ormah","category":"preference","expected":{"should_inject":["pref-001-dark"],"should_not_inject":["pref-001-port"],"should_suppress":false},"notes":"Implicit preference — task prompt with no preference keyword should surface UI preference"}]}
{"id":"whisper-pref-002","space":"ormah","memories":[{"node_id":"pref-002-commits","title":"User prefers concise commit messages without long descriptions","content":"Rishi prefers concise, short commit messages. Avoid long-winded descriptions or multi-paragraph commit bodies.","type":"preference","tier":"core","tags":["git","collaboration"],"space":null},{"node_id":"pref-002-arch","title":"Ormah uses SQLite with FTS5 and vector search","content":"The index layer uses SQLite with FTS5 for full-text search and sqlite-vec for vector similarity, fused via Reciprocal Rank Fusion (RRF).","type":"fact","tier":"working","tags":["architecture"],"space":"ormah"}],"prompts":[{"text":"write a commit message for this change","category":"preference","expected":{"should_inject":["pref-002-commits"],"should_not_inject":["pref-002-arch"],"should_suppress":false},"notes":"Implicit preference — 'write a commit message' should surface commit style preference"}]}
{"id":"whisper-pref-003","space":"ormah","memories":[{"node_id":"pref-003-nosum","title":"User dislikes trailing summaries at end of responses","content":"Rishi does not want summaries at the end of responses. He finds them redundant and prefers to read diffs directly.","type":"preference","tier":"core","tags":["collaboration"],"space":null},{"node_id":"pref-003-decay","title":"Working-tier memories decay using FSRS spaced repetition","content":"Working-tier memories decay after ~14 days using FSRS (Free Spaced Repetition Scheduler). The stability field tracks days until ~37% retrievability.","type":"fact","tier":"working","tags":["decay"],"space":"ormah"}],"prompts":[{"text":"explain what you just implemented","category":"preference","expected":{"should_inject":["pref-003-nosum"],"should_not_inject":["pref-003-decay"],"should_suppress":false},"notes":"Implicit preference — explaining/summarising should trigger no-summary preference"}]}
{"id":"whisper-pref-004","space":"ormah","memories":[{"node_id":"pref-004-tdd","title":"User follows TDD — write failing tests before implementation","content":"Rishi follows test-driven development. Always write the failing test first, run it to confirm it fails, then implement. Never skip the red step.","type":"preference","tier":"core","tags":["testing","tdd"],"space":null},{"node_id":"pref-004-port","title":"Ormah default port is 8787","content":"Default port is 8787.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"let's write a test for the new feature","category":"preference","expected":{"should_inject":["pref-004-tdd"],"should_not_inject":["pref-004-port"],"should_suppress":false},"notes":"Implicit preference — writing tests should surface TDD preference"}]}
{"id":"whisper-pref-005","space":"ormah","memories":[{"node_id":"pref-005-simple","title":"User prefers the simplest solution — no premature abstractions","content":"Always prefer the simpler solution. Before introducing a complex mechanism, ask: is there a simpler way? Only add complexity when the simpler approach demonstrably cannot solve the problem.","type":"preference","tier":"core","tags":["architecture","design"],"space":null},{"node_id":"pref-005-mcp","title":"Ormah exposes 6 agent-facing MCP tools","content":"MCP tools: remember, recall, get_self, mark_outdated, run_maintenance, submit_feedback.","type":"fact","tier":"working","tags":["mcp"],"space":"ormah"}],"prompts":[{"text":"how should we design this new feature","category":"preference","expected":{"should_inject":["pref-005-simple"],"should_not_inject":["pref-005-mcp"],"should_suppress":false},"notes":"Design question should surface simplicity preference"}]}
{"id":"whisper-pref-006","space":"ormah","memories":[{"node_id":"pref-006-dark2","title":"User prefers dark theme with monospace fonts for all UI work","content":"Dark theme, monospace fonts. Gold accent #d4a574. This applies to any UI component built in any project.","type":"preference","tier":"core","tags":["ui","design"],"space":null},{"node_id":"pref-006-tier","title":"Ormah core memory cap is 50 nodes","content":"A maximum of 50 nodes can be in the core tier at any time. Overflow is demoted to working.","type":"fact","tier":"working","tags":["tiers"],"space":"ormah"}],"prompts":[{"text":"build a graph visualisation component","category":"preference","expected":{"should_inject":["pref-006-dark2"],"should_not_inject":["pref-006-tier"],"should_suppress":false},"notes":"UI component task — should surface dark theme preference even without UI/design keyword"}]}
{"id":"whisper-fact-001","space":"ormah","memories":[{"node_id":"fact-001-port","title":"Ormah FastAPI server runs on port 8787 by default","content":"The FastAPI server runs on port 8787 by default, configurable via ORMAH_PORT environment variable.","type":"fact","tier":"working","tags":["config","server"],"space":"ormah"},{"node_id":"fact-001-decay","title":"Working-tier memories decay after 14 days","content":"Working-tier memories decay after approximately 14 days via FSRS spaced repetition.","type":"fact","tier":"working","tags":["decay"],"space":"ormah"}],"prompts":[{"text":"what port does ormah run on","category":"factual","expected":{"should_inject":["fact-001-port"],"should_not_inject":["fact-001-decay"],"should_suppress":false},"notes":"Direct fact lookup — exact port number"}]}
{"id":"whisper-fact-002","space":"ormah","memories":[{"node_id":"fact-002-model","title":"Ormah uses BAAI/bge-base-en-v1.5 for embeddings","content":"Default embedding model is BAAI/bge-base-en-v1.5 (768-dimensional). No task prefixes needed. Provider is 'local' using sentence-transformers.","type":"fact","tier":"working","tags":["embeddings","config"],"space":"ormah"},{"node_id":"fact-002-port","title":"Server port default is 8787","content":"Port 8787 is the default.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"what embedding model does ormah use","category":"factual","expected":{"should_inject":["fact-002-model"],"should_not_inject":["fact-002-port"],"should_suppress":false},"notes":"Direct fact lookup — embedding model name"}]}
{"id":"whisper-fact-003","space":"ormah","memories":[{"node_id":"fact-003-timeout","title":"UserPromptSubmit hook has 10-second timeout","content":"The Claude Code UserPromptSubmit hook that runs whisper inject has a 10-second timeout. Whisper must complete within this window or the injection is skipped.","type":"fact","tier":"working","tags":["hooks","whisper"],"space":"ormah"},{"node_id":"fact-003-cap","title":"Core memory tier cap is 50 nodes","content":"Maximum 50 nodes in core tier.","type":"fact","tier":"working","tags":["tiers"],"space":"ormah"}],"prompts":[{"text":"what is the hook timeout","category":"factual","expected":{"should_inject":["fact-003-timeout"],"should_not_inject":["fact-003-cap"],"should_suppress":false},"notes":"Direct fact lookup — timeout value"}]}
{"id":"whisper-fact-004","space":"ormah","memories":[{"node_id":"fact-004-cap","title":"Ormah core tier cap is 50 nodes maximum","content":"A maximum of 50 nodes can be in the core tier at any time. When a new core memory would exceed this, the lowest-importance core node is demoted to working tier.","type":"fact","tier":"working","tags":["tiers","architecture"],"space":"ormah"},{"node_id":"fact-004-port","title":"Port 8787","content":"Default port is 8787.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"how many core memories can ormah hold","category":"factual","expected":{"should_inject":["fact-004-cap"],"should_not_inject":["fact-004-port"],"should_suppress":false},"notes":"Direct fact lookup — core tier capacity"}]}
{"id":"whisper-fact-005","space":"ormah","memories":[{"node_id":"fact-005-min","title":"Whisper minimum relevance score threshold is 0.45","content":"The whisper pipeline drops search results with score below 0.45 (configurable via whisper_min_relevance_score). Temporal queries use a relaxed threshold of 0.30.","type":"fact","tier":"working","tags":["whisper","config"],"space":"ormah"},{"node_id":"fact-005-model","title":"Embedding model is bge-base-en-v1.5","content":"768-dim embeddings via bge-base-en-v1.5.","type":"fact","tier":"working","tags":["embeddings"],"space":"ormah"}],"prompts":[{"text":"what is the whisper min relevance score","category":"factual","expected":{"should_inject":["fact-005-min"],"should_not_inject":["fact-005-model"],"should_suppress":false},"notes":"Direct fact lookup — threshold value"}]}
{"id":"whisper-fact-006","space":"ormah","memories":[{"node_id":"fact-006-db","title":"Ormah uses SQLite with FTS5 for full-text and sqlite-vec for vector search","content":"The index layer uses SQLite with FTS5 for full-text search and sqlite-vec for vector similarity. Results are fused using Reciprocal Rank Fusion (RRF). Weights are configurable via ORMAH_FTS_WEIGHT and ORMAH_VECTOR_WEIGHT.","type":"fact","tier":"working","tags":["architecture","search","database"],"space":"ormah"},{"node_id":"fact-006-cap","title":"Core tier cap 50","content":"Max 50 core nodes.","type":"fact","tier":"working","tags":["tiers"],"space":"ormah"}],"prompts":[{"text":"what database does ormah use","category":"factual","expected":{"should_inject":["fact-006-db"],"should_not_inject":["fact-006-cap"],"should_suppress":false},"notes":"Direct fact lookup — database technology"}]}
{"id":"whisper-dec-001","space":"ormah","memories":[{"node_id":"dec-001-sync","title":"Decision: keep whisper pipeline synchronous, not async","content":"We decided to keep the whisper inject pipeline synchronous to ensure memories are injected before the prompt reaches Claude. Making it async would risk a race condition where the hook exits before injection completes.","type":"decision","tier":"working","tags":["whisper","architecture","decision"],"space":"ormah"},{"node_id":"dec-001-port","title":"Default port 8787","content":"Port 8787.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"why is whisper synchronous instead of async","category":"decision","expected":{"should_inject":["dec-001-sync"],"should_not_inject":["dec-001-port"],"should_suppress":false},"notes":"Decision + rationale — why question should surface the decision memory with reasoning"}]}
{"id":"whisper-dec-002","space":"ormah","memories":[{"node_id":"dec-002-embed","title":"Decision: use BAAI/bge-base-en-v1.5 — no task prefixes needed","content":"Chose bge-base-en-v1.5 over nomic-embed-text because it requires no task prefixes, making it simpler to use in production. Also produces 768-dim vectors compatible with sqlite-vec.","type":"decision","tier":"working","tags":["embeddings","decision"],"space":"ormah"},{"node_id":"dec-002-tier","title":"Three memory tiers: core, working, archival","content":"Ormah has three memory tiers. Core is always loaded (cap 50). Working decays after ~14 days. Archival is for historical reference.","type":"fact","tier":"working","tags":["tiers"],"space":"ormah"}],"prompts":[{"text":"why did we choose this embedding model","category":"decision","expected":{"should_inject":["dec-002-embed"],"should_not_inject":["dec-002-tier"],"should_suppress":false},"notes":"Decision recall — 'why did we choose' phrasing should surface decision with reason"}]}
{"id":"whisper-dec-003","space":"ormah","memories":[{"node_id":"dec-003-rrf","title":"Decision: use RRF to fuse FTS and vector search results","content":"Chose Reciprocal Rank Fusion to combine full-text search and vector similarity results. RRF is rank-based so it handles score scale differences naturally. Formula: 1/(k+rank) with k=60.","type":"decision","tier":"working","tags":["search","decision"],"space":"ormah"},{"node_id":"dec-003-model","title":"bge-base-en-v1.5 embedding model","content":"768-dim, no task prefixes.","type":"fact","tier":"working","tags":["embeddings"],"space":"ormah"}],"prompts":[{"text":"why do we use RRF for combining search results","category":"decision","expected":{"should_inject":["dec-003-rrf"],"should_not_inject":["dec-003-model"],"should_suppress":false},"notes":"Decision + rationale for architectural choice"}]}
{"id":"whisper-dec-004","space":"ormah","memories":[{"node_id":"dec-004-sqlite","title":"Decision: SQLite over Postgres — local-first, zero infrastructure","content":"Chose SQLite over Postgres because ormah is a local-first tool. No server to manage, no network dependency, ships as a single file. Users install with pip and it just works.","type":"decision","tier":"working","tags":["database","decision","architecture"],"space":"ormah"},{"node_id":"dec-004-cap","title":"Core tier cap 50 nodes","content":"Max 50 core nodes.","type":"fact","tier":"working","tags":["tiers"],"space":"ormah"}],"prompts":[{"text":"why did we choose SQLite over a proper database","category":"decision","expected":{"should_inject":["dec-004-sqlite"],"should_not_inject":["dec-004-cap"],"should_suppress":false},"notes":"Architecture decision — local-first rationale"}]}
{"id":"whisper-dec-005","space":"ormah","memories":[{"node_id":"dec-005-tiers","title":"Decision: three memory tiers — core, working, archival — not a flat list","content":"We decided on three tiers instead of a flat list because: core needs always-available fast loading (cap 50), working is the active search space with decay, and archival is for historical context rarely needed. Each tier has different retrieval semantics.","type":"decision","tier":"working","tags":["tiers","architecture","decision"],"space":"ormah"},{"node_id":"dec-005-sync","title":"Whisper is synchronous","content":"Synchronous to avoid race condition.","type":"fact","tier":"working","tags":["whisper"],"space":"ormah"}],"prompts":[{"text":"why does ormah have three memory tiers instead of one","category":"decision","expected":{"should_inject":["dec-005-tiers"],"should_not_inject":["dec-005-sync"],"should_suppress":false},"notes":"Architecture decision with rationale"}]}
{"id":"whisper-tech-001","space":"ormah","memories":[{"node_id":"tech-001-whisper","title":"Whisper pipeline: 8 stages from prompt to injection","content":"The whisper pipeline: (1) short prompt check, (2) topic-shift detection, (3) PromptClassifier intent detection, (4) hybrid search with intent params, (5) min_score filter, (6) cross-encoder reranker, (7) affinity boost, (8) injection gate. Returns empty string if gate not cleared.","type":"fact","tier":"working","tags":["whisper","architecture"],"space":"ormah"},{"node_id":"tech-001-port","title":"Port 8787","content":"Default port.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"how does whisper injection work","category":"technical","expected":{"should_inject":["tech-001-whisper"],"should_not_inject":["tech-001-port"],"should_suppress":false},"notes":"Technical explanation — multi-stage pipeline architecture"}]}
{"id":"whisper-tech-002","space":"ormah","memories":[{"node_id":"tech-002-rrf","title":"RRF formula: 1/(k+rank) with k=60, FTS dampened by 0.5","content":"Reciprocal Rank Fusion score = 1/(k + rank) where k=60 is a smoothing constant. FTS results are dampened by 0.5 before fusion. Weights configurable via ORMAH_FTS_WEIGHT (default 1.0) and ORMAH_VECTOR_WEIGHT (default 1.0).","type":"fact","tier":"working","tags":["search","algorithm"],"space":"ormah"},{"node_id":"tech-002-decay","title":"FSRS decay for working tier","content":"Working memories decay via FSRS after ~14 days.","type":"fact","tier":"working","tags":["decay"],"space":"ormah"}],"prompts":[{"text":"explain how RRF fusion works","category":"technical","expected":{"should_inject":["tech-002-rrf"],"should_not_inject":["tech-002-decay"],"should_suppress":false},"notes":"Technical explanation — algorithm details"}]}
{"id":"whisper-tech-003","space":"ormah","memories":[{"node_id":"tech-003-fsrs","title":"Ormah decay uses FSRS spaced repetition — stability field tracks retrievability","content":"Working-tier memories decay using FSRS (Free Spaced Repetition Scheduler). The stability field tracks days until ~37% retrievability. Each access resets stability via the FSRS review formula.","type":"fact","tier":"working","tags":["decay","algorithm"],"space":"ormah"},{"node_id":"tech-003-mcp","title":"Ormah MCP exposes 6 agent tools","content":"remember, recall, get_self, mark_outdated, run_maintenance, submit_feedback.","type":"fact","tier":"working","tags":["mcp"],"space":"ormah"}],"prompts":[{"text":"how does memory decay work in ormah","category":"technical","expected":{"should_inject":["tech-003-fsrs"],"should_not_inject":["tech-003-mcp"],"should_suppress":false},"notes":"Technical explanation — decay algorithm"}]}
{"id":"whisper-tech-004","space":"ormah","memories":[{"node_id":"tech-004-reranker","title":"Cross-encoder reranker blends CE score and embedding score with sigmoid","content":"The reranker blends cross-encoder score with embedding score: blended = blend_alpha * sigmoid(ce_score) + (1 - blend_alpha) * emb_score. Default blend_alpha is 0.4. Uses cross-encoder/ms-marco-MiniLM-L-6-v2.","type":"fact","tier":"working","tags":["reranker","whisper"],"space":"ormah"},{"node_id":"tech-004-tier","title":"Three memory tiers","content":"core/working/archival with different retention semantics.","type":"fact","tier":"working","tags":["tiers"],"space":"ormah"}],"prompts":[{"text":"how does the cross-encoder reranker score memories","category":"technical","expected":{"should_inject":["tech-004-reranker"],"should_not_inject":["tech-004-tier"],"should_suppress":false},"notes":"Technical explanation — reranker blend formula"}]}
{"id":"whisper-id-001","space":"ormah","memories":[{"node_id":"id-001-loc","title":"User lives in Dublin, Ireland","content":"Rishi lives in Dublin, Ireland.","type":"fact","tier":"core","tags":["personal","location"],"space":null},{"node_id":"id-001-port","title":"Ormah runs on port 8787","content":"Default port 8787.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"where does the user live","category":"identity","expected":{"should_inject":["id-001-loc"],"should_not_inject":["id-001-port"],"should_suppress":false},"notes":"Explicit identity query — location from global space=null memory"}]}
{"id":"whisper-id-002","space":"ormah","memories":[{"node_id":"id-002-job","title":"Rishi is a software engineer building AI-native tools","content":"Rishi Khandelwal is a software engineer. Currently building ormah as a side project and working on AI agent tooling professionally.","type":"fact","tier":"core","tags":["personal","career"],"space":null},{"node_id":"id-002-rrf","title":"RRF fusion algorithm","content":"RRF: 1/(k+rank) with k=60.","type":"fact","tier":"working","tags":["search"],"space":"ormah"}],"prompts":[{"text":"what is the user's job","category":"identity","expected":{"should_inject":["id-002-job"],"should_not_inject":["id-002-rrf"],"should_suppress":false},"notes":"Explicit identity query — profession"}]}
{"id":"whisper-id-003","space":"ormah","memories":[{"node_id":"id-003-proj","title":"Rishi is building ormah as a side project — persistent memory system for AI agents","content":"Rishi created ormah as a side project. It is a local-first persistent memory system for AI agents. He describes it as 'a nature-inspired persistent memory system for AI agents'.","type":"fact","tier":"core","tags":["personal","career","ormah"],"space":null},{"node_id":"id-003-fsrs","title":"FSRS decay for working memories","content":"14-day decay via FSRS.","type":"fact","tier":"working","tags":["decay"],"space":"ormah"}],"prompts":[{"text":"what am I working on professionally right now","category":"identity","expected":{"should_inject":["id-003-proj"],"should_not_inject":["id-003-fsrs"],"should_suppress":false},"notes":"Identity query — current work, cross-space (space=null memory queried from project context)"}]}
{"id":"whisper-id-004","space":"ormah","memories":[{"node_id":"id-004-gpu","title":"User's home GPU is RTX 3060 12GB for local ML inference","content":"GPU: ZOTAC Gaming RTX 3060 12GB OC. Used for local ML model inference including ormah's embedding model.","type":"fact","tier":"core","tags":["hardware","personal"],"space":null},{"node_id":"id-004-port","title":"Port 8787","content":"Default port.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"what GPU does the user have","category":"identity","expected":{"should_inject":["id-004-gpu"],"should_not_inject":["id-004-port"],"should_suppress":false},"notes":"Identity query — hardware spec from global memory"}]}
{"id":"whisper-temp-001","space":"ormah","memories":[{"node_id":"temp-001-recent","title":"Implemented flat ranked whisper display — top 2 full, rest title-only","content":"Rewrote whisper output format: flat ranked list, top 2 memories show full content + node ID, remaining memories (up to 6 total) show title + type + node ID only. Removed all section headers and budget-based truncation.","type":"fact","tier":"working","tags":["whisper","implementation"],"space":"ormah","created":"2026-03-27T10:00:00Z"},{"node_id":"temp-001-old","title":"Old whisper format used section headers","content":"The old whisper format used ## About the User, ## Core Memories, ## Project sections. Removed in 0.8.0.","type":"fact","tier":"working","tags":["whisper","history"],"space":"ormah","created":"2025-12-01T10:00:00Z"}],"prompts":[{"text":"what did we implement last week","category":"temporal","expected":{"should_inject":["temp-001-recent"],"should_not_inject":["temp-001-old"],"should_suppress":false},"notes":"Temporal query — recent memory should surface, older one should not"}]}
{"id":"whisper-temp-002","space":"ormah","memories":[{"node_id":"temp-002-today","title":"Added _return_debug flag to build_whisper_context","content":"Added _return_debug: bool = False parameter to build_whisper_context. When True, returns (whisper_text, injected_ids) tuple instead of just the string. Used by whisper eval runner.","type":"fact","tier":"working","tags":["implementation"],"space":"ormah","created":"2026-03-28T08:00:00Z"},{"node_id":"temp-002-old","title":"Early prototype stored memories in flat JSON file","content":"In the original prototype (2024), memories were stored in a flat JSON file. Replaced by markdown files in v0.1.","type":"fact","tier":"archival","tags":["history"],"space":"ormah","created":"2024-06-01T00:00:00Z"}],"prompts":[{"text":"what did I work on today","category":"temporal","expected":{"should_inject":["temp-002-today"],"should_not_inject":["temp-002-old"],"should_suppress":false},"notes":"Temporal query — today filter, archival tier should not surface"}]}
{"id":"whisper-temp-003","space":"ormah","memories":[{"node_id":"temp-003-recent","title":"Removed get_context tool — replaced by whisper and get_self","content":"Removed the get_context MCP tool. Its responsibilities were split: whisper handles involuntary recall injection, get_self handles identity profile loading.","type":"fact","tier":"working","tags":["mcp","refactor"],"space":"ormah","created":"2026-03-20T00:00:00Z"},{"node_id":"temp-003-very-old","title":"Initial MCP server setup from 2025","content":"Initial MCP server was set up in January 2025 with 3 tools.","type":"fact","tier":"archival","tags":["history","mcp"],"space":"ormah","created":"2025-01-15T00:00:00Z"}],"prompts":[{"text":"recent changes to ormah","category":"temporal","expected":{"should_inject":["temp-003-recent"],"should_not_inject":["temp-003-very-old"],"should_suppress":false},"notes":"Recency query — recent work should surface, archival history should not"}]}
{"id":"whisper-temp-004","space":"ormah","memories":[{"node_id":"temp-004-week","title":"Merged whisper truncation and referencing feature to main","content":"Feature branch feature/whisper-truncation-and-referencing was merged to main. 726 tests passing. Changed whisper output to flat ranked list with top-2 full content and rest as titles.","type":"fact","tier":"working","tags":["release","whisper"],"space":"ormah","created":"2026-03-28T07:00:00Z"},{"node_id":"temp-004-2025","title":"Ormah v0.5.0 released in 2025","content":"Version 0.5.0 released in November 2025 with affinity boost and reranker.","type":"fact","tier":"archival","tags":["release"],"space":"ormah","created":"2025-11-01T00:00:00Z"}],"prompts":[{"text":"what was the last thing we merged to main","category":"temporal","expected":{"should_inject":["temp-004-week"],"should_not_inject":["temp-004-2025"],"should_suppress":false},"notes":"Temporal + recency — most recent merge event"}]}
{"id":"whisper-noise-001","space":"ormah","memories":[{"node_id":"noise-001-pref","title":"User prefers dark themes","content":"Dark theme preferred.","type":"preference","tier":"core","tags":["ui"],"space":null}],"prompts":[{"text":"hello","category":"noise","expected":{"should_inject":[],"should_not_inject":["noise-001-pref"],"should_suppress":true},"notes":"Conversational greeting — should suppress entirely"}]}
{"id":"whisper-noise-002","space":"ormah","memories":[{"node_id":"noise-002-fact","title":"Ormah port 8787","content":"Port 8787.","type":"fact","tier":"working","tags":["config"],"space":"ormah"}],"prompts":[{"text":"thanks for the help","category":"noise","expected":{"should_inject":[],"should_not_inject":["noise-002-fact"],"should_suppress":true},"notes":"Conversational thanks — should suppress"}]}
{"id":"whisper-noise-003","space":"ormah","memories":[{"node_id":"noise-003-arch","title":"Ormah uses SQLite FTS5","content":"SQLite FTS5 + sqlite-vec, RRF fusion.","type":"fact","tier":"working","tags":["architecture"],"space":"ormah"}],"prompts":[{"text":"what is the weather in Dublin today","category":"noise","expected":{"should_inject":[],"should_not_inject":["noise-003-arch"],"should_suppress":true},"notes":"Completely off-topic — should suppress, no corpus memory is relevant"}]}
{"id":"whisper-noise-004","space":"ormah","memories":[{"node_id":"noise-004-pref","title":"User prefers concise responses","content":"No trailing summaries.","type":"preference","tier":"core","tags":["collaboration"],"space":null}],"prompts":[{"text":"ok sounds good","category":"noise","expected":{"should_inject":[],"should_not_inject":["noise-004-pref"],"should_suppress":true},"notes":"Short conversational acknowledgement — should suppress"}]}
{"id":"whisper-noise-005","space":"ormah","memories":[{"node_id":"noise-005-fact","title":"Whisper uses injection gate 0.55","content":"The injection gate threshold is 0.55.","type":"fact","tier":"working","tags":["whisper"],"space":"ormah"}],"prompts":[{"text":"continue please","category":"noise","expected":{"should_inject":[],"should_not_inject":["noise-005-fact"],"should_suppress":true},"notes":"'continue please' is in the conversational archetype — should suppress"}]}
{"id":"whisper-cont-001","space":"ormah","memories":[{"node_id":"cont-001-recent","title":"Working on whisper eval corpus — writing golden test cases","content":"Currently working on the whisper evaluation system. Writing golden corpus cases across 8 categories: preference, factual, decision, technical, identity, temporal, noise, continuation.","type":"fact","tier":"working","tags":["eval","whisper"],"space":"ormah","created":"2026-03-28T09:00:00Z"},{"node_id":"cont-001-2025","title":"Ormah v0.3.0 released in 2025","content":"Version 0.3.0 released with core memory cap enforcement.","type":"fact","tier":"archival","tags":["release"],"space":"ormah","created":"2025-06-01T00:00:00Z"}],"prompts":[{"text":"where were we","category":"continuation","expected":{"should_inject":["cont-001-recent"],"should_not_inject":["cont-001-2025"],"should_suppress":false},"notes":"Continuation query — should surface most recent work context"}]}
{"id":"whisper-cont-002","space":"ormah","memories":[{"node_id":"cont-002-recent","title":"Designing whisper eval system — category taxonomy finalized","content":"Designing a new whisper eval system. Finalized 8 query categories: preference (implicit surfacing), factual (direct lookup), decision (type retrieval), technical (explanatory), identity (personal info), temporal (time-filtered), noise (suppression), continuation (recency fallback).","type":"fact","tier":"working","tags":["eval","design"],"space":"ormah","created":"2026-03-28T08:30:00Z"},{"node_id":"cont-002-old","title":"Old context system from v0.4","content":"v0.4 used get_context for both whisper and identity.","type":"fact","tier":"archival","tags":["history"],"space":"ormah","created":"2025-10-01T00:00:00Z"}],"prompts":[{"text":"continue where we left off","category":"continuation","expected":{"should_inject":["cont-002-recent"],"should_not_inject":["cont-002-old"],"should_suppress":false},"notes":"Continuation — should find recent session context via recency fallback"}]}
{"id":"whisper-cont-003","space":"ormah","memories":[{"node_id":"cont-003-recent","title":"Implemented whisper eval runner and metrics modules","content":"Built eval/whisper/runner.py and eval/whisper/metrics.py. Runner seeds isolated DB, calls build_whisper_context with _return_debug=True, collects PromptResult per prompt. Metrics compute injection_recall, precision, f1, top2_recall, suppression_accuracy.","type":"fact","tier":"working","tags":["eval","implementation"],"space":"ormah","created":"2026-03-28T11:00:00Z"},{"node_id":"cont-003-arch","title":"Ormah layer stack","content":"Adapters → API → MemoryEngine → Embeddings → Index → Store.","type":"fact","tier":"working","tags":["architecture"],"space":"ormah","created":"2025-08-01T00:00:00Z"}],"prompts":[{"text":"let's pick up from where we stopped yesterday","category":"continuation","expected":{"should_inject":["cont-003-recent"],"should_not_inject":["cont-003-arch"],"should_suppress":false},"notes":"Continuation with recency framing — recent work surfaces, old architecture note does not"}]}
```

- [ ] **Step 2: Validate the corpus loads without errors**

```bash
cd /home/r2205/Projects/ormah/.worktrees/whisper-eval
uv run python -c "
from pathlib import Path
from eval.whisper.corpus import load_corpus
cases = load_corpus(Path('eval/whisper/corpus/golden/golden.jsonl'))
print(f'Loaded {len(cases)} cases')
cats = {}
for c in cases:
    for p in c['prompts']:
        cat = p.get('category','?')
        cats[cat] = cats.get(cat,0) + 1
for cat, n in sorted(cats.items()):
    print(f'  {cat}: {n}')
"
```

Expected output:
```
Loaded 37 cases
  continuation: 3
  decision: 5
  factual: 6
  identity: 4
  noise: 5
  preference: 6
  technical: 4
  temporal: 4
```

- [ ] **Step 3: Commit**

```bash
git add eval/whisper/corpus/golden/golden.jsonl
git commit -m "feat(eval): whisper golden corpus — 37 prompts across 8 categories"
```

---

## Task 9: Full Smoke Test

- [ ] **Step 1: Reinstall from worktree**

```bash
cd /home/r2205/Projects/ormah/.worktrees/whisper-eval
uv tool install . --reinstall
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all passing, including new `test_eval_whisper/` and `test_engine/test_whisper_debug.py`.

- [ ] **Step 3: Smoke-run the CLI against the golden corpus**

```bash
ormah eval whisper run --show-failures
```

Expected: table with 8 category rows printed to stdout. No crash.

- [ ] **Step 4: Verify category filter works**

```bash
ormah eval whisper run --category preference --show-failures
```

Expected: table showing only the `preference` row (6 prompts).

- [ ] **Step 5: Verify JSON output**

```bash
ormah eval whisper run --json | python3 -m json.tool | head -20
```

Expected: valid JSON with `aggregate` and `category_aggregates` keys.

- [ ] **Step 6: Commit smoke test result**

```bash
git add -A
git commit -m "chore: verify whisper eval smoke test passes"
```
