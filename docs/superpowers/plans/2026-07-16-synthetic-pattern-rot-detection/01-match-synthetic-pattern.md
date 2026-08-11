# Task 1: `match_synthetic_pattern` — return which pattern fired

**Files:**
- Modify: `src/ormah/engine/prompt_classifier.py:29-47`
- Modify: `src/ormah/api/routes_agent.py:16` (import), `:149-157` (call-site)
- Test: `tests/test_engine/test_prompt_classifier.py` (class `TestIsSyntheticPrompt`, ~L523)
- Test: `tests/test_engine/test_whisper_context.py` (class `TestSyntheticPromptEndpoint`)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `match_synthetic_pattern(prompt: str, extra_patterns: Sequence[str] = ()) -> str | None` in `ormah.engine.prompt_classifier`. Returns the regex **source string** that matched (`r"<task-notification>"` for builtins, the raw operator string otherwise), or `None` when the prompt is human. Task 2 threads this value into the DB; task 3 matches it against `_SYNTHETIC_PATTERNS[i].pattern`.

**Why this shape:** `is_synthetic_prompt` already knows which regex matched and throws it away. Rot detection needs exactly that. There is one production call-site, so no `is_synthetic_prompt` wrapper is kept — a wrapper with zero consumers is speculative abstraction.

**The one way this breaks:** an operator can configure the empty regex `""`. It matches everything and returns `""` — falsy, but a real match. Truthiness at the call-site would silently stop filtering every prompt for that operator. Steps 1 and 6 pin this.

---

- [ ] **Step 1: Write the failing unit tests**

Open `tests/test_engine/test_prompt_classifier.py`. Change the import on line 14 from `is_synthetic_prompt` to `match_synthetic_pattern`, then replace the whole `TestIsSyntheticPrompt` class body (~L523-561) with:

```python
class TestMatchSyntheticPattern:
    """Which pattern fired — the signal rot detection needs (#143)."""

    def test_task_notification_returns_its_pattern_source(self):
        assert match_synthetic_pattern("<task-notification>done</task-notification>") == (
            r"<task-notification>"
        )

    def test_scheduled_task_returns_its_pattern_source(self):
        assert match_synthetic_pattern("<scheduled-task id=3>") == r"<scheduled-task\b"

    def test_autonomous_loop_returns_its_pattern_source(self):
        assert match_synthetic_pattern("# Autonomous loop check") == (
            r"#\s*Autonomous loop check\b"
        )

    def test_leading_whitespace_still_matches(self):
        assert match_synthetic_pattern("\n  <task-notification>x") == r"<task-notification>"

    def test_operator_pattern_returns_the_raw_string(self):
        assert match_synthetic_pattern("BATCH JOB 12 done", [r"BATCH JOB"]) == r"BATCH JOB"

    def test_ide_wrapped_human_prompt_returns_none(self):
        # <ide_opened_file> PREFIXES a real human prompt (#134 regression guard).
        assert match_synthetic_pattern("<ide_opened_file>/a/b.py</ide_opened_file>fix this") is None

    def test_human_asking_about_a_marker_returns_none(self):
        # Anchored .match(), not .search() — a human discussing a marker is human.
        assert match_synthetic_pattern("what is a <task-notification> block?") is None

    def test_plain_human_prompt_returns_none(self):
        assert match_synthetic_pattern("fix the parser") is None

    def test_empty_prompt_returns_none(self):
        assert match_synthetic_pattern("") is None

    def test_invalid_operator_regex_is_skipped_not_fatal(self):
        # A config typo must never take the whisper down (fail-open).
        assert match_synthetic_pattern("hello", ["[unclosed"]) is None

    def test_invalid_regex_does_not_hide_a_later_valid_one(self):
        assert match_synthetic_pattern("BATCH x", ["[unclosed", r"BATCH"]) == r"BATCH"

    def test_empty_operator_pattern_returns_empty_string_not_none(self):
        """The empty regex matches everything and returns "" — falsy but REAL.

        Callers MUST test `is not None`. If this ever returns None, an operator
        who configured "" silently loses all filtering.
        """
        assert match_synthetic_pattern("anything at all", [""]) == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_engine/test_prompt_classifier.py -k MatchSyntheticPattern -v`
Expected: FAIL — `ImportError: cannot import name 'match_synthetic_pattern'`

- [ ] **Step 3: Implement it**

In `src/ormah/engine/prompt_classifier.py`, replace `is_synthetic_prompt` (L29-47) with:

```python
def match_synthetic_pattern(prompt: str, extra_patterns: Sequence[str] = ()) -> str | None:
    """The source of the pattern that matched, or None when the prompt is human.

    Returns the regex source rather than a bool so callers can record WHICH
    pattern fired — a pattern that stops firing is a rotted pattern (#143).

    ``extra_patterns`` carries install-specific regexes from settings; the
    defaults stay generic to Claude Code. An invalid pattern is logged and
    ignored — a config typo must never take the whisper down.

    An operator can configure the empty pattern "", which matches everything and
    returns "" — falsy but a real match. Callers MUST test ``is not None``.
    """
    text = prompt.lstrip()
    if not text:
        return None
    for compiled in _SYNTHETIC_PATTERNS:
        if compiled.match(text):
            return compiled.pattern
    for raw in extra_patterns or ():
        try:
            if re.match(raw, text):
                return raw
        except (re.error, TypeError) as e:
            logger.warning("Ignoring invalid synthetic-prompt pattern %r: %s", raw, e)
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_engine/test_prompt_classifier.py -k MatchSyntheticPattern -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Update the call-site**

In `src/ormah/api/routes_agent.py`, line 16, change:

```python
from ormah.engine.prompt_classifier import match_synthetic_pattern
```

Then replace L149-157 with (note the nesting: the settings flag still short-circuits *before* any regex runs, and the test is `is not None`):

```python
    if _settings.whisper_synthetic_filter_enabled:
        matched = match_synthetic_pattern(
            prompt, _settings.whisper_synthetic_prompt_patterns
        )
        if matched is not None:
            await anyio.to_thread.run_sync(
                lambda: engine.note_synthetic_whisper_skip(
                    prompt=prompt, space=space, session_id=session_id,
                )
            )
            return TextResponse(text="")
```

Leave the `# Machine-generated turn ...` comment block above (L143-148) untouched.

- [ ] **Step 6: Add the boundary tests that pin the falsy trap and the kill-switch**

Append to class `TestSyntheticPromptEndpoint` in `tests/test_engine/test_whisper_context.py`, matching the mocked-engine `TestClient` style already used there:

```python
    def test_empty_operator_pattern_still_skips_the_whisper(self, monkeypatch):
        """"" matches everything and is falsy — the guard must test `is not None`.

        Truthiness here would silently disable filtering for this operator.
        """
        from ormah.config import settings

        monkeypatch.setattr(settings, "whisper_synthetic_prompt_patterns", [""])
        client, engine = self._client()  # reuse this class's existing helper
        resp = client.post(
            "/agent/whisper",
            json={"prompt": "an ordinary human prompt", "session_id": "s-empty"},
        )
        assert resp.status_code == 200
        engine.get_whisper_context.assert_not_called()

    def test_filter_disabled_lets_a_synthetic_prompt_through(self, monkeypatch):
        """Kill-switch coverage: it was dropped in 566fe3a when the guard moved."""
        from ormah.config import settings

        monkeypatch.setattr(settings, "whisper_synthetic_filter_enabled", False)
        client, engine = self._client()
        resp = client.post(
            "/agent/whisper",
            json={"prompt": "<task-notification>done", "session_id": "s-off"},
        )
        assert resp.status_code == 200
        engine.get_whisper_context.assert_called_once()
```

`self._client()` is that class's existing helper (`tests/test_engine/test_whisper_context.py:3213`) — it builds a `FastAPI` app with `routes_agent.router` and a mocked engine, and returns both. Use it as-is; do not invent a fixture.

- [ ] **Step 7: Run the full affected suites**

Run: `python -m pytest tests/test_engine/test_prompt_classifier.py tests/test_engine/test_whisper_context.py -v`
Expected: PASS, no failures. Any other reference to `is_synthetic_prompt` will surface here as an ImportError — fix those call-sites too (`grep -rn is_synthetic_prompt src/ tests/` must return nothing).

- [ ] **Step 8: Lint**

Run: `make lint`
Expected: clean (`All checks passed!`).

- [ ] **Step 9: Commit**

```bash
git add src/ormah/engine/prompt_classifier.py src/ormah/api/routes_agent.py \
        tests/test_engine/test_prompt_classifier.py tests/test_engine/test_whisper_context.py
git commit -m "refactor(whisper): return which synthetic pattern matched, not just whether (#143)"
```
