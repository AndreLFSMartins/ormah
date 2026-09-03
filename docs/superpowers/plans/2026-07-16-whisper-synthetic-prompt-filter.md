# Whisper Synthetic-Prompt Filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the whisper pipeline from spending encode + search + rerank on machine-generated prompts, and record the skip so it stays measurable.

**Architecture:** A pure predicate `is_synthetic_prompt()` in `prompt_classifier.py`; a 6-line guard in `build_whisper_context` placed after the short-prompt check and before the classifier (the last point where no compute is spent); a new `silent_synthetic` outcome in `whisper_decisions`. Structural patterns ship as defaults; install-specific ones come from settings.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode=auto`), pydantic-settings, ruff (line-length 100).

**Spec:** `docs/superpowers/specs/2026-07-16-whisper-synthetic-prompt-filter-design.md` · **Issue:** #134

---

### Task 0: Cut the contribution branch

Per `FORK-WORKFLOW.md`, contribution branches are born from `upstream/main`, **never** from `local-main`. Do not rename remotes.

- [ ] **Step 1: Fetch upstream and cut the branch**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git checkout upstream/main -b fix/whisper-synthetic-prompt-filter
```

- [ ] **Step 2: Verify the branch is anchored on upstream, not on the Beta**

```bash
git log --oneline -1
git merge-base --is-ancestor HEAD upstream/main && echo "ANCHORED OK"
```
Expected: `ANCHORED OK`. If it fails, the branch was cut from the wrong base — redo Step 1.

---

### Task 1: `is_synthetic_prompt()` predicate

**Files:**
- Modify: `src/ormah/engine/prompt_classifier.py` (add after the `logger` line, ~L14)
- Test: `tests/test_engine/test_prompt_classifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine/test_prompt_classifier.py`:

```python
from ormah.engine.prompt_classifier import is_synthetic_prompt


class TestIsSyntheticPrompt:
    def test_task_notification_is_synthetic(self):
        assert is_synthetic_prompt("<task-notification>\n<task-id>abc</task-id>") is True

    def test_scheduled_task_is_synthetic(self):
        assert is_synthetic_prompt('<scheduled-task name="drive-watch" file="/x/S.md">') is True

    def test_autonomous_loop_is_synthetic(self):
        assert is_synthetic_prompt("# Autonomous loop check\n\nYou're being invoked") is True

    def test_leading_whitespace_still_matches(self):
        assert is_synthetic_prompt("\n  <task-notification>\n<task-id>a</task-id>") is True

    def test_ide_wrapper_with_human_prompt_is_not_synthetic(self):
        # REGRESSION GUARD (issue #134): the IDE prefixes this tag to a REAL human
        # prompt — 46/46 such events on the live DB carried human text. Filtering it
        # would silence the whisper for every prompt sent with a file open in the IDE.
        prompt = (
            "<ide_opened_file>The user opened the file /x/notes.md in the IDE."
            "</ide_opened_file>\nnão, isso fica em estratégia — revisa o portfólio"
        )
        assert is_synthetic_prompt(prompt) is False

    def test_human_asking_about_a_marker_is_not_synthetic(self):
        # The anchor is deliberate and fail-open: when in doubt, whisper.
        assert is_synthetic_prompt("what is a <task-notification> block?") is False

    def test_extra_pattern_from_settings_matches(self):
        assert is_synthetic_prompt("You are classifying the relationship between two memories",
                                   extra_patterns=[r"You are classifying the relationship"]) is True

    def test_invalid_extra_pattern_fails_open(self, caplog):
        # A config typo must degrade to "filters less", never kill the whisper.
        assert is_synthetic_prompt("hello there", extra_patterns=["[unclosed"]) is False

    def test_empty_prompt_is_not_synthetic(self):
        assert is_synthetic_prompt("") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine/test_prompt_classifier.py::TestIsSyntheticPrompt -v`
Expected: FAIL — `ImportError: cannot import name 'is_synthetic_prompt'`

- [ ] **Step 3: Write the implementation**

In `src/ormah/engine/prompt_classifier.py`, after `logger = logging.getLogger(__name__)` (~L14):

```python
# Machine-generated turns that reach the UserPromptSubmit hook. Matched ANCHORED
# at the start of the prompt: a human ASKING about one of these markers is a real
# prompt and still gets a whisper. Fail-open — when in doubt, whisper.
# Deliberately excluded: wrapper tags like <ide_opened_file> and <system-reminder>,
# which PREFIX a real human prompt rather than replace it (issue #134).
_SYNTHETIC_PATTERNS = (
    re.compile(r"<task-notification>"),
    re.compile(r"<scheduled-task\b"),
    re.compile(r"#\s*Autonomous loop check\b"),
)


def is_synthetic_prompt(prompt: str, extra_patterns: Sequence[str] = ()) -> bool:
    """True when the prompt was authored by a machine, not a human.

    ``extra_patterns`` carries install-specific regexes from settings; the
    defaults stay generic to Claude Code. An invalid pattern is logged and
    ignored — a config typo must never take the whisper down.
    """
    text = prompt.lstrip()
    if not text:
        return False
    if any(p.match(text) for p in _SYNTHETIC_PATTERNS):
        return True
    for raw in extra_patterns or ():
        try:
            if re.match(raw, text):
                return True
        except (re.error, TypeError) as e:
            logger.warning("Ignoring invalid synthetic-prompt pattern %r: %s", raw, e)
    return False
```

Add `Sequence` to the imports at the top of the file:

```python
from collections.abc import Sequence
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine/test_prompt_classifier.py::TestIsSyntheticPrompt -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/prompt_classifier.py tests/test_engine/test_prompt_classifier.py
git commit -m "feat(whisper): add is_synthetic_prompt predicate for machine-generated turns (#134)"
```

---

### Task 2: Settings

**Files:**
- Modify: `src/ormah/config.py` (after `whisper_intent_threshold`, ~L259)

- [ ] **Step 1: Add the settings**

```python
    # Machine-generated turns (subagent task-notifications, scheduled tasks,
    # autonomous-loop checks) reach the UserPromptSubmit hook like any prompt.
    # Whispering into them burns encode+search+rerank where no human reads, and
    # the injection can never be "referenced" — contaminating the usage judge.
    # Defaults cover Claude Code's own markers; add install-specific regexes
    # (headless scripts, other agents) here. Anchored at the prompt start.
    whisper_synthetic_filter_enabled: bool = True
    whisper_synthetic_prompt_patterns: list[str] = []
```

- [ ] **Step 2: Verify the settings load with defaults**

Run:
```bash
.venv/bin/python -c "from ormah.config import Settings; s=Settings(); print(s.whisper_synthetic_filter_enabled, s.whisper_synthetic_prompt_patterns)"
```
Expected: `True []`

- [ ] **Step 3: Commit**

```bash
git add src/ormah/config.py
git commit -m "feat(whisper): add synthetic-prompt filter settings (#134)"
```

---

### Task 3: The guard in `build_whisper_context`

**Files:**
- Modify: `src/ormah/engine/context_builder.py` (insert between the `if not self.engine:` block ending ~L398 and the `# Classify prompt intent` comment ~L400)
- Test: `tests/test_engine/test_whisper_context.py` (class `TestWhisperDecisions`)

Reads settings via `getattr(self.engine.settings, ...)` — the same pattern the file already uses for `whisper_exploration_enabled` (L814) — rather than threading two more parameters through a signature that already takes 25.

- [ ] **Step 1: Write the failing tests**

Add to class `TestWhisperDecisions` in `tests/test_engine/test_whisper_context.py`:

```python
    def test_synthetic_prompt_logs_silent_synthetic(self, db_graph):
        db, graph = db_graph
        builder = self._builder_with_db(db, graph)
        builder.engine.settings.whisper_synthetic_filter_enabled = True
        builder.engine.settings.whisper_synthetic_prompt_patterns = []

        out = builder.build_whisper_context(
            prompt="<task-notification>\n<task-id>x</task-id>\n<status>done</status>",
            session_id="s-synth",
        )

        assert out == ""
        rows = self._decisions(db)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "silent_synthetic"
        assert rows[0]["session_id"] == "s-synth"

    def test_ide_wrapped_human_prompt_is_not_skipped(self, db_graph):
        # REGRESSION GUARD (issue #134): must NOT log silent_synthetic — this is a
        # real human prompt the IDE merely prefixed. 46/46 live events carried
        # human text after the tag.
        db, graph = db_graph
        builder = self._builder_with_db(db, graph, results=[])
        builder.engine.settings.whisper_synthetic_filter_enabled = True
        builder.engine.settings.whisper_synthetic_prompt_patterns = []

        builder.build_whisper_context(
            prompt=("<ide_opened_file>The user opened /x/a.md in the IDE."
                    "</ide_opened_file>\nrevisa o portfólio de segurança"),
            session_id="s-ide",
        )

        rows = self._decisions(db)
        assert len(rows) == 1
        assert rows[0]["outcome"] != "silent_synthetic"

    def test_filter_disabled_does_not_skip(self, db_graph):
        db, graph = db_graph
        builder = self._builder_with_db(db, graph, results=[])
        builder.engine.settings.whisper_synthetic_filter_enabled = False
        builder.engine.settings.whisper_synthetic_prompt_patterns = []

        builder.build_whisper_context(
            prompt="<task-notification>\n<task-id>x</task-id>", session_id="s-off",
        )

        rows = self._decisions(db)
        assert rows[0]["outcome"] != "silent_synthetic"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine/test_whisper_context.py::TestWhisperDecisions -v -k "synthetic or ide_wrapped or disabled"`
Expected: FAIL — `test_synthetic_prompt_logs_silent_synthetic` gets outcome `silent_no_candidates`, not `silent_synthetic`.

- [ ] **Step 3: Write the implementation**

In `src/ormah/engine/context_builder.py`, add the import at the top alongside the existing `prompt_classifier` imports:

```python
from ormah.engine.prompt_classifier import is_synthetic_prompt
```

Insert immediately after the `if not self.engine:` block (before the `# Classify prompt intent before searching` comment):

```python
        # Machine-generated turn (subagent notification, scheduled task, loop
        # check): no human will read the injection, and the usage judge would
        # score it as an unreferenced miss. Skip before the classifier — the
        # last point where no encode/search/rerank has been paid (#134).
        _s = getattr(self.engine, "settings", None)
        if getattr(_s, "whisper_synthetic_filter_enabled", True) and is_synthetic_prompt(
            prompt, getattr(_s, "whisper_synthetic_prompt_patterns", ()) or ()
        ):
            logger.info(
                "Whisper diagnostics: prompt=%r synthetic_prompt -> skip",
                prompt_snippet,
            )
            self._log_decision(
                session_id=session_id, space=space, prompt=prompt,
                intent=None, outcome="silent_synthetic",
            )
            if _return_debug:
                return "", _injected_ids
            return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine/test_whisper_context.py::TestWhisperDecisions -v`
Expected: PASS (all, including the pre-existing decision tests)

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/context_builder.py tests/test_engine/test_whisper_context.py
git commit -m "feat(whisper): skip synthetic prompts before the classifier, log silent_synthetic (#134)"
```

---

### Task 4: Document the new outcome in the schema

**Files:**
- Modify: `src/ormah/index/schema.sql:228-230`

No migration: `whisper_decisions.outcome` is a free-text column and `_whisper_decision_stats` aggregates with an open `GROUP BY outcome`, so the new value flows into stats untouched. Only the comment needs to keep telling the truth.

- [ ] **Step 1: Update the comment**

Replace lines 228-230:

```sql
    outcome         TEXT NOT NULL,      -- 'injected' | 'silent_short' | 'silent_conversational'
                                        -- | 'silent_topic_shift' | 'silent_no_candidates'
                                        -- | 'silent_gate' | 'silent_blackout' | 'silent_error'
                                        -- | 'silent_synthetic'
```

- [ ] **Step 2: Commit**

```bash
git add src/ormah/index/schema.sql
git commit -m "docs(schema): document silent_synthetic whisper outcome (#134)"
```

---

### Task 5: Full gate + push

- [ ] **Step 1: Run lint and the full fast suite**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m pytest tests/ -q
```
Expected: ruff clean; suite green except the ~7 known environmental failures from the global `~/.config/ormah/.env` leak (pre-existing — confirm they also fail on `upstream/main` before blaming this change).

- [ ] **Step 2: Push to the fork (never upstream)**

```bash
git push fork fix/whisper-synthetic-prompt-filter
```

- [ ] **Step 3: Open the PR via council**

Run `/council-pr`. If it refuses with `origin-is-upstream — refusing to push`, that guard is council's, not git's — Step 2 already pushed.

---

### Task 6: Verify on the Beta (this is what "done" means)

Tests passing is not verification — the claim is about live traffic.

- [ ] **Step 1: Merge into the Beta and restart**

```bash
git checkout local-main
git merge fix/whisper-synthetic-prompt-filter
make restart
```

- [ ] **Step 2: Confirm the filter fires on real traffic**

After the Beta has served traffic, run:

```bash
.venv/bin/python -c "
import sqlite3, os
db = os.path.expanduser('~/.local/share/ormah/memory/index.db')
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
for row in c.execute(\"SELECT outcome, COUNT(*) n FROM whisper_decisions \"
                     \"WHERE logged_at > datetime('now','-1 day') GROUP BY outcome ORDER BY n DESC\"):
    print(row)
"
```
Expected: a `silent_synthetic` row appears. Projection from the 30d investigation: ~295 events/30d on defaults alone (~10/day). If it stays at 0 while subagents run, the patterns did not match — diagnose, do not assume.

- [ ] **Step 3: Report the local-pattern config to André — do NOT edit `.env`**

`.env` is André's decision, not the agent's. Do not apply this. Report it and let him choose:

```
# covers the remaining ~336 events/30d (~19.6%) measured on this install:
# the PT-BR description script (298), council/Codex reviews (30), ormah's own judge (8)
ORMAH_WHISPER_SYNTHETIC_PROMPT_PATTERNS=["Leia o seguinte conteúdo e gere uma description","<role>\\s*\\n?\\s*You are Codex","You are classifying the relationship"]
```

---

## Out of scope

- Stripping wrapper tags (`<ide_opened_file>`) from the query before search — separate issue.
- ormah marking its own maintenance prompts at the source — separate issue.
- Investigation items [1]–[7] (#135–#140).
