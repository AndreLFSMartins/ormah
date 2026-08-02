"""CLI adapter — thin synchronous HTTP client for terminal access to ormah."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import uuid

import httpx

from pathlib import Path

try:
    import fcntl  # POSIX only; Windows falls back to no locking (documented degraded mode)
except ImportError:  # pragma: no cover - Windows
    fcntl = None

from ormah.adapters.space_detect import detect_space_from_dir, resolve_space
from ormah.config import settings

BASE = f"http://localhost:{settings.port}"


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=30.0)


def _api(fn):
    """Run fn(), catching connection and HTTP errors."""
    try:
        return fn()
    except httpx.ConnectError:
        print("Ormah server not running. Start it with: ormah server start -d", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"Error: {e.response.status_code} {e.response.text}", file=sys.stderr)
        sys.exit(1)


def cmd_recall(args):
    space = resolve_space(args.space)
    body: dict = {"query": args.query}
    if args.limit:
        body["limit"] = args.limit
    if args.types:
        body["types"] = args.types.split(",")
    params = {"default_space": space} if space else {}

    def call():
        with _client() as c:
            r = c.post("/agent/recall", json=body, params=params)
            r.raise_for_status()
            if args.json:
                print(json.dumps(r.json(), indent=2))
            else:
                print(r.json()["text"])

    _api(call)


def cmd_remember(args):
    content = sys.stdin.read() if args.content == "-" else args.content
    space = resolve_space(args.space)
    body: dict = {
        "content": content,
        "type": args.type,
        "tier": args.tier,
    }
    if args.title:
        body["title"] = args.title
    if args.tags:
        body["tags"] = args.tags.split(",")
    if args.about_self:
        body["about_self"] = True
    if space:
        body["space"] = space
    params = {"default_space": space} if space else {}

    def call():
        with _client() as c:
            r = c.post("/agent/remember", json=body, params=params)
            r.raise_for_status()
            print(r.json()["text"])

    _api(call)


def cmd_ingest(args):
    if args.source == "-":
        content = sys.stdin.read()
    else:
        with open(args.source) as f:
            content = f.read()
    space = resolve_space(args.space)
    body: dict = {"content": content}
    params = {"default_space": space} if space else {}

    def call():
        with _client() as c:
            r = c.post("/ingest/conversation", json=body, params=params)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "error":
                print(data["result"], file=sys.stderr)
                sys.exit(1)
            count = data.get("extracted", 0)
            if count == 0:
                print("No new memories extracted from the conversation.")
            else:
                lines = [f"Extracted {count} memories:"]
                for mem in data.get("memories", []):
                    lines.append(f"  - {mem['title']} (ID: {mem['node_id'][:8]}...)")
                print("\n".join(lines))

    _api(call)


def cmd_ingest_session(args):
    from ormah.transcript.parser import parse_transcript

    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    result = parse_transcript(path)

    if result.user_turn_count < args.min_turns:
        print(
            f"Skipped: only {result.user_turn_count} user turns "
            f"(minimum: {args.min_turns})"
        )
        return

    pct = (result.cleaned_chars / result.total_chars * 100) if result.total_chars else 0
    print(
        f"Parsed: {result.user_turn_count} turns, "
        f"{result.cleaned_chars} chars ({pct:.1f}% of {result.total_chars})"
    )

    if not result.conversation.strip():
        print("No conversation text extracted.")
        return

    space = resolve_space(args.space)
    body: dict = {"content": result.conversation}
    params: dict = {}
    if space:
        params["default_space"] = space
    if args.dry_run:
        params["dry_run"] = "true"

    def call():
        with _client() as c:
            r = c.post(
                "/ingest/conversation",
                json=body,
                params=params,
                timeout=120.0,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "error":
                print(data["result"], file=sys.stderr)
                sys.exit(1)
            count = data.get("extracted", 0)
            if count == 0:
                print("No memories extracted from session.")
            else:
                label = "Would extract" if args.dry_run else "Extracted"
                lines = [f"{label} {count} memories:"]
                for mem in data.get("memories", []):
                    title = mem.get("title", "untitled")
                    node_id = mem.get("node_id")
                    if node_id:
                        lines.append(f"  - {title} (ID: {node_id[:8]}...)")
                    else:
                        mem_type = mem.get("type", "fact")
                        lines.append(f"  - [{mem_type}] {title}")
                print("\n".join(lines))

    _api(call)


def cmd_node(args):
    def call():
        with _client() as c:
            r = c.get(f"/agent/recall/{args.id}")
            r.raise_for_status()
            if args.json:
                print(json.dumps(r.json(), indent=2))
            else:
                print(r.json()["text"])

    _api(call)


def cmd_outdated(args):
    body: dict = {}
    if args.reason:
        body["reason"] = args.reason

    def call():
        with _client() as c:
            r = c.post(f"/agent/outdated/{args.id}", json=body)
            r.raise_for_status()
            print(r.json()["text"])

    _api(call)


def cmd_stats(args):
    def call():
        with _client() as c:
            r = c.get("/stats")
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage", {})
            store = data.get("store", {})
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                total = store.get("total_nodes", 0)
                edges = store.get("total_edges", 0)
                by_tier = store.get("by_tier", {})
                week = usage.get("whispers_used_this_week", 0)
                used_total = usage.get("whispers_used_total", 0)
                print(f"Whispers used: {week} this week  ({used_total} total)")
                print(f"Memories: {total}  Edges: {edges}")
                for tier, count in sorted(by_tier.items()):
                    print(f"  {tier}: {count}")

    _api(call)


def cmd_status(args):
    def call():
        with _client() as c:
            r = c.get("/admin/health")
            r.raise_for_status()
            data = r.json()
            print(f"Status: {data['status']}")
            if "jobs" in data:
                for name, info in data["jobs"].items():
                    state = info.get("state", "unknown")
                    last = info.get("last_run")
                    line = f"  {name}: {state}"
                    if last:
                        line += f" (last: {last})"
                    print(line)

    _api(call)


def _whisper_client() -> httpx.Client:
    """Client with short timeout for whisper hook — fail fast, never block the user."""
    return httpx.Client(base_url=BASE, timeout=5.0)


def cmd_whisper_inject(args):
    """Read hook JSON from stdin, fetch context, output additionalContext."""
    try:
        raw = sys.stdin.read()
        hook_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Malformed input — exit silently
        sys.exit(0)

    prompt = hook_data.get("prompt", "")
    cwd = hook_data.get("cwd", "")

    if not prompt:
        sys.exit(0)

    # Resolve space from the hook-provided cwd, not our process cwd
    space = detect_space_from_dir(cwd) if cwd else None

    session_id = hook_data.get("session_id", "")

    body: dict = {"prompt": prompt}
    if space:
        body["space"] = space
    if session_id:
        body["session_id"] = session_id

    try:
        with _whisper_client() as c:
            r = c.post("/agent/whisper", json=body)
            r.raise_for_status()
            text = r.json().get("text", "")
    except httpx.ConnectError:
        warning_key = f"server-down-warning:{session_id or 'unknown'}"
        cursors = _load_cursors()
        if not cursors.get(warning_key):
            cursors[warning_key] = True
            _save_cursors(cursors)
            print(json.dumps({
                "systemMessage": (
                    "Ormah's backend is unavailable. Automatic memory recall and capture "
                    "are paused. Run `ormah server start -d` to restore it."
                )
            }))
        sys.exit(0)
    except Exception:
        # Server down, timeout, or any error — exit silently
        sys.exit(0)

    warning_key = f"server-down-warning:{session_id or 'unknown'}"
    cursors = _load_cursors()
    if cursors.pop(warning_key, None) is not None:
        _save_cursors(cursors)

    if not text.strip():
        text = ""

    # Track prompt count per session (used by nudge and periodic extraction)
    count = 0
    if session_id:
        counters = _load_nudge_counters()
        count_key = f"nudge:{session_id}"
        count = counters.get(count_key, 0) + 1
        counters[count_key] = count
        _save_nudge_counters(counters)

        # Append nudge at interval
        if (settings.whisper_nudge_interval > 0
                and count % settings.whisper_nudge_interval == 0):
            nudge = (
                "\n\n---\n"
                "Remember to use ormah's remember tool to store decisions, "
                "preferences or noteworthy facts from this conversation."
            )
            text += nudge

    if not text.strip():
        # Still trigger periodic extraction even when no inject text
        if (session_id
                and settings.whisper_out_enabled
                and settings.whisper_out_interval > 0
                and count % settings.whisper_out_interval == 0):
            transcript = _resolve_transcript_path(session_id)
            if transcript:
                _spawn_background_store(transcript, cwd, session_id)
        sys.exit(0)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text,
        }
    }
    print(json.dumps(output))

    # Periodic background extraction — after output is printed
    if (session_id
            and settings.whisper_out_enabled
            and settings.whisper_out_interval > 0
            and count % settings.whisper_out_interval == 0):
        transcript = _resolve_transcript_path(session_id)
        if transcript:
            _spawn_background_store(transcript, cwd, session_id)

    sys.exit(0)


def _resolve_transcript_path(session_id: str) -> Path | None:
    """Find a transcript JSONL for a session ID across supported clients."""
    if not session_id:
        return None

    claude_projects = Path("~/.claude/projects").expanduser()
    if claude_projects.is_dir():
        matches = sorted(claude_projects.glob(f"*/{session_id}.jsonl"))
        if matches:
            return matches[0]

    codex_sessions = Path("~/.codex/sessions").expanduser()
    if codex_sessions.is_dir():
        matches = sorted(codex_sessions.rglob(f"*{session_id}*.jsonl"))
        if matches:
            return matches[-1]

    return None


def _spawn_background_store(transcript_path: Path, cwd: str, session_id: str) -> None:
    """Fire-and-forget: spawn 'ormah whisper store' in background."""
    import shutil
    import subprocess

    ormah_bin = shutil.which("ormah") or "ormah"
    hook_json = json.dumps({
        "transcript_path": str(transcript_path),
        "cwd": cwd,
        "session_id": session_id,
    })
    try:
        subprocess.Popen(
            [ormah_bin, "whisper", "store"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        ).communicate(input=hook_json.encode(), timeout=1)
    except Exception:
        pass  # fire and forget


_WHISPER_CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))) / "ormah"
_NUDGE_COUNTER_FILE = _WHISPER_CACHE_DIR / "whisper-nudge-counters.json"
_LEGACY_CURSOR_FILE = _WHISPER_CACHE_DIR / "whisper-cursors.json"  # pre-ADR-0004, multi-session


def _load_nudge_counters() -> dict:
    try:
        return json.loads(_NUDGE_COUNTER_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_nudge_counters(counters: dict) -> None:
    try:
        _WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _NUDGE_COUNTER_FILE.write_text(json.dumps(counters))
    except OSError:
        pass


def _retire_legacy_cursor(session_id: str, path: str) -> None:
    """Drop only this transcript's key; delete the file once it is empty (council R10).

    whisper-cursors.json is MULTI-SESSION: the old hook keyed on either session_id or
    the transcript path, so both are removed for this event only. Unlinking the whole
    file would wipe cursors for sessions that have not yet migrated to the server.
    """
    try:
        cursors = json.loads(_LEGACY_CURSOR_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(cursors, dict):
        return
    for key in (session_id, path):  # the old code keyed on either
        cursors.pop(key, None)
    try:
        if cursors:
            _LEGACY_CURSOR_FILE.write_text(json.dumps(cursors))
        else:
            _LEGACY_CURSOR_FILE.unlink(missing_ok=True)
    except OSError:
        pass


_NUDGE_OUTBOX_FILE = _WHISPER_CACHE_DIR / "whisper-nudge-outbox.jsonl"
_NUDGE_OUTBOX_LOCK = _WHISPER_CACHE_DIR / "whisper-nudge-outbox.lock"
_OUTBOX_MAX_AGE_DAYS = 30
_OUTBOX_DRAIN_SECONDS = 5.0  # well under the 30s hook timeout
_OUTBOX_DRAIN_MAX = 20


@contextlib.contextmanager
def _outbox_lock():
    """Lock a STABLE file, never the outbox itself.

    flock locks an inode. The drain replaces the outbox path, so a locker holding the
    old inode would let an appender write into an unlinked file — losing the event
    (measured: 1140 mutual-exclusion violations vs 0 with a dedicated lock file).
    """
    _WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover - Windows: degraded, documented, never fatal
        yield
        return
    with open(_NUDGE_OUTBOX_LOCK, "a+") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _nudge_client() -> httpx.Client:
    """Short-timeout client for the hook (council R10): the manifest allows 30s TOTAL,
    so a single request must never be able to consume the whole budget."""
    return httpx.Client(base_url=BASE, timeout=5.0)


def _queue_nudge(path: str) -> str:
    """Append a boundary event durably and return its record id.

    Called BEFORE any network work; the id is what an ack removes (council R10).
    """
    rec_id = uuid.uuid4().hex
    try:
        with _outbox_lock():
            with open(_NUDGE_OUTBOX_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"id": rec_id, "path": path, "at": time.time()}) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
    except OSError as e:
        # Degraded mode (council R9): the boundary event is lost if the server is also
        # down. Say so on stderr — silent loss is what we are trying to avoid — but
        # never block or fail the hook.
        print(f"ormah: could not queue nudge: {e}", file=sys.stderr)
    return rec_id


def _rewrite_outbox(records: list[dict]) -> None:
    """Atomic rewrite. Caller MUST hold _outbox_lock()."""
    tmp = _NUDGE_OUTBOX_FILE.with_suffix(f".jsonl.tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, _NUDGE_OUTBOX_FILE)


def _read_outbox() -> list[dict]:
    """Caller MUST hold _outbox_lock(). Skips torn lines instead of crashing."""
    out = []
    try:
        for line in _NUDGE_OUTBOX_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except (FileNotFoundError, OSError):
        pass
    return out


def _unqueue_nudge(rec_id: str) -> None:
    """Drop ONE record after its own 202 — never every record for that path."""
    try:
        with _outbox_lock():
            _rewrite_outbox([r for r in _read_outbox() if r.get("id") != rec_id])
    except OSError:
        pass


def _drain_nudge_outbox(c) -> None:
    """Retry older queued nudges, oldest first, within a strict budget.

    Budgeted because an unbounded backlog with a slow client would outlive the hook
    itself (council R9). Whatever does not fit stays queued for the next fire. The
    network runs with NO lock held (council R10): read under the lock, release, do the
    requests, then re-take the lock and rewrite only the records still present.
    """
    deadline = time.monotonic() + _OUTBOX_DRAIN_SECONDS
    cutoff = time.time() - _OUTBOX_MAX_AGE_DAYS * 86400
    try:
        with _outbox_lock():  # phase (a): read, then RELEASE
            records = _read_outbox()
    except OSError:
        return

    acked, sent, seen = set(), 0, set()
    for rec in records:  # phase (b): network, NO lock held
        p, at, rid = rec.get("path"), rec.get("at", 0), rec.get("id")
        if not p or not rid:
            continue
        if at < cutoff or not Path(p).exists():
            acked.add(rid)  # expired / transcript gone
            continue
        if p in seen:
            # Only treat it as a duplicate when the earlier record for this path actually
            # got a 202. Marking it acked on a FAILED send would discard a newer boundary
            # that was never delivered.
            acked.add(rid)
            continue
        if sent >= _OUTBOX_DRAIN_MAX or time.monotonic() >= deadline:
            break  # out of budget: the rest stays queued
        sent += 1
        try:
            status = c.post(
                "/ingest/nudge", json={"path": p, "session_id": None}
            ).status_code
            if status == 202:
                acked.add(rid)
                seen.add(p)  # only NOW is a later record a duplicate
            elif status in (404, 422):
                # A permanently un-acceptable path must not occupy the drain budget for
                # 30 days and starve valid backlog behind it.
                acked.add(rid)
        except Exception:
            pass  # transient: keep it queued

    try:
        with _outbox_lock():  # phase (c): re-read, drop only acked ids
            _rewrite_outbox([r for r in _read_outbox() if r.get("id") not in acked])
    except OSError:
        pass


def cmd_whisper_store(args):
    """PreCompact/SessionEnd hook: pure nudge (ADR-0004). The server owns the cursor and
    does the extraction on its own schedule; this process never waits on it. Space,
    min-turns and safe-boundary logic all live server-side in _ingest_session now, which
    is why they are gone from here. The hook ALWAYS exits 0 (never block compaction)."""
    try:
        hook_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    transcript_path = hook_data.get("transcript_path", "")
    session_id = hook_data.get("session_id", "")
    if not transcript_path and session_id:
        resolved = _resolve_transcript_path(session_id)
        transcript_path = str(resolved) if resolved else ""
    if not transcript_path or not Path(transcript_path).exists():
        sys.exit(0)

    # council R9: make the CURRENT event durable before any network work — a slow or
    # backlogged drain must never be able to lose the boundary that just happened.
    rec_id = _queue_nudge(transcript_path)
    body = {"path": transcript_path, "session_id": session_id or None}
    accepted = False
    try:
        with _nudge_client() as c:  # SHORT timeout (5s), not the 30s _client()
            r = c.post("/ingest/nudge", json=body)
            accepted = r.status_code == 202
            if accepted:
                _unqueue_nudge(rec_id)  # remove THIS record, not every one for the path
            _drain_nudge_outbox(c)  # older entries, budgeted, no lock over the wire
    except Exception:
        accepted = False  # server down — the record stays queued
    if accepted:
        # Retire the legacy client cursor for THIS transcript only, and only once the
        # server has taken ownership of it (council R4 + R10). A 404/422/offline nudge
        # must leave it alone — it is the only record of what was already ingested — and
        # the file is MULTI-SESSION, so it is never unlinked wholesale.
        _retire_legacy_cursor(session_id, transcript_path)
    sys.exit(0)


def cmd_whisper_setup(args):
    """Generate Claude Code hook config for the whisper hook."""
    import shutil

    ormah_bin = shutil.which("ormah") or "ormah"
    hooks: dict = {
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{ormah_bin} whisper inject",
                        "timeout": 10,
                    }
                ]
            }
        ],
    }
    hooks["PreCompact"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"{ormah_bin} whisper store",
                    "timeout": 30,
                    "async": True,
                }
            ]
        }
    ]
    hooks["SessionEnd"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"{ormah_bin} whisper store",
                    "timeout": 30,
                }
            ]
        }
    ]
    hook_config = {"hooks": hooks}

    if args.glob:
        settings_path = os.path.expanduser("~/.claude/settings.json")
    else:
        settings_path = os.path.join(".claude", "settings.local.json")

    # Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(settings_path)), exist_ok=True)

    # Merge with existing settings if file exists
    existing = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass

    existing.update(hook_config)

    with open(settings_path, "w") as f:
        json.dump(existing, f, indent=2)
        f.write("\n")

    print(f"Wrote hook config to {settings_path}")
    print(json.dumps(hook_config, indent=2))


def main():
    p = argparse.ArgumentParser(
        prog="ormah-cli",
        description="Terminal interface to the ormah memory system.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # --- recall ---
    rec = sub.add_parser("recall", help="Search memories")
    rec.add_argument("query", help="Search query")
    rec.add_argument("--limit", type=int, help="Max results")
    rec.add_argument("--types", help="Comma-separated memory types to filter")
    rec.add_argument("--json", action="store_true", help="Output raw JSON")
    rec.add_argument("--space", help="Override space detection")
    rec.set_defaults(func=cmd_recall)

    # --- remember ---
    rem = sub.add_parser("remember", help="Store a memory")
    rem.add_argument("content", help="Memory content (use - for stdin)")
    rem.add_argument("--title", help="Short title")
    rem.add_argument("--type", default="fact", help="Memory type (default: fact)")
    rem.add_argument("--tier", default="working", help="Tier: core/working/archival (default: working)")
    rem.add_argument("--tags", help="Comma-separated tags")
    rem.add_argument("--about-self", action="store_true", help="Link to user identity")
    rem.add_argument("--space", help="Override space detection")
    rem.set_defaults(func=cmd_remember)

    # --- ingest ---
    ing = sub.add_parser("ingest", help="Ingest a conversation log")
    ing.add_argument("source", help="File path or - for stdin")
    ing.add_argument("--space", help="Override space detection")
    ing.set_defaults(func=cmd_ingest)

    # --- ingest-session ---
    ings = sub.add_parser("ingest-session", help="Ingest a Claude Code JSONL session transcript")
    ings.add_argument("path", help="Path to Claude Code JSONL transcript")
    ings.add_argument("--dry-run", action="store_true", help="Extract but don't store — print what would be ingested")
    ings.add_argument("--space", help="Override project space (default: auto-detect from cwd)")
    ings.add_argument("--min-turns", type=int, default=5, help="Minimum user turns with text to consider worth ingesting (default: 5)")
    ings.set_defaults(func=cmd_ingest_session)

    # --- node ---
    nd = sub.add_parser("node", help="Get a specific memory by ID")
    nd.add_argument("id", help="Memory UUID")
    nd.add_argument("--json", action="store_true", help="Output raw JSON")
    nd.set_defaults(func=cmd_node)

    # --- outdated ---
    out = sub.add_parser("outdated", help="Mark a memory as outdated")
    out.add_argument("id", help="Memory UUID")
    out.add_argument("--reason", help="Reason for marking outdated")
    out.set_defaults(func=cmd_outdated)

    # --- stats ---
    st2 = sub.add_parser("stats", help="Show memory store statistics")
    st2.add_argument("--json", action="store_true", help="Output raw JSON")
    st2.set_defaults(func=cmd_stats)

    # --- status ---
    st = sub.add_parser("status", help="Check server health")
    st.set_defaults(func=cmd_status)

    # --- whisper ---
    wh = sub.add_parser("whisper", help="Claude Code hook integration")
    wh_sub = wh.add_subparsers(dest="whisper_cmd", required=True)

    wh_inject = wh_sub.add_parser("inject", help="(internal) UserPromptSubmit hook — called automatically by Claude Code")
    wh_inject.set_defaults(func=cmd_whisper_inject)

    wh_store = wh_sub.add_parser("store", help="(internal) PreCompact/SessionEnd hook — called automatically by Claude Code")
    wh_store.set_defaults(func=cmd_whisper_store)

    wh_setup = wh_sub.add_parser("setup", help="Write Claude Code hook config to settings.json")
    wh_setup.add_argument("--global", dest="glob", action="store_true", help="Write to global ~/.claude/settings.json instead of local")
    wh_setup.set_defaults(func=cmd_whisper_setup)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
