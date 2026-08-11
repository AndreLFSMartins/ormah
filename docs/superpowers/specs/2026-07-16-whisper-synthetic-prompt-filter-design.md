# Whisper: skip synthetic (machine-generated) prompts — Design

- **Date:** 2026-07-16
- **Status:** Approved (brainstorming) — ready for implementation plan
- **Issue:** [#134](https://github.com/r-spade/ormah/issues/134)
- **Source:** `docs/investigation-2026-07-15-whisper-pipeline.md`, item [0]
- **Branch (to cut):** `fix/whisper-synthetic-prompt-filter` from `upstream/main` (see `FORK-WORKFLOW.md`)

## Problem

The `UserPromptSubmit` hook fires on every turn, including machine-generated ones. The whisper
pipeline pays a full encode + hybrid search + cross-encoder rerank on prompts no human will read,
and records the outcome as if it were a real recall event.

Measured on the live DB (`~/.local/share/ormah/memory/index.db`, `retrieval_events`, 30d window,
2026-07-16): **631 of 1,714 events with text (36.8%) are machine-authored end-to-end, and 421 of
them received an injection.**

Two independent costs:

1. **Waste** — latency and compute spent where there is no reader.
2. **Contaminated instrumentation** — an injection into a subagent turn can never be "referenced",
   so the heuristic usage judge counts it as an unreferenced miss. This depresses the observed
   usage rate (25%) and inflates `silent_gate` (45%) with calls that should never have been made.

## Investigation findings that changed the fix

The issue's proposed pattern list is **wrong in two ways**, both verified against the live DB.

### 1. `<ide_opened_file>` is a wrapper, not a synthetic prompt (would cause a regression)

The IDE prefixes this tag to a **real human prompt**. Measured: **46 of 46** events carry a human
prompt after stripping the tag. Filtering on this prefix would silence the whisper for every prompt
sent while a file is open in the IDE — i.e. the normal case in the VSCode extension.

Same shape applies to `<system-reminder>` and `<command-name>` (slash commands the user typed).
**These are never filtered.**

### 2. The pattern list misses the largest contributor, and it is environment-specific

| Pattern | Events (30d) | Wasted injections | Generic? |
| --- | ---: | ---: | --- |
| `<task-notification>` | 239 | — | yes (Claude Code) |
| `<scheduled-task …>` | 52 | — | yes (Claude Code) |
| `# Autonomous loop check` | 4 | — | yes (Claude Code) |
| **structural subtotal** | **295 (17.2%)** | **184** | **default** |
| `Leia o seguinte conteúdo e gere uma description…` | 298 | — | no (local PT-BR script) |
| `<role>You are Codex…` | 30 | — | no (council/Codex plugin) |
| `You are classifying the relationship…` | 8 | — | no (ormah's own maintenance judge) |
| **local subtotal** | **336 (19.6%)** | **237** | **config** |
| **total** | **631 (36.8%)** | **421** | |

The single largest contributor (298 events, 17.4%) originates in a local script and does not exist
upstream. Hardcoding it would be over-fitting to one install — hence the config layer.

### 3. There is no structural signal; regex is the only route (verified, not assumed)

A subagent claimed the hook payload carries an `interactive: bool` field distinguishing headless
from human turns. **This was a hallucination.** Captured the real payload from `claude -p` via an
isolated `--settings` sandbox (no user config touched); the complete field set is:

```
session_id, transcript_path, cwd, prompt_id, permission_mode, hook_event_name, prompt
```

No `interactive`, no `agent_id`. Prefix matching is the only available discriminator.

### 4. `^You are` (as proposed in the issue) is too broad for a default

It currently matches only ormah's own maintenance judge (8 events), but `"You are right, fix it"`
is a plausible human prompt. It ships as a **config** pattern, never a default.

## Design

### Component 1 — `is_synthetic_prompt()` (`src/ormah/engine/prompt_classifier.py`)

```python
_SYNTHETIC_PATTERNS = (r"<task-notification>", r"<scheduled-task\b", r"#\s*Autonomous loop check\b")

def is_synthetic_prompt(prompt: str, extra_patterns: Sequence[str] = ()) -> bool: ...
```

- Matches **anchored at the start** of the stripped prompt (`re.match`), never mid-text.
  Deliberate and fail-open: a human asking *"what is `<task-notification>`?"* still gets a whisper.
  When in doubt, whisper.
- Lives in `prompt_classifier.py` — the module that already owns prompt-shape decisions — so
  `build_whisper_context` (820 lines, #140) gains a guard and no logic.
- An invalid user regex **must not break the whisper**: compile in `try/except`, log a warning,
  ignore that pattern, continue. A config typo degrades to "filters less", never to "whisper dies".

### Component 2 — settings (`src/ormah/config.py`)

| Setting | Default | Purpose |
| --- | --- | --- |
| `whisper_synthetic_filter_enabled` | `True` | kill-switch |
| `whisper_synthetic_prompt_patterns` | `[]` | extra regexes for install-specific traffic |

### Component 3 — the guard (`src/ormah/engine/context_builder.py`)

Placed immediately after the short-prompt check (~L390) and **before** the classifier — the last
point where no encode, search, or rerank has been paid. Mirrors `silent_short` exactly:

```python
if enabled and is_synthetic_prompt(prompt, extra_patterns):
    logger.info("Whisper diagnostics: prompt=%r synthetic_prompt -> skip", prompt_snippet)
    self._log_decision(session_id=..., space=..., prompt=prompt,
                       intent=None, outcome="silent_synthetic")
    return "" (or ("", []) when _return_debug)
```

Filtering server-side rather than in the hook keeps **one code path for all clients** (Claude Code
and Codex) and preserves instrumentation — without the `whisper_decisions` row we would be blind to
what was filtered, which would compound #137.

`memory_engine._whisper_decision_stats` aggregates with an open `GROUP BY outcome`, so
`silent_synthetic` appears in stats with no change there. Add the value to the outcome comment in
`src/ormah/index/schema.sql`.

## Testing

TDD. The regression test is the most important of the set — it locks the door on the exact mistake
the investigation found.

| # | Test | Why |
| --- | --- | --- |
| 1 | **`<ide_opened_file>` + human text → NOT filtered, whisper proceeds** | **Regression guard.** Stops anyone from "completing" the pattern list and silencing real prompts. |
| 2 | Each default pattern → filtered, returns `""` | happy path |
| 3 | `"what is <task-notification>?"` → NOT filtered | proves the anchor |
| 4 | `extra_patterns` from settings → filtered | config layer works |
| 5 | Invalid regex in `extra_patterns` → fail-open, no raise | error path; config typo must not kill the whisper |
| 6 | `whisper_synthetic_filter_enabled=False` → nothing filtered | kill-switch |
| 7 | Filtered call writes `outcome='silent_synthetic'` | instrumentation |

## Verification (not "tests pass")

After running on the Beta, query the live DB:

- `whisper_decisions` shows `outcome='silent_synthetic'` rows.
- Count matches projection: ~295/30d with defaults only; ~631/30d with the local patterns configured.
- `injection_rate` rises (denominator sheds machine turns) with no drop in absolute human injections.

## Out of scope

- **Stripping wrapper tags** before search (the tag and file path pollute the query embedding on 46
  events). Different problem — quality, not waste — and the gain is unmeasured. Separate issue.
- **ormah whispering to itself**: the 8 `You are classifying…` events are ormah's own maintenance
  prompts triggering the whisper hook. Config handles the symptom; the cause (ormah does not mark
  its own prompts) deserves its own issue.
- Items [1]–[7] of the investigation (#135–#140).

## Risks / unverified

- The 36.8% is measured over `retrieval_events`, which **only holds rows for calls that produced
  candidates**. Calls that went silent earlier are not in the denominator, so the true synthetic
  share of *all* whisper calls may differ. `whisper_decisions` stores only `prompt_hash`, not text,
  so the historical share cannot be recomputed exactly — this is precisely what the new
  `silent_synthetic` outcome fixes going forward.
- Pattern lists rot: Claude Code can rename or add machine-turn markers at any time, silently
  reducing coverage. The `silent_synthetic` count is the canary — if it falls toward zero while
  synthetic traffic continues, the patterns went stale.
- The local-pattern measurements come from one install (André's Beta). Projections for the defaults
  generalize; the 36.8% figure does not.
