### Task 5: Integer lifecycle-model version

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` — `_migrate_fsrs` and the module constants
- Create: `tests/test_engine/test_lifecycle_model_version.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `LIFECYCLE_MODEL_VERSION: int = 2`, `MemoryEngine._lifecycle_model_version() -> int`, `MemoryEngine._seed_stability_from_access_count() -> None`. `_migrate_fsrs` keeps its name and its call site in `startup()`.

Neither #220 nor #222 touches `_migrate_fsrs`, so this ports unchanged.

- [ ] **Step 1: Port the tests**

```bash
git show 4cf017f:tests/test_engine/test_lifecycle_model_version.py > tests/test_engine/test_lifecycle_model_version.py
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_lifecycle_model_version.py -v`
Expected: collection error — `ImportError: cannot import name 'LIFECYCLE_MODEL_VERSION'`.

- [ ] **Step 3: Port the implementation**

From `git show 4cf017f:src/ormah/engine/memory_engine.py`, take verbatim: the `LIFECYCLE_MODEL_VERSION = 2` module constant with its comment, and the three methods `_migrate_fsrs`, `_lifecycle_model_version` and `_seed_stability_from_access_count`. Replace `local-main`'s single `_migrate_fsrs` with all three.

Every fallback in `_lifecycle_model_version` resolves to 1 (already migrated) except the total absence of any signal, which returns 0. Skipping a seed is inert; running one overwrites `stability` and rewrites the Markdown.

**Then update one docstring elsewhere.** `_record_confirmed_use`'s lock-order note currently reads "exists in `_migrate_fsrs` and `_migrate_identity_tiers`". This task moves the seeding loop — the part that calls `file_store` inside `db.transaction()` — out of `_migrate_fsrs` and into `_seed_stability_from_access_count`, so after your change `_migrate_fsrs` no longer exhibits the pattern the sentence attributes to it. Change that name to `_seed_stability_from_access_count` and leave `_migrate_identity_tiers` alone.

Verify rather than assume: after your edit, every function the sentence names must actually open `db.transaction()` and call `file_store` **inside** it. `_ensure_self_node` was in this list once and was removed because it saves *before* opening its transaction — a reviewer caught it. Do not add names back without reading their bodies.

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_lifecycle_model_version.py -v`
Expected: 7 passed.

- [ ] **Step 5: Prove the guard is load-bearing**

Replace `return 1 if reviewed else 0` with `return 0`, run `test_a_rebuilt_index_does_not_reseed_earned_stability`, and confirm it reports `stability == 14.0` instead of `1.0`. Restore and confirm green. Report both.

- [ ] **Step 6: Run the engine suite and commit**

Run: `./.venv/bin/python -m pytest tests/test_engine/ -q` — expected: all pass. `startup()` runs `_migrate_fsrs` on every engine fixture, so a regression here fails broadly.

```bash
./.venv/bin/python -m ruff check src/ tests/
git add src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git commit -m "refactor(lifecycle): integer lifecycle-model version replaces the fsrs_migrated flag (#221)"
```

