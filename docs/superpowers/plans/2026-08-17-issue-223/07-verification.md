# Task 7: Version pin, docs-in-code, and the full verification gate

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (symbol: `MemoryEngine._lifecycle_model_version`)
- Test: `tests/test_engine/test_lifecycle_model_version.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: the branch, ready to push.

**`lifecycle_model_version` stays at `2`.** Nothing reads it on the promotion path and no existing data is rewritten — the `PRAGMA`-guarded `ALTER` is self-describing and idempotent. The version records *which reinforcement model wrote this store*, and #223 does not change the reinforcement model; it changes a creation default and adds a column. Bumping it would not help even hypothetically: it is a store-level flag, and a real store spans both eras of nodes. This is a recorded decision, not an omission — hence a test pinning it.

---

- [ ] **Step 1: Write the failing version-pin test**

Append to `tests/test_engine/test_lifecycle_model_version.py`:

```python
def test_223_does_not_bump_the_lifecycle_model_version(engine):
    """#223 changes a creation default and adds a column; it does not change the
    reinforcement model, which is what this version records."""
    from ormah.models.node import CreateNodeRequest, Tier

    node_id, _ = engine.remember(CreateNodeRequest(content="written under #223"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    engine.builder.index_single(engine.file_store.save(node))
    engine._record_confirmed_use(node_id)

    assert engine._lifecycle_model_version() == 2
```

Match the file's existing fixture name and the engine-construction idiom it already uses.

- [ ] **Step 2: Run it**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_engine/test_lifecycle_model_version.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0` — this test should pass immediately. It is a pin, not a driver: it fails only if someone later bumps the version without thinking. If it fails now, something in Tasks 1–6 changed the version and must be reverted.

- [ ] **Step 3: Record the decision in code**

In `src/ormah/engine/memory_engine.py`, append to the `_lifecycle_model_version` docstring, immediately before its closing `"""`:

```
        #223 deliberately does not bump this. The version records which
        reinforcement model wrote a store's stability values; #223 changes a
        creation default and adds a column, not the model. A bump would not
        help either way — this is a store-level flag, and a real store spans
        both eras of nodes.
```

- [ ] **Step 4: Confirm the PR carries only documentation that lives in code**

The PR's documentation is: the `superseded_by` field comment (Task 2), the `promotion_floor` docstring (Task 1), the promotion paragraph in `_record_confirmed_use` (Task 5), the derivation comment on `fsrs_initial_stability` (Task 1), the `_mark_superseded` docstring (Task 6), and this version note — plus the PR body.

```bash
git diff --name-only upstream/main...HEAD | grep -E '^(docs/|\.env\.example|\.council/)' && echo "STOP: product docs in the diff" || echo "clean: no product docs"
```

Expected: `clean: no product docs`. If anything prints, revert those paths to `upstream/main`'s content in a dedicated commit, following the `f8cb685` precedent from the #220 island.

`docs/01 - Data Model.md`, `docs/05 - Background Jobs.md` and `docs/12 - Configuration Reference.md` are **not** part of this PR: #223 adds no new configuration knob and removes none — `fsrs_initial_stability` is already documented, only its default moved. If the maintainer asks for product docs during review, it is a three-file edit added then.

- [ ] **Step 5: Confirm the island is still clean**

```bash
git log --oneline upstream/main..HEAD
```

Expected: only your own #223 commits above `upstream/main` (`90c431e` at re-base, 2026-08-23) — no dependency merges. Anything you did not write means the island was rebuilt from the wrong base.

- [ ] **Step 6: Run the full suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m pytest tests/ -q > full.txt 2>&1
echo "PYTEST_EXIT=$?" >> full.txt
tail -20 full.txt
grep -E "^FAILED" full.txt
```

Expected: the printed path contains `ormah-wt-223/`. The failure list must be **exactly** the 12 baseline names in `00-overview.md` — `tests/test_setup.py` (6), `tests/test_config.py` (2), `tests/test_background/test_consolidator.py::test_consolidation_settings_defaults`, `tests/test_background/test_hippocampus.py::test_new_file_triggers_ingestion`, and two in `tests/test_background/test_session_watcher.py`. The pass count should be `1925 + <the tests you added>`.

Any new name is a regression. Do not proceed until the list matches. Compare **names**, not counts and not files: Tasks 1 and 6 append tests to `tests/test_config.py` and `tests/test_background/test_consolidator.py`, so those two files now hold both baseline failures and new passing tests.

- [ ] **Step 7: Confirm the six env-leak failures still pass in isolation**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_background/test_consolidator.py tests/test_background/test_hippocampus.py \
    tests/test_background/test_session_watcher.py tests/test_config.py -q > clean.txt 2>&1
echo "PYTEST_EXIT=$?" >> clean.txt
tail -5 clean.txt
```

Expected: `PYTEST_EXIT=0`. This proves the four files' failures in Step 6 are still the `~/.config/ormah/.env` leak (issue #106 / PR #128) and not something #223 introduced.

- [ ] **Step 8: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git commit -m "docs(engine): record why #223 does not bump the lifecycle model version (#223)"
git show --stat HEAD
```

Expected: exactly two files.

- [ ] **Step 10: Stop before pushing**

Do **not** push or open the PR from inside this plan. Report to André:

- the full-suite numbers from Step 6, quoted from `full.txt`;
- the `git log --oneline upstream/main..HEAD` output from Step 5;
- confirmation that Step 4 printed `clean: no product docs`.

When he approves, the push is explicit and named: `git push fork feat/223-reversible-promotion`. Never a bare `git push` (the branch has no upstream on purpose) and never toward `fork/fix/220-confirmed-use`, which would corrupt PR #234.

**PRs #234 and #239 have landed and the island already sits on `upstream/main`** — no rebase step remains.

**When #223 is later cherry-picked onto `local-main`:** the promotion is incomplete there. `local-main` has `archived_at` and `forgetting_manager` (#28), which the island does not, so a promoted node keeps a stale graveyard timestamp and may remain purge-eligible while sitting in `working`. The cherry-pick must additionally clear `archived_at` on the node and in the index UPDATE. Use `git cherry-pick`, not `git merge` — and first run `git log local-main..feat/223-reversible-promotion` and `git diff --name-status local-main...feat/223-reversible-promotion | grep '^D'` to check for hygiene commits that would delete `docs/superpowers/`.
