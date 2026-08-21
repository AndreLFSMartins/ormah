# Task 7: `repair_edges` — recover lost edges without a full rebuild — SEPARATE PR


> ⚠️ **NOT re-anchored.** Tasks 0-5 were re-anchored against `upstream/main @ 9a7c524` on
> 2026-08-21 (see `00-overview.md`); this file was not, because it belongs to a second PR that
> cannot start until the first is merged — and `upstream/main` will have moved by then. Before
> executing it, repeat the re-anchor check: every line number, every `Connection` field, and
> every column list here was derived from `local-main` and must be re-derived from the island.

Read `00-overview.md` first — its Global Constraints apply to every step here.

> **One gate before starting: the fix must be MERGED, not merely reviewed.** Council round 1
> rejected the earlier wording ("tasks 1-5 pushed and reviewed") from both peers independently:
> review in the fork does not advance `upstream/main`, so a branch cut from it would carry the
> repair **without** the builder fix — repairing a store that is still actively losing edges, and
> risking a merge order where the repair lands first.
>
> Task 6 is **not** a gate. It supplies the acceptance number; it cannot cancel this task. See
> `06-drift-measurement.md`, *Why this is not a gate*.

**Files:**
- Create: `../ormah-wt-123-repair` island, branch `fix/123-repair-lost-edges`
- Modify: `src/ormah/index/builder.py` (new `repair_edges`, directly after `full_rebuild`),
  `src/ormah/api/routes_admin.py` (new endpoint below `/rebuild`, `:213`)
- Test: `tests/test_index/test_builder.py`

**Interfaces:**
- Consumes: `missing_typed` from task 6, as the acceptance number.
- Produces: `IndexBuilder.repair_edges() -> dict`, returning `{"scanned", "inserted", "failed"}`,
  and `POST /admin/repair-edges` returning that same shape with a `status` of `"repaired"` or
  `"repaired_partial"`.

**Why a dict and not an `int`.** Council round 1 (Codex): the earlier signature returned only the
net row delta while swallowing every per-file exception inside the transaction, and the handler
answered `status: "repaired"` unconditionally. A run where every file failed to parse would commit
nothing and report success — and task 6 explicitly forbids treating a parse failure as noise.

## What this buys

Today the only way back from lost edges is `POST /admin/rebuild`, which re-embeds and rebuilds FTS
for the whole store — 221.7 s measured on the Beta on 2026-08-21. A connections-only repair re-reads
each node's `connections` and inserts the missing `edges` rows, touching no nodes, no vectors, no FTS.

- [ ] **Step 1: Build the island**

**Prove the fix is in the base before cutting anything.** Do not infer it from a merged PR page;
test it.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
# The merge commit of the #123 fix PR, read from the PR itself — not from memory.
FIX_SHA=$(gh pr view <PR#> --json mergeCommit -q .mergeCommit.oid)
git merge-base --is-ancestor "$FIX_SHA" upstream/main && echo "OK: fix is in upstream/main" \
  || { echo "STOP: the #123 fix is NOT in upstream/main yet"; exit 1; }
```

If that prints `STOP`, there are exactly two acceptable moves — wait for the merge, or stack this
PR on the fix branch (`git worktree add -b fix/123-repair-lost-edges ../ormah-wt-123-repair
fix/123-reindex-preserves-incoming-edges`) and mark it explicitly as stacked so it cannot merge
independently. **Never** cut from a plain `upstream/main` that lacks the fix.

```bash
git worktree add -b fix/123-repair-lost-edges ../ormah-wt-123-repair upstream/main
cd ../ormah-wt-123-repair
python3 -m venv .venv
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -e ".[dev]"
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: a path containing `ormah-wt-123-repair/`. Anything else and every number below is void.

Then prove the fix is actually in **this** tree, not just in the base you named:

```bash
grep -n "_clear_derived" src/ormah/index/builder.py
```

Expected: hits. No output means the island does not carry the fix — stop.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_index/test_builder.py`:

```python
def test_repair_edges_restores_a_connection_missing_from_the_index(engine):
    """repair_edges re-derives edges from markdown without touching nodes or vectors."""
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="because X")
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    # Simulate the loss #123 used to cause, without depending on the bug still existing.
    engine.db.conn.execute("DELETE FROM edges WHERE target_id = ?", (id_b,))
    engine.db.conn.commit()

    # The cheap contract: repair must not re-embed or re-index anything.
    vectors_before = engine.db.conn.execute(
        "SELECT COUNT(*) FROM node_vectors").fetchone()[0]
    hashes_before = dict(engine.db.conn.execute("SELECT id, file_hash FROM nodes").fetchall())

    result = engine.builder.repair_edges()

    assert result["inserted"] == 1
    assert result["failed"] == 0
    assert result["scanned"] == 2
    row = engine.db.conn.execute(
        "SELECT source_id, reason FROM edges WHERE target_id = ?", (id_b,)
    ).fetchone()
    assert row["source_id"] == id_a
    assert row["reason"] == "because X"

    # Without these two, a repair_edges implemented as `full_rebuild()` plus a
    # COUNT(edges) delta would pass every other assertion in this file.
    assert engine.db.conn.execute(
        "SELECT COUNT(*) FROM node_vectors").fetchone()[0] == vectors_before
    assert dict(
        engine.db.conn.execute("SELECT id, file_hash FROM nodes").fetchall()) == hashes_before


def test_repair_edges_is_idempotent(engine):
    """A second run inserts nothing — the repair must not duplicate healthy rows."""
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="because X")
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    assert engine.builder.repair_edges()["inserted"] == 0
    assert engine.builder.repair_edges()["inserted"] == 0


def test_repair_edges_reports_a_failed_file_instead_of_swallowing_it(engine):
    """One unreadable file must be counted, not silently absorbed (#123).

    The repair keeps going — one corrupt file must not abort the other few thousand — but
    `failed` has to surface, or a run where every file failed reports success.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="because X")
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))
    engine.db.conn.execute("DELETE FROM edges WHERE target_id = ?", (id_b,))
    engine.db.conn.commit()

    # Corrupt B's file: valid path, unparseable frontmatter.
    engine.file_store._path_for(engine.file_store.load(id_b)).write_text(
        "---\nnot: [valid\n---\nbody", encoding="utf-8")

    result = engine.builder.repair_edges()

    assert result["failed"] == 1, "the unreadable file was swallowed"
    assert result["scanned"] == 2
    assert result["inserted"] == 1, "A's edge must still be repaired despite B failing"


def test_repair_edges_route_reports_partial_failure(engine_client):
    """The endpoint must not answer `repaired` when files failed."""
    resp = engine_client.post("/admin/repair-edges")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"status", "scanned", "inserted", "failed"}
    assert body["status"] == "repaired"  # clean store, nothing failed
```

The route test needs whatever client fixture `tests/test_api/` already uses for `/admin/rebuild`
— reuse it rather than inventing one, and put this test in that file if the fixture does not reach
`tests/test_index/`.

- [ ] **Step 3: Run and verify they FAIL**

```bash
H=$(mktemp -d); H=$(cd "$H" && pwd -P)
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$H .venv/bin/python -m pytest \
  tests/test_index/test_builder.py -q -k repair_edges > red.txt 2>&1
echo "PYTEST_EXIT=$?" >> red.txt
cat red.txt
```

Expected: `3 failed` with `AttributeError: 'IndexBuilder' object has no attribute
`repair_edges'`, plus the route test failing on a 404. Run the route test from wherever its
fixture lives.

- [ ] **Step 4: Implement `repair_edges`**

Add to `IndexBuilder`, directly after `full_rebuild`:

```python
    def repair_edges(self) -> dict[str, int]:
        """Reinsert edge rows declared in markdown but missing from the index (#123).

        Nodes, vectors and FTS are left alone — this is the cheap counterpart to
        `full_rebuild`, which re-embeds the whole store. Reuses `_index_file_edges`, so the
        FK guard and the reverse-edge canonicalisation behave exactly as in a normal index.

        Returns `{"scanned", "inserted", "failed"}`. `failed` is load-bearing: a run where
        every file failed to parse commits nothing, and reporting only the row delta would
        make that indistinguishable from a store that needed no repair.
        """
        # FileStore.list_paths takes L_mem. It MUST complete before the write transaction opens
        # L_db: every @serialized_memory_job background job goes L_mem -> L_db, and taking the
        # two in the opposite order deadlocks. Same trap incremental_update was fixed for — see
        # test_incremental_update_does_not_deadlock_against_a_memory_job.
        paths = list(self.file_store.list_paths())

        failed = 0
        before = self.db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        with self.db.transaction():
            for path in paths:
                try:
                    self._index_file_edges(path)
                except Exception as e:
                    # Edges are derived and best-effort: one unreadable file must not abort the
                    # repair of the other few thousand. Same rationale as full_rebuild's
                    # edge_failures counter. But it is COUNTED, never just logged.
                    failed += 1
                    logger.warning("repair_edges: failed on %s: %s", path, e)
        after = self.db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {"scanned": len(paths), "inserted": after - before, "failed": failed}
```

Two things this leans on. `_index_file_edges` calls `path.read_text()` directly instead of going
through a `FileStore` method, so it takes no lock of its own — hoisting `list_paths()` is enough.
And it uses `INSERT OR REPLACE` keyed on `(source_id, target_id, edge_type)`, so re-running it over
a healthy store rewrites identical rows and the count does not move, which is what the idempotence
test asserts.

- [ ] **Step 5: Run and verify they PASS**

```bash
H=$(mktemp -d); H=$(cd "$H" && pwd -P)
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$H .venv/bin/python -m pytest \
  tests/test_index/test_builder.py -q -k repair_edges > green.txt 2>&1
echo "PYTEST_EXIT=$?" >> green.txt
cat green.txt
```

Expected: `3 passed`, `PYTEST_EXIT=0` — plus the route test green in its own file.

- [ ] **Step 6: Expose it over HTTP**

The neighbouring `/rebuild` handler in `src/ormah/api/routes_admin.py:213` is three lines — engine
off `request.app.state`, one call, a dict with a `status` key:

```python
@router.post("/rebuild")
def rebuild_index(request: Request):
    engine = request.app.state.engine
    count = engine.rebuild_index()
    return {"status": "rebuilt", "nodes_indexed": count}
```

Insert directly below it, matching that shape:

```python
@router.post("/repair-edges")
def repair_edges(request: Request):
    """Reinsert edges declared in markdown but missing from the index (#123).

    The cheap alternative to /rebuild: no re-embedding, no FTS rebuild.

    `repaired_partial` is not cosmetic: some node files were unreadable and their
    connections were NOT restored, so the caller must not treat the store as whole.
    """
    engine = request.app.state.engine
    result = engine.builder.repair_edges()
    status = "repaired_partial" if result["failed"] else "repaired"
    return {"status": status, **result}
```

**Consider a facade.** `/rebuild` calls `engine.rebuild_index()`, not `engine.builder.<something>`.
Reaching through `engine.builder` from a route breaks that boundary (council round 1, Cursor —
non-blocking). If `MemoryEngine` gains a `repair_edges()` one-liner that forwards to the builder,
use it here and keep the route symmetric with its neighbour.

- [ ] **Step 7: Full suite, lint, island gates**

Run task 5's steps 1 through 5 verbatim against this island: import gate, full suite with clean
`HOME` and captured exit code, `ruff check src/ tests/`,
`git log --oneline upstream/main..HEAD` showing only your own commits, and
`git diff --name-only upstream/main...HEAD` free of any protected path.

- [ ] **Step 8: Commit, push, PR**

```bash
git add src/ormah/index/builder.py src/ormah/api/routes_admin.py tests/test_index/test_builder.py
git commit -m "feat(index): repair_edges — reinsert edges lost to #123 without a full rebuild

full_rebuild is the only existing recovery and it re-embeds the entire store.
This re-reads each node's connections and reinserts only the missing edge rows,
touching no nodes, vectors or FTS. Idempotent: it reuses _index_file_edges, so
the FK guard and the reverse-edge canonicalisation are unchanged.

Companion to the fix for #123, which stops new loss."
git push fork fix/123-repair-lost-edges
```

Then `/council-pr`, base `r-spade:main`. The body references the #123 fix PR as the companion that
stops the bleeding this one cleans up after.

Keep the Beta's numbers out of the PR body. `~/.local/share/ormah/memory/index.db` is a product of
`local-main`, ~729 commits and several unlanded PRs ahead of `upstream/main`.

- [ ] **Step 9: Prove it on the real store — needs André's go-ahead first**

This is the acceptance test, and it mutates the live store. Ask before running it.

```bash
env -u VIRTUAL_ENV -u PYTHONPATH /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python "$SCRATCH/drift.py"
curl -s -X POST http://localhost:8787/admin/repair-edges
env -u VIRTUAL_ENV -u PYTHONPATH /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python "$SCRATCH/drift.py"
```

Expected: **`missing_typed` goes to 0** — that is the acceptance criterion, not the symmetrised
`missing_live_target`.

`edges_inserted` will **not** generally equal the before-number, and asserting that it does is a
bug in the check, not in the repair (council round 1, Codex): `_index_file_edges` canonicalises
reverse edges, so two reciprocal markdown declarations collapse into one row. Compare the
before/after `missing_typed`, never the insert count against the miss count.

If `failed` comes back non-zero, the response says `repaired_partial` and the store is **not**
whole — report which files failed before re-running the drift script.

**The trap:** the running daemon serves `Tools/ormah`, not this island, so `/admin/repair-edges`
returns 404 until the Beta's tree carries the change *and* the daemon restarts. That restart is
André's call — pid 13585 is deliberately running code from 2026-08-20.
