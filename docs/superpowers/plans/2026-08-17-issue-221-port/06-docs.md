### Task 6: Documentation

**Files:**
- Modify: `docs/12 - Configuration Reference.md`, `docs/05 - Background Jobs.md`, `docs/01 - Data Model.md`

**Interfaces:** consumes the field names from Task 1 and the behavior from Tasks 2-5; produces nothing consumed by code.

- [ ] **Step 1: Port the docs changes, reconciled with #222**

```bash
git show 4cf017f:"docs/12 - Configuration Reference.md" > /tmp/t6-docs12.md
git show 4cf017f:"docs/05 - Background Jobs.md" > /tmp/t6-docs05.md
git show 4cf017f:"docs/01 - Data Model.md" > /tmp/t6-docs01.md
```

Diff each against the working copy and apply only #221's additions. **Do not overwrite wholesale** — `local-main` carries #222's documentation of the importance half-life, which `4cf017f` never had and which must survive.

Two sentences from `4cf017f`'s `docs/05` describe the importance scorer's recency and are **wrong here**, because #222 decoupled importance from FSRS. Where the ported text says importance anchors on FSRS retrievability, keep `local-main`'s #222 wording and add only that the anchor is `last_accessed`.

The `docs/12` prose block ports in full, including the paragraph stating that upgrading does not rescale existing `stability`, the `fsrs_stability_growth` removal note, the `fsrs_reinforcement_cooldown_days = 0` note, and the unsupported-downgrade paragraph. Verify the `~440` figure yourself (`-ln(0.3) × 365`) and use what you compute.

- [ ] **Step 2: Add what only this port knows**

Neither #220 nor #221 alone documents their composition. Add one paragraph to `docs/12`, after the cooldown explanation:

```markdown
Reinforcement fires only on *confirmed use* (#220) — an explicit recall or a submitted
positive signal, each taken at most once per whisper event. The per-day cooldown applies on
top of that latch, so the 74 updates above are 74 separate days on which a memory was
deliberately used, not 74 recalls. Surfacing a memory in a whisper or a search result does
not reinforce it and never did after #220.
```

- [ ] **Step 3: Verify the removed knob is gone from the docs**

```bash
grep -rn "fsrs_stability_growth" "docs/12 - Configuration Reference.md" src/ tests/
```

**Scope the grep to `docs/12`, not all of `docs/`.** Unlike the `fix/221-bounded-reinforcement` worktree, this branch is cut from `local-main`, which versions `docs/superpowers/` and `docs/lifecycle/`. A sweep over `docs/` therefore also hits eight planning and spec documents — including this plan — that legitimately name the removed knob in prose. The gate said "exactly three" over all of `docs/` and was wrong for that reason; scoped as above, three is correct.

Expected: **exactly three hits, and all three must survive** — the prose sentence in `docs/12` explaining the removal (naming the removed identifier is the point; it is what someone upgrading greps for), plus two in `tests/test_config_fsrs.py` (a comment and the removal assertion). For a zero-hit check on live code, scope it: `grep -rn "fsrs_stability_growth" src/`. If your count disagrees with this list, **stop and report** — do not delete a hit to reach the number.

- [ ] **Step 4: Commit**

```bash
git add "docs/12 - Configuration Reference.md" "docs/05 - Background Jobs.md" "docs/01 - Data Model.md"
git commit -m "docs(lifecycle): bounded reinforcement, the cooldown, and its composition with confirmed use (#221)"
```

