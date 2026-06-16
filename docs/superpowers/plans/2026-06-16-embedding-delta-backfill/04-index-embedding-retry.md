# Task 04: Bounded retry in `_index_embedding`

The inline write path swallows encode/upsert failures, leaking gaps. Add a bounded
retry with exponential backoff so transient Ollama hiccups don't drop the vector.
After exhausting retries, log and return — the reconciliation job (Task 03/06) is the
eventual-consistency net. Backoff stays short so `remember`/ingest isn't blocked long.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (`import time` at top ~L5-11; `_index_embedding` ~L1828-1839)
- Test: `tests/test_engine/test_index_embedding_retry.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_index_embedding_retry.py`:

```python
"""Tests for _index_embedding bounded retry (#32)."""
from __future__ import annotations

from ormah.models.node import CreateNodeRequest


class _FlakyEncoder:
    """Fails `fail_times` then succeeds, returning a fixed-dim vector."""
    def __init__(self, fail_times, dim):
        self.fail_times = fail_times
        self.calls = 0
        self._dim = dim

    def encode(self, text):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient encoder failure")
        import numpy as np
        return np.ones(self._dim, dtype="float32")


def test_index_embedding_retries_then_succeeds(engine, monkeypatch):
    nid, _ = engine.remember(CreateNodeRequest(title="Retry", content="payload"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    node = engine.file_store.load(nid)

    enc = _FlakyEncoder(fail_times=2, dim=engine.settings.embedding_dim)
    monkeypatch.setattr("ormah.embeddings.encoder.get_encoder", lambda settings: enc)
    monkeypatch.setattr("time.sleep", lambda s: None)  # no real backoff in tests

    engine._index_embedding(node)  # max_retries default 2 → 3 attempts total

    assert enc.calls == 3
    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (nid,)
    ).fetchone()[0] == 1


def test_index_embedding_gives_up_without_raising(engine, monkeypatch):
    nid, _ = engine.remember(CreateNodeRequest(title="Down", content="payload"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    node = engine.file_store.load(nid)

    class _DeadEncoder:
        def encode(self, text):
            raise RuntimeError("encoder permanently down")

    monkeypatch.setattr("ormah.embeddings.encoder.get_encoder", lambda settings: _DeadEncoder())
    monkeypatch.setattr("time.sleep", lambda s: None)

    engine._index_embedding(node)  # must NOT raise

    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (nid,)
    ).fetchone()[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine/test_index_embedding_retry.py -v`
Expected: FAIL — `test_index_embedding_retries_then_succeeds` fails (current code calls
`encode` once, gives up, leaves gap → `enc.calls == 1`, vector count 0).

- [ ] **Step 3: Add `import time`**

In `src/ormah/engine/memory_engine.py`, add `import time` to the stdlib import block
(after `import re` ~L9), keeping alphabetical-ish grouping:

```python
import re
import time
import uuid
```

- [ ] **Step 4: Implement the retry loop**

Replace `_index_embedding` (~L1828-1839) with:

```python
    def _index_embedding(self, node: MemoryNode) -> None:
        from ormah.embeddings.vector_store import VectorStore
        from ormah.embeddings.encoder import get_encoder

        text = _embedding_text(
            node.title, node.content, self.settings.embedding_max_content_chars
        )
        if not text:
            return

        max_retries = self.settings.embedding_index_max_retries
        backoff = self.settings.embedding_index_retry_backoff_seconds
        for attempt in range(max_retries + 1):
            try:
                encoder = get_encoder(self.settings)
                vec_store = VectorStore(self.db)
                embedding = encoder.encode(text)
                vec_store.upsert(node.id, embedding)
                return
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(backoff * (2 ** attempt))
                    continue
                logger.warning(
                    "Failed to index embedding for node %s after %d attempts: %s",
                    node.id[:8], max_retries + 1, e,
                )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine/test_index_embedding_retry.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_index_embedding_retry.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_index_embedding_retry.py
git commit -m "feat(engine): bounded retry in _index_embedding to reduce embedding gaps (#32)"
```
