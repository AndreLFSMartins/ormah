### Task 3: Heuristic detector on the ladder

**Files:**
- Modify: `src/ormah/background/session_watcher.py` — lines 40-41 (source constants) and the four
  `return` statements of `_node_usage_evidence` (lines 111-160)
- Test: `tests/test_background/test_usage_signal_strength.py` (create)

**Interfaces:**
- Consumes, from Task 2: `signal_strength.VERBATIM_NODE_ID`, `.VERBATIM_TITLE`,
  `.VERBATIM_SENTENCE`, `.OVERLAP_GATE`, `.HEURISTIC_SOURCE`, `.LLM_JUDGE_SOURCE`,
  `.token_overlap_strength(ratio)`
- Produces: nothing new. `_node_usage_evidence` keeps its `(bool, float, dict)` signature; only the
  float changes.

`_node_usage_evidence` reads `row` purely by key — `node_id`, `title`, `content`, `prompt_text` —
so a plain `dict` is a valid row and these tests need no database. **All five fixtures below were
executed against the real detector before this plan was written**; each one reaches the branch it
claims.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background/test_usage_signal_strength.py`:

```python
"""The heuristic detector places matches on the #218 ordinal ladder."""

import pytest

from ormah import signal_strength as ss
from ormah.background.session_watcher import _node_usage_evidence


def _row(node_id="a1b2c3d4-dead-beef-0000-000000000000", title="", content="", prompt_text=""):
    """_node_usage_evidence reads its row purely by key, so a dict is a valid row."""
    return {"node_id": node_id, "title": title, "content": content, "prompt_text": prompt_text}


def test_node_id_match_takes_the_top_heuristic_rung():
    referenced, strength, evidence = _node_usage_evidence(
        _row(content="anything"), "As memory a1b2c3d4 records, we chose X."
    )
    assert referenced
    assert evidence["match"] == "node_id"
    assert strength == ss.VERBATIM_NODE_ID


def test_title_match_takes_the_title_rung():
    referenced, strength, evidence = _node_usage_evidence(
        _row(
            title="Transcript watcher mines feedback usage",
            content="Some unrelated body text goes here.",
        ),
        "The transcript watcher mines feedback usage, as noted.",
    )
    assert referenced
    assert evidence["match"] == "title"
    assert strength == ss.VERBATIM_TITLE


def test_sentence_match_takes_the_sentence_rung():
    referenced, strength, evidence = _node_usage_evidence(
        _row(title="T", content="The consolidator summarizes from full source content."),
        "Recall that the consolidator summarizes from full source content today.",
    )
    assert referenced
    assert evidence["match"] == "sentence"
    assert strength == ss.VERBATIM_SENTENCE


def test_token_overlap_varies_with_its_ratio():
    """The defect #218 names: every token_overlap match used to report exactly 0.85."""
    referenced, strength, evidence = _node_usage_evidence(
        _row(title="Q", content="quantum entanglement decoherence topology manifold"),
        "We should consider decoherence, then topology, then the manifold, "
        "and finally quantum entanglement in that order.",
    )
    assert referenced
    assert evidence["match"] == "token_overlap"
    assert evidence["overlap_ratio"] == pytest.approx(1.0)
    assert strength == pytest.approx(ss.token_overlap_strength(1.0))
    assert strength != 0.85


def test_no_match_carries_no_strength():
    referenced, strength, evidence = _node_usage_evidence(
        _row(title="Z", content="alpha beta gamma delta"), "Completely unrelated prose here."
    )
    assert not referenced
    assert evidence["match"] == "none"
    assert strength == 0.0


def test_every_heuristic_rung_sits_inside_its_band():
    """The verbatim rungs must stay above the judge band, the overlap rung below implicit."""
    assert ss.VERBATIM_SENTENCE > ss.JUDGE_HI
    assert ss.OVERLAP_FLOOR + ss.OVERLAP_SPAN < ss.IMPLICIT
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_usage_signal_strength.py -q > /tmp/218-t3-red.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t3-red.txt
tail -20 /tmp/218-t3-red.txt
```

Expected: 4 failed, 2 passed. The four failures are the rung assertions — `1.0 != 0.98`,
`0.95 != 0.94`, `0.9 != 0.92`, and `0.85 != 0.5495...`. `test_no_match_carries_no_strength` and
`test_every_heuristic_rung_sits_inside_its_band` pass already.

- [ ] **Step 3: Import the ladder and reuse its source labels**

In `src/ormah/background/session_watcher.py`, add to the import block (after
`from ormah.engine.memory_engine import MemoryEngine`, line 19):

```python
from ormah import signal_strength
```

Then replace lines 40-41:

```python
_HEURISTIC_SOURCE = "transcript_watcher_heuristic"
_LLM_JUDGE_SOURCE = "transcript_watcher_llm_judge"
```

with:

```python
_HEURISTIC_SOURCE = signal_strength.HEURISTIC_SOURCE
_LLM_JUDGE_SOURCE = signal_strength.LLM_JUDGE_SOURCE
```

Keep the private aliases: about twenty call sites use them, and renaming those is churn this task
does not need. Lines 42-43 (`_HEURISTIC_AFFINITY_SOURCE`, `_LLM_JUDGE_AFFINITY_SOURCE`) are **not**
touched — they belong to #272.

- [ ] **Step 4: Put the four returns on the ladder**

In `_node_usage_evidence`, four edits:

```python
        return True, 1.0, {"match": "node_id", "short_id": short_id}
```
becomes
```python
        return True, signal_strength.VERBATIM_NODE_ID, {"match": "node_id", "short_id": short_id}
```

```python
        return True, 0.95, {"match": "title", "title": title}
```
becomes
```python
        return True, signal_strength.VERBATIM_TITLE, {"match": "title", "title": title}
```

```python
            return True, 0.9, {"match": "sentence", "text": sentence[:160]}
```
becomes
```python
            return True, signal_strength.VERBATIM_SENTENCE, {
                "match": "sentence",
                "text": sentence[:160],
            }
```

```python
    if len(overlap) >= 4 and overlap_ratio >= 0.5:
        return True, min(0.85, 0.45 + overlap_ratio), {
            "match": "token_overlap",
            "overlap": overlap[:12],
            "overlap_ratio": round(overlap_ratio, 3),
        }
```
becomes
```python
    if len(overlap) >= 4 and overlap_ratio >= signal_strength.OVERLAP_GATE:
        return True, signal_strength.token_overlap_strength(overlap_ratio), {
            "match": "token_overlap",
            "overlap": overlap[:12],
            "overlap_ratio": round(overlap_ratio, 3),
        }
```

The admission gate now reads `OVERLAP_GATE` rather than a repeated `0.5`. The ladder's floor is
*defined* as the value at that gate, so a literal here could drift away from it and silently break
`token_overlap_strength(gate) == OVERLAP_FLOOR`.

The final `return False, 0.0, {...}` is left alone: it is already the polarity-zero convention.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_usage_signal_strength.py -q > /tmp/218-t3-green.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t3-green.txt
tail -5 /tmp/218-t3-green.txt
```

Expected: `PYTEST_EXIT=0`, 6 passed.

- [ ] **Step 6: Prove the watcher suite did not regress**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_session_watcher.py tests/test_engine/test_confirmed_use_contract.py \
  -q > /tmp/218-t3-regress.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t3-regress.txt
tail -20 /tmp/218-t3-regress.txt
```

Expected: `PYTEST_EXIT=0`.

If a `test_session_watcher.py` test fails on a hardcoded `0.85`/`0.95`/`0.9`/`1.0` strength, update
that assertion to the ladder constant — the value moved by design. If
`test_confirmed_use_contract.py` fails, **stop and report**: `strength` was supposed to have no
readers, and a failure there falsifies the premise the whole design rests on.

- [ ] **Step 7: Lint and commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
git add src/ormah/background/session_watcher.py tests/test_background/test_usage_signal_strength.py
git commit -m "fix(feedback): place heuristic matches on the ordinal ladder (#218)

The four match kinds returned 1.0/0.95/0.9 and a token_overlap value that
saturated at 0.85 before its own entry gate could admit it, so a barely-passing
match and a ratio-7.5 match reported identically.

They now read the ladder, and token_overlap varies with its ratio. The
admission gate reads OVERLAP_GATE rather than a repeated literal, because the
ladder's floor is defined as the value at that gate.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```
