# Ingest / claude_cli — loose ends left by removing Ollama

> **Handoff doc.** Self-contained so a fresh conversation can resume cold. Written 2026-07-02.
> **Goal:** finish the migration of ormah's server-side extraction from local Ollama/gemma to
> headless `claude -p` (subscription, no paid API). Extraction itself already works; a few
> spots still assume the old `llm_provider`/Ollama and need fixing on the upstream branch.

---

## TL;DR — what to do next

> **Scope locked 2026-07-02 (André):** do **all four** loose ends **+** wire the maintenance seam
> to `claude_cli` (option A), on the **existing draft-PR branch** `feat/ingest-claude-cli-extraction`
> (no new branch). See "Decisions locked" at the bottom.

1. Create a **git worktree** of `feat/ingest-claude-cli-extraction` (do NOT `checkout` in the
   main tree — the dev server runs from `local-main` and its launchd wrapper refuses other branches).
   Same draft branch behind PR #79 — fixes go here.
2. Fix **#1 (bin-path robustness)** and **#2 (backfill gate)** via TDD (details below).
3. Do **#3 (is_free label)** and **#4 (setup wizard supports claude_cli)** — they are one setup.py pass.
4. **Maintenance (option A):** set `ORMAH_LLM_PROVIDER=claude_cli` so the 4 semantic jobs + judge
   run again. Zero code — the `claude_cli` adapter already serves the maintenance `llm_generate`
   seam ([llm/__init__.py:42](../../../src/ormah/background/llm/__init__.py#L42)). Bounded: intervals
   pinned to 999999 → only runs in the sleep cycle / button.
5. Merge `feat/ingest` → `local-main` (as before), restart the dev server, verify.
6. **Do NOT push.** PR #79 / `fork/feat` stays at `1811b2f` until André says otherwise.

---

## Current system state (verified 2026-07-02)

- **Dev server:** launchd label `com.ormah.server.dev`, `KeepAlive=true`, wrapper
  `~/.config/ormah/ormah-server-dev` → runs `.venv/bin/ormah server start` from the
  **`local-main`** working tree (wrapper refuses any other branch). Logs: `/tmp/ormah-dev.{out,err}`
  and `~/.local/share/ormah/logs/ormah.log`. Restart: `launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev`
  (preserves TCC/Full-Disk-Access — do not launch manually from a terminal).
- **Extraction is LIVE and verified** via `claude -p` (Haiku): a `dry_run` POST to
  `/ingest/conversation` extracted 1 correct memory in ~3.7s, real `claude -p` subprocess confirmed,
  zero error. Byte-cursor advances; no re-extraction loop; no gemma burning GPU.
- **Branches:**
  - `local-main` @ `2888016` — Beta integration branch (runs the dev server; **never** goes upstream).
    Already contains the merged claude_cli ingest feature + all other Beta work (#22/#26/#28/#32/#52/#59/#70…).
  - `feat/ingest-claude-cli-extraction` @ `3448f26` — **upstream-bound** branch (PR #79). Clean off origin/main.
    **All fixes below go here.**
  - `fork/feat` (PR #79) @ `1811b2f` — unchanged; commits `a39e7b1`+`3448f26` are local-only. **No pushes done.**
  - `feat/ingest-v1-backup` — old v1 lineage; holds 6 council fixes. Most are inapplicable to v2
    (they patch v1-only mechanisms). The ONLY still-relevant one is `e87cc1a` = loose-end #2 below.
- **`.env`** (`~/.config/ormah/.env`) — freshly minimized to 17 deliberate settings. Key values:
  `ORMAH_INGEST_LLM_PROVIDER=claude_cli`, `ORMAH_INGEST_LLM_MODEL=claude-haiku-4-5-20251001`,
  `ORMAH_CLAUDE_CLI_BIN=/Users/andre/.local/bin/claude`, `ORMAH_LLM_PROVIDER=none`,
  `ORMAH_CLAUDE_MAINTENANCE_ENABLED=true`, `ORMAH_FEEDBACK_LLM_JUDGE_ENABLED=true`,
  `ORMAH_DELETION_ENABLED=true`, embedding via Ollama `bge-m3`/dim 1024, `session_watcher` on,
  4 maintenance intervals pinned to `999999` (no continuous scheduling).

---

## The two seams (mental model — do not confuse)

| Concern | Function | Setting | State |
|---|---|---|---|
| **Extraction (ingest)** | `_extract_memories_llm` → `ingest_llm_generate` | `ingest_llm_provider` = `claude_cli` | ✅ live (Haiku) |
| Maintenance jobs + feedback judge | `llm_generate` | `llm_provider` = `none` | ❌ dead (see "separate decision") |

All 5 ingest entry points route to `_extract_memories_llm`: `/ingest/conversation`
(routes_ingest, used by the whisper-store hook), `session_watcher.py:823`, `hippocampus.py:116`,
`routes_ingest` dry_run, and `setup.py` backfill (POSTs to `/ingest/conversation`). No extraction
path is left on Ollama. **Confirmed by audit.**

---

## The loose ends (what "half-done from removing Ollama" means)

### #1 — bin-path robustness  [HIGH]
**File:** `src/ormah/background/llm/claude_cli_adapter.py:101`
```python
self.bin_path = bin_path or shutil.which("claude") or "claude"
```
Under launchd the PATH is minimal (`.venv/bin:/usr/local/bin:/usr/bin:/bin`) and does **not**
contain `claude` (it lives at `~/.local/bin/claude` → `~/.local/share/claude/versions/2.1.156`,
or `/opt/homebrew/bin/claude`). So `shutil.which` returns None → falls back to the literal
`"claude"` → `FileNotFoundError` → `status:error` → cursor never advances → **silent zero extraction**.
Today only the machine-specific `ORMAH_CLAUDE_CLI_BIN` in `.env` papers over it.

**Fix:** when `bin_path` is unset and `which("claude")` fails, search common install locations
(`~/.local/bin/claude`, `~/.local/share/claude/versions/*` current, `/opt/homebrew/bin/claude`,
`$HOME/.claude/local/claude`) before giving up; if still not found, log a clear actionable error
(“set ORMAH_CLAUDE_CLI_BIN”) rather than a bare FileNotFoundError. Keep `bin_path` (explicit
override) as highest priority.

**TDD:**
- Test: with `bin_path=None` and a monkeypatched `shutil.which` returning None + a fake claude at a
  known common location, the adapter resolves to that absolute path (not literal `"claude"`).
- Test: explicit `bin_path=/x/claude` still wins over auto-detection.
- Test: nothing found → clear error/None, not an unhandled exception.

### #2 — backfill gate honors ingest_llm_provider  [HIGH]  (= v1 commit `e87cc1a`)
**File:** `src/ormah/setup.py:1212-1213`
```python
llm_provider = env.get("ORMAH_LLM_PROVIDER", "none")
if llm_provider == "none":
    return
```
With `llm_provider=none` + `ingest_llm_provider=claude_cli` (André's exact config), backfill
**silently returns early** even though the server extracts fine. Bootstrap is broken.

**Fix:** gate on the *effective* ingest provider (mirror `_resolve_ingest_provider`):
```python
llm_provider = env.get("ORMAH_LLM_PROVIDER", "none")
ingest_provider = env.get("ORMAH_INGEST_LLM_PROVIDER", "") or llm_provider
if ingest_provider == "none":
    return
```
(Do **not** copy the v1 `_is_extractor_transcript` import from `e87cc1a` — that construct does not
exist in v2. Only port the gate lines.)

**TDD:**
- Test: `backfill_transcripts` does NOT early-return when `ORMAH_LLM_PROVIDER=none` and
  `ORMAH_INGEST_LLM_PROVIDER=claude_cli`.
- Test: still early-returns when both are effectively `none`.

### #3 — `is_free` cost label  [IN SCOPE — folds into #4]
**File:** `src/ormah/setup.py:1281` — `is_free = llm_provider == "ollama"`. With claude_cli the
“free” labelling is wrong (subscription is neither metered-API nor local-free, but it IS zero
API cost). Since #4 is a broader setup pass, do it here.

**Fix:** `is_free = llm_provider in ("ollama", "claude_cli")`. Then backfill prints the "no API cost"
path (setup.py:1282-1284) for claude_cli instead of running `_estimate_cost` on a subscription model.

**TDD:** with `llm_provider=claude_cli`, backfill cost display takes the free branch (no `_estimate_cost`
call / no "$" cost line).

### #4 — setup wizard supports claude_cli  [IN SCOPE — upstream completeness]
**Confirmed by reading `configure_llm` (setup.py:1063):** it iterates `LLM_PROVIDERS`
(setup.py:78 — litellm×4, ollama, none; **no claude_cli**) and persists **only** the maintenance
seam via `_enable_llm` (`ORMAH_LLM_PROVIDER/MODEL`, setup.py:1045). It never touches the ingest
seam. So a fresh `ormah setup` cannot enable claude extraction without hand-editing `.env`.

**Fix (three edits, all setup.py):**
1. Add a `claude_cli` entry to `LLM_PROVIDERS` (setup.py:78) — no api_key_var, like ollama:
   `("Claude subscription (headless CLI — no API key)", "claude_cli", None, "claude-haiku-4-5-20251001")`.
2. In `configure_llm`, add a `claude_cli` branch (the current `else` at 1141-1145 handles keyless
   ollama). It must write **both seams**: ingest (`ORMAH_INGEST_LLM_PROVIDER=claude_cli`,
   `ORMAH_INGEST_LLM_MODEL`, and an absolute `ORMAH_CLAUDE_CLI_BIN` via #1's resolver) **and**,
   per decision A, maintenance (`_enable_llm(env, "claude_cli", model)`). Add a small
   `_enable_claude_cli(env, model, bin_path)` helper rather than overloading `_enable_llm`.
3. Reuse #1's `resolve_claude_bin()` to fill `ORMAH_CLAUDE_CLI_BIN` (absolute path required under
   launchd — this is exactly loose-end #1; do NOT duplicate the search logic).

**TDD:**
- Test: selecting claude_cli in `configure_llm` (monkeypatched `input`) writes
  `ORMAH_INGEST_LLM_PROVIDER=claude_cli` + model **and** `ORMAH_LLM_PROVIDER=claude_cli` (decision A),
  plus an absolute `ORMAH_CLAUDE_CLI_BIN`.
- Test: `LLM_PROVIDERS` contains a claude_cli entry with `api_key_var=None`.

**NOT loose ends (audited, leave alone):** the 4 maintenance jobs’ `if not llm_enabled` gates
(`auto_linker:315`, `conflict_detector:213`, `consolidator:181`, `duplicate_merger:249`) and the
judge gate (`session_watcher:238`) are maintenance — correctly on `llm_provider`. And
`setup.py:969` (`ORMAH_LLM_PROVIDER != none`) is **API-key import**, irrelevant to subscription.

---

## Separate decision (NOT part of ingest loose ends) — maintenance / sleep cycle

When Ollama was removed, the 4 maintenance jobs **and** the feedback judge were orphaned on
`llm_generate`/`llm_provider=none` → dead. Consequences:
- The **sleep-cycle button / nightly 01:30 cron** (`/admin/tasks/run-all`, LaunchAgent
  `me.ormah.sleepcycle`) runs the 6 mechanical jobs + **forgetting (deletes memories, deletion=true)**
  but the 4 semantic jobs (dedup/conflict/auto-link/consolidate) **silently no-op** and report “ok”.
- The **judge** is now flag-ON but inert (needs a live `llm_provider`).
- Agent-driven maintenance (`claude_maintenance_enabled=true` → `maintenance_due` whisper signal →
  `ormah-maintenance` subagent → `run_maintenance`) **does** work and ran 2026-07-02 12:47; it does
  NOT depend on `llm_provider`.

**DECIDED 2026-07-02 (André): option A, now, in this same batch.** Set
`ORMAH_LLM_PROVIDER=claude_cli` in `.env`. Verified zero-code: the maintenance seam
`llm_generate` → `_get_or_create_adapter` → `get_adapter(settings)` resolves `settings.llm_provider`,
and `get_adapter` already builds `ClaudeCliAdapter` for `"claude_cli"`
([llm/__init__.py:42-50](../../../src/ormah/background/llm/__init__.py#L42-L50)). So the 4 semantic
jobs (`auto_linker`/`conflict_detector`/`consolidator`/`duplicate_merger`) + the feedback judge
run again through the same adapter, inheriting the #1 bin-path fix. Model stays independently
tunable via `ORMAH_LLM_MODEL` (default keeps Haiku). Bounded: the 4 intervals are pinned to 999999,
so this only fires in the sleep-cycle / button path, not continuously.

Rejected: (B) a dedicated `maintenance_llm_provider` seam — pointless code; ingest already has its
own seam+model and maintenance can differ by model alone. (C) agent-only — leaves the button/cron
path silently no-op'ing the semantic jobs, which is the bug André wants fixed.

**Deletion (still open, low urgency):** nightly forgetting deletes with `deletion=true`. Leave ON —
it is effectively a no-op today (store <90d young, per the forgetting-staleness audit). Revisit if
the store ages past the decay window; not a blocker for this batch.

**Verify (A):** after setting the env + restart, trigger the sleep cycle (`/admin/tasks/run-all` or
the button) and confirm the 4 semantic jobs report real work (edges/merges/consolidations > 0), not
the old silent "ok" no-op. A single `claude -p` spawn per candidate pair — watch subprocess count on
a large store; if it ever hurts, the agent-driven `run_maintenance` path remains the primary and this
inline path can go back to `none`.

---

## Logistics

- **Worktree:** `git worktree add ../ormah-ingest feat/ingest-claude-cli-extraction` (or use the
  Agent `isolation: worktree`). Leaves the `local-main` tree (serving the live server) untouched.
- **Run tests:** `.venv/bin/python -m pytest tests/ -v` (fast run excludes `integration`).
  Known-noisy: ~8–15 env-leak/fastembed failures are machine-state, not regressions. The
  `@pytest.mark.integration` claude tests need the real CLI + login.
- **After fixes:** merge `feat/ingest` → `local-main` (`git merge --no-ff`), then
  `launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev`, then re-run the `dry_run` probe to
  confirm extraction still works.
- **Verify each fix** with a real check, not just green tests: for #1, run the adapter under a
  stripped PATH and confirm it still finds claude; for #2, run backfill dry logic with the two-provider
  config and confirm it does not early-return.

## Gotchas (bit us this session)
- **.env format:** the launchd wrapper does `export "$line"` → **NO inline `#` comments after a
  value** (they become part of the value → pydantic ValidationError → launchd crash-loop). Comments
  only on their own line. Also `ormah setup` rewrites `.env` lossily (drops comments/order).
- **`ORMAH_CLAUDE_CLI_BIN` must be absolute** under launchd (this is exactly loose-end #1).
- **curl is blocked** in the ormah context — use Python `urllib`.
- **graphify convention:** run `graphify query "<q>"` before grepping; `graphify update .` after edits.
- **No `--no-verify`, no force-push, no push at all** until André signs off.

## Decisions locked (2026-07-02, André)
1. **Scope:** all four loose ends (#1 + #2 + #3 + #4). #3 folds into the #4 setup.py pass.
2. **Branch/isolation:** work on the **existing draft-PR branch** `feat/ingest-claude-cli-extraction`
   (no new branch) via a git worktree, so the `local-main` dev server stays untouched.
3. **Maintenance provider:** **now, option A** — `ORMAH_LLM_PROVIDER=claude_cli` (zero code; see the
   "Separate decision" section above, now resolved). Nightly deletion stays ON (no-op today).

## Suggested execution order (TDD each)
1. **#1** bin-path resolver → expose reusable `resolve_claude_bin()` (adapter + wizard both use it).
2. **#2** backfill gate on effective ingest provider.
3. **#4 + #3** one setup.py pass: `LLM_PROVIDERS` entry, `configure_llm` claude_cli branch writing
   both seams, `is_free` includes claude_cli.
4. **Maintenance (A):** `.env` `ORMAH_LLM_PROVIDER=claude_cli`; no code. Verify via sleep-cycle probe.
5. Merge `feat/ingest` → `local-main`, `launchctl kickstart -k …`, re-run the dry_run + sleep-cycle probes.
