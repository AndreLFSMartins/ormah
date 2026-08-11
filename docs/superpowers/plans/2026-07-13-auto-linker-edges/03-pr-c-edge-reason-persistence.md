# PR C — `reason` survives a reindex

Branch: `fix/edge-reason-survives-reindex` off **`upstream/main`** (independent of PR A and B).
Read [00-overview.md](00-overview.md) first — especially the `PYTHONPATH` trap.

The three files this PR touches are **identical on `upstream/main` and the Beta** in the regions edited here (`Connection` at `models/node.py`, the `connections` block at `markdown.py:16-24` / `:84-88`, and `_index_file_edges` in `index/builder.py`), so the snippets below apply verbatim to both.

**The finding:** on the live store, **100% of 27,507 edges have `reason = NULL`** — including the 432 edges whose types (`supports`, `part_of`, `depends_on`, `evolved_from`, `contradicts`) only `auto_linker` and `conflict_detector` can create, and both of those writers *do* pass a `reason`. So the reasons are being written and then erased.

**Why an SQL fix cannot work.** The markdown file is the source of truth; the SQLite index is derived. `Connection` has only `target`, `edge`, `weight` — there is **no `reason` field**, and `markdown.py:85-88` serializes exactly those three keys. Reindexing a node deletes its edges (`builder._remove_node`: `DELETE FROM edges WHERE source_id = ? OR target_id = ?`) and recreates them from the markdown via `builder._index_file_edges`, which cannot supply a `reason` because the file never carried one. The index updater runs **every minute**. Any `reason` therefore has a lifetime of at most ~60 seconds.

The fix is to make `reason` part of the file format. `edges.reason` already exists in `schema.sql:33` — no DB migration is needed.

**Scope note:** this is a file-format change. Old files without `reason` parse fine (the field is optional, defaults to `None`); new files gain an extra key that old ormah versions ignore. Forward- and backward-compatible.

---

### Task 6: `Connection.reason` round-trips through markdown

**Files:**
- Modify: `src/ormah/models/node.py:56-59` (`Connection`)
- Modify: `src/ormah/store/markdown.py:17-24` (parse) and `:90-94` (serialize)
- Test: `tests/test_store/test_markdown.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store/test_markdown.py`:

```python
def test_connection_reason_round_trips():
    """The reason an edge exists must survive a save/load cycle — the index is
    rebuilt from markdown every minute, so anything not in the file is lost."""
    from ormah.models.node import Connection, EdgeType, MemoryNode, NodeType
    from ormah.store.markdown import parse_node, serialize_node

    node = MemoryNode(
        type=NodeType.fact,
        content="Python is a programming language.",
        connections=[
            Connection(
                target="11111111-1111-1111-1111-111111111111",
                edge=EdgeType.supports,
                weight=0.8,
                reason="Both describe Python as a language.",
            )
        ],
    )

    reloaded = parse_node(serialize_node(node))

    assert reloaded.connections[0].reason == "Both describe Python as a language."
    assert reloaded.connections[0].edge == EdgeType.supports
    assert reloaded.connections[0].weight == 0.8


def test_connection_without_reason_still_parses():
    """Files written before this change have no `reason` key — they must still load."""
    from ormah.store.markdown import parse_node

    text = """---
id: 22222222-2222-2222-2222-222222222222
type: fact
created: 2026-01-01T00:00:00+00:00
updated: 2026-01-01T00:00:00+00:00
connections:
  - target: 33333333-3333-3333-3333-333333333333
    edge: related_to
    weight: 0.7
---
Old file.
"""
    node = parse_node(text)
    assert node.connections[0].reason is None
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah/.claude/worktrees/edges-117
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_store/test_markdown.py -k reason -v
```

Expected: the first FAILS with a pydantic error (`Connection` has no field `reason` — extra inputs are not permitted, or the attribute is missing after the round trip); the second PASSES already.

- [ ] **Step 3: Implement**

In `src/ormah/models/node.py`, add the field to `Connection`:

```python
class Connection(BaseModel):
    target: str
    edge: EdgeType = EdgeType.related_to
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str | None = None
```

In `src/ormah/store/markdown.py`, parse it (inside the `for conn in meta.get("connections", []):` loop):

```python
        connections.append(
            Connection(
                target=conn["target"],
                edge=EdgeType(conn.get("edge", "related_to")),
                weight=conn.get("weight", 0.5),
                reason=conn.get("reason"),
            )
        )
```

And serialize it — keep the key out of the frontmatter when it is absent, so existing files are not churned:

```python
    if node.connections:
        meta["connections"] = [
            {
                "target": c.target,
                "edge": c.edge.value,
                "weight": c.weight,
                **({"reason": c.reason} if c.reason else {}),
            }
            for c in node.connections
        ]
```

- [ ] **Step 4: Run the store suite**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_store/ -v
```

Expected: PASS, both new tests included.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/models/node.py src/ormah/store/markdown.py tests/test_store/test_markdown.py
git commit -m "feat(model): Connection carries the reason the edge exists

The markdown file is the source of truth and the index is rebuilt from it every
minute, but Connection had no reason field — so every reason written by
auto_linker or conflict_detector was erased by the next reindex. On the store
this was found on, 100% of 27507 edges had reason=NULL, including edge types
only those two jobs can create.

The key is omitted when empty, so existing files are not churned, and files
without it still parse (reason defaults to None)."
```

---

### Task 7: the index writes `reason` back, and the writers stop dropping it

**Files:**
- Modify: `src/ormah/index/builder.py:224-230` (`_index_file_edges`)
- Modify: `src/ormah/background/auto_linker.py` (`_apply_edge`, the markdown `Connection`)
- Modify: `src/ormah/background/conflict_detector.py` (the markdown `Connection`)
- Test: `tests/test_index/test_builder.py`, `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_index/test_builder.py` (the file exists):

```python
def test_reindex_preserves_the_edge_reason(engine):
    """Reindexing a node must not wipe why its edges exist."""
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node = engine.file_store.load(id_a)
    node.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="because X")
    )
    engine.file_store.save(node)

    # index_single takes a Path, not an id (builder.py:124) — passing the id raises
    # before the assertion is ever reached (Codex R2, critical #4). The only helper that
    # maps a node to its file is FileStore._path_for(node) (file_store.py:192), which
    # takes the MemoryNode, not the id.
    engine.builder.index_single(engine.file_store._path_for(node))

    row = engine.db.conn.execute(
        "SELECT reason FROM edges WHERE source_id = ? AND target_id = ? AND edge_type = 'supports'",
        (id_a, id_b),
    ).fetchone()
    assert row is not None
    assert row["reason"] == "because X"
```

**Known bug this PR does NOT fix, surfaced by the review — state it in the PR body.** `_remove_node` deletes edges where the reindexed node is **source or target**, but `_index_file_edges` only recreates the connections stored in *that node's own* markdown. So reindexing node **B** deletes an incoming `A→B` edge and cannot restore it — the connection lives in A's file. Preserving `reason` on the outbound rebuild does not address this; it is a pre-existing structural flaw in incremental reindexing (the fix is to stop deleting incoming edges on an update, and reserve the full cascade for actual node deletion). It deserves its own issue, not a rider on this one.

And append to `tests/test_background/test_auto_linker.py`:

```python
def test_apply_edge_writes_the_reason_into_the_markdown(engine):
    """The reason must reach the file, otherwise the next reindex erases it."""
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)
    _apply_edge(engine, id_a, id_b, "supports", "they agree about Python", 0.8)

    node = engine.file_store.load(id_a)
    conn = next(c for c in node.connections if c.target == id_b)
    assert conn.reason == "they agree about Python"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_index/test_builder.py::test_reindex_preserves_the_edge_reason \
  tests/test_background/test_auto_linker.py::test_apply_edge_writes_the_reason_into_the_markdown -v
```

Expected: both FAIL — `row["reason"] is None` (the builder's `INSERT OR REPLACE` omits the column) and `conn.reason is None` (the `Connection` built in `_apply_edge` never sets it).

- [ ] **Step 3: Implement**

`src/ormah/index/builder.py` — include `reason` in the statement (the column already exists in `schema.sql:33`):

```python
            conn.execute(
                """
                INSERT OR REPLACE INTO edges (source_id, target_id, edge_type, weight, created, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (node.id, c.target, c.edge.value, c.weight, node.created.isoformat(), c.reason),
            )
```

`src/ormah/background/auto_linker.py` — in `_apply_edge`, pass the reason into the markdown connection:

```python
                md_conn = Connection(
                    target=node_b_id,
                    edge=EdgeType(edge_type),
                    weight=round(similarity, 2),
                    reason=reason or None,
                )
```

`src/ormah/background/conflict_detector.py` — same, for the connection it appends to `dirty_nodes`:

```python
                md_conn = Connection(
                    target=target_id,
                    edge=EdgeType(edge_type_str),
                    weight=0.9,
                    reason=explanation or None,
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_index/ tests/test_background/test_auto_linker.py \
  tests/test_background/test_conflict_detector.py tests/test_store/ -v
```

Expected: PASS.

- [ ] **Step 5: Full suite + lint**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/ -q --ignore=tests/test_cloud 2>&1 | tail -3
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ruff check src/ tests/
```

Expected: the same ~12 environmental failures as the baseline in `00-overview.md`, no new ones.

- [ ] **Step 6: Commit and open the PR**

```bash
git add src/ormah/index/builder.py src/ormah/background/auto_linker.py \
        src/ormah/background/conflict_detector.py \
        tests/test_index/test_builder.py tests/test_background/test_auto_linker.py
git commit -m "fix(index): reindexing no longer erases why an edge exists

builder._index_file_edges rebuilt edges from markdown without the reason column,
and the writers never put the reason in the markdown to begin with. Since the
index updater reindexes changed files every minute, every reason had a lifetime
of about a minute. The reason now travels: writer -> Connection -> markdown ->
index."

git push -u origin fix/edge-reason-survives-reindex
```

Open the PR against `r-spade/ormah:main`, titled `fix(index): reindex wipes edges.reason — 100% of edges end up with reason=NULL`, and include the live-store evidence (27,507 edges, all `reason=NULL`, including types only auto_linker/conflict_detector create).

**Backfill note for the PR body (do not implement — call it out):** this stops the bleeding but does not recover the reasons already lost. They are unrecoverable — they were never written to a file. A future run of each job regenerates reasons only for pairs it has not already recorded in `auto_link_checked` / `conflict_checked`, so most existing edges keep `reason=NULL` forever unless those tables are selectively cleared. That is a separate decision, not part of this PR.
