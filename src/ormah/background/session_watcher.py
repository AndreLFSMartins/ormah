"""Session watcher — auto-ingest completed agent JSONL transcripts."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Event, Lock, Thread, Timer

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ormah.background.ingest_spool import IngestSpool, root_key, spool_root
from ormah.background.llm_client import (
    cancel_active_llm_calls,
    ingest_provider_configured,
    resume_llm_adapters,
)
from ormah.engine.memory_engine import (
    EXTRACT_ERR_CALL_FAILED,
    EXTRACT_ERR_NO_PROVIDER,
    MemoryEngine,
)
from ormah.text.tokens import distinctive_tokens
from ormah.transcript.parser import TranscriptResult, TranscriptTurn, parse_transcript, should_rewind

logger = logging.getLogger(__name__)


class IngestResult(Enum):
    """Why an ingest attempt did/didn't commit, so reconcile parks only files that cannot
    progress (corrupt / frozen safe boundary) and never parks transient external failures."""
    OK = "ok"                    # committed new content
    NO_PROGRESS = "no_progress"  # nothing new at the safe boundary, or unparseable (file's fault) -> park-eligible
    TRANSIENT = "transient"      # external failure (engine error) or defer -> retry, never park

_STATE_FILENAME = ".session_watcher_state"
MAX_EXTRACT_FAILURES = 3  # per-slice extraction failures (provider present) before skipping it
_HEURISTIC_SOURCE = "transcript_watcher_heuristic"
_LLM_JUDGE_SOURCE = "transcript_watcher_llm_judge"
_HEURISTIC_AFFINITY_SOURCE = "auto_heuristic"
_LLM_JUDGE_AFFINITY_SOURCE = "auto_llm_judge"
_DEFAULT_SESSION_WATCHER_DIR = Path("~/.claude/projects")
_CODEX_SESSION_WATCHER_DIR = Path("~/.codex/sessions")

_LLM_FEEDBACK_JUDGE_PROMPT = """\
You are judging retrieval feedback for Ormah, a memory system.

Given a user prompt, the assistant response, and memories that Ormah injected before the
assistant answered, decide whether each memory was actually useful retrieval context.

Verdicts:
- "used": the assistant response materially uses, cites, paraphrases, or relies on the memory.
- "irrelevant": the memory is clearly unrelated/noisy for this prompt and response.
- "uncertain": there is not enough evidence either way. Silence alone is uncertain, not irrelevant.

Rules:
- Do not mark a memory "used" just because it shares generic words with the response.
- Do not mark a memory "irrelevant" just because the assistant omitted it.
- Use "irrelevant" only when the memory is plainly off-topic for the user's prompt and answer.
- Prefer "uncertain" when the judgment is ambiguous.

Return strict JSON matching this shape:
{
  "verdicts": [
    {
      "whisper_log_id": 123,
      "verdict": "used|irrelevant|uncertain",
      "confidence": 0.0
    }
  ]
}
"""


def _normalise_text(text: str) -> str:
    """Lowercase text and collapse punctuation/whitespace for matching."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", text.lower())
    return " ".join(cleaned.split())


def _assistant_response_after_prompt(
    turns: list[TranscriptTurn],
    prompt_text: str | None,
) -> str | None:
    """Return assistant text immediately following the matching user prompt."""
    if not prompt_text:
        return None

    wanted = _normalise_text(prompt_text)
    if not wanted:
        return None

    for idx, turn in enumerate(turns):
        if turn.role != "user" or _normalise_text(turn.text) != wanted:
            continue

        responses: list[str] = []
        for next_turn in turns[idx + 1:]:
            if next_turn.role == "user":
                break
            if next_turn.role == "assistant":
                responses.append(next_turn.text)
        return "\n\n".join(responses) if responses else None

    return None


def _node_usage_evidence(row, response_text: str) -> tuple[bool, float, dict]:
    """Detect whether an assistant response clearly referenced an injected memory."""
    response_norm = _normalise_text(response_text)
    response_tokens = distinctive_tokens(response_text, extra_stop_words={"memory", "ormah"})

    node_id = row["node_id"]
    short_id = node_id[:8] if node_id else ""
    if short_id and short_id.lower() in response_text.lower():
        return True, 1.0, {"match": "node_id", "short_id": short_id}

    title = row["title"] or ""
    title_tokens = distinctive_tokens(title, extra_stop_words={"memory", "ormah"})
    title_norm = _normalise_text(title)
    if len(title_tokens) >= 2 and len(title_norm) >= 12 and title_norm in response_norm:
        return True, 0.95, {"match": "title", "title": title}

    content = row["content"] or ""
    for sentence in re.split(r"[\n.!?]+", content):
        sentence = sentence.strip()
        if len(sentence) < 24:
            continue
        sentence_tokens = distinctive_tokens(sentence, extra_stop_words={"memory", "ormah"})
        sentence_norm = _normalise_text(sentence)
        if len(sentence_tokens) >= 4 and sentence_norm in response_norm:
            return True, 0.9, {"match": "sentence", "text": sentence[:160]}

    node_tokens = distinctive_tokens(
        f"{title} {content}",
        extra_stop_words={"memory", "ormah"},
    )
    prompt_tokens = distinctive_tokens(row["prompt_text"] or "")
    candidate_tokens = node_tokens - prompt_tokens
    overlap = sorted(candidate_tokens & response_tokens)
    denominator = min(len(candidate_tokens), 12)
    overlap_ratio = (len(overlap) / denominator) if denominator else 0.0
    if len(overlap) >= 4 and overlap_ratio >= 0.5:
        return True, min(0.85, 0.45 + overlap_ratio), {
            "match": "token_overlap",
            "overlap": overlap[:12],
            "overlap_ratio": round(overlap_ratio, 3),
        }

    return False, 0.0, {
        "match": "none",
        "overlap": overlap[:12],
        "overlap_ratio": round(overlap_ratio, 3),
    }


def _normalise_judge_verdict(raw: object) -> str:
    """Map loose LLM verdict labels to the canonical feedback verdicts."""
    value = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"used", "useful", "referenced", "positive", "relevant"}:
        return "used"
    if value in {
        "irrelevant",
        "clearly_irrelevant",
        "not_useful",
        "negative",
        "noisy",
        "noise",
    }:
        return "irrelevant"
    return "uncertain"


def _confidence(raw: object) -> float:
    """Parse and clamp an LLM confidence value into [0.0, 1.0]."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def _llm_feedback_judge_response_format() -> dict:
    """Return the compact structured-output schema for whisper feedback judgments."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "whisper_feedback_verdicts",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "verdicts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "whisper_log_id": {"type": "integer"},
                                "verdict": {
                                    "type": "string",
                                    "enum": ["used", "irrelevant", "uncertain"],
                                },
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "required": ["whisper_log_id", "verdict", "confidence"],
                        },
                    },
                },
                "required": ["verdicts"],
            },
        },
    }


def _feedback_llm_judge_enabled(engine: MemoryEngine) -> bool:
    settings = engine.settings
    return bool(
        getattr(settings, "feedback_llm_judge_enabled", False)
        and getattr(settings, "llm_enabled", False)
    )


def _llm_judge_whisper_usage(
    engine: MemoryEngine,
    prompt_text: str,
    response_text: str,
    rows: list,
) -> dict[int, dict]:
    """Ask the configured LLM to judge ambiguous whisper usage for one turn."""
    if not rows:
        return {}

    from ormah.background.llm_client import extract_json, llm_generate

    candidates = [
        {
            "whisper_log_id": row["id"],
            "node_id": (row["node_id"] or "")[:8],
            "title": row["title"] or "",
            "content": (row["content"] or "")[:1200],
        }
        for row in rows
    ]
    payload = {
        "user_prompt": (prompt_text or "")[:2500],
        "assistant_response": response_text[:5000],
        "memories": candidates,
    }
    prompt = (
        _LLM_FEEDBACK_JUDGE_PROMPT
        + "\n\nInput JSON:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    raw = llm_generate(
        engine.settings,
        prompt,
        json_mode=True,
        response_format=_llm_feedback_judge_response_format(),
        temperature=0,
        max_tokens=512,
    )
    if raw is None:
        return {}

    try:
        parsed = json.loads(extract_json(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("LLM returned invalid JSON for feedback judgment")
        return {}

    verdicts = parsed.get("verdicts") if isinstance(parsed, dict) else parsed
    if not isinstance(verdicts, list):
        return {}

    judgments: dict[int, dict] = {}
    valid_ids = {int(row["id"]) for row in rows}
    for item in verdicts:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("whisper_log_id", item.get("id"))
        try:
            whisper_log_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if whisper_log_id not in valid_ids:
            continue

        verdict = _normalise_judge_verdict(item.get("verdict"))
        confidence = _confidence(item.get("confidence"))
        judgments[whisper_log_id] = {
            "verdict": verdict,
            "confidence": confidence,
            "reason": str(item.get("reason") or "")[:500],
        }

    return judgments


def _insert_usage_signal(
    conn,
    row,
    transcript: TranscriptResult,
    *,
    signal_type: str,
    polarity: int,
    strength: float,
    source: str,
    evidence: dict,
    created: str,
) -> int:
    conn.execute(
        """
        INSERT INTO signals
            (
                whisper_log_id, node_id, signal_type, polarity, strength,
                source, session_id, agent_id, surface, space, prompt_hash,
                evidence, created
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            row["id"],
            row["node_id"],
            signal_type,
            polarity,
            strength,
            source,
            row["session_id"],
            transcript.source,
            "transcript_watcher",
            row["space"],
            row["prompt_hash"],
            json.dumps(evidence, sort_keys=True),
            created,
        ),
    )
    return conn.execute("SELECT changes()").fetchone()[0]


def _insert_affinity(
    conn,
    row,
    *,
    signal: int,
    source: str,
    confirmed_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO affinity
            (
                prompt_vec, prompt_text, node_id, signal, source,
                confirmed_at, space, session_id, whisper_log_id
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            row["prompt_vec"],
            row["prompt_text"],
            row["node_id"],
            signal,
            source,
            confirmed_at,
            row["space"],
            row["session_id"],
            row["id"],
        ),
    )


def _record_whisper_usage_signals(
    engine: MemoryEngine,
    transcript: TranscriptResult,
    turns: list | None = None,
) -> int:
    """Mine transcript responses for clear usage of injected whisper memories.

    *turns* restricts mining to a subset of ``transcript.turns`` (e.g. only the
    closed/safe blocks of an active session, so a still-growing assistant response
    is not judged from a partial body). Defaults to all turns.
    """
    if turns is None:
        turns = transcript.turns
    llm_judge_enabled = _feedback_llm_judge_enabled(engine)
    rows = engine.db.conn.execute(
        """
        SELECT
            wl.id, wl.node_id,
            COALESCE(re.prompt_text, wl.prompt_text) AS prompt_text,
            COALESCE(re.prompt_hash, wl.prompt_hash) AS prompt_hash,
            COALESCE(re.prompt_vec, wl.prompt_vec) AS prompt_vec,
            COALESCE(re.session_id, wl.session_id) AS session_id,
            COALESCE(re.space, wl.space) AS space,
            n.title, n.content,
            (
                SELECT s.polarity FROM signals s
                WHERE s.whisper_log_id = wl.id
                  AND s.source = ?
                ORDER BY s.id DESC
                LIMIT 1
            ) AS heuristic_polarity,
            EXISTS (
                SELECT 1 FROM signals s
                WHERE s.whisper_log_id = wl.id
                  AND s.source = ?
            ) AS has_llm_judge
        FROM whisper_log wl
        LEFT JOIN retrieval_events re ON re.id = wl.retrieval_event_id
        JOIN nodes n ON n.id = wl.node_id
        WHERE wl.session_id = ?
          AND wl.was_injected = 1
        ORDER BY wl.logged_at ASC, wl.id ASC
        """,
        (_HEURISTIC_SOURCE, _LLM_JUDGE_SOURCE, transcript.session_id),
    ).fetchall()
    if not rows:
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    recorded = 0

    heuristic_records: list[dict] = []
    llm_groups: dict[tuple[str, str], list] = {}
    response_cache: dict[str, str | None] = {}
    for row in rows:
        prompt_text = row["prompt_text"] or ""
        if prompt_text not in response_cache:
            response_cache[prompt_text] = _assistant_response_after_prompt(
                turns,
                prompt_text,
            )
        response = response_cache[prompt_text]
        if response is None:
            continue

        heuristic_polarity = row["heuristic_polarity"]
        has_heuristic = heuristic_polarity is not None
        has_llm_judge = bool(row["has_llm_judge"])

        referenced = False
        if not has_heuristic:
            referenced, strength, evidence = _node_usage_evidence(row, response)
            signal_type = "whisper_referenced" if referenced else "whisper_unreferenced"
            polarity = 1 if referenced else 0
            heuristic_records.append({
                "row": row,
                "signal_type": signal_type,
                "polarity": polarity,
                "strength": strength,
                "evidence": {
                    **evidence,
                    "detector": _HEURISTIC_SOURCE,
                    "response_chars": len(response),
                },
            })
        else:
            referenced = int(heuristic_polarity) == 1

        if llm_judge_enabled and not has_llm_judge and not referenced:
            llm_groups.setdefault((prompt_text, response), []).append(row)

    with engine.db.transaction() as conn:
        for record in heuristic_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_HEURISTIC_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] == 1:
                _insert_affinity(
                    conn,
                    row,
                    signal=1,
                    source=_HEURISTIC_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )

    if not llm_groups:
        return recorded

    judge_records: list[dict] = []
    min_confidence = getattr(engine.settings, "feedback_llm_judge_min_confidence", 0.75)
    for (prompt_text, response), group_rows in llm_groups.items():
        judgments = _llm_judge_whisper_usage(engine, prompt_text, response, group_rows)
        for row in group_rows:
            judgment = judgments.get(int(row["id"]))
            if judgment is None:
                continue

            verdict = judgment["verdict"]
            confidence = judgment["confidence"]
            promoted = confidence >= min_confidence and verdict in {"used", "irrelevant"}
            polarity = 0
            signal_type = "whisper_judged_uncertain"
            if promoted and verdict == "used":
                polarity = 1
                signal_type = "whisper_judged_used"
            elif promoted and verdict == "irrelevant":
                polarity = -1
                signal_type = "whisper_judged_irrelevant"

            judge_records.append({
                "row": row,
                "signal_type": signal_type,
                "polarity": polarity,
                "strength": confidence,
                "evidence": {
                    "detector": _LLM_JUDGE_SOURCE,
                    "verdict": verdict,
                    "confidence": confidence,
                    "min_confidence": min_confidence,
                    "reason": judgment["reason"],
                    "promoted": promoted,
                    "response_chars": len(response),
                },
            })

    with engine.db.transaction() as conn:
        for record in judge_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_LLM_JUDGE_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] in (1, -1):
                _insert_affinity(
                    conn,
                    row,
                    signal=record["polarity"],
                    source=_LLM_JUDGE_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )

    return recorded


def _is_subagent_transcript(path: Path) -> bool:
    """True for subagent transcripts (Claude Code writes them under ``<uuid>/subagents/``).

    Skipped for cost and redundancy, not for low value: a subagent transcript is large
    (often ~10x a normal session), so ingesting one would burn many extraction calls, and
    its deliverable already reaches the store through the parent session's tool-result — only
    the intermediate tool-call noise is dropped. Matches a ``subagents`` segment at any depth
    so nested layouts are covered too.
    """
    return "subagents" in path.parts


def _space_from_encoded_dir(dirname: str) -> str | None:
    """Extract project space from an encoded transcript directory name.

    Claude Code uses paths like ``-Users-johndoe-Projects-ormah``.
    The current compatibility strategy uses the last ``-`` segment as
    the project name; future transcript sources should provide their
    own space strategy before reaching the watcher.
    Leading ``-`` is stripped before splitting.
    """
    stripped = dirname.lstrip("-")
    if not stripped:
        return None
    parts = stripped.split("-")
    return parts[-1] if parts else None


def _resolve_transcript_session_id(
    engine: MemoryEngine,
    path: Path,
    parsed_session_id: str,
    source: str,
) -> str:
    """Resolve source-specific transcript filenames back to hook session ids.

    Claude Code transcript filenames are the session id. Codex rollout filenames can embed
    the hook session id inside a longer filename, so use recent whisper_log rows to recover
    the id that was used when whispers were injected.
    """
    if not parsed_session_id:
        return parsed_session_id

    exact = engine.db.conn.execute(
        "SELECT 1 FROM whisper_log WHERE session_id = ? LIMIT 1",
        (parsed_session_id,),
    ).fetchone()
    if exact is not None:
        return parsed_session_id

    if source != "codex":
        return parsed_session_id

    row = engine.db.conn.execute(
        """
        SELECT session_id
        FROM whisper_log
        WHERE session_id IS NOT NULL
          AND session_id != ''
          AND length(session_id) >= 6
          AND ? LIKE '%' || session_id || '%'
        ORDER BY length(session_id) DESC, logged_at DESC, id DESC
        LIMIT 1
        """,
        (path.name,),
    ).fetchone()
    return row["session_id"] if row is not None else parsed_session_id


def _space_from_whisper_log(engine: MemoryEngine, session_id: str) -> str | None:
    """Return the most recent non-empty space logged for a whisper session."""
    if not session_id:
        return None

    row = engine.db.conn.execute(
        """
        SELECT space
        FROM whisper_log
        WHERE session_id = ?
          AND space IS NOT NULL
          AND space != ''
        ORDER BY logged_at DESC, id DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    return row["space"] if row is not None else None


def _space_for_transcript(
    engine: MemoryEngine,
    path: Path,
    result: TranscriptResult,
) -> str | None:
    """Choose the project space for a parsed transcript."""
    logged_space = _space_from_whisper_log(engine, result.session_id)
    if logged_space:
        return logged_space

    if result.source == "claude_code":
        return _space_from_encoded_dir(path.parent.name)

    return None


def _expand_watch_dir(path: Path) -> Path:
    return Path(path).expanduser().resolve()


def _default_acceptance_roots() -> list[Path]:
    """The standard hook locations a nudge may target regardless of discovery config.

    Patchable (council R10/D8): a nudge is an explicit user request, so a path under the
    default Claude or Codex root is accepted even when a custom ``session_watcher_dir``
    replaced the discovery defaults — otherwise every ``~/.codex/sessions`` transcript
    would get a permanent 422. Tests patch this to ``[]`` so the suite never builds watches
    over the real ``~/.claude`` / ``~/.codex`` on a dev machine.
    """
    return [
        _expand_watch_dir(_DEFAULT_SESSION_WATCHER_DIR),
        _expand_watch_dir(_CODEX_SESSION_WATCHER_DIR),
    ]


def _configured_watch_roots(settings) -> list[Path]:
    """Discovery roots for the current settings, WITHOUT an ``exists()`` filter (council
    R4/R5), so an absent configured dir still yields a handler and a later nudge for a
    transcript under it is accepted instead of 422'd forever."""
    primary = _expand_watch_dir(settings.session_watcher_dir)
    roots = [primary]
    if primary == _expand_watch_dir(_DEFAULT_SESSION_WATCHER_DIR):
        roots.append(_expand_watch_dir(_CODEX_SESSION_WATCHER_DIR))
    return roots


def _is_nested_or_equal(a: Path, b: Path) -> bool:
    """True when ``a`` is ``b`` or lives inside ``b``."""
    return a == b or b in a.parents


def _resolve_acceptance_roots(settings) -> list[tuple[Path, bool]]:
    """Return ``(root, discover)`` for every root a nudge may target.

    Separate "where I discover" from "what I accept" (council R10/R11):
      - Discovery roots (``_configured_watch_roots``) get an Observer and a reconcile sweep,
        but only while ``session_watcher_enabled`` is true.
      - Acceptance roots = discovery ∪ the default Claude/Codex roots. Every acceptance root
        gets a handler + spool so ``/ingest/nudge`` can be honoured, but an acceptance-only
        root is never swept (``discover=False``) — sweeping it would ingest transcripts under
        a directory the user deliberately swapped out.

    Roots are deduplicated by resolved path, and any root nested under (or containing) a root
    already kept is collapsed away, so one transcript can never get two cursors — the ADR's
    single-cursor invariant. Discovery roots are considered first so they win the collapse
    and keep their ``discover`` flag.
    """
    enabled = bool(settings.session_watcher_enabled)
    discovery = _configured_watch_roots(settings)
    discovery_set = set(discovery)
    ordered = discovery + [r for r in _default_acceptance_roots() if r not in discovery_set]

    kept: list[tuple[Path, bool]] = []
    for root in ordered:
        if any(
            _is_nested_or_equal(root, k) or _is_nested_or_equal(k, root) for k, _ in kept
        ):
            continue
        kept.append((root, enabled and root in discovery_set))
    return kept


def _file_hash(path: Path) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_state(watch_dir: Path) -> dict:
    """Load persisted state for the watch directory."""
    state_path = watch_dir / _STATE_FILENAME
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupted session watcher state file %s, starting fresh", state_path)
    return {}


def _save_state(watch_dir: Path, state: dict) -> None:
    """Persist state atomically — a torn ``write_text`` would discard every cursor in this
    dir (``_load_state`` treats corrupt JSON as "start fresh"), and with an always-on worker
    a concurrent reader is the norm, not the exception (measured: 7081 torn reads on a direct
    write vs 0 via ``os.replace``). Stage in a per-pid tmp file, fsync it, then rename it into
    place; fsync the directory so the rename itself survives a crash."""
    state_path = watch_dir / _STATE_FILENAME
    tmp = state_path.with_suffix(state_path.suffix + f".tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, state_path)
    with contextlib.suppress(OSError):  # durability of the rename itself, best-effort
        dir_fd = os.open(state_path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _commit_state(state: dict, rel: str, entry: dict, state_lock, watch_dir: Path) -> None:
    """Write one state entry and persist, honoring the optional cross-thread lock."""
    if state_lock is not None:
        with state_lock:
            state[rel] = entry
            _save_state(watch_dir, state)
    else:
        state[rel] = entry
        _save_state(watch_dir, state)


def _should_flush(is_idle: bool, capped: bool) -> bool:
    """A Batch closes once idle, or once the parser filled a full flush_bytes batch.

    Gating on ``capped`` (not ``pending >= flush_bytes``) matters: break-before capping
    guarantees a multi-turn slice's pending bytes stay BELOW flush_bytes, so a
    byte-threshold comparison would never fire for the common multi-turn case. ``capped``
    is the parser's own "a full batch is ready, more closed content remains" signal.
    """
    return is_idle or capped


def _ingest_session(
    engine: MemoryEngine,
    path: Path,
    state: dict,
    watch_dir: Path,
    min_turns: int,
    idle_threshold: float = 600.0,
    flush_bytes: int = 60000,
    on_defer_active=None,
    state_lock=None,
    boundary: int | None = None,
    force_flush: bool = False,
) -> IngestResult:
    """Ingest a single JSONL session transcript if changed.

    ``boundary`` is the accepted EOF the drain forwards from the spool job (ADR-0004 Task 3).
    When present it does two narrow things, and nothing else: (1) it is an absolute
    ``stop_offset`` ceiling passed to EVERY parse in this lane — the happy path, the
    orphan-recovery rewind probe, and the rewind re-parse — so ingestion never reads past the
    bytes the nudge measured (PreCompact nudges a LIVE, still-growing session); (2) it
    FORCE-FLUSHES, bypassing ONLY the idle-threshold and the ``min_turns`` gate, so a short
    just-ended session is not stranded. It must NOT touch the safe-boundary rule or any
    cap/quarantine rule: an ended session is final, but a response still being written must
    never be split from its prompt.

    Returns:
        IngestResult.OK         — new content was committed.
        IngestResult.NO_PROGRESS — nothing to commit at the safe boundary (file is frozen,
                                   corrupt, or already fully consumed). The drain completes an
                                   empty delta, or dead-letters an idle file whose bytes never
                                   reach a safe boundary.
        IngestResult.TRANSIENT  — external failure (engine error, in-flight defer, or below
                                   min_turns while active); the drain requeues with backoff.
    """
    if _is_subagent_transcript(path):
        return IngestResult.NO_PROGRESS
    rel = str(path.relative_to(watch_dir))

    try:
        h = _file_hash(path)
    except OSError as e:
        logger.warning("Cannot read %s: %s", path, e)
        return IngestResult.TRANSIENT
    try:
        size = path.stat().st_size
    except OSError as e:
        logger.warning("Cannot stat %s: %s", path, e)
        return IngestResult.TRANSIENT

    # Incremental: only parse the turns appended since the last ingest.
    existing = state.get(rel)
    prev_offset = existing.get("end_offset", 0) if existing else 0
    # Skip an unchanged file only if the previous ingest already consumed it whole. A stored
    # offset behind EOF means a pending tail or a legacy mid-response cursor still to process,
    # which must be re-parsed (so recovery can run) even when the hash is unchanged.
    if existing and existing.get("hash") == h and prev_offset >= size:
        return IngestResult.NO_PROGRESS
    if prev_offset > size:
        prev_offset = 0  # file shrank (compaction/rewrite) -> re-ingest whole

    # Two INDEPENDENT effects of a nudge, decoupled (council-pr F3): the `boundary`
    # stop_offset ceiling applies to EVERY producer's job (never read past accepted bytes),
    # but the FORCE-FLUSH intent (bypass idle + min_turns) belongs ONLY to an explicit nudge.
    # Deriving force_flush from `boundary is not None` leaked the bypass to Observer/reconcile
    # jobs (which also carry a boundary), fragmenting active sessions. The caller now passes
    # force_flush from the job's reason; boundary keeps pinning the ceiling for all jobs.
    try:
        result = parse_transcript(
            path, start_offset=prev_offset, max_bytes=flush_bytes, stop_offset=boundary
        )
        if should_rewind(result, prev_offset):
            # Orphan with NO forward progress: a genuine cursor left mid-response by an
            # older version. Re-parse the whole file so the dropped tail is re-paired with
            # its prompt. With forward progress the orphan is a false positive (ADR-0003,
            # #149): the fragment is dropped and the cursor advances — rewinding there
            # would re-ingest the whole file on every tick forever.
            original_offset = prev_offset
            logger.info("Session watcher recovering legacy mid-response cursor for %s", rel)
            prev_offset = 0
            # Uncapped probe: decide progress on the true whole-file boundary. A capped
            # re-parse can stop before the parked cursor even when recoverable closed
            # content exists past it, which would mis-park a recoverable file forever.
            # The stop_offset ceiling still applies: the recovery path must honour the same
            # accepted boundary as the happy path, or it becomes the consent leak.
            result = parse_transcript(path, start_offset=0, stop_offset=boundary)
            if result.safe_end_offset <= original_offset:
                # The rewind itself made no progress: the "orphan" tail is a still-open
                # in-flight response, not a recoverable one. ADR-0003: a no-progress
                # transcript parks, it does not re-extract the closed prefix every tick.
                return IngestResult.NO_PROGRESS
            # There is something to recover: drain capped as usual so the ingest slice
            # honours flush_bytes; later ticks continue incrementally from the new cursor.
            result = parse_transcript(
                path, start_offset=0, max_bytes=flush_bytes, stop_offset=boundary
            )
    except Exception as e:
        logger.warning("Session transcript parse error for %s: %s", path, e)
        return IngestResult.NO_PROGRESS

    # Commit only the "safe" payload — the closed boundary, content proven complete by a
    # terminal stop_reason (Claude Code), a Codex task_complete event, or a following user
    # turn. This never splits a multi-record response from its prompt. A trailing block
    # with no completion signal yet is genuinely in-flight and is held back; once it
    # completes the file changes and the next parse picks it up. (A response left forever
    # in-flight — a process killed mid-turn — is intentionally never ingested.)
    payload_offset = result.safe_end_offset
    payload_conversation = result.safe_conversation
    payload_users = result.safe_user_turn_count
    payload_turns = result.safe_turns

    # When the file looks idle/finished, commit whatever is closed even below flush_bytes,
    # so a short finished session is not stranded.
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        age = idle_threshold + 1  # treat unstatable file as idle
    is_idle = age > idle_threshold

    # Salience: don't extract from a below-threshold window unless the session is finished (idle).
    # A short but complete session is still captured; a short ACTIVE window defers to accumulate.
    # A nudge force-flushes: a SessionEnd/PreCompact on a short session is an explicit ask, so
    # the min_turns accumulation gate does not apply.
    if not is_idle and not force_flush and payload_users < min_turns:
        if on_defer_active is not None:
            on_defer_active()
        return IngestResult.TRANSIENT

    # Nothing new to commit at the closed boundary.
    if payload_offset <= prev_offset:
        # Active session with appended-but-unclosed content (a still-streaming response):
        # schedule a retry so the turn is committed once it completes.
        if not is_idle and result.end_offset > prev_offset and on_defer_active is not None:
            on_defer_active()
            return IngestResult.TRANSIENT  # will grow; retry, never park
        return IngestResult.NO_PROGRESS   # idle/frozen safe boundary -> park-eligible

    # Batch gate: flush once idle, or once the parser filled a full flush_bytes batch
    # (result.capped). Below that, defer so a Batch accumulates instead of round-tripping
    # the LLM per turn. A nudge force-flushes past this too: it authorised these exact bytes.
    if not force_flush and not _should_flush(is_idle, result.capped):
        if on_defer_active is not None:
            on_defer_active()  # schedule a retry so the tail is not lost
        return IngestResult.TRANSIENT

    result.session_id = _resolve_transcript_session_id(
        engine,
        path,
        result.session_id,
        result.source,
    )
    space = _space_for_transcript(engine, path, result)
    signals_recorded = _record_whisper_usage_signals(engine, result, turns=payload_turns)

    provider_on = ingest_provider_configured(engine.settings)

    def _record_extract_failure(reason: str) -> IngestResult:
        """Per-slice failure cap: a deterministically un-processable slice would otherwise pin the
        byte-cursor forever (every retry re-parses the same slice, re-fails, never advances). Count
        failures at this offset (persisted, so it survives restarts); once capped, SKIP the slice
        forward and record the loss durably (not just a log line) so it can be replayed. Shared by
        the extract-error-string path and the ingest-exception path so a deterministic non-string
        failure cannot pin the cursor either (council-pr I1)."""
        fail_count = (
            existing.get("extract_fail_count", 0) + 1
            if existing and existing.get("extract_fail_offset") == prev_offset
            else 1
        )
        if fail_count >= MAX_EXTRACT_FAILURES:
            skip_entry = dict(existing or {})
            skipped_slices = list(skip_entry.get("skipped_slices", []))
            skipped_slices.append({
                "start": prev_offset,
                "end": payload_offset,
                "source_hash": h,
                "reason": reason,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            skip_entry.update({
                "hash": h,
                "end_offset": payload_offset,  # advance past the toxic slice
                "last_ingested": datetime.now(timezone.utc).isoformat(),
                "session_id": result.session_id,
                "source": result.source,
                "space": space,
                "skipped_slices": skipped_slices,
            })
            skip_entry.pop("extract_fail_offset", None)
            skip_entry.pop("extract_fail_count", None)
            _commit_state(state, rel, skip_entry, state_lock, watch_dir)
            logger.error(
                "Session watcher SKIPPING un-processable slice for %s after %d failures (%s): "
                "cursor %d->%d, %d chars dropped (observable data loss)",
                rel, fail_count, reason, prev_offset, payload_offset, payload_offset - prev_offset,
            )
            # The cursor advanced -> progress, like a successful empty extraction. If more
            # closed content remains past this slice, drain it now instead of waiting for the
            # next reconcile tick (mirror the success path below).
            if result.capped and on_defer_active is not None:
                on_defer_active()
            return IngestResult.OK
        # Not yet capped: persist the counter (cursor stays) and retry.
        fail_entry = dict(existing or {})
        fail_entry.update({
            "hash": h,
            "end_offset": prev_offset,  # cursor unchanged; slice will be retried
            "extract_fail_offset": prev_offset,
            "extract_fail_count": fail_count,
        })
        _commit_state(state, rel, fail_entry, state_lock, watch_dir)
        return IngestResult.TRANSIENT

    try:
        ingested = engine.ingest_conversation(
            content=payload_conversation,
            space=space,
            agent_id=result.source,
            extra_tags=["session-transcript"],
        )
    except sqlite3.OperationalError as e:
        # A locked DB (WAL contention with the background scheduler) or a transient disk error is
        # RETRYABLE — it resolves on a later tick. Never count it toward the cap: doing so would
        # permanently skip a slice that would have committed once the lock cleared (council-pr H2).
        # Some OperationalErrors are deterministic (a broken schema) — treating those as transient
        # too is deliberate (council-pr M): a broken DB should stall LOUDLY (a warning every tick,
        # no data loss), never silently skip data the way capping would. Loud stall > silent loss.
        logger.warning("Session watcher transient storage error for %s: %s", path, e)
        return IngestResult.TRANSIENT
    except OSError as e:
        # Filesystem-level transient failure — same reasoning as the SQLite lock above.
        logger.warning("Session watcher transient I/O error for %s: %s", path, e)
        return IngestResult.TRANSIENT
    except Exception as e:
        logger.warning("Session watcher ingestion error for %s: %s", path, e)
        # A DETERMINISTIC exception (e.g. a memory whose content always breaks a write) would pin
        # the cursor forever, re-calling the LLM every tick — count it toward the per-slice cap so
        # it skips after MAX_EXTRACT_FAILURES. Transient storage/IO errors are handled above and
        # never reach here. Reaching here means extraction produced memories -> provider on (I1).
        if not provider_on:
            return IngestResult.TRANSIENT
        return _record_extract_failure("ingest_exception_x3")

    if isinstance(ingested, str):
        # Provider-wide failures — no provider, or the LLM call itself failed (binary missing, auth,
        # network, timeout -> raw is None) — resolve when the provider recovers, so they must NEVER
        # burn the slice. Counting them would skip every slice during an outage after the cap = mass
        # silent loss (council-pr H1). Only a SLICE-SPECIFIC failure (the LLM responded but its
        # content was unparseable/invalid) is deterministic and counts toward the per-slice cap —
        # this is the class that caused the original 1393x loop (a parse failure), still guarded.
        if ingested in (EXTRACT_ERR_NO_PROVIDER, EXTRACT_ERR_CALL_FAILED):
            logger.warning("Session watcher extraction deferred (provider-wide) for %s: %s",
                           path, ingested)
            return IngestResult.TRANSIENT
        logger.warning("Session watcher ingestion failed (slice-specific) for %s: %s", path, ingested)
        return _record_extract_failure("extract_failed_x3")

    count = len(ingested) if isinstance(ingested, list) else 0

    new_node_ids = [m["node_id"] for m in ingested] if isinstance(ingested, list) else []
    # prev_offset == 0 means a fresh/whole re-ingest; don't carry stale cumulative
    # turns or node_ids forward (the new ingest re-covers them).
    carry = existing and prev_offset > 0
    prev_node_ids = existing.get("node_ids", []) if carry else []
    prev_turns = existing.get("user_turns", 0) if carry else 0

    # Carry forward durable state (esp. skipped_slices — the quarantine trail) when advancing
    # incrementally. Building the entry from scratch wiped skipped_slices, so the first successful
    # slice after a capped one destroyed the durable loss record (council-pr C1). A fresh whole
    # re-ingest (prev_offset == 0, carry False) legitimately starts clean — those byte ranges are
    # being re-read, so any prior quarantine of them is stale.
    entry = dict(existing) if carry else {}
    entry.update({
        "hash": h,
        "end_offset": payload_offset,
        "last_ingested": datetime.now(timezone.utc).isoformat(),
        "session_id": result.session_id,
        "source": result.source,
        "space": space,
        "user_turns": prev_turns + payload_users,
        "node_ids": prev_node_ids + new_node_ids,
        "signals_recorded": signals_recorded,
    })
    entry.pop("extract_fail_offset", None)  # a success at this offset clears the retry counter
    entry.pop("extract_fail_count", None)
    _commit_state(state, rel, entry, state_lock, watch_dir)

    logger.info(
        "Session watcher ingested %s (%d new turns, %d memories extracted, %d signals recorded)",
        rel, payload_users, count, signals_recorded,
    )
    if result.capped and on_defer_active is not None:
        # The parse stopped at the byte cap with more closed content past payload_offset —
        # retrigger the retry timer so the next slice drains promptly instead of waiting
        # for the next file-append event or reconcile tick.
        on_defer_active()
    return IngestResult.OK


class SessionHandler(FileSystemEventHandler):
    """Watches for .jsonl file create/modify events with debouncing."""

    def __init__(
        self,
        engine: MemoryEngine,
        watch_dir: Path,
        debounce_seconds: float,
        min_turns: int,
        idle_threshold: float = 600.0,
        lookback_hours: int = 72,
        retry_seconds: float = 30.0,
        flush_bytes: int = 60000,
        stop_event: Event | None = None,
        spool: "IngestSpool | None" = None,
    ) -> None:
        self.engine = engine
        self.watch_dir = watch_dir
        self.debounce_seconds = debounce_seconds
        self.min_turns = min_turns
        self.idle_threshold = idle_threshold
        self.lookback_hours = lookback_hours
        self.retry_seconds = retry_seconds
        self.flush_bytes = flush_bytes
        self.spool = spool
        self._state = _load_state(watch_dir)
        self._timers: dict[str, Timer] = {}
        self._ingesting: set[str] = set()
        self._lock = Lock()
        self._state_lock = Lock()
        self._stop_event = stop_event or Event()
        # Always-on drain worker (ADR-0004): one serial consumer owns _ingesting and the
        # state lock; producers (Observer, reconcile, /ingest/nudge) only enqueue.
        self._wake = Event()
        self._drain_thread: Thread | None = None
        self._idle_poll_seconds = 2.0  # belt-and-braces: covers any missed wake() signal
        # Idle-branch recover() only reclaims running/ claims older than this, so it never
        # steals a legitimately in-flight claim or races a fresh requeue's two-copy window
        # (council-pr R3 F3). Longer than any healthy _run_job extraction; orphans are rare.
        self._recover_stale_seconds = 60.0

    # --- Producer side: the Observer debounces file events into the spool -----------------

    def _schedule_enqueue(self, path: Path) -> None:
        """Debounce a file event, then ENQUEUE (never ingest) so the single drain owns
        extraction. The debounce belongs here — on the producer — not on the drain."""
        if self._stop_event.is_set() or self.spool is None:
            return
        key = str(path)
        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
            timer = Timer(self.debounce_seconds, self._enqueue_path, args=(path, "observer"))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _enqueue_path(self, path: Path, reason: str) -> None:
        """Enqueue the file at its current EOF and wake the drain. The claim/dedup is the
        spool's; a boundary already queued is never lowered (Task 1)."""
        with self._lock:
            self._timers.pop(str(path), None)
        if self._stop_event.is_set() or self.spool is None:
            return
        try:
            boundary = path.stat().st_size
        except OSError:
            return
        # force_flush=False: the Observer/idle-retry lane is discovery, never an explicit ask;
        # it must respect min_turns/idle so an active session is not fragmented (council-pr R2).
        self.spool.enqueue(path, boundary=boundary, reason=reason, force_flush=False)
        self.wake()

    # --- Consumer side: the one serial drain thread ---------------------------------------

    def start_drain(self) -> None:
        """Start the always-on drain worker. Call after ``spool.recover()``."""
        self._drain_thread = Thread(
            target=self._drain_forever, daemon=True,
            name=f"ingest-drain-{self.watch_dir.name}",
        )
        self._drain_thread.start()

    def wake(self) -> None:
        """Signal that the spool has work. Never blocks — the request path calls this."""
        self._wake.set()

    def join_drain(self, timeout: float | None = None) -> None:
        if self._drain_thread is not None:
            self._drain_thread.join(timeout)

    def drain_alive(self) -> bool:
        """True while the drain thread is still running (ADR-0004 slice 2 shutdown fence)."""
        return self._drain_thread is not None and self._drain_thread.is_alive()

    def _drain_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self.spool.claim_next()
            except Exception as e:  # a broken spool must not kill the worker
                logger.warning("Ingest drain claim error on %s: %s", self.watch_dir, e)
                job = None
            if job is None:
                # council-pr R2 F1: a job orphaned in running/ (a requeue that itself failed on
                # an FS fault, below) is invisible to claim_next, which scans only pending/, and
                # startup recover() will not run again until the NEXT restart. Sweep STALE
                # running/ claims back to pending/ here so they self-heal live. Age-gated
                # (council-pr R3 F3): only claims older than _recover_stale_seconds are reclaimed,
                # so this never steals a legitimately in-flight claim (another process sharing the
                # spool, #150) nor races a fresh requeue's sub-ms two-copy window. recover()
                # no-ops on an empty running/ (the steady state) -- a cheap listdir per idle tick.
                with contextlib.suppress(Exception):
                    self.spool.recover(min_age_seconds=self._recover_stale_seconds)
                self._wake.wait(timeout=self._idle_poll_seconds)
                self._wake.clear()
                continue
            try:
                self._run_job(job)
            except Exception as e:  # one bad job must not kill the worker
                logger.warning("Ingest drain run error on %s: %s", self.watch_dir, e)
                # council-pr F2: the job was already claimed into running/ by claim_next.
                # An unexpected error here (OSError from _commit_state/complete, an
                # _ingest_session raise, ...) would otherwise strand it in running/ until the
                # NEXT restart's recover() -- the live drain only scans pending/. Requeue it
                # as an EXTERNAL failure (persisted backoff), retried forever, never
                # dead-lettered (H1: an unexpected error is treated as transient). Guard the
                # double-dispose: if _run_job already completed/requeued the job its running/
                # file is gone, so resurrecting it would duplicate-extract -- skip then. A
                # requeue that itself raises must not kill the worker either.
                with contextlib.suppress(Exception):
                    if job._file.exists():
                        self.spool.requeue(job, failure_class="external")

    @contextlib.contextmanager
    def _ingesting_guard(self, path: Path):
        """The single in-flight marker, so ``in_flight_count`` (shutdown drain) sees the
        one running extraction and ``stop_session_watcher`` waits it out."""
        key = str(path)
        with self._lock:
            self._ingesting.add(key)
        try:
            yield
        finally:
            with self._lock:
                self._ingesting.discard(key)

    def _run_job(self, job) -> None:
        """The ONE place a transcript is ingested. Owns the guard and the state lock, so
        there is exactly one writer per path and one writer of the cursor regardless of how
        many producers enqueued it."""
        if self._stop_event.is_set():
            # Shutting down: refuse before touching the engine (use-after-close guard, #52).
            # The job stays claimed in running/ and spool.recover() requeues it next start.
            return
        path = job.path
        rel = str(path.relative_to(self.watch_dir))
        # Force-flush is the explicit nudge's intent, persisted on the job and read back here
        # -- NEVER re-derived from job.reason (council-pr R2 F4: deriving it from a shared
        # "drain" reason force-flushed every producer's capped remainder, including Observer's).
        # Observer and reconcile jobs pass the boundary CEILING but do NOT force-flush, so an
        # active, below-min_turns session keeps accumulating instead of fragmenting per event.
        force_flush = job.force_flush
        with self._ingesting_guard(path):
            result = _ingest_session(
                self.engine, path, self._state, self.watch_dir, self.min_turns,
                idle_threshold=self.idle_threshold, flush_bytes=self.flush_bytes,
                boundary=job.boundary, force_flush=force_flush, state_lock=self._state_lock,
            )
        if result is IngestResult.TRANSIENT:
            # External failure class -> retried forever with persisted backoff, never
            # dead-lettered: an outage must not discard accepted work (ADR-0004 H1).
            self.spool.requeue(job, failure_class="external")
            return
        if result is IngestResult.OK:
            if (self._state.get(rel, {}).get("end_offset") or 0) < job.boundary:
                # Capped batch: the boundary is not drained yet. ENQUEUE the remainder
                # FIRST, COMPLETE SECOND (council R12) — the reverse order loses the intent
                # if the process dies between the two calls; a duplicate job is a no-op.
                # The continuation INHERITS this job's force_flush (council-pr R2 F4): an
                # Observer's remainder stays non-forcing, a nudge's remainder stays forcing.
                self.spool.enqueue(
                    path, boundary=job.boundary, reason="drain", force_flush=job.force_flush
                )
            self.spool.complete(job)
            return
        # NO_PROGRESS: the closed delta at the safe boundary is empty.
        if self._idle_with_unsafe_tail(path, rel, job.boundary):
            # An idle transcript whose bytes never reach a safe boundary (a single
            # unterminated turn): completing would strand those bytes forever. Advance the
            # cursor past the frozen prefix so the sweep stops re-selecting it, and keep a
            # dead-letter record with a distinct reason (slice 3 owns the real policy) —
            # never a silent complete.
            self._mark_frozen_prefix_consumed(path, rel, job.boundary)
            self.spool.requeue(job, failure_class="no_safe_boundary")
            return
        self.spool.complete(job)

    def _idle_with_unsafe_tail(self, path: Path, rel: str, boundary: int | None = None) -> bool:
        """True when the file is idle, has bytes past the cursor, yet the parser closes
        nothing there (a single unterminated turn). Non-idle files keep being retried
        (re-enqueued as they grow); an unparseable/empty delta is the file's own fault.

        The parse honours the accepted ``boundary`` as a ``stop_offset`` ceiling (council-pr
        F1): a still-growing session can have bytes past the boundary that the nudge never
        accepted, and examining them here would decide "frozen" on unaccepted content."""
        try:
            st = path.stat()
        except OSError:
            return False
        if time.time() - st.st_mtime <= self.idle_threshold:
            return False
        cursor = self._state.get(rel, {}).get("end_offset") or 0
        if st.st_size <= cursor:
            return False
        try:
            parsed = parse_transcript(path, start_offset=cursor, stop_offset=boundary)
        except Exception:
            return False
        return parsed.safe_end_offset <= cursor

    def _mark_frozen_prefix_consumed(
        self, path: Path, rel: str, boundary: int | None = None
    ) -> None:
        """Advance the cursor over a dead-lettered frozen prefix so reconcile stops
        re-selecting it — but NEVER past the accepted ``boundary`` (council-pr F1), and NEVER
        BACKWARD past the current cursor (council-pr R2 F2). Jumping to raw EOF would mark bytes
        [boundary, size] consumed even though no nudge accepted them; writing a boundary below
        the current cursor (a stale/out-of-order job) would rewind it and re-open already-
        consumed bytes for duplicate extraction. If the file later grows past a new, higher
        boundary, that new nudge re-opens the remainder for examination."""
        try:
            size = path.stat().st_size
        except OSError:
            return
        cursor = self._state.get(rel, {}).get("end_offset") or 0
        target = min(boundary, size) if boundary is not None else size
        if target <= cursor:
            # stale/out-of-order boundary, or nothing new to skip -- monotonic: never rewind.
            return
        entry = dict(self._state.get(rel, {}))
        entry["end_offset"] = target
        _commit_state(self._state, rel, entry, self._state_lock, self.watch_dir)

    def cancel_pending_timers(self) -> None:
        """Cancel debounce/retry timers that have not fired yet (shutdown)."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    def in_flight_count(self) -> int:
        """Number of ingests that have claimed a file and not yet released it."""
        with self._lock:
            return len(self._ingesting)

    def reconcile(self) -> int:
        """Disk-truth safety net, now a PRODUCER: ENQUEUE (never ingest) transcripts the
        live FSEvents path dropped, so the one serial drain still owns extraction.

        A stat-only scan finds files that still need work — never-seen (within lookback) or a
        state cursor behind EOF — and enqueues at most
        ``session_watcher_reconcile_max_per_tick`` of them, OLDEST-first by mtime (D3: the
        producer-side cap preserves both the per-tick budget and the no-starvation guard; the
        serial drain paces consumption, this cap paces production so one sweep of a 10k-file
        backlog cannot enqueue 10k jobs at once). ``enqueue`` is idempotent per (path,
        boundary), so re-sweeping a still-pending file is a no-op. Returns the number enqueued.

        Gated by the caller on the per-watch ``discover`` flag — an acceptance-only root is
        never swept.
        """
        if self.spool is None:
            return 0
        cutoff = time.time() - (self.lookback_hours * 3600) if self.lookback_hours > 0 else 0
        cap = self.engine.settings.session_watcher_reconcile_max_per_tick
        candidates: list[tuple[float, Path, int]] = []
        for jsonl_file in self.watch_dir.rglob("*.jsonl"):
            if _is_subagent_transcript(jsonl_file):
                continue
            try:
                st = jsonl_file.stat()
            except OSError:
                continue
            rel = str(jsonl_file.relative_to(self.watch_dir))
            entry = self._state.get(rel)
            if entry is None:
                # Never-seen: mirror the lookback catch-up rules below.
                if self.lookback_hours < 0:
                    continue  # catch-up disabled -> skip never-seen files
                if cutoff > 0 and st.st_mtime < cutoff:
                    continue
            elif (entry.get("end_offset") or 0) >= st.st_size:
                continue  # fully consumed -> skip cheaply
            # else: seen with cursor behind EOF -> pending/failed tail (or a grown file).
            candidates.append((st.st_mtime, jsonl_file, st.st_size))
        # Oldest-first: the longest-waiting transcript is enqueued before newer ones, so a
        # steady drip of fresh files cannot indefinitely defer an older one past the cap.
        candidates.sort(key=lambda t: t[0])
        enqueued = 0
        for _mtime, jsonl_file, size in candidates[:cap]:
            # force_flush=False: reconcile is a disk-truth safety net, not an explicit ask --
            # it must respect min_turns/idle so it never fragments an active session (R2 F4).
            self.spool.enqueue(jsonl_file, boundary=size, reason="reconcile", force_flush=False)
            enqueued += 1
        if enqueued:
            self.wake()
            logger.info(
                "Session watcher reconcile enqueued %d transcript(s) the live path missed",
                enqueued,
            )
        return enqueued

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".jsonl"):
            path = Path(event.src_path)
            if not _is_subagent_transcript(path):
                self._schedule_enqueue(path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".jsonl"):
            path = Path(event.src_path)
            if not _is_subagent_transcript(path):
                self._schedule_enqueue(path)


@dataclass
class SessionWatch:
    """A live watch root: its directory, always-on handler + spool, and — only when this root
    is a discovery root and the watcher is enabled — a swappable Observer."""
    watch_dir: Path
    handler: SessionHandler
    observer: "Observer | None"
    spool: "IngestSpool"
    discover: bool = False


def _run_startup_discovery(handler: SessionHandler) -> None:
    """One reconcile sweep at startup so a discovery root does not wait a full reconcile
    interval after a restart to re-enqueue transcripts whose cursor is behind EOF.

    ``reconcile`` only ENQUEUES (no DB writes), so this may run on a daemon thread off the
    bind path — the original bind-blocking bug was the old catch-up scan ingesting
    synchronously.
    """
    try:
        handler.reconcile()
    except Exception as e:  # a bad backlog file must not crash the startup thread
        logger.warning("Session watcher startup discovery error for %s: %s", handler.watch_dir, e)


def start_session_watcher(engine: MemoryEngine) -> list[SessionWatch]:
    """Build the always-on ingest worker for every acceptance root and return the watches.

    Each root gets a handler + spool + drain thread unconditionally (the worker is always on,
    so ``/ingest/nudge`` is honoured even when the watcher is disabled). A discovery root that
    is enabled additionally gets an Observer and a startup discovery sweep. Crash recovery is
    ``spool.recover()`` — microseconds — not a startup tree walk.
    """
    s = engine.settings
    roots = _resolve_acceptance_roots(s)
    if not roots:
        logger.warning("Session watcher: no watch root resolved from %s", s.session_watcher_dir)
        return []

    stop_event = Event()
    watches: list[SessionWatch] = []
    try:
        for watch_dir, discover in roots:
            try:
                # Our own watch root: create it if absent (council R4/R5) so a later nudge is
                # accepted, not 422'd forever. Skip only a root whose creation raises.
                watch_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("Session watcher: cannot create watch root %s: %s", watch_dir, e)
                continue
            spool = IngestSpool(spool_root(s) / root_key(watch_dir))
            requeued = spool.recover()  # BEFORE the drain thread starts
            if requeued:
                logger.info("Recovered %d in-flight ingest job(s) on %s", requeued, watch_dir)
            handler = SessionHandler(
                engine, watch_dir, s.session_watcher_debounce_seconds, s.session_watcher_min_turns,
                s.session_watcher_idle_threshold, s.session_watcher_lookback_hours,
                retry_seconds=s.session_watcher_retry_seconds,
                flush_bytes=s.session_watcher_flush_bytes,
                stop_event=stop_event, spool=spool,
            )
            handler.start_drain()  # the always-on worker
            # HIGH-B (council R1, Codex): register the PROVISIONAL watch (observer=None) BEFORE
            # observer.start() — so a failing observer.start() below still leaves this root's
            # already-draining handler inside `watches`. Without this, the rollback except-block
            # can never join_drain() it (an orphan drain thread could then touch the DB after
            # engine.shutdown() closes it, #52). The observer is filled in only once started.
            watch = SessionWatch(
                watch_dir=watch_dir, handler=handler, observer=None,
                spool=spool, discover=discover,
            )
            watches.append(watch)
            observer = None
            if discover:
                observer = Observer()
                observer.schedule(handler, str(watch_dir), recursive=True)
                # M-3: assign onto the watch BEFORE start() — watchdog can spin up emitter
                # threads before raising, and a raise here must still leave `watch.observer`
                # populated so the rollback's _stop_and_drain stops/joins it instead of
                # leaking a half-started Observer.
                watch.observer = observer
                observer.start()
                # Off-bind startup sweep so a restart re-enqueues a behind-EOF cursor now,
                # not one reconcile interval later. reconcile is DB-free, so daemon is safe.
                Thread(
                    target=_run_startup_discovery, args=(handler,),
                    name="ormah-session-startup-discovery", daemon=True,
                ).start()
            logger.info("Ingest worker started on %s (observer=%s)", watch_dir, bool(observer))
    except Exception:
        # Transactional startup: tear down everything already running — drain threads,
        # observers, timers, and any in-flight ingest — so a leaked, never-drained handler
        # cannot write to the DB after engine.shutdown() closes it. HIGH-A: the process keeps
        # serving after a caught rollback (main.lifespan), so re-arm any cancelled adapter.
        _stop_and_drain(watches, rearm=True)
        raise
    return watches


def _drain_handlers(handlers: list["SessionHandler"]) -> None:
    """Poll until no handler has an in-flight ingest, so nothing touches the DB after db.close().

    Uncapped: a deadline cap would abandon a running ingest and re-open the use-after-close window.
    A watchdog log every ~5s surfaces a stuck drain instead of a silent hang.
    """
    waited = 0.0
    while any(h.in_flight_count() > 0 for h in handlers):
        time.sleep(0.05)
        waited += 0.05
        if waited >= 5.0:
            n = sum(h.in_flight_count() for h in handlers)
            logger.warning("Session watcher shutdown still draining %d in-flight ingest(s)", n)
            waited = 0.0


def _stop_and_drain(watches: list[SessionWatch], *, rearm: bool = False) -> None:
    """Shared shutdown/rollback sequence (ADR-0004 slice 2): stop, cancel, drain, rearm.

    Cancelling in-flight LLM calls after ``wake()`` and before the join is what turns the
    previously-uncapped ``join_drain()`` wait (up to the provider timeout, ~40min at the Beta's
    sizing) into a bounded wait: a killed extraction raises ``LlmCancelledError``, which the
    engine maps to a provider-wide transient (never the per-slice failure cap — see
    ``memory_engine._extract_memories_llm``), so the slice is durably re-ingested on next boot.

    HIGH-C (council R2, Codex): a single timed cancel pass cannot see an adapter built AFTER
    the pass (a job that had already cleared ``_run_job``'s stop-check). Loop cancel + a bounded
    join until every drain thread has actually exited — a late-built adapter registers its Popen
    in time for the NEXT iteration's cancel, so shutdown is bounded by construction, not by a
    fixed number of passes.

    HIGH-3 (council-pr R3, Codex): ``cancel_active_llm_calls()`` is BEST-EFFORT and suppressed —
    the join fence after it is LOAD-BEARING and must never be skipped by a cancel failure (an
    un-joined orphan drain thread can touch the DB after ``engine.shutdown()``, #52). Accepted
    consequence: if cancellation fails systematically the drain stops being bounded by the cancel
    and is bounded only by the provider timeout again — strictly no worse than the pre-slice
    baseline, and the fence still runs.

    HIGH-A (council R1, Cursor): only the ROLLBACK caller passes ``rearm=True`` — the process
    keeps serving after a caught startup failure (``main.lifespan``), so leaving the adapters
    cancelled would poison every later maintenance/ingest LLM call until restart. A normal
    shutdown must NEVER rearm — the DB is about to close.
    """
    # HIGH-2 refine (council-pr R2, Codex): the ENTIRE drain body runs inside the try, so a raise
    # ANYWHERE in it (most directly an adapter's cancel_active() raising AFTER it set its cancel
    # flag) still rearms on the rollback path instead of leaving adapters permanently cancelled
    # while main.lifespan keeps serving. The raise is NOT swallowed — it propagates after the
    # finally runs (the rollback re-raises by design); we only guarantee rearm happened first.
    try:
        for w in watches:
            w.handler._stop_event.set()  # no NEW job starts (_run_job's stop-check refuses)
        for w in watches:
            if w.observer is not None:
                # HIGH-3: individually exception-safe. A provisional Observer whose start()
                # raised (HIGH-B assigns watch.observer BEFORE start()) is a never-started
                # thread; its stop()/join() can raise RuntimeError. One bad observer must not
                # abort the sequence before the rearm below.
                with contextlib.suppress(Exception):
                    w.observer.stop()
            w.handler.cancel_pending_timers()
            w.handler.wake()  # unblock the drain's idle wait so it exits promptly
        # HIGH-3 (council-pr R3, Codex): the cancel calls are BEST-EFFORT; the join fence below
        # is LOAD-BEARING. A raising cancel used to jump straight to the finally, skipping the
        # whole fence (join_drain / _drain_handlers / observer.join) and leaving an un-joined
        # orphan drain thread that can touch the DB after engine.shutdown() closes it (#52).
        try:
            cancelled = cancel_active_llm_calls()
            if cancelled:
                logger.info("Cancelled %d in-flight LLM call(s) for shutdown", cancelled)
        except Exception as e:
            logger.debug("Cancelling in-flight LLM calls for shutdown failed: %s", e)
        while any(w.handler.drain_alive() for w in watches):
            try:
                cancel_active_llm_calls()  # global (module-level adapter caches) -> also kills a
            except Exception as e:         # late-built adapter's fresh Popen on the NEXT iteration
                logger.debug("Cancelling in-flight LLM calls for shutdown failed: %s", e)
            for w in watches:
                w.handler.join_drain(timeout=0.2)
        _drain_handlers([w.handler for w in watches])  # in_flight_count()==0 -> returns at once
        for w in watches:
            if w.observer is not None:
                # HIGH-3: a never-started Observer thread raises RuntimeError("cannot join
                # thread before it is started"). Per-observer suppress/log so it can't escape.
                try:
                    w.observer.join(timeout=5)
                except Exception as e:
                    logger.debug("Observer join during shutdown failed: %s", e)
    finally:
        # HIGH-3/HIGH-2: rearm must ALWAYS run on the rollback path (rearm=True), whatever raised
        # above — otherwise main.lifespan keeps serving with adapters permanently cancelled
        # (ingest AND maintenance dead until restart). A normal shutdown NEVER rearms.
        if rearm:
            resume_llm_adapters()


def stop_session_watcher(watches: list[SessionWatch]) -> None:
    """Stop observers and fully drain in-flight ingests before returning.

    The lifespan calls engine.shutdown() (db.close()) right after this. The stop check in
    ``_run_job`` rejects NEW ingests; we stop the drain thread and wait for any in-flight
    ingest to finish, so nothing touches the DB after db.close(). The wait is NOT capped — a
    deadline cap would re-open the use-after-close window by abandoning a running ingest (#52).
    ``rearm`` stays False here (the default): the process is going away and the DB is about to
    close, so adapters must never be resumed on this path.
    """
    _stop_and_drain(watches)
    if watches:
        logger.info("Session watcher stopped")


def run_session_reconcile(watches: list[SessionWatch]) -> int:
    """Periodic safety net: recreate any dead Observer, then reconcile each DISCOVERY watch.

    Recreating the Observer keeps the fast path alive going forward; the reconcile sweep
    enqueues anything the live path dropped. ``reconcile`` is gated on the per-watch
    ``discover`` flag, never a global read of ``session_watcher_enabled`` — an acceptance-only
    root (a default Claude/Codex root under a custom ``session_watcher_dir``) must never be
    swept. Returns total enqueued.
    """
    total = 0
    for w in watches:
        if w.observer is not None:
            try:
                alive = w.observer.is_alive()
            except Exception:
                alive = False
            if not alive:
                logger.warning("Session watcher Observer not alive for %s; recreating", w.watch_dir)
                try:
                    w.observer.stop()
                    w.observer.join(timeout=5)
                except Exception as e:
                    logger.debug("Stopping dead Observer for %s failed: %s", w.watch_dir, e)
                try:
                    observer = Observer()
                    observer.schedule(w.handler, str(w.watch_dir), recursive=True)
                    observer.start()
                    w.observer = observer
                except Exception as e:
                    logger.warning("Failed to recreate Observer for %s: %s", w.watch_dir, e)
        if w.discover:
            total += w.handler.reconcile()
    return total
