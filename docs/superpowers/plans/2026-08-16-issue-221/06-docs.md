# Task 6: Documentation

**Files:**
- Modify: `docs/12 - Configuration Reference.md:232-241`
- Modify: `docs/05 - Background Jobs.md:127` and `docs/05 - Background Jobs.md:152`
- Modify: `docs/01 - Data Model.md:38-39`

**Interfaces:**
- Consumes: the field names from Task 2 and the behavior from Tasks 3–5.
- Produces: nothing consumed by code.

**Scope discipline:** do not touch `docs/05` lines 129, 137, or 154 (high-importance decay protection and the importance recency term). Those belong to #222 / PR #235; editing them here creates a conflict with an open PR.

---

- [ ] **Step 1: Update the configuration reference**

In `docs/12 - Configuration Reference.md`, replace the FSRS rows (lines 236-239):

```markdown
| `fsrs_initial_stability` | `1.0` |
| `fsrs_decay_threshold` | `0.3` |
| `fsrs_stability_growth` | `1.5` |
| `fsrs_max_stability` | `365.0` |
```

with:

```markdown
| `fsrs_initial_stability` | `1.0` |
| `fsrs_decay_threshold` | `0.3` |
| `fsrs_max_stability` | `365.0` |
| `fsrs_growth_factor` | `0.5` |
| `fsrs_growth_exponent` | `0.5` |
| `fsrs_spacing_cap` | `2.0` |
| `fsrs_reinforcement_cooldown_days` | `1.0` |
```

Then add, immediately after that table:

```markdown
Reinforcement is bounded and diminishing (#221):

```text
spacing = min(R^-0.2, fsrs_spacing_cap)
S'      = min(S * (1 + fsrs_growth_factor * S^-fsrs_growth_exponent * spacing),
              fsrs_max_stability)
```

`fsrs_spacing_cap` keeps a very old memory from reaching the ceiling in a single
use, and `fsrs_growth_exponent` shrinks each step as stability rises — roughly 74
eligible updates take a node from `1.0` to the default cap.
`fsrs_reinforcement_cooldown_days` allows at most one numeric stability update per
node per window; use still advances `last_accessed` on every event.

Because of that, `last_review` can lag real use by a full cooldown window, and any
job that treats it as a recency signal will read an actively used memory as stale.
Decay and importance therefore anchor on `last_accessed`. If you add a consumer
that anchors on `last_review` instead, keep
`fsrs_reinforcement_cooldown_days < -ln(fsrs_decay_threshold) x stability`
(about `1.2` days at the default threshold and an initial stability of `1.0`), or
that consumer will treat the cooldown lag as decay.
`fsrs_stability_growth` was removed in #221: it was a base multiplier, and the new
`fsrs_growth_factor` is an additive term with different semantics.

Downgrading to a build older than #221 after upgrading is **not supported**. The
store records which lifecycle model wrote its `stability` values, and an older
binary does not know that key: it keeps writing with the unbounded formula while
leaving the version marker at the newer value, so a later upgrade trusts a marker
that no longer describes the data. Roll the binary back only together with a
backup taken before the upgrade.
```

- [ ] **Step 2: Update the background-jobs doc**

In `docs/05 - Background Jobs.md`, replace line 127:

```markdown
- `decay_manager` uses FSRS-style retrievability and importance to decide whether to demote working memories
```

with:

```markdown
- `decay_manager` uses FSRS-style retrievability and importance to decide whether to demote working memories, anchored on `last_accessed` (the last use) rather than on `last_review` (the last numeric stability update), which the reinforcement cooldown can leave a window behind
```

Then replace line 152:

```markdown
This score is not static. Recall and search hits update `access_count`, `last_accessed`, `last_review`, and `stability`, so a memory's importance changes over time as it is used, connected, or left untouched.
```

with:

```markdown
This score is not static. Recall and search hits update `access_count` and `last_accessed` on every event, while `stability` and `last_review` move at most once per `fsrs_reinforcement_cooldown_days`, so a memory's importance changes over time as it is used, connected, or left untouched.
```

- [ ] **Step 3: Update the data model doc**

In `docs/01 - Data Model.md`, replace lines 38-39:

```markdown
last_accessed: datetime     # Last recall/search hit (UTC)
last_review: datetime | None # Last FSRS review (spaced repetition)
```

with:

```markdown
last_accessed: datetime     # Last recall/search hit (UTC); the decay anchor
last_review: datetime | None # Last numeric stability update; gated by the reinforcement cooldown, so it can lag last_accessed
```

- [ ] **Step 4: Verify the removed knob is gone from the docs**

Run: `grep -rn "fsrs_stability_growth" docs/ src/ tests/`

Expected: **exactly one hit**, in `tests/test_config_fsrs.py` — the
`test_the_removed_growth_knob_no_longer_exists` assertion from Task 2, which contains the string by
construction and must survive. `docs/` and `src/` must be clean by now: the docs mention in Step 1
is prose *about* the removal, not the identifier, and Task 3 removed the last live reader.

**The old expectation here was "no output" (council round 3, I2).** An implementer chasing a clean
grep deletes the only regression test that the base-multiplier knob is gone — the gate destroying
the thing it exists to protect. If you want zero hits in `docs/` and `src/` alone, scope the grep:
`grep -rn "fsrs_stability_growth" docs/ src/`.

- [ ] **Step 5: Commit**

```bash
git add "docs/12 - Configuration Reference.md" "docs/05 - Background Jobs.md" "docs/01 - Data Model.md"
git commit -m "docs(lifecycle): bounded reinforcement knobs, cooldown, and the decay anchor (#221)"
```

- [ ] **Step 6: Final gate**

```bash
./.venv/bin/python -m pytest tests/ -v
./.venv/bin/python -m ruff check src/ tests/
git log --oneline upstream/main..HEAD
```

Expected: the full suite green, ruff clean, and exactly six commits — one per task — with nothing inherited from another branch.

If any pre-existing failure appears, check it against the known-environmental set before treating it as a regression: run the same test on a clean `upstream/main` checkout first.
