# Preserve `seq` on edge-only reindex (#126) — Implementation Plan (v2, post-council)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the auto_linker from re-queueing the nodes it just processed, without ever freezing a node out of relinking.

**Architecture:** `seq` is a change-sequence: the builder reallocates it on every index pass and the auto_linker enqueues by `seq > watermark`. Writing an edge rewrites the node's markdown, so the reindex bumps its `seq` and the node re-enters the queue with nothing to learn. The fix stores a **content fingerprint** (`sha256(title, content, type, space)`) in a column written **only by the builder**, and reallocates `seq` only when that fingerprint changes. When it does change, the node's cached pair verdicts are invalidated in the same transaction — otherwise the requeue is a no-op, because the auto_linker skips pairs already in `auto_link_checked`.

**Tech Stack:** Python 3.12, SQLite, pytest (`asyncio_mode=auto`), ruff (line-length 100, py311).

---

## Why v2 — what the council caught

The first version compared the incoming markdown against **the stored row**. Both peers broke it:

**1. `auto_cluster` dual-writes (Cursor, confirmed).** [auto_cluster.py:64-86](../../../src/ormah/background/auto_cluster.py#L64-L86) writes `space` **straight into SQLite** (`UPDATE nodes SET space = ?`) *and* saves the markdown, bypassing the builder. So by reindex time the stored row **already holds the new space** — prior == incoming, fingerprint unchanged, `seq` preserved, and the node is **frozen out of relinking forever** (it sits behind the watermark). Today's unconditional bump requeues it. v1 would have been a **regression**.

→ The baseline cannot be the stored row. It must be a value only the builder writes: a persisted fingerprint column, which a direct `UPDATE` does not touch.

**2. A fresh `seq` does not invalidate cached verdicts (Codex, confirmed).** The auto_linker skips any pair already in `auto_link_checked` ([auto_linker.py:552-554](../../../src/ormah/background/auto_linker.py#L552-L554)) **before** it even looks at the edge. And invalidation today is incomplete: [memory_engine.py:1098-1117](../../../src/ormah/engine/memory_engine.py#L1098-L1117) clears `auto_link_checked` only for content/title edits — a `type`/`space` edit clears only `conflict_checked`, and a **direct markdown edit clears nothing at all**. So requeueing a node whose pairs are all cached does nothing: it is re-scanned and every pair is skipped.

→ Bumping `seq` is necessary but **not sufficient**. The fingerprint change must invalidate the node's cached pairs atomically.

**R2 — three more, all accepted (Cursor).**

- *The backfill would bake in a pending relink.* It stamps the fingerprint from the current rows — but a row whose `file_hash` is stale has a reindex pending, and if `auto_cluster` already wrote the new `space` to the DB **and** the markdown, stamping it would make the next reindex see no change and lose the relink. Rows with a stale `file_hash` are now left **NULL** (a NULL never equals the incoming fingerprint, so they requeue). Tested in Task 6b.
- *The tests used a column that does not exist.* `auto_link_checked` has **`result`**, not `edge_type` ([schema.sql:85-91](../../../src/ormah/index/schema.sql#L85-L91)) — the v2 test INSERTs would have failed outright. Fixed.
- *`full_rebuild` would fire ~15k invalidations.* With `prior=None` for every node, each would call `_invalidate_checked_pairs`, i.e. a `WHERE node_a = ? OR node_b = ?` delete against a table whose PK is `(node_a, node_b)` with **no index on `node_b`** — a partial scan per node.

**Divergence from Cursor, deliberate:** Cursor proposed fixing that last one by clearing the three `*_checked` tables **globally** inside `full_rebuild`. That fixes the performance but changes behaviour: a rebuild would then re-judge the **entire store** with the LLM — a large new cost, on a store of ~15k nodes, that nobody asked for. Instead, invalidation is gated on `prior is not None`, so it runs only on an incremental reindex of an existing node. `full_rebuild` keeps its current cost and its current (pre-existing) behaviour of not clearing cached verdicts. That gap is real but is **not** this issue's; recorded as a follow-up.

**3. Connection topology (Codex) — partially rebutted.** Codex argued that removing/retargeting a connection changes candidate eligibility (the auto_linker skips pairs that already have an edge), so it should requeue. Two reasons it does not: (a) the `auto_link_checked` lookup runs **before** the existing-edge lookup, so an already-judged pair is skipped regardless of topology; (b) rejudging a pair whose edge a user deliberately deleted would **recreate the edge they removed**. The residual case — a never-judged pair whose imported edge is later removed — is narrow and is **not** addressed here. Recorded as a follow-up, not a blocker.

---

## Environment — read this first, it will cost you the session if you get it wrong

**NEVER check out a branch in `/Users/andre/Documents/GitHub/Tools/ormah`.** That clone is the Beta: editable install, serves the live server. All work happens in a worktree of `/Users/andre/Documents/GitHub/ormah-dev`.

- `ormah-dev` remotes: `origin` = fork (`AndreLFSMartins/ormah`), `upstream` = `r-spade/ormah`. Base: `upstream/main`.
- **pytest requires an isolated `HOME`** — otherwise the real `~/.config/ormah/.env` (which sets `ORMAH_LLM_PROVIDER=claude_cli`) is read by `tests/conftest.py` at import and collection dies with a pydantic `ValidationError` (issue #106). Every pytest command below is prefixed with `HOME=$(mktemp -d)`.
- The worktree needs its **own venv** — the Beta's venv lacks `respx` and must not be touched.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/ormah/index/schema.sql` | Table definitions for fresh DBs | **Modified** — add `content_fingerprint` |
| `src/ormah/index/db.py` | Schema migrations for existing DBs | **Modified** — add + backfill the column |
| `src/ormah/index/builder.py` | Index build/update. Owns `seq` allocation. | **Modified** — conditional `seq` + cache invalidation |
| `tests/test_index/test_seq_fingerprint.py` | Tests for conditional `seq` allocation | **Created** |

Fixing it in the builder (not in `_apply_edge`) covers `conflict_detector` and the six `memory_engine.index_single` call-sites for free.

---

### Task 0: Worktree + green baseline

**Files:** none (environment only)

- [ ] **Step 1: Create the worktree from upstream/main**

```bash
cd /Users/andre/Documents/GitHub/ormah-dev
git fetch upstream
git worktree add /Users/andre/Documents/GitHub/ormah-dev/.wt-126 -b fix/126-seq-fingerprint upstream/main
```

- [ ] **Step 2: Isolated venv**

```bash
cd /Users/andre/Documents/GitHub/ormah-dev/.wt-126
uv venv .venv --python 3.12
uv pip install -e ".[dev]" --python /Users/andre/Documents/GitHub/ormah-dev/.wt-126/.venv/bin/python
```

- [ ] **Step 3: Record the baseline**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: green except **5 pre-existing failures** in `tests/test_setup.py` (`TestConfigureClaudeCodeMcp` / `TestConfigureCodexMcp`) — they fail identically on pristine `upstream/main` because they touch the machine's real Codex CLI. **Do not fix them.** Write the exact counts down; Task 7 compares against them.

---

### Task 1: Schema — the fingerprint column

**Files:**
- Modify: `src/ormah/index/schema.sql`
- Modify: `src/ormah/index/db.py:129-155` (`_migrate`)
- Test: `tests/test_index/test_seq_fingerprint.py`

The column must be written **only** by the builder. That is the whole point: a direct `UPDATE nodes SET space = ...` (auto_cluster) leaves the fingerprint stale, so the next reindex sees a mismatch and correctly requeues the node.

- [ ] **Step 1: Write the failing test**

Create `tests/test_index/test_seq_fingerprint.py`:

```python
"""Conditional seq allocation driven by a persisted content fingerprint (#126)."""

from __future__ import annotations

from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType


def _row(engine, node_id: str):
    return engine.db.conn.execute(
        "SELECT seq, content_fingerprint FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()


def _seq(engine, node_id: str) -> int:
    return _row(engine, node_id)["seq"]


def _make_node(engine, title="Python language", content="Python is a programming language.",
               node_type=NodeType.fact, tags=None):
    node_id, _ = engine.remember(
        CreateNodeRequest(content=content, type=node_type, title=title,
                          tags=tags if tags is not None else ["test"]),
        agent_id="test",
    )
    return node_id


def test_indexing_persists_a_content_fingerprint(engine):
    """The builder stamps a fingerprint on every node it indexes."""
    node_id = _make_node(engine)
    fp = _row(engine, node_id)["content_fingerprint"]
    assert fp, "builder must persist a content fingerprint"
    assert len(fp) == 64, "expected a sha256 hex digest"
```

- [ ] **Step 2: Run it — must fail**

```bash
cd /Users/andre/Documents/GitHub/ormah-dev/.wt-126
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py -q
```

Expected: **FAIL** — `no such column: content_fingerprint`.

- [ ] **Step 3: Add the column to the schema**

In `src/ormah/index/schema.sql`, inside the `nodes` table definition, add after the `seq` column:

```sql
    content_fingerprint TEXT
```

- [ ] **Step 4: Migrate existing DBs, with a backfill**

In `src/ormah/index/db.py`, inside `_migrate()`, after the existing `nodes` enrichment-column block, add:

```python
            # #126: fingerprint of the fields that can change a linking decision. Written ONLY
            # by IndexBuilder — a direct `UPDATE nodes SET space = ...` (auto_cluster dual-write)
            # deliberately leaves it stale, so the next reindex sees the mismatch and requeues the
            # node. Backfill from the current rows so the fix does not requeue the whole store once.
            if "content_fingerprint" not in node_cols:
                conn.execute("ALTER TABLE nodes ADD COLUMN content_fingerprint TEXT")
                from ormah.index.fingerprint import content_fingerprint

                # Backfill from the current rows so the fix does not requeue the whole store
                # once on upgrade. BUT: a row whose file_hash no longer matches the file on
                # disk has a pending reindex — and if auto_cluster already wrote the new
                # `space` into BOTH the DB and the markdown, backfilling from the row would
                # bake the new value into the fingerprint, the next reindex would see no
                # change, and that node's pending relink would be lost silently. Leave those
                # NULL: a NULL fingerprint never equals the incoming one, so the first
                # reindex requeues them, which is exactly what they are owed.
                rows = conn.execute(
                    "SELECT id, title, content, type, space, file_path, file_hash FROM nodes"
                ).fetchall()
                stamped = []
                for r in rows:
                    node_id, title, content, node_type, space, file_path, file_hash = r
                    try:
                        on_disk = hashlib.sha256(
                            Path(file_path).read_bytes()
                        ).hexdigest() if file_path else None
                    except OSError:
                        on_disk = None
                    if on_disk is not None and on_disk != file_hash:
                        continue          # pending reindex -> leave NULL -> requeue
                    stamped.append(
                        (content_fingerprint(title, content, node_type, space), node_id)
                    )
                conn.executemany(
                    "UPDATE nodes SET content_fingerprint = ? WHERE id = ?", stamped
                )
```

This needs `import hashlib` and `from pathlib import Path` at the top of `db.py` if not already present.

**Note on `file_hash`:** confirm how `FileStore.file_hash()` computes the digest and reuse that exact function rather than re-implementing sha256-over-bytes here — a mismatch in the algorithm would mark every row as stale and requeue the whole store. Read `src/ormah/store/file_store.py` before writing this step.

- [ ] **Step 5: Create the fingerprint helper**

Create `src/ormah/index/fingerprint.py`:

```python
"""Fingerprint of the node fields that can change a linking decision (#126)."""

from __future__ import annotations

import hashlib


def content_fingerprint(
    title: str | None, content: str, node_type: str, space: str | None
) -> str:
    """sha256 over the fields a linking decision actually depends on.

    `title`/`content` feed the embedding (`embedding_text`) and the LLM judge prompt;
    `type` is shown to the judge; `space` is shown to the judge AND drives
    `cross_space_penalty` during candidate selection. Anything else — connections, tags,
    tier, importance, access_count — cannot change what the linker would decide, so it must
    not requeue the node (#126).

    The separator is a NUL byte: it cannot occur in any of these fields, so
    ("ab", "c") and ("a", "bc") cannot collide.
    """
    parts = [title or "", content, node_type, space or ""]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
```

- [ ] **Step 6: Stamp the fingerprint in the builder**

In `src/ormah/index/builder.py`, add the import at the top:

```python
from ormah.index.fingerprint import content_fingerprint
```

In `_index_file_nodes_only`, add `content_fingerprint` to the `INSERT OR REPLACE` column list and its value to the tuple. The column list becomes:

```python
            INSERT OR REPLACE INTO nodes
            (id, type, tier, source, space, space_locked, title, content, created, updated,
             last_accessed, access_count, confidence, importance,
             valid_until, stability, last_review, archived_at, file_path, file_hash,
             content_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?)
```

and the last value in the tuple (after `file_hash`):

```python
                content_fingerprint(node.title, node.content, node.type.value, node.space),
```

- [ ] **Step 7: Run — must pass**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py -q
```

Expected: **PASS**.

- [ ] **Step 8: Commit**

```bash
git add src/ormah/index/schema.sql src/ormah/index/db.py src/ormah/index/fingerprint.py src/ormah/index/builder.py tests/test_index/test_seq_fingerprint.py
git commit -m "feat(index): persist a content fingerprint written only by the builder (#126)"
```

---

### Task 2: The bug — an edge write must not requeue the node

**Files:**
- Modify: `src/ormah/index/builder.py`
- Test: `tests/test_index/test_seq_fingerprint.py`

- [ ] **Step 1: Write the failing test**

This is #126. It reproduces exactly what `_apply_edge` does.

```python
def test_edge_write_does_not_bump_seq(engine):
    """Persisting a connection must not requeue the node (#126).

    _apply_edge appends a Connection, touches `updated`, and saves the markdown. That
    rewrite used to bump `seq`, sending the node back to the end of the auto_linker queue
    with nothing new to learn — the pairs are already in auto_link_checked. That is what
    pinned the backlog at ~the size of the store.
    """
    id_a = _make_node(engine)
    id_b = _make_node(engine, title="Ruby language", content="Ruby is a programming language.")
    seq_before = _seq(engine, id_a)

    node = engine.file_store.load(id_a)
    node.connections.append(
        Connection(target=id_b, edge=EdgeType.related_to, weight=0.9, reason="both languages")
    )
    node.touch_updated()
    engine.builder.index_single(engine.file_store.save(node))

    assert _seq(engine, id_a) == seq_before, "an edge write must not requeue the node"
```

- [ ] **Step 2: Run it — must fail**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py::test_edge_write_does_not_bump_seq -q
```

Expected: **FAIL** — the seq is bumped. This is the bug. If it passes, stop: you are not reproducing #126.

- [ ] **Step 3: Read the prior row before the delete**

Both incremental paths delete the row before the `seq` is allocated. Add this method to `IndexBuilder`:

```python
    def _prior_row(self, node_id: str):
        """The stored fingerprint + seq, read BEFORE _remove_node deletes the row.

        The fingerprint — not the row's live columns — is the baseline: auto_cluster writes
        `space` straight into SQLite (auto_cluster.py:64-86), so the row's own columns may
        already hold the new value while the fingerprint still reflects the last indexed
        content. Comparing against the fingerprint is what keeps that node getting requeued.
        """
        return self.db.conn.execute(
            "SELECT seq, content_fingerprint FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
```

- [ ] **Step 4: Make the seq allocation conditional**

In `_index_file_nodes_only`, change the signature to `def _index_file_nodes_only(self, path: Path, prior=None) -> None:` and replace the unconditional seq block with:

```python
        # Durable monotonic change-sequence (council v2 crit#1): allocate from meta.node_seq_next
        # — never decreases, unlike MAX(seq)+1 which is non-monotonic across INSERT OR REPLACE.
        #
        # #126: only a CONTENT change requeues. A reindex whose only delta is the connection
        # block (an edge write by auto_linker/conflict_detector) is not a content change —
        # requeueing it sent the node back to the end of the queue with nothing to learn, which
        # pinned the backlog at ~the size of the store. Compare against the PERSISTED fingerprint,
        # never against the row's live columns: auto_cluster writes `space` directly into SQLite,
        # so the row can already hold the new value while the fingerprint still reflects the last
        # indexed content — comparing rows would freeze that node out of relinking for good.
        new_fp = content_fingerprint(node.title, node.content, node.type.value, node.space)

        if prior is not None and prior["content_fingerprint"] == new_fp:
            conn.execute("UPDATE nodes SET seq = ? WHERE id = ?", (prior["seq"], node.id))
        else:
            row = conn.execute("SELECT value FROM meta WHERE key = 'node_seq_next'").fetchone()
            next_seq = int(row[0]) if row else 1
            conn.execute("UPDATE nodes SET seq = ? WHERE id = ?", (next_seq, node.id))
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('node_seq_next', ?)",
                (str(next_seq + 1),),
            )
            if prior is not None:
                # Only an INCREMENTAL reindex of an existing node invalidates its cached
                # verdicts. full_rebuild passes prior=None for every node: calling this there
                # would fire ~15k `WHERE node_a = ? OR node_b = ?` deletes against a table whose
                # PK is (node_a, node_b) with no index on node_b — a partial scan per node, on
                # an operation that is already heavy. It would also silently make a rebuild
                # re-judge the entire store with the LLM, a large new cost nobody asked for.
                self._invalidate_checked_pairs(conn, node.id)
```

- [ ] **Step 5: Add the cache invalidation (stub for now — Task 3 tests it)**

A requeue is a no-op unless the cached verdicts go with it. Add to `IndexBuilder`:

```python
    def _invalidate_checked_pairs(self, conn, node_id: str) -> None:
        """Drop cached pair verdicts for a node whose content fingerprint changed (#126).

        The auto_linker skips any pair already in `auto_link_checked` BEFORE it looks at the
        edge (auto_linker.py:552-554), so a fresh `seq` alone changes nothing: the node is
        re-scanned and every one of its pairs is skipped. memory_engine.update_node clears
        these tables only for content/title edits (a type/space edit clears only
        conflict_checked, and a direct markdown edit clears nothing) — doing it here covers
        every path into the index, including disk edits and sync.
        """
        for table in ("auto_link_checked", "duplicate_checked", "conflict_checked"):
            conn.execute(
                f"DELETE FROM {table} WHERE node_a = ? OR node_b = ?", (node_id, node_id)
            )
```

- [ ] **Step 6: Thread `prior` through `_index_file`**

```python
    def _index_file(self, path: Path, prior=None) -> None:
        """Index a single markdown file into the database (nodes + edges)."""
        self._index_file_nodes_only(path, prior)
        self._index_file_edges(path)
```

- [ ] **Step 7: Capture `prior` in `index_single`**

```python
    def index_single(self, path: Path) -> None:
        """Index or re-index a single file."""
        node = parse_node(path.read_text(encoding="utf-8"))
        with self.db.transaction():
            prior = self._prior_row(node.id)   # read BEFORE the delete (#126)
            self._remove_node(node.id)
            self._index_file(path, prior)
```

- [ ] **Step 8: Capture `prior` in `update_index`**

Replace the update branch (`builder.py:110-113`):

```python
                    elif indexed[node.id] != file_hash:
                        prior = self._prior_row(node.id)   # read BEFORE the delete (#126)
                        self._remove_node(node.id, keep_vectors=True)
                        self._index_file(path, prior)
                        updated += 1
```

Leave the `if node.id not in indexed:` branch alone — a new node has no prior and must get a fresh `seq`.

- [ ] **Step 9: Run — must pass**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py -q
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_background/test_auto_linker.py -q -k "seq or watermark"
```

Expected: **PASS**, including the existing `test_seq_bumped_on_rewrite` and `test_metadata_update_does_not_bump_seq`.

- [ ] **Step 10: Commit**

```bash
git add src/ormah/index/builder.py tests/test_index/test_seq_fingerprint.py
git commit -m "fix(index): an edge write no longer requeues the node (#126)"
```

---

### Task 3: A requeue must actually rejudge — invalidate cached pairs

**Files:**
- Test: `tests/test_index/test_seq_fingerprint.py`

This is the council's second finding. Without it the whole fix is theatre: the node returns to the queue and every pair is skipped.

- [ ] **Step 1: Write the test**

```python
def test_fingerprint_change_invalidates_cached_pairs(engine):
    """A requeue is a no-op unless the cached verdicts go with it.

    auto_linker skips any pair already in auto_link_checked BEFORE it looks at the edge
    (auto_linker.py:552-554). memory_engine clears that table only on content/title edits —
    a type/space edit clears only conflict_checked, and a direct markdown edit clears
    nothing. So the invalidation belongs in the builder, where the fingerprint change is
    detected, and it must cover every path into the index.
    """
    id_a = _make_node(engine)
    id_b = _make_node(engine, title="Ruby language", content="Ruby is a programming language.")
    pair = tuple(sorted([id_a, id_b]))
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO auto_link_checked (node_a, node_b, result, checked_at) "
            "VALUES (?, ?, 'none', '2026-07-14T00:00:00+00:00')",
            pair,
        )

    # a SPACE change: memory_engine would NOT clear auto_link_checked for this
    node = engine.file_store.load(id_a)
    node.space = "some-other-space"
    engine.builder.index_single(engine.file_store.save(node))

    left = engine.db.conn.execute(
        "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
    ).fetchone()
    assert left is None, "a fingerprint change must drop the node's cached pair verdicts"


def test_edge_write_keeps_cached_pairs(engine):
    """The converse: an edge write must NOT drop cached verdicts (it would refeed the LLM)."""
    id_a = _make_node(engine)
    id_b = _make_node(engine, title="Ruby language", content="Ruby is a programming language.")
    pair = tuple(sorted([id_a, id_b]))
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO auto_link_checked (node_a, node_b, result, checked_at) "
            "VALUES (?, ?, 'related_to', '2026-07-14T00:00:00+00:00')",
            pair,
        )

    node = engine.file_store.load(id_a)
    node.connections.append(Connection(target=id_b, edge=EdgeType.related_to, weight=0.9))
    node.touch_updated()
    engine.builder.index_single(engine.file_store.save(node))

    left = engine.db.conn.execute(
        "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
    ).fetchone()
    assert left is not None, "an edge write must not invalidate cached verdicts"
```

- [ ] **Step 2: Run — both must pass**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py -q -k cached
```

Expected: **PASS** (Task 2 Step 5 already implemented it; these pin the behaviour in both directions).

- [ ] **Step 3: Commit**

```bash
git add tests/test_index/test_seq_fingerprint.py
git commit -m "test(index): a fingerprint change invalidates cached pair verdicts (#126)"
```

---

### Task 4: The regression the council caught — auto_cluster's direct DB write

**Files:**
- Test: `tests/test_index/test_seq_fingerprint.py`

**This is the most important test in the plan.** It is the exact scenario that would have shipped a node-freezing regression: `auto_cluster` writes `space` into SQLite *and* into the markdown, bypassing the builder. If the baseline were the stored row, prior would already equal the incoming value and the node would never be requeued.

- [ ] **Step 1: Write the test**

```python
def test_direct_db_space_update_still_requeues(engine):
    """auto_cluster dual-writes `space`: straight into SQLite AND into the markdown.

    (auto_cluster.py:64-86 — `UPDATE nodes SET space = ?` plus file_store.save, never through
    the builder.) If the baseline for "did the content change?" were the stored ROW, the row
    would already hold the new space by reindex time, the comparison would see no change, the
    seq would be preserved, and the node would be frozen out of relinking forever.

    The persisted fingerprint is the baseline precisely because a direct UPDATE does not touch
    it: it still reflects the last INDEXED content, so the mismatch is detected.
    """
    node_id = _make_node(engine)
    seq_before = _seq(engine, node_id)

    # exactly what auto_cluster does: DB first...
    with engine.db.transaction() as conn:
        conn.execute("UPDATE nodes SET space = ? WHERE id = ?", ("clustered-space", node_id))
    # ...then the markdown, never through the builder
    node = engine.file_store.load(node_id)
    node.space = "clustered-space"
    path = engine.file_store.save(node)

    engine.builder.index_single(path)

    assert _seq(engine, node_id) > seq_before, (
        "a space change written directly to the DB must still requeue the node — "
        "comparing against the stored row instead of the fingerprint would freeze it"
    )
```

- [ ] **Step 2: Run — must pass**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py::test_direct_db_space_update_still_requeues -q
```

Expected: **PASS**. If it fails, the fingerprint is being compared against the row's live columns instead of the persisted column — go back to Task 2 Step 4.

- [ ] **Step 3: Commit**

```bash
git add tests/test_index/test_seq_fingerprint.py
git commit -m "test(index): a direct DB space write must still requeue (auto_cluster) (#126)"
```

---

### Task 5: Every fingerprint field requeues; nothing else does

**Files:**
- Test: `tests/test_index/test_seq_fingerprint.py`

- [ ] **Step 1: Write the tests**

```python
def test_content_change_bumps_seq(engine):
    """Content feeds the embedding and the judge prompt."""
    node_id = _make_node(engine)
    seq_before = _seq(engine, node_id)
    max_before = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]

    node = engine.file_store.load(node_id)
    node.content = "Totally different subject: baking sourdough bread."
    engine.builder.index_single(engine.file_store.save(node))

    assert _seq(engine, node_id) > seq_before
    assert _seq(engine, node_id) > max_before, "must land at the head of the queue"


def test_title_change_bumps_seq(engine):
    """Title feeds the embedding and the judge prompt."""
    node_id = _make_node(engine)
    seq_before = _seq(engine, node_id)
    node = engine.file_store.load(node_id)
    node.title = "An entirely different title"
    engine.builder.index_single(engine.file_store.save(node))
    assert _seq(engine, node_id) > seq_before


def test_type_change_bumps_seq(engine):
    """Type is shown to the LLM judge."""
    node_id = _make_node(engine, node_type=NodeType.fact)
    seq_before = _seq(engine, node_id)
    node = engine.file_store.load(node_id)
    node.type = NodeType.decision
    engine.builder.index_single(engine.file_store.save(node))
    assert _seq(engine, node_id) > seq_before


def test_tags_only_change_does_not_bump_seq(engine):
    """Tags feed FTS, never the linker."""
    node_id = _make_node(engine, tags=["one"])
    seq_before = _seq(engine, node_id)

    node = engine.file_store.load(node_id)
    node.tags = ["one", "two"]
    engine.builder.index_single(engine.file_store.save(node))

    assert _seq(engine, node_id) == seq_before
    tags = {r["tag"] for r in engine.db.conn.execute(
        "SELECT tag FROM node_tags WHERE node_id = ?", (node_id,))}
    assert tags == {"one", "two"}, "the tag edit must still land in the index"
```

(`space` is already covered by Task 4, which exercises the harder path.)

- [ ] **Step 2: Run**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py -q
```

Expected: **PASS**.

- [ ] **Step 3: Commit**

```bash
git add tests/test_index/test_seq_fingerprint.py
git commit -m "test(index): pin each fingerprint field; tags must not requeue (#126)"
```

---

### Task 6: `full_rebuild` must still requeue everything

**Files:**
- Test: `tests/test_index/test_seq_fingerprint.py`

`full_rebuild` empties the table, so `prior` is always `None` and every node gets a fresh `seq`. Nothing in the code *states* that, and a refactor could break it silently — a restored store that is never relinked would be a catastrophic, invisible failure.

- [ ] **Step 1: Write the test**

```python
def test_full_rebuild_allocates_new_seq(engine):
    """A mass reindex requeues the whole store and clears the watermark."""
    node_id = _make_node(engine)
    seq_before = _seq(engine, node_id)
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('auto_link_watermark', ?)",
            (str(seq_before),),
        )

    engine.builder.full_rebuild()

    assert _seq(engine, node_id) > seq_before, "mass reindex must land nodes at the head"
    watermark = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'auto_link_watermark'"
    ).fetchone()
    assert watermark is None, "full_rebuild must clear the watermark"
```

- [ ] **Step 2: Run**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py::test_full_rebuild_allocates_new_seq -q
```

Expected: **PASS**.

- [ ] **Step 3: Commit**

```bash
git add tests/test_index/test_seq_fingerprint.py
git commit -m "test(index): full_rebuild still requeues the whole store (#126)"
```

---

### Task 6b: The migration backfill must not bake in a pending relink

**Files:**
- Test: `tests/test_index/test_seq_fingerprint.py`

The backfill stamps the fingerprint from the current rows — except for rows whose `file_hash` is stale, which are left `NULL` so the first reindex requeues them. That exception exists for one reason: `auto_cluster` may have already written the new `space` into both the DB and the markdown without a reindex, and baking that into the fingerprint would silently lose the pending relink.

- [ ] **Step 1: Write the test**

```python
def test_migration_leaves_stale_rows_unstamped(engine, tmp_path):
    """A row whose file on disk no longer matches its file_hash has a pending reindex.

    Backfilling its fingerprint from the row would bake in a change that was never indexed
    (auto_cluster writes `space` to the DB and the markdown without going through the
    builder), so the next reindex would see no change and the relink would be lost. Those
    rows must be left NULL, which forces a mismatch and a requeue.
    """
    node_id = _make_node(engine)

    # simulate the pending-reindex window: file on disk changed, DB not yet reindexed
    with engine.db.transaction() as conn:
        conn.execute("UPDATE nodes SET file_hash = ? WHERE id = ?", ("stale-hash", node_id))
        conn.execute("UPDATE nodes SET content_fingerprint = NULL WHERE id = ?", (node_id,))

    # re-running the migration must NOT stamp this row
    engine.db._migrate()

    fp = _row(engine, node_id)["content_fingerprint"]
    assert fp is None, "a row with a pending reindex must be left unstamped"

    # ...and the first reindex requeues it
    seq_before = _seq(engine, node_id)
    node = engine.file_store.load(node_id)
    engine.builder.index_single(engine.file_store.save(node))
    assert _seq(engine, node_id) > seq_before
```

- [ ] **Step 2: Run**

```bash
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_index/test_seq_fingerprint.py::test_migration_leaves_stale_rows_unstamped -q
```

Expected: **PASS**. If the migration is not idempotent (it must be — `_migrate` runs on every startup), fix that first: the `if "content_fingerprint" not in node_cols` guard already makes the `ALTER` idempotent, but the **backfill** must also be safe to re-run, so scope it to rows where `content_fingerprint IS NULL`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_index/test_seq_fingerprint.py
git commit -m "test(index): the migration must not stamp rows with a pending reindex (#126)"
```

---

### Task 7: Full suite, lint, PR

**Files:** none (verification only)

- [ ] **Step 1: Full suite**

```bash
cd /Users/andre/Documents/GitHub/ormah-dev/.wt-126
HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: the Task 0 baseline **plus the 9 new tests passing**. The only permitted failures are the 5 pre-existing `tests/test_setup.py` ones. **Any other failure is a regression you introduced — fix it, do not rationalise it.**

- [ ] **Step 2: Lint**

```bash
.venv/bin/python -m ruff check src/ tests/
```

Expected: no new errors (`memory_engine.py` has 4 pre-existing ones on `upstream/main`).

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin fix/126-seq-fingerprint
gh pr create --repo r-spade/ormah --base main --head AndreLFSMartins:fix/126-seq-fingerprint \
  --title "fix(index): requeue a node only when its content fingerprint changes (#126)" \
  --body "$(cat <<'EOF'
Closes #126.

## The bug

`seq` is a change-sequence: `IndexBuilder` reallocates it from `meta.node_seq_next` on **every** index pass, and the auto_linker enqueues by `seq > watermark`. So any reindexed node goes back to the end of the queue.

Writing an edge does exactly that: `_apply_edge` persists the connection into the node's markdown, the `file_hash` changes, `index_updater` reindexes within 60s, and the `seq` is bumped — **the auto_linker requeues the node it just processed**, with nothing to learn, since the pairs are already in `auto_link_checked`.

Measured on a live 14,942-node store: backlog pinned at **14,178** (~95%) regardless of throughput. Of the 13,103 nodes with `seq > 700,000`, **11,833 (90%)** were created before today but updated today. Re-queue rate ~352 nodes/hour.

## The fix

A **content fingerprint** — `sha256(title, content, type, space)` — is persisted on the node and written **only by the builder**. `seq` is reallocated only when it changes.

Two subtleties, both caught in peer review:

**The baseline must be the persisted fingerprint, never the stored row.** `auto_cluster` writes `space` straight into SQLite *and* into the markdown, bypassing the builder (`auto_cluster.py:64-86`). Comparing the incoming markdown against the stored *row* would find them already equal at reindex time, preserve the `seq`, and **freeze that node out of relinking forever**. A direct `UPDATE` does not touch the fingerprint column, so the mismatch is still detected. `test_direct_db_space_update_still_requeues` pins this.

**A requeue must invalidate cached verdicts.** The auto_linker skips any pair already in `auto_link_checked` *before* it looks at the edge (`auto_linker.py:552-554`), so a fresh `seq` alone changes nothing. `memory_engine.update_node` clears that table only for content/title edits — a type/space edit clears only `conflict_checked`, and a direct markdown edit clears nothing. The invalidation now happens in the builder, where the change is detected, covering every path into the index.

`full_rebuild` is unchanged: it empties the table and clears the watermark, so every node is requeued and a restored store is fully relinked.

Fixing it in the builder also covers `conflict_detector`, which writes edges the same way.

## Migration

`content_fingerprint` is added by `_migrate()` and **backfilled from the existing rows**, so the fix does not requeue the whole store once on upgrade.

## Tests

- `test_edge_write_does_not_bump_seq` — the bug; fails on `main`
- `test_direct_db_space_update_still_requeues` — the auto_cluster dual-write freeze
- `test_fingerprint_change_invalidates_cached_pairs` / `test_edge_write_keeps_cached_pairs`
- `test_content_/title_/type_change_bumps_seq`, `test_tags_only_change_does_not_bump_seq`
- `test_full_rebuild_allocates_new_seq`
- `test_indexing_persists_a_content_fingerprint`

## Known follow-up (not addressed here)

Removing a never-judged pair's imported edge does not requeue the node. Rejudging a pair whose edge a user deliberately deleted would recreate it, so this is a deliberate trade-off rather than an oversight.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Council coverage:** Cursor's `auto_cluster` freeze → Task 1 (persisted column) + Task 4 (the test). Codex's cached-verdict finding → Task 2 Step 5 + Task 3. Codex's connection-topology finding → rebutted in "Why v2", recorded as a follow-up in the PR body.

**Type consistency:** `content_fingerprint(title, content, node_type, space)` is called with `node.type.value` (`str`) everywhere — in the builder, and in the migration backfill (which reads the `type` column, also `str`). `_prior_row` returns a `sqlite3.Row` read by key, matching the rest of `builder.py`.

**Deliberate gap:** `_apply_edge` still calls `touch_updated()`, so `updated` still changes on an edge write. It is informational metadata and no longer affects the queue.
