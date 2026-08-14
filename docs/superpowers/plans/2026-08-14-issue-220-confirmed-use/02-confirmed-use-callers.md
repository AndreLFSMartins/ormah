# Task 2: Qualified positive feedback records confirmed use

**Files:**
- Modify: `tests/test_engine/test_confirmed_use_contract.py` (append the confirmed-use cases)
- Modify: `src/ormah/engine/memory_engine.py` (`submit_feedback`, `_submit_feedback_locked`, one new module constant, one new helper `_event_is_confirmed`)
- Modify: `src/ormah/background/session_watcher.py` (`_record_whisper_usage_signals`, the `auto_llm_judge` block only)
- Modify: `tests/test_background/test_session_watcher.py` (one helper plus five cases)

**Interfaces:**
- Consumes: `MemoryEngine._record_confirmed_use(self, node_id: str) -> None` from Task 1. Nothing else.
- Produces: `MemoryEngine._submit_feedback_locked(...) -> tuple[str | None, bool, str]` — now returns `(resolved_node_id, became_confirmed, message)` instead of just the message. `resolved_node_id` is `None` and `became_confirmed` is `False` on the error paths. Its only caller is `submit_feedback`.

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


# --- Idempotency contracts (council finding: reinforce on transition only) ---

def test_replaying_the_same_positive_feedback_confirms_once(engine):
    """Contract 10a: one confirmed-use event reinforces exactly once.

    affinity and signals both use ON CONFLICT DO NOTHING, so a replayed request
    records no new evidence yet still returns success. Reinforcing on every call
    would let a retried tool call or a double-click manufacture retention.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)
    after_first = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first, (
        "replaying the same positive feedback reinforced twice"
    )


def test_negative_then_positive_feedback_confirms(engine):
    """Contract 10b: a genuine negative-to-positive change IS a new confirmation.

    This is the case a naive 'did the signals INSERT add a row?' gate gets
    wrong: the unique key is (whisper_log_id, signal_type, source) with no
    polarity, so the second call hits ON CONFLICT DO NOTHING even though the
    explicit UPDATE genuinely flips the event to positive.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=-1, source="explicit", whisper_log_id=log_id)
    after_negative = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) != after_negative, (
        "flipping the event from negative to positive did not confirm use"
    )


def test_second_source_on_an_already_confirmed_event_does_not_reconfirm(engine):
    """Contract 10c: the event is confirmed once, not once per source.

    This is the mirror failure: source is part of the unique key, so an
    implicit-positive followed by an explicit-positive DOES insert a second
    signals row. The event was already confirmed; it must not reinforce again.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="implicit", whisper_log_id=log_id)
    after_first = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first, (
        "a second positive source reconfirmed an already-confirmed event"
    )
```

**These three tests exist because the council refuted the obvious gate.** The measured schema is
`CREATE UNIQUE INDEX idx_signals_whisper_type_source_unique ON signals(whisper_log_id, signal_type, source) WHERE whisper_log_id IS NOT NULL`
(`schema.sql:189`) — **`polarity` is not in the key**, and `affinity` has no unique index in
`schema.sql` at all (its indexes are created by migration code). So "did the signals INSERT add a
row?" is wrong in both directions: 10b would be a false negative, 10c a false positive. The gate has
to be a state transition of the *event*, computed inside the transaction. Steps 3 and 3b implement it.

The helper's assumptions are verified, not guessed: `schema.sql:116-124` declares `whisper_log` with both `id` and `node_id`, and `_log_feedback_candidates` (`memory_engine.py:561`) performs the `INSERT INTO whisper_log` at `:600`. `recall_search` calls it with `surface="recall_search"`, so a search is enough to seed a row.

- [ ] **Step 2: Run them and confirm which fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use_contract.py -v -k "confirm or heuristic or negative" )
```

Expected: contract 7 **PASSES** (`recall_node` already confirmed its node; this is a regression pin). Contract 8 **FAILS** for all three sources — feedback records affinity and signals but never reinforces. Contract 10b **FAILS** for the same reason (nothing confirms, so the negative-to-positive flip changes nothing). Contracts 9, 10, 10a and 10c **PASS** vacuously, because nothing confirms yet; they become meaningful once Steps 3 and 3b land, which is exactly why they are written now.

Record the exact pass/fail split you observe. If 10a or 10c fails at this point, something already reinforces and the premise of Task 1 is wrong — stop and investigate rather than proceeding.

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
            resolved_node_id, became_confirmed, message = self._submit_feedback_locked(
                node_id=node_id,
                signal=signal,
                source=source,
                whisper_log_id=whisper_log_id,
            )
        # Reinforcement runs after the transaction commits: db.transaction() holds a
        # process-level lock for its whole body, and _record_confirmed_use does file
        # I/O. Calling it inside would also take db_lock before memory_lock, inverting
        # the order every serialized writer uses. A crash in this gap costs this
        # event's reinforcement permanently — see the note below.
        if became_confirmed:
            self._record_confirmed_use(resolved_node_id)
        return message
```

Note the gate is now `became_confirmed` alone: the signal, the source allowlist and the resolution check all fold into it, computed inside the transaction where the before/after state is visible.

In `_submit_feedback_locked`, change the return type annotation and both return statements. The signature (`:2514-2520`) becomes:

```python
    def _submit_feedback_locked(
        self,
        node_id: str,
        signal: int,
        source: str = "explicit",
        whisper_log_id: int | None = None,
    ) -> tuple[str | None, bool, str]:
```

The early error return (`:2532-2533`) becomes:

```python
        if error is not None:
            return None, False, error
```

The final return (`:2612`) becomes:

```python
        return (
            resolved_node_id,
            became_confirmed,
            f"Feedback recorded for node {resolved_node_id[:8]}...",
        )
```

`_submit_feedback_locked` has exactly one caller (`submit_feedback`), so no other site needs updating. Verify:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && grep -rn "_submit_feedback_locked" src/ tests/ )
```

- [ ] **Step 3b: Compute `became_confirmed` as an event state transition**

Still in `_submit_feedback_locked`. Add the helper as a method on `MemoryEngine`, next to the feedback helpers:

```python
    def _event_is_confirmed(self, conn, whisper_log_id: int, node_id: str) -> bool:
        """True when this whisper event already counts as a confirmed use.

        Confirmation is a property of the (event, node) pair, not of a request:
        one qualified positive makes it true and further requests cannot make it
        true again. Sources outside the allowlist and negative signals never
        satisfy it.
        """
        placeholders = ",".join("?" * len(_CONFIRMED_USE_SOURCES))
        row = conn.execute(
            f"""
            SELECT 1 FROM affinity
            WHERE whisper_log_id = ? AND node_id = ? AND signal = 1
              AND source IN ({placeholders})
            LIMIT 1
            """,
            (whisper_log_id, node_id, *sorted(_CONFIRMED_USE_SOURCES)),
        ).fetchone()
        return row is not None
```

Inside the existing `with self.db.transaction() as conn:` block (`:2544`), read the state **before** the writes — as the first statement in the block, above the affinity `INSERT`:

```python
        with self.db.transaction() as conn:
            was_confirmed = self._event_is_confirmed(conn, whisper_log_id, resolved_node_id)
```

and read it again as the **last** statement of the same block, after the signals insert:

```python
            became_confirmed = (
                not was_confirmed
                and self._event_is_confirmed(conn, whisper_log_id, resolved_node_id)
            )
```

**Why two reads instead of a rowcount.** Walked through the three idempotency contracts:

| Case | before | after | `became_confirmed` |
| --- | --- | --- | --- |
| 10a — explicit `+1` replayed | confirmed | confirmed | `False` — no double reinforcement |
| 10b — explicit `-1` then `+1` | not confirmed (row is `signal = -1`) | confirmed (the explicit `UPDATE` flips it) | `True` — a real confirmation |
| 10c — implicit `+1` then explicit `+1` | confirmed | confirmed | `False` — one event, one confirmation |
| contract 9 — `auto_heuristic` `+1` | not confirmed | still not confirmed (source outside the allowlist) | `False` |
| contract 10 — any `-1` | not confirmed | not confirmed (`signal = 1` never matches) | `False` |
| contract 8 — first qualified `+1` | not confirmed | confirmed | `True` |

The two reads are cheap (indexed on `whisper_log_id`) and, unlike a rowcount, they do not depend on
which columns happen to be in a unique index. **This also survives a DB with no unique index on
`affinity`** — those indexes come from migration code, not `schema.sql`, so a legacy database can
accumulate duplicate rows; `EXISTS`-style reads are indifferent to that, while a rowcount is not.

- [ ] **Step 4: Run the feedback contracts — all must pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use_contract.py -v )
```

Expected: all pass, including contracts 9 and 10, which now genuinely discriminate.

- [ ] **Step 5: Write the failing session-watcher tests**

Append to `tests/test_background/test_session_watcher.py`, modelled on the existing `test_llm_judge_promotes_used_verdict`.

First the shared helper — these tests must honour the same dual-store contract as Task 1's, reading all four lifecycle fields from the markdown file **and** the SQLite row. Reading only `file_store` (as the first draft did) would pass while a DB-only or file-only write rotted the other store:

```python
_LIFECYCLE_FIELDS = ("access_count", "last_accessed", "stability", "last_review")


def _lifecycle(engine, node_id):
    """The four lifecycle fields, from the markdown file and the SQLite row."""
    node = engine.file_store.load(node_id)
    row = engine.db.conn.execute(
        "SELECT access_count, last_accessed, stability, last_review FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    return {
        "file": tuple(getattr(node, f) for f in _LIFECYCLE_FIELDS),
        "db": tuple(row[f] for f in _LIFECYCLE_FIELDS),
    }
```

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

    before = _lifecycle(engine, node_id)

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

    after = _lifecycle(engine, node_id)
    assert after != before, "the judged-used node was not confirmed"
    assert after["file"][0] == before["file"][0] + 1, "access_count did not advance by one"
    assert after["db"][0] == after["file"][0], "file and DB disagree on access_count"

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

    before = _lifecycle(engine, node_id)

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

    assert _lifecycle(engine, node_id) == before, "an unused verdict changed lifecycle fields"
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

    before = _lifecycle(engine, node_id)

    recorded = _record_whisper_usage_signals(engine, transcript)

    # The heuristic signal is still recorded — this is about lifecycle, not observability.
    assert recorded == 1
    signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal["polarity"] == 1

    assert _lifecycle(engine, node_id) == before, "auto_heuristic confirmed use — it must not"
```

This test must pass both before and after Step 7 — it pins that the change to the judge block did not leak into the heuristic block. The two paths use separate transactions (`:498` and `:561`), so the isolation is structural, but structure is an argument and this is a measurement.

Two more, both from council findings:

```python
def test_replaying_the_judge_does_not_reconfirm(engine, tmp_path):
    """Issue #220: a second pass over the same transcript reinforces nothing.

    has_llm_judge already excludes an event that was judged before, so the
    replay must not even reach the confirm loop. This pins that the exclusion
    covers reinforcement and not only signal insertion.
    """
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-replay-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-replay-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

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
    after_first = _lifecycle(engine, node_id)

    with patch(_LLM_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    assert _lifecycle(engine, node_id) == after_first, (
        "replaying the judge reinforced the same event twice"
    )


def test_one_failing_node_does_not_skip_the_rest_of_the_batch(engine, tmp_path):
    """Issue #220: reinforcement is isolated per node, for any exception.

    The judge signals are already committed when this loop runs, so an escaping
    exception would abort the slice and — because has_llm_judge is now set —
    the retry would never re-judge these events. The later nodes would lose
    their only chance at confirmation.

    ZeroDivisionError is the realistic case, not a contrived one: stability is
    Field(default=1.0, ge=0.0), so zero is legal, and the mutator divides by it.
    """
    prompt = "What deployment marker should we use?"
    response = "Both of those notes are exactly right."
    transcript_path = tmp_path / "judge-batch-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    first_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact", title="Blue deployment rollback marker",
    ))
    second_id, _ = engine.remember(CreateNodeRequest(
        content="Roll back within one minute when the marker check fails.",
        type="fact", title="Rollback timing",
    ))
    log_ids = [
        _insert_injected_whisper_log(
            engine, node_id=node_id, session_id="judge-batch-session", prompt=prompt,
        )
        for node_id in (first_id, second_id)
    ]
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before_second = _lifecycle(engine, second_id)

    real_mutator = engine._record_confirmed_use

    def failing_for_first(node_id):
        if node_id == first_id:
            raise ZeroDivisionError("float division by zero")
        return real_mutator(node_id)

    llm_response = json.dumps({
        "verdicts": [
            {"whisper_log_id": log_id, "verdict": "used", "confidence": 0.9,
             "reason": "endorsed"}
            for log_id in log_ids
        ]
    })
    with patch(_LLM_PATCH, return_value=llm_response), \
         patch.object(engine, "_record_confirmed_use", side_effect=failing_for_first):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 2, "the signals themselves must still be recorded"
    assert _lifecycle(engine, second_id) != before_second, (
        "the first node's failure skipped the second node's reinforcement"
    )
```

The batch test only discriminates if `first_id` is reinforced **before** `second_id`. `confirmed_node_ids` is appended in `judge_records` order, which follows the query's row order — if that turns out not to put `first_id` first, make the ordering explicit in the implementation rather than weakening the assertion.

- [ ] **Step 6: Run them and watch the positive case fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_background/test_session_watcher.py -v -k "confirmed_use" )
```

Expected: `test_llm_judge_used_verdict_records_confirmed_use` **FAILS** (`access_count` unchanged — nothing confirms yet), and `test_one_failing_node_does_not_skip_the_rest_of_the_batch` **FAILS** too (the second node is never reinforced, because nothing reinforces). The unused-verdict, heuristic and replay tests **PASS**; all three pass vacuously at this point and become discriminating after Step 7, which is why they are written now.

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
    # for the length of N file saves — and would take db_lock before memory_lock,
    # inverting the order every serialized writer uses.
    #
    # Each node is isolated: the signals above are already committed, so letting one
    # node's failure escape would abort the ingest slice, skip every later node, and
    # leave has_llm_judge set — the retry then filters this event out and the skipped
    # reinforcements are lost for good. Failures here are logged, never raised.
    for node_id in confirmed_node_ids:
        try:
            engine._record_confirmed_use(node_id)
        except Exception:
            logger.exception("confirmed-use reinforcement failed for node %s", node_id)

    return recorded
```

The `auto_heuristic` block at `:498` is **not** modified. The two paths do not share a transaction, so no heuristic record can reach this list.

**`except Exception`, not `except OSError`** (council finding, round 2). `OSError` alone does not cover what this mutator can raise. **Verified on `upstream/main`:** `MemoryNode.stability` is `Field(default=1.0, ge=0.0)` (`models/node.py:59`), so zero is a legal value, and the mutator computes `math.exp(-days_since / node.stability)` (`memory_engine.py:1946`) — a real `ZeroDivisionError` on any node whose stability has reached zero. Add `sqlite3.Error` from the DB update and validation errors from markdown parsing, and a narrow catch would still let one bad node take out the rest of the batch. Confirm the module already binds `logger`; `session_watcher.py` does, so no new import is needed beyond that check.

**What this does not fix, stated honestly.** A hard process kill between the `COMMIT` and this loop still loses that batch's reinforcement, and the loss is permanent — `has_llm_judge` keeps the retry from re-judging. The claim in the earlier draft that "the next confirmed use restores it" was **wrong**, and the council quantified it: with `S = 1` and `growth = 1.5`, uses on day 1 and day 2, dropping the day-1 update yields about **2.24** stability instead of **3.07**. The node stays permanently below its true trajectory. This cost is accepted rather than fixed: the alternative is a durable pending-event table plus a reconciliation loop, which the spec rejected as disproportionate and which the council agreed the residual crash window alone does not justify.

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

submit_feedback now reinforces when a whisper event first becomes a qualified
positive: signal == 1 with a source in explicit, implicit or auto_llm_judge.
The allowlist is fail-closed, so auto_heuristic (pending #218) and every
negative signal do not reinforce. The gate is a state transition of the event
read inside the transaction, not a rowcount: affinity and signals both use ON
CONFLICT DO NOTHING and their unique key excludes polarity, so a replay would
report zero on a real negative-to-positive flip and one on an already-confirmed
event reaching a second source. The session watcher's auto_llm_judge path does
the same for its positive verdicts, isolated per node so one bad node cannot
abort the ingest slice.

Reinforcement runs after the enclosing transaction commits rather than inside
it: db.transaction() holds a process-level lock for its whole body, the mutator
writes markdown to disk, and calling it inside would take db_lock before
memory_lock. The accepted cost is a hard crash between COMMIT and the
reinforcement: that event's update is lost permanently, since the watcher will
not re-judge it, and the node's stability stays below its true trajectory.

Refs #220" )
```

- [ ] **Step 11: Report, and do not open the PR**

Push the branch to your fork:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && git push fork fix/220-confirmed-use )
```

**Stop there.** The PR must not be opened while draft PR [#229](https://github.com/r-spade/ormah/pull/229) still declares `Closes #220–#223`. Report the branch as ready and state that the PR is blocked on #229 being closed as superseded.

When it is unblocked, the PR body must mention that `FileStore.touch_access` (`src/ormah/store/file_store.py:145`) is a namesake left untouched on purpose, so a reviewer does not read it as an oversight.
