### Task 01: Spike — subscription auth, envelope fixture, hooks-off, extractor workdir (GATE)

Not TDD — a verification spike that produces the facts Tasks 02+ depend on. **If the
subscription-auth check fails, STOP and revisit the design with André before writing any code.**

**Files:**
- Create: `tests/fixtures/claude_cli_envelope.json` (captured real envelope, for Task 02's contract test)
- Create: `docs/superpowers/plans/2026-07-01-claude-cli-memory-extraction/SPIKE-FINDINGS.md` (record results)

- [ ] **Step 1: Confirm subscription auth (no API billing) — in an interactive shell first**

```bash
env -u ANTHROPIC_API_KEY claude -p "reply with the single word ok" \
  --model haiku --output-format json
```

Expected: a JSON envelope with a `result` field. Verify the account used is the **subscription**
(`claude` logged in via `~/.claude/`), NOT an API key. If it only works WITH `ANTHROPIC_API_KEY`
set, the "no API" requirement fails — **STOP**.

- [ ] **Step 1b: Re-confirm under the REAL launchd plist env (the deployment context)**

The interactive shell is NOT the deployment env. The server runs under `com.ormah.server.dev` via
launchd, which has its own `PATH`/env and macOS TCC scoping — `~/.claude/` OAuth and the `claude`
binary may resolve differently there. Prove it in that exact context: write a tiny probe the launchd
service runs, or exec through the same env the plist provides.

```bash
# Capture the launchd service env and run the probe under it:
launchctl print gui/$(id -u)/com.ormah.server.dev | sed -n 's/^[[:space:]]*\([A-Z_]*\) => .*/\1/p' | head
# Then run the probe with cwd=/tmp/ormah-extractor and NO ANTHROPIC_API_KEY, mirroring the
# server's PATH, and confirm: (a) `claude` is found, (b) subscription auth works, (c) billing
# mode is subscription (not api). Record the exact PATH and result in SPIKE-FINDINGS.md.
```

Gate: subscription auth must work **in the launchd context**, not just the terminal. If `claude`
is not on the launchd PATH, record the absolute path for `claude_cli_bin` (Task 03). If auth fails
under launchd → **STOP** and revisit with André.

- [ ] **Step 2: Capture the envelope shape**

Save the exact stdout of Step 1 to `tests/fixtures/claude_cli_envelope.json`. Note in
SPIKE-FINDINGS.md the field holding the assistant text (expected `result`) and whether it is a
plain string or nested. Task 02's parser targets this shape.

**Also confirm `claude -p` reads the prompt from stdin** (Task 02 feeds it via `input=`, never argv):
```bash
printf 'reply with the word STDINOK' | env -u ANTHROPIC_API_KEY claude -p \
  --model haiku --output-format json
```
Expected: the envelope `result` contains `STDINOK`. If `claude -p` ignores stdin and requires the
prompt as an argument, that breaks the privacy/ARG_MAX design — **STOP** and revisit with André.

- [ ] **Step 3: Settle the hooks-off mechanism**

The extractor's `claude -p` child must NOT fire ormah hooks (else it POSTs to `/ingest` and/or
spawns another extraction → recursion). Test candidates in order and record which works:

```bash
# candidate A: settings override with empty hooks
env -u ANTHROPIC_API_KEY claude -p "reply ok" --model haiku --output-format json \
  --settings '{"hooks":{}}'
# candidate B: a dedicated config dir without the plugin
CLAUDE_CONFIG_DIR=/tmp/ormah-extractor-cfg env -u ANTHROPIC_API_KEY \
  claude -p "reply ok" --model haiku --output-format json
```

Verify the child did NOT trigger a `/ingest/conversation` on the running server (grep
`/tmp/ormah-dev.err` for a new POST during the call). Record the winning mechanism verbatim —
Task 02 hardcodes it.

- [ ] **Step 3b: Confirm the tool-deny flag (prompt-injection boundary)**

The transcript is untrusted input. Confirm the exact flag that denies ALL agent tools so the worker
can only emit text, never act:

```bash
env -u ANTHROPIC_API_KEY claude -p "list your available tools, then try to read /etc/hosts" \
  --model haiku --output-format json --allowed-tools ""
```

Verify the worker reports no usable tools / cannot read the file. If `--allowed-tools ""` is not the
right flag on this CLI version, record the correct one (`--disallowed-tools`, a settings key, etc.)
in SPIKE-FINDINGS.md — Task 02 uses it as `_TOOL_DENY_ARGS`.

- [ ] **Step 4: Confirm extractor workdir → transcript location**

Run the child with `cwd=/tmp/ormah-extractor` and confirm where its transcript lands:

```bash
mkdir -p /tmp/ormah-extractor
( cd /tmp/ormah-extractor && env -u ANTHROPIC_API_KEY claude -p "reply ok" \
  --model haiku --output-format json )
ls -t ~/.claude/projects/*ormah-extractor*/ 2>/dev/null | head
```

Record the encoded project dir name. **Spike result: `/tmp/ormah-extractor` → cwd real path
`/private/tmp/ormah-extractor` → `~/.claude/projects/-private-tmp-ormah-extractor/`** (macOS `/tmp`
symlink). Task 04's `_encode_workdir` uses `os.path.realpath` to match. The worker DOES persist a
transcript here, so both the recursion guard (Task 04) and the purge (Task 02) are required.

- [ ] **Step 5: Write SPIKE-FINDINGS.md and gate**

Record: (1) subscription auth works without API key — yes/no; (2) envelope text field; (3) hooks-off
mechanism; (4) extractor transcript path. If (1) is no → STOP. Otherwise Tasks 02–06 proceed using
these values. No commit (findings + fixture live under gitignored `docs/superpowers/` and `tests/fixtures/`
— add the fixture to git in Task 02 where the contract test uses it).
