# Task 1: Budget the Batch on conversation length

**Files:**
- Modify: `src/ormah/transcript/parser.py:199-203` (extract `_format_turn`)
- Modify: `src/ormah/transcript/parser.py:206-262` (signature, counters, predicate)
- Modify: `src/ormah/transcript/parser.py:301,332,356,339,359` (call sites)
- Modify: `src/ormah/background/session_watcher.py:864,889` (the only two callers of the renamed keyword)
- Test: `tests/test_transcript/test_parser.py` (new tests appended)

⚠️ **The watcher call sites move in THIS task, not Task 3** (council R3, Codex). Renaming the keyword
here while `session_watcher.py` still passes `max_bytes=` would leave Task 1 and Task 2 as knowingly
broken commits — `_ingest_session` would raise `TypeError`, which its own `except Exception` converts
into `NO_PROGRESS`, so the watcher suite Task 2 asks you to run could not pass. Every commit in this
plan must be independently green.

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `parse_transcript(path, start_offset=0, max_conversation_chars=None, stop_offset=None)`.
  The `max_bytes` keyword is **gone** — Task 2 adds `max_raw_bytes` as a separate keyword.
  Also exported for tests: `_format_turn(turn) -> str` and `_TURN_SEPARATOR = "\n\n"`.

Read the spec section "1 · Parser predicate" before starting. The commit-site asymmetry table there is
the part that gets implemented wrong if skimmed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transcript/test_parser.py`:

```python
def _tool_heavy_jsonl(path, turns: int, text_chars: int = 500, noise_chars: int = 40000) -> None:
    """A transcript whose RAW bytes dwarf its CLEANED conversation.

    Each turn carries a little real conversation and a large tool_use/tool_result payload the
    Extractor never sees. This is the fixture that DISCRIMINATES the two budget axes: under a
    byte budget one turn exhausts the batch; under a content budget many turns fit. A fixture
    padded with plain user text passes identically under both units and proves nothing.
    """
    import json
    lines = []
    for i in range(turns):
        lines.append({"type": "user", "message": {"role": "user",
                      "content": f"u{i} " + "q" * text_chars}})
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"blob": "N" * noise_chars}}]}})
        lines.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "M" * noise_chars}]}})
        lines.append({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": f"a{i} " + "r" * text_chars}],
                      "stop_reason": "end_turn"}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def test_projected_length_matches_rendered_conversation():
    """The running counter and the rendered payload must not be able to drift.

    Both go through _format_turn and _TURN_SEPARATOR; this pins the arithmetic the parser
    uses to decide a boundary against the string the Extractor actually receives.
    """
    from ormah.transcript.parser import (
        _TURN_SEPARATOR, TranscriptTurn, _conversation_from_turns, _format_turn,
    )
    turns = [
        TranscriptTurn(role="user", text="hello"),
        TranscriptTurn(role="assistant", text="world"),
        TranscriptTurn(role="user", text="again"),
    ]
    for k in range(len(turns) + 1):
        incremental = (
            sum(len(_format_turn(t)) for t in turns[:k])
            + len(_TURN_SEPARATOR) * max(0, k - 1)
        )
        assert incremental == len(_conversation_from_turns(turns[:k])), f"drift at k={k}"


def test_content_budget_batches_many_turns_a_byte_budget_could_not(tmp_path):
    """The regression Amendment 3 exists to kill: tool-heavy turns must BATCH.

    Each turn here spends ~80KB of raw transcript on tool payloads and ~1KB on conversation.
    A byte budget of 60000 is exhausted by the first turn alone, so it committed exactly one
    user turn. A 60000-CHAR content budget must fit dozens.
    """
    from ormah.transcript.parser import parse_transcript

    path = tmp_path / "toolheavy.jsonl"
    _tool_heavy_jsonl(path, turns=30)

    result = parse_transcript(path, max_conversation_chars=60000)

    assert result.safe_user_turn_count >= 5, (
        f"only {result.safe_user_turn_count} user turn(s) batched — the budget is still "
        "bounded by a quantity the Extractor never sees"
    )
    assert len(result.safe_conversation) <= 60000


def test_content_budget_never_commits_past_the_budget(tmp_path):
    """A multi-turn slice's committed conversation stays within the budget — break BEFORE
    the turn that would overshoot, not after."""
    from ormah.transcript.parser import parse_transcript

    path = tmp_path / "toolheavy.jsonl"
    _tool_heavy_jsonl(path, turns=30, text_chars=2000)

    result = parse_transcript(path, max_conversation_chars=20000)

    assert result.capped is True
    assert len(result.safe_conversation) <= 20000
    assert result.safe_user_turn_count > 1


def test_terminal_assistant_turn_counts_toward_the_budget(tmp_path):
    """The commit-site asymmetry: at the terminal-assistant site the budget check runs
    BEFORE the append, but the commit INCLUDES that turn. Forgetting it under-counts by a
    whole turn and lets the slice exceed the budget."""
    from ormah.transcript.parser import parse_transcript

    import json
    lines = [
        {"type": "user", "message": {"role": "user", "content": "u0"}},
        {"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "a0"}]}},
        {"type": "user", "message": {"role": "user", "content": "u1"}},
        {"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Z" * 900}]}},
    ]
    path = tmp_path / "asym.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    # Budget large enough for turns 1-3 but NOT for the 900-char assistant turn.
    result = parse_transcript(path, max_conversation_chars=200)

    assert result.capped is True
    assert len(result.safe_conversation) <= 200
    assert not any(t.text.startswith("Z") for t in result.safe_turns)


def test_single_oversized_turn_is_still_committed(tmp_path):
    """The progress guard: a lone turn bigger than the budget can't be shrunk, so it is
    committed as its own slice. This guard is load-bearing for Task 2's rewind invariant."""
    from ormah.transcript.parser import parse_transcript

    import json
    lines = [
        {"type": "user", "message": {"role": "user", "content": "u0"}},
        {"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "X" * 50000}]}},
    ]
    path = tmp_path / "oversized.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    result = parse_transcript(path, max_conversation_chars=1000)

    assert result.safe_user_turn_count == 1
    assert len(result.safe_conversation) > 1000  # unavoidable for a lone oversized turn
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./.venv/bin/python -m pytest tests/test_transcript/test_parser.py -k "projected_length or content_budget or terminal_assistant or single_oversized" -v
```

Expected: FAIL — `TypeError: parse_transcript() got an unexpected keyword argument
'max_conversation_chars'`, and `ImportError` for `_format_turn` / `_TURN_SEPARATOR`.

- [ ] **Step 3: Extract the shared turn renderer**

Replace `src/ormah/transcript/parser.py:199-203` with:

```python
_TURN_SEPARATOR = "\n\n"


def _format_turn(turn: TranscriptTurn) -> str:
    """The exact rendering a turn gets in the Extractor's payload.

    ``_conversation_from_turns`` and the parser's running length counter MUST both go through
    this function. The budget is only correct while the length it accumulates is the length
    the Extractor receives — that identity is the whole point of ADR-0001 Amendment 3.
    """
    return f"{turn.role.title()}: {turn.text}"


def _conversation_from_turns(turns: list[TranscriptTurn]) -> str:
    return _TURN_SEPARATOR.join(_format_turn(turn) for turn in turns)
```

- [ ] **Step 4: Change the signature and the docstring**

In `parse_transcript`, replace the `max_bytes: int | None = None` parameter (`parser.py:209`) with:

```python
    max_conversation_chars: int | None = None,
```

Replace the `When *max_bytes* is set, ...` docstring paragraph (`parser.py:222-226`) with:

```
    When *max_conversation_chars* is set, parsing stops BEFORE committing a turn that would
    push the CLEANED conversation of the closed slice past that budget — so a multi-turn slice
    never exceeds it. The caller re-parses from the new ``safe_end_offset`` to drain the rest.
    A single turn larger than the budget is committed anyway (there is no smaller slice to make
    progress with); that progress guard is what keeps ``capped`` implying an advanced safe
    boundary, which is what keeps ``should_rewind`` (ADR-0003) unreachable from a capped parse.

    The budget is measured on conversation the Extractor receives, NOT on transcript bytes
    (ADR-0001 Amendment 3): the raw→clean ratio ranges from ~3x to ~93x, so a byte budget bounds
    a quantity uncorrelated with recall.
```

Also fix the `stop_offset` paragraph at `parser.py:230`: replace `` ``max_bytes`` alone commits an
oversized single turn anyway `` with `` ``max_conversation_chars`` alone commits an oversized single
turn anyway ``.

- [ ] **Step 5: Add the counters and the predicate**

Replace `parser.py:253-262` (the `_capped` declaration and `_would_overshoot`) with:

```python
    _capped = False  # a budget stopped the parse before an overshooting turn
    # _len_after[k] == len(_conversation_from_turns(turns[:k])) — maintained incrementally so a
    # candidate boundary costs O(1) instead of re-joining the whole slice at every commit site.
    _len_after: list[int] = [0]

    def _projected_len(pending: TranscriptTurn | None) -> int:
        """Conversation length once *pending* (if any) joins the turns already accumulated."""
        base = _len_after[-1]
        if pending is None:
            return base
        separator = len(_TURN_SEPARATOR) if turns else 0
        return base + separator + len(_format_turn(pending))

    def _commit_turn(turn: TranscriptTurn) -> None:
        new_len = _projected_len(turn)  # BEFORE the append — the separator depends on `turns`
        turns.append(turn)
        _len_after.append(new_len)

    def _would_overshoot(pending: TranscriptTurn | None = None) -> bool:
        # Only refuse a candidate boundary once something is already committed — a first turn
        # alone can't be shrunk further, so it is always allowed through. Do NOT remove this
        # progress guard: it is what makes `capped` imply `safe_end_offset > start_offset`.
        return (
            max_conversation_chars is not None
            and _safe_len > 0
            and _projected_len(pending) > max_conversation_chars
        )
```

- [ ] **Step 6: Update the three commit sites**

`parser.py:301` (Codex `task_complete`) and `parser.py:332` (new user turn) — the committed set is
`turns` as it stands, so drop the argument:

```python
                    if _would_overshoot():
                        _capped = True
                        break
```

`parser.py:339` (user turn append) becomes:

```python
                    _commit_turn(TranscriptTurn(role="user", text=text))
                    user_turn_count += 1
```

`parser.py:353-359` (assistant) — build the turn first so the check can see it, because the commit
includes it:

```python
                if text and user_turn_count > 0:
                    pending = TranscriptTurn(role="assistant", text=text)
                    if _assistant_is_terminal(entry) and _exceeds_ceiling(f.tell()):
                        break  # ceiling: refuse an oversized/grew-after turn entirely
                    if _assistant_is_terminal(entry) and _would_overshoot(pending):
                        _capped = True
                        break
                    _commit_turn(pending)
```

- [ ] **Step 7: Re-express the existing parser test**

In `tests/test_transcript/test_parser.py:764`, rename the keyword:

```python
        bounded = parse_transcript(path, max_conversation_chars=10, stop_offset=ceiling)
```

Update the two docstring mentions of `max_bytes` at lines 750 and 752 to `max_conversation_chars`.

- [ ] **Step 7b: Move the two watcher call sites in the SAME commit**

`session_watcher.py:864` and `:889` are the only callers of the renamed keyword. Update just the
keyword — the watcher's own `flush_bytes` parameter keeps its name until Task 3, so this stays a
one-word change and the tree stays green:

```python
        result = parse_transcript(
            path, start_offset=prev_offset, max_conversation_chars=flush_bytes, stop_offset=boundary
        )
```

```python
            result = parse_transcript(
                path, start_offset=0, max_conversation_chars=flush_bytes, stop_offset=boundary
            )
```

Leave the uncapped probe at `:880` untouched — it must stay uncapped or a recoverable file gets
mis-parked (ADR-0003).

- [ ] **Step 7c: Rename the keyword at the remaining TEST call sites too**

`tests/test_background/test_session_watcher_flush.py` calls `parse_transcript(..., max_bytes=...)` at
lines 58, 67, 79 and 94. Task 3 rewrites those tests wholesale, but leaving them broken here would make
this commit red. Rename **only the keyword** now (`max_bytes=` → `max_conversation_chars=`); their
assertions still pass because that fixture pads with plain user text, where raw bytes ≈ cleaned chars.
Task 3 replaces them with discriminating versions.

```bash
grep -rn "max_bytes" src/ tests/ | grep -v "max_raw_bytes"
```

Expected: **no hits**, across `src/` *and* `tests/` (council: an earlier draft grepped only `src/` and
would have missed the test callers). A remaining hit is a caller that will `TypeError` at runtime.

- [ ] **Step 8: Run the FULL suite, not just the parser**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: PASS, all of them — **including every orphan/rewind test, unedited**. If an orphan test
needs editing, STOP: the design's premise (boundary positions unchanged, only the choice among
candidates) has failed and the plan must go back to review.

- [ ] **Step 9: Lint and commit**

⛔ **Stage `session_watcher.py` and the flush tests too** — both council peers caught an earlier draft
that described moving the call sites in prose but staged only the parser. A commit that renames the
keyword without its callers `TypeError`s on checkout, and `_ingest_session`'s `except Exception`
converts that into a silent `NO_PROGRESS`. Verify the **committed tree**, not the dirty working tree.

```bash
ruff check src/ tests/
git add src/ormah/transcript/parser.py \
        src/ormah/background/session_watcher.py \
        tests/test_transcript/test_parser.py \
        tests/test_background/test_session_watcher_flush.py
git commit -m "feat(parser): budget the batch on conversation length, not transcript bytes

ADR-0001 Amendment 3: _would_overshoot compared a byte-offset delta while the
Extractor only ever receives safe_conversation, so the ~15K-token sweet spot was
missed by ~18x. Budget the cleaned conversation instead, tracked incrementally so a
candidate boundary stays O(1).

The progress guard (_safe_len > 0) is preserved deliberately: it is what makes a
capped parse imply an advanced safe boundary, keeping should_rewind (ADR-0003)
unreachable from a cap."
```
