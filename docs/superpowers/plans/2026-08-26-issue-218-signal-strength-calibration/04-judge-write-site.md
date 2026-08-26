### Task 4: Judge records use the judge band

**Files:**
- Modify: `src/ormah/background/session_watcher.py:549` — `"strength": confidence` in the
  `judge_records.append({...})` block
- Modify: `tests/test_background/test_session_watcher.py:427` — the one existing assertion in the
  repository that pins a strength value
- Test: `tests/test_background/test_usage_signal_strength.py` (append)

**Interfaces:**
- Consumes, from Task 2: `signal_strength.judge_strength(confidence, min_confidence, polarity)`,
  `.JUDGE_LO`, `.JUDGE_HI`
- **Requires Task 3 first.** This task appends to the test file Task 3 creates and relies on its
  module-level `import pytest` and `from ormah import signal_strength as ss`, and on the
  `from ormah import signal_strength` import Task 3 adds to `session_watcher.py`. Running this
  task against a repository where Task 3 has not landed will fail at import.
- Produces: nothing new.

**One existing assertion breaks, and only one.** A sweep of every `strength` occurrence across the
whole upstream test tree found three: `test_session_watcher.py:427` (a value assertion — this one
breaks), `test_whisper_log_cleanup.py:69` (an INSERT column list), and
`test_feedback_schema.py:177` (a column-name check). The latter two are unaffected.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_usage_signal_strength.py`:

```python
import json
from unittest.mock import patch

from ormah.background.session_watcher import _record_whisper_usage_signals
from ormah.models.node import CreateNodeRequest
from ormah.transcript.parser import parse_transcript
from tests.test_background.test_session_watcher import (
    _LLM_PATCH,
    _insert_injected_whisper_log,
    _write_turn_jsonl,
)


def _judged(engine, tmp_path, *, verdict, confidence, slug):
    """Drive one whisper through the judge and return its stored signal row."""
    prompt = "How should we handle the blue deployment rollback?"
    response = "Nothing in particular comes to mind about that."
    transcript_path = tmp_path / f"{slug}.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Roll back a blue deployment by repointing the load balancer first.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id=slug, prompt=prompt
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    llm_response = json.dumps({"verdicts": [{
        "whisper_log_id": whisper_log_id,
        "verdict": verdict,
        "confidence": confidence,
        "reason": "fixture",
    }]})
    with patch(_LLM_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    return engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ? "
        "AND source = 'transcript_watcher_llm_judge'",
        (whisper_log_id,),
    ).fetchone()


def test_a_used_verdict_lands_inside_the_judge_band(engine, tmp_path):
    """It used to store the raw confidence, which collides with other channels."""
    signal = _judged(engine, tmp_path, verdict="used", confidence=0.88, slug="judge-band-used")
    assert signal["polarity"] == 1
    assert signal["strength"] != 0.88
    assert ss.JUDGE_LO <= signal["strength"] <= ss.JUDGE_HI
    assert signal["strength"] == pytest.approx(
        ss.judge_strength(0.88, engine.settings.feedback_llm_judge_min_confidence, 1)
    )


def test_an_uncertain_verdict_carries_no_strength(engine, tmp_path):
    """Below min_confidence the polarity is 0, so the row asserts nothing.

    Its confidence is not lost: it stays in signals.evidence.
    """
    signal = _judged(
        engine, tmp_path, verdict="used", confidence=0.35, slug="judge-band-uncertain"
    )
    assert signal["polarity"] == 0
    assert signal["strength"] == 0.0
    assert json.loads(signal["evidence"])["confidence"] == 0.35
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_usage_signal_strength.py -q -k judge > /tmp/218-t4-red.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t4-red.txt
tail -20 /tmp/218-t4-red.txt
```

Expected: 2 failed — the used verdict stores `0.88` instead of a band value, and the uncertain one
stores `0.35` instead of `0.0`.

- [ ] **Step 3: Put the judge record on its band**

In `src/ormah/background/session_watcher.py`, inside `judge_records.append({...})`:

```python
                "strength": confidence,
```
becomes
```python
                "strength": signal_strength.judge_strength(confidence, min_confidence, polarity),
```

`polarity` and `min_confidence` are both already in scope at that point — `polarity` is assigned a
few lines above by the `promoted` branch, and `min_confidence` is read from settings before the
loop. `evidence` below still records the raw `confidence` and `min_confidence`, untouched: the
backfill in Task 6 depends on both staying there.

- [ ] **Step 4: Update the one existing assertion**

In `tests/test_background/test_session_watcher.py`, line 427:

```python
    assert judge_signal["strength"] == 0.88
```
becomes
```python
    # #218: strength is the judge's band position now, not its raw confidence.
    assert judge_signal["strength"] == pytest.approx(
        signal_strength.judge_strength(0.88, engine.settings.feedback_llm_judge_min_confidence, 1)
    )
```

Add `from ormah import signal_strength` to that file's imports if it is not already there.
`pytest` is already imported in that module.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_usage_signal_strength.py \
  tests/test_background/test_session_watcher.py \
  tests/test_engine/test_confirmed_use_contract.py -q > /tmp/218-t4-green.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t4-green.txt
tail -10 /tmp/218-t4-green.txt
```

Expected: `PYTEST_EXIT=0`.

A failure in `test_confirmed_use_contract.py` means **stop and report** — `strength` was supposed
to have no readers, and a failure there falsifies the design's premise rather than needing a patch.

- [ ] **Step 6: Lint and commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
git add src/ormah/background/session_watcher.py \
        tests/test_background/test_usage_signal_strength.py \
        tests/test_background/test_session_watcher.py
git commit -m "fix(feedback): judge records store a band position, not raw confidence (#218)

The judge wrote strength=confidence on every verdict, including the uncertain
ones that assert nothing — so a 0.35 uncertain row and a genuine 0.35-strength
row were indistinguishable, and a confident judgment collided numerically with
channels that are not comparable to it.

Confidence now maps affinely onto the judge band, anchored on the caller's
min_confidence rather than the literal 0.75. Polarity-zero rows store 0.0; their
raw confidence is still recorded in signals.evidence.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```
