# SPIKE-FINDINGS — Task 01 (GATE)

Re-run 2026-07-01 on branch `feat/ingest-claude-cli-extraction` (base `origin/main`).

## Gate results

1. **Subscription auth without API key — YES.** `env -u ANTHROPIC_API_KEY claude -p ...` returns
   `rc=0`, `is_error: false`. No paid API key present → the child uses subscription OAuth (`~/.claude/`).
   The "no API" requirement holds.
2. **Envelope text field:** `envelope["result"]` — a plain **string**. Full key set:
   `type, subtype, result, is_error, session_id, uuid, num_turns, stop_reason, usage, modelUsage,
   total_cost_usd, duration_ms, duration_api_ms, ttft_ms, permission_denials, api_error_status,
   fast_mode_state, terminal_reason`. `type == "result"`. Task 02 parses `envelope.get("result")`.
3. **stdin — YES.** `printf 'reply with the single word STDINOK' | claude -p ...` → `result: "STDINOK"`.
   Prompt is read from stdin; Task 02 feeds via `input=`, never argv.
4. **hooks-off mechanism:** `--settings '{"hooks":{}}'` accepted (rc=0). Used as `_HOOKS_OFF_ARGS`.
5. **tool-deny:** `--allowed-tools ""` accepted (rc=0), `permission_denials: []` with no tool use.
   Used as `_TOOL_DENY_ARGS`.
6. **Extractor workdir → transcript location** (confirmed prior session, unchanged): cwd
   `/tmp/ormah-extractor` → real path `/private/tmp/ormah-extractor` (macOS `/tmp` symlink) →
   `~/.claude/projects/-private-tmp-ormah-extractor/`. Task 02 purge + Task 04 guard both use
   `os.path.realpath` before encoding.

## Fixture

`tests/fixtures/claude_cli_envelope.json` — captured real envelope from this run (result `"STDINOK"`).

## Deferred

- **Step 1b (launchd context re-confirm):** interactive shell passed. Re-confirm subscription auth
  under the real `com.ormah.server.dev` launchd env is deferred to Task 06 enablement (record the
  launchd `PATH` and `claude_cli_bin` there). Not a blocker for Tasks 02–05 (pure code + unit tests).

## Base-divergence note (origin/main vs the plan's local-main assumptions)

Decided 2026-07-01: develop off `origin/main` (upstream-clean), adapt Tasks 04/05 to origin/main:
- `_ingest_session` returns **`bool`** on origin/main (NOT `IngestResult`). The extractor guard
  returns `False` (skip), and Task 04's tests assert `is False`, not `== IngestResult.NO_PROGRESS`.
- `on_created`/`on_modified` on origin/main have **no** `_is_subagent_transcript` filter to "extend";
  the extractor guard is added as its own standalone check in the handlers.
- No #52 off-bind-path catch-up on origin/main. e2e (Task 06) runs by merging the feature into
  `local-main` (the Beta integration branch / dev server), not by running this branch raw.
