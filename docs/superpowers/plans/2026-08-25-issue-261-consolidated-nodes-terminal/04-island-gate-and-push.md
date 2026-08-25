> Plan overview: [00-overview.md](00-overview.md)

### Task 4: Island gate + push

**Files:** none.

- [ ] **Step 1: Prove the island is clean**

```bash
git log --oneline upstream/main..HEAD
git diff --stat upstream/main..HEAD
```
Expected: exactly the two commits from Tasks 2–3; only `consolidator.py` and `test_consolidator.py` in the stat.

- [ ] **Step 2: Push to the fork**

```bash
git push fork fix/261-consolidated-nodes-are-terminal
```
Expected: branch created on `AndreLFSMartins/ormah`; the pre-push hook passes (no protected paths touched). Then hand off to `/council-pr` (base `r-spade:main`) — outside this plan.
