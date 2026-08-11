# Setup: stop clobbering pre-existing user config

Design spec — fixes [r-spade/ormah#70](https://github.com/r-spade/ormah/issues/70).

## Problem

`ormah setup` overwrites user-owned content in external config files instead of
surgically merging only Ormah's own entries. Three lossy spots, two root causes:

1. **Claude hooks** — `configure_claude_hooks` → `_merge_json_file("~/.claude/settings.json", {"hooks": ...})`
   (`src/ormah/setup.py:196`). Events: `UserPromptSubmit`, `PreCompact`, `SessionEnd`.
2. **Codex hooks** — `configure_codex_hooks` → `_merge_json_file("~/.codex/hooks.json", {"hooks": ...})`
   (`src/ormah/setup.py:305`). Events: `UserPromptSubmit`, `Stop`.
3. **`.env`** — `_read_env_file`/`_write_env_file` (`src/ormah/setup.py:755`, `:769`) round-trip
   through a `dict`, dropping every comment, blank line, and the original ordering on each write.

**Root cause (1 + 2):** `_merge_json_file` (`src/ormah/setup.py:133-152`) merges one level deep.
For `mcpServers` (keyed by server name) that is correct — only the `ormah` key is touched.
For `hooks`, each event maps to a *list* of hook groups, and `dict.update` replaces the whole
list, discarding any co-tenant hook registered under the same event.

**Root cause (3):** the `.env` writer rebuilds the file from a `dict` that never contained the
non-`KEY=VALUE` lines, so it cannot preserve them.

The **uninstall** paths (`src/ormah/setup.py:700-726`, `:1255-1285`) already do the right thing:
per-matcher filtering via `_is_ormah_hook` that preserves co-tenants. The install paths are simply
asymmetric with the removal logic that already exists in the same file.

## Goals

- Installing Ormah hooks preserves any third-party hook under the same event name.
- Re-running `ormah setup` is idempotent — it never duplicates Ormah's own hook entries.
- Writing the `.env` preserves comments, blank lines, and ordering; only Ormah-owned `KEY=` lines
  change, and keys removed by a caller are dropped.

## Non-goals

- No change to MCP registration (Claude Code/Desktop/Codex) — already surgical (keyed by name).
- No change to the Codex TOML writers or the CLAUDE.md sentinel-block writer — already surgical.
- No new declared dependency; do not migrate to `python-dotenv` (would force changing 8 callers).
- No change to the uninstall paths.

## Design

### 1. `_is_ormah_hook` — single source of truth (existing)

Already defined and used by the uninstall paths. Reuse it unchanged as the predicate for
"this hook entry belongs to Ormah".

### 2. `_merge_hooks(existing_hooks: dict, ormah_hooks: dict) -> dict` (new)

Pure function. For each event in `ormah_hooks`:

- Take the existing event list (default `[]`).
- Within each existing matcher, drop inner hooks for which `_is_ormah_hook` is true
  (strip prior Ormah entries); keep matchers that still have non-Ormah hooks.
- Append the Ormah matchers for that event.

Events present in `existing_hooks` but not in `ormah_hooks` are left untouched. This mirrors the
uninstall filtering, so install and uninstall share the same notion of an "Ormah hook".

Returns the merged `hooks` dict. Pure and independently testable — no file I/O.

### 3. `configure_claude_hooks` / `configure_codex_hooks` (changed)

Both: read the existing JSON file, apply `_merge_hooks` to its `hooks` sub-dict, write back.
Replaces the `_merge_json_file(..., {"hooks": ...})` call. `_merge_json_file` stays for the
`mcpServers` callers, where one-level merge is correct.

### 4. `_write_env_file(env: dict[str, str])` (changed; signature unchanged)

Preserve the existing file's layout:

- If the file exists, read its raw lines.
- For each existing `KEY=...` line whose key is in `env`: replace with `KEY=<new value>` in place.
- Drop existing `KEY=...` lines whose key is *not* in `env` (caller removed it).
- Keep comment lines, blank lines, and any other content verbatim, in original order.
- Append `KEY=value` for keys in `env` not already present in the file, at the end.
- If the file does not exist, write keys in `dict` order (current behavior).
- Preserve `0o600` permissions.

The 8 callers using the `read dict → mutate → write dict` pattern stay unchanged.
`_read_env_file` is unchanged.

## Testing (TDD)

Unit, pure-function and file-level, mocking only the home-dir path (`tmp_path`):

- `_merge_hooks`:
  - co-tenant: a non-Ormah hook under `UserPromptSubmit` survives the merge.
  - idempotent: merging twice yields exactly one Ormah entry (no duplication).
  - untouched event: an event Ormah doesn't claim is returned unchanged.
- `configure_claude_hooks` / `configure_codex_hooks` (against a `tmp_path` settings file):
  - pre-existing third-party hook under a shared event is preserved after install.
  - second `configure_*` call does not duplicate Ormah's hook.
- `_write_env_file`:
  - file with comments + a manually-added key: writing an updated `env` preserves the comments,
    the blank lines, the ordering, and the manual key.
  - removing a key from the dict drops its line but keeps comments.
  - new key appends at the end.
  - non-existent file falls back to dict-order write.

## Worked example (the bug this catches)

`~/.claude/settings.json` has `UserPromptSubmit: [{hooks: [{command: "other-tool"}]}]`.
Run `ormah setup`. With `_merge_hooks`, the result is
`UserPromptSubmit: [{hooks: [{command: "other-tool"}]}, {hooks: [{command: ".../ormah whisper inject"}]}]`
— the other tool's hook survives. Today, `_merge_json_file` replaces the list, leaving only Ormah.
