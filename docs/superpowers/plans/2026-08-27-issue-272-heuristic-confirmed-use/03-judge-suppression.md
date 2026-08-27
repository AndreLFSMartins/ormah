# Task 3: Re-anchor the Judge's Suppression on Confirmation

**Depends on:** Task 2. **Read `00-overview.md` first — its Global Constraints apply.**

**Files:**
- Modify: `src/ormah/background/session_watcher.py` (`:439-457` query, `:486-506` loop)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: `HEURISTIC_CONFIRM_FLOOR` (Task 1), the claim in the heuristic block (Task 2).
- Produces: nothing for later tasks.

## Background

Line `:505` reads:

```python
        if llm_judge_enabled and not has_llm_judge and not referenced:
```

`not referenced` means *any* heuristic hit suppresses the judge — including a weak `token_overlap` hit
that, after Task 1, confirms nothing. That hit is then left with **no confirmation route at all**: too
weak to claim, and denied the one detector that could still judge it. That is 1,587 of the 1,629 rows.

The condition should be "this event is already settled", not "the heuristic saw something".

## Why `confirmed_use_claims`, not just the strength

Two cases need different sources of truth:

- **First pass** (`has_heuristic` false): the strength is in hand from `_node_usage_evidence`, and the
  claim has not been taken yet — the transaction that takes it opens later, at `:508`.
- **Re-ingest** (`has_heuristic` true): the strength is not in scope at all. The row query returns only
  `heuristic_polarity`.

`confirmed_use_claims` answers both, and answers a third case neither covers: a positive
`submit_feedback` submitted through MCP. `has_llm_judge` is structurally blind to that — it only sees
the watcher's own signal source — which is the same blindness #220's contract 13a documents.

---

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_background/test_session_watcher.py`:

```python
def test_a_weak_heuristic_hit_still_reaches_the_judge(engine, tmp_path):
    """#272 D3: below the floor, the judge is the only route left — do not suppress it.

    Before #272 any heuristic hit suppressed the judge, so a token_overlap match
    could neither claim nor be judged. That is 1,587 of the 1,629 measured rows.
    """
    prompt = "What about the retention policy?"
    response = "Retention uses decay, stability and archival thresholds together."
    transcript_path = tmp_path / "weak-to-judge-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Decay lowers stability until archival thresholds move a node out of working.",
        type="fact",
        title="Decay stability archival thresholds",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="weak-to-judge-session", prompt=prompt,
    )

    llm_response = json.dumps({"judgments": [{
        "whisper_log_id": whisper_log_id,
        "verdict": "used",
        "confidence": 0.95,
        "reason": "The answer applies the retention guidance.",
    }]})
    before = _lifecycle(engine, node_id)
    with patch(_LLM_PATCH, return_value=llm_response) as mock_llm:
        _record_whisper_usage_signals(engine, transcript)

    assert mock_llm.called, "a weak heuristic hit suppressed the judge"
    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert claim is not None, "the judge confirmed nothing for a weak heuristic hit"
    assert _lifecycle(engine, node_id) != before


def test_a_confirming_heuristic_hit_does_not_reach_the_judge(engine, tmp_path):
    """#272 D3: judging an event that already confirmed is wasted spend."""
    prompt = "How should we solve feedback collection?"
    response = "The right fix is the transcript watcher mines feedback usage approach."
    transcript_path = tmp_path / "strong-skips-judge-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact",
        title="Transcript watcher mines feedback usage",
    ))
    _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="strong-skips-judge-session", prompt=prompt,
    )

    with patch(_LLM_PATCH) as mock_llm:
        _record_whisper_usage_signals(engine, transcript)

    assert not mock_llm.called, "a confirming heuristic hit was judged anyway"


def test_an_already_confirmed_event_is_not_rejudged_on_reingest(engine, tmp_path):
    """#272 D3: the claim table settles the re-ingest case the strength cannot.

    On a second pass has_heuristic is true and the strength is not in scope, so
    confirmed_use_claims is the only authority on whether this event is settled.
    """
    prompt = "How should we solve feedback collection?"
    response = "The right fix is the transcript watcher mines feedback usage approach."
    transcript_path = tmp_path / "reingest-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact",
        title="Transcript watcher mines feedback usage",
    ))
    _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="reingest-session", prompt=prompt,
    )

    with patch(_LLM_PATCH) as first_llm:
        _record_whisper_usage_signals(engine, transcript)
    assert not first_llm.called

    after_first = _lifecycle(engine, node_id)

    with patch(_LLM_PATCH) as second_llm:
        _record_whisper_usage_signals(engine, transcript)

    assert not second_llm.called, "a settled event was sent to the judge on re-ingest"
    assert _lifecycle(engine, node_id) == after_first, "the event reinforced twice"


def test_mcp_feedback_suppresses_the_judge_for_that_event(engine, tmp_path):
    """#272 D3: closes the cross-caller blindness has_llm_judge cannot see (#220 13a)."""
    prompt = "What about the retention policy?"
    response = "Retention uses decay, stability and archival thresholds together."
    transcript_path = tmp_path / "mcp-first-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Decay lowers stability until archival thresholds move a node out of working.",
        type="fact",
        title="Decay stability archival thresholds",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="mcp-first-session", prompt=prompt,
    )

    engine.submit_feedback(node_id, signal=1, source="implicit", whisper_log_id=whisper_log_id)
    after_feedback = _lifecycle(engine, node_id)

    with patch(_LLM_PATCH) as mock_llm:
        _record_whisper_usage_signals(engine, transcript)

    assert not mock_llm.called, "an event already confirmed through MCP was judged again"
    assert _lifecycle(engine, node_id) == after_feedback, "the event reinforced twice"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_background/test_session_watcher.py \
  -k "weak_heuristic_hit_still_reaches or already_confirmed_event_is_not_rejudged or mcp_feedback_suppresses" -v
```

Expected: FAIL.
- `test_a_weak_heuristic_hit_still_reaches_the_judge` fails on `assert mock_llm.called` — today any hit
  suppresses the judge.
- `test_mcp_feedback_suppresses_the_judge_for_that_event` fails on `assert not mock_llm.called` — today
  a weak hit that was already confirmed through MCP is still queued.
- `test_a_confirming_heuristic_hit_does_not_reach_the_judge` should already PASS (a title hit sets
  `referenced`), so it is a regression pin, not a red test.

- [ ] **Step 3: Add `already_confirmed` to the row query**

In `_record_whisper_usage_signals` (`:417`), add one column to the SELECT at `:439-457`, immediately
after the `has_llm_judge` EXISTS block:

```python
            EXISTS (
                SELECT 1 FROM signals s
                WHERE s.whisper_log_id = wl.id
                  AND s.source = ?
            ) AS has_llm_judge,
            EXISTS (
                SELECT 1 FROM confirmed_use_claims c
                WHERE c.whisper_log_id = wl.id
                  AND c.node_id = wl.node_id
            ) AS already_confirmed
```

The parameter tuple is unchanged — the new subquery binds no placeholders.

- [ ] **Step 4: Re-anchor the suppression**

Replace `:486-506`, the `referenced` bookkeeping and the queueing condition:

```python
        referenced = False
        confirms = False
        if not has_heuristic:
            referenced, strength, evidence = _node_usage_evidence(row, response)
            signal_type = "whisper_referenced" if referenced else "whisper_unreferenced"
            polarity = 1 if referenced else 0
            # Issue #272: whether THIS hit will take the claim in the transaction below.
            # Not the same question as `referenced`: a token_overlap hit is referenced
            # but sits under the floor, so it confirms nothing.
            confirms = referenced and strength >= HEURISTIC_CONFIRM_FLOOR
            heuristic_records.append({
                "row": row,
                "signal_type": signal_type,
                "polarity": polarity,
                "strength": strength,
                "evidence": {
                    **evidence,
                    "detector": _HEURISTIC_SOURCE,
                    "response_chars": len(response),
                },
            })

        # Issue #272: suppress the judge only for an event that is already settled —
        # not for any heuristic sighting. A below-floor hit keeps the judge, which is
        # the only route left that can still confirm it.
        #
        # already_confirmed covers the two cases `confirms` cannot: a re-ingest, where
        # the strength is not in scope at all, and a positive submit_feedback through
        # MCP, which has_llm_judge is structurally blind to because it only sees this
        # watcher's own signal source (#220 contract 13a).
        settled = confirms or bool(row["already_confirmed"])
        if llm_judge_enabled and not has_llm_judge and not settled:
            llm_groups.setdefault((prompt_text, response), []).append(row)
```

Note the `else: referenced = int(heuristic_polarity) == 1` branch is **deleted**: `referenced` no longer
drives the queueing decision, and on the re-ingest path `already_confirmed` answers it correctly.

- [ ] **Step 5: Import the floor**

`session_watcher.py:20` already imports `MemoryEngine` at module scope, and `memory_engine.py` does not
import `session_watcher` at all — verified, so there is no cycle. Extend the existing line:

```python
from ormah.engine.memory_engine import HEURISTIC_CONFIRM_FLOOR, MemoryEngine
```

Import the floor rather than reaching for `signal_strength.IMPLICIT` directly: the engine owns what
"enough evidence to confirm" means, and the ladder rung it happens to equal is an implementation
detail of that decision.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_background/test_session_watcher.py -v 2>&1 | tail -30
```

Expected: PASS, all four new tests plus every pre-existing one.

- [ ] **Step 7: Run the full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -20
```

- [ ] **Step 8: Lint and commit**

```bash
make lint
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(feedback): a weak heuristic hit must not also lose the judge (#272)

Any heuristic sighting suppressed the LLM judge, so a token_overlap hit — too
weak to claim confirmed use — was also denied the one detector that could still
confirm it. That combination left 1,587 of 1,629 positive references with no
route to the lifecycle at all.

Suppression is now anchored on the event being settled rather than merely seen.
confirmed_use_claims answers the two cases the in-hand strength cannot: a
re-ingest, where the strength is out of scope, and a positive submit_feedback
through MCP, which has_llm_judge is structurally blind to."
```
