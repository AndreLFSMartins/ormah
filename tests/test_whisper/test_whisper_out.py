"""Tests for whisper-out: the PreCompact/SessionEnd hook is a pure /ingest/nudge trigger.

ADR-0004: the hook no longer parses, min-turns-gates, space-detects or keeps a client
cursor. It queues the boundary event durably (an outbox), POSTs a nudge, and always exits
0. The server owns the cursor and does extraction on its own schedule.
"""

from __future__ import annotations

import io
import json
import multiprocessing as mp
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

import ormah.adapters.cli_adapter as cli
from ormah.adapters.cli_adapter import main


def _run_cli(args: list[str], monkeypatch, stdin_text: str | None = None):
    """Run the CLI with given args, returning (exit_code, stdout, stderr)."""
    monkeypatch.setattr("sys.argv", ["ormah-cli"] + args)
    if stdin_text is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))

    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)
    monkeypatch.setattr("sys.stderr", stderr)

    exit_code = 0
    try:
        main()
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 0

    return exit_code, stdout.getvalue(), stderr.getvalue()


def _mock_response(data, status_code=200):
    return httpx.Response(
        status_code=status_code,
        json=data,
        request=httpx.Request("POST", "http://test"),
    )


def _make_transcript(user_turns: int = 6) -> str:
    """Create a minimal JSONL transcript with the given number of user turns."""
    lines = []
    for i in range(user_turns):
        lines.append(json.dumps({
            "type": "user",
            "message": {"content": f"User message {i} about important architecture decisions"},
        }))
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"stop_reason": "end_turn",
                        "content": [{"type": "text", "text": f"Response {i} with details"}]},
        }))
    return "\n".join(lines) + "\n"


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Point the whisper cache (outbox, lock, counters, legacy cursor) at a temp dir so
    tests never touch the real ~/.cache/ormah. XDG_CACHE_HOME is set too, so child
    processes that re-import cli_adapter (spawn) resolve the SAME directory."""
    cache_home = tmp_path / "cache"
    cache_home.mkdir()
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    cache_dir = cache_home / "ormah"
    monkeypatch.setattr(cli, "_WHISPER_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cli, "_NUDGE_OUTBOX_FILE", cache_dir / "whisper-nudge-outbox.jsonl")
    monkeypatch.setattr(cli, "_NUDGE_OUTBOX_LOCK", cache_dir / "whisper-nudge-outbox.lock")
    monkeypatch.setattr(cli, "_NUDGE_COUNTER_FILE", cache_dir / "whisper-nudge-counters.json")
    monkeypatch.setattr(cli, "_LEGACY_CURSOR_FILE", cache_dir / "whisper-cursors.json")
    return cache_dir


def _mock_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        cli, "_nudge_client",
        lambda: httpx.Client(transport=transport, base_url="http://test"),
    )


def _outbox_records(cache_dir) -> list[dict]:
    p = cache_dir / "whisper-nudge-outbox.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


class TestWhisperStoreNudge:
    def test_whisper_store_posts_nudge(self, monkeypatch, tmp_path, _isolate_cache):
        """SessionEnd hook POSTs {path, session_id} to /ingest/nudge and exits 0 — no
        content, no parse, no cursor file."""
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(_make_transcript(6))

        captured = []

        def handler(request):
            captured.append(request)
            return _mock_response({"status": "accepted"}, status_code=202)

        _mock_client(monkeypatch, handler)

        hook_input = json.dumps({
            "transcript_path": str(transcript),
            "cwd": str(tmp_path),
            "session_id": "abc",
        })
        code, _, _ = _run_cli(["whisper", "store"], monkeypatch, stdin_text=hook_input)

        assert code == 0
        assert len(captured) == 1
        assert str(captured[0].url).endswith("/ingest/nudge")
        assert json.loads(captured[0].content) == {"path": str(transcript), "session_id": "abc"}
        # No legacy cursor file is ever created by the pure nudge.
        assert not (_isolate_cache / "whisper-cursors.json").exists()
        # Its own record was removed on the 202 — nothing left queued.
        assert _outbox_records(_isolate_cache) == []

    def test_whisper_store_exits_zero_when_server_down(self, monkeypatch, tmp_path, _isolate_cache):
        """Server unreachable -> exit 0 silently AND the path is queued in the outbox."""
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(_make_transcript(6))

        def handler(request):
            raise httpx.ConnectError("Connection refused")

        _mock_client(monkeypatch, handler)

        hook_input = json.dumps({"transcript_path": str(transcript), "session_id": "abc"})
        code, _, _ = _run_cli(["whisper", "store"], monkeypatch, stdin_text=hook_input)

        assert code == 0
        recs = _outbox_records(_isolate_cache)
        assert [r["path"] for r in recs] == [str(transcript)]

    def test_current_event_is_queued_before_any_network_call(
        self, monkeypatch, tmp_path, _isolate_cache
    ):
        """council R9: the current boundary must be durable BEFORE the POST. Simulate the
        hook being killed mid-request and assert the outbox already holds this transcript."""
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(_make_transcript(6))

        class _KillClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **k):
                raise SystemExit(0)

        monkeypatch.setattr(cli, "_nudge_client", lambda: _KillClient())

        hook_input = json.dumps({"transcript_path": str(transcript), "session_id": "abc"})
        code, _, _ = _run_cli(["whisper", "store"], monkeypatch, stdin_text=hook_input)

        assert code == 0
        recs = _outbox_records(_isolate_cache)
        assert [r["path"] for r in recs] == [str(transcript)]

    def test_drain_is_budgeted_and_cannot_starve_the_current_event(
        self, monkeypatch, tmp_path, _isolate_cache
    ):
        """council R9: with many queued entries, the current transcript is queued and
        POSTed FIRST, and the drain stops at _OUTBOX_DRAIN_MAX leaving the rest queued."""
        monkeypatch.setattr(cli, "_OUTBOX_DRAIN_MAX", 3)
        monkeypatch.setattr(cli, "_OUTBOX_DRAIN_SECONDS", 100.0)  # isolate the count budget

        # Seed 10 older entries, each a real existing transcript.
        _isolate_cache.mkdir(parents=True, exist_ok=True)
        seeded = []
        with (_isolate_cache / "whisper-nudge-outbox.jsonl").open("w") as fh:
            for i in range(10):
                t = tmp_path / f"old-{i}.jsonl"
                t.write_text(_make_transcript(2))
                seeded.append(str(t))
                fh.write(json.dumps({"id": f"seed-{i}", "path": str(t), "at": time.time()}) + "\n")

        current = tmp_path / "current.jsonl"
        current.write_text(_make_transcript(6))

        captured = []

        def handler(request):
            captured.append(json.loads(request.content)["path"])
            return _mock_response({"status": "accepted"}, status_code=202)

        _mock_client(monkeypatch, handler)

        hook_input = json.dumps({"transcript_path": str(current), "session_id": "cur"})
        code, _, _ = _run_cli(["whisper", "store"], monkeypatch, stdin_text=hook_input)

        assert code == 0
        assert captured[0] == str(current)          # current event went first
        assert len(captured) == 1 + 3               # current + exactly DRAIN_MAX drained
        remaining = {r["path"] for r in _outbox_records(_isolate_cache)}
        assert len(remaining) == 7                  # the rest stayed queued
        assert str(current) not in remaining        # the current event was acked, not left

    def test_entry_removed_only_on_its_own_202(self, monkeypatch, tmp_path, _isolate_cache):
        """council R9: a mixed response map (202 for A, 500 for B) removes A and keeps B —
        removal is never batch-wide."""
        a = tmp_path / "a.jsonl"
        a.write_text(_make_transcript(2))
        b = tmp_path / "b.jsonl"
        b.write_text(_make_transcript(2))

        _isolate_cache.mkdir(parents=True, exist_ok=True)
        with (_isolate_cache / "whisper-nudge-outbox.jsonl").open("w") as fh:
            fh.write(json.dumps({"id": "id-a", "path": str(a), "at": time.time()}) + "\n")
            fh.write(json.dumps({"id": "id-b", "path": str(b), "at": time.time()}) + "\n")

        current = tmp_path / "current.jsonl"
        current.write_text(_make_transcript(6))

        def handler(request):
            path = json.loads(request.content)["path"]
            if path == str(b):
                return _mock_response({"status": "error"}, status_code=500)
            return _mock_response({"status": "accepted"}, status_code=202)

        _mock_client(monkeypatch, handler)

        hook_input = json.dumps({"transcript_path": str(current), "session_id": "cur"})
        code, _, _ = _run_cli(["whisper", "store"], monkeypatch, stdin_text=hook_input)

        assert code == 0
        remaining = [r["path"] for r in _outbox_records(_isolate_cache)]
        assert remaining == [str(b)]                # only the 500 stayed queued

    @pytest.mark.skipif(cli.fcntl is None, reason="POSIX fcntl unavailable (degraded mode)")
    def test_concurrent_append_during_drain_is_not_lost(self, monkeypatch, _isolate_cache):
        """council R9 (the inode trap): a drain that rewrites the outbox via os.replace
        must not swallow a concurrent append, because both take the STABLE lock file."""
        _isolate_cache.mkdir(parents=True, exist_ok=True)
        appends = 60
        rewrites = 60
        barrier = mp.Barrier(2)

        appender = mp.Process(target=_concurrent_appender, args=(barrier, appends))
        drainer = mp.Process(target=_concurrent_drainer, args=(barrier, rewrites))
        appender.start()
        drainer.start()
        appender.join(30)
        drainer.join(30)
        assert not appender.is_alive() and not drainer.is_alive()

        paths = {r["path"] for r in _outbox_records(_isolate_cache)}
        expected = {f"/append/{i}" for i in range(appends)}
        assert expected <= paths            # not one appended record was lost

    def test_outbox_is_drained_on_the_next_fire(self, monkeypatch, tmp_path, _isolate_cache):
        """A queued nudge is re-sent (and removed) on the next fire; a vanished file is
        dropped without a POST; a still-valid entry and the new path are POSTed."""
        gone = tmp_path / "gone.jsonl"
        gone.write_text(_make_transcript(2))
        old = tmp_path / "old.jsonl"
        old.write_text(_make_transcript(2))

        _isolate_cache.mkdir(parents=True, exist_ok=True)
        with (_isolate_cache / "whisper-nudge-outbox.jsonl").open("w") as fh:
            fh.write(json.dumps({"id": "id-gone", "path": str(gone), "at": time.time()}) + "\n")
            fh.write(json.dumps({"id": "id-old", "path": str(old), "at": time.time()}) + "\n")

        gone.unlink()  # transcript vanished after it was queued

        new = tmp_path / "new.jsonl"
        new.write_text(_make_transcript(6))

        posted = []

        def handler(request):
            posted.append(json.loads(request.content)["path"])
            return _mock_response({"status": "accepted"}, status_code=202)

        _mock_client(monkeypatch, handler)

        hook_input = json.dumps({"transcript_path": str(new), "session_id": "new"})
        code, _, _ = _run_cli(["whisper", "store"], monkeypatch, stdin_text=hook_input)

        assert code == 0
        assert str(new) in posted
        assert str(old) in posted
        assert str(gone) not in posted                 # vanished file never POSTed
        assert _outbox_records(_isolate_cache) == []   # everything acked/dropped

    def test_whisper_store_exits_zero_on_missing_transcript(self, monkeypatch, _isolate_cache):
        """No transcript_path and unresolvable session_id -> exit 0, no HTTP, no queue."""
        monkeypatch.setattr(cli, "_resolve_transcript_path", lambda session_id: None)

        def handler(request):  # pragma: no cover - must never be called
            raise AssertionError("no HTTP call expected")

        _mock_client(monkeypatch, handler)

        hook_input = json.dumps({"session_id": "no-such-session"})
        code, _, _ = _run_cli(["whisper", "store"], monkeypatch, stdin_text=hook_input)

        assert code == 0
        assert not (_isolate_cache / "whisper-nudge-outbox.jsonl").exists()

    def test_legacy_cursor_key_removed_only_after_202(self, monkeypatch, tmp_path, _isolate_cache):
        """council R4 + R10: on 202 ONLY this session's key leaves whisper-cursors.json;
        other sessions survive. On 422 nothing is removed at all."""
        _isolate_cache.mkdir(parents=True, exist_ok=True)
        cursor_file = _isolate_cache / "whisper-cursors.json"
        cursor_file.write_text(json.dumps({"sess-A": 100, "sess-B": 200}))

        ta = tmp_path / "a.jsonl"
        ta.write_text(_make_transcript(6))

        def ok_handler(request):
            return _mock_response({"status": "accepted"}, status_code=202)

        _mock_client(monkeypatch, ok_handler)
        _run_cli(
            ["whisper", "store"], monkeypatch,
            stdin_text=json.dumps({"transcript_path": str(ta), "session_id": "sess-A"}),
        )

        assert cursor_file.exists()
        assert json.loads(cursor_file.read_text()) == {"sess-B": 200}

        # A 422 nudge for sess-B must leave its cursor untouched.
        tb = tmp_path / "b.jsonl"
        tb.write_text(_make_transcript(6))

        def rejected_handler(request):
            return _mock_response({"detail": "outside watched dirs"}, status_code=422)

        _mock_client(monkeypatch, rejected_handler)
        _run_cli(
            ["whisper", "store"], monkeypatch,
            stdin_text=json.dumps({"transcript_path": str(tb), "session_id": "sess-B"}),
        )

        assert json.loads(cursor_file.read_text()) == {"sess-B": 200}


# --- module-level workers for the multiprocessing concurrency test (must be picklable) ---


def _concurrent_appender(barrier, n):
    import ormah.adapters.cli_adapter as _cli

    barrier.wait()
    for i in range(n):
        _cli._queue_nudge(f"/append/{i}")


def _concurrent_drainer(barrier, n):
    import ormah.adapters.cli_adapter as _cli

    barrier.wait()
    for _ in range(n):
        _cli._unqueue_nudge("no-such-id")  # pure read + os.replace rewrite under the lock


class TestResolveTranscriptPath:
    def test_resolve_transcript_path_prefers_claude_exact_match(self, monkeypatch, tmp_path):
        claude_root = tmp_path / ".claude" / "projects" / "proj"
        claude_root.mkdir(parents=True)
        transcript = claude_root / "sess-123.jsonl"
        transcript.write_text(_make_transcript(1))

        monkeypatch.setenv("HOME", str(tmp_path))

        from ormah.adapters.cli_adapter import _resolve_transcript_path

        assert _resolve_transcript_path("sess-123") == transcript

    def test_resolve_transcript_path_finds_codex_rollout_file(self, monkeypatch, tmp_path):
        codex_root = tmp_path / ".codex" / "sessions" / "2026" / "04" / "02"
        codex_root.mkdir(parents=True)
        transcript = codex_root / "rollout-2026-04-02T17-34-35-sess-456.jsonl"
        transcript.write_text(_make_transcript(1))

        monkeypatch.setenv("HOME", str(tmp_path))

        from ormah.adapters.cli_adapter import _resolve_transcript_path

        assert _resolve_transcript_path("sess-456") == transcript


class TestIngestEndpointExtraTags:
    def test_ingest_endpoint_extra_tags(self, engine):
        """HTTP test: extra_tags query param applied to created memories."""
        fake_llm_response = json.dumps({
            "memories": [
                {
                    "content": "The project uses SQLite for storage",
                    "type": "fact",
                    "title": "SQLite storage",
                    "tags": ["architecture"],
                },
            ]
        })
        with patch("ormah.background.llm_client.ingest_llm_generate", return_value=fake_llm_response):
            result = engine.ingest_conversation(
                content="A conversation about database choices and architecture." * 10,
                extra_tags=["whisper-out"],
            )

        assert isinstance(result, list)
        assert len(result) == 1
        node_id = result[0]["node_id"]

        node = engine.file_store.load(node_id)
        assert node is not None
        assert "whisper-out" in node.tags
        assert "auto-ingested" in node.tags


class TestWhisperSetup:
    def test_whisper_setup_includes_precompact(self, monkeypatch, tmp_path):
        """Setup generates both UserPromptSubmit and PreCompact hooks when whisper_out_enabled.

        HOME is isolated: `whisper setup --global` WRITES to ~/.claude/settings.json."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(
            "ormah.adapters.cli_adapter.settings",
            MagicMock(port=8787, whisper_out_enabled=True),
        )

        code, out, err = _run_cli(["whisper", "setup", "--global"], monkeypatch)

        assert code == 0
        assert "PreCompact" in out
        assert "UserPromptSubmit" in out

    def test_whisper_setup_always_registers_precompact(self, monkeypatch, tmp_path):
        """Setup always registers PreCompact hook (runtime flag gates execution, not
        registration). HOME is isolated: --global writes to ~/.claude/settings.json."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(
            "ormah.adapters.cli_adapter.settings",
            MagicMock(port=8787, whisper_out_enabled=False, whisper_out_min_turns=5),
        )

        code, out, err = _run_cli(["whisper", "setup", "--global"], monkeypatch)

        assert code == 0
        assert "PreCompact" in out
        assert "UserPromptSubmit" in out
