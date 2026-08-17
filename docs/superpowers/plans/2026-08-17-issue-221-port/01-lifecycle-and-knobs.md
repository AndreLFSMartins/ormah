### Task 1: `lifecycle.py` and the config knobs

**Files:**
- Create: `src/ormah/lifecycle.py`, `tests/test_lifecycle.py`, `tests/test_config_fsrs.py`
- Modify: `src/ormah/config.py:169-173` (the FSRS block) and its validators around `src/ormah/config.py:1006`

**Interfaces:**
- Consumes: nothing.
- Produces: `lifecycle.retrievability(days_since, stability, *, fallback_stability)`, `lifecycle.spacing_factor(...)`, `lifecycle.reinforced_stability(stability, days_since, *, growth_factor, growth_exponent, spacing_cap, max_stability, initial_stability)`, `lifecycle.reinforcement_due(last_review, now, cooldown_days)`; settings `fsrs_growth_factor` 0.5, `fsrs_growth_exponent` 0.5, `fsrs_spacing_cap` 2.0, `fsrs_reinforcement_cooldown_days` 1.0.

- [ ] **Step 1: Port the module and its tests verbatim**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-221-integ
git show 4cf017f:src/ormah/lifecycle.py > src/ormah/lifecycle.py
git show 4cf017f:tests/test_lifecycle.py > tests/test_lifecycle.py
git show 4cf017f:tests/test_config_fsrs.py > tests/test_config_fsrs.py
```

These three files do not exist on `local-main` and neither #220 nor #222 touches their concerns, so they port unchanged — with **one deletion**.

Delete this test from `tests/test_config_fsrs.py`. Task 2 adds it back:

```python
def test_the_removed_growth_knob_no_longer_exists(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir)
    assert not hasattr(settings, "fsrs_stability_growth")
```

**Why it moves:** `_record_confirmed_use` still reads `fsrs_stability_growth` until Task 2, so the knob cannot go yet — and shipping this task with a known-red test would break the rule that every commit on this branch passes the suite. This is the same call André made on the original #221 plan for the same knob.

Delete **only** that one test. `test_an_env_carrying_the_removed_knob_still_loads` stays: it asserts `fsrs_growth_factor == 0.5` and passes whether or not the old knob exists. The comment near the top that mentions `fsrs_stability_growth` by name also stays — it documents the NaN behavior and is not an assertion.

- [ ] **Step 2: Run the lifecycle tests — they must pass, the config ones must fail**

Run: `./.venv/bin/python -m pytest tests/test_lifecycle.py -v`
Expected: all pass — `lifecycle.py` is self-contained.

Run: `./.venv/bin/python -m pytest tests/test_config_fsrs.py -v`
Expected: failures naming the four new knobs as unknown fields. That is the RED for Step 3.

Do **not** remove `fsrs_stability_growth` in this task — `_record_confirmed_use` still reads it until Task 2, so removing it now breaks the engine at this commit.

- [ ] **Step 3: Add the four knobs**

In `src/ormah/config.py`, in the FSRS block that currently reads:

```python
    # FSRS spaced repetition decay
    fsrs_initial_stability: float = 1.0    # days; starting stability for new nodes
    fsrs_decay_threshold: float = 0.3      # R below this = decay candidate
    fsrs_stability_growth: float = 1.5     # base multiplier on access
    fsrs_max_stability: float = 365.0      # cap at 1 year
```

append after `fsrs_max_stability`:

```python

    # Bounded reinforcement (#221). See docs/12 for the curve.
    fsrs_growth_factor: float = 0.5        # g; size of one reinforcement step
    fsrs_growth_exponent: float = 0.5      # w; damps the step as stability rises
    fsrs_spacing_cap: float = 2.0          # ceiling on the R^-0.2 spacing factor
    fsrs_reinforcement_cooldown_days: float = 1.0  # min days between numeric updates
```

- [ ] **Step 4: Add the validators**

Port the validator bodies verbatim from `git show 4cf017f:src/ormah/config.py` — the `_fsrs_finite`, `_fsrs_positive` and `_fsrs_spacing_cap` validators — into `local-main`'s validator block, next to the existing `_fsrs_positive` around line 1006. Keep `fsrs_stability_growth` in `_fsrs_positive`'s field list for now; Task 2 removes it.

The non-finite check is not redundant with the positivity checks: NaN compares `False` against every `<=`, so without it a NaN knob passes validation and is serialized into YAML frontmatter.

- [ ] **Step 5: Run the config tests**

Run: `./.venv/bin/python -m pytest tests/test_config_fsrs.py -v`
Expected: **all pass.** The one test that could not pass yet was removed in Step 1.

- [ ] **Step 6: Run the full suite and commit**

Run: `./.venv/bin/python -m pytest tests/ -q`
Expected: **zero failures**, and the passed count above the 2545 baseline by the number of tests this task added. A single failure is a regression — stop and report it; there is no known-red set on this branch.

```bash
./.venv/bin/python -m ruff check src/ tests/
git add src/ormah/lifecycle.py tests/test_lifecycle.py tests/test_config_fsrs.py src/ormah/config.py
git commit -m "feat(lifecycle): centralize the lifecycle math and add the bounded-reinforcement knobs (#221)"
```

