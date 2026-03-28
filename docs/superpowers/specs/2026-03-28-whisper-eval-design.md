# Whisper Eval System Design

**Date:** 2026-03-28
**Status:** Approved

---

## Goal

Build a standalone evaluation system that measures whisper pipeline quality end-to-end — which memories get injected, which don't, and whether suppression fires correctly — broken down by query category. The output is a per-category diagnostic report that identifies where whisper is strong and where it fails.

## Motivation

Whisper precision is currently ~30% useful (relevant context injected ~2 out of 7 messages). The goal is to understand which query categories work well and which don't, and to have a repeatable baseline that measures improvement over time. The evaluation must test the **full pipeline** — intent classification → search → scoring → injection gate → output — not just the retrieval layer in isolation.

This system is separate from the recall eval harness (`feature/eval-system`). The recall eval tests `recall_search_structured` in isolation. The whisper eval tests `build_whisper_context`, which includes the classifier, topic-shift detection, affinity boost, and injection gate. These are orthogonal measurements and must not be conflated.

---

## Query Category Taxonomy

Eight categories, each exercising a distinct whisper code path or known failure mode:

| Category | Example prompts | What it tests |
|---|---|---|
| `preference` | "let's build a settings page", "write me a test", "help me design an API" | Implicit surfacing — task prompt has no preference keyword but relevant preference should inject |
| `factual` | "what port does ormah run on", "what embedding model do we use", "what's the hook timeout" | Direct fact lookup via general search |
| `decision` | "what did we decide about auth tokens", "why did we choose this embedding model" | Decision retrieval; known weakness — type field not in embedding |
| `technical` | "how does search work", "explain the reranker", "why is whisper synchronous" | Broader explanatory queries; relevant memory contains reasoning not just a value |
| `identity` | "where do I live", "what is my job", "what am I working on professionally" | Explicit personal info from `space=null` memories |
| `temporal` | "what did I work on last week", "recent progress on the API" | `created_after` filter, `strip_temporal_phrases`, relaxed min_score |
| `noise` | "hello", "thanks for the help", "what is the weather today" | Suppression — pipeline must return `""` |
| `continuation` | "where were we", "continue from last time", "pick up from yesterday" | Continuation path, recency fallback with low semantic signal |

**Corpus target:** ~37 prompts total. Weighted toward `preference` (6), `factual` (6), and `noise` (5) because those are where the current quality gap is largest.

---

## Architecture

### Production code change: debug mode on `build_whisper_context`

One minimal change to `src/ormah/engine/context_builder.py`. Add `_return_debug: bool = False` to `build_whisper_context`. When `True`, return `(whisper_text, injected_node_ids)` instead of just the string.

```python
def build_whisper_context(
    self,
    ...,
    _return_debug: bool = False,
) -> str | tuple[str, list[str]]:
    ...
    # After final cap — this is exactly what gets rendered
    search_results = search_results[:max_nodes]
    _injected_ids = [r["node"]["id"] for r in search_results]

    # ... build body, framing, suppression logic (unchanged) ...

    if _return_debug:
        return result, _injected_ids
    return result
```

If the pipeline suppresses (result is `""`), `_injected_ids` is empty — correct. No other production code changes.

### File layout

```
eval/
  whisper/
    __init__.py
    runner.py       # seeds DB, calls build_whisper_context, collects results
    metrics.py      # injection_recall, precision, f1, suppression_accuracy, top2_recall
    corpus.py       # load + validate JSONL, validates category field
    report.py       # table output per category + failures list
    seeder.py       # seeds isolated eval DB (mirrors recall eval seeder; consolidate when eval-system merges)
    corpus/
      golden/
        golden.jsonl  # ~37 prompts across 8 categories
```

No dependency on `feature/eval-system`. When that branch merges to main, shared code (seeder, corpus loader, metrics functions) can be consolidated.

---

## Corpus Format

JSONL. One case per line. Extends the recall eval schema with `category` (per prompt) and `should_suppress` (per prompt expected).

```jsonl
{
  "id": "whisper-pref-001",
  "space": "ormah",
  "memories": [
    {
      "node_id": "pref-001-dark-theme",
      "title": "User prefers minimal dark-themed UIs with gold accent colour",
      "content": "The user prefers minimal, dark-themed UIs with monospace fonts and warm accent colors (gold/bronze #d4a574). Applies to all front-end work.",
      "type": "preference",
      "tier": "core",
      "tags": ["ui", "design"],
      "space": null
    },
    {
      "node_id": "pref-001-distractor",
      "title": "FastAPI server runs on port 8787",
      "content": "The FastAPI server runs on port 8787 by default, configurable via ORMAH_PORT.",
      "type": "fact",
      "tier": "working",
      "tags": ["config"],
      "space": "ormah"
    }
  ],
  "prompts": [
    {
      "text": "let's build a settings page for ormah",
      "category": "preference",
      "expected": {
        "should_inject": ["pref-001-dark-theme"],
        "should_not_inject": ["pref-001-distractor"],
        "should_suppress": false
      },
      "notes": "Implicit preference — task prompt with no preference keyword should surface UI preference"
    }
  ]
}
```

**Fields:**
- `id`: unique case identifier, format `whisper-{category}-{nnn}`
- `space`: the "current working space" passed to the whisper pipeline for this case
- `memories[].node_id`: stable ID used in expected labels; preserved through seeding
- `memories[].space`: `null` for global memories, a string for project-scoped
- `prompts[].category`: one of the 8 taxonomy values
- `prompts[].expected.should_inject`: node IDs that must appear in whisper output
- `prompts[].expected.should_not_inject`: node IDs that must NOT appear (distractor check)
- `prompts[].expected.should_suppress`: `true` means expect empty whisper output (noise cases)

---

## Runner

```python
def run_whisper_eval(cases: list[dict], engine) -> WhisperEvalResult:
    for case in cases:
        seed_case(engine, case)          # clear DB, insert case memories + embeddings
        space = case.get("space")
        for prompt_obj in case["prompts"]:
            whisper_text, injected_ids = engine.context_builder.build_whisper_context(
                prompt=prompt_obj["text"],
                space=space,
                recent_prompts=[],       # [] not None — skips first-message review mechanism
                session_id=None,         # skips whisper_log writes (no feedback pollution)
                _return_debug=True,
            )
            metrics = compute_whisper_metrics(
                should_inject=prompt_obj["expected"].get("should_inject", []),
                should_not_inject=prompt_obj["expected"].get("should_not_inject", []),
                should_suppress=prompt_obj["expected"].get("should_suppress", False),
                injected_ids=injected_ids,
                injection_fired=bool(whisper_text.strip()),
            )
            # collect result with case_id, prompt text, category, metrics
```

Each case runs against an isolated DB seeded only with that case's memories. `recent_prompts=[]` (not `None`) bypasses the first-message review candidate block. `session_id=None` means the whisper_log insert is skipped — eval runs must not write feedback data.

**Implementation note:** The runner accesses the whisper pipeline via the engine. The exact call path (`engine.context_builder.build_whisper_context` vs `engine.get_whisper_context`) should be verified against `memory_engine.py` during implementation — wire to whichever exposes `_return_debug`.

---

## Metrics

Computed per prompt, aggregated per category and overall.

| Metric | Formula | Applies to |
|---|---|---|
| `injection_recall` | `len(should_inject ∩ injected) / len(should_inject)` | all non-noise |
| `injection_precision` | `len(should_inject ∩ injected) / len(injected)` | all non-noise |
| `f1` | harmonic mean of recall and precision | all non-noise |
| `top2_recall` | fraction of `should_inject` nodes in positions 0–1 of injected list | all non-noise |
| `suppression_correct` | `True` if `should_suppress` and `injected_ids == []` | noise cases |
| `false_positive_present` | `True` if any `should_not_inject` node appears in `injected_ids` | all |
| `injection_fired` | `bool(whisper_text.strip())` | all |

`top2_recall` is specific to whisper: nodes in positions 0–1 are shown in full (the "wow" experience). Nodes in positions 2–5 are title-only. A correct memory surfaced at position 3 is less useful than at position 0.

Aggregate per category:
- Mean of `injection_recall`, `injection_precision`, `f1`, `top2_recall` across labeled prompts
- `suppression_accuracy`: mean of `suppression_correct` across noise prompts
- `false_positive_rate`: fraction of prompts where at least one `should_not_inject` was injected

---

## Report

```
Whisper Eval — golden corpus  (37 prompts, 8 categories)
═══════════════════════════════════════════════════════════════
                     recall  precision    f1   top2_rec  fp_rate
preference  (6)       0.67      0.82    0.73     0.50     0.17
factual     (6)       0.83      0.90    0.86     0.67     0.00
decision    (5)       0.60      0.75    0.67     0.40     0.20
technical   (4)       0.75      0.88    0.81     0.50     0.00
identity    (4)       0.75      0.80    0.77     0.75     0.00
temporal    (4)       0.70      0.85    0.77     0.50     0.25
continuation(3)       0.67      0.78    0.72     0.33     0.00
───────────────────────────────────────────────────────────────
noise       (5)  suppression_accuracy: 0.80  (4/5 correctly silent)
───────────────────────────────────────────────────────────────
OVERALL     (37)      0.72      0.84    0.78     0.54

FAILURES (3):
  whisper-pref-002  [preference]  "let's create a website"
    expected: [dark-theme-001]  injected: []
  whisper-dec-003   [decision]   "what did we decide about auth tokens"
    expected: [auth-dec-001]    injected: [arch-fact-002]
  whisper-noise-004 [noise]      "hello there"
    expected: suppress  got: injected [pref-001-dark-theme]
```

---

## CLI

New subcommand group under `ormah eval`:

```bash
ormah eval whisper run                          # run full golden corpus
ormah eval whisper run --category preference    # single category
ormah eval whisper run --show-failures          # print failure details
ormah eval whisper run --json                   # machine-readable output
```

Wired into the existing `ormah` CLI alongside the recall eval commands when that branch merges. For now, added as a new `eval` command group on main.

---

## Scope Boundaries

**In scope:**
- `_return_debug` change to `build_whisper_context`
- `eval/whisper/` directory with runner, metrics, corpus loader, report, seeder
- `eval/whisper/corpus/golden/golden.jsonl` with ~37 cases across all 8 categories
- `ormah eval whisper run` CLI command

**Out of scope:**
- Session capture or labeling workflows (not needed for initial diagnostic)
- CI regression gates (add once baseline is established)
- Synthetic corpus generation
- Consolidation with `feature/eval-system` (deferred until that branch merges)
- Any changes to the whisper pipeline itself (this eval is for measurement only)
