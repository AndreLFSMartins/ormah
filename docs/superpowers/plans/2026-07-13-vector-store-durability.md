# Vector Store Durability & Watermark Resilience — Implementation Plan (v3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the vector store from being silently wiped and stop the auto_linker watermark from freezing, so daily maintenance keeps running through restarts and config blips.

**Architecture:** Three independent fail-closed hardenings, each its own commit + TDD: (0) `init_vec_table` derives the stored dimension from the table DDL (works for empty tables) and refuses to DROP a *populated* store on a mismatch unless a dim-valued escape hatch authorizes it; (1) the embedding backfill persists each chunk as it is encoded (durable + resumable in delta mode); (2) `auto_linker` skips a vectorless node instead of aborting the whole run, with a WARNING when it parks the watermark.

**Tech Stack:** Python 3.12, sqlite-vec (vec0), pydantic-settings, pytest (`asyncio_mode=auto`), local venv at `.venv/bin/python`.

**Root cause (verified 2026-07-13, live Beta):** boot at 09:53 ran with `embedding_dim=768` (`.env` mid-edit → config default), so `init_vec_table` DROPPED the 1024-dim store; boot at 10:28 (corrected `.env`, 1024) DROPPED again and re-created at 1024. Each drop left `node_vectors` empty, and `auto_linker` fail-closed-aborted on the first vectorless node → watermark frozen at 333726 with 12,135-node backlog. Non-resumable backfill (buffer-then-upsert) meant every restart mid-encode re-embedded all 12k from zero.

**Council r2/r3 outcome (this v3):** cursor R2 = approved-with-caveats (all r1 criticals/importants verified closed); codex R3 = needs-attention. v3 incorporates: codex HIGH — `_flush()` moved OUT of the encode `try` so persistence errors propagate as job failures instead of polluting `failed_ids` (Task 1); codex HIGH — unparseable `node_vectors` DDL now fails closed with `RuntimeError` (rows preserved) instead of booting into broken vector search (Task 0); codex MEDIUM — the recovery step verifies the embedding gap BEFORE run-all, since run-all does not gate auto_linker on backfill success (Task 3); cursor minors — Settings→`allow_drop` wiring test (Task 0) and `make smoke` pre-deploy (Task 3). REJECTED with cursor's concurrence: codex's demand to implement the vectorless-node retry/dead-letter set in this change — deferred to the upstream issue (see Task 2 header; full rationale in `.council/council-result.md`).

**Council r1 (cursor ❌ / codex ⚠️) — revisions incorporated:**
- CRITICAL (both peers): the proposed `raise` sat inside `init_vec_table`'s `except Exception: pass` → guard swallowed; and the `LIMIT 1` probe can't see an EMPTY mismatched table. Fix: derive dim from `sqlite_master` DDL, restructure the function so the guard is outside any broad except.
- HIGH (codex): boolean escape hatch would re-authorize silent drops forever if left in `.env`. Fix: dim-valued flag — `ORMAH_REINDEX_ON_DIM_CHANGE=<new dim>` authorizes only a migration TO that exact dim; a later unrelated mismatch (e.g. fallback to 768) is still refused.
- HIGH (codex): parking the watermark can starve nodes beyond the `auto_link_max_nodes_per_run` window if a node is PERMANENTLY vectorless (poison). Decision: accepted residual risk for this plan — the incident class being fixed is mass-vectorless-during-catch-up, which self-heals next run. Mitigation here: WARNING log with the parked node id (observability). A dead-letter/retry set decoupled from the cursor is deferred; noted on the upstream issue.
- IMPORTANT (cursor): stop_event contract — the interleaved design already flushes pending on cooperative cancel via the final `_flush()`; comment clarified and a pinning test added.
- MEDIUM (codex): chunked persistence makes DELTA mode resumable; SCHEMA mode still re-encodes all rows until the version advances (idempotent upserts — wasted compute, no data loss). Documented as the contract; schema-progress tracking deferred to the upstream issue.
- Legacy test `tests/test_embeddings/test_adapters.py::TestDimensionMismatch::test_mismatch_drops_and_recreates` pins the OLD silent-drop behavior — it must be updated to the new contract (Task 0 Step 6).
- Recovery after an authorized drop is automatic: the embedding_backfill job's first run is `now+10s` (`scheduler.py:198`); documented in Task 0/3.

**Upstream:** #109 covers Tasks 1+2. Task 0 (the dim-mismatch silent DROP) is a **distinct** root cause — open a new upstream issue (Task 3 Step 5), including the escape-hatch semantics and the two deferred follow-ups above.

---

## File Structure

- `src/ormah/index/db.py` — `init_vec_table`: DDL-based dim detection + `allow_drop` guard (Task 0).
- `src/ormah/config.py` — add `reindex_on_dim_change: int = 0` (Task 0).
- `src/ormah/engine/memory_engine.py` — startup caller passes `allow_drop` (Task 0); `_embed_node_rows` interleaves encode+upsert (Task 1).
- `src/ormah/background/auto_linker.py` — skip vectorless node + WARNING, don't abort (Task 2).
- Tests: `tests/test_index/test_init_vec_table_guard.py` (create), `tests/test_embeddings/test_adapters.py` (update legacy), `tests/test_engine/test_embed_node_rows.py` (extend), `tests/test_background/test_auto_linker.py` (extend).

Run everything with `/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest`.

---

### Task 0: `init_vec_table` — DDL-based dim detection + refuse to silently DROP a populated store

**Files:**
- Modify: `src/ormah/config.py:41` (add field)
- Modify: `src/ormah/index/db.py:351-396` (restructure `init_vec_table`; add `import re` to the imports block at the top if absent)
- Modify: `src/ormah/engine/memory_engine.py:156` (pass flag)
- Modify: `tests/test_embeddings/test_adapters.py:195-228` (update legacy test to the new contract)
- Test: `tests/test_index/test_init_vec_table_guard.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""Guard: a dim mismatch must never silently DROP a populated vector store."""
from __future__ import annotations

import numpy as np
import pytest

from ormah.embeddings.vector_store import VectorStore


def _count(engine) -> int:
    return engine.db.conn.execute("SELECT count(*) FROM node_vectors").fetchone()[0]


def test_dim_mismatch_on_populated_store_raises_not_drops(engine):
    dim = engine.settings.embedding_dim
    VectorStore(engine.db).upsert("n1", np.ones(dim, dtype=np.float32))
    assert _count(engine) == 1

    with pytest.raises(RuntimeError, match="dimension mismatch"):
        engine.db.init_vec_table(dim + 256)  # e.g. config default 768 vs stored 1024

    assert _count(engine) == 1  # nothing dropped


def test_dim_mismatch_on_empty_store_recreates(engine):
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")
    new_dim = engine.settings.embedding_dim + 256

    engine.db.init_vec_table(new_dim)  # empty → safe to recreate, no raise

    row = engine.db.conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='node_vectors'"
    ).fetchone()
    assert f"FLOAT[{new_dim}]" in row[0]


def test_allow_drop_authorizes_reindex(engine):
    dim = engine.settings.embedding_dim
    VectorStore(engine.db).upsert("n1", np.ones(dim, dtype=np.float32))

    engine.db.init_vec_table(dim + 256, allow_drop=True)  # explicit → drops

    assert _count(engine) == 0
    row = engine.db.conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='node_vectors'"
    ).fetchone()
    assert f"FLOAT[{dim + 256}]" in row[0]


def test_unparseable_ddl_raises_and_preserves_rows(engine):
    """A node_vectors table whose DDL has no FLOAT[dim] (corrupt/foreign schema)
    must fail closed: never guess-drop, never boot into broken vector search."""
    with engine.db.transaction() as conn:
        conn.execute("DROP TABLE node_vectors")
        conn.execute("CREATE TABLE node_vectors (id TEXT PRIMARY KEY, embedding BLOB)")
        conn.execute("INSERT INTO node_vectors (id, embedding) VALUES ('n1', x'00')")

    with pytest.raises(RuntimeError, match="FLOAT"):
        engine.db.init_vec_table(engine.settings.embedding_dim)

    assert _count(engine) == 1  # rows preserved for inspection/recovery


def test_startup_wiring_respects_reindex_flag(settings):
    """MemoryEngine.__init__ authorizes the drop only when the flag equals the
    configured dim; a stale flag from a previous migration keeps refusing."""
    from ormah.engine.memory_engine import MemoryEngine

    eng = MemoryEngine(settings)
    dim = settings.embedding_dim
    VectorStore(eng.db).upsert("n1", np.ones(dim, dtype=np.float32))
    eng.db.close()

    # Stale flag: authorizes the OLD dim while config asks a new one → refuse.
    settings.embedding_dim = dim + 256
    settings.reindex_on_dim_change = dim  # stale value != new dim
    with pytest.raises(RuntimeError, match="dimension mismatch"):
        MemoryEngine(settings)

    # Correct flag: equals the NEW dim → authorized drop.
    settings.reindex_on_dim_change = dim + 256
    eng2 = MemoryEngine(settings)
    assert eng2.db.conn.execute("SELECT count(*) FROM node_vectors").fetchone()[0] == 0
    eng2.db.close()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_index/test_init_vec_table_guard.py -v`
Expected: `test_dim_mismatch_on_populated_store_raises_not_drops` FAILS (current code drops silently — count becomes 0, no RuntimeError). `test_dim_mismatch_on_empty_store_recreates` FAILS (current `LIMIT 1` probe can't see an empty table's dim — DDL stays at the old dim). `test_allow_drop_authorizes_reindex` FAILS (TypeError: unexpected keyword `allow_drop`). `test_unparseable_ddl_raises_and_preserves_rows` FAILS (no raise today). `test_startup_wiring_respects_reindex_flag` FAILS (Settings has no `reindex_on_dim_change` yet).

- [ ] **Step 3: Add the config field**

In `src/ormah/config.py`, right after `embedding_dim` (line 41):

```python
    # Set to the NEW dim to authorize ONE deliberate destructive reindex of a
    # populated vector store (embedding-model migration). Remove after the boot.
    reindex_on_dim_change: int = 0
```

- [ ] **Step 4: Restructure `init_vec_table` in `db.py`**

Add `import re` to the imports at the top of `src/ormah/index/db.py` (after `import logging`). Replace the whole function (`src/ormah/index/db.py:351-396`):

```python
    def init_vec_table(self, dim: int = 768, *, allow_drop: bool = False) -> None:
        """Create the sqlite-vec virtual table. Requires sqlite-vec extension.

        The stored dimension is read from the table DDL in sqlite_master, so an
        EMPTY mismatched table is detected too (a row probe cannot see it). On a
        mismatch: an empty table is dropped and recreated at *dim*; a POPULATED
        table is protected — RuntimeError — unless ``allow_drop=True`` (a
        deliberate embedding-model migration). The caller (engine startup) is
        responsible for re-embedding after any authorized drop; the
        embedding_backfill job first fires ~10s after boot, so recovery is
        automatic.
        """
        try:
            import sqlite_vec

            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
        except ImportError:
            return  # sqlite-vec not available, vector search disabled

        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='node_vectors'"
        ).fetchone()
        if row is not None:
            match = re.search(r"FLOAT\[(\d+)\]", row[0] or "")
            if match is None:
                # Corrupt/foreign schema: fail closed — never guess-drop, and never
                # boot into broken vector search (MATCH would fail at runtime).
                raise RuntimeError(
                    "node_vectors exists but its DDL has no FLOAT[dim] — "
                    "unsupported or corrupt schema. Rows were preserved; inspect "
                    "the table, then restore a vec0 table (or move this one aside "
                    "and let the embedding backfill re-embed)."
                )
            else:
                existing_dim = int(match.group(1))
                if existing_dim != dim:
                    count = self.conn.execute(
                        "SELECT count(*) FROM node_vectors"
                    ).fetchone()[0]
                    if count > 0 and not allow_drop:
                        raise RuntimeError(
                            f"Embedding dimension mismatch: configured "
                            f"ORMAH_EMBEDDING_DIM={dim} but node_vectors holds "
                            f"{count} vectors of dim {existing_dim}. Refusing to "
                            f"DROP them. If this is a deliberate embedding-model "
                            f"change, set ORMAH_REINDEX_ON_DIM_CHANGE={dim} for one "
                            f"boot (remove it afterwards); otherwise fix "
                            f"ORMAH_EMBEDDING_DIM — the code default is 768."
                        )
                    logger.info(
                        "Recreating vec table (%d → %d, %d vectors dropped)",
                        existing_dim, dim, count,
                    )
                    with self.transaction() as conn:
                        conn.execute("DROP TABLE node_vectors")

        with self.transaction() as conn:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS node_vectors USING vec0("
                f"id TEXT PRIMARY KEY, embedding FLOAT[{dim}])"
            )
```

Note the structure: the broad `try` now wraps ONLY the extension import/load; the guard and its `RuntimeError` are outside any `except`, so they can never be swallowed (council r1 critical). The old `LIMIT 1` row probe and its `except Exception: pass` are gone entirely.

- [ ] **Step 5: Pass the flag from startup**

In `src/ormah/engine/memory_engine.py:156`:

```python
        self.db.init_vec_table(
            settings.embedding_dim,
            allow_drop=settings.reindex_on_dim_change == settings.embedding_dim,
        )
```

The equality (not a truthy check) is the one-shot-ish semantics: the flag authorizes only a migration TO the exact configured dim. If the config later falls back to 768 with a stale `ORMAH_REINDEX_ON_DIM_CHANGE=1024` in `.env`, `1024 != 768` → still refused (council r1 high).

- [ ] **Step 6: Update the legacy test that pins the old silent-drop behavior**

In `tests/test_embeddings/test_adapters.py`, replace the body of `TestDimensionMismatch::test_mismatch_drops_and_recreates` (lines ~196-228) with the new contract (same fixture/skip logic, new assertions):

```python
    def test_mismatch_on_populated_refuses_then_drops_with_allow(self, tmp_path):
        """A populated store refuses a dim change; allow_drop authorizes it."""
        from ormah.index.db import Database

        db = Database(tmp_path / "index.db")
        db.init_schema()
        try:
            db.init_vec_table(dim=4)
        except Exception:
            pytest.skip("sqlite-vec not available")

        import struct

        vec_bytes = struct.pack("4f", 1.0, 0.0, 0.0, 0.0)
        db.conn.execute(
            "INSERT INTO node_vectors (id, embedding) VALUES (?, ?)",
            ("test-node", vec_bytes),
        )
        db.conn.commit()

        with pytest.raises(RuntimeError, match="dimension mismatch"):
            db.init_vec_table(dim=8)  # populated + no authorization → refuse

        db.init_vec_table(dim=8, allow_drop=True)  # authorized → drop + recreate
        row = db.conn.execute(
            "SELECT id FROM node_vectors WHERE id = 'test-node'"
        ).fetchone()
        assert row is None

        db.close()
```

- [ ] **Step 7: Run the guard tests + the legacy file**

Run: `.venv/bin/python -m pytest tests/test_index/test_init_vec_table_guard.py tests/test_embeddings/test_adapters.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/ormah/config.py src/ormah/index/db.py src/ormah/engine/memory_engine.py tests/test_index/test_init_vec_table_guard.py tests/test_embeddings/test_adapters.py
git commit -m "fix(index): DDL-based dim detection; refuse to silently DROP a populated vector store"
```

---

### Task 1: Durable backfill — persist each chunk as it is encoded

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:1295-1323` (`_embed_node_rows`)
- Test: `tests/test_engine/test_embed_node_rows.py` (extend)

**Durability contract (document in the docstring):** persistence is atomic per chunk of 100 — a hard kill mid-`upsert_batch` rolls back at most the current chunk. DELTA mode is restart-resumable (the anti-join skips already-persisted rows). SCHEMA mode still re-encodes every row until the schema version advances at the end — idempotent upserts, so wasted compute but no data loss (schema-progress tracking is a deferred follow-up on the upstream issue).

- [ ] **Step 1: Write the failing tests** (append to the existing file; add `import pytest` and `import numpy as np` at the top if absent)

```python
def test_embed_node_rows_persists_incrementally(engine, monkeypatch):
    """A hard interrupt mid-encode must leave already-encoded chunks persisted,
    not lose everything. Simulate the kill with a BaseException on encode #101."""
    from ormah.models.node import CreateNodeRequest

    dim = engine.settings.embedding_dim
    for i in range(150):
        engine.remember(CreateNodeRequest(title=f"n{i}", content=f"content {i}"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

    calls = {"n": 0}

    class _KillAt101:
        def encode(self, text):
            calls["n"] += 1
            if calls["n"] == 101:
                raise KeyboardInterrupt("hard kill mid-encode")
            return np.ones(dim, dtype=np.float32)

    monkeypatch.setattr("ormah.embeddings.encoder.get_encoder", lambda s: _KillAt101())
    rows = engine.db.conn.execute("SELECT id, title, content FROM nodes").fetchall()

    with pytest.raises(KeyboardInterrupt):
        engine._embed_node_rows(rows)

    persisted = engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids"
    ).fetchone()[0]
    assert persisted == 100  # first full chunk landed before the kill


def test_embed_node_rows_flushes_pending_on_cooperative_cancel(engine, monkeypatch):
    """stop_event set mid-run: everything encoded so far is persisted (the final
    flush runs on the cooperative-cancel path too)."""
    import threading

    from ormah.models.node import CreateNodeRequest

    dim = engine.settings.embedding_dim
    for i in range(120):
        engine.remember(CreateNodeRequest(title=f"c{i}", content=f"cancel {i}"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

    stop = threading.Event()
    calls = {"n": 0}

    class _StopAt105:
        def encode(self, text):
            calls["n"] += 1
            if calls["n"] == 105:
                stop.set()  # cancellation arrives after this encode returns
            return np.ones(dim, dtype=np.float32)

    monkeypatch.setattr("ormah.embeddings.encoder.get_encoder", lambda s: _StopAt105())
    rows = engine.db.conn.execute("SELECT id, title, content FROM nodes").fetchall()

    embedded_ids, failed_ids = engine._embed_node_rows(rows, stop_event=stop)

    assert len(embedded_ids) == 105  # 100 flushed at the boundary + 5 pending flushed on exit
    assert failed_ids == []
    persisted = engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids"
    ).fetchone()[0]
    assert persisted == 105


def test_persistence_failure_propagates_not_marked_failed(engine, monkeypatch):
    """An upsert_batch error is a JOB failure, not a per-node encode failure: it
    must propagate (tracked() records it) and the node must NOT enter failed_ids
    — a wrong failed_ids entry would get its vector deleted by the schema-mode
    failed-node cleanup. (council r3, codex high)"""
    import sqlite3

    from ormah.models.node import CreateNodeRequest

    dim = engine.settings.embedding_dim
    nid, _ = engine.remember(CreateNodeRequest(title="pf", content="persist fail"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

    class _OkEncoder:
        def encode(self, text):
            return np.ones(dim, dtype=np.float32)

    monkeypatch.setattr("ormah.embeddings.encoder.get_encoder", lambda s: _OkEncoder())

    def _boom(self, items):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(
        "ormah.embeddings.vector_store.VectorStore.upsert_batch", _boom
    )
    rows = engine.db.conn.execute(
        "SELECT id, title, content FROM nodes WHERE id = ?", (nid,)
    ).fetchall()

    with pytest.raises(sqlite3.OperationalError):
        engine._embed_node_rows(rows)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine/test_embed_node_rows.py -v -k "incrementally or cooperative or persistence"`
Expected: the first two FAIL — current code buffers everything in `all_items`: the KeyboardInterrupt in phase 1 skips phase 2 (`persisted == 0`), and on cooperative cancel phase 2's own stop-check writes nothing (`persisted == 0`). The persistence-failure test PASSES against current code (phase 2 already propagates) — it is the regression net that forbids putting `_flush()` inside the encode `try` in the rewrite (council r3, codex high: that variant would swallow DB errors into `failed_ids`).

- [ ] **Step 3: Interleave encode + upsert**

Replace the two-phase body in `_embed_node_rows` (`src/ormah/engine/memory_engine.py:1295-1323` — from `all_items: list[...] = []` through `embedded_ids = upserted_ids`) with a single interleaved loop:

```python
        chunk_size = 100
        pending: list[tuple[str, Any]] = []
        upserted_ids: list[str] = []
        failed_ids: list[str] = []

        def _flush() -> None:
            # Persistence errors are NOT per-node failures: they propagate so the
            # job aborts loudly (tracked() records it) instead of polluting
            # failed_ids — a failed_ids entry here would be wrong AND, in schema
            # mode, would get its (possibly persisted) vector deleted by the
            # failed-node cleanup.
            if not pending:
                return
            vec_store.upsert_batch(pending)
            self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            upserted_ids.extend(item[0] for item in pending)
            pending.clear()

        for idx, n in enumerate(nodes):
            if stop_event is not None and stop_event.is_set():
                break  # cooperative cancel — the final _flush() below persists pending
            text = _embedding_text(n["title"], n["content"], max_chars)
            if text:
                try:
                    embedding = encoder.encode(text)
                except Exception as e:
                    logger.warning("Failed to embed node %s: %s", n["id"][:8], e)
                    failed_ids.append(n["id"])
                else:
                    pending.append((n["id"], embedding))
                    if len(pending) >= chunk_size:
                        _flush()  # outside the encode try — DB errors propagate
            done = idx + 1
            if done % log_every == 0 or done == total:
                logger.info("Embedding memories: %d/%d", done, total)
        _flush()  # final partial chunk — runs on natural end AND cooperative cancel

        embedded_ids = upserted_ids
```

The trailing block (`vec_count` warning + `return embedded_ids, failed_ids`) at lines 1324-1335 stays unchanged. Update the docstring with the durability contract stated above this task.

- [ ] **Step 4: Run the file's full test set**

Run: `.venv/bin/python -m pytest tests/test_engine/test_embed_node_rows.py tests/test_engine/test_backfill_embeddings.py tests/test_background/test_embedding_backfill.py -v`
Expected: all PASS (3 original + 2 new + the backfill suites, which exercise `_embed_node_rows` through `backfill_embeddings`).

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_embed_node_rows.py
git commit -m "fix(embeddings): persist each chunk as encoded so restarts don't lose backfill progress"
```

---

### Task 2: `auto_linker` skips a vectorless node instead of aborting the run

**Files:**
- Modify: `src/ormah/background/auto_linker.py:434-445`
- Test: `tests/test_background/test_auto_linker.py` (extend)

**Accepted residual risk (from council r1):** a PERMANENTLY vectorless (poison) node still parks the watermark, so nodes beyond the `auto_link_max_nodes_per_run` window stay unlinked until it heals. The incident class this fixes (mass-vectorless during backfill catch-up) self-heals on the next run. Mitigation: WARNING log with the node id. A retry set decoupled from the cursor is deferred — record it on the upstream issue.

- [ ] **Step 1: Write the failing test** (append to the existing file; reuses its helpers `_create_pair`, `_edges_between`, `_reset_adapter`, `_LLM_PATCH`)

```python
def test_vectorless_node_skipped_then_heals(engine):
    """A vectorless node must not kill the run: later nodes still get edges,
    the watermark parks BEFORE the orphan, and once the orphan's vector lands
    a later run advances past it (skip-then-heal)."""
    import json

    import numpy as np
    from unittest.mock import patch

    from ormah.background.auto_linker import _get_watermark, run_auto_linker
    from ormah.embeddings.vector_store import VectorStore
    from ormah.models.node import CreateNodeRequest

    # Orphan: lowest seq above the watermark, vector deleted.
    a_id, _ = engine.remember(
        CreateNodeRequest(title="orphan", content="a node whose vector was lost", tags=["test"])
    )
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (a_id,))

    id_b, id_c = _create_pair(engine)  # both embedded, similar

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    orphan_seq = engine.db.conn.execute(
        "SELECT seq FROM nodes WHERE id = ?", (a_id,)
    ).fetchone()["seq"]
    verdict = json.dumps({"relationship": "supports", "reason": "same topic"})

    with patch(_LLM_PATCH, return_value=verdict):
        stats = run_auto_linker(engine)

    assert len(_edges_between(engine, id_b, id_c)) >= 1  # pair linked despite orphan
    assert stats["pairs_attempted"] >= 1
    assert _get_watermark(engine.db.conn) < orphan_seq  # parked before the orphan

    # Heal: the orphan's vector lands (backfill), next run advances past it.
    dim = engine.settings.embedding_dim
    VectorStore(engine.db).upsert(a_id, np.ones(dim, dtype=np.float32))
    with patch(_LLM_PATCH, return_value=verdict):
        run_auto_linker(engine)

    assert _get_watermark(engine.db.conn) >= orphan_seq
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_background/test_auto_linker.py::test_vectorless_node_skipped_then_heals -v`
Expected: FAIL — current code hits `stopped = True; break` on the orphan, never reaches B/C: no edge, `pairs_attempted == 0`.

- [ ] **Step 3: Skip instead of abort**

In `src/ormah/background/auto_linker.py`, replace the abort branch (the `if text and node_vec is None:` block at ~L436-443, including its `ponytail:` comment):

```python
            node_vec = vec_store.get(node["id"]) if text else None
            if text and node_vec is None:
                # Vectorless node (store mid-backfill). Don't abort the whole run —
                # that froze the cursor for the entire store. Park the watermark here
                # (resolved=False → never advance past it, fail-closed) but keep
                # processing later nodes so they still get edges. A later run advances
                # once this node's vector lands. A PERMANENTLY vectorless node parks
                # the cursor for good — hence the WARNING (deferred: retry set
                # decoupled from the cursor).
                logger.warning(
                    "auto_linker: node %s (seq %s) has no vector; watermark parked, "
                    "continuing with later nodes",
                    node["id"][:8], node["seq"],
                )
                active.append({"node": node, "resolved": False, "pending": 0, "collected": True})
                continue
```

- [ ] **Step 4: Run the new test + the whole auto_linker suite**

Run: `.venv/bin/python -m pytest tests/test_background/test_auto_linker.py -v`
Expected: all PASS. The existing fail-closed regression tests (`test_empty_vector_index_does_not_advance_watermark`, `test_llm_none_does_not_advance_past_node`) must stay green — the watermark still never advances past an unprocessed node.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py tests/test_background/test_auto_linker.py
git commit -m "fix(auto_linker): skip a vectorless node instead of aborting the whole run"
```

---

### Task 3: Full gate + deploy + operational recovery

- [ ] **Step 1: Full suite + lint**

Run: `.venv/bin/python -m pytest tests/ -q` and `ruff check src/ tests/`
Expected: green except the 9 known environmental failures in `tests/test_setup.py` / `tests/test_setup_json.py` (machine-specific MCP-config/fastembed-cache tests — pre-existing, verified 2026-07-13 before these changes). The count must not grow.

Recommended (council r2, cursor): `make smoke` — the Docker fresh-install smoke test exercises the sqlite-vec boot path that Task 0 changes.

- [ ] **Step 2: Council review before touching local-main**

This is the mandatory gate. Run `/council-pr` (base = local-main; `main` is a symref to local-main, so diff-base auto-resolves). Do not merge on a defect.

- [ ] **Step 3: Deploy (restart is now safe)**

`launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev`. With Task 0, a config blip refuses to boot loudly (launchd error log) instead of wiping; with Task 1, an interrupted backfill resumes. The store is already full at 1024, so the delta backfill is a near-noop. If the guard ever fires legitimately (real model migration): set `ORMAH_REINDEX_ON_DIM_CHANGE=<new dim>`, boot once, REMOVE the line; the backfill job re-embeds automatically starting ~10s after boot.

- [ ] **Step 4: Unfreeze the watermark (recover the frozen cursor)**

The next scheduled auto_linker is tomorrow 10:33. **First verify the embedding gap is closed** — run-all does NOT gate auto_linker on backfill success (each task's exception is caught and the chain continues; council r3, codex medium):

```bash
.venv/bin/python - <<'PY'
import sqlite3, sqlite_vec
c = sqlite3.connect("file:/Users/andre/.local/share/ormah/memory/index.db?mode=ro", uri=True)
c.enable_load_extension(True); sqlite_vec.load(c); c.enable_load_extension(False)
vec = c.execute("SELECT count(*) FROM node_vectors").fetchone()[0]
nodes = c.execute("SELECT count(*) FROM nodes").fetchone()[0]
print(f"vec={vec} nodes={nodes} gap={nodes - vec}")
PY
```

Only when `gap` is ~0 (a handful of just-ingested nodes is fine), trigger the full pass: `POST http://localhost:8787/admin/tasks/run-all`. Watch `ormah.log` for `auto_linker run: {... pairs_attempted > 0 ...}` and a rising watermark. This is the sleep-cycle catch-up for the frozen days. If `gap` is large, wait for the embedding_backfill job (or trigger it alone) and re-check before running auto_linker.

- [ ] **Step 5: Open the upstream issue for Task 0**

Task 0 is not in #109. File a new issue — title: `bug(index): init_vec_table silently DROPs a populated vector store on dim mismatch — config default 768 wipes a 1024 store` — referencing #109, #32, #84. Include: the DDL-introspection fix, the dim-valued escape hatch semantics, and the two deferred follow-ups (retry set for parked vectorless nodes; schema-mode backfill progress tracking).

---

## Self-Review

- **Spec coverage:** Defect 0 → Task 0; Defect 1 → Task 1; Defect 2 → Task 2; operational recovery → Task 3. All council r1 criticals/highs addressed or explicitly accepted-with-mitigation (documented above).
- **Guard swallow (r1 critical):** the restructured function has the `raise` outside any `except`; the broad probe try/except is deleted. Empty-table mismatch now detected via DDL.
- **Escape hatch (r1 high):** dim-valued, validated by equality with the configured dim — a stale flag cannot authorize an unrelated mismatch.
- **Type/name consistency:** `init_vec_table(dim, *, allow_drop=False)`, `reindex_on_dim_change: int = 0`, `_flush()`, `pending`, `upserted_ids`, `_get_watermark` used consistently. `pairs_attempted` matches the run-stats keys; test helpers match `tests/test_background/test_auto_linker.py`.
- **Legacy pins:** the one test pinning silent-drop (`TestDimensionMismatch`) is updated in Task 0 Step 6; the fail-closed watermark tests are explicitly required green in Task 2 Step 4.
- **Risk:** the current live server (dim=1024, table=1024, store full) trips nothing on deploy. Residual risks documented: poison-node parking (WARNING + deferred retry set), schema-mode replay cost (deferred progress tracking).
