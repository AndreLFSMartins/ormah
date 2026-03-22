# Whisper & Recall Eval System Design

**Date:** 2026-03-22
**Status:** Approved
**Context:** Whisper and recall precision are ormah's make-or-break feature. Without a rigorous eval system guiding development, improvements are guesswork and regressions go undetected.

---

## Goals

- Measure whisper injection precision and recall against a known corpus of memories and prompts
- Catch regressions automatically in CI
- Support eval-driven development: every pipeline change is validated against metrics before merging
- Grow ground truth over time via real session replays and affinity signal (Phase 1 feedback loop)

**Primary metric priority:** False negative rate (missed relevant memories) is the existential metric. Precision, F1, MRR, and injection rate are all tracked equally after that.

---

## Architecture: Standalone `eval/` Module with CLI

The eval system lives in `eval/` at repo root — a self-contained package independent of `src/ormah/`. It uses the same `MemoryEngine` code as production but points to a dedicated isolated SQLite database (`eval/eval_db/`), never touching the user's real memory store.

The eval DB is rebuilt from corpus files before each run. It is gitignored. The corpus files are version-controlled.

---

## Directory Layout

```
eval/
├── corpus/
│   ├── golden/
│   │   └── golden.jsonl          # Hand-crafted cases — version-controlled, ~50-100 cases
│   ├── synthetic/
│   │   └── synthetic.jsonl       # LLM-generated corpus — version-controlled, regenerable
│   └── sessions/
│       └── *.jsonl               # Real session replays — gitignored, user-captured
│
├── results/
│   ├── latest.json               # Latest run results (overwritten each run)
│   └── history.jsonl             # Appended after each run — metric trend history
│
├── eval_db/                      # Isolated SQLite eval database (gitignored)
│
├── runner.py                     # Core: loads corpus, runs pipeline, computes metrics
├── corpus_builder.py             # Seeds eval_db from corpus files; LLM synthetic generation
├── judge.py                      # Export/import labeling workflow for Claude Code judge
├── metrics.py                    # Precision@k, Recall@k, F1, MRR, injection rate
├── report.py                     # Formats stdout report and writes JSON results
└── cli.py                        # CLI entry points wired into `ormah eval *`
```

---

## Corpus & Ground Truth Format

Each entry in `golden.jsonl` and `synthetic.jsonl` is a self-contained evaluation case:

```json
{
  "id": "golden-001",
  "memories": [
    {
      "title": "Ormah uses SQLite with FTS5",
      "content": "The index layer uses SQLite with FTS5 for full-text search and sqlite-vec for vector similarity.",
      "type": "fact",
      "tier": "working",
      "tags": ["architecture", "search"],
      "space": "ormah"
    }
  ],
  "prompts": [
    {
      "text": "how does the search layer work in ormah?",
      "expected": {
        "should_inject": ["golden-001-mem-0"],
        "should_not_inject": []
      },
      "notes": "Direct factual match — should always surface"
    }
  ]
}
```

Key decisions:
- **Memories are embedded in the case.** Each case seeds its own nodes into the eval DB. The eval DB is rebuilt clean from corpus before each run.
- **`should_inject` / `should_not_inject`** are explicit node ID lists. This is the ground truth that drives all metrics.
- **Golden cases** are small and hand-verified: ~5–15 memories per case, 1–3 prompts each. They are the regression canary.
- **Synthetic cases** are larger batches: 50–200 memories, many prompts. Generated once by LLM, version-controlled, regenerable when the pipeline changes significantly.
- **Session replay cases** have no pre-labeled expected nodes. They go through the labeling workflow before contributing to eval.

---

## Runner & Metrics

The runner instantiates `MemoryEngine` pointed at the eval DB (no HTTP, no CLI overhead) and for each case:

1. **Seed** — insert the case's memories into the eval DB
2. **Run whisper pipeline** — call `ContextBuilder.build_whisper_context(prompt)` directly
3. **Collect output** — which node IDs were injected, which were filtered at each stage
4. **Score** — compute per-case and aggregate metrics

### Metrics

| Metric | Definition |
|---|---|
| `recall@k` | Of `should_inject` nodes, fraction that appeared in top-k results |
| `precision@k` | Of top-k injected, fraction in `should_inject` |
| `F1@k` | Harmonic mean of recall@k and precision@k |
| `MRR` | Mean Reciprocal Rank of first relevant result |
| `injection_rate` | Fraction of prompts where whisper fired at all |
| `false_negative_rate` | Fraction of `should_inject` nodes completely missed |

Default `k=5` (matching whisper injection cap). All metrics reported per-case and aggregated. Golden and synthetic corpora are reported separately so regressions in the canary set are immediately visible.

---

## Ground Truth: Labeling Workflow

Ground truth comes from two sources depending on lifecycle stage.

### Claude Code as Judge (bootstrap phase)

When corpus cases have no labels yet (new session replays, new synthetic cases), the runner exports them for labeling:

```
ormah eval export-for-labeling
```

This writes `eval/corpus/pending_labels.jsonl` containing each unlabeled `(prompt, memory_title, memory_content, case_id)` pair. The user then asks Claude Code to process the file — Claude scores each pair and writes results to `eval/corpus/labels.jsonl`:

```json
{"case_id": "session-003", "prompt_idx": 0, "memory_idx": 2, "score": 2, "reason": "..."}
```

Scoring scale:
- **2** = clearly relevant → `should_inject`
- **1** = borderline → excluded from precision/recall (ambiguous)
- **0** = not relevant → `should_not_inject`

Labels are imported back and persisted into the corpus files:

```
ormah eval import-labels
```

Labels survive across runs — Claude Code is only invoked for new unlabeled cases, not re-scored every time.

### Affinity Table (mature phase)

Once the adaptive feedback loop (Phase 1) is live, the runner can pull labels directly from the `affinity` table: `signal=+1` → `should_inject`, `signal=-1` → `should_not_inject`. This replaces or supplements Claude-as-judge for session replay cases, giving real user-validated labels that grow automatically over time.

The runner picks the source automatically: affinity table signal if available for a node, corpus label otherwise.

---

## Regression Detection

Every run appends to `results/history.jsonl` (timestamp + all metric values). The runner compares current metrics against the previous run and flags drops in the report.

### Report Output

```
═══ Ormah Eval Report ══════════════════════
Corpus: golden (42 cases) | 2026-03-22 14:30

  Recall@5        0.81  ████████░░  ▼ -0.06 vs last run  ← regression
  Precision@5     0.74  ███████░░░  ▲ +0.02
  F1@5            0.77  ████████░░  ▼ -0.03
  MRR             0.83  ████████░░  → no change
  Injection rate  0.91  █████████░  → no change
  False neg rate  0.19  ██░░░░░░░░  ▲ +0.06 (worse)

Worst cases:
  golden-007  recall=0.00  "how do we handle auth tokens?"
  golden-023  recall=0.50  "what's the DB schema for nodes?"
```

Results are also written to `results/latest.json` (machine-readable) and appended to `results/history.jsonl`.

### CI Gate Modes

Two complementary failure modes, combinable:

```bash
# Absolute floor — fail if metric drops below threshold
ormah eval run --corpus golden --fail-below recall@5=0.70,precision@5=0.60

# Regression gate — fail if any metric drops more than N% vs previous run
ormah eval run --corpus golden --fail-on-regression delta=0.05
```

Only the golden corpus runs in CI — it is fast (no LLM calls, deterministic) and acts as the regression canary. Full corpus (synthetic + sessions) is run manually for deeper analysis.

---

## CLI Commands

```
ormah eval build-corpus                        # Seed eval DB from corpus files
ormah eval run                                 # Run full eval suite, print report, write results/
ormah eval run --corpus golden                 # Run only golden set
ormah eval run --fail-below recall@5=0.70      # Absolute floor (CI mode)
ormah eval run --fail-on-regression delta=0.05 # Regression gate
ormah eval export-for-labeling                 # Export unlabeled pairs to pending_labels.jsonl
ormah eval import-labels                       # Merge labels.jsonl into corpus ground truth
ormah eval capture-session <path>              # Copy session transcript into corpus/sessions/
ormah eval generate-synthetic                  # LLM-generate new synthetic cases
```

---

## CI Integration

```yaml
- name: Eval regression gate
  run: ormah eval run --corpus golden --fail-below recall@5=0.70 --fail-on-regression delta=0.05
```

The eval suite must pass before any whisper/recall pipeline change is merged.

---

## Out of Scope

- Evaluating `get_context` (agent-driven) separately from whisper — whisper is the priority
- Real-time eval during whisper execution
- Automated synthetic corpus regeneration on every CI run (too slow; regenerate manually when pipeline changes significantly)
- Cross-encoder fine-tuning pipeline (Phase 2 — after affinity data matures)
