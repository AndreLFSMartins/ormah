> Plan overview: [00-overview.md](00-overview.md)

### Task 3: Fix — exclude consolidated nodes from both discovery queries

**Files:**
- Modify: `src/ormah/background/consolidator.py:13-18` (docstring), `:39-41` (seed query), `:77-80` (member query)

**Interfaces:**
- Produces: module constant `_NOT_CONSOLIDATED: str` (SQL predicate over the `nodes` alias).

- [ ] **Step 1: Add the constant above `_find_consolidation_clusters`**

```python
# A consolidated node is terminal for discovery: never a seed, never a member. Feeding a
# summary back into consolidation writes a summary from summaries while the real sources sit
# in archival, unread (#261). The predicate is applied to both queries below.
_NOT_CONSOLIDATED = (
    "NOT EXISTS (SELECT 1 FROM node_tags WHERE node_id = nodes.id AND tag = 'consolidated')"
)
```

- [ ] **Step 2: Docstring + seed query**

Replace the docstring first line and the seed query:

```python
def _find_consolidation_clusters(engine, limit: int = 4) -> list[list[dict]]:
    """Find clusters of similar working-tier nodes for consolidation.

    Nodes tagged ``consolidated`` are terminal and are excluded as seed and as member (#261).
    Returns up to *limit* clusters, each a list of node dicts (max
    ``engine.settings.consolidation_max_cluster_nodes`` nodes).
    Does NOT call the LLM — pure similarity-based clustering.
    """
```

```python
    rows = conn.execute(
        "SELECT id, title, content, space FROM nodes "
        f"WHERE tier = 'working' AND {_NOT_CONSOLIDATED}"
    ).fetchall()
```

- [ ] **Step 3: Member query**

```python
            m_row = conn.execute(
                "SELECT id, title, content, space, tier FROM nodes "
                f"WHERE id = ? AND {_NOT_CONSOLIDATED}",
                (mid,),
            ).fetchone()
```
The existing `if m_row is None or m_row["tier"] != "working": continue` stays as is.

- [ ] **Step 4: Both new tests green, whole file green, ruff clean**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_background/test_consolidator.py -q > /tmp/t3.txt 2>&1; echo "PYTEST_EXIT=$?" >> /tmp/t3.txt; cat /tmp/t3.txt
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/ruff check src/ormah/background/consolidator.py tests/test_background/test_consolidator.py
```
Expected: all passed, `PYTEST_EXIT=0`; `All checks passed!`.

- [ ] **Step 5: Full suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > /tmp/t3-full.txt 2>&1; echo "PYTEST_EXIT=$?" >> /tmp/t3-full.txt; tail -5 /tmp/t3-full.txt
```
Expected: `PYTEST_EXIT=0`. Report the exact passed/failed counts from the file, not from memory.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/background/consolidator.py
git commit -m "fix(consolidator): consolidated nodes are terminal for cluster discovery (#261)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
