# Runbook — running against the archived data directory (`ormah_old`)

**LOCAL-ONLY.** This file describes one machine's data layout. It is never part of an
upstream PR — `docs/runbooks/` is in the `PROTECTED` allowlist of `.git/hooks/pre-push`
(fail-closed). See FORK-WORKFLOW.md Golden rule 5.

## What happened (2026-08-13)

The live data directory was archived so a clean server could be built from zero:

```
~/.local/share/ormah      ->  ~/.local/share/ormah_old     # mv, atomic, same volume
~/.local/share/ormah                                       # recreated empty
```

`~/.local/share/ormah_old/models/` was then **deleted** (68 GB). It was a fastembed cache,
not data: 67 GB of it were 10,755 `.incomplete` blobs from a download retry loop that ran
1h28 on 2026-08-05. Nothing referenced it — this install embeds through Ollama
(`ORMAH_EMBEDDING_PROVIDER=ollama`, `bge-m3`, dim 1024).

What remains in `ormah_old` (5.1 GB):

| path | size | note |
|---|---|---|
| `memory/` | 943 MB | the real archive: `nodes/` (36,968 entries), `index.db` (761 MB), `deleted/` |
| `backups/` | 3.7 GB | rotating local backups |
| `memory.bak-20260708-172456/` | 241 MB | pre-migration snapshot |
| `memory.bak-pre-standard-20260708/` | 181 MB | pre-migration snapshot |
| `logs/`, `server.log` | 30 MB | history behind the sleeping-cycle measurements |
| `local_api_token` | — | dead here; see "The token does not follow" below |

## The recipe — point a server at the archive

Both paths are plain settings with the `ORMAH_` env prefix, so no copying is needed
(`src/ormah/config.py:77` and `:82`, prefix at `:68`):

```bash
ORMAH_MEMORY_DIR=$HOME/.local/share/ormah_old/memory \
ORMAH_BACKUP_DIR=$HOME/.local/share/ormah_old/backups \
ORMAH_PORT=8788 \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ormah server start
```

`ORMAH_PORT` is not optional if the clean server is up: both default to 8787 and the
second one loses the bind.

## Four things that will bite

### 1. This is read-write, not a snapshot

Nothing about `ORMAH_MEMORY_DIR` makes the archive read-only. A server pointed at it
mutates `nodes/` and `index.db`, and background jobs will happily rewrite the very
history the archive exists to preserve. To keep the archive pristine, copy first:

```bash
cp -Rc ~/.local/share/ormah_old/memory ~/.local/share/ormah_test/memory   # APFS clone-on-write, instant
```

`-c` makes it an APFS clone: no extra disk until something is written.

### 2. Embedding dimension must match what wrote the index

The archived `index.db` vectors were written at `ORMAH_EMBEDDING_DIM=1024` (`bge-m3` via
Ollama). Booting against it with a different model/dim is the destructive case the code
guards with `reindex_on_dim_change` (`config.py:100`) — that flag authorizes wiping the
vector store. Do not set it while pointed at the archive. Keep the embedding block of
`~/.config/ormah/.env` unchanged, or pass the same three values explicitly:

```bash
ORMAH_EMBEDDING_PROVIDER=ollama ORMAH_EMBEDDING_MODEL=bge-m3 ORMAH_EMBEDDING_DIM=1024
```

Ollama must be up on :11434 with `bge-m3` pulled, or the boot has no embedder at all.

### 3. The token does not follow

`local_api_token` is **hardcoded**, not derived from `ORMAH_MEMORY_DIR`:

```python
# src/ormah/api/local_auth.py:14
LOCAL_ADMIN_TOKEN_PATH = Path.home() / ".local" / "share" / "ormah" / "local_api_token"
```

So a server pointed at the archive still reads the capability from the **clean** install,
and `ormah_old/local_api_token` is inert. Harmless for memory work — it only gates the
account/billing and cloud-protection routes — but it means the two installs are not
isolated on that axis.

### 4. launchd does not see your shell

`com.ormah.server.dev` runs `~/.config/ormah/ormah-server-dev`, which sources
`~/.config/ormah/.env` and ignores the environment of whatever terminal you exported in.
An `ORMAH_MEMORY_DIR` set in a shell affects **only** the server that shell starts.
To make launchd itself serve the archive you would have to edit that `.env` — which also
redirects the Beta the whisper hooks talk to. Prefer the foreground command above.

That wrapper also refuses to boot unless the repo is on `local-main` (FORK-WORKFLOW.md
Golden rule 1) — the working tree is what the live Beta serves.

## Current state (as of 2026-08-13)

The server is **stopped** and its launchd agent is **unloaded**:

```bash
launchctl bootout gui/$(id -u)/com.ormah.server.dev     # what was run
```

`ormah server stop` alone is not enough: the agent has `KeepAlive=true` and respawns the
process within seconds, and the CLI's own launchd check looks for a different label, so it
reports "No launchd agent installed" while the agent is right there.

To bring the Beta back:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ormah.server.dev.plist
```

## Rollback

The archive is one rename away from being live again:

```bash
launchctl bootout gui/$(id -u)/com.ormah.server.dev   # stop the clean server first
rmdir ~/.local/share/ormah                            # only succeeds if still empty
mv ~/.local/share/ormah_old ~/.local/share/ormah
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ormah.server.dev.plist
```

The deleted `models/` does not come back, and does not need to: with the Ollama provider
nothing reads it, and a `local` provider re-downloads it (~300 MB when it behaves).

## Open, not fixed

The fastembed download loop that produced 10,755 `.incomplete` blobs in 88 minutes was
never diagnosed. Flipping `ORMAH_EMBEDDING_PROVIDER` back to `local` can reproduce it.
Watch `~/.local/share/ormah/models/*/blobs/` if you ever do.

## Untested

Every command here is derived from reading the code and the plists; the archive-pointed
boot in "The recipe" has **not** been executed. Expect the first run to surface something
this file does not mention.
