# Task 3: Re-anchor the Judge's Suppression on Confirmation

**Depends on:** Task 2. **Read `00-overview.md` first — its Global Constraints apply.**

**Files:**
- Modify: `src/ormah/background/session_watcher.py` (`:439-457` query, `:486-506` loop,
  `:588-595` the judge's affinity write)
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

## The regression this task creates, and must therefore close

Sending weak hits to the judge is the point of this task — and it is also what makes a latent
contradiction reachable for the first time. Found by Codex (HIGH) in the council run on the final
plan, and verified against the base:

- Task 2 writes `_insert_affinity(signal=1, source=_HEURISTIC_AFFINITY_SOURCE)` for **every**
  positive hit, `token_overlap` included — the claim is gated by the floor, the affinity row is not.
- `affinity` carries `idx_affinity_node_whisper_log_unique ON affinity(node_id, whisper_log_id)
  WHERE whisper_log_id IS NOT NULL` (`index/db.py:389-393`), and `_insert_affinity` uses
  `ON CONFLICT DO NOTHING` (`session_watcher.py:385-414`).
- So if the judge now answers `irrelevant` for that same event, its `-1` row is **silently
  discarded**. `signals` records the negative verdict, but retrieval keeps consuming the earlier
  `+1`: the memory stays boosted by a reference the judge just rejected.

Today this is unreachable — `referenced = int(heuristic_polarity) == 1` (`:503-505`) stops a positive
hit from ever being queued, and Step 4 deletes that branch. **The defect arrives with this task, so
it closes with this task.**

### Precedence follows the pattern the repo already uses

`_submit_feedback_locked` (`memory_engine.py:2849-2877`) already resolves exactly this: it runs
`INSERT ... ON CONFLICT DO NOTHING`, then an `UPDATE` **conditional on the source** — `explicit`
overwrites whatever sits there, other sources do not. Step 5 applies the same shape one rung down,
giving `explicit` > `auto_llm_judge` > `auto_heuristic`.

The judge overwrites only a row whose source is `auto_heuristic`, so a human's `explicit` feedback is
never clobbered. Deferring the heuristic's affinity write instead was rejected: with the judge off by
default, deferral would silently drop the `+1` that today's `token_overlap` hits legitimately produce
— a retrieval change well outside this issue.

---

## The judge preamble is mandatory in every test below

Council round 1 (Cursor, HIGH) caught this and it was verified against the base: the judge does not
run unless **both** flags are on. `_feedback_llm_judge_enabled` is

```python
return bool(
    getattr(settings, "feedback_llm_judge_enabled", False)
    and getattr(settings, "llm_enabled", False)   # llm_enabled is llm_provider != "none"
)
```

and the defaults leave it off. A test that omits the preamble asserts `mock_llm.called` against a
judge that structurally cannot run — it fails identically before and after a correct implementation,
so it cannot falsify anything.

The payload key is **`verdicts`**, not `judgments`: `_llm_judge_whisper_usage` reads
`parsed.get("verdicts")`. `_LLM_PATCH` (`"ormah.background.llm_client.llm_generate"`) is the right
target — that is the symbol the judge imports.

Every test in this task therefore carries:

```python
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True
```

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
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    llm_response = json.dumps({"verdicts": [{
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


def test_an_irrelevant_verdict_overrides_the_weak_heuristic_affinity(engine, tmp_path):
    """#272, council (Codex HIGH): the judge outranks the heuristic for the same event.

    This task is what makes the conflict reachable: a token_overlap hit now gets both
    an affinity +1 from the heuristic block AND a trip to the judge. affinity has a
    unique (node_id, whisper_log_id) index and _insert_affinity is ON CONFLICT DO
    NOTHING, so without Step 5 the judge's -1 is silently dropped and retrieval keeps
    consuming a +1 the judge just rejected.

    Red before Step 5 on the final row's polarity, not on the signal: the signals table
    records the negative verdict either way. The affinity row is the falsifier.
    """
    prompt = "What about the retention policy?"
    response = "Retention uses decay, stability and archival thresholds together."
    transcript_path = tmp_path / "irrelevant-override-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Decay lowers stability until archival thresholds move a node out of working.",
        type="fact",
        title="Decay stability archival thresholds",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="irrelevant-override-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    llm_response = json.dumps({"verdicts": [{
        "whisper_log_id": whisper_log_id,
        "verdict": "irrelevant",
        "confidence": 0.95,
        "reason": "The answer never uses the injected memory.",
    }]})
    with patch(_LLM_PATCH, return_value=llm_response) as mock_llm:
        _record_whisper_usage_signals(engine, transcript)

    assert mock_llm.called, "the weak hit never reached the judge — check Step 4"

    affinity = engine.db.conn.execute(
        "SELECT signal, source FROM affinity WHERE node_id = ? AND whisper_log_id = ?",
        (node_id, whisper_log_id),
    ).fetchall()
    assert len(affinity) == 1, "the unique index should keep exactly one row per event"
    assert affinity[0]["signal"] == -1, (
        "the heuristic's +1 survived an irrelevant verdict — retrieval will keep boosting "
        "a memory the judge rejected"
    )
    assert affinity[0]["source"] == "auto_llm_judge"

    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert claim is None, "a negative verdict took a confirmed-use claim"


def test_explicit_feedback_outranks_a_later_judge_verdict(engine, tmp_path):
    """#272: precedence is explicit > auto_llm_judge > auto_heuristic, not last-write-wins.

    Step 5's UPDATE is scoped to source = 'auto_heuristic' precisely so a human's
    explicit feedback is never overwritten by an automated verdict. Drop that WHERE
    clause and this goes red.

    The feedback is NEGATIVE, and that is load-bearing — not a stylistic choice.
    An earlier draft used signal=1 and could not fail: a positive explicit feedback
    takes the _claim_confirmed_use latch synchronously inside _submit_feedback_locked
    (memory_engine.py:2842-2849), so Step 3's already_confirmed reads True, Step 4's
    `settled` is True, the judge is never queued, the patched LLM is never called and
    Step 5's UPDATE never runs at all. The assertion then passed on Task 2's
    ON CONFLICT DO NOTHING alone, with the scoping clause deleted or intact.

    signal=-1 is the path that reaches Step 5: _claim_confirmed_use returns False for
    any signal != 1, so the affinity row is written as 'explicit' while NO claim is
    taken. already_confirmed is False, `confirms` is False (the response only
    token-overlaps, whose band supremum 0.78 sits under the 0.80 floor), so the event
    is unsettled, the judge runs, and its UPDATE fires against a row whose source is
    'explicit'. Only the `AND source = 'auto_heuristic'` clause leaves it standing.

    It is also the real scenario: a human marked a memory as NOT useful, which does
    not settle the event, and the judge's later verdict must not overwrite the
    attribution back to itself.
    """
    prompt = "What about the retention policy?"
    response = "Retention uses decay, stability and archival thresholds together."
    transcript_path = tmp_path / "explicit-outranks-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Decay lowers stability until archival thresholds move a node out of working.",
        type="fact",
        title="Decay stability archival thresholds",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="explicit-outranks-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    # A human says this memory was NOT useful, through MCP. This writes the affinity
    # row as 'explicit' WITHOUT taking the claim (signal != 1), which is what leaves
    # the event unsettled so the judge below actually runs. See the docstring.
    engine.submit_feedback(node_id, signal=-1, source="explicit", whisper_log_id=whisper_log_id)

    llm_response = json.dumps({"verdicts": [{
        "whisper_log_id": whisper_log_id,
        "verdict": "irrelevant",
        "confidence": 0.95,
        "reason": "The answer never uses the injected memory.",
    }]})
    with patch(_LLM_PATCH, return_value=llm_response) as mock_judge:
        _record_whisper_usage_signals(engine, transcript)

    affinity = engine.db.conn.execute(
        "SELECT signal, source FROM affinity WHERE node_id = ? AND whisper_log_id = ?",
        (node_id, whisper_log_id),
    ).fetchone()
    assert affinity["source"] == "explicit", "an automated verdict overwrote explicit feedback"
    assert affinity["signal"] == -1, "the human's negative signal was replaced"

    # The guard on the guard: if the judge never ran, the two assertions above hold
    # trivially and prove nothing about the scoping clause. This is what the earlier
    # signal=1 draft failed silently.
    assert mock_judge.called, (
        "the judge never ran, so Step 5's UPDATE never executed and this test cannot "
        "distinguish a scoped UPDATE from an unscoped one"
    )


def test_a_confirming_heuristic_hit_does_not_reach_the_judge(engine, tmp_path):
    """#272 D3: judging an event that already confirmed is wasted spend.

    Council (Cursor, MEDIUM) on the final plan: asserting only `not mock_llm.called`
    is not enough. The plan itself notes this already passes on the old `referenced`
    rule, so on its own it pins nothing about #272. Worse, an implementation that
    calls _claim_confirmed_use only when `not llm_judge_enabled` would keep every
    Task 2 test green (the judge is off by default there) AND this one green — while
    in production, with the judge armed, a verbatim hit would be neither claimed nor
    judged. The claim and lifecycle assertions below are what falsify that.
    """
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
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="strong-skips-judge-session", prompt=prompt,
    )
    # The judge is ENABLED here on purpose: with it off, "not called" would be
    # vacuously true and the test would pass against any suppression rule at all.
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before = _lifecycle(engine, node_id)
    with patch(_LLM_PATCH) as mock_llm:
        _record_whisper_usage_signals(engine, transcript)

    assert not mock_llm.called, "a confirming heuristic hit was judged anyway"

    # The judge is ARMED here. These two are what stop a claim-only-when-judge-disabled
    # implementation from shipping green.
    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ? AND node_id = ?",
        (whisper_log_id, node_id),
    ).fetchone()
    assert claim is not None, (
        "a verbatim hit took no claim while the judge was enabled — it is now neither "
        "confirmed nor judged"
    )
    assert _lifecycle(engine, node_id) != before, "the claim was taken but nothing reinforced"


def test_an_already_confirmed_event_is_not_rejudged_on_reingest(engine, tmp_path):
    """#272 D3: on RE-INGEST the claim table is the only authority left.

    Council R3 (Cursor, MEDIUM) rejected the first version of this test: it used a
    verbatim response, so the base's old rule suppressed the judge on BOTH passes
    (`referenced` on the first, `heuristic_polarity == 1` on the second) and the test
    passed unchanged. It proved nothing about `already_confirmed`.

    The response is unreferenced instead, and the claim comes from MCP feedback. On
    the second pass `has_heuristic` is true with polarity 0, so the base computes
    `referenced = False` and QUEUES the judge — red today. Only `already_confirmed`
    can suppress it, which is exactly the predicate under test.
    """
    prompt = "How should we solve feedback collection?"
    response = "I don't know."
    transcript_path = tmp_path / "reingest-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact",
        title="Transcript watcher mines feedback usage",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="reingest-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    # The claim arrives through MCP, the one caller has_llm_judge cannot see.
    engine.submit_feedback(node_id, signal=1, source="implicit", whisper_log_id=whisper_log_id)

    # First pass writes the polarity-0 heuristic row that makes the next pass a re-ingest.
    with patch(_LLM_PATCH) as first_llm:
        _record_whisper_usage_signals(engine, transcript)
    assert not first_llm.called, "the judge ran on an event MCP had already confirmed"

    after_first = _lifecycle(engine, node_id)

    # Second pass: has_heuristic is now true, polarity 0. Only the claim can settle it.
    with patch(_LLM_PATCH) as second_llm:
        _record_whisper_usage_signals(engine, transcript)

    assert not second_llm.called, "a settled event was sent to the judge on re-ingest"
    assert _lifecycle(engine, node_id) == after_first, "the event reinforced twice"


def test_mcp_feedback_suppresses_the_judge_for_that_event(engine, tmp_path):
    """#272 D3: closes the cross-caller blindness has_llm_judge cannot see (#220 13a).

    The response is deliberately UNREFERENCED. Council R2 (Cursor, MEDIUM) caught the
    earlier fixture: it overlapped the node, so `referenced` was already true and the
    base's `not referenced` suppressed the judge on its own — the test passed before
    and after, proving nothing. With no textual reference, the base queues the judge
    (red today) and only `already_confirmed` can suppress it (green after).
    """
    prompt = "What about the retention policy?"
    response = "I don't know."
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
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

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

**Red (must fail today):**

- `test_a_weak_heuristic_hit_still_reaches_the_judge` — fails on `assert mock_llm.called`. Today any
  hit suppresses the judge.
- `test_an_irrelevant_verdict_overrides_the_weak_heuristic_affinity` — fails on `assert mock_llm.called`
  before Step 4, then on `affinity[0]["signal"] == -1` after Step 4 and before Step 5. Both failures
  are real; the second is the one this task's own change creates.
- `test_mcp_feedback_suppresses_the_judge_for_that_event` — fails on `assert not mock_llm.called`. The
  response is unreferenced, so the base queues the judge; only `already_confirmed` can stop it.
- `test_an_already_confirmed_event_is_not_rejudged_on_reingest` — fails on the same assertion, on the
  re-ingest pass where `heuristic_polarity` is 0.

**Green (regression pins, not red tests):**

- `test_a_confirming_heuristic_hit_does_not_reach_the_judge` — a title hit already sets `referenced`,
  so the base suppresses the judge for its own reason. It pins that the new rule does not lose that.
  Its claim/lifecycle assertions are green only because Task 2 has already landed; run this task out
  of order and they go red for the right reason.
- `test_explicit_feedback_outranks_a_later_judge_verdict` — green before Step 5 (nothing overwrites
  anything today) and green after (the UPDATE is scoped to `auto_heuristic`). It is the guard on
  Step 5, not a test of it: drop the `AND source = ...` clause and it goes red.

  **This claim was false until the pre-flight scan caught it, and the fix is the `signal=-1` in the
  fixture — do not "simplify" it back to `signal=1`.** With positive feedback the latch is taken
  synchronously inside `_submit_feedback_locked`, `already_confirmed` reads True, Step 4 marks the
  event settled, the judge is never queued and Step 5's UPDATE never runs; the assertion then held
  on Task 2's `ON CONFLICT DO NOTHING` alone, scoping clause present or absent. The `assert
  mock_judge.called` in that test exists to make this failure mode loud instead of silent.

Council round 3 (Cursor) rejected an earlier version of the re-ingest test that belonged in the second
list while being claimed for the first. If a test in the red list passes on the first run, stop: the
fixture is wrong, and adjusting the assertion instead would bake in a test that cannot fail. The
mirror rule holds for this list: if a test in the GREEN list would stay green with the change it
claims to guard deleted, it is not a guard — that is exactly what the paragraph above describes.

**Sanity check before implementing — the preamble must actually arm the judge.** If
`test_a_weak_heuristic_hit_still_reaches_the_judge` fails on `mock_llm.called` even after Step 4, the
judge is off rather than suppressed, and the test is unfalsifiable. Confirm the preamble works first:

```bash
python -m pytest tests/test_background/test_session_watcher.py \
  -k "test_llm_judge_used_verdict_records_confirmed_use" -v
```

That pre-existing test uses the same preamble and must pass on the untouched base. If it does, the
preamble is right and any remaining failure is the real defect.

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

- [ ] **Step 5: Let the judge's verdict outrank the heuristic's affinity row**

In the judge's commit loop, replace the affinity block at `:588-595`:

```python
            if record["polarity"] in (1, -1):
                _insert_affinity(
                    conn,
                    row,
                    signal=record["polarity"],
                    source=_LLM_JUDGE_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )
                # Issue #272: affinity is keyed unique on (node_id, whisper_log_id) and
                # _insert_affinity is ON CONFLICT DO NOTHING, so for an event the
                # heuristic block already wrote a +1 for, the INSERT above is a no-op.
                # Before this task that could not happen — a positive hit never reached
                # the judge — but Step 4 is what sends weak hits here, so without this
                # UPDATE an `irrelevant` verdict would be recorded in signals and
                # silently ignored by retrieval, which would keep consuming the +1.
                #
                # Same shape _submit_feedback_locked uses for explicit feedback
                # (memory_engine.py:2869-2877): INSERT ... DO NOTHING, then an UPDATE
                # scoped by source. Scoped to auto_heuristic ONLY — the judge outranks
                # the heuristic, and explicit feedback outranks the judge.
                conn.execute(
                    """
                    UPDATE affinity
                    SET signal = ?, source = ?, confirmed_at = ?
                    WHERE node_id = ?
                      AND whisper_log_id = ?
                      AND source = ?
                    """,
                    (
                        record["polarity"],
                        _LLM_JUDGE_AFFINITY_SOURCE,
                        now_iso,
                        row["node_id"],
                        row["id"],
                        _HEURISTIC_AFFINITY_SOURCE,
                    ),
                )
```

The UPDATE sits **after** `_insert_affinity` and **before** the `_claim_confirmed_use` call that
follows it in the same loop body. That ordering is deliberate and the existing comment at `:596-602`
explains why nothing may be reordered around the claim: the helper reads `changes()` immediately
after its own INSERT. Since both statements here run before the helper is entered, its read is
unaffected — but do not move this UPDATE below the claim, where a future edit could drift into that
window.

**Why not defer the heuristic's affinity write instead** (the other option Codex offered): the judge
is **off by default** (`feedback_llm_judge_enabled`), so a below-floor hit normally never reaches it.
Deferring would drop the `+1` that `token_overlap` hits legitimately produce today, changing
retrieval for every default install. This task must not do that.

- [ ] **Step 6: Import the floor**

`session_watcher.py:20` already imports `MemoryEngine` at module scope, and `memory_engine.py` does not
import `session_watcher` at all — verified, so there is no cycle. Extend the existing line:

```python
from ormah.engine.memory_engine import HEURISTIC_CONFIRM_FLOOR, MemoryEngine
```

Import the floor rather than reaching for `signal_strength.IMPLICIT` directly: the engine owns what
"enough evidence to confirm" means, and the ladder rung it happens to equal is an implementation
detail of that decision.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
python -m pytest tests/test_background/test_session_watcher.py -v > /tmp/ormah-272-file.txt 2>&1; RC=$?
tail -30 /tmp/ormah-272-file.txt
echo "pytest exit=$RC"
```

Expected: PASS, all four new tests plus every pre-existing one.

- [ ] **Step 8: Run the full suite**

```bash
python -m pytest tests/ -q > /tmp/ormah-272-run.txt 2>&1; RC=$?
tail -20 /tmp/ormah-272-run.txt
echo "pytest exit=$RC"   # 0, or only baseline IDs failed
```

- [ ] **Step 9: Lint and commit**

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
through MCP, which has_llm_judge is structurally blind to.

Sending weak hits to the judge also makes a latent conflict reachable for the
first time, so the same change closes it: affinity is unique per (node, event)
and inserted ON CONFLICT DO NOTHING, so the heuristic's +1 would have swallowed
an irrelevant verdict's -1 and left retrieval boosting a memory the judge had
just rejected. The judge now overwrites an auto_heuristic affinity row, in the
shape submit_feedback already uses for explicit feedback and scoped so that
explicit still outranks both."
```
