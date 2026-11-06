> Overview: [00-overview.md](00-overview.md). Read it first; it carries the header, Global Constraints, and task order.

### Task 2: The completeness guard compares membership

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:207-221` (`_graph_is_fully_indexed`)
- Modify: `src/ormah/engine/memory_engine.py` imports (add `parse_node`)
- Test: `tests/test_engine/test_lifecycle_model_version.py`

**Interfaces:**
- Consumes: Task 1 — `_migrate_fsrs()` seeds unconditionally and reaches this guard only while the recorded version is below `LIFECYCLE_MODEL_VERSION`.
- Consumes (existing): `FileStore.list_paths() -> list[Path]` (globs `nodes/*.md` only; soft-deleted files live in `deleted/`), `ormah.store.markdown.parse_node(text) -> MemoryNode`.
- Consumes (existing test helpers, already defined at the top of the test file): `_make_node(engine) -> str`, `_version(engine) -> str | None`, `_unmigrated_meta(engine) -> None`.
- Produces: `_graph_is_fully_indexed() -> bool` returns `False` if any file under `nodes/` fails to parse, and otherwise returns whether the set of parsed `node.id` equals the set of `id` in the `nodes` table **and** no two files carry the same id.

**Council round 5 amendment (Codex, high @ 0.99).** A bare `set` of parsed ids discards
multiplicity: two `nodes/*.md` carrying the same `node.id` collapse to one entry while SQLite
holds one row, so `on_disk == indexed` reports a complete graph. The cardinality check this
task replaces *rejects* that case (2 files vs 1 row), so set equality alone is a regression of
the existing guard, not merely a gap. Verified in the code, not taken on the peer's word:
`file_store.py:161` names files `{type}_{slug}_{short_id}.md` with the slug derived from the
title, so one id with two titles is two coexisting files; `file_store.py:182` returns
`matches[0]` from an *unordered* glob, so the seed's `save()` may write to the duplicate that
is not the indexed one. Ormah's own path cannot create the duplicate (`_path_for` reuses the
existing file) — the realistic route is external Markdown dropped into `nodes/`, which is the
very scenario this plan exists to support. The fix keeps the cardinality guarantee alongside
membership.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_engine/test_lifecycle_model_version.py`:

```python
def test_equal_counts_with_different_membership_withhold_the_version(engine):
    """#236, council round 4 (Codex, high @ 0.97): len(list_paths()) ==
    COUNT(*) proves cardinality, not membership. An indexed file replaced
    externally by a different node while the process was stopped leaves both
    sides at the same count while the id sets diverge. Recording the version
    over that graph asserts a completed migration that never happened."""
    node_id = _make_node(engine)
    _unmigrated_meta(engine)

    # Swap one indexed file for an unindexed stranger: one file out, one file
    # in, so the counts stay identical and only the membership changes.
    target = next(
        path for path in engine.file_store.list_paths()
        if parse_node(path.read_text(encoding="utf-8")).id == node_id
    )
    target.unlink()
    stranger = MemoryNode(
        type=NodeType.fact,
        title="Stranger",
        content="On disk, never indexed",
    )
    engine.file_store.save(stranger)

    on_disk = len(engine.file_store.list_paths())
    indexed = engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert on_disk == indexed, "the fixture must keep the counts equal, or it proves nothing"

    engine._migrate_fsrs()

    assert _version(engine) is None, (
        "a version was recorded over a graph whose membership does not match the index"
    )
```

And, for the round-5 amendment, append this second test:

```python
def test_two_files_sharing_one_id_withhold_the_version(engine):
    """#236, council round 5 (Codex, high @ 0.99): a set of parsed ids discards
    multiplicity. Two Markdown files carrying the same node.id collapse to one
    entry while SQLite holds one row, so bare set equality calls the graph
    complete — a case the cardinality check this task replaces used to reject."""
    node_id = _make_node(engine)
    _unmigrated_meta(engine)

    # The store already holds the Self node, so assert against the baseline
    # rather than absolute counts.
    indexed = engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert len(engine.file_store.list_paths()) == indexed, (
        "the fixture must start from a balanced graph, or it proves nothing"
    )

    # A duplicate the way an external tool makes one: same id, different title,
    # therefore a different filename, written straight to disk so FileStore's
    # _path_for cannot reuse the existing file.
    original = next(
        path for path in engine.file_store.list_paths()
        if parse_node(path.read_text(encoding="utf-8")).id == node_id
    )
    node = parse_node(original.read_text(encoding="utf-8"))
    node.title = "Renamed by an external tool"
    duplicate = original.parent / f"fact_renamed-by-an-external-tool_{node.short_id}.md"
    duplicate.write_text(serialize_node(node), encoding="utf-8")

    assert len(engine.file_store.list_paths()) == indexed + 1, (
        "the duplicate must add one file and no row, or it proves nothing"
    )
    assert engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == indexed

    engine._migrate_fsrs()

    assert _version(engine) is None, (
        "a version was recorded over a graph holding two files for one id"
    )
```

Add `from ormah.store.markdown import parse_node, serialize_node` to the test file's imports if it is not already there.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
env HOME=/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah-wt-236/bfc80cca-2299-49d6-8031-0bef47a85395/scratchpad/fakehome \
  python -m pytest tests/test_engine/test_lifecycle_model_version.py -v -k "equal_counts_with_different_membership"
```

Expected: FAIL on `assert _version(engine) is None` — the value is `"2"`, because the counts match and the cardinality check reports the graph complete.

The `assert on_disk == indexed` line must PASS. If it fails, the fixture is wrong and the test proves nothing — fix the fixture before touching the implementation.

- [ ] **Step 3: Write the implementation**

First, add the import. In `src/ormah/engine/memory_engine.py`, directly after the existing line:

```python
from ormah.store.file_store import FileStore
```

add:

```python
from ormah.store.markdown import parse_node
```

Then, in `_graph_is_fully_indexed`, replace the docstring's closing paragraph and the two statements below it:

```python
        list_paths() globs nodes/*.md only, and soft-deleted files are moved to
        deleted/, so tombstones are absent from both sides of the comparison.
        """
        indexed = self.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        return len(self.file_store.list_paths()) == indexed
```

with:

```python
        Membership AND cardinality (#236, council rounds 4 and 5). Equal counts
        do not establish that every file has its row: a file replaced externally
        by a different node while the process was stopped leaves both sides at
        the same count while the id sets diverge. Membership alone is not enough
        either: a set discards multiplicity, so two files carrying the same id
        collapse to one entry against SQLite's single row and would read as
        complete (round 5, Codex high@0.99). Both checks are kept.

        A file that fails to parse returns False before any comparison, and the
        ordering is load-bearing. An unparseable file contributes no id, so it
        would drop out of BOTH sets and a bare set equality would call such a
        graph complete — the opposite of what this guard exists to say. Fail
        closed on both edges: unreadable file, or sets unequal in either
        direction.

        list_paths() globs nodes/*.md only, and soft-deleted files are moved to
        deleted/, so tombstones are absent from both sides of the comparison.
        """
        paths = self.file_store.list_paths()
        on_disk: set[str] = set()
        for path in paths:
            try:
                on_disk.add(parse_node(path.read_text(encoding="utf-8")).id)
            except Exception:
                logger.warning(
                    "Lifecycle completeness check: cannot read %s; treating the "
                    "graph as incomplete.",
                    path,
                )
                return False

        if len(on_disk) != len(paths):
            logger.warning(
                "Lifecycle completeness check: %d files carry only %d distinct "
                "node ids; treating the graph as incomplete.",
                len(paths),
                len(on_disk),
            )
            return False

        indexed = {
            row["id"] for row in self.db.conn.execute("SELECT id FROM nodes").fetchall()
        }
        return on_disk == indexed
```

Leave the docstring's first two paragraphs untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
env HOME=/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah-wt-236/bfc80cca-2299-49d6-8031-0bef47a85395/scratchpad/fakehome \
  python -m pytest tests/test_engine/test_lifecycle_model_version.py tests/test_index/test_builder.py tests/test_backup.py -v
```

Expected: all PASS. `test_no_version_is_recorded_while_a_file_is_missing_from_the_index` is the regression guard for the fail-closed ordering above — it writes `broken.md` and expects the marker withheld. If it fails, the `return False` on parse failure is missing or sits after the comparison instead of before it.

- [ ] **Step 4b: Pin that a store at the current version never parses the graph**

Council round 5 (Cursor, medium @ 0.93). This is a **tripwire, not a red-green test**: it
cannot go red against a correct implementation, by design. It exists so that moving the parse
loop above `if version >= LIFECYCLE_MODEL_VERSION` — which would put an O(N) full-store parse
on every start — turns something red. It belongs to Task 2, not Task 1: `parse_node` is not a
name in `memory_engine` until Step 3 adds the import, so patching it earlier raises
`AttributeError` instead of proving anything.

Append:

```python
def test_a_store_at_the_current_version_never_parses_the_graph(engine, monkeypatch):
    """#236, council round 5 (Cursor, medium @ 0.93): the early return must sit
    above the completeness guard. Nothing else pins that ordering — the
    latecomer test stays green either way — and losing it puts a full-store
    Markdown parse on every startup(), synchronous in the lifespan."""
    assert _version(engine) == "2"

    # Count calls rather than raise: _graph_is_fully_indexed wraps the parse in
    # `except Exception`, which swallows AssertionError and fails closed, so a
    # raising sentinel is invisible to the test and pins nothing.
    calls: list[str] = []
    real_parse = memory_engine.parse_node

    def _spy(text):
        calls.append(text)
        return real_parse(text)

    monkeypatch.setattr(memory_engine, "parse_node", _spy)

    engine._migrate_fsrs()

    assert not calls, (
        "a store at the current version parsed the graph: the early return no "
        "longer sits above the completeness guard, so every startup() now pays "
        "a full-store Markdown parse"
    )
    assert _version(engine) == "2"
```

Run:

```bash
env HOME=<fakehome> python -m pytest tests/test_engine/test_lifecycle_model_version.py \
  -v -k "never_parses_the_graph"
```

Expected: PASS.

**Then run the falsifier Cursor asked for, and record its output.** Temporarily move the
`if version >= LIFECYCLE_MODEL_VERSION: return` block *below* the `_graph_is_fully_indexed()`
call, re-run this one test, and confirm it goes **red** with `AssertionError: a store at the
current version parsed the graph`. Revert immediately — `git diff` must be clean of that move
before Step 5. A tripwire that cannot be shown to fire is not evidence.

- [ ] **Step 5: Run the wider suites for regressions**

Run:

```bash
env HOME=/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah-wt-236/bfc80cca-2299-49d6-8031-0bef47a85395/scratchpad/fakehome \
  python -m pytest tests/test_engine tests/test_cloud_*.py tests/test_backup.py tests/test_lifecycle.py -q
```

Expected: all PASS — **797** collected on the branch tip before this plan (the "794" this plan carried was measured earlier and went stale against the branch's own later commits), so the count should be 801: 797 plus the four tests this plan adds (one in Task 1, three in Task 2 after the round-5 amendment). Note `tests/test_cloud` is not a directory in this worktree; the cloud tests are the top-level `tests/test_cloud_*.py` files.

- [ ] **Step 6: Run ruff**

Run: `ruff check src/ tests/`

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git commit -m "fix(lifecycle): the completeness guard compares membership, not counts (#236)"
```
