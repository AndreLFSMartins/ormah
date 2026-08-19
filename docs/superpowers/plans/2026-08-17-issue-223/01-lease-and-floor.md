# Task 1: Seven-day lease default + `promotion_floor`

**Files:**
- Modify: `src/ormah/config.py` (symbol: `fsrs_initial_stability`)
- Modify: `src/ormah/lifecycle.py` (append after `reinforcement_due`)
- Test: `tests/test_lifecycle.py`
- Test: `tests/test_background/test_decay_manager.py`

**Interfaces:**
- Consumes: `lifecycle.retrievability(days_since, stability, *, fallback_stability=1.0)` — already exists.
- Produces: `lifecycle.promotion_floor(stability: float, initial_stability: float) -> float`, used by Task 5. `Settings.fsrs_initial_stability == 5.814`, used by Tasks 4 and 5.

**Why `max`, never a sum:** `max` is what makes "the post-update floor does not amplify the same event into a longer-than-initial lease" structural rather than incidental, and makes repeated promotions idempotent.

---

- [ ] **Step 1: Write the failing lease + floor tests**

Append to `tests/test_lifecycle.py`:

```python
def test_default_initial_stability_gives_a_seven_day_unused_lease():
    """-7/ln(0.3) = 5.8140852, rounded to 5.814 in config."""
    from ormah.config import Settings

    initial = Settings().fsrs_initial_stability
    assert initial == 5.814
    # 6.5 days unused: still retrievable. 7.5 days: a decay candidate.
    assert lifecycle.retrievability(6.5, initial) > 0.3
    assert lifecycle.retrievability(7.5, initial) < 0.3


def test_rounded_default_crosses_threshold_just_under_seven_days():
    """5.814 x 1.2039728 = 6.99990 days, ~8.8 s before the 7-day mark.

    Pinned deliberately: an assertion of `> 0.3` at t = 7.0 would FAIL.
    """
    assert lifecycle.retrievability(7.0, 5.814) < 0.3
    assert lifecycle.retrievability(6.99, 5.814) > 0.3


def test_promotion_floor_never_reduces_stability():
    """Equality at 50.0, not `>= 5.814` — with `>=` a min/max swap passes."""
    assert lifecycle.promotion_floor(50.0, 5.814) == 50.0


def test_promotion_floor_lifts_a_below_floor_stability():
    assert lifecycle.promotion_floor(2.0, 5.814) == 5.814


def test_promotion_floor_is_idempotent():
    once = lifecycle.promotion_floor(1.0, 5.814)
    assert lifecycle.promotion_floor(once, 5.814) == once
```

If `tests/test_lifecycle.py` does not already do so, add `from ormah import lifecycle` at the top.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_lifecycle.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: the printed path contains `ormah-wt-223/`. Failures: `AttributeError: module 'ormah.lifecycle' has no attribute 'promotion_floor'` on three tests, and `assert 1.0 == 5.814` on the lease test.

- [ ] **Step 3: Change the config default**

In `src/ormah/config.py`, replace the `fsrs_initial_stability` line:

```python
    fsrs_initial_stability: float = 5.814   # days; -7 / ln(0.3) — a seven-day unused lease
```

It stays a directly configured knob rather than one derived from `fsrs_decay_threshold`: the acceptance criterion asserts the lease at *the default* threshold and calls the value *the configured* initial stability. The existing `_fsrs_finite` and `_fsrs_positive` validators already cover it — do not add a validator.

- [ ] **Step 4: Add the pure function**

Append to `src/ormah/lifecycle.py`:

```python
def promotion_floor(stability: float, initial_stability: float) -> float:
    """``max(S, initial)`` — the lease a promoted node restarts from.

    ``max``, never a sum: a node promoted twice in one cooldown window must end
    at one initial lease, not two, and a node whose stability already exceeds the
    initial value must not be pulled down to it.
    """
    return max(stability, initial_stability)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_lifecycle.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`, all tests pass.

- [ ] **Step 6: Write the decay-cadence test**

The formula test above proves the math; this one proves the real job honours it.

`tests/test_background/test_decay_manager.py` has no fixture of its own — it uses the shared
`engine` fixture from `tests/conftest.py`. Its two helpers, `_make_stale(engine, node_id, days=30)`
and `_make_decayable(engine, node_id)`, write straight to SQLite with `UPDATE nodes`; neither takes
a fractional number of days, so this test sets the two fields itself through the file store.

**Set `stability` explicitly rather than asserting `remember()` produced it.** Task 4 is what wires
`remember()` to the knob, and Task 4 runs *after* this task — an assertion on `remember()`'s output
here would fail for the right reason at the wrong time. Task 4 owns that assertion
(`test_remember_uses_the_configured_initial_stability`).

Append to `tests/test_background/test_decay_manager.py`:

```python
def test_a_seven_day_lease_survives_six_and_a_half_days_and_decays_after_seven(engine):
    """Drives run_decay, not the formula: the seven-day lease must reach the job."""
    now = datetime.now(timezone.utc)
    node_id, _ = engine.remember(CreateNodeRequest(content="a fresh working memory"))

    def _age_it(days: float) -> None:
        node = engine.file_store.load(node_id)
        node.stability = 5.814            # Task 4 makes remember() do this; pinned here on purpose
        node.importance = 0.0             # under decay_importance_threshold (0.5), gate is `>=`
        node.last_accessed = now - timedelta(days=days)
        engine.builder.index_single(engine.file_store.save(node))

    _age_it(6.5)
    run_decay(engine)
    assert _get_tier(engine, node_id) == Tier.working.value

    _age_it(7.5)
    run_decay(engine)
    assert _get_tier(engine, node_id) == Tier.archival.value
```

`datetime`, `timedelta`, `timezone`, `run_decay`, `CreateNodeRequest` and `Tier` are already imported
at the top of that file — do not re-import them inside the test. `_get_tier` is the file's own helper
and returns the raw string from the `nodes` row, which is why the assertions compare against
`Tier.working.value`, not the enum. `FileStore.save()` returns the written `Path`, which is what
`index_single` wants — `_path_for` is private, never call it.

- [ ] **Step 7: Run it and verify it passes**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_background/test_decay_manager.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`, with no dependency on Task 4 — this test sets `stability` itself.

- [ ] **Step 8: Check the config suite did not regress**

The default change is visible to any test that pins settings defaults.

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_config.py tests/test_lifecycle.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`. If a test asserts `fsrs_initial_stability == 1.0`, update it to `5.814` — that is the intended change, and record it in the commit message.

- [ ] **Step 9: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 10: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
git add src/ormah/config.py src/ormah/lifecycle.py tests/test_lifecycle.py \
        tests/test_background/test_decay_manager.py tests/test_config.py
git commit -m "feat(lifecycle): seven-day initial lease and the promotion floor (#223)"
git show --stat HEAD
```

Expected: `git show --stat HEAD` lists exactly the files you added — no `docs/`, no `.env.example`.
