> Overview: [00-overview.md](00-overview.md). Read it first; it carries the header, Global Constraints, and task order.

### Task 5: Full suite and PR

**Files:** none modified.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all PASS. Cite the summary line in the PR body.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin fix/236-restore-fsrs-migration
gh pr create --base main --title "fix(lifecycle): a restore onto an existing index re-evaluates the FSRS migration (#236)" --body "$(cat <<'BODY'
Closes #236.

`full_rebuild` now clears `fsrs_migrated` and `lifecycle_model_version` alongside `auto_link_watermark`, and `MemoryEngine.rebuild_index` (serialized) calls `_migrate_fsrs()` after re-embedding, so a restore onto an existing index re-evaluates the migration instead of trusting a marker written for the previous graph.

The seed is now decided per node, not per store: it touches only nodes matching `last_review IS NULL AND stability = 1.0 AND access_count > 0`. That keeps it from overwriting a stability some other writer produced — including externally authored Markdown, which is the only way a pre-FSRS node can exist — and lets a mixed graph seed its pre-FSRS nodes while leaving migrated ones alone. `_migrate_fsrs` also withholds the version marker while `len(list_paths()) != COUNT(*) FROM nodes`, so a rebuild that could not index every file never records a completed migration.

Known limit, stated rather than glossed: `parse_node` maps an absent `stability` and an explicit `stability: 1.0` to the same value, so a deliberately authored `1.0` with a usage history is indistinguishable from an unseeded node and will be seeded. That case is exactly what #236 requires the seed to accept.

Tests: unit (per-node eligibility, mixed store, no usage history, interrupted seed, incomplete graph, restore seeds / keeps earned stability / admin rebuild), builder (keys cleared), end-to-end via `BackupService.restore` + `startup()` for both the happy path and the unindexable-file path. Full suite: <paste summary line>.

Reviewed by the Dev Council across three rounds; every accepted finding is carried in the spec with its origin.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

---

