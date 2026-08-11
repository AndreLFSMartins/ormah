# Setup: skip the Claude Code wiring the ormah plugin already provides — Design

- **Date:** 2026-07-16
- **Status:** Approved (brainstorming) — ready for implementation plan
- **Issue:** [#145](https://github.com/r-spade/ormah/issues/145)
- **Branch (to cut):** `fix/setup-skip-plugin-wiring` from `upstream/main` (see `FORK-WORKFLOW.md`)

## Problem

With the ormah Claude Code plugin installed, `ormah setup` wires the same integrations a **second**
time into the user's global config. Both wirings are live, so every human turn runs the whisper
twice — the expensive path (encode + hybrid search + cross-encoder rerank) paid twice per prompt.

`_claude_code_wire()` (`src/ormah/setup.py:2388`) performs five installs. Four of them duplicate what
the plugin already ships in `integrations/claude-plugin/`:

| `_claude_code_wire()` step | Plugin equivalent | Duplicate? |
| --- | --- | --- |
| `configure_claude_hooks` → `~/.claude/settings.json` | `hooks/hooks.json` | yes |
| `configure_claude_code_mcp` → `~/.claude.json` | `.mcp.json` | yes |
| `install_claude_agents` → `~/.claude/agents/` | `agents/ormah-maintenance.md` | yes |
| `install_claude_commands` → `~/.claude/commands/` | `commands/*.md` | yes |
| `install_claude_md` → `~/.claude/CLAUDE.md` | *(none — plugins cannot write CLAUDE.md)* | **no** |

`_install_hooks` merges carefully *within* `settings.json`, and `_is_ormah_hook`
(`src/ormah/setup.py:161`) already recognizes both the CLI form (`<...>/ormah whisper inject`) and
the plugin wrapper form (`<...>/ormah-whisper-inject`). But the plugin's hooks live in a **different
file**, so no merge inside `settings.json` can ever dedupe across the two.

### Evidence (measured 2026-07-16, André's install: plugin 0.13.3 + settings.json wiring)

Live `retrieval_events`, last 7 days, grouped by `(session_id, prompt_hash)`:

| rows per prompt | prompts |
| --- | --- |
| 1 | 198 |
| **2** | **319** |
| 3–5 | 7 |

Both wirings resolve to the same binary — the plugin shim is `exec ormah whisper inject` and
`which ormah` is `/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ormah`, the same path
`configure_claude_hooks` hardcoded. So this is pure duplicate work, not two behaviours.

Consequences: 2× the expensive retrieval path per human turn; 2 rows per prompt in
`retrieval_events`, which double-counts every per-event metric in `whisper_health`; doubled
nudge/extraction counters; `ormah whisper store` twice per compaction and per session end; two ormah
MCP servers; and `ormah-maintenance` listed twice (once as a CLI agent, once as `ormah:ormah-maintenance`).

### Why the existing guard does not hold

`--skip-client-setup` exists (`src/ormah/cli.py:790`) and `integrations/claude-plugin/SETUP.md:38` is
explicit about it. But the guard is **opt-in**, and the paths a plugin user actually hits do not pass it:

- `install.sh:196` — plain `ormah setup`.
- `install.sh:191` — `ormah setup --update` on the upgrade path. `--update` does not imply
  `--skip-client-setup`.
- `desktop/ui/src/InstallPanel.tsx:38` → `setup_agents` → `ormah setup --json` → `run_setup_json`.

So removing the entries by hand does not stick: removal is a one-off human action, re-adding is a
side effect of a command run for an unrelated reason. Verified on this install — the three hooks were
removed on 2026-07-15 and were present again on 2026-07-16 (`settings.json` mtime 18:18).

### Two findings not recorded in the issue

1. **`_claude_code_is_wired()` has a dead branch** (`src/ormah/setup.py:2297`). It iterates
   `hooks.values()` and reads `entry.get("command")`, but `entry` is the *matcher* dict
   (`keys=['hooks']`), not the hook. Confirmed by executing it against the live config: the branch
   yields `''` for every event and never matches. The `True` it returns today comes **only** from the
   `.claude.json` MCP fallback.
2. **`is_wired_fn` gates nothing.** It is read only by `list_agents()` (`src/ormah/setup.py:2542`) for
   the UI. Both `run_setup` (`src/ormah/setup.py:2684`) and `run_setup_json`
   (`src/ormah/setup.py:2585`) call `wire_fn()` unconditionally for every detected agent. Therefore the
   skip must live **inside** the wire path — fixing detection alone would change nothing.

## Approach

Guard at the top of `_claude_code_wire()`. All three offending entry points (`install.sh` plain,
`install.sh --update`, and the desktop button via `run_setup_json`) route through it, so one guard
fixes three paths.

Rejected alternatives:

- **Gate on `is_wired_fn` in the registry.** Nothing consults it before wiring (finding 2), and
  "is wired" ≠ "is provided by the plugin" — gating on it would also suppress the legitimate re-wire
  when the ormah binary path changes on upgrade.
- **New `AgentDescriptor` field (`provided_by_plugin`).** An abstraction for a single case. YAGNI.

## Design

### 1. Detection — `_claude_code_plugin_active() -> bool`

Pure read of `~/.claude/settings.json`. Returns `True` when `enabledPlugins` holds any key matching
`ormah@<marketplace>` with value `True`. Prefix match because the marketplace name varies by install.

Chosen over checking for `hooks/hooks.json` under `~/.claude/plugins/` because the file is present but
inert when the plugin is **disabled** (`"ormah@ormah": false`) or when a stale version stays cached
(this install has both 0.12.4 and 0.13.3). `enabledPlugins == true` is the authoritative signal that
the plugin's hooks are live.

**Fail-open to today's behaviour:** any `OSError`/`JSONDecodeError`/unexpected shape → `False` → wire
as today. Erring toward "wire" costs a duplicate (loud, measurable); erring toward "skip" leaves a
user with no whisper at all (silent). The default takes the loud side.

### 2. `_claude_code_wire()` — the guard

When `_claude_code_plugin_active()`:

- remove the redundant CLI wiring with the existing helpers: `_remove_claude_hooks()`,
  `_remove_mcp_from_json(Path.home() / ".claude.json")`, `_remove_claude_agents()`,
  `_remove_claude_commands()`;
- run `install_claude_md()` only — the plugin has no equivalent;
- report: *"plugin already provides hooks/MCP/agents/commands — removed redundant CLI wiring"*.

Otherwise: current behaviour, untouched.

The strip is safe by construction: `_is_ormah_hook` distinguishes the two forms, and the plugin's
hooks live in a different file that `_remove_claude_hooks` never opens — it physically cannot delete
them. Third-party hooks under the same events are preserved by the existing `_strip_ormah_hooks`
matcher rules.

This also self-heals every already-duplicated install (the decision on existing wiring): the next
`ormah setup` — for whatever reason it is run — converges to a single wiring.

### 3. `_claude_code_is_wired()` — in scope by consequence

After step 2 strips the MCP entry, `.claude.json` no longer holds `ormah`. Since the hooks branch is
dead (finding 1), the MCP fallback is the only thing returning `True` today — so `is_wired` would
start returning `False` on an install where everything works, and `list_agents()` would report
"Claude Code: not wired" in the UI. That is a regression **this change would introduce**, which is why
the function is in scope rather than adjacent cleanup:

- return `True` when `_claude_code_plugin_active()`;
- fix the matcher-structure bug so the hooks branch actually inspects `matcher["hooks"][*]["command"]`
  (reuse `_is_ormah_hook` rather than the `"ormah whisper" in cmd` substring test);
- keep the `.claude.json` MCP fallback.

### 4. Data flow

```
install.sh (plain | --update)  ─┐
desktop InstallPanel → run_setup_json ─┼─→ _detected_agents() → agent.wire_fn()
ormah setup                     ─┘                                   │
                                                                     ▼
                                                      _claude_code_wire()
                                                                     │
                                        _claude_code_plugin_active()?│
                                          ┌──────────── yes ─────────┴──── no ───────────┐
                                          ▼                                              ▼
                            strip CLI hooks/MCP/agents/commands            configure_claude_hooks
                            install_claude_md()                            configure_claude_code_mcp
                            report "plugin provides these"                 install_claude_md
                                                                           install_claude_agents
                                                                           install_claude_commands
```

### 5. Error handling

- `_claude_code_plugin_active()` never raises: it is a read wrapped in the same
  `(OSError, json.JSONDecodeError, AttributeError)` handling `_claude_code_is_wired` already uses,
  returning `False` on any failure.
- The `_remove_*` helpers are already no-ops when their target is absent or unparseable (fail-closed:
  a hand-edited config with a syntax error is left alone rather than replaced).
- A fresh install with the plugin and no CLI wiring hits the strip path and removes nothing — the
  guard is idempotent in both directions.

### 6. Testing (TDD)

In `tests/test_setup.py`, with a fake `~/.claude` via `tmp_path` + monkeypatched `Path.home`:

| Test | Asserts |
| --- | --- |
| plugin active → wire writes no hooks | `settings.json` has no ormah hook after `_claude_code_wire()` |
| plugin active → existing CLI wiring stripped | pre-seeded ormah hooks/MCP/agents/commands are gone |
| plugin active → `CLAUDE.md` still installed | the guidance block is present |
| plugin **disabled** (`false`) → wires normally | ormah hooks present (the case file-presence detection would get wrong) |
| unreadable/absent `settings.json` → wires normally | fail-open preserved |
| strip preserves third-party hooks | a co-tenant hook on `UserPromptSubmit` survives |
| `is_wired` True with plugin active and no MCP | no false "not wired" in the UI |
| **regression:** `is_wired` detects CLI hooks with no MCP entry | fails today — proves the dead branch |

The last row is written first and must fail against current `main` before the fix.

## Verification

- `python -m pytest tests/test_setup.py -v` — green.
- `make lint`.
- Live check on this install after merging to `local-main`: run `ormah setup --update`, then confirm
  `settings.json` holds no ormah hooks, the ormah MCP entry is gone from `.claude.json`, and a new
  session logs **1** row per prompt in `retrieval_events` (currently 2).

## Branch strategy

Per `FORK-WORKFLOW.md`: cut `fix/setup-skip-plugin-wiring` from `upstream/main`, push to `fork`, open
the PR with `/council-pr` (base `r-spade:main`). Then Recipe B — merge into `local-main` so the Beta
stops paying 2× immediately.

## Out of scope

- The whisper pipeline itself (issues #135–#140).
- The `~/.local/bin/ormah` vs `.venv/bin/ormah` split on this install: `.claude.json` registers the MCP
  under `~/.local/bin/ormah` while the hooks use the `.venv` path. Unrelated to the duplicate; noted
  only because step 2 removes that MCP entry, after which the plugin shim resolves `ormah` from PATH
  (verified: the same `.venv` binary).
- Any change to `--skip-client-setup`; it stays as an explicit override.

## Risks / unverified

- The `enabledPlugins` format (`"ormah@ormah": true`) is read from this install's `settings.json`; no
  official doc was consulted guaranteeing its stability. If it changes shape, the guard degrades to
  "wire as today" — the safe side, and the duplicate would resurface rather than the whisper going
  silent.
- The desktop path (`run_setup_json`) is covered by inference from reading that it calls
  `_claude_code_wire`, not by an end-to-end run of the Tauri app.
- The 7-day duplicate counts come from one install (André's Beta). The mechanism is
  install-independent, but the ratio is not a population statistic.
- Whether two concurrently registered ormah MCP servers (CLI + plugin) cause a functional problem
  beyond redundancy was not investigated — the fix removes one either way.
