# Ormah Desktop (macOS menubar app)

A ruthlessly minimal Tauri v2 menubar app (F10). It is **onboarding + visibility**,
not a new product:

1. **Menubar presence** — tray icon whose title is the weekly *whispers-used*
   count (the F09 counter), with a dropdown showing the stats.
2. **Bundled runtime** — ships the Ormah server as a frozen sidecar and manages
   start/stop. No `curl | bash`, no launchd fiddling.
3. **One-click agent setup** — detects Claude Code / Claude Desktop / Codex and
   wires hooks/MCP via the bundled `ormah setup --json`.
4. **Open graph** — opens the existing web UI in the browser. No reimplementation.
5. **Auto-update** — Tauri updater (Sparkle-style appcast).

Explicitly **not** in v1: Memory Spotlight / global hotkey, native graph or node
editing, Windows/Linux, settings beyond start-at-login + update channel.

## Architecture

```
Tauri shell (Rust, src-tauri/)
  ├─ tray.rs      tray icon + title (counter) + dropdown menu
  ├─ stats.rs     polls GET /agent/stats every 60s → tray title
  ├─ sidecar.rs   spawns/stops the bundled ormah-server
  └─ commands.rs  setup_agents (ormah setup --json), open graph, onboarding marker
       ↓ spawns
binaries/ormah-server-<triple>   ← PyInstaller-frozen `ormah` (server + setup)
       ↓ serves
http://127.0.0.1:8787            ← existing FastAPI app + web UI
```

The frozen sidecar is the normal `ormah` CLI: the app runs
`ormah-server server start` to serve, and `ormah-server setup --json` to wire
agents. One binary, two jobs.

## Prerequisites (one-time)

- A **Mac** (this app cannot be built or run on Linux/Windows).
- Rust + `cargo` (`https://rustup.rs`).
- Tauri CLI: `cargo install tauri-cli --version "^2" --locked`.
- Python 3.12 + PyInstaller (the build script provisions a venv).
- For release only: an **Apple Developer ID** ($99/yr) and a Tauri updater
  signing keypair (`cargo tauri signer generate`).

## Build & run (dev)

```bash
# 1. Freeze the Python server into a sidecar binary for your arch.
desktop/scripts/build-sidecar.sh

# 2. Generate the full icon set from the placeholder source (one-time).
cd desktop/src-tauri && cargo tauri icon icons/icon.png && cd -

# 3. Run the app (tray appears; server boots; onboarding shows on first run).
cd desktop && cargo tauri dev
```

Exit criterion for the dev spike: `.dmg`-free `cargo tauri dev` shows the tray
with a live counter, and **Open graph** loads the existing UI.

## Release (signed + notarized .dmg)

CI: `.github/workflows/desktop-release.yml` builds per-arch on macOS runners,
signs with Developer ID, notarizes via `notarytool`, signs the updater appcast,
and attaches the `.dmg` to the GitHub release. Trigger with a `desktop-v*` tag.

Required GitHub secrets:

| Secret | Purpose |
| --- | --- |
| `APPLE_CERTIFICATE` | base64 Developer ID Application `.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | password for the `.p12` |
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: … (TEAMID)` |
| `APPLE_ID` | Apple ID email for notarization |
| `APPLE_APP_PASSWORD` | app-specific password for notarytool |
| `APPLE_TEAM_ID` | Apple Developer Team ID |
| `TAURI_SIGNING_PRIVATE_KEY` | Tauri updater private key |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | password for the updater key |

Also set `plugins.updater.pubkey` in `tauri.conf.json` to the matching public
key, and point `plugins.updater.endpoints` at where you host the appcast.

## Risks / known follow-ups

- **Bundling rabbit hole** — `sqlite-vec`, `sentence-transformers`/`torch`, and
  `tokenizers` native deps are the schedule risk. The PyInstaller flags in
  `build-sidecar.sh` are a starting point; expect to iterate on a real Mac. If
  frozen builds fight back, the fallback is an embedded uv env (install.sh logic
  inside the app).
- **Model downloads on first run** — embedding + reranker weights are *not*
  bundled in the `.dmg`. The onboarding flow waits for the server and shows
  honest "downloading models" status before declaring ready.
- **Updater appcast publishing** — the CI `publish` job attaches artifacts but
  the appcast (`latest.json`) regeneration/upload is a TODO.

## Verification status

The Rust shell, configs, scripts, CI, and onboarding UI in this directory were
authored on Linux and are **not yet compiled or run** — they require a Mac.
What *is* tested (in the main pytest suite) is everything the app depends on:

- `GET /agent/stats` — `tests/test_api/test_stats.py`
- `ormah setup --json` (`detect_clients`, `run_setup_json`) — `tests/test_setup_json.py`
