### Task 1: Full source content reaches the prompt

**Files:**
- Modify: `src/ormah/background/consolidator.py:212-217` (item building) and `:262-263` (apply)
- Test: `tests/test_background/test_consolidator.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks depend on. `_consolidate_cluster(engine, cluster)` keeps its
  signature and its `-> None` return.

**Context you need.** `_consolidate_cluster` builds a prompt from a list of node dicts
(`{"id", "title", "content", "space", "type"}`), calls the LLM, and hands the result to
`_apply_consolidation`, which creates the consolidated node, links `derived_from` edges and
demotes every source to `archival`. Line 216 renders each source as
`f"- [{title}]: {content[:300]}"`. That cap is the bug: 85.5% of real sources are longer than 300
chars, so the model is told to "preserve every concrete detail" of text it never saw, and the
sources are demoted right afterwards. `_apply_consolidation` is NOT touched in this task.

`_consolidate_cluster` imports `llm_generate` **inside the function body**. That is what makes
`monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)` work. Keep it there.

Upstream's `llm_generate` call is `llm_generate(engine.settings, prompt, json_mode=True)` — no
`response_format`. Your spy must accept that shape.

- [ ] **Step 1: Add the module import to the test file**

At the top of `tests/test_background/test_consolidator.py`, after the existing imports, add:

```python
from ormah.background import consolidator
```

- [ ] **Step 2: Write the failing regression test**

Append to `tests/test_background/test_consolidator.py`:

```python
def test_full_source_content_reaches_the_prompt(monkeypatch, consolidation_engine):
    """The consolidator must never summarize from a partial view of a source (#192)."""
    engine, ids = consolidation_engine
    marker = "MARKER-BEYOND-THE-OLD-300-CHAR-CAP"
    long_content = "padding. " * 600 + marker  # ~5400 chars, marker at the very end
    cluster = [
        {"id": ids[0], "title": "long source", "content": long_content, "space": None},
        {"id": ids[1], "title": "short source", "content": "A short one.", "space": None},
    ]
    captured = {}

    def spy(settings, prompt, json_mode=True, **kwargs):
        captured["prompt"] = prompt
        return json.dumps({"title": "t", "summary": "s", "type": "fact"})

    monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)

    consolidator._consolidate_cluster(engine, cluster)

    assert marker in captured["prompt"], "content past char 300 never reached the model"
    assert long_content in captured["prompt"]
    assert "A short one." in captured["prompt"]
```

- [ ] **Step 3: Run it and verify it fails**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py::test_full_source_content_reaches_the_prompt -v \
  > out.txt 2>&1; echo "PYTEST_EXIT=$?" >> out.txt; cat out.txt
```

Expected: FAIL on `assert marker in captured["prompt"]` — the marker sits past char 300.

- [ ] **Step 4: Remove the truncation**

In `src/ormah/background/consolidator.py`, replace:

```python
    # Build prompt
    items = []
    for node in cluster:
        title = node.get("title") or "Untitled"
        content = node.get("content", "")
        items.append(f"- [{title}]: {content[:300]}")
    items_text = "\n".join(items)
```

with:

```python
    # Build prompt from FULL content, never a slice (#192). The prompt below tells the model its
    # output "becomes the PRIMARY representation of this knowledge" and that it must "preserve
    # every concrete detail" -- instructions that are meaningless about text the model was never
    # shown, and destructive here because _apply_consolidation demotes every source to archival
    # immediately afterwards. A cluster too large for the prompt is split upstream in
    # run_consolidation; it is never trimmed.
    items = []
    for node in cluster:
        title = node.get("title") or "Untitled"
        content = node.get("content", "")
        items.append(f"- [{title}]: {content}")
    items_text = "\n".join(items)
```

- [ ] **Step 5: Run the test and verify it passes**

Same command as Step 3. Expected: PASS.

- [ ] **Step 6: Write the failing audit-log test**

Append to `tests/test_background/test_consolidator.py`:

```python
def test_consolidation_logs_source_and_summary_sizes(monkeypatch, consolidation_engine, caplog):
    """A lossy consolidation must be detectable after the fact (#192)."""
    engine, ids = consolidation_engine
    cluster = [
        {"id": ids[0], "title": "a", "content": "x" * 400, "space": None},
        {"id": ids[1], "title": "b", "content": "y" * 600, "space": None},
    ]

    def spy(settings, prompt, json_mode=True, **kwargs):
        return json.dumps({"title": "t", "summary": "z" * 120, "type": "fact"})

    monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)

    with caplog.at_level("INFO"):
        consolidator._consolidate_cluster(engine, cluster)

    assert "source_chars=1000" in caplog.text
    assert "summary_chars=120" in caplog.text
```

- [ ] **Step 7: Run it and verify it fails**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py::test_consolidation_logs_source_and_summary_sizes -v \
  > out.txt 2>&1; echo "PYTEST_EXIT=$?" >> out.txt; cat out.txt
```

Expected: FAIL — no such log line exists.

- [ ] **Step 8: Emit the audit log**

At the very end of `_consolidate_cluster`, replace:

```python
    node_ids = [n["id"] for n in cluster]
    _apply_consolidation(engine, node_ids, title, summary, node_type)
```

with:

```python
    node_ids = [n["id"] for n in cluster]
    new_id = _apply_consolidation(engine, node_ids, title, summary, node_type)
    # Audit trail (#192): the sources are demoted to archival by the call above, so this summary
    # becomes what gets read instead of them. Recording both sizes makes a consolidation that
    # shed too much visible in the logs without re-measuring the store by hand.
    logger.info(
        "consolidated %d sources into %s: source_chars=%d summary_chars=%d sources=%s",
        len(node_ids), new_id,
        sum(len(n.get("content") or "") for n in cluster), len(summary),
        ",".join(node_ids),
    )
```

- [ ] **Step 9: Run the whole consolidator suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py -v > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt; tail -30 out.txt
```

Expected: `PYTEST_EXIT=0`, both new tests pass, no pre-existing test broken.

- [ ] **Step 10: Commit**

```bash
git add src/ormah/background/consolidator.py tests/test_background/test_consolidator.py
git commit -m "fix(consolidator): show the LLM full source content, not content[:300] (#192)

The prompt told the model to preserve every concrete detail of text it had
never seen: on a live 1,843-node store, 254 of 297 consolidated originals
(85.5%) were longer than 300 chars, and 110,519 characters were never shown.
The sources are demoted to archival immediately after, so the withheld
content is displaced by a summary written without it.

Also records source_chars/summary_chars at INFO so a lossy consolidation is
detectable after the fact."
```
