# Task 2: Qualified positive feedback records confirmed use

**Files:**
- Modify: `tests/test_engine/test_confirmed_use_contract.py` (append the confirmed-use cases)
- Modify: `src/ormah/engine/memory_engine.py` (`submit_feedback`, `_submit_feedback_locked`, one new module constant)
- Modify: `src/ormah/background/session_watcher.py` (`_record_whisper_usage_signals`, the `auto_llm_judge` block only)
- Modify: `tests/test_background/test_session_watcher.py` (append two cases)

**Interfaces:**
- Consumes: `MemoryEngine._record_confirmed_use(self, node_id: str) -> None` from Task 1. Nothing else.
- Produces: `MemoryEngine._submit_feedback_locked(...) -> tuple[str | None, str]` — now returns `(resolved_node_id, message)` instead of just the message. `resolved_node_id` is `None` on the error paths. Its only caller is `submit_feedback`.

All line numbers are from `upstream/main` (`a28837b`) **before Task 1's edits**, which shift them. Locate code by the quoted snippet.

---

- [ ] **Step 1: Write the failing confirmed-use tests for feedback**

Append to `tests/test_engine/test_confirmed_use_contract.py`:

```python
# --- Confirmed-use contracts ----------------------------------------------

def _seed_whisper_log(engine, node_id, prompt="what about caching?"):
    """Insert a whisper_log row so submit_feedback can resolve one.

    submit_feedback attaches feedback to a whisper/recall event; without a row
    it returns an error string instead of recording anything.
    """
    engine.recall_search(prompt, limit=10)
    row = engine.db.conn.execute(
        "SELECT id FROM whisper_log WHERE node_id = ? ORDER BY id DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    assert row is not None, "no whisper_log row was created — check the surface used"
    return row["id"]


def test_recall_node_confirms_only_the_requested_node(engine):
    """Contract 7: recall_node confirms the node asked for, never its neighbours."""
    from ormah.models.node import CreateNodeRequest

    target, _ = engine.remember(CreateNodeRequest(
        content="caching architecture target node", title="Target", type="fact", tier="working",
    ))
    neighbour, _ = engine.remember(CreateNodeRequest(
        content="caching architecture neighbour node", title="Neighbour", type="fact",
        tier="working",
    ))
    engine.graph.add_edge(target, neighbour, "related_to")

    before_target = _snapshot(engine, target)
    before_neighbour = _snapshot(engine, neighbour)

    engine.recall_node(target)

    assert _snapshot(engine, target) != before_target, "recall_node did not confirm its node"
    assert _snapshot(engine, neighbour) == before_neighbour, (
        "recall_node confirmed a neighbour — only the requested node counts"
    )


@pytest.mark.parametrize("source", ["explicit", "implicit", "auto_llm_judge"])
def test_qualified_positive_feedback_confirms_use(engine, source):
    """Contract 8: the three allowlisted sources confirm, with signal == 1."""
    ids = _make_nodes(engine, count=2)
    target, other = ids[0], ids[1]
    log_id = _seed_whisper_log(engine, target)

    before_target = _snapshot(engine, target)
    before_other = _snapshot(engine, other)

    engine.submit_feedback(target, signal=1, source=source, whisper_log_id=log_id)

    assert _snapshot(engine, target) != before_target, (
        f"positive {source} feedback did not confirm use"
    )
    assert _snapshot(engine, other) == before_other, "an unrelated node was confirmed"


def test_auto_heuristic_positive_does_not_confirm(engine):
    """Contract 9: auto_heuristic is excluded pending #218 — fail-closed."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    before = _snapshot(engine, target)
    engine.submit_feedback(target, signal=1, source="auto_heuristic", whisper_log_id=log_id)

    assert _snapshot(engine, target) == before, "auto_heuristic must not confirm use"


@pytest.mark.parametrize("source", ["explicit", "implicit", "auto_llm_judge", "auto_heuristic"])
def test_negative_feedback_never_confirms(engine, source):
    """Contract 10: -1 is evidence about the prompt/node pair, never a confirmed use."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    before = _snapshot(engine, target)
    engine.submit_feedback(target, signal=-1, source=source, whisper_log_id=log_id)

    assert _snapshot(engine, target) == before, (
        f"negative {source} feedback changed lifecycle fields"
    )
```

The helper's assumptions are verified, not guessed: `schema.sql:116-124` declares `whisper_log` with both `id` and `node_id`, and `_log_feedback_candidates` (`memory_engine.py:561`) performs the `INSERT INTO whisper_log` at `:600`. `recall_search` calls it with `surface="recall_search"`, so a search is enough to seed a row.

- [ ] **Step 2: Run them and confirm which fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use_contract.py -v -k "confirm or heuristic or negative" )
```

Expected: contract 7 **PASSES** (`recall_node` already confirmed its node; this is a regression pin). Contract 8 **FAILS** for all three sources — feedback records affinity and signals but never reinforces. Contracts 9 and 10 **PASS** vacuously, because nothing confirms yet; they become meaningful once Step 3 lands, which is exactly why they are written now.

- [ ] **Step 3: Add the allowlist and reinforce outside the transaction**

In `src/ormah/engine/memory_engine.py`, add the constant near the other module-level constants at the top of the file:

```python
# Issue #220: the only feedback sources that count as confirmed use. Fail-closed —
# anything not listed here, and every negative signal, does not reinforce.
# auto_heuristic is excluded pending #218 signal calibration.
_CONFIRMED_USE_SOURCES = frozenset({"explicit", "implicit", "auto_llm_judge"})
```

Replace `submit_feedback` (`:2498-2512`):

```python
    def submit_feedback(
        self,
        node_id: str,
        signal: int,
        source: str = "explicit",
        whisper_log_id: int | None = None,
    ) -> str:
        """Record feedback while preventing retention from deleting its event."""
        with self.db.transaction():
            resolved_node_id, message = self._submit_feedback_locked(
                node_id=node_id,
                signal=signal,
                source=source,
                whisper_log_id=whisper_log_id,
            )
        # Reinforcement runs after the transaction commits: db.transaction() holds a
        # process-level lock for its whole body, and _record_confirmed_use does file
        # I/O. A crash in this gap costs one reinforcement, which the next confirmed
        # use restores; holding the global write lock across disk I/O would stall
        # every whisper and ingest in the process.
        if resolved_node_id is not None and signal == 1 and source in _CONFIRMED_USE_SOURCES:
            self._record_confirmed_use(resolved_node_id)
        return message
```

In `_submit_feedback_locked`, change the return type annotation and both return statements. The signature (`:2514-2520`) becomes:

```python
    def _submit_feedback_locked(
        self,
        node_id: str,
        signal: int,
        source: str = "explicit",
        whisper_log_id: int | None = None,
    ) -> tuple[str | None, str]:
```

The early error return (`:2532-2533`) becomes:

```python
        if error is not None:
            return None, error
```

The final return (`:2612`) becomes:

```python
        return resolved_node_id, f"Feedback recorded for node {resolved_node_id[:8]}..."
```

`_submit_feedback_locked` has exactly one caller (`submit_feedback`), so no other site needs updating. Verify:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && grep -rn "_submit_feedback_locked" src/ tests/ )
```

- [ ] **Step 4: Run the feedback contracts — all must pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use_contract.py -v )
```

Expected: all pass, including contracts 9 and 10, which now genuinely discriminate.

- [ ] **Step 5: Write the failing session-watcher tests**

Append to `tests/test_background/test_session_watcher.py`, modelled on the existing `test_llm_judge_promotes_used_verdict`:

```python
def test_llm_judge_used_verdict_records_confirmed_use(engine, tmp_path):
    """Issue #220: a positive auto_llm_judge verdict confirms use for its node."""
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-confirms-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-confirms-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before_access = engine.file_store.load(node_id).access_count
    before_stability = engine.file_store.load(node_id).stability

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "used",
            "confidence": 0.88,
            "reason": "The answer endorses the injected deployment guidance.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    after = engine.file_store.load(node_id)
    assert after.access_count == before_access + 1, "the judged-used node was not confirmed"
    assert after.stability != before_stability

    # The signal and affinity rows must still be written — confirmed use is
    # additional behaviour, not a replacement for observability.
    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert affinity is not None
    assert affinity["source"] == "auto_llm_judge"


def test_llm_judge_unused_verdict_does_not_record_confirmed_use(engine, tmp_path):
    """A negative verdict is affinity evidence only — it never reinforces."""
    prompt = "What deployment marker should we use?"
    response = "Ignore that; we are switching to a completely different scheme."
    transcript_path = tmp_path / "judge-unused-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-unused-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before = engine.file_store.load(node_id)
    before_access, before_stability = before.access_count, before.stability

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "unused",
            "confidence": 0.9,
            "reason": "The answer rejects the injected guidance.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    after = engine.file_store.load(node_id)
    assert after.access_count == before_access
    assert after.stability == before_stability
```

And contract 12 — the heuristic path produces a **positive** polarity that must still not confirm. Modelled on the existing `test_record_whisper_usage_signal_promotes_clear_reference`, which exercises that path with the judge off:

```python
def test_heuristic_positive_does_not_record_confirmed_use(engine, tmp_path):
    """Issue #220: auto_heuristic yields polarity 1 but never confirms use.

    The heuristic path is excluded pending #218 signal calibration. This is the
    case that matters: it is positive, so only the source keeps it out.
    """
    prompt = "How should we solve feedback collection?"
    response = "The right fix is the transcript watcher mines feedback usage approach."
    transcript_path = tmp_path / "heuristic-no-confirm-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact",
        title="Transcript watcher mines feedback usage",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="heuristic-no-confirm-session", prompt=prompt,
    )

    before = engine.file_store.load(node_id)
    before_access, before_stability = before.access_count, before.stability

    recorded = _record_whisper_usage_signals(engine, transcript)

    # The heuristic signal is still recorded — this is about lifecycle, not observability.
    assert recorded == 1
    signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal["polarity"] == 1

    after = engine.file_store.load(node_id)
    assert after.access_count == before_access, "auto_heuristic confirmed use — it must not"
    assert after.stability == before_stability
```

This test must pass both before and after Step 7 — it pins that the change to the judge block did not leak into the heuristic block. The two paths use separate transactions (`:498` and `:561`), so the isolation is structural, but structure is an argument and this is a measurement.

- [ ] **Step 6: Run them and watch the positive case fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_background/test_session_watcher.py -v -k "confirmed_use" )
```

Expected: `test_llm_judge_used_verdict_records_confirmed_use` **FAILS** (`access_count` unchanged — nothing confirms yet). The unused-verdict and heuristic tests **PASS**; both pass vacuously at this point and become discriminating after Step 7, which is why they are written now.

- [ ] **Step 7: Collect confirmed IDs inside the block, reinforce after it**

In `src/ormah/background/session_watcher.py`, `_record_whisper_usage_signals`, the `auto_llm_judge` block at `:561`. Replace:

```python
    with engine.db.transaction() as conn:
        for record in judge_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_LLM_JUDGE_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] in (1, -1):
                _insert_affinity(
                    conn,
                    row,
                    signal=record["polarity"],
                    source=_LLM_JUDGE_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )

    return recorded
```

with:

```python
    confirmed_node_ids: list[str] = []
    with engine.db.transaction() as conn:
        for record in judge_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_LLM_JUDGE_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] in (1, -1):
                _insert_affinity(
                    conn,
                    row,
                    signal=record["polarity"],
                    source=_LLM_JUDGE_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )
            if record["polarity"] == 1:
                confirmed_node_ids.append(row["node_id"])

    # Issue #220: reinforcement runs after the transaction commits. db.transaction()
    # holds a process-level lock for its whole body and _record_confirmed_use writes
    # markdown to disk, so doing this inside would stall every writer in the process
    # for the length of N file saves.
    for node_id in confirmed_node_ids:
        engine._record_confirmed_use(node_id)

    return recorded
```

The `auto_heuristic` block at `:498` is **not** modified. The two paths do not share a transaction, so no heuristic record can reach this list.

- [ ] **Step 8: Run the watcher tests — both must pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_background/test_session_watcher.py -v )
```

Expected: the two new tests pass and every pre-existing watcher test still passes — in particular `test_llm_judge_promotes_used_verdict`, whose `recorded == 2` assertion must be unaffected, since reinforcement does not change the returned count.

- [ ] **Step 9: Full suite against the baseline, then lint**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort ) \
  > /private/tmp/claude-501/220-task2.txt
diff /private/tmp/claude-501/220-baseline-ids.txt /private/tmp/claude-501/220-task2.txt
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && make lint )
```

Expected: no output from `diff`, clean lint.

- [ ] **Step 10: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git add -A && \
  git commit -m "fix(lifecycle): record confirmed use from qualified positive feedback

recall_node was the only caller reinforcing a memory. Positive feedback wrote
affinity and signal rows but never advanced the lifecycle, so deliberate
confirmation counted for nothing.

submit_feedback now reinforces when signal == 1 and the source is one of
explicit, implicit or auto_llm_judge; the allowlist is fail-closed, so
auto_heuristic (pending #218) and every negative signal do not. The session
watcher's auto_llm_judge path does the same for its positive verdicts.

Reinforcement runs after the enclosing transaction commits rather than inside
it: db.transaction() holds a process-level lock for its whole body and the
mutator writes markdown to disk. The cost is a crash window worth one lost
reinforcement, which the next confirmed use restores.

Refs #220" )
```

- [ ] **Step 11: Report, and do not open the PR**

Push the branch to your fork:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && git push fork fix/220-confirmed-use )
```

**Stop there.** The PR must not be opened while draft PR [#229](https://github.com/r-spade/ormah/pull/229) still declares `Closes #220–#223`. Report the branch as ready and state that the PR is blocked on #229 being closed as superseded.

When it is unblocked, the PR body must mention that `FileStore.touch_access` (`src/ormah/store/file_store.py:145`) is a namesake left untouched on purpose, so a reviewer does not read it as an oversight.
