# Fork & contribution workflow (Ormah)

This repo (`Tools/ormah`) is André's **running Beta** — a *converging downstream* of
`r-spade/ormah`, **not** a diverged fork.

## Mental model (the one thing that prevents every problem)

- `local-main` = everything in `r-spade/main` **+** your local commits. You are
  **ahead-in-queue**, never diverged — `r-spade/main` is a strict ancestor of `local-main`.
- A GitHub PR diffs a **branch (head)** against a **base** — not "your fork" against
  "upstream". A branch based on `upstream/main` contains none of your 400+ commit lead, so
  that lead is **invisible** to the PR.
- Hence the **clean island**: a contribution branch cut from `upstream/main`, living in its
  own worktree. Islands keep every PR clean no matter how far ahead the Beta runs.

## Remotes — keep these names

| remote     | points to               | role                                                              |
|------------|-------------------------|-------------------------------------------------------------------|
| `origin`   | `r-spade/ormah`         | council divergence gate + PR base (council needs origin=upstream) |
| `upstream` | `r-spade/ormah`         | `gh pr create` base                                               |
| `fork`     | `AndreLFSMartins/ormah` | where you push branches / publish                                 |

The inversion (`origin` = upstream) is **intentional**: `council_pr.py` has an explicit
`origin-is-upstream` guard (divergence gate anchored on `main..origin/main`; PR base read
from the `upstream` remote). Renaming to the "standard" convention breaks council. Leave
the names as they are.

## Golden rules

1. **One clone; isolation comes from `git worktree add`.** The `Tools/ormah` working tree is
   what the **running Beta serves** (launchd `com.ormah.server.dev`), so switching its branch
   swaps the live server's code under it and crashes every whisper hook. Keep `Tools/ormah`
   parked on `local-main` and give every other branch its own worktree.
2. **Every contribution branch is a clean island** — born from `upstream/main`.
3. **Branches go to `fork`.** Only PRs flow up to `upstream` (you have no write access there,
   and you don't want it).
4. `local-main` is your **Beta = upstream + queued PRs + private notes**. It is
   **disposable / recreatable**, not a relic.
5. **Local-only material never reaches a PR.** Versioning and shipping are separate concerns,
   handled by two independent mechanisms — keep them apart:
   - **`.gitignore` decides what enters a commit.** `CLAUDE.md`, `INSTRUCTIONS.md`,
     `SESSION_LOG.md` and `.council/` are **untracked**: no git backup, and a `git clean -x`
     erases them.
   - **The `pre-push` hook decides what ships.** `FORK-WORKFLOW.md` and the
     decision history under `docs/` *are* versioned on `local-main` (history a `git clean -x`
     can erase is not history), and the hook is what keeps them out of a PR: fail-closed, it
     rejects any push whose three-dot diff against `upstream/main` carries a local-only path.
     Two ref classes are exempt, and only towards `fork` (the private Beta backup):
     `local-main` and `integration/*`.

   **The rule is derived, not written** (since 2026-09-02). Inside the **territory** —
   `docs/`, `.council/`, and any `.md`/`.html` anywhere — a path may ship **only if
   `upstream/main` already tracks it**. Nothing to register, ever: a new local-only doc is
   blocked the moment it exists, and a doc upstream adds becomes shippable on its own.

   This replaced a hand-written `PROTECTED` enumeration that was fail-closed for the paths it
   listed and fail-**open** for every path it did not — three retrofits in three weeks
   (`docs/runbooks/`, `docs/agents/`, the `CONTEXT*.md` glossaries), and 21 local-only files
   still slipping through when it was replaced, including the whole `.scratch/` tree.

   Source code is deliberately **outside** the territory: PRs are made of new source files, so
   deny-by-default there would block every legitimate contribution. Fork-only source (e.g.
   `background/pair_skip.py`) is not covered by the hook — Rule 2 is what keeps it out of a PR.

   The one case it blocks wrongly is a PR that genuinely **adds** a doc upstream. Override
   deliberately and visibly: `git push --no-verify`.

   > **The hook lives OUTSIDE the clone**, at `~/.config/ormah/githooks/pre-push`, reached via
   > `core.hooksPath`. Not in `.git/hooks/` (a re-clone erases it) and deliberately **not**
   > versioned in the repo as `.githooks/`: an island is born from `upstream/main`, which has no
   > such directory, so the hook would vanish on exactly the branches it exists to watch. Living
   > outside, one file covers every worktree and every branch.
   >
   > A re-clone still loses `.git/config`, so re-run this one line before pushing anything:
   >
   > ```bash
   > git config core.hooksPath "$HOME/.config/ormah/githooks"
   > ```

## Recipe A — contribute a change upstream

**Islands are created by `/wt-start`, never by hand.** It fetches `upstream`, cuts the branch from
the Base you name, **hydrates the gitignored agent docs** (`CLAUDE.md`, `AGENTS.md`,
`INSTRUCTIONS.md`, `.council/` memory) that a fresh worktree is otherwise born without, and opens a
VSCode window of its own. Run it from the `Tools/ormah` window:

```bash
/wt-start <issue#> --base upstream --deps    # the clean island, in a window of its own
```

`--base upstream` is not optional here: this repo declares two Bases (`upstream` = `upstream/main`,
`local` = `local-main`) plus `requireBaseChoice`, so the skill refuses to choose for you — it stops
and asks. Use `--base local` for a Beta-only fix that is not going upstream (Recipe B territory).
`--deps` runs the `deps` command from `.claude/worktree.json` — `env -u VIRTUAL_ENV -u PYTHONPATH
uv sync` — whose `env -u` prefix is the import gate below applied at install time; without the flag
the skill only prints the reminder. Island and branch carry the issue number
(`../ormah-wt-<n>-<slug>`, `<fix|feat>/<n>-<slug>`, the prefix taken from the issue's `bug` label);
the older number-less `ormah-wt-<slug>` islands are legacy and the Sweep still handles them.

Everything below runs **in the new window**, never in `Tools/ormah`:

```bash
# ... commits ...
git log --oneline upstream/main..HEAD        # gate: ONLY your own commits, nothing else
git push fork fix/<n>-<slug>                 # the branch lives on YOUR fork
/council-pr                                  # review + open PR (base r-spade:main, head fork:fix/<n>-<slug>)
```

The gate line is the proof the island is clean: anything in that log you did not write means
the branch was cut from the wrong base — rebuild the island before pushing. Once the PR lands,
prune the island with the Sweep (`/wt-start --sweep`, then confirm the candidate) instead of by
hand: it reads PR state from `gh`, so it sees squash-merges, and it warns if a hydrated file was
edited inside the island before removing anything. Branch rules in Recipe D.

> The skill creates, hydrates, opens and prunes — it never implements, commits, merges, or touches
> the branch `Tools/ormah` is parked on. And `uv sync` is how the **islands** are built locally
> only: `make install` (`pip install -e ".[dev]"`) is byte-identical to `upstream/main` and must
> not diverge.

> **`/council-pr` serves islands only.** On a fork-local branch (cut from `local-main`, spec
> carrying `Upstream: none`) `diff-base` resolves `REMOTE=upstream` and returns the merge-base
> with `upstream/main`, so the whole fork-local lead lands in the diff — 660 files on #11,
> 2026-09-03. Release the run and restart it with `review-run-start --base-sha $(git merge-base
> local-main HEAD)`: `capture-diff`, `build-review-scope --base-ref` and `peer-round
> --codex-base` all take an explicit base. Steps 2–5 do not — stop before the Merge Flow and
> merge through Recipe B.

### Import gate — run it before trusting any test number from an island

`VIRTUAL_ENV` exported in the shell (the Beta's own `Tools/ormah/.venv`) overrides the island's
interpreter: `sys.path` resolves to *that* venv **plus `Tools/ormah/src`**, so the island's tests
import `local-main`'s code. The suite goes green against the wrong tree and the number is worthless.
This has already produced a retracted "98 passed".

Strip the leaked variables and **prove which tree you imported** before any test run:

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
#   the printed path MUST contain ormah-wt-<n>-<slug>/ — if it does not, STOP: the number is not yours
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt              # NEVER pipe pytest to `tail` — the exit code becomes tail's
```

`HOME` is the third leaked variable, and `env -u` cannot strip it. `Settings.model_config`
reads `~/.config/ormah/.env` **before** the island's own `.env`, and the Beta's copy sets
providers that `upstream/main` rejects — with `ORMAH_LLM_PROVIDER=claude_cli` the island's
`conftest.py` dies at import with `ValidationError: llm_provider must be one of {'litellm',
'ollama', 'none'}` before a single test runs. Only a clean `HOME` isolates it.

All three parts are load-bearing: without the import line the run is against the wrong tree,
without the redirect + `$?` a run with failures reports exit 0, and without the clean `HOME`
the suite may not start at all.

> If `/council-pr` push is blocked by `origin-is-upstream — refusing to push to a repo you
> do not own`, that guard is council's, not git's — an explicit `git push fork fix/<slug>`
> bypasses it.

### Evidence gate — the Beta's data describes `local-main`, never `upstream/main`

The same trap as the import gate, one level up: there the wrong *code* runs, here the right
code produces numbers about the **wrong tree**.

- `local-main` = `upstream/main` **+ ~693 commits**, and **every PR you have opened but that has
  not landed yet lives in `local-main`** (queued, not merged). `gh pr view <n>` is the only
  authority on which ones those are — the Beta running a change is not evidence it shipped.
- The server, the MCP processes and the whisper hook all import from `Tools/ormah/src/ormah`
  (golden rule 1), so **`~/.local/share/ormah/memory/index.db` is a product of `local-main`**.
  Every row in it — `whisper_log`, `affinity`, `signals`, `confirmed_use_claims` — was written
  by queued code.

Before quoting any measurement or behaviour claim in an upstream issue or PR, prove the path
exists there:

```bash
git diff --stat upstream/main local-main -- src/ormah/<file>.py   # empty  = the finding is upstream's
git show upstream/main:src/ormah/<file>.py | grep -n "<symbol>"   # absent = the finding is yours only
```

State the base in the comment itself when it matters. Real case, 2026-08-19: one measurement
session produced #246 and a comment on #242 — `affinity.py` was byte-identical to `upstream/main`
(finding valid upstream), while `confirmed_use_claims` did not exist there at all (it comes from
PR #234, still open). Same database, same session, two different bases.

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

The `/wt-start` Sweep implements these rules and is the normal way to apply them; the rules below
are what it enforces, and what you follow when pruning by hand.

- Prune a **local** branch once its PR is **merged** or **closed** — confirm with
  `gh pr list --repo r-spade/ormah --author AndreLFSMartins`. A branch whose PR is still
  **open** stays: you may need it for review changes.
- Prune **local refs only**. The PR lives on the `fork` branch, so deleting that branch on
  the `fork` remote while the PR is open closes the PR.
- Use `git branch -d` (safe — refuses unmerged). Reserve `git branch -D` for squash-merged
  PRs confirmed via `gh`.
- Recover any time while the fork branch exists: `git checkout -b fix/<slug> fork/fix/<slug>`.
