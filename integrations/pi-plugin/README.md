# Ormah-Pi

The Ormah memory layer for the [Pi](https://github.com/earendil-works/pi-coding-agent) coding agent — the Pi counterpart to Ormah's Claude Code integration (`integrations/claude-plugin/`).

Ormah is a local-first, self-maintaining memory system for AI agents. This extension wires Pi into a local Ormah server so memory is **involuntary**: relevant context is whispered before each prompt, and sessions are extracted into durable memory when they end.

Local. Private. Portable. Yours to keep.

## What it does

- **Whisper (involuntary recall)** — before each prompt, calls `POST /agent/whisper` and injects the returned context as a hidden message so the LLM starts the turn with memory. Ports Claude's `UserPromptSubmit` hook.
- **Memory tools** — registers six tools the LLM can call, proxied to the Ormah HTTP API:
  - `ormah_remember`, `ormah_recall`, `ormah_recall_node`, `ormah_mark_outdated`, `ormah_submit_feedback`, `ormah_run_maintenance`
- **Transcript capture** — on compaction (`session_before_compact`) and session end (`session_shutdown`), normalizes the Pi session into `User:`/`Assistant:` text and `POST /ingest/conversation` for server-side extraction. Ports Claude's `PreCompact` + `SessionEnd` hooks.
- **Commands** — `/ormah:setup`, `/ormah:status`, `/ormah:maintenance`, `/ormah:upgrade`, `/ormah:reload`.
- **Self-maintenance** — when enabled, whisper appends a `maintenance_due` signal at most once per 24h; `/ormah:maintenance` loads the maintenance agent prompt so the session runs the two-step `ormah_run_maintenance` flow.

## Requirements

- Pi ≥ 0.80
- A running local Ormah server (`ormah server start`, default `http://127.0.0.1:8787`)

## Install

Full end-user flow (Ormah runtime + Pi extension + wiring) is in [SETUP.md](./SETUP.md). Short version:

```bash
# 1. Ormah runtime (detects Pi and wires it automatically)
bash <(curl -fsSL https://ormah.me/install.sh)
# 2. Pi extension from the package gallery
pi install npm:ormah-pi
# 3. In Pi: /reload, then /ormah:status
```

Other sources:

```bash
pi install git:github.com/r-spade/ormah@main      # from git (tag/commit pinned)
pi install npm:ormah-pi -l                        # project-local (.pi/settings.json)
pi -e ./integrations/pi-plugin/ormah-pi.ts         # try without installing (dev)
```

`ormah-pi` appears on the [pi.dev/packages](https://pi.dev/packages) gallery because its `package.json` carries the `pi-package` keyword.

## First-run setup

If `ormah setup` (step 1) already detected Pi, you're done — `/ormah:status` should show `connected`. If you used `--skip-client-setup`, run `/ormah:setup` inside Pi: it runs `ormah setup --skip-client-setup` (server + local models + autostart) and writes the Ormah guidance block into `~/.pi/agent/AGENTS.md`. Then `/reload`.

## Configuration

All settings are env vars (read from the environment and `~/.config/ormah/.env`):

| Var | Default | Purpose |
|---|---|---|
| `ORMAH_HOST` / `ORMAH_PORT` | `127.0.0.1` / `8787` | Ormah server location |
| `ORMAH_BASE_URL` | `http://$HOST:$PORT` | Override base URL entirely |
| `ORMAH_WHISPER_NUDGE_INTERVAL` | `10` | Nudge the agent to `remember` every N prompts (0 = off) |
| `ORMAH_WHISPER_OUT_MIN_TURNS` | `3` | Minimum user turns before a session is stored |
| `ORMAH_PI_MAINTENANCE_ENABLED` | `false` | Enable the `maintenance_due` whisper signal (falls back to `ORMAH_CLAUDE_MAINTENANCE_ENABLED`) |
| `ORMAH_MAINTENANCE_SIGNAL_INTERVAL_HOURS` | `24` | Max once per N hours the signal is appended |
| `ORMAH_PI_*_TIMEOUT_MS` | various | Per-call HTTP timeouts |

> **Note:** whisper store (transcript extraction) and LLM-backed maintenance need an Ormah LLM provider (`ORMAH_LLM_PROVIDER=ollama|litellm` + key). Local recall, whisper retrieval, and the tools work without one.

## Publishing (maintainers)

To list `ormah-pi` on the [pi.dev/packages](https://pi.dev/packages) gallery, publish to npm from this directory. The `package.json` already carries the `pi-package` keyword (required for gallery listing) and declares core imports as `peerDependencies` (Pi bundles them — do not bundle them yourself).

```bash
cd integrations/pi-plugin
npm version patch            # bump version
npm publish --access public # gallery re-indexes packages tagged pi-package
```

Users then install with `pi install npm:ormah-pi` (versioned pins like `npm:ormah-pi@0.1.1` are respected). For an optional gallery preview, add `pi.image` (PNG/JPEG/GIF/WebP) or `pi.video` (MP4) to the `pi` block in `package.json`.

Tag releases so git installs can pin a ref: `git tag v0.1.1 && git push --tags`, then `pi install git:github.com/r-spade/ormah@v0.1.1`.

## Architecture

Transport is HTTP `fetch` to the Ormah server — the same `/agent/*` routes Ormah's own MCP adapter (`src/ormah/adapters/maintenance_manager.py` … `mcp_adapter.py`) uses — so no `ormah mcp` subprocess is needed. Pi sessions live at `~/.pi/agent/sessions/` with a different JSONL shape than Claude/Codex, so transcript capture normalizes entries client-side and feeds `POST /ingest/conversation` directly (no upstream Ormah change required).

## Layout

```text
integrations/pi-plugin/
  ormah-pi.ts            # entry — wires events, tools, commands
  package.json           # pi-package metadata (pi.extensions)
  tsconfig.json
  src/
    config.ts            # ORMAH_* env config
    client.ts            # HTTP client → /agent/* and /ingest/*
    space.ts             # space detection (mirrors space_detect.py)
    whisper.ts           # before_agent_start inject + nudge + maintenance_due
    tools.ts             # 6 registerTool calls
    store.ts             # session_before_compact / session_shutdown → /ingest
    session.ts           # Pi entries → normalized conversation text
    maintenance.ts       # loads the maintenance agent prompt
  agents/
    ormah-maintenance.md # maintenance agent prompt (port of upstream)
```

## License

MIT, same as Ormah.
