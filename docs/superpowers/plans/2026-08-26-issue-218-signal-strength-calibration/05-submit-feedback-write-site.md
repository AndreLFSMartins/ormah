### Task 5: `submit_feedback` stops hardcoding 1.0

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` — the import block, and the literal `1.0` in the
  `signals` INSERT inside `submit_feedback` (the parameter tuple around line 2792)
- Test: `tests/test_engine/test_feedback_signal_strength.py` (create)

**Interfaces:**
- Consumes, from Task 2: `signal_strength.feedback_strength(source, signal)`, `.EXPLICIT`,
  `.IMPLICIT`, `.UNKNOWN`
- Produces: nothing new.

Today an explicit user confirmation and an implicit agent self-assessment are stored with an
identical `strength` of `1.0`; only `source` tells them apart. `affinity_implicit_weight = 0.8`
already encodes the judgment that they differ, but the signals path ignores it — and this task does
**not** read that setting, because it is the affinity boost weight and coupling the two would make
changing one silently change the other.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_feedback_signal_strength.py`:

```python
"""submit_feedback records a real strength, not a hardcoded 1.0 (#218)."""

import pytest

from ormah import signal_strength as ss
from ormah.models.node import CreateNodeRequest


def _node_with_whisper(engine, title):
    """Create a node and a whisper_log row submit_feedback can resolve."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="caching architecture note for the strength ladder",
        title=title,
        type="fact",
        tier="working",
    ))
    engine.recall_search("caching architecture", limit=10)
    row = engine.db.conn.execute(
        "SELECT id FROM whisper_log WHERE node_id = ? ORDER BY id DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    assert row is not None, "no whisper_log row was created — check the surface used"
    return node_id, row["id"]


def _stored_strength(engine, whisper_log_id):
    return engine.db.conn.execute(
        "SELECT strength FROM signals WHERE whisper_log_id = ? "
        "AND signal_type = 'feedback_submitted'",
        (whisper_log_id,),
    ).fetchone()["strength"]


@pytest.mark.parametrize(
    "source,expected",
    [
        ("explicit", ss.EXPLICIT),
        ("implicit", ss.IMPLICIT),
        ("auto_heuristic", ss.UNKNOWN),
    ],
)
def test_each_feedback_source_records_its_own_rung(engine, source, expected):
    node_id, log_id = _node_with_whisper(engine, f"Caching {source}")
    engine.submit_feedback(node_id, signal=1, source=source, whisper_log_id=log_id)
    assert _stored_strength(engine, log_id) == expected


def test_explicit_and_implicit_no_longer_collide(engine):
    """Both used to store exactly 1.0, leaving source as the only discriminator."""
    explicit_id, explicit_log = _node_with_whisper(engine, "Caching E")
    implicit_id, implicit_log = _node_with_whisper(engine, "Caching I")
    engine.submit_feedback(explicit_id, signal=1, source="explicit", whisper_log_id=explicit_log)
    engine.submit_feedback(implicit_id, signal=1, source="implicit", whisper_log_id=implicit_log)
    assert _stored_strength(engine, explicit_log) != _stored_strength(engine, implicit_log)


def test_negative_feedback_keeps_its_channel_rung(engine):
    """strength is the evidence for THIS row's polarity, so -1 is not weaker."""
    node_id, log_id = _node_with_whisper(engine, "Caching N")
    engine.submit_feedback(node_id, signal=-1, source="explicit", whisper_log_id=log_id)
    assert _stored_strength(engine, log_id) == ss.EXPLICIT
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/test_feedback_signal_strength.py -q > /tmp/218-t5-red.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t5-red.txt
tail -20 /tmp/218-t5-red.txt
```

Expected: 3 failed, 2 passed. `implicit` and `auto_heuristic` store `1.0` instead of their rungs,
and the collision test fails because both sides read `1.0`. The `explicit` parametrisation and the
negative test already pass — `EXPLICIT` is `1.0`.

- [ ] **Step 3: Import the ladder into the engine**

In `src/ormah/engine/memory_engine.py`, add to the `ormah` import block:

```python
from ormah import signal_strength
```

- [ ] **Step 4: Replace the literal**

In `submit_feedback`, in the parameter tuple of the `INSERT INTO signals` statement:

```python
                    "feedback_submitted",
                    signal,
                    1.0,
                    source,
```
becomes
```python
                    "feedback_submitted",
                    signal,
                    signal_strength.feedback_strength(source, signal),
                    source,
```

Do not touch `_CONFIRMED_USE_SOURCES` (line 56) or `_claim_confirmed_use` — those are #272.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/test_feedback_signal_strength.py \
  tests/test_engine/test_confirmed_use_contract.py -q > /tmp/218-t5-green.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t5-green.txt
tail -10 /tmp/218-t5-green.txt
```

Expected: `PYTEST_EXIT=0`, 5 passed in the new file.

A failure in `test_confirmed_use_contract.py` means **stop and report** — see Task 4 Step 5.

- [ ] **Step 6: Lint and commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
git add src/ormah/engine/memory_engine.py tests/test_engine/test_feedback_signal_strength.py
git commit -m "fix(feedback): submit_feedback records a real strength (#218)

The signals INSERT declared strength in its column list and then passed a
literal 1.0, so an explicit user confirmation and an implicit agent
self-assessment were stored identically and source was the only discriminator.

Each source now maps onto its own rung of the #218 ladder, fail-closed for
sources the ladder does not know. affinity_implicit_weight is deliberately not
reused: it is the affinity boost weight, and coupling the two would make
changing one silently change the other.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```
