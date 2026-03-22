# Adaptive Feedback Loop — Design Spec
**Date:** 2026-03-22
**Status:** Approved for implementation

---

## Problem

Ormah's whisper pipeline is static. It injects memories based on retrieval scores but
has no mechanism to learn whether those decisions were correct. A memory that scores
just below the injection gate is silently dropped every session, even if it would have
been highly useful for that user's specific prompts. Ormah never knows it was wrong.

**Goal:** Establish a passive, low-friction feedback loop through which ormah
continuously improves whisper recall the more it is used. No user-facing UI, no CLI
commands, no mid-session interruptions.

---

## Design Principles

- **Simplicity first.** All complexity must be justified.
- **Passive learning.** Feedback collected through behaviour, not explicit ratings.
- **Rare and targeted.** Review fires at most once per session, only for genuinely
  novel uncertain cases.
- **Phase 1 scope: false negatives only.** Memories gated out that may have been
  relevant. False positive coverage is Phase 2.

---

## Existing Pipeline (Accurate)

Full sequence in `build_whisper_context` as it exists today:

```
1. Short prompt check         → skip if ≤ 2 alphanumeric chars
2. Topic-shift detection      → skip if prompt too similar to recent prompts
3. PromptClassifier           → classify intent (temporal/identity/conversational/general)
                                 conversational → skip injection entirely
4. Hybrid search              → FTS5 + bge-base-en-v1.5 vector + RRF fusion
                                 boosts: confidence, tier, recency, access_count
5. min_score filter           → drop candidates below 0.45
6. Cross-encoder reranker     → Xenova/ms-marco-MiniLM-L-6-v2 (enabled by default)
                                 scores all candidates:
                                 blended = 0.4 × sigmoid(CE) + 0.6 × embedding_score
7. Injection gate             → if max blended score < 0.55 → drop everything
                                 score floor: keep only results ≥ 0.55
8. Identity split + cap
9. Format + inject
```

**Note on temporal queries:** `source=temporal` results (fetched by SQL recency, not
semantic similarity) carry scores near 0.001. The existing code relaxes min_score to
0.30 and sets `reranker_min_score = 0.0` for temporal queries. These results must be
excluded from `whisper_log` logging — their near-zero scores have no relevance signal
meaning.

**Why affinity is still needed despite the cross-encoder:** `ms-marco-MiniLM-L-6-v2`
is trained on MS MARCO web search queries. It does not know that "help me ace this
interview" + "Rishi is an ML engineer" is a high-relevance pair for this specific user.
The affinity layer adds personalised relevance the cross-encoder cannot provide.

---

## Scope

### In scope (Phase 1)

- `whisper_log` table — log every non-temporal injection candidate (with `prompt_snippet` for review display)
- `affinity` table — labeled (prompt_vec, prompt_text, node, signal) pairs; `source` column distinguishes explicit (user) vs implicit (Claude inline) feedback
- `review_log` table — track surfaced candidates to enforce rate limits
- Affinity boost inserted after cross-encoder scoring, before both filters; implicit signals weighted at 0.8×
- Exploration slot — one unconfirmed cold-start candidate per inject cycle
- Review mechanism — session-start context injection via `build_core_context`; shows conversation context + memory content in natural language
- `submit_feedback` MCP tool + `/agent/feedback` route
- Implicit feedback — Claude calls `submit_feedback` inline when it uses or deliberately ignores a whispered memory

### Out of scope (Phase 2)

- False positive coverage (injected but not useful)
- Mid-session review injection
- Aggregate threshold tuning
- Fine-tuning the cross-encoder (`ms-marco-MiniLM-L-6-v2`) on affinity-labeled pairs
- PromptClassifier archetype expansion

---

## Data Model

Three new tables added to `schema.sql`. No existing tables modified.

### `whisper_log`

Append-only event log. One row per (prompt, node) candidate per inject cycle.
Non-temporal candidates only.

```sql
CREATE TABLE IF NOT EXISTS whisper_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL,
    space          TEXT,
    prompt_hash    TEXT NOT NULL,    -- sha256(prompt), no raw text stored
    prompt_snippet TEXT,             -- first 300 chars of prompt for review context display
    prompt_vec     BLOB NOT NULL,    -- 768-dim float32 embedding
    node_id        TEXT NOT NULL,
    score          REAL NOT NULL,    -- cross-encoder blended score, before affinity boost
    was_injected   INTEGER NOT NULL, -- 1 = injected, 0 = gated out
    logged_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_whisper_log_session ON whisper_log(session_id);
CREATE INDEX IF NOT EXISTS idx_whisper_log_node    ON whisper_log(node_id);
CREATE INDEX IF NOT EXISTS idx_whisper_log_logged  ON whisper_log(logged_at);
```

`score` records the cross-encoder blended score before the affinity boost is applied.
This preserves the raw retrieval signal independently of feedback history.

`prompt_snippet` stores the first 300 characters of the prompt (truncated at a word
boundary with `…` if longer). Used only for the session-start review context block so
the user understands what was being discussed when ormah held back a memory. The paired
memory content provides additional context for ambiguous snippets (e.g. code-heavy
prompts). Not used for retrieval.

**Storage:** 768 dims × 4 bytes + ~300 bytes text ≈ 3.3KB/row. At ~250 candidates/day
→ ~300MB/year. Rows older than 90 days can be pruned by the decay_manager background
job (outside the 7-day review eligibility window; affinity signal already extracted).

### `affinity`

Labeled feedback. One row per confirmed review answer.

```sql
CREATE TABLE IF NOT EXISTS affinity (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_vec   BLOB NOT NULL,    -- 768-dim embedding of the reviewed prompt
    prompt_text  TEXT,             -- full prompt text; used for cross-encoder fine-tuning
    node_id      TEXT NOT NULL,
    signal       INTEGER NOT NULL, -- +1 helpful, -1 not helpful
    source       TEXT NOT NULL DEFAULT 'explicit', -- 'explicit' (user) or 'implicit' (Claude inline)
    confirmed_at TEXT NOT NULL,
    space        TEXT,
    session_id   TEXT,
    UNIQUE (node_id, session_id)   -- prevent duplicate submissions
);

CREATE INDEX IF NOT EXISTS idx_affinity_node ON affinity(node_id);
```

`prompt_text` stores the full prompt text for Phase 2 cross-encoder fine-tuning.
Training pairs are `(prompt_text, node.content, signal)` — exactly what
`ms-marco-MiniLM-L-6-v2` needs to learn which memories are relevant to which prompts
for this specific user.

`source` distinguishes explicit user-confirmed signals from implicit signals Claude
records inline. Implicit signals carry 0.8× weight in the affinity boost computation.

### `review_log`

Tracks surfaced candidates. Rate-limit enforcement uses `COUNT(answered=0)` per
`node_id` rather than a separate counter column.

```sql
CREATE TABLE IF NOT EXISTS review_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    surfaced_at TEXT NOT NULL,
    answered    INTEGER DEFAULT 0  -- 0 = ignored/skipped, 1 = answered
);

CREATE INDEX IF NOT EXISTS idx_review_log_node ON review_log(node_id);
```

---

## Pipeline Changes

### Insertion Point

The affinity boost is inserted **after the cross-encoder scores all candidates, but
before both the reranker min_score filter and the injection gate**. This gives affinity
the maximum opportunity to rescue false negatives:

```
... (steps 1–5 unchanged) ...

6.  Cross-encoder reranker → scores all candidates
    blended = 0.4 × sigmoid(CE) + 0.6 × embedding_score
    (no filter applied yet — all scored candidates continue)

    [NEW] Affinity boost
          → for each candidate: boosted_score = blended + affinity_adjustment
          → affinity_adjustment ∈ [−0.15, +0.15]

    Reranker min_score filter → drop boosted_score < 0.40
    (previously dropped blended < 0.40; now drops boosted < 0.40)

7.  Injection gate → drop if max boosted_score < 0.55
    Score floor: keep only boosted_score ≥ 0.55
```

A node at 0.45 blended with a strong +1 signal → boosted to 0.58 → survives both
filters and injects.

A node at 0.30 blended with max +1 signal → boosted to 0.45 → survives reranker floor
but not gate (0.55). The effective rescue range for false negatives is [0.40, 0.55):
nodes that cleared the hybrid min_score (0.45) but would have been gated out.

### Affinity Boost Computation

```
inputs: current_prompt_vec (768-dim), node_id, affinity table

1. Fetch all affinity rows WHERE node_id = ?

2. For each row:
     sim      = cosine(current_prompt_vec, row.prompt_vec)
     if sim < 0.70: skip
     days_ago = (now − row.confirmed_at).total_seconds() / 86400
     recency  = exp(−days_ago × ln2 / 30)   ← half-life 30 days
     source_w = 0.8 if row.source == 'implicit' else 1.0
     weight   = sim × recency × source_w

3. weighted_sum = Σ (signal × weight)
   weight_total = Σ weight

4. if weight_total == 0: boost = 0.0
   else:
     normalised = weighted_sum / weight_total   ← in [−1, +1]
     boost = normalised × 0.15                  ← capped at ±0.15

5. candidate.boosted_score = blended_score + boost
```

Implicit signals (source = 'implicit') carry 0.8× weight — slightly discounted
relative to explicit user confirmation, but still high-trust since Claude's inline
judgement is usually correct. Explicit signals (user-confirmed) are always 1.0×.

**Batching:** fetch all affinity rows for all candidate `node_id`s in a single query
before the loop. Group by `node_id` in Python. No per-candidate DB round-trips.

**Configurable parameters** (added to `config.py` as `Settings` fields):

| Setting | Default | Description |
|---|---|---|
| `affinity_similarity_threshold` | 0.70 | Min cosine sim to a past prompt to count |
| `affinity_half_life_days` | 30 | Recency decay half-life in days |
| `affinity_max_boost` | 0.15 | Maximum score adjustment in either direction |
| `whisper_exploration_enabled` | True | Whether to inject exploration slot candidates |

### Exploration Slot

After the gate selects survivors, one additional candidate is appended:

```
From gated-out candidates with boosted_score ≥ 0.40:
  Filter to those with NO affinity row for any similar prompt + this node_id
  (similarity > 0.70 — checked in Python using pre-fetched affinity rows,
   same batch fetch used for boost computation above)

  Take the highest-scored eligible candidate.
  Inject it. Log it with was_injected = 1.
  (Does not displace regular results.)
```

Only fires when `whisper_exploration_enabled = True`.

### Logging

At the end of each inject cycle, write one `whisper_log` row per candidate where:
- `source != "temporal"` (temporal results excluded — their scores are not meaningful)
- `boosted_score >= 0.40` (below this is noise)

`score` stored is the **pre-boost blended score** from the cross-encoder step.
`was_injected` reflects the final post-gate, post-exploration decision.

---

## Review Mechanism

### When It Triggers

`build_core_context` is called via the `get_context` MCP tool at session start.
It already appends signals into the context text (onboarding nudge,
`unprocessed_memories`). The review appends a review block when eligible candidates
exist — before any user work begins.

Session-start only. Users with long-running sessions accumulate candidates in
`whisper_log` and are asked at their next new session. The 7-day lookback window
keeps candidates fresh.

### Eligibility

**Step 1 — SQL pre-filter** (deduplicates by `node_id` before loading blobs):

```sql
SELECT wl.node_id, MAX(wl.score) as score, wl.session_id, wl.space,
       wl.prompt_snippet, n.title, n.content
FROM whisper_log wl
JOIN nodes n ON n.id = wl.node_id
WHERE wl.was_injected = 0
  AND wl.logged_at > datetime('now', '-7 days')
GROUP BY wl.node_id
ORDER BY score DESC
LIMIT 20
```

Note: `wl.source != 'temporal'` is not a filter here — `whisper_log` never contains
temporal rows (they are excluded at logging time). The `prompt_vec` blob is loaded only
in Step 2 Python filtering, not in this pre-filter query.

**Step 2 — Python filtering** (loads `prompt_vec` only for top-20):

For each candidate:

1. **No strong existing signal** — fetch all `affinity` rows for this `node_id`.
   Compute cosine sim against candidate's `prompt_vec`. If any past prompt with
   signal exists above 0.70 similarity → skip (already known, boost handles it).

2. **Not recently surfaced** — no `review_log` row for this `node_id` in last 14 days.

3. **Not exhausted** — fewer than 3 `review_log` rows with `answered = 0` for this
   `node_id` (count of ignored attempts). At 3, give up permanently.

Take the first eligible candidate. **Limit: 1 question per session.**

### Context Block

```
## Ormah: one quick question (optional)
Before we start — in a recent session in /{space}, you were working on:
"{prompt_snippet}"

I held back this memory because I wasn't confident it was relevant:
"{node title}" — {node content}

Ask the user naturally: would that memory have been useful while they were working on
that? Yes or no is all you need. Then call submit_feedback with their answer (signal=1
for yes, signal=-1 for no). If they'd rather skip, proceed normally — won't be asked
again for this memory.
```

No raw scores exposed. No node IDs shown to the user. Claude reads the memory content
and prompt snippet, then frames the question in its own words — conversational, not
transactional. If the memory content is long, Claude summarises it in one sentence.
No blocking: if the user skips or ignores the question, the session proceeds normally.

### Rate Limits

| Limit | Value | Enforced via |
|---|---|---|
| Questions per session | 1 | LIMIT 1 in eligibility |
| Candidate lookback window | 7 days | `logged_at` filter |
| Min gap between surfacing same node | 14 days | `review_log` timestamp |
| Max ignored attempts before giving up | 3 | COUNT(answered=0) in review_log |

---

## New MCP Tool: `submit_feedback`

### Interface

```json
{
  "node_id": "abc123...",
  "signal": 1,
  "source": "explicit"
}
```

`source` is optional, defaults to `"explicit"`. Claude passes `"implicit"` when calling
inline (not from a user-confirmed review). No `session_id` in the input — the server
resolves `prompt_vec` and `prompt_text` from the most recent `whisper_log` row for
this `node_id`. This avoids requiring Claude to track session identifiers across turns.

### Server-side (`POST /agent/feedback`)

```
1. SELECT prompt_vec, prompt_text, session_id, space
   FROM whisper_log
   WHERE node_id = ?
   ORDER BY logged_at DESC
   LIMIT 1

2. INSERT INTO affinity
     (prompt_vec, prompt_text, node_id, signal, source, confirmed_at, space, session_id)
   ON CONFLICT (node_id, session_id) DO NOTHING   ← idempotent

3. UPDATE review_log SET answered = 1
   WHERE node_id = ? AND answered = 0
   ORDER BY surfaced_at DESC LIMIT 1
   (skipped for implicit feedback — review_log is not updated)
```

Active immediately on the next inject cycle.

---

## Complete Data Flow

```
Session N (any length):
  Each UserPromptSubmit:
    → whisper inject
    → hybrid search → min_score 0.45
    → cross-encoder → blended scores (all candidates, no filter yet)
    → [NEW] affinity boost batch-applied (±0.15 on blended scores)
    → reranker min_score filter: drop boosted < 0.40
    → injection gate: drop if max < 0.55, floor at 0.55
    → [NEW] exploration slot (1 unconfirmed candidate, if enabled)
    → [NEW] whisper_log written (non-temporal, boosted_score ≥ 0.40)
    → context injected into Claude

Next new session start:
  get_context MCP call:
    → [NEW] build_core_context runs eligibility check
    → finds gated-out candidate, no affinity signal, not recently surfaced
    → appends review block to context text
    → [NEW] review_log row inserted (surfaced_at = now, answered = 0)
    → Claude asks naturally, one question before any work begins
    → user answers (or skips)
    → if answered: Claude calls submit_feedback(node_id, ±1)
      → affinity row stored, review_log answered = 1

Following sessions:
  whisper inject
    → "ML engineer" raw blended score: 0.48
    → affinity lookup: +1 signal, similarity 0.82, confirmed 2 days ago
      recency = exp(−2 × ln2 / 30) ≈ 0.95
      boost = (0.82 × 0.95 × 1) / (0.82 × 0.95) × 0.15 = +0.15
      boosted: 0.48 + 0.15 = 0.63 → above gate (0.55) → INJECTED
    → review never asked about this node for similar prompts again
```

---

## What Improves Over Time

```
Day 1:    Cross-encoder baseline. Personalised gaps remain.
Month 1:  20–50 affinity pairs. Recall improving for recurring prompt types.
Month 3:  Affinity table rich. Right memories surface reliably for this user.
Year 1:   Genuinely personalised. Different from any other user's ormah instance.
```

---

## Phase 2 (After Measuring Phase 1)

1. **False positive coverage** — extend eligibility to `was_injected = 1` candidates
   with no affinity signal. One additional WHERE condition. No new infrastructure.
2. **Aggregate threshold tuning** — lower injection gate for users with persistently
   high miss rates.
3. **Cross-encoder fine-tuning** — once the affinity table has enough labeled pairs,
   fine-tune `ms-marco-MiniLM-L-6-v2` on `(prompt_text, node.content, signal)` triples.
   The affinity table is designed to collect exactly this training data. Separate spec.

---

## Implementation Notes

- **`whisper_log` pruning:** add to `decay_manager` background job. Rows older than
  90 days safe to delete.
- **Affinity batch fetch:** load all affinity rows for candidate `node_id`s in one
  query at the start of the boost step. No per-candidate DB calls.
- **`whisper_exploration_enabled`:** add as `whisper_exploration_enabled: bool = True`
  to `Settings` in `config.py`, consistent with `whisper_reranker_enabled` and
  similar flags.
- **Temporal exclusion:** check `r.get("source") == "temporal"` before logging to
  `whisper_log`. These results have near-zero scores and should never enter the
  review queue.
- **prompt_snippet truncation:** truncate at a word boundary ≤ 300 chars, append `…`.
  Stored at inject time alongside `prompt_vec`. Never used for retrieval.
- **Implicit feedback:** add instructions to `CLAUDE.md` (ormah project) telling Claude
  to call `submit_feedback(node_id, signal, source="implicit")` inline — with `signal=1`
  when it actively uses a whispered memory in its response, `signal=-1` when it
  explicitly decides the whispered memory is not relevant to the current task. Claude
  should not call `submit_feedback` when it simply doesn't reference a memory (silence
  is not a negative signal). `review_log` is not updated for implicit calls.
