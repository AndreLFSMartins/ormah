# Task 4: Full verification and push

> Part of `docs/superpowers/plans/2026-08-16-issue-222/`. **Read `00-overview.md` first** —
> it carries the Global Constraints and the council findings that every task must honor.

**Files:** none modified.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: branch `fix/222-retrievability-only-decay` on the `fork` remote.

- [ ] **Step 1: Run the full deterministic suite**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
ORMAH_LLM_PROVIDER=none python -m pytest -q 2>&1 | tail -30
```

Expected: failures limited to the known-red baseline (sqlite-vec `vec0 knn` errors in auto-link/conflict/worker-thread vector search, plus the setup binary-detection assumption). Any failure outside that set is a regression from this work — STOP and report it, do not push.

- [ ] **Step 2: Lint the whole tree**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 3: Confirm the diff against upstream contains only the six intended files**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
git diff --stat upstream/main...HEAD
```

Expected exactly:
- `docs/05 - Background Jobs.md`
- `docs/12 - Configuration Reference.md`
- `src/ormah/background/decay_manager.py`
- `src/ormah/background/importance_scorer.py`
- `src/ormah/config.py`
- `tests/test_background/test_decay_manager.py`
- `tests/test_background/test_importance_scorer.py`
- `tests/test_background/test_lifecycle_chain.py`
- `tests/test_config.py`

That is 9 files. If anything under `docs/superpowers/`, `docs/lifecycle/`, `.council/`, `graphify-out/`, `CLAUDE.md`, `INSTRUCTIONS.md`, or `SESSION_LOG.md` appears, STOP — a local-only overlay file leaked into the branch and the `pre-push` hook will (correctly) reject the push.

- [ ] **Step 4: Push to the fork**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
git push fork fix/222-retrievability-only-decay
```

Expected: branch created on `AndreLFSMartins/ormah`. If the `pre-push` hook rejects, do NOT use `--no-verify` — fix the leaked file first.

- [ ] **Step 5: Report, do not open the PR**

Report and stop. Opening the PR is a separate decision for André — PR #229 still declares `Closes #220-#223` while open, and the PR body/base needs his review.

The report MUST include, each with its actual output rather than a claim:

1. Branch name and the four commit SHAs.
2. Full-suite summary compared against the Task 0 baseline (name any failure outside it).
3. **The verbatim result of `tests/test_background/test_lifecycle_chain.py`** — specifically whether `test_full_chain_with_cap_armed_can_evict_a_just_demoted_node` passed as asserted or had to be adjusted, and what the boundary node's measured importance was. This is the council C1 evidence; a summary line is not enough.
4. Whether `math` had to be added to `config.py` imports (it did — confirm it landed).
