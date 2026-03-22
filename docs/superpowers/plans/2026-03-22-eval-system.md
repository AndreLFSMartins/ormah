# Whisper & Recall Eval System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone eval module (`eval/`) that measures whisper injection precision and recall against a versioned corpus, with CI regression gates.

**Architecture:** Standalone `eval/` package at repo root. Uses `MemoryEngine` pointed at an isolated SQLite DB (`eval/eval_db/`). Per-case seeding: DB cleared and reseeded per eval case using forced node IDs from the corpus. Runner calls `recall_search_structured` directly to get structured results and computes metrics against labeled ground truth. CLI commands wired into `ormah eval *`.

**Tech Stack:** Python, ormah `MemoryEngine`/`MemoryNode`/`FileStore`/`IndexBuilder` (internal APIs), `recall_search_structured` for retrieval, argparse for CLI, JSONL for corpus + results.

**Worktree:** `/home/r2205/Projects/ormah/.worktrees/eval-system` on branch `feature/eval-system`

**Spec:** `docs/superpowers/specs/2026-03-22-whisper-recall-eval-system-design.md`

---

## File Map

**Create:**
- `eval/__init__.py` — package marker
- `eval/corpus.py` — load, parse, validate corpus JSONL files
- `eval/seeder.py` — clear eval DB + seed case memories with forced node IDs
- `eval/runner.py` — orchestrate per-case eval: seed → recall → score → aggregate
- `eval/metrics.py` — recall@k, precision@k, F1@k, MRR, injection_rate, false_negative_rate
- `eval/report.py` — format stdout report, write latest.json, append history.jsonl
- `eval/judge.py` — export-for-labeling, import-labels
- `eval/session.py` — capture-session: parse Claude Code transcript into unlabeled corpus entry
- `eval/cli.py` — all `ormah eval *` CLI command handlers
- `eval/corpus/golden/golden.jsonl` — initial 10 hand-crafted golden cases
- `eval/corpus/sessions/.gitkeep` — placeholder, sessions are gitignored
- `eval/.gitignore` — ignore eval_db/, results/, corpus/sessions/*.jsonl, corpus/pending_labels.jsonl, corpus/labels.jsonl
- `tests/test_eval/__init__.py`
- `tests/test_eval/test_corpus.py`
- `tests/test_eval/test_seeder.py`
- `tests/test_eval/test_metrics.py`
- `tests/test_eval/test_runner.py`
- `tests/test_eval/test_report.py`
- `tests/test_eval/test_judge.py`
- `tests/test_eval/test_session.py`

**Modify:**
- `src/ormah/cli.py` — add `eval` subparser that delegates to `eval/cli.py`

---

## Key Implementation Notes (read before starting)

**Seeding with forced node IDs:** `MemoryNode.id` is a Pydantic field with `default_factory=lambda: str(uuid.uuid4())`. You can override it: `MemoryNode(id="golden-001-mem-0", ...)`. The seeder creates nodes this way, then calls `engine.file_store.save(node)` → `engine.builder.index_single(path)` → `engine._index_embedding(node)`. This bypasses `remember()` (which auto-generates IDs and runs auto-linking/core-cap enforcement we don't want in eval).

**Clearing between cases:** Delete all `.md` files from `engine.file_store.nodes_dir`, call `engine.builder.full_rebuild()` (rebuilds empty), then `engine.db.conn.execute("DELETE FROM node_vectors")`.

**Getting structured retrieval results:** The eval runner calls `engine.recall_search_structured(query=prompt, limit=k, tiers=["core","working"], touch_access=False)`. This returns `list[dict]` with `{"node": {...}, "score": float}`. We do NOT call `build_whisper_context` (which returns a string). We apply `min_score` and `injection_gate` thresholds manually to simulate the pipeline.

**Engine startup for eval:** Call `engine.startup()` once when initializing the eval run. It creates a self-node (user identity), which is fine — the seeder's `clear()` removes it before each case. Don't disable or skip startup; the embedder warmup it runs is necessary for search to work.

**Session replay seeding:** Session cases have no embedded memories. When the runner encounters a session case, it seeds the FULL golden + synthetic corpus into the eval DB (all memories from both tiers), then runs each session prompt against that combined corpus.

---

## Task 1: Package skeleton and corpus loader

**Files:**
- Create: `eval/__init__.py`
- Create: `eval/corpus.py`
- Create: `eval/.gitignore`
- Create: `eval/corpus/sessions/.gitkeep`
- Create: `tests/test_eval/__init__.py`
- Create: `tests/test_eval/test_corpus.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval/test_corpus.py
import json
import pytest
from pathlib import Path
from eval.corpus import load_corpus, validate_case, CorpusError


def _write_jsonl(path, lines):
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")


def test_load_golden_case(tmp_path):
    case = {
        "id": "test-001",
        "memories": [
            {"node_id": "test-001-mem-0", "title": "SQLite FTS5", "content": "Uses FTS5", "type": "fact", "tier": "working"}
        ],
        "prompts": [
            {"text": "how does search work?", "expected": {"should_inject": ["test-001-mem-0"], "should_not_inject": []}}
        ]
    }
    f = tmp_path / "golden.jsonl"
    _write_jsonl(f, [case])
    cases = load_corpus(f)
    assert len(cases) == 1
    assert cases[0]["id"] == "test-001"
    assert cases[0]["memories"][0]["node_id"] == "test-001-mem-0"


def test_load_skips_header(tmp_path):
    header = {"_header": True, "generated_at": "2026-01-01", "generator_version": "0.3.0"}
    case = {"id": "syn-001", "memories": [], "prompts": []}
    f = tmp_path / "synthetic.jsonl"
    _write_jsonl(f, [header, case])
    cases = load_corpus(f)
    assert len(cases) == 1
    assert cases[0]["id"] == "syn-001"


def test_load_empty_file(tmp_path):
    f = tmp_path / "golden.jsonl"
    f.write_text("")
    cases = load_corpus(f)
    assert cases == []


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(CorpusError, match="not found"):
        load_corpus(tmp_path / "nonexistent.jsonl")


def test_validate_case_missing_node_id(tmp_path):
    case = {
        "id": "bad-001",
        "memories": [{"title": "no id", "content": "x", "type": "fact", "tier": "working"}],
        "prompts": []
    }
    with pytest.raises(CorpusError, match="node_id"):
        validate_case(case)


def test_validate_case_duplicate_node_ids():
    case = {
        "id": "dup-001",
        "memories": [
            {"node_id": "dup-001-mem-0", "title": "A", "content": "a", "type": "fact", "tier": "working"},
            {"node_id": "dup-001-mem-0", "title": "B", "content": "b", "type": "fact", "tier": "working"},
        ],
        "prompts": []
    }
    with pytest.raises(CorpusError, match="duplicate"):
        validate_case(case)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/r2205/Projects/ormah/.worktrees/eval-system
uv run pytest tests/test_eval/test_corpus.py -v
```
Expected: `ModuleNotFoundError: No module named 'eval'` or similar import error.

- [ ] **Step 3: Create the package files**

`eval/__init__.py`:
```python
"""Ormah eval system — whisper and recall precision measurement."""
```

`eval/.gitignore`:
```
eval_db/
results/
corpus/sessions/*.jsonl
corpus/pending_labels.jsonl
corpus/labels.jsonl
```

`eval/corpus/sessions/.gitkeep`:
```
```

`eval/corpus.py`:
```python
"""Load and validate eval corpus files (JSONL format)."""

from __future__ import annotations

import json
from pathlib import Path


class CorpusError(Exception):
    """Raised on corpus file errors."""


def load_corpus(path: Path) -> list[dict]:
    """Load a corpus JSONL file. Skips header lines. Returns list of cases.

    Raises CorpusError if the file does not exist.
    """
    if not path.exists():
        raise CorpusError(f"Corpus file not found: {path}")

    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("_header"):
            continue
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
            raise CorpusError(
                f"Case '{case_id}' memory[{i}] missing required 'node_id' field"
            )
        if node_id in seen_ids:
            raise CorpusError(
                f"Case '{case_id}' has duplicate node_id: '{node_id}'"
            )
        seen_ids.add(node_id)
```

`tests/test_eval/__init__.py`:
```python
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval/test_corpus.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/__init__.py eval/.gitignore eval/corpus.py eval/corpus/sessions/.gitkeep tests/test_eval/__init__.py tests/test_eval/test_corpus.py
git commit -m "feat(eval): package skeleton and corpus loader"
```

---

## Task 2: DB seeder

**Files:**
- Create: `eval/seeder.py`
- Create: `tests/test_eval/test_seeder.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval/test_seeder.py
import pytest
from pathlib import Path
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine
from eval.seeder import seed_case, clear_eval_db


@pytest.fixture
def eval_engine(tmp_path):
    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    yield engine
    engine.shutdown()


def _make_case(case_id="t-001"):
    return {
        "id": case_id,
        "memories": [
            {
                "node_id": f"{case_id}-mem-0",
                "title": "Test memory A",
                "content": "Content about hybrid search and FTS5",
                "type": "fact",
                "tier": "working",
                "tags": ["search"],
                "space": "testproject",
            },
            {
                "node_id": f"{case_id}-mem-1",
                "title": "Test memory B",
                "content": "Content about vector embeddings",
                "type": "fact",
                "tier": "working",
                "tags": [],
                "space": "testproject",
            },
        ],
        "prompts": [],
    }


def test_seed_inserts_nodes_with_correct_ids(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    node = eval_engine.graph.get_node("t-001-mem-0")
    assert node is not None
    assert node["title"] == "Test memory A"


def test_seed_forces_node_id(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    node = eval_engine.graph.get_node("t-001-mem-0")
    assert node["id"] == "t-001-mem-0"


def test_seed_only_case_nodes_in_db(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    count = eval_engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert count == 2  # only the 2 case memories, no self-node


def test_clear_removes_all_nodes(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    clear_eval_db(eval_engine)
    count = eval_engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert count == 0


def test_seed_after_clear_gives_fresh_state(eval_engine):
    case_a = _make_case("a-001")
    case_b = _make_case("b-001")
    seed_case(eval_engine, case_a)
    seed_case(eval_engine, case_b)  # should clear a-001 first
    assert eval_engine.graph.get_node("a-001-mem-0") is None
    assert eval_engine.graph.get_node("b-001-mem-0") is not None


def test_seed_indexes_embedding(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    vec_count = eval_engine.db.conn.execute("SELECT COUNT(*) FROM node_vectors").fetchone()[0]
    assert vec_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eval/test_seeder.py -v
```
Expected: `ModuleNotFoundError: No module named 'eval.seeder'`

- [ ] **Step 3: Implement the seeder**

`eval/seeder.py`:
```python
"""Seed the isolated eval DB with memories from a corpus case."""

from __future__ import annotations

from ormah.models.node import MemoryNode, NodeType, Tier


def seed_case(engine, case: dict) -> None:
    """Clear eval DB and seed with memories from *case*.

    Memories are inserted with their corpus node_id preserved — no UUID generation.
    Skips auto-linking and core-cap enforcement (not relevant for eval).
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
    engine.builder.full_rebuild()
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval/test_seeder.py -v
```
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/seeder.py tests/test_eval/test_seeder.py
git commit -m "feat(eval): DB seeder with forced node IDs"
```

---

## Task 3: Metrics module

**Files:**
- Create: `eval/metrics.py`
- Create: `tests/test_eval/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval/test_metrics.py
import pytest
from eval.metrics import recall_at_k, precision_at_k, f1_at_k, mrr, false_negative_rate, compute_case_metrics


def test_recall_perfect():
    assert recall_at_k(["a", "b"], ["a", "b", "c", "d"], k=8) == 1.0


def test_recall_partial():
    assert recall_at_k(["a", "b"], ["a", "c", "d", "e"], k=8) == pytest.approx(0.5)


def test_recall_none_injected():
    assert recall_at_k(["a", "b"], ["c", "d"], k=8) == 0.0


def test_recall_empty_should_inject():
    # No ground truth — undefined, returns None
    assert recall_at_k([], ["a", "b"], k=8) is None


def test_precision_perfect():
    assert precision_at_k(["a", "b"], ["a", "b"], k=2) == 1.0


def test_precision_zero():
    assert precision_at_k(["a", "b"], ["c", "d"], k=2) == 0.0


def test_precision_empty_results():
    assert precision_at_k(["a"], [], k=8) == 0.0


def test_f1_perfect():
    assert f1_at_k(["a"], ["a"], k=8) == pytest.approx(1.0)


def test_f1_zero():
    assert f1_at_k(["a"], ["b"], k=8) == pytest.approx(0.0)


def test_mrr_first_result_relevant():
    assert mrr(["a", "b"], ["a", "c", "d"]) == pytest.approx(1.0)


def test_mrr_second_result_relevant():
    assert mrr(["a", "b"], ["c", "a", "d"]) == pytest.approx(0.5)


def test_mrr_no_relevant():
    assert mrr(["a"], ["b", "c"]) == pytest.approx(0.0)


def test_false_negative_rate_all_missed():
    assert false_negative_rate(["a", "b"], ["c", "d"], k=8) == pytest.approx(1.0)


def test_false_negative_rate_none_missed():
    assert false_negative_rate(["a", "b"], ["a", "b"], k=8) == pytest.approx(0.0)


def test_compute_case_metrics_returns_all_keys():
    result = compute_case_metrics(
        should_inject=["a", "b"],
        ranked_ids=["a", "c", "d", "b"],
        injection_gate=0.55,
        ranked_scores=[0.9, 0.8, 0.7, 0.6],
        k=8,
    )
    for key in ["recall", "precision", "f1", "mrr", "false_negative_rate", "injection_fired"]:
        assert key in result


def test_injection_fired_false_when_gate_filters_all():
    result = compute_case_metrics(
        should_inject=["a"],
        ranked_ids=["a", "b"],
        injection_gate=0.99,   # very high gate
        ranked_scores=[0.5, 0.4],
        k=8,
    )
    assert result["injection_fired"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eval/test_metrics.py -v
```
Expected: `ModuleNotFoundError: No module named 'eval.metrics'`

- [ ] **Step 3: Implement the metrics module**

`eval/metrics.py`:
```python
"""Precision, recall, and related retrieval metrics for eval."""

from __future__ import annotations


def recall_at_k(
    should_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> float | None:
    """Fraction of should_inject nodes appearing in top-k ranked results.

    Returns None if should_inject is empty (undefined metric).
    """
    if not should_inject:
        return None
    top_k = set(ranked_ids[:k])
    hits = sum(1 for nid in should_inject if nid in top_k)
    return hits / len(should_inject)


def precision_at_k(
    should_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> float:
    """Fraction of top-k injected nodes that are in should_inject."""
    top_k = ranked_ids[:k]
    if not top_k:
        return 0.0
    relevant = set(should_inject)
    hits = sum(1 for nid in top_k if nid in relevant)
    return hits / len(top_k)


def f1_at_k(
    should_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> float | None:
    """Harmonic mean of recall@k and precision@k. Returns None if recall is None."""
    r = recall_at_k(should_inject, ranked_ids, k)
    if r is None:
        return None
    p = precision_at_k(should_inject, ranked_ids, k)
    if r + p == 0:
        return 0.0
    return 2 * p * r / (p + r)


def mrr(should_inject: list[str], ranked_ids: list[str]) -> float:
    """Mean Reciprocal Rank of the first relevant result."""
    relevant = set(should_inject)
    for rank, nid in enumerate(ranked_ids, start=1):
        if nid in relevant:
            return 1.0 / rank
    return 0.0


def false_negative_rate(
    should_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> float | None:
    """Fraction of should_inject nodes completely missed (not in top-k).

    Returns None if should_inject is empty.
    """
    if not should_inject:
        return None
    top_k = set(ranked_ids[:k])
    missed = sum(1 for nid in should_inject if nid not in top_k)
    return missed / len(should_inject)


def compute_case_metrics(
    should_inject: list[str],
    ranked_ids: list[str],
    injection_gate: float,
    ranked_scores: list[float],
    k: int,
) -> dict:
    """Compute all metrics for a single (prompt, results) pair.

    injection_fired: True if at least one result passes the injection_gate.
    """
    above_gate = [nid for nid, score in zip(ranked_ids, ranked_scores) if score >= injection_gate]
    return {
        "recall": recall_at_k(should_inject, ranked_ids, k),
        "precision": precision_at_k(should_inject, ranked_ids, k),
        "f1": f1_at_k(should_inject, ranked_ids, k),
        "mrr": mrr(should_inject, ranked_ids),
        "false_negative_rate": false_negative_rate(should_inject, ranked_ids, k),
        "injection_fired": len(above_gate) > 0,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval/test_metrics.py -v
```
Expected: all 18 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/metrics.py tests/test_eval/test_metrics.py
git commit -m "feat(eval): metrics module — recall@k, precision@k, F1, MRR, FNR"
```

---

## Task 4: Eval runner

**Files:**
- Create: `eval/runner.py`
- Create: `tests/test_eval/test_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval/test_runner.py
"""Integration tests for the eval runner."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from eval.runner import run_eval, EvalResult


def _make_case(case_id, mem_titles, prompt_text, should_inject):
    return {
        "id": case_id,
        "memories": [
            {
                "node_id": f"{case_id}-mem-{i}",
                "title": t,
                "content": f"Content about {t.lower()}",
                "type": "fact",
                "tier": "working",
                "space": "testproject",
            }
            for i, t in enumerate(mem_titles)
        ],
        "prompts": [
            {
                "text": prompt_text,
                "expected": {
                    "should_inject": should_inject,
                    "should_not_inject": [],
                },
            }
        ],
    }


@pytest.fixture
def eval_engine(tmp_path):
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine
    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    yield engine
    engine.shutdown()


def test_run_eval_returns_result(eval_engine, tmp_path):
    case = _make_case(
        "t-001",
        ["SQLite search", "Unrelated memory"],
        "how does search work?",
        ["t-001-mem-0"],
    )
    result = run_eval([case], eval_engine, k=8)
    assert isinstance(result, EvalResult)
    assert len(result.case_results) == 1


def test_run_eval_empty_corpus(eval_engine):
    result = run_eval([], eval_engine, k=8)
    assert result.aggregate["recall"] is None
    assert result.aggregate["precision"] is None
    assert result.case_results == []


def test_run_eval_all_unlabeled(eval_engine):
    case = {
        "id": "unlabeled-001",
        "memories": [
            {"node_id": "u-mem-0", "title": "A", "content": "stuff", "type": "fact", "tier": "working"}
        ],
        "prompts": [
            {"text": "what is X?", "expected": {"should_inject": [], "should_not_inject": []}}
        ],
    }
    result = run_eval([case], eval_engine, k=8)
    assert result.aggregate["recall"] is None  # no labeled cases


def test_run_eval_case_isolation(eval_engine):
    case_a = _make_case("a-001", ["Fact about apples"], "tell me about apples", ["a-001-mem-0"])
    case_b = _make_case("b-001", ["Fact about oranges"], "tell me about oranges", ["b-001-mem-0"])
    result = run_eval([case_a, case_b], eval_engine, k=8)
    assert len(result.case_results) == 2
    # Case A's memory should not appear in case B's search
    case_b_result = result.case_results[1]
    all_returned_ids = [nid for nid in case_b_result.get("all_ranked_ids", [])]
    assert "a-001-mem-0" not in all_returned_ids
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eval/test_runner.py -v
```
Expected: `ModuleNotFoundError: No module named 'eval.runner'`

- [ ] **Step 3: Implement the runner**

`eval/runner.py`:
```python
"""Eval runner: orchestrates per-case seeding, retrieval, and scoring."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from eval.metrics import compute_case_metrics
from eval.seeder import seed_case

logger = logging.getLogger(__name__)

_INJECTION_GATE = 0.55  # mirrors settings.whisper_injection_gate default


@dataclass
class EvalResult:
    case_results: list[dict] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)


def run_eval(
    cases: list[dict],
    engine,
    k: int = 8,
    min_score: float = 0.45,
    injection_gate: float = _INJECTION_GATE,
) -> EvalResult:
    """Run the eval pipeline over *cases*. Returns EvalResult with per-case and aggregate metrics.

    For each case:
    1. Seed eval DB with only that case's memories (full corpus cleared first)
    2. Run recall_search_structured for each prompt
    3. Compute metrics against ground truth labels
    """
    all_case_results = []

    for case in cases:
        case_result = _eval_case(case, engine, k=k, min_score=min_score, injection_gate=injection_gate)
        all_case_results.append(case_result)

    aggregate = _aggregate(all_case_results, k=k)
    return EvalResult(case_results=all_case_results, aggregate=aggregate)


def _eval_case(case: dict, engine, k: int, min_score: float, injection_gate: float) -> dict:
    """Seed and evaluate a single corpus case."""
    seed_case(engine, case)

    prompt_results = []
    for prompt_obj in case.get("prompts", []):
        prompt_text = prompt_obj["text"]
        expected = prompt_obj.get("expected", {})
        should_inject = expected.get("should_inject", [])

        try:
            raw = engine.recall_search_structured(
                query=prompt_text,
                limit=k * 2,  # over-fetch before filtering
                tiers=["core", "working"],
                touch_access=False,
            )
        except Exception as e:
            logger.warning("recall_search_structured failed for case %s: %s", case["id"], e)
            raw = []

        # Apply min_score filter (same as whisper pipeline)
        filtered = [r for r in raw if r.get("score", 0) >= min_score]
        ranked_ids = [r["node"]["id"] for r in filtered]
        ranked_scores = [r.get("score", 0.0) for r in filtered]

        metrics = compute_case_metrics(
            should_inject=should_inject,
            ranked_ids=ranked_ids,
            injection_gate=injection_gate,
            ranked_scores=ranked_scores,
            k=k,
        )
        prompt_results.append({
            "prompt": prompt_text,
            "should_inject": should_inject,
            "all_ranked_ids": ranked_ids,
            "metrics": metrics,
        })

    return {
        "case_id": case["id"],
        "prompt_results": prompt_results,
    }


def _aggregate(case_results: list[dict], k: int) -> dict:
    """Compute aggregate metrics across all prompt results. Returns None for each metric if no labeled cases."""
    all_metrics = [
        pr["metrics"]
        for cr in case_results
        for pr in cr.get("prompt_results", [])
    ]
    labeled = [m for m in all_metrics if m["recall"] is not None]

    if not labeled:
        return {
            "recall": None, "precision": None, "f1": None,
            "mrr": None, "false_negative_rate": None, "injection_rate": None,
            "case_count": len(case_results),
            "labeled_prompt_count": 0,
        }

    def _avg(key):
        vals = [m[key] for m in labeled if m[key] is not None]
        return sum(vals) / len(vals) if vals else None

    fired = [m for m in all_metrics if m["injection_fired"]]
    return {
        "recall": _avg("recall"),
        "precision": _avg("precision"),
        "f1": _avg("f1"),
        "mrr": _avg("mrr"),
        "false_negative_rate": _avg("false_negative_rate"),
        "injection_rate": len(fired) / len(all_metrics) if all_metrics else None,
        "case_count": len(case_results),
        "labeled_prompt_count": len(labeled),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval/test_runner.py -v
```
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/runner.py tests/test_eval/test_runner.py
git commit -m "feat(eval): runner — per-case seeding, retrieval, and metric aggregation"
```

---

## Task 5: Report generator

**Files:**
- Create: `eval/report.py`
- Create: `tests/test_eval/test_report.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval/test_report.py
import json
from pathlib import Path
from datetime import datetime
from eval.report import format_report, write_results, load_previous_run


def _make_aggregate(recall=0.81, precision=0.74):
    return {
        "recall": recall, "precision": precision, "f1": 0.77, "mrr": 0.83,
        "false_negative_rate": 0.19, "injection_rate": 0.91,
        "case_count": 42, "labeled_prompt_count": 42,
    }


def _make_case_results():
    return [
        {"case_id": "golden-007", "prompt_results": [
            {"prompt": "how do we handle auth tokens?", "should_inject": ["m0"], "all_ranked_ids": [], "metrics": {"recall": 0.0, "precision": 0.0, "f1": 0.0, "mrr": 0.0, "false_negative_rate": 1.0, "injection_fired": False}}
        ]},
    ]


def test_format_report_contains_metrics(tmp_path):
    agg = _make_aggregate()
    report = format_report(agg, _make_case_results(), k=8, corpus_label="golden", previous=None)
    assert "Recall@8" in report
    assert "0.81" in report
    assert "Precision@8" in report


def test_format_report_shows_regression(tmp_path):
    agg = _make_aggregate(recall=0.75)
    prev = _make_aggregate(recall=0.81)
    report = format_report(agg, _make_case_results(), k=8, corpus_label="golden", previous=prev)
    assert "▼" in report  # regression arrow


def test_format_report_suppresses_noise():
    agg = _make_aggregate(recall=0.811)
    prev = _make_aggregate(recall=0.810)  # delta=0.001, below 0.01 threshold
    report = format_report(agg, _make_case_results(), k=8, corpus_label="golden", previous=prev)
    assert "→" in report  # no-change arrow for recall


def test_format_report_shows_worst_cases():
    agg = _make_aggregate()
    report = format_report(agg, _make_case_results(), k=8, corpus_label="golden", previous=None)
    assert "golden-007" in report


def test_write_results_creates_files(tmp_path):
    agg = _make_aggregate()
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    write_results(agg, _make_case_results(), results_dir=results_dir, corpus_label="golden", k=8)
    assert (results_dir / "latest.json").exists()
    assert (results_dir / "history.jsonl").exists()


def test_write_results_appends_history(tmp_path):
    agg = _make_aggregate()
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    write_results(agg, [], results_dir=results_dir, corpus_label="golden", k=8)
    write_results(agg, [], results_dir=results_dir, corpus_label="golden", k=8)
    lines = (results_dir / "history.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


def test_load_previous_run_returns_none_when_no_history(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    assert load_previous_run(results_dir) is None


def test_load_previous_run_returns_last_entry(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    history = results_dir / "history.jsonl"
    history.write_text(
        json.dumps({"aggregate": {"recall": 0.75}, "corpus_label": "golden"}) + "\n" +
        json.dumps({"aggregate": {"recall": 0.80}, "corpus_label": "golden"}) + "\n"
    )
    prev = load_previous_run(results_dir, corpus_label="golden")
    assert prev["aggregate"]["recall"] == 0.80
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eval/test_report.py -v
```
Expected: `ModuleNotFoundError: No module named 'eval.report'`

- [ ] **Step 3: Implement the report module**

`eval/report.py`:
```python
"""Format eval reports and write results files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_NOISE_THRESHOLD = 0.01  # deltas smaller than this are shown as "→"
_BAR_WIDTH = 10


def _bar(value: float | None) -> str:
    if value is None:
        return "?" * _BAR_WIDTH
    filled = round(value * _BAR_WIDTH)
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _arrow(current: float | None, previous: float | None, higher_is_better: bool = True) -> str:
    if current is None or previous is None:
        return ""
    delta = current - previous
    if abs(delta) < _NOISE_THRESHOLD:
        return "  →"
    if (delta > 0) == higher_is_better:
        return f"  ▲ +{abs(delta):.2f}"
    return f"  ▼ -{abs(delta):.2f} vs last run  ← regression"


def format_report(
    aggregate: dict,
    case_results: list[dict],
    k: int,
    corpus_label: str,
    previous: dict | None,
) -> str:
    """Format the eval report as a human-readable string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    n = aggregate.get("case_count", 0)
    lines = [
        f"═══ Ormah Eval Report ══════════════════════",
        f"Corpus: {corpus_label} ({n} cases) | {now}",
        "",
    ]

    prev_agg = previous.get("aggregate") if previous else None

    metrics = [
        ("Recall", "recall", True),
        ("Precision", "precision", True),
        ("F1", "f1", True),
        ("MRR", "mrr", True),
        ("Injection rate", "injection_rate", True),
        ("False neg rate", "false_negative_rate", False),
    ]

    for label, key, higher_is_better in metrics:
        val = aggregate.get(key)
        prev_val = prev_agg.get(key) if prev_agg else None
        display_key = f"{label}@{k}" if key in ("recall", "precision", "f1") else label
        val_str = f"{val:.2f}" if val is not None else "N/A"
        bar = _bar(val)
        arrow = _arrow(val, prev_val, higher_is_better)
        lines.append(f"  {display_key:<18} {val_str}  {bar}{arrow}")

    # Worst cases (lowest recall)
    worst = _worst_cases(case_results, n=5)
    if worst:
        lines.append("")
        lines.append("Worst cases:")
        for case_id, recall, prompt in worst:
            recall_str = f"{recall:.2f}" if recall is not None else "N/A"
            lines.append(f"  {case_id:<20} recall={recall_str}  \"{prompt[:60]}\"")

    return "\n".join(lines)


def _worst_cases(case_results: list[dict], n: int) -> list[tuple]:
    """Return n worst (case_id, avg_recall, first_prompt) sorted by recall ascending."""
    rows = []
    for cr in case_results:
        recalls = [
            pr["metrics"]["recall"]
            for pr in cr.get("prompt_results", [])
            if pr["metrics"]["recall"] is not None
        ]
        if not recalls:
            continue
        avg_recall = sum(recalls) / len(recalls)
        first_prompt = cr["prompt_results"][0]["prompt"] if cr["prompt_results"] else ""
        rows.append((cr["case_id"], avg_recall, first_prompt))
    rows.sort(key=lambda r: r[1])
    return rows[:n]


def write_results(
    aggregate: dict,
    case_results: list[dict],
    results_dir: Path,
    corpus_label: str,
    k: int,
) -> None:
    """Write latest.json and append to history.jsonl."""
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    entry = {
        "timestamp": ts,
        "corpus_label": corpus_label,
        "k": k,
        "aggregate": aggregate,
    }
    (results_dir / "latest.json").write_text(json.dumps(entry, indent=2))
    with open(results_dir / "history.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_previous_run(results_dir: Path, corpus_label: str = "golden") -> dict | None:
    """Return the last history entry for corpus_label, or None if no history exists."""
    history_file = results_dir / "history.jsonl"
    if not history_file.exists():
        return None
    last = None
    for line in history_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        if entry.get("corpus_label") == corpus_label:
            last = entry
    return last
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval/test_report.py -v
```
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/report.py tests/test_eval/test_report.py
git commit -m "feat(eval): report generator with regression detection"
```

---

## Task 6: Judge (labeling workflow)

**Files:**
- Create: `eval/judge.py`
- Create: `tests/test_eval/test_judge.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval/test_judge.py
import json
import pytest
from pathlib import Path
from eval.judge import export_for_labeling, import_labels


def _write_jsonl(path, lines):
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")


@pytest.fixture
def corpus_dir(tmp_path):
    golden = tmp_path / "golden"
    golden.mkdir()
    return tmp_path


def _make_case(case_id, labeled=True):
    should_inject = ["mem-0"] if labeled else []
    return {
        "id": case_id,
        "memories": [
            {"node_id": "mem-0", "title": "T", "content": "C", "type": "fact", "tier": "working"}
        ],
        "prompts": [
            {"text": "some prompt", "expected": {"should_inject": should_inject, "should_not_inject": []}}
        ],
    }


def test_export_skips_labeled_cases(corpus_dir):
    _write_jsonl(corpus_dir / "golden" / "golden.jsonl", [_make_case("labeled-001", labeled=True)])
    pending = export_for_labeling(corpus_dir)
    assert pending == []


def test_export_includes_unlabeled_cases(corpus_dir):
    _write_jsonl(corpus_dir / "golden" / "golden.jsonl", [_make_case("unlabeled-001", labeled=False)])
    pending = export_for_labeling(corpus_dir)
    assert len(pending) == 1
    assert pending[0]["case_id"] == "unlabeled-001"
    assert pending[0]["memory_id"] == "mem-0"
    assert "prompt_text" in pending[0]
    assert "memory_title" in pending[0]
    assert "memory_content" in pending[0]


def test_export_writes_pending_labels_file(corpus_dir):
    _write_jsonl(corpus_dir / "golden" / "golden.jsonl", [_make_case("u-001", labeled=False)])
    export_for_labeling(corpus_dir, write=True)
    pending_file = corpus_dir / "pending_labels.jsonl"
    assert pending_file.exists()
    lines = [json.loads(l) for l in pending_file.read_text().strip().splitlines()]
    assert len(lines) == 1


def test_import_labels_updates_corpus(corpus_dir):
    case = _make_case("u-001", labeled=False)
    case["memories"][0]["node_id"] = "u-001-mem-0"
    case["prompts"][0]["expected"]["should_inject"] = []
    golden_file = corpus_dir / "golden" / "golden.jsonl"
    _write_jsonl(golden_file, [case])

    labels = [
        {"case_id": "u-001", "prompt_idx": 0, "memory_id": "u-001-mem-0", "score": 2, "reason": "relevant"}
    ]
    labels_file = corpus_dir / "labels.jsonl"
    _write_jsonl(labels_file, labels)

    import_labels(corpus_dir, labels_file)

    updated = [json.loads(l) for l in golden_file.read_text().strip().splitlines()]
    assert "u-001-mem-0" in updated[0]["prompts"][0]["expected"]["should_inject"]


def test_import_labels_score_0_goes_to_should_not_inject(corpus_dir):
    case = _make_case("u-002", labeled=False)
    case["memories"][0]["node_id"] = "u-002-mem-0"
    case["prompts"][0]["expected"]["should_inject"] = []
    golden_file = corpus_dir / "golden" / "golden.jsonl"
    _write_jsonl(golden_file, [case])

    labels = [
        {"case_id": "u-002", "prompt_idx": 0, "memory_id": "u-002-mem-0", "score": 0, "reason": "irrelevant"}
    ]
    labels_file = corpus_dir / "labels.jsonl"
    _write_jsonl(labels_file, labels)

    import_labels(corpus_dir, labels_file)
    updated = [json.loads(l) for l in golden_file.read_text().strip().splitlines()]
    assert "u-002-mem-0" in updated[0]["prompts"][0]["expected"]["should_not_inject"]


def test_import_labels_score_1_not_added_to_either(corpus_dir):
    case = _make_case("u-003", labeled=False)
    case["memories"][0]["node_id"] = "u-003-mem-0"
    case["prompts"][0]["expected"]["should_inject"] = []
    golden_file = corpus_dir / "golden" / "golden.jsonl"
    _write_jsonl(golden_file, [case])

    labels = [
        {"case_id": "u-003", "prompt_idx": 0, "memory_id": "u-003-mem-0", "score": 1, "reason": "borderline"}
    ]
    labels_file = corpus_dir / "labels.jsonl"
    _write_jsonl(labels_file, labels)

    import_labels(corpus_dir, labels_file)
    updated = [json.loads(l) for l in golden_file.read_text().strip().splitlines()]
    assert "u-003-mem-0" not in updated[0]["prompts"][0]["expected"]["should_inject"]
    assert "u-003-mem-0" not in updated[0]["prompts"][0]["expected"]["should_not_inject"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eval/test_judge.py -v
```
Expected: `ModuleNotFoundError: No module named 'eval.judge'`

- [ ] **Step 3: Implement the judge module**

`eval/judge.py`:
```python
"""Labeling workflow: export unlabeled pairs for Claude Code, import scored labels."""

from __future__ import annotations

import json
from pathlib import Path

from eval.corpus import load_corpus


def export_for_labeling(corpus_dir: Path, write: bool = False) -> list[dict]:
    """Find all unlabeled (prompt, memory) pairs across all corpus files.

    A case is unlabeled if ALL its prompts have empty should_inject AND
    empty should_not_inject. Returns a list of pending label entries.

    If write=True, also writes corpus_dir/pending_labels.jsonl.
    """
    pending: list[dict] = []
    corpus_files = list((corpus_dir / "golden").glob("*.jsonl"))
    if (corpus_dir / "synthetic").exists():
        corpus_files += list((corpus_dir / "synthetic").glob("*.jsonl"))

    for corpus_file in corpus_files:
        try:
            cases = load_corpus(corpus_file)
        except Exception:
            continue

        for case in cases:
            for prompt_idx, prompt_obj in enumerate(case.get("prompts", [])):
                exp = prompt_obj.get("expected", {})
                if exp.get("should_inject") or exp.get("should_not_inject"):
                    continue  # already labeled
                for mem in case.get("memories", []):
                    pending.append({
                        "case_id": case["id"],
                        "prompt_idx": prompt_idx,
                        "memory_id": mem["node_id"],
                        "prompt_text": prompt_obj["text"],
                        "memory_title": mem.get("title", ""),
                        "memory_content": mem.get("content", ""),
                    })

    if write:
        out = corpus_dir / "pending_labels.jsonl"
        out.write_text("\n".join(json.dumps(p) for p in pending) + "\n" if pending else "")

    return pending


def import_labels(corpus_dir: Path, labels_file: Path) -> int:
    """Read labels_file and update corpus files with scored labels.

    Score 2 → should_inject, Score 0 → should_not_inject, Score 1 → ignored (ambiguous).
    Returns number of labels applied.
    """
    labels = []
    for line in labels_file.read_text().splitlines():
        line = line.strip()
        if line:
            labels.append(json.loads(line))

    # Build index: case_id → [label]
    by_case: dict[str, list[dict]] = {}
    for label in labels:
        by_case.setdefault(label["case_id"], []).append(label)

    applied = 0
    corpus_files = list((corpus_dir / "golden").glob("*.jsonl"))
    if (corpus_dir / "synthetic").exists():
        corpus_files += list((corpus_dir / "synthetic").glob("*.jsonl"))

    for corpus_file in corpus_files:
        try:
            cases = load_corpus(corpus_file)
        except Exception:
            continue

        modified = False
        for case in cases:
            case_labels = by_case.get(case["id"], [])
            if not case_labels:
                continue
            for label in case_labels:
                pidx = label["prompt_idx"]
                mid = label["memory_id"]
                score = label["score"]
                if pidx >= len(case.get("prompts", [])):
                    continue
                prompt_obj = case["prompts"][pidx]
                exp = prompt_obj.setdefault("expected", {"should_inject": [], "should_not_inject": []})
                if score == 2 and mid not in exp["should_inject"]:
                    exp["should_inject"].append(mid)
                    applied += 1
                    modified = True
                elif score == 0 and mid not in exp["should_not_inject"]:
                    exp["should_not_inject"].append(mid)
                    applied += 1
                    modified = True
                # score == 1 → ambiguous, skip

        if modified:
            corpus_file.write_text(
                "\n".join(json.dumps(c) for c in cases) + "\n"
            )

    return applied
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval/test_judge.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/judge.py tests/test_eval/test_judge.py
git commit -m "feat(eval): labeling workflow — export-for-labeling and import-labels"
```

---

## Task 7: Session capture

**Files:**
- Create: `eval/session.py`
- Create: `tests/test_eval/test_session.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval/test_session.py
import json
import pytest
from pathlib import Path
from eval.session import capture_session


def _make_transcript(turns: int) -> str:
    lines = []
    for i in range(turns):
        lines.append(json.dumps({"type": "user", "message": {"content": f"User prompt {i}"}}))
        lines.append(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Response {i}"}]}}))
    return "\n".join(lines) + "\n"


def test_capture_session_copies_file(tmp_path):
    src = tmp_path / "session.jsonl"
    src.write_text(_make_transcript(3))
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    entry = capture_session(src, sessions_dir)
    assert any(sessions_dir.glob("*.jsonl"))


def test_capture_session_extracts_prompts(tmp_path):
    src = tmp_path / "session.jsonl"
    src.write_text(_make_transcript(3))
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    entry = capture_session(src, sessions_dir)
    assert len(entry["prompts"]) == 3
    assert entry["prompts"][0]["text"] == "User prompt 0"


def test_capture_session_empty_labels(tmp_path):
    src = tmp_path / "session.jsonl"
    src.write_text(_make_transcript(2))
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    entry = capture_session(src, sessions_dir)
    for prompt_obj in entry["prompts"]:
        assert prompt_obj["expected"]["should_inject"] == []
        assert prompt_obj["expected"]["should_not_inject"] == []


def test_capture_session_no_memories(tmp_path):
    src = tmp_path / "session.jsonl"
    src.write_text(_make_transcript(2))
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    entry = capture_session(src, sessions_dir)
    assert entry["memories"] == []


def test_capture_session_unique_id(tmp_path):
    src = tmp_path / "session.jsonl"
    src.write_text(_make_transcript(2))
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    entry = capture_session(src, sessions_dir)
    assert entry["id"].startswith("session-")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eval/test_session.py -v
```
Expected: `ModuleNotFoundError: No module named 'eval.session'`

- [ ] **Step 3: Implement session capture**

`eval/session.py`:
```python
"""Capture and parse Claude Code session transcripts into unlabeled corpus entries."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path


def capture_session(transcript_path: Path, sessions_dir: Path) -> dict:
    """Copy a Claude Code JSONL transcript and create an unlabeled corpus entry.

    Returns the corpus entry dict (caller should save it to sessions/*.jsonl).
    Session cases have no embedded memories — they run against the full corpus.
    """
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Copy the transcript file
    dest = sessions_dir / transcript_path.name
    shutil.copy2(transcript_path, dest)

    # Parse user turns
    prompts = []
    for line in transcript_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "user":
            continue
        msg = obj.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            # Extract text parts
            text = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        else:
            text = str(content)
        text = text.strip()
        if text:
            prompts.append({
                "text": text,
                "expected": {"should_inject": [], "should_not_inject": []},
            })

    session_id = f"session-{uuid.uuid4().hex[:8]}"
    return {
        "id": session_id,
        "memories": [],  # session cases use the full corpus as their memory pool
        "prompts": prompts,
        "source_file": str(dest),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval/test_session.py -v
```
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/session.py tests/test_eval/test_session.py
git commit -m "feat(eval): session capture — parse Claude Code transcripts into corpus entries"
```

---

## Task 8: CLI wiring

**Files:**
- Create: `eval/cli.py`
- Modify: `src/ormah/cli.py`
- Create: `tests/test_eval/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval/test_cli.py
import sys
import io
import pytest
from unittest.mock import patch


def _run_ormah(args, monkeypatch):
    monkeypatch.setattr("sys.argv", ["ormah"] + args)
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)
    from ormah.cli import main
    try:
        main()
    except SystemExit:
        pass
    return stdout.getvalue()


def test_eval_subcommand_exists(monkeypatch):
    out = _run_ormah(["eval", "--help"], monkeypatch)
    assert "eval" in out or "run" in out  # help printed without error
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_eval/test_cli.py -v
```
Expected: `SystemExit` or error — `eval` subcommand doesn't exist yet.

- [ ] **Step 3: Implement eval/cli.py**

`eval/cli.py`:
```python
"""CLI handlers for ormah eval commands."""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL_DIR = Path(__file__).parent
_CORPUS_DIR = _EVAL_DIR / "corpus"
_RESULTS_DIR = _EVAL_DIR / "results"
_EVAL_DB_DIR = _EVAL_DIR / "eval_db"


def _make_engine():
    """Create a MemoryEngine pointing at the isolated eval DB."""
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (_EVAL_DB_DIR / "nodes").mkdir(parents=True, exist_ok=True)
    settings = Settings(memory_dir=_EVAL_DB_DIR)
    engine = MemoryEngine(settings)
    engine.startup()
    return engine


def cmd_eval_run(args):
    from eval.corpus import load_corpus, CorpusError
    from eval.runner import run_eval
    from eval.report import format_report, write_results, load_previous_run

    corpus_label = args.corpus  # "golden", "synthetic", or "all"
    k = args.k

    # Determine which corpus files to load
    files = _corpus_files_for_label(corpus_label)
    cases = []
    for f in files:
        try:
            cases.extend(load_corpus(f))
        except CorpusError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if not cases:
        print(f"Warning: no cases found in corpus '{corpus_label}'", file=sys.stderr)
        sys.exit(0)

    engine = _make_engine()
    try:
        result = run_eval(cases, engine, k=k)
    finally:
        engine.shutdown()

    previous = load_previous_run(_RESULTS_DIR, corpus_label=corpus_label)
    report = format_report(result.aggregate, result.case_results, k=k, corpus_label=corpus_label, previous=previous)
    print(report)
    write_results(result.aggregate, result.case_results, results_dir=_RESULTS_DIR, corpus_label=corpus_label, k=k)

    # CI gates
    exit_code = 0
    if args.fail_below:
        exit_code = max(exit_code, _check_fail_below(result.aggregate, args.fail_below))
    if args.fail_on_regression and previous:
        exit_code = max(exit_code, _check_regression(result.aggregate, previous["aggregate"], args.fail_on_regression))

    sys.exit(exit_code)


def cmd_eval_build_corpus(args):
    """Seed eval DB from corpus files (debugging/inspection only)."""
    from eval.corpus import load_corpus, CorpusError
    from eval.seeder import seed_case

    engine = _make_engine()
    total = 0
    try:
        for f in _corpus_files_for_label("all"):
            try:
                cases = load_corpus(f)
            except CorpusError:
                continue
            for case in cases:
                seed_case(engine, case)
                total += 1
    finally:
        engine.shutdown()
    print(f"Seeded {total} cases into eval DB at {_EVAL_DB_DIR}")


def cmd_eval_export_for_labeling(args):
    from eval.judge import export_for_labeling

    pending = export_for_labeling(_CORPUS_DIR, write=True)
    print(f"Exported {len(pending)} unlabeled pairs to {_CORPUS_DIR / 'pending_labels.jsonl'}")


def cmd_eval_import_labels(args):
    from eval.judge import import_labels

    labels_file = _CORPUS_DIR / "labels.jsonl"
    if not labels_file.exists():
        print(f"Error: {labels_file} not found. Run export-for-labeling first.", file=sys.stderr)
        sys.exit(1)
    n = import_labels(_CORPUS_DIR, labels_file)
    print(f"Applied {n} labels to corpus files.")


def cmd_eval_capture_session(args):
    from eval.session import capture_session
    import json

    sessions_dir = _CORPUS_DIR / "sessions"
    entry = capture_session(Path(args.path), sessions_dir)
    out_file = sessions_dir / f"{entry['id']}.jsonl"
    out_file.write_text(json.dumps(entry) + "\n")
    print(f"Captured session → {out_file} ({len(entry['prompts'])} prompts)")


def _corpus_files_for_label(label: str) -> list[Path]:
    if label == "golden":
        return list((_CORPUS_DIR / "golden").glob("*.jsonl"))
    if label == "synthetic":
        return list((_CORPUS_DIR / "synthetic").glob("*.jsonl")) if (_CORPUS_DIR / "synthetic").exists() else []
    if label == "sessions":
        return list((_CORPUS_DIR / "sessions").glob("*.jsonl"))
    # "all"
    files = list((_CORPUS_DIR / "golden").glob("*.jsonl"))
    if (_CORPUS_DIR / "synthetic").exists():
        files += list((_CORPUS_DIR / "synthetic").glob("*.jsonl"))
    files += list((_CORPUS_DIR / "sessions").glob("*.jsonl"))
    return files


def _check_fail_below(aggregate: dict, spec: str) -> int:
    """Parse 'recall@8=0.70,precision@8=0.60' and check thresholds. Returns 1 if any fails."""
    failed = False
    for part in spec.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        metric_raw, threshold_str = part.split("=", 1)
        metric_key = metric_raw.split("@")[0].replace("-", "_").lower()
        # map "false_neg_rate" etc
        key_map = {
            "recall": "recall", "precision": "precision", "f1": "f1",
            "mrr": "mrr", "injection_rate": "injection_rate",
            "false_negative_rate": "false_negative_rate",
        }
        key = key_map.get(metric_key, metric_key)
        val = aggregate.get(key)
        threshold = float(threshold_str)
        if val is None or val < threshold:
            val_str = f"{val:.3f}" if val is not None else "N/A"
            print(f"FAIL: {metric_raw}={val_str} < {threshold}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


def _check_regression(current: dict, previous: dict, spec: str) -> int:
    """Parse 'delta=0.05' and fail if any metric drops more than delta. Returns 1 if regression."""
    delta = float(spec.split("=", 1)[1]) if "=" in spec else 0.05
    failed = False
    for key in ("recall", "precision", "f1", "mrr"):
        cur = current.get(key)
        prev = previous.get(key)
        if cur is None or prev is None:
            continue
        if (prev - cur) > delta:
            print(f"REGRESSION: {key} dropped {prev:.3f} → {cur:.3f} (delta={prev-cur:.3f} > {delta})", file=sys.stderr)
            failed = True
    return 1 if failed else 0
```

- [ ] **Step 4: Wire into src/ormah/cli.py**

Add the `eval` subparser to `src/ormah/cli.py`. After the `# --- whisper ---` block, add:

```python
    # --- eval ---
    eval_p = sub.add_parser("eval", help="Whisper/recall evaluation system")
    eval_sub = eval_p.add_subparsers(dest="eval_cmd", required=True)

    eval_run = eval_sub.add_parser("run", help="Run eval suite and print report")
    eval_run.add_argument("--corpus", default="golden", choices=["golden", "synthetic", "sessions", "all"],
                          help="Corpus to evaluate (default: golden)")
    eval_run.add_argument("--k", type=int, default=8, help="Top-k for metrics (default: 8)")
    eval_run.add_argument("--fail-below", default=None,
                          help="Fail if metrics below threshold, e.g. recall@8=0.70,precision@8=0.60")
    eval_run.add_argument("--fail-on-regression", default=None,
                          help="Fail if metric drops more than delta vs last run, e.g. delta=0.05")
    eval_run.set_defaults(func=_cmd_eval_run)

    eval_build = eval_sub.add_parser("build-corpus", help="Seed eval DB from corpus files (debug)")
    eval_build.set_defaults(func=_cmd_eval_build_corpus)

    eval_export = eval_sub.add_parser("export-for-labeling", help="Export unlabeled pairs to pending_labels.jsonl")
    eval_export.set_defaults(func=_cmd_eval_export_for_labeling)

    eval_import = eval_sub.add_parser("import-labels", help="Merge labels.jsonl into corpus ground truth")
    eval_import.set_defaults(func=_cmd_eval_import_labels)

    eval_capture = eval_sub.add_parser("capture-session", help="Copy session transcript into corpus/sessions/")
    eval_capture.add_argument("path", help="Path to Claude Code JSONL transcript")
    eval_capture.set_defaults(func=_cmd_eval_capture_session)
```

And add the command handler imports near the top of `main()`:

```python
    from eval.cli import (
        cmd_eval_run as _cmd_eval_run,
        cmd_eval_build_corpus as _cmd_eval_build_corpus,
        cmd_eval_export_for_labeling as _cmd_eval_export_for_labeling,
        cmd_eval_import_labels as _cmd_eval_import_labels,
        cmd_eval_capture_session as _cmd_eval_capture_session,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval/test_cli.py -v
```
Expected: `test_eval_subcommand_exists` passes.

- [ ] **Step 6: Smoke test the CLI manually**

```bash
cd /home/r2205/Projects/ormah/.worktrees/eval-system
uv run ormah eval --help
uv run ormah eval run --help
```
Expected: help text printed, `run`, `build-corpus`, `export-for-labeling`, `import-labels`, `capture-session` all listed.

- [ ] **Step 7: Commit**

```bash
git add eval/cli.py src/ormah/cli.py tests/test_eval/test_cli.py
git commit -m "feat(eval): wire ormah eval * CLI commands"
```

---

## Task 9: Write initial golden corpus

**Files:**
- Create: `eval/corpus/golden/golden.jsonl`

This is the regression canary. Write 10 cases covering different retrieval scenarios: direct keyword match, semantic match (query ≠ keywords in memory), cross-type recall, negative cases (noise memories that should NOT surface), and identity queries.

- [ ] **Step 1: Write the golden corpus file**

Create `eval/corpus/golden/golden.jsonl`. Each line is one JSON case. Write exactly these 10 cases (copy verbatim):

```
{"id": "golden-001", "memories": [{"node_id": "golden-001-mem-0", "title": "Ormah uses SQLite with FTS5 and vector search", "content": "The index layer uses SQLite with FTS5 for full-text search and sqlite-vec for vector similarity, fused via Reciprocal Rank Fusion (RRF).", "type": "fact", "tier": "working", "tags": ["architecture", "search"], "space": "ormah"}, {"node_id": "golden-001-mem-1", "title": "Ormah memory tiers: core, working, archival", "content": "Ormah has three memory tiers. Core memories are always loaded (cap 50). Working memories decay after ~14 days. Archival is for historical reference.", "type": "fact", "tier": "working", "tags": ["architecture"], "space": "ormah"}, {"node_id": "golden-001-mem-2", "title": "Ormah server runs on port 8787", "content": "The FastAPI server runs on port 8787 by default, configurable via ORMAH_PORT.", "type": "fact", "tier": "working", "tags": ["config"], "space": "ormah"}], "prompts": [{"text": "how does search work in ormah?", "expected": {"should_inject": ["golden-001-mem-0"], "should_not_inject": ["golden-001-mem-2"]}, "notes": "Direct semantic match — search architecture should surface, port config should not"}]}
{"id": "golden-002", "memories": [{"node_id": "golden-002-mem-0", "title": "User prefers concise responses without trailing summaries", "content": "Rishi does not want summaries at the end of responses. He finds them redundant and prefers to read diffs directly.", "type": "preference", "tier": "core", "tags": ["collaboration", "about_self"], "space": null}, {"node_id": "golden-002-mem-1", "title": "User's home GPU is RTX 3060 12GB", "content": "GPU: ZOTAC Gaming RTX 3060 12GB OC. Used for local ML model inference.", "type": "fact", "tier": "core", "tags": ["hardware", "about_self"], "space": null}, {"node_id": "golden-002-mem-2", "title": "SQLite uses WAL mode for concurrent reads", "content": "Ormah enables WAL mode on SQLite for better read concurrency during background jobs.", "type": "fact", "tier": "working", "tags": ["database"], "space": "ormah"}], "prompts": [{"text": "don't summarize at the end please", "expected": {"should_inject": ["golden-002-mem-0"], "should_not_inject": ["golden-002-mem-2"]}, "notes": "Identity/preference recall — phrasing differs from memory title but semantically matches"}]}
{"id": "golden-003", "memories": [{"node_id": "golden-003-mem-0", "title": "Whisper pipeline has 8 stages", "content": "The whisper pipeline: short prompt check, topic-shift detection, PromptClassifier, hybrid search, min_score filter (0.45), cross-encoder reranker, injection gate (0.55), identity split/cap, inject.", "type": "fact", "tier": "working", "tags": ["whisper", "architecture"], "space": "ormah"}, {"node_id": "golden-003-mem-1", "title": "Cross-encoder uses sigmoid-blended scoring", "content": "The reranker blends cross-encoder score with embedding score: blended = 0.4 * sigmoid(ce_score) + 0.6 * emb_score.", "type": "fact", "tier": "working", "tags": ["reranker", "whisper"], "space": "ormah"}, {"node_id": "golden-003-mem-2", "title": "Background jobs run via APScheduler", "content": "APScheduler manages all background jobs: auto-linker, conflict detector, duplicate merger, importance scorer, decay manager, consolidator, hippocampus, session watcher.", "type": "fact", "tier": "working", "tags": ["background", "architecture"], "space": "ormah"}], "prompts": [{"text": "what are the stages in the whisper injection pipeline?", "expected": {"should_inject": ["golden-003-mem-0"], "should_not_inject": ["golden-003-mem-2"]}, "notes": "Multi-fact retrieval — both whisper memories relevant, background jobs not relevant"}]}
{"id": "golden-004", "memories": [{"node_id": "golden-004-mem-0", "title": "Decision: use BAAI/bge-base-en-v1.5 for embeddings", "content": "Chose bge-base-en-v1.5 over nomic-embed-text because it requires no task prefixes, making it simpler to use in production.", "type": "decision", "tier": "working", "tags": ["embeddings", "decision"], "space": "ormah"}, {"node_id": "golden-004-mem-1", "title": "Embedding dimension is 768", "content": "BAAI/bge-base-en-v1.5 produces 768-dimensional embeddings stored in sqlite-vec.", "type": "fact", "tier": "working", "tags": ["embeddings"], "space": "ormah"}, {"node_id": "golden-004-mem-2", "title": "Ormah MCP exposes 6 agent-facing tools", "content": "MCP tools: remember, recall, get_context, get_self, mark_outdated, run_maintenance.", "type": "fact", "tier": "working", "tags": ["mcp"], "space": "ormah"}, {"node_id": "golden-004-mem-3", "title": "Vector search uses cosine similarity", "content": "sqlite-vec performs approximate nearest-neighbor search using cosine similarity on normalized 768-dim vectors.", "type": "fact", "tier": "working", "tags": ["embeddings", "search"], "space": "ormah"}], "prompts": [{"text": "why did we choose this embedding model?", "expected": {"should_inject": ["golden-004-mem-0"], "should_not_inject": ["golden-004-mem-2"]}, "notes": "Decision recall — phrasing 'why did we choose' should surface the decision memory"}]}
{"id": "golden-005", "memories": [{"node_id": "golden-005-mem-0", "title": "Ormah file store uses markdown files", "content": "Each memory node is persisted as a markdown file in memory/nodes/. The filename is the node UUID.", "type": "fact", "tier": "working", "tags": ["storage"], "space": "ormah"}, {"node_id": "golden-005-mem-1", "title": "Spreading activation propagates through graph edges", "content": "After hybrid search, ormah activates neighbors of seed results via graph edges. Formula: score = seed_score * edge_weight * type_factor * decay. Single-hop only.", "type": "fact", "tier": "working", "tags": ["search", "graph"], "space": "ormah"}, {"node_id": "golden-005-mem-2", "title": "Old architecture note from 2024", "content": "In the original prototype, memories were stored in a flat JSON file. This was replaced by markdown files for human readability.", "type": "fact", "tier": "archival", "tags": ["history"], "space": "ormah"}], "prompts": [{"text": "how does graph activation work?", "expected": {"should_inject": ["golden-005-mem-1"], "should_not_inject": ["golden-005-mem-2"]}, "notes": "Archival tier should not surface (test tier filtering); spreading activation memory should"}]}
{"id": "golden-006", "memories": [{"node_id": "golden-006-mem-0", "title": "Jentic Workflow Miner Agent is Rishi's keystone product", "content": "At Jentic, Rishi built the Workflow Miner Agent — autonomously discovers automatable business processes and captures them in Arazzo format.", "type": "fact", "tier": "core", "tags": ["career", "about_self"], "space": null}, {"node_id": "golden-006-mem-1", "title": "Ormah uses APScheduler for background jobs", "content": "Background jobs are managed by APScheduler. Jobs include: auto-linker, decay manager, duplicate merger.", "type": "fact", "tier": "working", "tags": ["background"], "space": "ormah"}, {"node_id": "golden-006-mem-2", "title": "Ormah project created by Rishi as side project", "content": "Rishi created Ormah as a side project. It is listed on his CV as 'a nature-inspired persistent memory system for AI agents'.", "type": "fact", "tier": "core", "tags": ["about_self", "ormah"], "space": null}], "prompts": [{"text": "what am I working on professionally right now?", "expected": {"should_inject": ["golden-006-mem-0"], "should_not_inject": ["golden-006-mem-1"]}, "notes": "Identity query with space=null — cross-space memory should surface over project-specific one"}]}
{"id": "golden-007", "memories": [{"node_id": "golden-007-mem-0", "title": "Auth tokens stored as httpOnly cookies", "content": "JWT auth tokens are stored in httpOnly cookies with 24-hour expiry. Refresh tokens have 30-day expiry.", "type": "decision", "tier": "working", "tags": ["auth", "security"], "space": "webapp"}, {"node_id": "golden-007-mem-1", "title": "CORS configured for localhost:3000 in dev", "content": "Development CORS allows localhost:3000. Production CORS restricts to the verified domain.", "type": "fact", "tier": "working", "tags": ["config", "security"], "space": "webapp"}, {"node_id": "golden-007-mem-2", "title": "Ormah webhook endpoint for memory ingestion", "content": "POST /ingest accepts conversation content and extracts memories via LLM.", "type": "fact", "tier": "working", "tags": ["api"], "space": "ormah"}], "prompts": [{"text": "how are auth tokens handled?", "expected": {"should_inject": ["golden-007-mem-0"], "should_not_inject": ["golden-007-mem-2"]}, "notes": "Space isolation — webapp auth memory should score higher than ormah-space memory"}]}
{"id": "golden-008", "memories": [{"node_id": "golden-008-mem-0", "title": "Decision: keep whisper pipeline synchronous", "content": "We decided to keep the whisper inject pipeline synchronous (not async) to ensure memories are injected before the prompt reaches Claude. Async would risk a race condition.", "type": "decision", "tier": "working", "tags": ["whisper", "architecture", "decision"], "space": "ormah"}, {"node_id": "golden-008-mem-1", "title": "UserPromptSubmit hook has 10s timeout", "content": "The Claude Code UserPromptSubmit hook that runs whisper inject has a 10-second timeout. Whisper must complete within this window.", "type": "fact", "tier": "working", "tags": ["hooks", "whisper"], "space": "ormah"}, {"node_id": "golden-008-mem-2", "title": "Python version requirement: 3.11+", "content": "Ormah requires Python 3.11 or higher.", "type": "fact", "tier": "working", "tags": ["requirements"], "space": "ormah"}], "prompts": [{"text": "why is whisper synchronous instead of async?", "expected": {"should_inject": ["golden-008-mem-0"], "should_not_inject": ["golden-008-mem-2"]}, "notes": "Long query with causal phrasing — decision memory should surface"}, {"text": "what is the whisper hook timeout?", "expected": {"should_inject": ["golden-008-mem-1"], "should_not_inject": ["golden-008-mem-2"]}, "notes": "Second prompt in same case — different memory should surface"}]}
{"id": "golden-009", "memories": [{"node_id": "golden-009-mem-0", "title": "RRF fusion formula", "content": "Reciprocal Rank Fusion: score = 1/(k + rank) where k=60 is a smoothing constant. FTS results are dampened by 0.5. Weights configurable via ORMAH_FTS_WEIGHT/ORMAH_VECTOR_WEIGHT.", "type": "fact", "tier": "working", "tags": ["search", "algorithm"], "space": "ormah"}, {"node_id": "golden-009-mem-1", "title": "Ormah supports ollama as embedding provider", "content": "Embedding provider can be switched to ollama via ORMAH_EMBEDDING_PROVIDER=ollama and ORMAH_EMBEDDING_MODEL.", "type": "fact", "tier": "working", "tags": ["config", "embeddings"], "space": "ormah"}, {"node_id": "golden-009-mem-2", "title": "User dislikes verbose commit messages", "content": "Rishi prefers concise commit messages. Avoid long-winded descriptions.", "type": "preference", "tier": "core", "tags": ["about_self", "collaboration"], "space": null}], "prompts": [{"text": "RRF", "expected": {"should_inject": ["golden-009-mem-0"], "should_not_inject": ["golden-009-mem-2"]}, "notes": "Short 3-letter query — exact acronym match should surface the RRF memory"}]}
{"id": "golden-010", "memories": [{"node_id": "golden-010-mem-0", "title": "Ormah decay uses FSRS spaced repetition", "content": "Working-tier memories decay using FSRS (Free Spaced Repetition Scheduler). Stability field tracks days until ~37% retrievability.", "type": "fact", "tier": "working", "tags": ["decay", "architecture"], "space": "ormah"}, {"node_id": "golden-010-mem-1", "title": "Duplicate merger compares same-type nodes only", "content": "The duplicate merger only compares pairs of the same type. A fact and a preference with identical content are never merged.", "type": "fact", "tier": "working", "tags": ["background", "dedup"], "space": "ormah"}, {"node_id": "golden-010-mem-2", "title": "Ormah core memory cap is 50", "content": "A maximum of 50 nodes can be in the core tier at any time. Overflow is demoted to working.", "type": "fact", "tier": "working", "tags": ["tiers"], "space": "ormah"}], "prompts": [{"text": "what is the weather like in Dublin today?", "expected": {"should_inject": [], "should_not_inject": ["golden-010-mem-0", "golden-010-mem-1", "golden-010-mem-2"]}, "notes": "Fully off-topic prompt — nothing in the corpus should inject (tests false positive rate)"}]}
```

- [ ] **Step 2: Run the full eval on the golden corpus to verify it works end-to-end**

```bash
cd /home/r2205/Projects/ormah/.worktrees/eval-system
uv run ormah eval run --corpus golden
```
Expected: report prints with metrics. No crashes. Specific metric values don't matter yet — we're establishing a baseline.

- [ ] **Step 3: Commit**

```bash
git add eval/corpus/golden/golden.jsonl
git commit -m "feat(eval): initial 10-case golden corpus"
```

---

## Task 10: Run full test suite and verify

- [ ] **Step 1: Run all eval tests**

```bash
cd /home/r2205/Projects/ormah/.worktrees/eval-system
uv run pytest tests/test_eval/ -v
```
Expected: all tests pass.

- [ ] **Step 2: Run the full test suite to verify nothing broken**

```bash
uv run pytest tests/ -v --ignore=tests/test_background/test_llm_adapters.py
```
Expected: all tests pass (ignoring the pre-existing litellm failure).

- [ ] **Step 3: Smoke test the CI command**

```bash
uv run ormah eval run --corpus golden --fail-below recall@8=0.0 --fail-on-regression delta=0.99
```
Expected: exits 0 (thresholds set to always-pass for smoke test).

- [ ] **Step 4: Commit and push**

```bash
git add -A
git commit -m "feat(eval): complete whisper/recall eval system"
```

---

## Out of Scope (deferred)

- **`ormah eval generate-synthetic`** — listed in spec CLI table but not implemented here. Synthetic corpus generation requires LLM calls and is run manually when needed. The command scaffolding can be added to `eval/cli.py` as a stub that prints "Not yet implemented" if needed, but the full implementation is deferred until the golden corpus proves insufficient for regression detection.
- **Session replay seeding against full corpus** — runner currently seeds only case memories. For session cases (no embedded memories), the caller in `cmd_eval_run` should seed golden + synthetic before running session prompts. This is a Task 8 CLI extension left to the implementer: detect `case["memories"] == []` and call `seed_case(engine, {"memories": all_golden_memories})` before running those prompts.
