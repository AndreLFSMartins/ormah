"""In-context relevance-gate eval (the ship gate). Run pre-merge with a live provider:
   env -u VIRTUAL_ENV HOME=$(mktemp -d) .venv/bin/python -m eval.relevance.runner

Runs the REAL `_INGEST_LLM_PROMPT` + `_INGEST_RESPONSE_SCHEMA` end-to-end via
MemoryEngine._extract_memories_llm and scores the emitted provenance labels.
This tests the production decision (labels compete inside the real extraction
prompt), unlike a standalone classify-prompt eval over isolated content — see
Task 5 brief. Exits non-zero if either asymmetric threshold is missed or the
corpus is too small.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

MIN_PER_CLASS = 20
CORPUS_PATH = Path(__file__).parent / "corpus/cases.json"


def _labels_for(engine: Any, snippet: str) -> list[str]:
    """Return the list of provenance labels the real extractor emits for a snippet."""
    mems = engine._extract_memories_llm(snippet)
    if isinstance(mems, str):  # extractor error string
        return []
    return [m.get("provenance") for m in mems if isinstance(m, dict)]


def _default_engine() -> Any:
    """Construct the real MemoryEngine the way the codebase does (see
    src/ormah/main.py:190, tests/conftest.py): MemoryEngine(Settings())."""
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    return MemoryEngine(Settings())


def main(
    engine_factory: Callable[[], Any] = _default_engine,
    corpus_path: Path | None = None,
) -> int:
    path = corpus_path or CORPUS_PATH
    cases = json.loads(path.read_text())
    prod = [c for c in cases if c["label"] == "product"]
    mat = [c for c in cases if c["label"] == "material"]
    if len(prod) < MIN_PER_CLASS or len(mat) < MIN_PER_CLASS:
        print(f"FAIL: corpus too small (product={len(prod)}, material={len(mat)}, "
              f"need >={MIN_PER_CLASS} each)")
        return 2

    engine = engine_factory()
    # product preserved: extractor emits at least one candidate labeled "product"
    prod_ok = sum("product" in _labels_for(engine, c["snippet"]) for c in prod) / len(prod)
    # material dropped: extractor labels a candidate "material" (the gate would drop it)
    mat_ok = sum("material" in _labels_for(engine, c["snippet"]) for c in mat) / len(mat)
    print(f"product_preserved={prod_ok:.3f} (>=0.98)  material_dropped={mat_ok:.3f} (>=0.80)")
    ok = prod_ok >= 0.98 and mat_ok >= 0.80
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
