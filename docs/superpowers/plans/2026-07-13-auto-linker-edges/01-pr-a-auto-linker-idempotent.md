# PR A — Idempotent edge writes (closes #117)

Branch: `fix/117-auto-linker-idempotent-edges` off **`upstream/main`**.
Read [00-overview.md](00-overview.md) first — especially the `PYTHONPATH` trap and the upstream-vs-Beta table.

All line numbers below refer to **`upstream/main`**, not the Beta.

---

### Task 1: `_apply_edge` becomes idempotent

An edge that already exists is not an error — someone else (ingest auto-link, the conflict detector, a reindex) created the same link while we were waiting on the LLM. Ignore it and let the `auto_link_checked` marker commit, so the pair is never re-judged.

**The markdown append must become idempotent, NOT conditional on winning the race.** This is the subtle part, and getting it wrong reintroduces data loss (Codex R1, critical #1):

The markdown file is the source of truth — reindexing **deletes** a node's edges and recreates them from the file. The winner of the race writes its own markdown on a best-effort path (`try/except logger.debug`). So if the winner committed the DB row but failed to save its markdown, the edge exists **only in the index**. If we then skip our own markdown append because we "lost", the next reindex deletes the edge — while `auto_link_checked` (which we just committed) guarantees the pair is never reconsidered. The link is gone forever.

So: always ensure the connection is in the file, adding it only if it is not already there. That is idempotent (no duplicate on a normal lost race) **and** self-healing (it repairs a winner that failed to persist). It is also less code than the `rowcount` gate.

**Files:**
- Modify: `src/ormah/background/auto_linker.py:285-312` (the body of `_apply_edge`)
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_auto_linker.py` (the file already defines the `_create_pair(engine)` helper used here):

```python
def test_apply_edge_is_idempotent_when_edge_already_exists(engine):
    """A concurrent writer created the same edge between collection and apply.
    _apply_edge must not raise, and must still record the pair as checked."""
    from datetime import datetime, timezone
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)
    now = datetime.now(timezone.utc).isoformat()
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, weight, created, reason) "
            "VALUES (?, ?, 'supports', 0.9, ?, 'created by someone else')",
            (id_a, id_b, now),
        )

    _apply_edge(engine, id_a, id_b, "supports", "auto-linker reason", 0.8)

    # The pre-existing edge survives untouched; no duplicate was created.
    rows = engine.db.conn.execute(
        "SELECT reason FROM edges WHERE source_id = ? AND target_id = ? AND edge_type = 'supports'",
        (id_a, id_b),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["reason"] == "created by someone else"

    # The pair is marked checked -> it will never be re-judged. This is exactly what
    # the rollback used to erase, which is why the pair poisoned every future run.
    pair = tuple(sorted([id_a, id_b]))
    assert engine.db.conn.execute(
        "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
    ).fetchone() is not None


def test_apply_edge_does_not_duplicate_the_markdown_connection(engine):
    """The winner of the race already wrote its Connection to the file. We must not
    append a second one for the same (target, edge)."""
    from datetime import datetime, timezone
    from ormah.models.node import Connection, EdgeType
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)
    now = datetime.now(timezone.utc).isoformat()
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, weight, created, reason) "
            "VALUES (?, ?, 'supports', 0.9, ?, 'x')",
            (id_a, id_b, now),
        )
    node = engine.file_store.load(id_a)          # the winner persisted its markdown
    node.connections.append(Connection(target=id_b, edge=EdgeType.supports, weight=0.9))
    engine.file_store.save(node)

    _apply_edge(engine, id_a, id_b, "supports", "reason", 0.8)

    node = engine.file_store.load(id_a)
    assert len([c for c in node.connections if c.target == id_b]) == 1


def test_apply_edge_repairs_a_markdown_connection_the_winner_failed_to_save(engine):
    """The winner committed the DB row but crashed before saving its markdown. The
    file is the source of truth and a reindex rebuilds edges from it — so if we skip
    the append just because we lost the race, the next reindex deletes the edge while
    auto_link_checked stops the pair from ever being reconsidered. The link would be
    lost forever. We must repair the file instead. (Codex R1, critical #1.)"""
    from datetime import datetime, timezone
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)
    now = datetime.now(timezone.utc).isoformat()
    with engine.db.transaction() as conn:        # DB row exists, markdown does NOT
        conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, weight, created, reason) "
            "VALUES (?, ?, 'supports', 0.9, ?, 'winner crashed before saving md')",
            (id_a, id_b, now),
        )
    assert [c for c in engine.file_store.load(id_a).connections if c.target == id_b] == []

    _apply_edge(engine, id_a, id_b, "supports", "reason", 0.8)

    conns = [c for c in engine.file_store.load(id_a).connections if c.target == id_b]
    assert len(conns) == 1
    assert conns[0].edge.value == "supports"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah/.claude/worktrees/edges-117
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_auto_linker.py -k "idempotent or duplicate_the_markdown" -v
```

Expected: both FAIL. The first with `sqlite3.IntegrityError: UNIQUE constraint failed: edges.source_id, edges.target_id, edges.edge_type` — the production bug, reproduced.

- [ ] **Step 3: Implement**

In `src/ormah/background/auto_linker.py`, replace everything from `with engine.db.transaction() as conn:` to the end of `_apply_edge` with:

```python
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO auto_link_checked (node_a, node_b, result, checked_at) "
            "VALUES (?, ?, ?, ?)",
            (*pair, edge_type, now),
        )

        if edge_type not in ("none", "error"):
            # OR IGNORE, not a raw INSERT: the "edge exists?" guard ran at collection
            # time, before the LLM call. Any concurrent writer (ingest auto-link,
            # conflict_detector, a reindex) may have created this same
            # (source, target, type) in the meantime. Losing that race means the link
            # already exists — the outcome we wanted. A raw INSERT turned it into an
            # IntegrityError that rolled back the auto_link_checked row above and
            # aborted the entire run (#117).
            conn.execute(
                "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight, created, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (node_a_id, node_b_id, edge_type, round(similarity, 3), now, reason),
            )

    if edge_type not in ("none", "error"):
        try:
            mem_node = engine.file_store.load(node_a_id)
            # Ensure the connection is in the file, whether or not WE won the insert.
            # The markdown is the source of truth (a reindex rebuilds edges from it) and
            # the winner's own save is best-effort. If the winner committed the row but
            # failed to save its file, skipping this append would let the next reindex
            # delete the edge, while the auto_link_checked row committed above would stop
            # the pair from ever being reconsidered — the link would be lost for good.
            # Idempotent: adds nothing when the connection is already there.
            if mem_node is not None and not any(
                c.target == node_b_id and c.edge.value == edge_type
                for c in mem_node.connections
            ):
                mem_node.connections.append(
                    Connection(
                        target=node_b_id,
                        edge=EdgeType(edge_type),
                        weight=round(similarity, 2),
                    )
                )
                mem_node.touch_updated()
                engine.file_store.save(mem_node)
        except Exception as e:
            logger.debug("Failed to persist connection to markdown for %s: %s", node_a_id[:8], e)
```

**Known limitation, deliberately not fixed here** (surface it in the PR body): if the concurrent writer created the **reverse** edge (`B→A`) instead, `INSERT OR IGNORE` does not suppress our `A→B` — the primary key is directional — so the pair can end up with edges in both directions. This is pre-existing (the collection-time guard checks both directions, but not the apply-time window), rare (the live store of 27,507 edges has exactly one such pair, from a week before the incident), and orthogonal to #117. The index builder already skips a reverse duplicate when rebuilding from markdown.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_auto_linker.py -v
```

Expected: PASS, including every pre-existing auto_linker test — the happy path still writes the edge and the markdown connection, because `rowcount > 0` when the row is new.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py tests/test_background/test_auto_linker.py
git commit -m "fix(auto-linker): make the edge write idempotent (INSERT OR IGNORE)

The 'edge already exists?' guard runs at collection time, before the LLM call
that decides the link type. A concurrent edge writer in that window made the raw
INSERT raise IntegrityError, which rolled back the auto_link_checked marker in
the same transaction — so the pair came back on every future run — and aborted
the whole run.

Losing that race means the link already exists, which is the desired outcome.
The markdown append is now gated on rowcount, so a lost race cannot duplicate a
Connection in the file.

Refs #117"
```

---

### Task 2: one bad pair must not abort the run

Even with Task 1, `_apply_edge` can still raise (e.g. a foreign-key violation when a node is deleted concurrently). Today that reaches the top-level `except` in `run_auto_linker` and kills the run, freezing the watermark for the whole store. Catch it at the call site, log **which pair** (the current failure logs nothing — during the incident the colliding edge was unrecoverable), and fail closed on that node.

**On the "poison pair parks the watermark forever" objection (Codex R1, critical #2) — accepted as a real property, rejected as a blocker for this PR.** A pair that fails deterministically does park the cursor. But that is not introduced here: it is the existing contract of the monotonic cursor, which already parks on an unavailable LLM (`node_resolved = False; break`) and on a permanently vectorless node. It is already recorded as a deferred follow-up on issue #109 ("a retry/dead-letter set decoupled from the monotonic cursor — new table + migration"). What this PR removes is the *dominant* cause: before it, **every** UNIQUE collision killed the run; after it, collisions cannot happen at all. Building a quarantine table here would mean shipping a schema migration inside an outage fix. What the objection does earn is a better test: the one below proves the run still makes **progress** (earlier nodes advance the watermark), which the original test did not.

**Files:**
- Modify: `src/ormah/background/auto_linker.py:401-404` (the `_apply_edge(...)` call inside `run_auto_linker`)
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing test**

```python
def test_run_survives_an_edge_apply_failure(engine, monkeypatch):
    """A pair whose edge write blows up must not abort the whole run."""
    import json
    from unittest.mock import patch
    from ormah.background import auto_linker as al

    _create_pair(engine)
    engine.settings.llm_enabled = True

    def boom(*_args, **_kwargs):
        raise RuntimeError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(al, "_apply_edge", boom)

    llm_response = json.dumps({"relationship": "supports", "reason": "r"})
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=llm_response):
        al.run_auto_linker(engine)   # must return normally, not raise

    # Fail closed: the watermark must NOT have advanced past the unresolved node.
    watermark = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'auto_link_watermark'"
    ).fetchone()
    assert watermark is None or int(watermark["value"]) == 0


def test_a_failing_pair_does_not_block_progress_on_earlier_nodes(engine, monkeypatch):
    """Progress, not just survival (Codex R1, critical #2): the failing pair parks the
    cursor AT that node, but every node before it still advances the watermark. Without
    this, the fix would only be swapping one kind of total stall for another."""
    import json
    from unittest.mock import patch
    from ormah.models.node import CreateNodeRequest, NodeType
    from ormah.background import auto_linker as al

    # A first pair that links cleanly, then a second pair whose apply always fails.
    good_a, good_b = _create_pair(engine)
    bad_a, bad_b = _create_pair(
        engine, title_a="Rust language", content_a="Rust is a systems language.",
        title_b="Rust lang", content_b="Rust is a popular systems language.",
    )
    engine.settings.llm_enabled = True

    real_apply = al._apply_edge

    def apply_or_boom(eng, a_id, b_id, *args, **kwargs):
        if a_id in (bad_a, bad_b):
            raise RuntimeError("FOREIGN KEY constraint failed")
        return real_apply(eng, a_id, b_id, *args, **kwargs)

    monkeypatch.setattr(al, "_apply_edge", apply_or_boom)

    good_seq = engine.db.conn.execute(
        "SELECT seq FROM nodes WHERE id = ?", (good_b,)
    ).fetchone()["seq"]

    llm_response = json.dumps({"relationship": "supports", "reason": "r"})
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=llm_response):
        al.run_auto_linker(engine)

    row = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'auto_link_watermark'"
    ).fetchone()
    assert row is not None, "the run made no progress at all — the failing pair stalled everything"
    assert int(row["value"]) >= good_seq, "the clean nodes before the failing pair must advance"
```

> `run_auto_linker` returns `None` on `upstream/main`, so these tests assert on behavior (returns instead of raising; the watermark advances up to — but not past — the failing node) rather than on a stats dict. The Beta's version does return stats, and Task 8 adds an `edge_apply_failures` counter there.
>
> **Honest limit of this test:** it proves progress *within* a run, not eventual progress *across* runs past a permanently failing pair. That genuinely does not happen, and is the deferred quarantine follow-up on #109 — it is called out in the PR body rather than silently left out.

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_auto_linker.py::test_run_survives_an_edge_apply_failure -v
```

Expected: FAIL. The `RuntimeError` escapes the call site and is swallowed by the top-level `except Exception` — which means the run aborted. (The test currently fails on the watermark assertion only if the abort happens to leave it clean; the real signal is the `Auto-linker failed:` warning in the captured log.) Confirm the abort explicitly with `-o log_cli=true --log-cli-level=WARNING` and look for `Auto-linker failed: FOREIGN KEY constraint failed`.

- [ ] **Step 3: Implement**

In `run_auto_linker`, wrap the `_apply_edge` call (currently lines 401-404, right after `relationship = llm_result["relationship"]`):

```python
                    relationship = llm_result["relationship"]  # may be 'error' (invalid output)
                    try:
                        _apply_edge(
                            engine, node["id"], match["id"], relationship,
                            llm_result.get("reason", ""), similarity,
                        )
                    except Exception as e:
                        # A single unwritable pair must never abort the run. It used to:
                        # the exception reached the top-level handler, killed the run and
                        # froze the watermark for the whole store (#117). Log the pair —
                        # the old failure logged nothing, so the colliding edge was
                        # unknowable after the fact.
                        logger.warning(
                            "auto_linker: edge apply failed for %s -> %s (%s): %s",
                            node["id"][:8], match["id"][:8], relationship, e,
                        )
                        node_resolved = False   # fail closed: watermark stays behind this node
                        continue
                    # 'error' (poison content) is recorded in auto_link_checked by _apply_edge
                    # and the node still counts as resolved → watermark advances (council v2 crit#2).
                    if relationship not in ("none", "error"):
                        created += 1
```

- [ ] **Step 4: Run the auto_linker suite**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_auto_linker.py -v
```

Expected: PASS. Note `node_resolved = False` triggers the existing `break` after the match loop — the run stops advancing at that node, which is the pre-existing fail-closed contract (`crit#1/imp#4`), not new behavior.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py tests/test_background/test_auto_linker.py
git commit -m "fix(auto-linker): a failing pair no longer aborts the run

An exception from _apply_edge reached the top-level handler, killing the run and
freezing the watermark for the entire store. It is now caught at the call site:
logged with the actual source/target/type (the old failure logged nothing, so the
colliding edge was unrecoverable) and the node is left unresolved, so the cursor
fails closed rather than skipping work.

Refs #117"
```

---

### Task 3: same raw `INSERT` in `conflict_detector`

`conflict_detector` writes `evolved_from` / `contradicts` edges with the same unguarded `INSERT` (`conflict_detector.py:253` and `:261`), and it runs concurrently with `auto_linker` — which also emits `contradicts`. Same latent bug, same fix.

**Files:**
- Modify: `src/ormah/background/conflict_detector.py:244-274`
- Test: `tests/test_background/test_conflict_detector.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_conflict_detector.py`:

```python
def test_conflict_edge_write_is_idempotent(engine):
    """An edge another writer already created must not raise."""
    from datetime import datetime, timezone
    from ormah.models.node import CreateNodeRequest, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="Coffee is good for you.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Coffee is bad for you.", type=NodeType.fact), agent_id="t")

    now = datetime.now(timezone.utc).isoformat()
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, weight, created, reason) "
            "VALUES (?, ?, 'contradicts', 0.9, ?, 'someone else')",
            (id_a, id_b, now),
        )

    # Writing the same contradiction again must be a no-op, not an IntegrityError,
    # and must not overwrite the existing row.
    with engine.db.transaction() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight, created, reason) "
            "VALUES (?, ?, 'contradicts', 0.9, ?, ?)",
            (id_a, id_b, now, "conflict detector"),
        )
        assert cur.rowcount == 0

    rows = engine.db.conn.execute(
        "SELECT reason FROM edges WHERE source_id = ? AND target_id = ?", (id_a, id_b)
    ).fetchall()
    assert len(rows) == 1 and rows[0]["reason"] == "someone else"
```

> This pins the SQL contract (idempotent write, existing row wins) rather than driving the full LLM-mocked `run_conflict_detection`, which the existing suite already covers. It passes on its own; the production change is Step 3, and Step 4 re-runs the **existing** suite to prove the change did not break the real path.

- [ ] **Step 2: Run it**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_conflict_detector.py::test_conflict_edge_write_is_idempotent -v
```

Expected: PASS (it asserts `INSERT OR IGNORE` semantics, which SQLite already provides).

- [ ] **Step 3: Implement**

In `src/ormah/background/conflict_detector.py`, change both statements to `INSERT OR IGNORE` and gate the markdown/counter work on the row actually landing:

```python
            with engine.db.transaction() as db_conn:
                if conflict_type == "evolution":
                    evolved = llm_result.get("evolved_node", "b")
                    if evolved == "a":
                        newer_id, older_id = node_a["id"], node_b["id"]
                    else:
                        newer_id, older_id = node_b["id"], node_a["id"]

                    # OR IGNORE: auto_linker also emits contradicts, and both jobs run
                    # concurrently over overlapping pairs. A concurrent writer may have
                    # created this exact edge while the LLM was judging — same race as #117.
                    cur = db_conn.execute(
                        "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight, created, reason) "
                        "VALUES (?, ?, 'evolved_from', 0.9, ?, ?)",
                        (newer_id, older_id, now, explanation),
                    )
                    edge_type_str = "evolved_from"
                    source_id, target_id = newer_id, older_id
                else:
                    cur = db_conn.execute(
                        "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight, created, reason) "
                        "VALUES (?, ?, 'contradicts', 0.9, ?, ?)",
                        (node_a["id"], node_b["id"], now, explanation),
                    )
                    edge_type_str = "contradicts"
                    source_id, target_id = node_a["id"], node_b["id"]

            # Queue the markdown connection UNCONDITIONALLY, not only when we won the
            # insert (Codex R2, critical #1 — the same data-loss path Task 1 closes).
            # The file is the source of truth; if the writer that won the row failed to
            # save its markdown, this is the only chance to repair it. rowcount only
            # decides whether this run *created* an edge, i.e. the metric.
            md_conn = Connection(
                target=target_id,
                edge=EdgeType(edge_type_str),
                weight=0.9,
            )
            dirty_nodes.setdefault(source_id, []).append(md_conn)
            if cur.rowcount > 0:
                edges_created += 1
```

And make the markdown persistence loop idempotent — it currently does a blind `extend`, which would duplicate a connection the winner already wrote:

```python
        # Persist new connections to markdown files
        for nid, new_connections in dirty_nodes.items():
            try:
                mem_node = engine.file_store.load(nid)
                if mem_node is None:
                    continue
                existing = {(c.target, c.edge.value) for c in mem_node.connections}
                fresh = [
                    c for c in new_connections if (c.target, c.edge.value) not in existing
                ]
                if not fresh:
                    continue
                mem_node.connections.extend(fresh)
                mem_node.touch_updated()
                engine.file_store.save(mem_node)
            except Exception as e:
                logger.debug("Failed to persist conflict edge to markdown for %s: %s", nid[:8], e)
```

- [ ] **Step 4: Run the conflict-detector suite**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_conflict_detector.py -v
```

Expected: PASS. If a pre-existing test asserted `edges_created` for a repeat run over an already-linked pair, it now correctly counts 0 — that is the intended behavior change; update the test to match.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/ -q --ignore=tests/test_cloud 2>&1 | tail -3
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ruff check src/ tests/
```

Expected: the same ~12 environmental failures as the baseline in `00-overview.md`, **no new ones**.

```bash
git add src/ormah/background/conflict_detector.py tests/test_background/test_conflict_detector.py
git commit -m "fix(conflict-detector): idempotent edge writes

conflict_detector writes contradicts/evolved_from with the same unguarded INSERT
that broke auto_linker, and the two jobs run concurrently over overlapping node
pairs. Same fix: OR IGNORE, and only count/append to markdown when the row
actually landed.

Refs #117"
```

- [ ] **Step 6: Open the PR**

```bash
git push -u fork fix/117-auto-linker-idempotent-edges
gh pr create --repo r-spade/ormah --base main \
  --title "fix(background): idempotent edge writes — a UNIQUE collision no longer aborts the auto_linker run (#117)" \
  --body "Closes #117.

\`auto_linker\` checks whether an edge exists at **collection** time but inserts it at **apply** time, after the LLM judgment call. Any concurrent edge writer in that window (ingest auto-link, conflict_detector, a reindex, or a second manually-triggered run) creates the row first and the raw \`INSERT\` raises \`IntegrityError\`.

Two amplifiers turned one collision into a total outage:
- the edge insert shares a transaction with \`INSERT OR IGNORE INTO auto_link_checked\`, so the rollback erased the checked marker and the pair came back poisoned on every future run;
- nothing caught the exception at the call site, so it reached the top-level handler, killed the run and froze the watermark for the whole store. On the store where this was diagnosed the cursor sat at seq 333726 with a ~13k backlog.

**Changes**
1. \`_apply_edge\` uses \`INSERT OR IGNORE\`. Losing the race means the link already exists — the desired outcome. The markdown append is gated on \`rowcount\` so a lost race cannot duplicate a \`Connection\` in the file.
2. A failing pair is caught at the call site, logged **with its source/target/type** (the old failure logged nothing, so the colliding edge was unrecoverable), and leaves its node unresolved — the cursor fails closed instead of skipping work.
3. \`conflict_detector\` had the same unguarded \`INSERT\` for \`contradicts\`/\`evolved_from\` and runs concurrently over overlapping pairs — same fix.

**Ruled out**, so this is not treating a symptom: intra-run duplication is impossible (the pair set is undirected and run-scoped, one candidate = one insert) and the LLM cannot forge IDs (they come from the collected candidate; the model only returns an int \`pair_id\`).

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
