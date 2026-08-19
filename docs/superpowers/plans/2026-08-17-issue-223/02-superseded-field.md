# Task 2: `superseded_by` on the model and in Markdown

**Files:**
- Modify: `src/ormah/models/node.py` (symbol: `MemoryNode`)
- Modify: `src/ormah/store/markdown.py` (symbols: `parse_node`, `serialize_node`)
- Test: `tests/test_store/test_markdown.py`

**Interfaces:**
- Produces: `MemoryNode.superseded_by: str | None`, read by Task 5's promotion gate and written by Task 6's `_mark_superseded`.

**Deliberately NOT on `UpdateNodeRequest`.** This is policy state written by the consolidator; no agent sets it. Adding it there would expose a way to unblock a superseded node through the public API, which is exactly the escape #191 withheld.

---

- [ ] **Step 1: Write the failing roundtrip tests**

Append to `tests/test_store/test_markdown.py`:

```python
def test_superseded_by_survives_a_markdown_roundtrip():
    node = MemoryNode(type=NodeType.fact, content="a superseded source")
    node.superseded_by = "11111111-2222-3333-4444-555555555555"

    parsed = parse_node(serialize_node(node))

    assert parsed.superseded_by == "11111111-2222-3333-4444-555555555555"


def test_superseded_by_is_absent_from_frontmatter_when_none():
    """Without this assertion, writing `superseded_by: null` pollutes every node file."""
    node = MemoryNode(type=NodeType.fact, content="an ordinary node")

    text = serialize_node(node)

    assert "superseded_by" not in text
    assert parse_node(text).superseded_by is None


def test_a_file_written_before_223_parses_to_none():
    node = MemoryNode(type=NodeType.fact, content="written by an older build")
    text = serialize_node(node)
    assert parse_node(text).superseded_by is None


def test_stability_is_not_retroactively_rescaled():
    """#191 forbids rescaling values that predate the new default."""
    node = MemoryNode(type=NodeType.fact, content="an old node", stability=1.0)
    assert parse_node(serialize_node(node)).stability == 1.0


def test_a_file_with_no_stability_key_parses_to_one_not_the_new_default():
    """parse_node's `meta.get("stability", 1.0)` fallback must stay 1.0."""
    text = (
        "---\n"
        "id: 99999999-8888-7777-6666-555555555555\n"
        "type: fact\n"
        "tier: working\n"
        "source: agent:test\n"
        "created: 2026-01-01T00:00:00Z\n"
        "updated: 2026-01-01T00:00:00Z\n"
        "last_accessed: 2026-01-01T00:00:00Z\n"
        "---\n"
        "a node from before FSRS\n"
    )
    assert parse_node(text).stability == 1.0
```

Match the file's existing imports; it should already import `parse_node`, `serialize_node`, `MemoryNode` and `NodeType`. Add any that are missing.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_store/test_markdown.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: the printed path contains `ormah-wt-223/`. `ValueError: "MemoryNode" object has no field "superseded_by"` on the first test. The last two tests should already pass — they pin behaviour this task must not break.

- [ ] **Step 3: Add the field to the model**

In `src/ormah/models/node.py`, inside `class MemoryNode`, add the field immediately after `deleted_at`:

```python
    superseded_by: str | None = None  # id of the consolidation node that replaced this one; blocks automatic promotion (#223)
```

Do **not** add it to `UpdateNodeRequest`.

- [ ] **Step 4: Parse it**

In `src/ormah/store/markdown.py`, inside `parse_node`, add to the `MemoryNode(...)` call immediately after `deleted_at=deleted_at,`:

```python
        superseded_by=meta.get("superseded_by"),
```

- [ ] **Step 5: Serialize it only when set**

In `src/ormah/store/markdown.py`, inside `serialize_node`, add immediately after the `deleted_at` block, following the existing optional-field pattern:

```python
    if node.superseded_by is not None:
        meta["superseded_by"] = node.superseded_by
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_store/test_markdown.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`.

- [ ] **Step 7: Check nothing that serializes a node regressed**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_store/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`.

- [ ] **Step 8: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add src/ormah/models/node.py src/ormah/store/markdown.py tests/test_store/test_markdown.py
git commit -m "feat(models): superseded_by records consolidation provenance (#223)"
git show --stat HEAD
```

Expected: exactly three files.
