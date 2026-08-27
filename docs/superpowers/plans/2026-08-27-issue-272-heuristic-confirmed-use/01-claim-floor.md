# Task 1: The Evidence Floor in `_claim_confirmed_use`

**Depends on:** Task 0 (worktree + baseline). **Read `00-overview.md` first — its Global Constraints apply.**

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (`:57`, `:2722`, `:2764`, `:2812`, `:2895`)
- Test: `tests/test_engine/test_confirmed_use_contract.py`
- Test: `tests/test_signal_strength.py`

**Interfaces:**
- Consumes: `ormah.signal_strength.IMPLICIT` (0.80), `signal_strength.token_overlap_strength(ratio)`,
  `signal_strength.feedback_strength(source, signal)` — all already exist on the base.
- Produces: `HEURISTIC_CONFIRM_FLOOR: float` and the new keyword-only `strength: float` parameter on
  `_claim_confirmed_use`, both consumed by Tasks 2 and 4.

## Background

`_CONFIRMED_USE_SOURCES` omits `auto_heuristic` deliberately — the #220 design conditioned admission on
"#218 providing signal calibration". #218 has landed that calibration, so admission is now correct, but
only above a floor. Without the floor, `token_overlap` (97.4% of heuristic hits, and the least precise
kind) would gain the same lifecycle power as a verbatim `node_id` match.

## Why contract 9 still passes

`test_auto_heuristic_positive_does_not_confirm` calls `submit_feedback(..., source="auto_heuristic")`,
whose strength comes from `signal_strength.feedback_strength`, and `_FEEDBACK_LADDER` maps
`auto_heuristic` to `UNKNOWN` (0.40) — below the floor, always. The test keeps passing without a special
case. Only its docstring is stale. **Do not weaken or delete this test.**

---

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_signal_strength.py`:

```python
def test_token_overlap_never_reaches_the_confirm_floor():
    """#272 D1: token_overlap is excluded from confirmed use BY CONSTRUCTION.

    The band's supremum is OVERLAP_FLOOR + OVERLAP_SPAN == 0.78, so no reachable
    overlap_ratio can clear a 0.80 floor. Measured max on a live store: 7.583.
    """
    from ormah.engine.memory_engine import HEURISTIC_CONFIRM_FLOOR

    for ratio in (0.5, 1.0, 1.167, 1.5, 3.0, 7.583, 37.0, 1e6):
        assert signal_strength.token_overlap_strength(ratio) < HEURISTIC_CONFIRM_FLOOR


def test_verbatim_match_kinds_clear_the_confirm_floor():
    """#272 D1: the three verbatim kinds are exactly the ones admitted."""
    from ormah.engine.memory_engine import HEURISTIC_CONFIRM_FLOOR

    assert signal_strength.VERBATIM_NODE_ID >= HEURISTIC_CONFIRM_FLOOR
    assert signal_strength.VERBATIM_TITLE >= HEURISTIC_CONFIRM_FLOOR
    assert signal_strength.VERBATIM_SENTENCE >= HEURISTIC_CONFIRM_FLOOR
```

Add to `tests/test_engine/test_confirmed_use_contract.py`:

```python
@pytest.mark.parametrize("strength,should_confirm", [
    (0.80, True),    # exactly the floor — inclusive
    (0.7999, False), # just below
    (0.98, True),    # node_id
    (0.40, False),   # token_overlap floor
])
def test_heuristic_claim_respects_the_evidence_floor(engine, strength, should_confirm):
    """#272 D1/D2: the floor lives in the claim helper, not in its callers."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    with engine.db.transaction() as conn:
        claimed = engine._claim_confirmed_use(
            conn, log_id, target,
            signal=1, source="auto_heuristic", strength=strength,
        )

    assert claimed is should_confirm


def test_the_floor_does_not_gate_the_other_sources(engine):
    """#272 D2: the floor is scoped to auto_heuristic only.

    explicit is 1.00 on the ladder, so a low strength reaching this helper would
    mean the caller computed it wrong — but gating it here would silently drop a
    real confirmation instead of surfacing that bug.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    with engine.db.transaction() as conn:
        claimed = engine._claim_confirmed_use(
            conn, log_id, target, signal=1, source="explicit", strength=0.0,
        )

    assert claimed is True, "the floor must not apply to non-heuristic sources"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_signal_strength.py -k confirm_floor -v
python -m pytest tests/test_engine/test_confirmed_use_contract.py -k "evidence_floor or other_sources" -v
```

Expected: FAIL — `ImportError: cannot import name 'HEURISTIC_CONFIRM_FLOOR'` for the first pair, and
`TypeError: _claim_confirmed_use() got an unexpected keyword argument 'strength'` for the second.

- [ ] **Step 3: Add the constant and admit the source**

In `src/ormah/engine/memory_engine.py`, replace the block at `:55-57`:

```python
# Issue #220: the only feedback sources that count as confirmed use. Fail-closed —
# anything not listed here, and every negative signal, does not reinforce.
# auto_heuristic was excluded pending #218 signal calibration; #272 admits it above
# HEURISTIC_CONFIRM_FLOOR, which the ladder now makes meaningful.
_CONFIRMED_USE_SOURCES = frozenset({"explicit", "implicit", "auto_llm_judge", "auto_heuristic"})

# Issue #272: the evidence rung a heuristic hit must reach to confirm use. Defined by
# reference to the ladder, not as a literal, so the two cannot drift apart in silence.
# At IMPLICIT (0.80) this admits the three verbatim match kinds and excludes
# token_overlap by construction — that band's supremum is 0.78.
HEURISTIC_CONFIRM_FLOOR = signal_strength.IMPLICIT
```

- [ ] **Step 4: Gate the claim**

In `_claim_confirmed_use` (`:2722`), add the keyword-only parameter to the signature:

```python
    def _claim_confirmed_use(
        self,
        conn,
        whisper_log_id: int | None,
        node_id: str,
        *,
        signal: int,
        source: str,
        strength: float,
    ) -> bool:
```

Replace the guard at `:2764`:

```python
        if whisper_log_id is None or signal != 1 or source not in _CONFIRMED_USE_SOURCES:
            return False
        # Issue #272: auto_heuristic confirms only on verbatim evidence. Scoped to that
        # one source deliberately: explicit (1.00) and implicit (0.80) clear the floor
        # anyway, and the judge's band starts at 0.82 — applying it to them would add a
        # second gate on paths that do not need one, and would couple the judge's band
        # to a constant it does not own. A low strength arriving on those sources means
        # the CALLER is wrong, and dropping the claim would hide that instead of failing.
        if source == "auto_heuristic" and strength < HEURISTIC_CONFIRM_FLOOR:
            return False
```

Append to the docstring, after the "Fail-closed:" paragraph:

```
        Issue #272 admits auto_heuristic, but only above HEURISTIC_CONFIRM_FLOOR.
        submit_feedback needs no special case for it: feedback_strength maps that
        source to UNKNOWN (0.40), below the floor by construction, because a
        submit_feedback call carries no evidence of a verbatim match and so cannot
        earn a verbatim rung.
```

- [ ] **Step 5: Pass the strength from `submit_feedback`**

In `_submit_feedback_locked` (`:2812`), the strength is currently computed inline in the `signals`
INSERT at `:2895`. Hoist it above the transaction block and reuse the same value:

```python
        whisper_log_id = row["id"]
        # Computed once and used twice: the claim's floor and the signals row must
        # agree by construction, not by two call sites happening to match.
        strength = signal_strength.feedback_strength(source, signal)

        with self.db.transaction() as conn:
            became_confirmed = self._claim_confirmed_use(
                conn,
                whisper_log_id,
                resolved_node_id,
                signal=signal,
                source=source,
                strength=strength,
            )
```

Then at `:2895`, replace the inline call with the hoisted variable:

```python
                    strength,
```

- [ ] **Step 6: Fix the stale docstring on contract 9**

In `tests/test_engine/test_confirmed_use_contract.py:247`:

```python
def test_auto_heuristic_positive_does_not_confirm(engine):
    """Contract 9: submit_feedback(auto_heuristic) is below the #272 evidence floor.

    Not an exclusion by source any more — auto_heuristic IS in the allowlist since
    #272. feedback_strength maps it to UNKNOWN (0.40), under HEURISTIC_CONFIRM_FLOOR,
    because a submit_feedback call carries no evidence of a verbatim match.
    """
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
python -m pytest tests/test_signal_strength.py tests/test_engine/test_confirmed_use_contract.py -v
```

Expected: PASS, including the untouched contract 9 and contracts 10a–10f. Any failure outside the
Task 0 baseline is a real regression — do not proceed.

- [ ] **Step 8: Verify no other caller broke**

```bash
grep -rn "_claim_confirmed_use" src/ tests/
```

Every call site must now pass `strength=`. There are exactly three on this base, all verified:

| Site | Fix |
|---|---|
| `memory_engine.py:841` — `recall_node`, already `source="explicit"` | add `strength=signal_strength.EXPLICIT` |
| `memory_engine.py:2843` — `_submit_feedback_locked` | done in Step 5 |
| `session_watcher.py:603` — the LLM judge | add `strength=record["strength"]` |

The judge site already has the value to hand: `record["strength"]` is
`signal_strength.judge_strength(...)`, computed where the record is built. Passing it keeps the claim
and the `signals` row on one number rather than two that happen to agree.

Fix any site the grep finds that still omits the argument, then re-run the full suite.

```bash
python -m pytest tests/ -q > /tmp/ormah-272-run.txt 2>&1; RC=$?
tail -20 /tmp/ormah-272-run.txt
echo "pytest exit=$RC"   # 0, or only baseline IDs failed
```

- [ ] **Step 9: Lint and commit**

```bash
make lint
git add src/ormah/engine/memory_engine.py src/ormah/background/session_watcher.py \
        tests/test_engine/test_confirmed_use_contract.py tests/test_signal_strength.py
git commit -m "fix(feedback): admit auto_heuristic to confirmed use above an evidence floor (#272)

_CONFIRMED_USE_SOURCES excluded auto_heuristic pending #218 signal calibration,
which has now landed. The source is admitted, gated on HEURISTIC_CONFIRM_FLOOR
(0.80, the implicit rung): verbatim matches clear it, token_overlap cannot —
that band's supremum is 0.78.

The floor lives in _claim_confirmed_use so a future caller cannot reopen the
hole, and is scoped to auto_heuristic so it does not shadow bugs on the other
sources. submit_feedback needs no special case: feedback_strength maps
auto_heuristic to UNKNOWN, below the floor by construction."
```
