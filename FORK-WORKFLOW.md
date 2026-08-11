# Fork & contribution workflow (Ormah)

**READ THIS before any development, planning, branch, or PR operation.**

This repo (`Tools/ormah`) is André's **running Beta** — a *converging downstream* of
`r-spade/ormah`, **not** a diverged fork.

## Mental model (the one thing that prevents every problem)

- `local-main` = everything in `r-spade/main` **+** your local commits. You are
  **ahead-in-queue**, never diverged — `r-spade/main` is a strict ancestor of `local-main`.
- A GitHub PR diffs a **branch (head)** against a **base** — NOT "your fork" against
  "upstream". Your fork being hundreds of commits ahead is **invisible** to a PR whose
  branch is based on `upstream/main`.
- Therefore the single load-bearing rule: **every contribution branch is cut from
  `upstream/main`, never from `local-main`.** That keeps every PR clean no matter how far
  ahead your Beta runs.

## Remotes — do NOT rename

| remote     | points to               | role                                                        |
|------------|-------------------------|-------------------------------------------------------------|
| `origin`   | `r-spade/ormah`         | council divergence gate + PR base (council needs origin=upstream) |
| `upstream` | `r-spade/ormah`         | `gh pr create` base                                         |
| `fork`     | `AndreLFSMartins/ormah` | where you push branches / publish                           |

The inversion (`origin` = upstream) is **intentional**: `council_pr.py` has an explicit
`origin-is-upstream` guard (divergence gate anchored on `main..origin/main`; PR base read
from the `upstream` remote). Renaming to the "standard" convention **breaks council**.
Leave it.

## Golden rules

1. **One clone, but isolation = worktree, not `checkout`.** Never a second clone. And never
   `git checkout <upstream-branch>` in `Tools/ormah` itself: this working tree is what the
   **running Beta serves** (launchd `com.ormah.server.dev`), so switching its branch swaps the
   live server's code under it and crashes every whisper hook. Use `git worktree add`.
2. **Contribution branches are born from `upstream/main`** — never from `local-main`.
3. **Push branches to `fork`, never to `upstream`** (no write access, and you don't want it).
4. `local-main` is your **Beta = upstream + queued PRs + private notes**. It is
   **disposable / recreatable**, not a relic.
5. Local-only overlay files (`CLAUDE.md`, `INSTRUCTIONS.md`, `SESSION_LOG.md`, `FORK-WORKFLOW.md`,
   `graphify-out/`, `.council/`, and **everything under `docs/`** — ADRs, superpowers plans/specs,
   investigation notes) are **versioned on `local-main`** and never go upstream. Since 2026-08-11 those
   are two independent facts, not one: an ignore rule was never what kept them out of a PR, it only
   decided whether they entered a commit at all. What keeps them out is
   **`.git/hooks/pre-push`** — fail-closed, it rejects any push whose three-dot diff against
   `upstream/main` touches a protected path, with one exception (`local-main` → `fork`, the private
   Beta backup). The hook lives in `.git/hooks/`, which every worktree in this clone shares, so it
   covers all 20 at once. Rule 2 is still the practice; the hook is the net for when it slips
   (a cherry-pick from `local-main`, a branch cut from the wrong base). Override, deliberately and
   visibly: `git push --no-verify`.

   > The hook is **not** versioned (nothing under `.git/` is). Re-cloning this repo loses it —
   > re-create it from this rule before pushing anything.

## Recipe A — contribute a change upstream

```bash
git fetch upstream
git worktree add -b fix/<slug> ../ormah-wt-<slug> upstream/main   # clean island on r-spade's tip
cd ../ormah-wt-<slug>                        # work HERE — Tools/ormah stays on local-main
# ... commits ...
git push fork fix/<slug>                     # the branch lives on YOUR fork
/council-pr                                  # review + open PR (base r-spade:main, head fork:fix/<slug>)
```

> **Never** `git checkout upstream/main -b fix/<slug>` inside `Tools/ormah` — that swaps the
> running Beta's code (see Golden rule 1). The worktree gives the same clean island without
> touching what the live server serves. Prune it with `git worktree remove ../ormah-wt-<slug>`
> once the PR lands (branch-pruning rules in Recipe D still apply).

The PR diff = only your commits. The 400+ commit lead is invisible because the branch
does not contain it.

> If `/council-pr` push is blocked by `origin-is-upstream — refusing to push to a repo you
> do not own`, that guard is council's, not git's — an explicit `git push fork fix/<slug>`
> bypasses it.

## Recipe B — also run the change in your Beta right now

```bash
git checkout local-main
git merge fix/<slug>     # now it lives in BOTH: the clean island (for the PR) and the running Beta
```

## Recipe C — sync down (upstream advanced / your PR landed)

```bash
git fetch upstream
git checkout local-main
git merge upstream/main
#   conflict on a file the maintainer edited on your merged PR? -> keep THEIRS (it's canonical now)
git branch -d fix/<slug-that-landed>
```

Identical commits merge cleanly on their own. Conflicts appear only where the maintainer
edited your PR — resolve by taking their version.

## Recipe D — branch hygiene (prune)

- Prune a **local** branch only when its PR is **merged** or **closed** — check with
  `gh pr list --repo r-spade/ormah --author AndreLFSMartins`.
- **Never** prune a branch whose PR is **open** (you may need it for review changes).
- **Never** delete the branch on the **`fork` remote** while its PR is open — that closes
  the PR. Only touch local refs.
- Use `git branch -d` (safe — refuses unmerged). Only for squash-merged PRs confirmed via
  `gh` use `git branch -D`.
- Deleting a local branch never touches the PR (the PR lives on the fork). Recover any time
  while the fork branch exists: `git checkout -b fix/<slug> fork/fix/<slug>`.

## Anti-patterns (these are the "merging becomes a mess" pain)

- Cutting a PR branch from `local-main` -> PR shows hundreds of commits.
- `git checkout` of a contribution branch inside `Tools/ormah` -> swaps the live Beta's code,
  crashes the whisper hooks. Use a worktree.
- A second dev clone -> doubles reconciliation.
- Renaming remotes to the "standard" convention -> breaks council.
- Deleting an open PR's branch on the `fork` remote -> closes the PR.
- `git push upstream ...` -> you never push branches to upstream; only PRs flow up.
