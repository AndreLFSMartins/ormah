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

## Stage 2: bundled runtime + keeping whisper working

The app's one-click setup runs `ormah setup --json`, which wires **MCP and the
whisper hooks** into Claude Code / Codex:

- `UserPromptSubmit` → `<ormah_bin> whisper inject` (involuntary recall)
- `PreCompact` / `SessionEnd` → `<ormah_bin> whisper store`

These hooks run inside the *agent's* process, not the app, so `<ormah_bin>` must
be a **stable executable on the user's machine**. For the dev / `curl` install
that's `~/.local/bin/ormah` and whisper works as-is. For a fully **bundled** app
(non-devs with no system `ormah`), the in-bundle binary is **not** a stable
path:

- An **AppImage** mounts at a fresh `/tmp/.mount_xxxx` every launch, so a hook
  pointing at the in-bundle binary breaks on the next run.
- The hook CLI also needs the server's `ORMAH_PORT`; if the bundled app doesn't
  use the default port, `whisper inject` would hit the wrong server.

**Required Stage-2 work so whisper survives in the bundled app:**

1. On setup, install a **stable CLI shim on `PATH`** — e.g. `~/.local/bin/ormah`
   — a tiny launcher that `exec`s the bundled `ormah-server` with the app's
   `ORMAH_PORT` exported. Point the whisper hooks at this shim, not the
   ephemeral bundle path.
2. Make setup **port-aware**: write the shim/hooks with the same port the
   bundled server runs on (and decide that port — see Risks: 8787 clashes with a
   dev's existing server).
3. Re-run/refresh the shim on app update so the path/port stay correct.

Until this lands, whisper only works when a real `ormah` CLI is already on
`PATH` (the dev/`curl` install).

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

The app **builds and runs on Linux** (`cargo build` + `cargo tauri dev`/run):
intro → install flow → in-app graph all work against a server with the F10
endpoints. The **macOS** build (`.dmg`, signing, notarization) still needs a Mac
or the CI runner. **Stage 2** (frozen-runtime bundling + the whisper CLI shim
above) is not done yet, so today the app relies on a real `ormah` already on
`PATH`.

Backend the app depends on is covered by the pytest suite:

- `GET /agent/stats` — `tests/test_api/test_stats.py`
- `GET /agent/clients` + `ormah setup --json` — `tests/test_api/test_stats.py`, `tests/test_setup_json.py`
