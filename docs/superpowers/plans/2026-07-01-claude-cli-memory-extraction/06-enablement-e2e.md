### Task 06: Enablement + end-to-end verification

Switch the runtime to `claude_cli`, restart, and prove the whole chain: extraction happens via
Claude, zero gemma calls, and the extractor's own transcript is not re-ingested. No new production
code — this is configuration + a verification gate. (`~/.config/ormah/.env` is not committed.)

**Files:**
- Modify: `~/.config/ormah/.env` (runtime config; not in git)
- Reference: `/tmp/ormah-dev.err` (dev server log), `http://localhost:8787` (via python `urllib`, not curl)

- [ ] **Step 1: Point EXTRACTION (only) at claude_cli**

Edit `~/.config/ormah/.env`:

```
ORMAH_INGEST_LLM_PROVIDER=claude_cli
ORMAH_CLAUDE_CLI_MODEL=haiku
ORMAH_CLAUDE_CLI_TIMEOUT_SECONDS=120
ORMAH_CLAUDE_CLI_MAX_CONCURRENCY=1
ORMAH_SESSION_WATCHER_ENABLED=true
```

Leave `ORMAH_LLM_PROVIDER` as it is (maintenance path — e.g. `none` with claude_maintenance, or
`ollama`). Do NOT set it to `claude_cli`. Keep embeddings on Ollama
(`ORMAH_EMBEDDING_PROVIDER=ollama`, `bge-m3`) — unchanged.

- [ ] **Step 2: Restart the dev server (config is cached at boot)**

Run: `launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev`
Wait for bind (python, since curl is intercepted in this env):

```python
import urllib.request, time
for _ in range(30):
    try:
        urllib.request.urlopen("http://localhost:8787/health", timeout=2); print("UP"); break
    except Exception: time.sleep(1)
```
Expected: `UP` within a few seconds (catch-up runs off the bind path since #52).

- [ ] **Step 3: Verify extraction goes to Claude, not gemma**

Trigger a dry-run extraction via python `urllib`:

```python
import json, urllib.request
req = urllib.request.Request(
    "http://localhost:8787/ingest/conversation?dry_run=true",
    data=json.dumps({"content": "e2e probe: André decidiu migrar a extração do ormah "
                     "para claude -p Haiku via provider claude_cli, sem API."}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
print(json.load(urllib.request.urlopen(req, timeout=180)))
```
Expected: `status: dry_run`, `extracted >= 1`.

- [ ] **Step 4: Assert zero Ollama generate calls during extraction**

Confirm no `/api/generate` (gemma) fired for the probe — extraction used Claude:

```bash
grep -c "api/generate" /tmp/ormah-dev.err   # note the count
# run Step 3 again, then:
grep -c "api/generate" /tmp/ormah-dev.err   # count MUST be unchanged
```
Expected: the `/api/generate` count does not increase (embeddings still hit `/api/embed`, which is fine).

- [ ] **Step 5: Assert the extractor transcript is not re-ingested**

After a few extractions, confirm the watcher did not ingest its own worker transcript:

```bash
grep -a "session_watcher ingested" /tmp/ormah-dev.err | grep -i "ormah-extractor" || echo "OK: extractor transcript excluded"
```
Expected: `OK: extractor transcript excluded` (no line naming the extractor's encoded dir).

- [ ] **Step 6: Full suite green**

Run: `.venv/bin/python -m pytest tests/ -m 'not integration' -q`
Expected: PASS. Then `.venv/bin/ruff check src/ tests/` — clean.

- [ ] **Step 7: Update the ormah memory + finalize**

Update memory `ormah-ingest-stale-adapter` / `ollama-setup`: the runtime provider is now
`claude_cli` (Haiku, subscription), gemma retired from extraction. Open the upstream PR from the
feature branch per the project's PR flow (`/council-pr`).
