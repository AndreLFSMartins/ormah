# Task 4 — Re-rebase `feat/87-pair-batching` and open its PR

**Where:** `/Users/andre/Documents/GitHub/ormah-dev`. Branch already rebased+green on 2026-07-09 over `bf5917d`; upstream has since added 2 test-isolation commits → trivial re-rebase expected.

- [ ] **Step 1: Checkout + backup tag**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git checkout feat/87-pair-batching )
git -C /Users/andre/Documents/GitHub/ormah-dev tag backup/pr87-pre-open-20260710
git -C /Users/andre/Documents/GitHub/ormah-dev rev-parse --short HEAD
```

Expected: HEAD = `8a2f474`.

- [ ] **Step 2: Rebase onto current upstream/main**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git rebase upstream/main )
```

Expected: clean or near-clean (the 2 new upstream commits touch setup/uninstall tests only).

- [ ] **Step 3: Suite gate (I4 — automated diff vs baseline)**

```bash
P=/Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync
( cd /Users/andre/Documents/GitHub/ormah-dev && .venv/bin/pip install -q -e ".[dev]" \
  && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
     .venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | grep -E '^FAILED' | sort > /tmp/pr87-fail.txt )
comm -23 /tmp/pr87-fail.txt <(sort $P/baseline-failures.txt) > /tmp/pr87-new-fail.txt
if [ -s /tmp/pr87-new-fail.txt ]; then echo "NEW FAILURES — DO NOT PUSH:"; cat /tmp/pr87-new-fail.txt; else echo "GATE PASS"; fi
```

Gate: `/tmp/pr87-new-fail.txt` empty (FAILED ⊆ `baseline-failures.txt`). Any line → stop, do NOT run Step 4.

- [ ] **Step 4: Push to r-spade (same hosting as sibling #92)**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git push upstream feat/87-pair-batching )
```

Expected: accepted (André pushed #92's branch to r-spade on 07-09, so permission exists). If rejected → push to `origin` (fork) instead and use `--head AndreLFSMartins:feat/87-pair-batching` in Step 5.

- [ ] **Step 5: Open the PR**

```bash
gh pr create --repo r-spade/ormah --base main --head feat/87-pair-batching \
  --title "feat(background): batch K pairs per LLM call in dedup/conflict maintenance (#87)" \
  --body "Closes #87.

Batches maintenance LLM work: instead of 1 pair per \`claude -p\` spawn (~6–23s each, serialized), each call now processes K pairs (per-provider knob: claude_cli=10, ollama=1 — same code path, no fork).

- Rebased onto current main; suite green locally (same environmental failures as clean main).
- Conflict-resolution notes vs #88 vec-reuse / #90 exceptions: see PR #92 discussion (sibling of this series).
- Follow-up planned (#87 thread): cap counted in PAIRS (500–1000) instead of nodes."
```

Adjust body wording against `/Users/andre/Documents/GitHub/ormah-dev/proposal-2026-07-09-sleep-cycle-performance.md` if it differs — the proposal doc is the source of truth for K values.

- [ ] **Step 6: Record PR number + tip in `delta-manifest.md` under `## new-tips`**

```bash
gh pr list --repo r-spade/ormah --head feat/87-pair-batching --json number,url --jq '.[0]'
git -C /Users/andre/Documents/GitHub/ormah-dev rev-parse --short feat/87-pair-batching
```
