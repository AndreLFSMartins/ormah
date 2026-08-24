### Task 3: Budget arithmetic and the pure split function

**Files:**
- Modify: `src/ormah/background/consolidator.py` (prompt template at `:219-248`, new helpers)
- Test: `tests/test_background/test_consolidator.py`

**Interfaces:**
- Consumes: `Settings.consolidation_max_prompt_chars` from Task 2 — used by Task 4, not here.
  `_split_cluster_to_fit` takes a plain int budget and reads no settings.
- Produces, all in `ormah.background.consolidator`:
  - `_CONSOLIDATE_PROMPT: str` — module constant with a single `{items_text}` slot
  - `_prompt_overhead_chars() -> int`
  - `_render_item(node: dict) -> str`
  - `_item_chars(node: dict) -> int`
  - `_split_cluster_to_fit(cluster: list[dict], budget_chars: int) -> list[list[dict]]`

**Context you need.** The prompt is currently an inline f-string inside `_consolidate_cluster`.
To know what the template itself costs, it has to become a module constant that can be rendered
with an empty items block. A hardcoded number would go stale the first time someone edits the
prompt, and this one is load-bearing: it is subtracted from the operator's budget.

The f-string already escapes the JSON braces as `{{` / `}}`, and `str.format` uses the exact same
escaping, so the prompt text moves **verbatim** — the only edits are dropping the `f` prefix and
calling `.format(items_text=items_text)`.

`_split_cluster_to_fit` is a **pure function**: no engine, no settings, no I/O beyond a warning
log. It packs greedily in the order it receives, which is the order `_find_consolidation_clusters`
produces (seed first, then descending similarity), so the most similar sources stay together in
the first sub-cluster. It does NOT apply `consolidation_min_cluster_size` — dropping short
sub-clusters is Task 4's job, and keeping settings out of here is what makes it trivially
testable.

`tests/test_background/test_consolidator.py` must already have `from ormah.background import
consolidator` at the top (added in Task 1). Add it if it is missing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_consolidator.py`:

```python
class TestSplitClusterToFit:
    """#192: a cluster that does not fit is SPLIT, never truncated."""

    @staticmethod
    def _node(nid: str, chars: int) -> dict:
        return {"id": nid, "title": "t", "content": "x" * chars, "space": None}

    def test_cluster_that_fits_is_returned_whole(self):
        cluster = [self._node("a", 100), self._node("b", 100)]
        assert consolidator._split_cluster_to_fit(cluster, 10_000) == [cluster]

    def test_oversized_cluster_is_split_preserving_order(self):
        cluster = [self._node(x, 400) for x in ("a", "b", "c", "d")]
        parts = consolidator._split_cluster_to_fit(cluster, 900)

        assert [[n["id"] for n in p] for p in parts] == [["a", "b"], ["c", "d"]]
        flat = [n["id"] for p in parts for n in p]
        assert flat == ["a", "b", "c", "d"]        # order preserved
        assert len(flat) == len(set(flat))          # no duplicates

    def test_node_larger_than_the_whole_budget_is_dropped_with_a_warning(self, caplog):
        cluster = [self._node("small", 100), self._node("huge", 5_000), self._node("s2", 100)]
        with caplog.at_level("WARNING"):
            parts = consolidator._split_cluster_to_fit(cluster, 1_000)

        assert [[n["id"] for n in p] for p in parts] == [["small", "s2"]]
        assert "huge" in caplog.text

    def test_no_source_is_ever_truncated(self):
        cluster = [self._node("a", 400), self._node("b", 400)]
        parts = consolidator._split_cluster_to_fit(cluster, 500)
        for part in parts:
            for node in part:
                assert len(node["content"]) == 400

    def test_exhausted_budget_returns_nothing_and_warns(self, caplog):
        with caplog.at_level("WARNING"):
            assert consolidator._split_cluster_to_fit([self._node("a", 10)], 0) == []
        assert "budget" in caplog.text.lower()


def test_prompt_overhead_is_computed_from_the_template():
    overhead = consolidator._prompt_overhead_chars()
    assert overhead == len(consolidator._CONSOLIDATE_PROMPT.format(items_text=""))
    assert 1_000 < overhead < 10_000  # sanity: the template is real prose, not a stub
```

- [ ] **Step 2: Run them and verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py -k "SplitCluster or prompt_overhead" -v \
  > out.txt 2>&1; echo "PYTEST_EXIT=$?" >> out.txt; cat out.txt
```

Expected: FAIL — `AttributeError: module 'ormah.background.consolidator' has no attribute
'_split_cluster_to_fit'`.

- [ ] **Step 3: Lift the prompt into a module constant (mechanical — do not retype the text)**

In `src/ormah/background/consolidator.py`:

1. Cut the entire statement that starts with `    prompt = f"""\` and ends with the closing
   `}}"""` — the block containing "You are consolidating a cluster..." through the JSON object
   example (upstream lines 219–248).
2. Paste it at module level, immediately after the `logger = logging.getLogger(__name__)` line.
3. In the pasted copy, change the opening line from `    prompt = f"""\` to
   `_CONSOLIDATE_PROMPT = """\` — dedent it, rename it, and **drop the `f` prefix**. Touch
   nothing else: the `{{`/`}}` JSON escaping and the `{items_text}` slot mean exactly the same
   thing to `str.format` as they did to the f-string.
4. Where the statement used to be inside `_consolidate_cluster`, put:

```python
    prompt = _CONSOLIDATE_PROMPT.format(items_text=items_text)
```

Verify the move was textually neutral before moving on:

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "
from ormah.background import consolidator as c
p = c._CONSOLIDATE_PROMPT.format(items_text='ITEMS')
assert 'ITEMS' in p and '{items_text}' not in p
assert p.count('{') == p.count('}')          # JSON braces unescaped exactly once
assert p.rstrip().endswith('}')
print('template ok:', len(p), 'chars')"
```

- [ ] **Step 4: Add the arithmetic and the split**

Immediately after `_CONSOLIDATE_PROMPT`, add:

```python
def _prompt_overhead_chars() -> int:
    """Chars the template costs around the items block.

    Computed from the template itself so it cannot go stale when the prompt is edited -- this
    number is subtracted from the operator's budget, so a hardcoded copy that drifted would
    silently overrun the window the consolidation route asks for.
    """
    return len(_CONSOLIDATE_PROMPT.format(items_text=""))


def _render_item(node: dict) -> str:
    """One source as it appears in the items block. FULL content -- never a slice (#192)."""
    title = node.get("title") or "Untitled"
    content = node.get("content", "")
    return f"- [{title}]: {content}"


def _item_chars(node: dict) -> int:
    """What one source costs in the prompt: its rendered line plus the newline that joins it."""
    return len(_render_item(node)) + 1


def _split_cluster_to_fit(cluster: list[dict], budget_chars: int) -> list[list[dict]]:
    """Split *cluster* into sub-clusters whose rendered items fit within *budget_chars*.

    Greedy, in the order given -- which is the order ``_find_consolidation_clusters`` produces
    (seed first, then descending similarity), so the most similar sources stay together in the
    first sub-cluster.

    A source is NEVER truncated (#192): one that does not fit the remainder opens a new
    sub-cluster, and one larger than the whole budget is dropped entirely and left where it is.
    Losing a consolidation is recoverable -- the node stays working and keeps being whispered.
    Summarizing from a partial view is not, because the sources are demoted to archival the
    moment the summary is written.

    Sub-clusters shorter than ``consolidation_min_cluster_size`` are NOT filtered here; that is
    the caller's decision, which keeps this function pure and settings-free.
    """
    if budget_chars <= 0:
        logger.warning(
            "consolidation prompt budget is %d chars after the template's own overhead; "
            "raise ORMAH_CONSOLIDATION_MAX_PROMPT_CHARS -- nothing can be consolidated",
            budget_chars,
        )
        return []

    parts: list[list[dict]] = []
    current: list[dict] = []
    used = 0

    for node in cluster:
        cost = _item_chars(node)
        if cost > budget_chars:
            logger.warning(
                "consolidation source %s costs %d chars, more than the whole prompt budget "
                "(%d); it stays put rather than being summarized from a partial view",
                node.get("id"), cost, budget_chars,
            )
            continue
        if current and used + cost > budget_chars:
            parts.append(current)
            current = []
            used = 0
        current.append(node)
        used += cost

    if current:
        parts.append(current)
    return parts
```

- [ ] **Step 5: Run the new tests and verify they pass**

Same command as Step 2. Expected: 6 passed, `PYTEST_EXIT=0`.

- [ ] **Step 6: Confirm the move changed no behavior**

Task 1's regression test proves the prompt still carries full content after the move:

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt; tail -20 out.txt
```

Expected: `PYTEST_EXIT=0`.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/consolidator.py tests/test_background/test_consolidator.py
git commit -m "feat(consolidator): prompt budget arithmetic and pure cluster split (#192)

The prompt template becomes a module constant so its overhead is computed
from itself rather than hardcoded. _split_cluster_to_fit packs sources
greedily in similarity order and never truncates one: a source that does not
fit opens a new sub-cluster, and one larger than the whole budget is left
alone."
```
