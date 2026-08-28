# Task 2: The Heuristic Block Claims and Reinforces

**Depends on:** Task 1. **Read `00-overview.md` first — its Global Constraints apply.**

**Files:**
- Modify: `src/ormah/background/session_watcher.py` (`:508-529`, and a new loop before `:531`)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: `engine._claim_confirmed_use(conn, whisper_log_id, node_id, *, signal, source, strength)`
  and `HEURISTIC_CONFIRM_FLOOR`, both from Task 1.
- Produces: nothing new for later tasks. Task 3 modifies the same function but a different block.

## Background

The heuristic commit block writes a signal and an affinity row, then stops. This is the change the
issue is actually about: **0 of 1,629** positive heuristic pairs ever took a claim.

## The affinity row this block writes is settled in Task 3, not here

This block writes `_insert_affinity(signal=1, ...)` for every positive hit — the floor gates the
*claim*, not the affinity row — so a `token_overlap` hit still records a `+1` here, exactly as it
does today. That is deliberate and unchanged.

It only becomes a problem once Task 3 starts sending those weak hits to the judge, because affinity
is unique per `(node_id, whisper_log_id)` and `_insert_affinity` is `ON CONFLICT DO NOTHING`: a later
`irrelevant` verdict could not overwrite this row. **Task 3 owns that fix** (its Step 5), since Task 3
is what makes the path reachable. Nothing to do about it here — do not pre-emptively change this
block's affinity write.

## The two ordering rules — both load-bearing

1. **`_insert_affinity` must run BEFORE the claim.** The claim helper reads `changes()`, so nothing may
   sit between its INSERT and that read. This is already documented at `session_watcher.py:598-602`.
2. **Reinforcement runs AFTER the transaction closes.** `_record_confirmed_use` does file I/O;
   calling it inside would hold the process-wide write lock across N markdown saves and would take
   `db_lock` before `memory_lock`, inverting the order every serialized writer uses (#220 §4.3).

## Why this needs its OWN reinforcement loop

The judge's loop lives at `:623`, but `:531` returns early:

```python
    if not llm_groups:
        return recorded
```

After Task 3, a confirming heuristic hit is exactly the case that produces no `llm_groups` — so
reusing the judge's loop would skip reinforcement precisely when it matters most. The new loop must sit
**between the heuristic transaction and that early return.**

---

- [ ] **Step 1: Write the failing test**

Add to `tests/test_background/test_session_watcher.py`:

```python
@pytest.mark.parametrize("title,content,response,should_confirm", [
    # title match (0.94) — the title appears verbatim in the response
    (
        "Transcript watcher mines feedback usage",
        "The transcript watcher mines feedback usage from completed transcripts.",
        "The right fix is the transcript watcher mines feedback usage approach.",
        True,
    ),
    # sentence match (0.92) — a content sentence appears verbatim
    (
        "Vector search notes",
        "Sqlite vec stores embeddings inside the same database file as the nodes.",
        "As noted: sqlite vec stores embeddings inside the same database file as the nodes.",
        True,
    ),
])
def test_verbatim_heuristic_match_confirms_use(
    engine, tmp_path, title, content, response, should_confirm,
):
    """#272: a verbatim heuristic hit reinforces the memory. Contract 12, inverted.

    This is the issue's acceptance criterion: 0 of 1,629 positive heuristic pairs
    took a claim, because only the judge block ever called _claim_confirmed_use.
    """
    prompt = "How should we solve feedback collection?"
    transcript_path = tmp_path / "verbatim-confirm-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(content=content, type="fact", title=title))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="verbatim-confirm-session", prompt=prompt,
    )

    before = _lifecycle(engine, node_id)
    recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 1
    signal = engine.db.conn.execute(
        "SELECT polarity, strength FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal["polarity"] == 1
    assert signal["strength"] >= 0.80, "fixture did not produce a verbatim match — check the text"

    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ? AND node_id = ?",
        (whisper_log_id, node_id),
    ).fetchone()
    assert claim is not None, "the heuristic path took no confirmed-use claim"
    assert _lifecycle(engine, node_id) != before, "the claim was taken but nothing reinforced"


def test_node_id_heuristic_match_confirms_use(engine, tmp_path):
    """#272 spec case 1: the strongest match kind (0.98).

    Separate from the parametrized test above because the response must quote the
    node's short id, which only exists after the node is created.
    """
    prompt = "Which memory covers the retention policy?"
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Retention is governed by decay and archival thresholds.",
        type="fact",
        title="Retention policy overview",
    ))
    response = f"That is memory {node_id[:8]}, which covers it."

    transcript_path = tmp_path / "nodeid-confirm-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="nodeid-confirm-session", prompt=prompt,
    )

    before = _lifecycle(engine, node_id)
    _record_whisper_usage_signals(engine, transcript)

    signal = engine.db.conn.execute(
        "SELECT strength, evidence FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert json.loads(signal["evidence"])["match"] == "node_id"
    assert signal["strength"] == signal_strength.VERBATIM_NODE_ID

    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ? AND node_id = ?",
        (whisper_log_id, node_id),
    ).fetchone()
    assert claim is not None, "a node_id match — the strongest evidence there is — did not claim"
    assert _lifecycle(engine, node_id) != before


def test_token_overlap_heuristic_match_does_not_confirm(engine, tmp_path):
    """#272 D1: the weak channel records evidence but never reinforces.

    97.4% of heuristic hits are token_overlap; admitting them would give the least
    precise kind the same lifecycle power as a verbatim node_id match.
    """
    prompt = "What about the retention policy?"
    # Overlapping vocabulary, but no verbatim title or sentence.
    # MEASURED, not guessed: this text yields match="token_overlap", overlap_ratio 0.6,
    # strength ~0.436 — a real weak hit, under the 0.80 floor. The earlier text
    # ("Retention uses decay, stability and archival thresholds together.") gave
    # overlap_ratio 0.4, BELOW OVERLAP_GATE 0.5, so _node_usage_evidence returned
    # match="none" and this test exercised no heuristic path at all.
    response = (
        "The decay process lowers stability, and archival thresholds eventually "
        "move things along."
    )
    transcript_path = tmp_path / "overlap-no-confirm-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Decay lowers stability until archival thresholds move a node out of working.",
        type="fact",
        title="Decay stability archival thresholds",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="overlap-no-confirm-session", prompt=prompt,
    )

    before = _lifecycle(engine, node_id)
    with patch(_LLM_PATCH, return_value=None):  # judge unavailable — isolate the heuristic
        _record_whisper_usage_signals(engine, transcript)

    signal = engine.db.conn.execute(
        "SELECT polarity, strength, evidence FROM signals WHERE whisper_log_id = ?",
        (whisper_log_id,),
    ).fetchone()
    assert signal["polarity"] == 1, "fixture did not match at all — check the vocabulary overlap"
    assert json.loads(signal["evidence"])["match"] == "token_overlap"
    assert signal["strength"] < 0.80

    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert claim is None, "token_overlap took a claim — it is below the evidence floor"
    assert _lifecycle(engine, node_id) == before


def test_one_nodes_reinforcement_failure_does_not_stop_the_batch(engine, tmp_path):
    """#272: the batch is isolated per node, matching the judge path's contract."""
    prompt = "How should we solve feedback collection?"
    response = (
        "Two things: the transcript watcher mines feedback usage approach, "
        "and sqlite vec stores embeddings inside the same database file as the nodes."
    )
    transcript_path = tmp_path / "batch-failure-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    first, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact", title="Transcript watcher mines feedback usage",
    ))
    second, _ = engine.remember(CreateNodeRequest(
        content="Sqlite vec stores embeddings inside the same database file as the nodes.",
        type="fact", title="Vector search notes",
    ))
    for node_id in (first, second):
        _insert_injected_whisper_log(
            engine, node_id=node_id, session_id="batch-failure-session", prompt=prompt,
        )

    before_second = _lifecycle(engine, second)
    real = engine._record_confirmed_use

    def flaky(node_id):
        if node_id == first:
            raise ZeroDivisionError("simulated mutator failure")
        return real(node_id)

    with patch.object(engine, "_record_confirmed_use", side_effect=flaky):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 2, "a mutator failure changed the recorded count"
    assert _lifecycle(engine, second) != before_second, "node 2 lost its reinforcement"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_background/test_session_watcher.py \
  -k "verbatim_heuristic_match_confirms or token_overlap_heuristic_match or nodes_reinforcement_failure" -v
```

Expected: `test_verbatim_heuristic_match_confirms_use` FAILS on
`assert claim is not None` — "the heuristic path took no confirmed-use claim".
`test_token_overlap_heuristic_match_does_not_confirm` should already PASS (nothing claims today); it is
a regression pin for Task 3, not a red test. If the verbatim test passes, the fixture is not producing
a verbatim match — fix the fixture, do not adjust the assertion.

- [ ] **Step 3: Claim inside the heuristic transaction**

In `session_watcher.py`, replace the block at `:508-529`:

```python
    heuristic_confirmed_ids: list[str] = []
    with engine.db.transaction() as conn:
        for record in heuristic_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_HEURISTIC_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] == 1:
                _insert_affinity(
                    conn,
                    row,
                    signal=1,
                    source=_HEURISTIC_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )
                # Issue #272: the same at-most-once claim the judge block takes. The
                # engine gates it on HEURISTIC_CONFIRM_FLOOR, so a token_overlap hit
                # records its evidence here and confirms nothing.
                #
                # _insert_affinity MUST stay above this call: the claim helper reads
                # changes(), so nothing may sit between its INSERT and that read.
                if engine._claim_confirmed_use(
                    conn,
                    row["id"],
                    row["node_id"],
                    signal=1,
                    source=_HEURISTIC_AFFINITY_SOURCE,
                    strength=record["strength"],
                ):
                    heuristic_confirmed_ids.append(row["node_id"])
```

- [ ] **Step 4: Reinforce after the transaction, before the early return**

Immediately after that `with` block and **before** `if not llm_groups:` at `:531`, insert:

```python
    # Issue #272: reinforcement runs after the transaction commits — _record_confirmed_use
    # does file I/O, and calling it inside would hold the process-wide write lock across
    # N markdown saves and take db_lock before memory_lock, inverting the order every
    # serialized writer uses.
    #
    # This is deliberately NOT the judge's loop below: the `if not llm_groups: return`
    # that follows means the judge's loop never runs when there is nothing to judge —
    # which, since a confirming heuristic hit now suppresses the judge, is exactly the
    # case this loop exists for.
    #
    # Isolated per node: the signals and claims are already committed, so letting one
    # failure escape would abandon every later node with its claim taken and nothing to
    # retry it. At-most-once means a miss is logged, never raised.
    for node_id in heuristic_confirmed_ids:
        try:
            engine._record_confirmed_use(node_id)
        except Exception:
            logger.exception("confirmed-use reinforcement failed for node %s", node_id)

    if not llm_groups:
        return recorded
```

- [ ] **Step 5: Rewrite contract 12 to its new meaning**

Replace `test_heuristic_positive_does_not_record_confirmed_use` (`:2404-2441`) entirely. Its fixture
matches on **title** (verified: `_normalise_text` reduces the title to
`transcript watcher mines feedback usage`, which is a substring of the normalised response), so under
#272 it now confirms — the old assertion is exactly what changed:

```python
def test_heuristic_below_the_floor_does_not_record_confirmed_use(engine, tmp_path):
    """Contract 12, as amended by #272: the floor, not the source, is the gate.

    Before #272 no heuristic hit could confirm. Now a verbatim one does, and only
    evidence below HEURISTIC_CONFIRM_FLOOR is kept out. The verbatim half of this
    contract lives in test_verbatim_heuristic_match_confirms_use.
    """
    prompt = "What about the retention policy?"
    # MEASURED, not guessed: this text yields match="token_overlap", overlap_ratio 0.6,
    # strength ~0.436 — a real weak hit, under the 0.80 floor. The earlier text
    # ("Retention uses decay, stability and archival thresholds together.") gave
    # overlap_ratio 0.4, BELOW OVERLAP_GATE 0.5, so _node_usage_evidence returned
    # match="none" and this test exercised no heuristic path at all.
    response = (
        "The decay process lowers stability, and archival thresholds eventually "
        "move things along."
    )
    transcript_path = tmp_path / "contract12-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Decay lowers stability until archival thresholds move a node out of working.",
        type="fact",
        title="Decay stability archival thresholds",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="contract12-session", prompt=prompt,
    )

    before = _lifecycle(engine, node_id)
    with patch(_LLM_PATCH, return_value=None):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 1
    signal = engine.db.conn.execute(
        "SELECT polarity, strength FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal["polarity"] == 1, "the signal is still recorded — this is lifecycle, not observability"
    assert signal["strength"] < 0.80

    assert _lifecycle(engine, node_id) == before, "a below-floor hit confirmed use — it must not"
    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert claim is None, "a below-floor hit took a confirmed-use claim"
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_background/test_session_watcher.py -v > /tmp/ormah-272-file.txt 2>&1; RC=$?
tail -30 /tmp/ormah-272-file.txt
echo "pytest exit=$RC"
```

Expected: PASS, including `test_replaying_the_judge_does_not_reconfirm` and every other pre-existing
test. Any failure outside the Task 0 baseline is a regression.

- [ ] **Step 7: Run the full suite**

```bash
python -m pytest tests/ -q > /tmp/ormah-272-run.txt 2>&1; RC=$?
tail -20 /tmp/ormah-272-run.txt
echo "pytest exit=$RC"   # 0, or only baseline IDs failed
```

- [ ] **Step 8: Lint and commit**

```bash
make lint
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(feedback): the heuristic detector claims confirmed use (#272)

The heuristic commit block wrote a signal and an affinity row and stopped, so
0 of 1,629 positive heuristic pairs ever reinforced a memory — the detector
carrying 81% of positive volume was a lifecycle dead end.

It now takes the same at-most-once claim the judge block takes, gated by the
engine on the evidence floor, and reinforces in its own post-commit loop. That
loop cannot be shared with the judge's: the early return above it means the
judge's loop never runs when there is nothing to judge.

Contract 12 is rewritten rather than deleted — its subject changes from 'the
source is excluded' to 'the floor is the gate'."
```
