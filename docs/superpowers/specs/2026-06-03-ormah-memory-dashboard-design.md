# Ormah Memory Dashboard — Design

- **Date:** 2026-06-03
- **Status:** Approved (brainstorming) — ready for implementation plan
- **Scope:** A UI panel that surfaces how *accurate* ("assertiveness") and how *used* Ormah's whispered memory is.

## Goal

Add a panel to the Ormah UI that answers two questions from data Ormah **already records** (no new instrumentation):

1. **Confidence** — "is the memory helping me?" Assertiveness + usage at a glance.
2. **Tuning** — "what should I prune, and is the system healthy?"

## Decisions (from brainstorming)

- New **4th toggleable side panel** (alongside settings / insights / admin), with two internal tabs: **Confidence** and **Tuning**.
- **Window selector:** 7d / 30d / 90d.
- **Temporal fidelity:** snapshot numbers + **inline-SVG sparklines**. No charting library.
- **Backend:** a single **on-the-fly** endpoint with a bounded window. No rollup table or job (YAGNI; revisit if measured slow).

## Data sources (existing)

| Table | Fields used |
|---|---|
| `whisper_log` | `score` (pre-boost), `was_injected`, `logged_at`, `node_id`, `session_id` |
| `affinity` | `signal` (±1), `source` (explicit/implicit), `confirmed_at`, `node_id`, `session_id` |
| `nodes` | `access_count`, `last_accessed`, `confidence`, `importance`, `stability`, `tier`, `last_review` |

## Backend

### Endpoint

`GET /admin/metrics?window=<7d|30d|90d>` in `src/ormah/api/routes_admin.py`. Runs in the **threadpool** (matches the recent concurrency hardening — engine-bound work off the event loop). Returns:

```json
{ "window": "30d", "confidence": { ... }, "tuning": { ... } }
```

`window` parses to days (7 / 30 / 90), default 30; invalid → clamp to default.

### Engine method

`memory_engine.metrics(window_days: int) -> dict`. One method; aggregation SQL bounded by `logged_at` / `confirmed_at` using the existing indices.

### Confidence metrics

Each renders as a headline value + a daily sparkline (buckets over the window).

| Metric | Formula | Feedback-dependent |
|---|---|---|
| **Injection rate** | `whisper_log was_injected=1` / total candidates | No |
| **Whisper precision** | `affinity +1` / affinity rows linked to *injected* whispers | Yes |
| **Feedback balance** | % positive (`+1` vs `−1`) | Yes |
| **Recall gap** | count(injected & `−1`) + count(gated & `+1`) | Yes |

**Mandatory meta-metric — Feedback coverage** = whispers with any affinity signal / total whispers. First-class number. When coverage is below a threshold, the UI shows a "low coverage — feedback metrics noisy" banner and the three feedback-dependent values render as `—`. Without this, the feedback numbers mislead.

**Honesty note (documented so the number isn't misread):** the *"gated & +1"* half of recall gap is rare by construction. Implicit feedback only fires when an *injected* whisper is used (CLAUDE.md rule 10), so that half fills only from **explicit** feedback.

**Linking feedback to injection:** `submit_feedback` already resolves an affinity row against the node's most-recent `whisper_log` entry in the session. Precision and recall-gap are computed over affinity rows joined to `whisper_log` on `(node_id, session_id)`, keyed by `was_injected`.

### Tuning metrics

- **Rankings:**
  - *Top useful* — nodes by `access_count` desc, tiebreak feedback balance. Limit N (~10).
  - *Dead weight* — low `access_count` + old `last_accessed` + archival tier → prune candidates. Limit N.
  - (The `access_count` ordering needs no feedback.)
- **Tier health** — core / working / archival distribution (reuse `engine.stats()` `by_tier`) + **decay pressure**: working nodes whose FSRS retrievability is near `fsrs_decay_threshold`, using the same `exp(-days_since / stability)` calc as `src/ormah/background/decay_manager.py`.

## Frontend (React + Vite — no new dependency)

| File | Change |
|---|---|
| `ui/src/components/MetricsPanel.tsx` | New: panel shell, tab state (`'confidence' \| 'tuning'`), window selector; fetch on open + on window change |
| `ui/src/components/Sparkline.tsx` | New: pure `<svg><polyline>` from a `number[]`; no lib |
| `ui/src/api.ts` | Add `fetchMetrics(window)` |
| `ui/src/types.ts` | Add `MetricsResponse`, `ConfidenceMetrics`, `TuningMetrics`, `RankingRow` |
| `ui/src/App.tsx` | Add `'metrics'` to the `activePanel` union; render `MetricsPanel` |
| `ui/src/components/TopBar.tsx` | 4th toggle button + label/icon |
| `ui/src/hooks/useKeyboardShortcuts.ts` | Shortcut to toggle the metrics panel |
| `ui/src/styles.css` | `.metric-card`, `.sparkline`, `.ranking-row`, `.coverage-banner` reusing existing design tokens (no new theme) |

## Data flow

`panel open / window change` → `fetchMetrics(window)` → `GET /admin/metrics?window` → `engine.metrics()` → JSON → render:

- **Confidence** — 4 metric cards (value + sparkline) + coverage banner.
- **Tuning** — two ranking lists + tier-health bars.

## Error & empty states

- Empty DB / zero whispers → metrics show `—` with a friendly "no data yet" copy.
- Low feedback coverage → coverage banner; feedback-dependent metrics dimmed / `—`.
- Fetch error → existing `Toast` pattern.

## Testing (done = verified)

- **Backend unit (pytest):** seed `whisper_log` / `affinity` / `nodes` fixtures; assert each metric's math, window filtering, ranking order, tier health, coverage. Edge cases: zero whispers, zero feedback, all-injected, all-gated.
- **Frontend:** `Sparkline` renders correct points for a sample series; `MetricsPanel` happy / empty / fetch-error states.
- **Verification:** `make test` + targeted pytest module + manual UI check via `make dev` (open panel, switch tabs, change window).

## Out of scope

- Recall-gap detailed per-node list (Tuning option B).
- Gate calibration suggestion (Tuning option C) — **v2**.
- Charting library / full time-series — sparklines only.
- Rollup table / background job — on-the-fly only.

## Open risk

- **`whisper_log` growth:** on-the-fly aggregation cost grows with log size. Acceptable for local single-user now; instrument query time in the endpoint and revisit with rollups if a measured query exceeds budget.
