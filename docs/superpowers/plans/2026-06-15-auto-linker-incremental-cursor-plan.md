# Incremental auto-linker cursor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `run_auto_linker` (and the shared `_find_link_candidates` preview) process only nodes newer than a persisted cursor, turning the per-run O(n²) full scan into O(batch·n), while draining the historical backlog gradually.

**Architecture:** A `(updated, id)` watermark stored in the existing `meta` key-value table. `run_auto_linker` selects a bounded batch of nodes after the watermark (`updated ASC, id ASC`), runs the unchanged inner logic, then advances the watermark to the last fully-processed node. `_find_link_candidates` reads the same watermark window but never advances it. Absent watermark = epoch, so the backlog drains across runs.

**Tech Stack:** Python 3.11, SQLite (sqlite-vec), pytest (`asyncio_mode=auto`), existing `engine` fixture.

**Spec:** `docs/superpowers/specs/2026-06-15-auto-linker-incremental-cursor-design.md`

**Branch:** `perf/auto-linker-incremental` (base 0.11.0)

## File structure

- Modify `src/ormah/config.py` — add setting `auto_link_max_nodes_per_run`.
- Modify `src/ormah/background/auto_linker.py` — add watermark helpers, a shared incremental node-select, rewrite `run_auto_linker` and `_find_link_candidates`.
- Modify `tests/test_background/test_auto_linker.py` — add cursor tests; existing tests must stay green.

Watermark storage: key `auto_link_watermark` in `meta`, value `json.dumps([updated, node_id])`. Absent ⇒ `("", "")`. SQLite predicate (portable, no row-value dependency): `WHERE updated > :u OR (updated = :u AND id > :i)`.

---

### Task 1: Config setting `auto_link_max_nodes_per_run`

**Files:**
- Modify: `src/ormah/config.py` (near line 121-123, beside other `auto_link_*` settings)
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing test**

```python
def test_max_nodes_per_run_default(engine):
    """The batch-size setting exists with a sane default."""
    assert engine.settings.auto_link_max_nodes_per_run == 500
```

- [ ] **Step 2: Run, expect FAIL** — `pytest tests/test_background/test_auto_linker.py::test_max_nodes_per_run_default -v` → AttributeError.

- [ ] **Step 3: Add the setting**

In `src/ormah/config.py`, beside the other `auto_link_*` fields:

```python
    auto_link_max_nodes_per_run: int = 500  # cursor batch: nodes scanned per run
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/ormah/config.py tests/test_background/test_auto_linker.py
git commit -m "feat(config): add auto_link_max_nodes_per_run cursor batch setting (#26)"
```

---

### Task 2: Watermark helpers

**Files:**
- Modify: `src/ormah/background/auto_linker.py` (add helpers near top, after imports)
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing test**

```python
def test_watermark_roundtrip(engine):
    """Absent watermark reads as epoch; set then get round-trips."""
    from ormah.background.auto_linker import _get_watermark, _set_watermark

    assert _get_watermark(engine.db.conn) == ("", "")

    _set_watermark(engine, "2026-06-15T00:00:00+00:00", "node-xyz")
    assert _get_watermark(engine.db.conn) == ("2026-06-15T00:00:00+00:00", "node-xyz")
```

- [ ] **Step 2: Run, expect FAIL** — ImportError.

- [ ] **Step 3: Implement the helpers**

In `src/ormah/background/auto_linker.py` (add `import json` is already present):

```python
_WATERMARK_KEY = "auto_link_watermark"


def _get_watermark(conn) -> tuple[str, str]:
    """Return (updated, id) of the last fully-processed node, or ('', '') if unset."""
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (_WATERMARK_KEY,)
    ).fetchone()
    if row is None:
        return ("", "")
    try:
        updated, node_id = json.loads(row["value"])
        return (updated, node_id)
    except (json.JSONDecodeError, ValueError, TypeError):
        return ("", "")


def _set_watermark(engine, updated: str, node_id: str) -> None:
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (_WATERMARK_KEY, json.dumps([updated, node_id])),
        )
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py tests/test_background/test_auto_linker.py
git commit -m "feat(background): add auto_link watermark get/set helpers (#26)"
```

---

### Task 3: Incremental node select

**Files:**
- Modify: `src/ormah/background/auto_linker.py`
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing test**

```python
def test_select_nodes_after_window(engine):
    """Only nodes after the (updated,id) watermark are returned, ordered, bounded."""
    from ormah.background.auto_linker import _select_nodes_after

    id_a, id_b = _create_pair(engine)  # two nodes, real timestamps

    # Watermark before both ⇒ both returned, ordered by (updated, id)
    rows = _select_nodes_after(engine.db.conn, "", "", limit=10)
    ids = [r["id"] for r in rows]
    assert id_a in ids and id_b in ids

    # Watermark at the last row ⇒ nothing after it
    last = rows[-1]
    rows2 = _select_nodes_after(engine.db.conn, last["updated"], last["id"], limit=10)
    assert all(r["id"] != last["id"] for r in rows2)

    # limit is honoured
    assert len(_select_nodes_after(engine.db.conn, "", "", limit=1)) == 1
```

- [ ] **Step 2: Run, expect FAIL** — ImportError.

- [ ] **Step 3: Implement the select**

```python
def _select_nodes_after(conn, wm_updated: str, wm_id: str, limit: int) -> list:
    """Nodes with (updated, id) strictly greater than the watermark, ascending, bounded."""
    return conn.execute(
        "SELECT id, content, title, type, space, updated FROM nodes "
        "WHERE updated > ? OR (updated = ? AND id > ?) "
        "ORDER BY updated ASC, id ASC LIMIT ?",
        (wm_updated, wm_updated, wm_id, limit),
    ).fetchall()
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py tests/test_background/test_auto_linker.py
git commit -m "feat(background): incremental (updated,id) node select for auto-linker (#26)"
```

---

### Task 4: `run_auto_linker` drives the cursor

**Files:**
- Modify: `src/ormah/background/auto_linker.py` (`run_auto_linker`, ~L273-364)
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_run_advances_watermark(engine):
    """After a run, the watermark equals the last processed node's (updated, id)."""
    from ormah.background.auto_linker import run_auto_linker, _get_watermark, _select_nodes_after

    _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=json.dumps({"relationship": "none", "reason": "x"})):
        run_auto_linker(engine)

    all_rows = _select_nodes_after(engine.db.conn, "", "", limit=100)
    last = all_rows[-1]
    assert _get_watermark(engine.db.conn) == (last["updated"], last["id"])


def test_empty_delta_is_noop(engine):
    """A second run with the watermark at the head selects nothing and never calls the LLM."""
    from ormah.background.auto_linker import run_auto_linker

    _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=json.dumps({"relationship": "none", "reason": "x"})):
        run_auto_linker(engine)

    mock_llm = MagicMock(return_value=json.dumps({"relationship": "none", "reason": "x"}))
    with patch(_LLM_PATCH, mock_llm):
        run_auto_linker(engine)
    assert mock_llm.call_count == 0


def test_backlog_drains_across_runs(engine):
    """With batch=1, two nodes take two runs to fully process."""
    from ormah.background.auto_linker import run_auto_linker, _get_watermark, _select_nodes_after

    _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    engine.settings.auto_link_max_nodes_per_run = 1
    _reset_adapter()

    rows = _select_nodes_after(engine.db.conn, "", "", limit=100)
    with patch(_LLM_PATCH, return_value=json.dumps({"relationship": "none", "reason": "x"})):
        run_auto_linker(engine)
        assert _get_watermark(engine.db.conn) == (rows[0]["updated"], rows[0]["id"])
        run_auto_linker(engine)
        assert _get_watermark(engine.db.conn) == (rows[1]["updated"], rows[1]["id"])
```

- [ ] **Step 2: Run, expect FAIL** — watermark not advanced / LLM still called.

- [ ] **Step 3: Rewrite `run_auto_linker`**

Replace the node fetch + loop. Read the watermark, select the batch, track the last *complete* node, advance the watermark at the end. The inner match logic (encode → search → cross-space penalty → threshold → `auto_link_checked` → existing-edge → `_llm_classify_link` → `_apply_edge`) is unchanged.

```python
def run_auto_linker(engine) -> None:
    """Incrementally link nodes newer than the watermark; advance the watermark."""
    try:
        from ormah.embeddings.encoder import get_encoder
        from ormah.embeddings.vector_store import VectorStore

        settings = engine.settings
        if not settings.llm_enabled:
            logger.debug("Auto-linker skipped: LLM not enabled")
            return

        encoder = get_encoder(settings)
        vec_store = VectorStore(engine.db)
        conn = engine.db.conn
        threshold = settings.auto_link_similarity_threshold
        cross_space_penalty = settings.auto_link_cross_space_penalty
        max_edges = settings.auto_link_max_edges_per_run

        wm_updated, wm_id = _get_watermark(conn)
        nodes = _select_nodes_after(
            conn, wm_updated, wm_id, settings.auto_link_max_nodes_per_run
        )

        created = 0
        last_complete: tuple[str, str] | None = None
        stopped_early = False

        for node in nodes:
            if created >= max_edges:
                stopped_early = True
                break

            text = f"{node['title'] or ''} {node['content']}".strip()
            if text:
                query_vec = encoder.encode(text)
                similar = vec_store.search(query_vec, limit=6)

                for match in similar:
                    if created >= max_edges:
                        stopped_early = True
                        break
                    if match["id"] == node["id"]:
                        continue

                    similarity = match["similarity"]
                    other_space = conn.execute(
                        "SELECT space FROM nodes WHERE id = ?", (match["id"],)
                    ).fetchone()
                    if other_space is not None:
                        if (node["space"] or "") != (other_space["space"] or ""):
                            similarity -= cross_space_penalty
                    if similarity < threshold:
                        continue

                    pair = tuple(sorted([node["id"], match["id"]]))
                    if conn.execute(
                        "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
                    ).fetchone():
                        continue
                    if conn.execute(
                        "SELECT 1 FROM edges WHERE (source_id = ? AND target_id = ?) "
                        "OR (source_id = ? AND target_id = ?)",
                        (node["id"], match["id"], match["id"], node["id"]),
                    ).fetchone():
                        continue
                    other = conn.execute(
                        "SELECT title, content, type, space FROM nodes WHERE id = ?",
                        (match["id"],),
                    ).fetchone()
                    if other is None:
                        continue

                    llm_result = _llm_classify_link(settings, node, other)
                    if llm_result is None:
                        continue
                    relationship = llm_result["relationship"]
                    _apply_edge(
                        engine, node["id"], match["id"], relationship,
                        llm_result.get("reason", ""), similarity,
                    )
                    if relationship != "none":
                        created += 1

            if stopped_early:
                break
            last_complete = (node["updated"], node["id"])

        if last_complete is not None:
            _set_watermark(engine, last_complete[0], last_complete[1])
        if created:
            logger.info("Auto-linker created %d edges", created)

    except Exception as e:
        logger.warning("Auto-linker failed: %s", e)
```

- [ ] **Step 4: Run the full file, expect PASS** — `pytest tests/test_background/test_auto_linker.py -v`. All new tests pass AND the existing `test_llm_*` / `test_checked_pairs_*` tests stay green.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py tests/test_background/test_auto_linker.py
git commit -m "feat(background): drive auto_linker by incremental watermark cursor (#26)"
```

---

### Task 5: `_find_link_candidates` shares the incremental scan

**Files:**
- Modify: `src/ormah/background/auto_linker.py` (`_find_link_candidates`, ~L131-220)
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing test**

```python
def test_find_candidates_uses_window_without_advancing(engine):
    """Preview reads the watermark window but never advances the watermark."""
    from ormah.background.auto_linker import _find_link_candidates, _get_watermark

    _create_pair(engine)
    engine.settings.auto_link_similarity_threshold = 0.0

    before = _get_watermark(engine.db.conn)
    cands = _find_link_candidates(engine, limit=8)
    assert isinstance(cands, list)
    assert all("node_a" in c and "node_b" in c and "similarity" in c for c in cands)
    # Preview must not move the cursor
    assert _get_watermark(engine.db.conn) == before
```

- [ ] **Step 2: Run, expect FAIL** — watermark advanced or shape mismatch.

- [ ] **Step 3: Rewrite the node fetch in `_find_link_candidates`**

Replace `ORDER BY RANDOM()` full scan with the shared incremental select; read the watermark, do **not** advance it. Inner filtering (similarity/threshold/cross-space, `seen_pairs`, `auto_link_checked`, existing edge) and the returned `{"node_a", "node_b", "similarity"}` shape are unchanged.

```python
        conn = engine.db.conn
        wm_updated, wm_id = _get_watermark(conn)
        nodes = _select_nodes_after(
            conn, wm_updated, wm_id, settings.auto_link_max_nodes_per_run
        )
```

(Remove the old `nodes = conn.execute("SELECT ... ORDER BY RANDOM()").fetchall()` line; the rest of the function body — the `for node in nodes:` candidate-collection loop bounded by `limit` — stays as-is.)

- [ ] **Step 4: Run, expect PASS** — `pytest tests/test_background/test_auto_linker.py -v`. Existing `TestFindLinkCandidates` / `test_run_maintenance` tests stay green.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py tests/test_background/test_auto_linker.py
git commit -m "feat(background): share incremental scan in _find_link_candidates (#26)"
```

---

### Task 6: Full suite + lint

- [ ] **Step 1:** `pytest tests/test_background/ -v` → all green.
- [ ] **Step 2:** `ruff check src/ tests/` → clean.
- [ ] **Step 3:** Manual smoke against the dev server (optional, real store): restart `.venv/bin/ormah server`, confirm a maintenance run advances `meta.auto_link_watermark` (`sqlite3 ~/.local/share/ormah/memory/index.db "SELECT value FROM meta WHERE key='auto_link_watermark'"`).

---

## Self-review

- **Spec coverage:** watermark in `meta` (T2) ✓; incremental select / O(batch·n) (T3,T4) ✓; backlog drains from epoch (T4 `test_backlog_drains_across_runs`) ✓; `_find_link_candidates` shared scan, no advance (T5) ✓; new setting default 500 (T1) ✓; composite `(updated,id)` cursor + ties (T3 predicate) ✓; correctness/idempotency via existing `auto_link_checked` (existing tests kept green, T4/T5) ✓; partial-run/`max_edges` does not advance past the interrupted node (T4 `stopped_early`/`last_complete`) ✓.
- **Placeholder scan:** none — every code step shows full code.
- **Type consistency:** `_get_watermark` returns `(str, str)` used by `_select_nodes_after(conn, wm_updated, wm_id, limit)` in both T4 and T5; `_set_watermark(engine, updated, node_id)`; `auto_link_max_nodes_per_run` name consistent across T1/T4/T5.
- **Out of scope (unchanged):** LLM edge-quality (~90% supports), ANN (#25), embedding reuse.
