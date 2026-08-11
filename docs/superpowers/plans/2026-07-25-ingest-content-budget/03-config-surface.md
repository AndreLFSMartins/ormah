# Task 3: Rename the setting to the new unit, warn on the old one, rewire the watcher

**Files:**
- Modify: `src/ormah/config.py:99` (field), `:561-566` (floor validator), `:575-586` (cap validator)
- Modify: `src/ormah/background/session_watcher.py:785-793, 803, 864, 889, 1105, 1116, 1258, 1475`
- Test: `tests/test_background/test_session_watcher_flush.py:21-46, 49-97, 234-300`

**Interfaces:**
- Consumes: Task 1/2's `parse_transcript(..., max_conversation_chars=..., max_raw_bytes=...)`.
- Produces:
  - `Settings.session_watcher_flush_chars: int = 60000`
  - `Settings.session_watcher_max_raw_bytes: int | None = None` (value set in Task 6)
  - `_ingest_session(..., flush_chars: int = 60000, max_raw_bytes: int | None = None, ...)`
  - `SessionWatcher(..., flush_chars=..., max_raw_bytes=...)`

**Migration decision (do not substitute your own).** `session_watcher_flush_bytes` appears nowhere
outside tests — not in any live `.env`, no installer or template writes it. A transparent alias would
silently reinterpret a tuned value across incomparable units (someone's `200000` bytes would become
200000 *chars*, 3.3x the sweet spot). So: **rename, and warn loudly if the old env var is present.**
Today `extra: "ignore"` swallows it with no signal at all, so a warning is strictly better.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_background/test_session_watcher_flush.py:21-46` with:

```python
def test_flush_defaults():
    s = Settings()
    assert s.session_watcher_flush_chars == 60000   # ~15K tokens of CONVERSATION
    assert s.session_watcher_retry_seconds == 30.0     # decoupled from idle
    assert s.session_watcher_idle_threshold == 600.0   # policy A
    assert s.session_watcher_flush_chars <= s.ingest_max_content_chars


def test_flush_chars_over_cap_rejected():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_chars=200000, ingest_max_content_chars=100000,
                 ingest_chunk_chars=200000)


def test_flush_chars_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_chars=500)


def test_flush_chars_equal_cap_allowed():
    s = Settings(session_watcher_flush_chars=100000, ingest_max_content_chars=100000,
                 ingest_chunk_chars=100000)
    assert s.session_watcher_flush_chars == s.ingest_max_content_chars


@pytest.fixture(autouse=True)
def _reset_deprecation_warn_once():
    """The warning is once-per-process, so without this reset the SECOND deprecation test in a
    pytest session sees no record and fails (council R2, Cursor). Reset before and after so test
    order never matters."""
    import ormah.config as cfg

    cfg._warned_flush_bytes = False
    yield
    cfg._warned_flush_bytes = False


def test_deprecated_flush_bytes_env_var_warns_and_is_ignored(monkeypatch, caplog):
    """The unit changed, so the old value is not translatable. Honouring it would silently
    reinterpret a tuned number; swallowing it silently (today's `extra: ignore`) hides the
    change. Warn, and use the new default."""
    import logging

    monkeypatch.setenv("ORMAH_SESSION_WATCHER_FLUSH_BYTES", "200000")
    with caplog.at_level(logging.WARNING, logger="ormah.config"):
        s = Settings()

    assert s.session_watcher_flush_chars == 60000  # the stale value did NOT leak in
    assert any("ORMAH_SESSION_WATCHER_FLUSH_BYTES" in r.message for r in caplog.records)
    assert any("unit" in r.message.lower() for r in caplog.records)


def test_deprecated_flush_bytes_in_an_env_FILE_also_warns(tmp_path, monkeypatch, caplog):
    """Council R1 (Codex): Settings loads ~/.config/ormah/.env and ./.env (config.py:11-17), so
    checking os.environ alone misses the LIKELY case -- an operator who set the old key in a
    config file gets no warning, which is precisely the silent migration this task claims to
    prevent."""
    import logging

    import ormah.config as cfg

    env_file = tmp_path / ".env"
    env_file.write_text("ORMAH_SESSION_WATCHER_FLUSH_BYTES=200000\n")

    # Point the scanner at the SAME list Settings resolves. Passing only Settings(_env_file=...)
    # would leave the scanner reading the import-time list and the assertion would pass or fail
    # for the wrong reason (council R2, Cursor).
    monkeypatch.setattr(cfg, "_EXISTING_ENV_FILES", [str(env_file)])
    monkeypatch.delenv("ORMAH_SESSION_WATCHER_FLUSH_BYTES", raising=False)

    assert cfg._deprecated_key_present() is True   # the file path is what is under test

    with caplog.at_level(logging.WARNING, logger="ormah.config"):
        s = Settings(_env_file=str(env_file))

    assert s.session_watcher_flush_chars == 60000
    assert any("ORMAH_SESSION_WATCHER_FLUSH_BYTES" in r.message for r in caplog.records), (
        "the deprecated key was set in an env FILE and produced no warning"
    )


def test_deprecated_key_scanner_ignores_comments_and_partial_names(tmp_path):
    """Presence detection must not fire on a commented-out line or on a longer key that merely
    starts with the deprecated name."""
    import ormah.config as cfg

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# ORMAH_SESSION_WATCHER_FLUSH_BYTES=1\n"
        "ORMAH_SESSION_WATCHER_FLUSH_BYTES_OLD=2\n"
    )
    assert cfg._deprecated_key_present(env_files=[str(env_file)]) is False


def test_raw_ceiling_far_below_the_measured_ratio_is_rejected():
    """Council R1 (Cursor): a floor of `>= flush_chars` compares bytes to chars and permits a
    ~200KB ceiling, which would close tool-heavy slices long before the char sweet spot --
    re-creating the axis error Amendment 3 exists to fix, one scale up."""
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_chars=60000, session_watcher_max_raw_bytes=200000)


def test_retry_seconds_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_retry_seconds=0)
```

Then replace `tests/test_background/test_session_watcher_flush.py:49-97` (the three parser tests that
assert on the byte axis) with:

```python
def _tool_heavy_turns(path, turns: int, text_chars: int = 500, noise_chars: int = 40000) -> None:
    """Raw bytes >> cleaned chars. See 01-content-budget.md for why plain-text padding is
    useless here: it passes identically under both units and tests nothing."""
    lines = []
    for i in range(turns):
        lines.append({"type": "user", "message": {"role": "user",
                      "content": f"u{i} " + "q" * text_chars}})
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"blob": "N" * noise_chars}}]}})
        lines.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "M" * noise_chars}]}})
        lines.append({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": f"a{i} " + "r" * text_chars}],
                      "stop_reason": "end_turn"}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def test_parse_transcript_breaks_before_overshooting_the_content_budget(tmp_path):
    """A multi-turn slice must never exceed the conversation budget — break BEFORE committing
    the turn that would push it over, not after."""
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "big.jsonl"
    _tool_heavy_turns(p, turns=30, text_chars=2000)

    full = parse_transcript(p)
    capped = parse_transcript(p, max_conversation_chars=60000)

    assert 0 < capped.safe_end_offset < full.safe_end_offset
    assert len(capped.safe_conversation) <= 60000
    assert capped.capped is True
    assert capped.safe_user_turn_count < full.user_turn_count

    # Draining the remainder from the new cursor must make more progress and eventually reach
    # EOF (proves the left-behind turn isn't lost).
    next_slice = parse_transcript(
        p, start_offset=capped.safe_end_offset, max_conversation_chars=60000,
    )
    assert len(next_slice.safe_conversation) <= 60000
    assert next_slice.safe_user_turn_count > 0


def test_parse_transcript_no_budget_preserves_behavior(tmp_path):
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "small.jsonl"
    _write_turns(p, turns=2, pad=100)

    default = parse_transcript(p)
    explicit_none = parse_transcript(p, max_conversation_chars=None, max_raw_bytes=None)

    assert default.safe_end_offset == explicit_none.safe_end_offset
    assert default.capped is False
    assert explicit_none.capped is False


def test_parse_transcript_single_oversized_turn_commits_anyway(tmp_path):
    """A single turn bigger than the budget can't make empty progress — commit it as its own
    slice rather than starving the drain forever."""
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "oneturn.jsonl"
    _write_turns(p, turns=1, pad=20000)

    result = parse_transcript(p, max_conversation_chars=5000)
    assert result.safe_user_turn_count == 1
    assert len(result.safe_conversation) > 5000  # unavoidable for a lone oversized turn
```

Finally, in the same file, rename every remaining `flush_bytes=60000` keyword passed to
`_ingest_session` (lines 225, 248, 267, 291, 298) to `flush_chars=60000`, and change the assertion at
line 252 from `engine.recorded_lengths[-1] <= 60000` to the same bound expressed on the payload the
engine received (it already is a length of conversation, so the number is unchanged — only the
docstring's justification changes). Update the docstrings at lines 235-238, 256-257 and 274-275 to say
"conversation chars" instead of "bytes".

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./.venv/bin/python -m pytest tests/test_background/test_session_watcher_flush.py -v
```

Expected: FAIL — `ValidationError: Extra inputs are not permitted` / `AttributeError:
'Settings' object has no attribute 'session_watcher_flush_chars'`.

- [ ] **Step 3: Rename the setting**

Replace `src/ormah/config.py:99` with:

```python
    session_watcher_flush_chars: int = 60000       # CONVERSATION chars that close a Batch (~15K tok)
    session_watcher_max_raw_bytes: int | None = None  # independent raw-span budget; see ADR-0001 Am.3
```

- [ ] **Step 4: Rename the validators**

Replace `src/ormah/config.py:561-566` with:

```python
    @field_validator("session_watcher_flush_chars")
    @classmethod
    def _flush_chars_min(cls, v: int) -> int:
        if v < 1000:
            raise ValueError(f"session_watcher_flush_chars must be >= 1000, got {v}")
        return v

    @field_validator("session_watcher_max_raw_bytes")
    @classmethod
    def _max_raw_bytes_min(cls, v: int | None) -> int | None:
        if v is not None and v < 1000:
            raise ValueError(f"session_watcher_max_raw_bytes must be >= 1000, got {v}")
        return v
```

Replace `src/ormah/config.py:575-586` with:

```python
    @model_validator(mode="after")
    def _flush_chars_within_cap(self) -> "Settings":
        if self.session_watcher_flush_chars > self.ingest_max_content_chars:
            raise ValueError(
                "session_watcher_flush_chars "
                f"({self.session_watcher_flush_chars}) must be <= "
                f"ingest_max_content_chars ({self.ingest_max_content_chars}); "
                "a larger cap would let a MULTI-turn batch overshoot the extractor's "
                "truncation limit (a single turn bigger than the cap is still truncated, "
                "and logged, regardless of this setting)"
            )
        # Council R1 (Cursor): a bare `>= flush_chars` floor compares BYTES to CHARS and would
        # admit a ~200KB ceiling. Measured raw->clean ratios run ~3x to ~93x (p50 ~27x), so such a
        # ceiling closes tool-heavy slices far below the char sweet spot -- the same axis error
        # Amendment 3 fixes, one scale up, and silently. Anchor the floor on the observed ratio.
        _MIN_RAW_RATIO = 25  # ~p50 of the measured raw:clean ratio; below this the raw budget wins
        if (
            self.session_watcher_max_raw_bytes is not None
            and self.session_watcher_max_raw_bytes
            < self.session_watcher_flush_chars * _MIN_RAW_RATIO
        ):
            raise ValueError(
                f"session_watcher_max_raw_bytes ({self.session_watcher_max_raw_bytes}) must be "
                f">= {_MIN_RAW_RATIO}x session_watcher_flush_chars "
                f"({self.session_watcher_flush_chars * _MIN_RAW_RATIO}); the measured raw:clean "
                f"ratio is ~{_MIN_RAW_RATIO}x at p50, so a tighter raw budget would close batches "
                "before the recall sweet spot and become the binding limit -- reintroducing the "
                "axis error ADR-0001 Amendment 3 removes"
            )
        return self
```

- [ ] **Step 5: Add the deprecation warning**

At the top of `src/ormah/config.py`, after the imports, add:

```python
import logging
import os

logger = logging.getLogger(__name__)

_DEPRECATED_FLUSH_BYTES_ENV = "ORMAH_SESSION_WATCHER_FLUSH_BYTES"
_warned_flush_bytes = False


def _deprecated_key_present(env_files: list[str] | None = None) -> bool:
    """True when the deprecated key is set in ANY configured settings source.

    pydantic-settings resolves the process environment AND the .env files in _ENV_FILES, so
    checking os.environ alone would miss the likeliest case: an operator who wrote the old key
    into ~/.config/ormah/.env. Parsing is deliberately crude -- we only need presence, never the
    value (the value is in the wrong unit and is discarded either way).
    """
    if _DEPRECATED_FLUSH_BYTES_ENV in os.environ:
        return True
    # Mirror Settings' own resolution, including the `or ".env"` fallback (config.py:20) -- a
    # scanner that reads a different list than Settings does would report on files nobody loads
    # (council R2, Cursor).
    sources = env_files if env_files is not None else (_EXISTING_ENV_FILES or [".env"])
    for path in sources:
        try:
            for line in Path(path).read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if stripped.split("=", 1)[0].strip().upper() == _DEPRECATED_FLUSH_BYTES_ENV:
                    return True
        except OSError:
            continue
    return False
```

Then add this `model_validator` to `Settings` (next to the others):

```python
    @model_validator(mode="after")
    def _warn_on_deprecated_flush_bytes(self) -> "Settings":
        # Renamed in ADR-0001 Amendment 3 because the UNIT changed: the old value counted raw
        # transcript bytes, the new one counts conversation chars, and the raw->clean ratio
        # ranges from ~3x to ~93x. Translating is not possible, so the old value is ignored --
        # but silently ignoring it (what `extra: "ignore"` does today) hides a real config
        # change from the operator. Warn once per process.
        # Council R1 (Codex): checking os.environ ALONE misses the likely case. Settings also reads
        # ~/.config/ormah/.env and ./.env (see _ENV_FILES above), and an operator who set the old
        # key there would get no warning at all -- the exact silent migration this guard exists to
        # prevent. Scan every configured source.
        global _warned_flush_bytes
        if not _warned_flush_bytes and _deprecated_key_present():
            _warned_flush_bytes = True
            logger.warning(
                "%s is set but no longer used: it was renamed to ORMAH_SESSION_WATCHER_FLUSH_CHARS "
                "and its unit changed from raw transcript bytes to conversation characters "
                "(ADR-0001 Amendment 3). The old value was IGNORED; the default %d is in effect. "
                "Remove the old variable, or set the new one deliberately.",
                _DEPRECATED_FLUSH_BYTES_ENV, self.session_watcher_flush_chars,
            )
        return self
```

- [ ] **Step 6: Rewire the session watcher**

`session_watcher.py:803` — rename the parameter and add the new one:

```python
    flush_chars: int = 60000,
    max_raw_bytes: int | None = None,
```

`session_watcher.py:864` and `:889` — both `parse_transcript` calls:

```python
        result = parse_transcript(
            path, start_offset=prev_offset, max_conversation_chars=flush_chars,
            max_raw_bytes=max_raw_bytes, stop_offset=boundary,
        )
```

```python
            result = parse_transcript(
                path, start_offset=0, max_conversation_chars=flush_chars,
                max_raw_bytes=max_raw_bytes, stop_offset=boundary,
            )
```

Leave the uncapped probe at `:880` **exactly as it is** — it must stay uncapped, or a recoverable file
gets mis-parked.

`session_watcher.py:1105` / `:1116` — constructor:

```python
        flush_chars: int = 60000,
        max_raw_bytes: int | None = None,
```

```python
        self.flush_chars = flush_chars
        self.max_raw_bytes = max_raw_bytes
```

`session_watcher.py:1258`:

```python
                idle_threshold=self.idle_threshold, flush_chars=self.flush_chars,
                max_raw_bytes=self.max_raw_bytes,
```

`session_watcher.py:1475`:

```python
                flush_chars=s.session_watcher_flush_chars,
                max_raw_bytes=s.session_watcher_max_raw_bytes,
```

`session_watcher.py:785-793` — `_should_flush`'s docstring, which still argues in bytes:

```python
def _should_flush(is_idle: bool, capped: bool) -> bool:
    """A Batch closes once idle, or once the parser filled a full batch.

    Gating on ``capped`` (not a length comparison) matters: break-before capping guarantees a
    multi-turn slice's committed conversation stays BELOW the budget, so a threshold comparison
    would never fire for the common multi-turn case. ``capped`` is the parser's own "a full
    batch is ready, more closed content remains" signal, and it now covers BOTH budgets
    (conversation length and raw span) — the gate does not care which one bound.
    """
    return is_idle or capped
```

- [ ] **Step 7: Sweep the remaining references**

```bash
grep -rn "flush_bytes" src/ tests/ --include='*.py'
```

Expected: only `ORMAH_SESSION_WATCHER_FLUSH_BYTES` in `config.py` and in the deprecation test. Any
other hit is an unconverted call site — fix it. `tests/test_background/test_session_watcher.py` has 27
references; rename each `flush_bytes=` keyword to `flush_chars=`.

- [ ] **Step 8: Run the full suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: **PASS, fully green.** No red window is planned or acceptable here.

An earlier draft claimed `test_oversized_turn_is_split_not_truncated` was expected to fail at this
point. That was wrong: it constructs `Settings(ingest_max_content_chars=1000,
session_watcher_flush_chars=1000)`, and the only validators this task adds are `flush_chars >= 1000`,
`flush_chars <= ingest_max_content_chars` (1000 ≤ 1000 ✓) and the raw-ratio floor. The check that
rejects that construction is `ingest_chunk_chars <= ingest_max_content_chars`, which Task 4 adds — in
the same commit as the fix to that very test. If anything fails here, it is a real defect, not a
planned window.

- [ ] **Step 9: Lint and commit**

```bash
ruff check src/ tests/
git add src/ormah/config.py src/ormah/background/session_watcher.py tests/
git commit -m "refactor(config): rename flush_bytes to flush_chars, warn on the stale env var

The unit changed (raw transcript bytes -> conversation characters), so the old value is not
translatable: the raw->clean ratio ranges from ~3x to ~93x, and honouring a tuned 200000 as
200000 chars would silently ship 3.3x the recall sweet spot. The variable is set in no install
and no template, so there is nothing to migrate -- but ignoring it silently (today's
extra: ignore) hides the change, so warn once at startup instead.

Also plumbs the new raw-span budget through the watcher, defaulting to None (disabled)."
```
