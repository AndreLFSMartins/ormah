# Whisper-health Metric Implementation Plan (v3 — post-council x2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface whisper coverage/precision via `engine.stats()` so the feedback loop closed in #21 stops being unmeasurable.

**Architecture:** One pure read-only function `compute_whisper_health(conn, now)` aggregates `whisper_log` + `affinity` into `all_time` and `last_7d` recuts, then `engine.stats()` adds one `whisper_health` key. No new route, CLI, or change to the collection/miner side.

**Tech Stack:** Python 3.11, sqlite3, pytest.

## Council corrections

**Round 1 (v2):** three verified correctness defects, all fixed by ONE structural change — every feedback aggregate anchors in `whisper_log` via `JOIN ... AND wl.was_injected = 1`, and `last_7d` filters `wl.logged_at >= since` on both sides. This caps coverage at 100% (C1), keeps `last_7d` a single cohort (I1), and stops comparing the divergently-formatted `confirmed_at` (I2).

**Round 2 (v3):** both peers confirmed the v2 SQL is correct (coverage ≤ 1.0 holds). Remaining items are honesty/visibility + test gaps, NOT correctness bugs:

- **I1 — legacy `whisper_log_id IS NULL` feedback vanishes.** The INNER JOIN drops pre-#21 affinity rows (NULL whisper_log_id — supported by `idx_affinity_node_session_legacy_unique`, db.py:241-243, and produced by `ON DELETE SET NULL`, db.py:221; see `UPSTREAM_ISSUE_schema_migration_whisper_log_id.md`). On a migrated store `all_time` can look feedback-empty. It's *undercounting*, not inflation. **Fix:** keep coverage/precision linked-only (correct by definition) and surface the loss via `unlinked_feedback_rows` on `all_time` + document it.
- **I2 — integration test only covers an empty store.** **Fix:** add a seeded `engine`-fixture test asserting non-trivial coverage/precision against the real schema.
- **M1 (known limitation, documented not fixed) — held-back attribution undercounts.** A node injected earlier then re-logged held-back: `submit_feedback` resolves the *latest* whisper_log (held-back) and the JOIN excludes it. Undercounting. The fix lives in `submit_feedback` (collection side) → out of scope here; documented + follow-up.
- **M2 — DISTINCT test doesn't mirror production.** `idx_affinity_node_whisper_log_unique` (db.py:234) forbids two affinity rows on one `whisper_log_id`. **Fix:** rename the test as a DISTINCT guard with a note.
- **M3 — API regression gap.** `tests/test_api/test_routes.py::test_stats` asserts only `total_nodes`. **Fix:** assert `whisper_health` presence there.
- **M4 — `logged_at` ISO invariant.** Production writers always use `.isoformat()` for `logged_at` (context_builder.py:601, memory_engine.py:493), so the space-format skew can't occur on that column (unlike `confirmed_at`). **Fix:** document the invariant; no test for an impossible case (YAGNI).

---

### Task 1: `compute_whisper_health` pure function

**Files:**
- Create: `src/ormah/engine/whisper_health.py`
- Test: `tests/test_whisper_health.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_whisper_health.py`:

```python
import sqlite3
from datetime import datetime, timedelta, timezone

from ormah.engine.whisper_health import compute_whisper_health

NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)
ISO = NOW.isoformat()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE whisper_log "
        "(id INTEGER PRIMARY KEY, was_injected INTEGER, logged_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE affinity "
        "(whisper_log_id INTEGER, signal INTEGER, confirmed_at TEXT)"
    )
    return conn


def _inject(conn, wid, when=ISO, injected=1):
    conn.execute(
        "INSERT INTO whisper_log (id, was_injected, logged_at) VALUES (?, ?, ?)",
        (wid, injected, when),
    )


def _feedback(conn, wid, signal, when=ISO):
    conn.execute(
        "INSERT INTO affinity (whisper_log_id, signal, confirmed_at) VALUES (?, ?, ?)",
        (wid, signal, when),
    )


def test_empty_store_ratios_none():
    out = compute_whisper_health(_db(), NOW)
    for window in ("all_time", "last_7d"):
        assert out[window]["coverage"] is None
        assert out[window]["precision"] is None
        assert out[window]["injected"] == 0
    assert out["all_time"]["unlinked_feedback_rows"] == 0


def test_injection_without_feedback():
    conn = _db()
    _inject(conn, 1)
    _inject(conn, 2)
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["injected"] == 2
    assert out["coverage"] == 0.0
    assert out["precision"] is None


def test_mixed_signals_precision():
    conn = _db()
    for wid in (1, 2, 3, 4):
        _inject(conn, wid)
    _feedback(conn, 1, 1)
    _feedback(conn, 2, 1)
    _feedback(conn, 3, 1)
    _feedback(conn, 4, -1)
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["precision"] == 0.75
    assert out["coverage"] == 1.0


def test_distinct_guards_against_double_count():
    # In production idx_affinity_node_whisper_log_unique (db.py:234) forbids two
    # affinity rows on one whisper_log_id, so this two-row shape can't occur for
    # real. The minimal schema here omits that index on purpose, to assert the
    # DISTINCT clause is a defensive guard that keeps coverage <= 1.0 regardless.
    conn = _db()
    _inject(conn, 1)
    _feedback(conn, 1, 1)
    _feedback(conn, 1, -1)
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["feedback_rows"] == 1
    assert out["coverage"] == 1.0  # not 2.0


def test_held_back_candidate_feedback_excluded():
    # C1: feedback on a was_injected=0 candidate must NOT inflate coverage.
    conn = _db()
    _inject(conn, 1, injected=1)
    _feedback(conn, 1, 1)
    _inject(conn, 2, injected=0)  # held-back candidate
    _feedback(conn, 2, 1)         # later converted to affinity
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["injected"] == 1
    assert out["feedback_rows"] == 1
    assert out["coverage"] == 1.0  # not 2.0
    assert out["positive"] == 1   # held-back signal excluded from precision too


def test_legacy_null_whisper_log_id_surfaced_not_counted():
    # I1 (council r2): pre-#21 affinity rows carry whisper_log_id = NULL. They are
    # excluded from linked-only coverage/precision but surfaced via
    # unlinked_feedback_rows so the loss is visible, not silent.
    conn = _db()
    _inject(conn, 1)
    _feedback(conn, 1, 1)
    conn.execute(
        "INSERT INTO affinity (whisper_log_id, signal, confirmed_at) "
        "VALUES (NULL, 1, ?)",
        (ISO,),
    )
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["coverage"] == 1.0            # linked-only, NULL row ignored
    assert out["positive"] == 1              # NULL row excluded from precision
    assert out["unlinked_feedback_rows"] == 1  # but counted and exposed


def test_last_7d_old_injection_recent_feedback():
    # I1 (r1): recent feedback for an old injection must not push last_7d above 1.0.
    conn = _db()
    old = (NOW - timedelta(days=10)).isoformat()
    _inject(conn, 1, when=old)
    _feedback(conn, 1, 1, when=ISO)  # feedback today
    out = compute_whisper_health(conn, NOW)
    assert out["all_time"]["coverage"] == 1.0
    assert out["last_7d"]["injected"] == 0
    assert out["last_7d"]["feedback_rows"] == 0
    assert out["last_7d"]["coverage"] is None


def test_mixed_confirmed_at_format_still_counted():
    # I2 (r1): confirmed_at in datetime('now') space-format must not be dropped,
    # because the window filters wl.logged_at, never confirmed_at.
    conn = _db()
    _inject(conn, 1, when=ISO)
    _feedback(conn, 1, 1, when="2026-06-24 00:00:00")  # space-format, no TZ
    out = compute_whisper_health(conn, NOW)["last_7d"]
    assert out["feedback_rows"] == 1
    assert out["coverage"] == 1.0


def test_seven_day_cutoff():
    conn = _db()
    old = (NOW - timedelta(days=10)).isoformat()
    _inject(conn, 1, when=old)
    _feedback(conn, 1, 1, when=old)
    out = compute_whisper_health(conn, NOW)
    assert out["all_time"]["injected"] == 1
    assert out["all_time"]["coverage"] == 1.0
    assert out["last_7d"]["injected"] == 0
    assert out["last_7d"]["coverage"] is None
    assert out["last_7d"]["precision"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_whisper_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ormah.engine.whisper_health'`

- [ ] **Step 3: Write the implementation**

Create `src/ormah/engine/whisper_health.py`:

```python
"""Whisper effectiveness metrics derived from whisper_log + affinity.

Read-only aggregation for the feedback loop closed in #21 — surfaces coverage
(share of injected memories that drew any feedback) and precision (positive
share of feedback on injected memories) so whisper effectiveness stops being
unmeasurable.

Semantics & known limitations (council-reviewed):
- coverage/precision are LINKED-ONLY: they count affinity rows joined to an
  injected whisper (whisper_log_id NOT NULL AND was_injected = 1). Legacy
  pre-#21 rows (whisper_log_id IS NULL) are excluded but surfaced separately as
  `unlinked_feedback_rows` on `all_time`, so the loss is visible, not silent.
- the window filters `wl.logged_at`, which production writers always emit via
  `.isoformat()` (context_builder.py, memory_engine.py) — so lexicographic
  comparison on that column is safe. `confirmed_at` (written as datetime('now'),
  a different format) is never compared.
- KNOWN UNDERCOUNT: if a node was injected then re-logged held-back, feedback
  attaches to the latest (held-back) whisper_log row and is excluded here. The
  fix belongs in submit_feedback's attribution (collection side), tracked as a
  follow-up; this read-only metric reports pessimistically rather than wrong.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta


def _window(conn: sqlite3.Connection, since: str | None) -> dict:
    # Anchor every feedback aggregate in whisper_log via INNER JOIN with
    # was_injected = 1, so numerator and denominator share one universe. The
    # window filters wl.logged_at on BOTH sides (single cohort).
    log_filter = " AND logged_at >= ?" if since else ""
    join_filter = " AND wl.logged_at >= ?" if since else ""
    log_params: tuple = (since,) if since else ()
    join_params: tuple = (since,) if since else ()

    injected = conn.execute(
        "SELECT COUNT(*) FROM whisper_log WHERE was_injected = 1" + log_filter,
        log_params,
    ).fetchone()[0]
    feedback_rows = conn.execute(
        "SELECT COUNT(DISTINCT a.whisper_log_id) FROM affinity a "
        "JOIN whisper_log wl ON wl.id = a.whisper_log_id "
        "WHERE wl.was_injected = 1" + join_filter,
        join_params,
    ).fetchone()[0]
    pos, neg = conn.execute(
        "SELECT "
        "COALESCE(SUM(CASE WHEN a.signal = 1 THEN 1 ELSE 0 END), 0), "
        "COALESCE(SUM(CASE WHEN a.signal = -1 THEN 1 ELSE 0 END), 0) "
        "FROM affinity a "
        "JOIN whisper_log wl ON wl.id = a.whisper_log_id "
        "WHERE wl.was_injected = 1" + join_filter,
        join_params,
    ).fetchone()

    fb_total = pos + neg
    return {
        "injected": injected,
        "feedback_rows": feedback_rows,
        "coverage": feedback_rows / injected if injected else None,
        "positive": pos,
        "negative": neg,
        "precision": pos / fb_total if fb_total else None,
    }


def compute_whisper_health(conn: sqlite3.Connection, now: datetime) -> dict:
    """Return whisper coverage/precision over all_time and last_7d windows.

    ``now`` is injected (never ``datetime.now()`` inside the query) so callers
    and tests are deterministic. See module docstring for the linked-only
    semantics and known undercount.
    """
    since_7d = (now - timedelta(days=7)).isoformat()
    all_time = _window(conn, None)
    # Surface legacy/unattributable feedback (whisper_log_id IS NULL) so the
    # linked-only ratios don't silently hide it. all_time only — the 7d cohort
    # is injection-anchored and has no NULL side.
    all_time["unlinked_feedback_rows"] = conn.execute(
        "SELECT COUNT(*) FROM affinity WHERE whisper_log_id IS NULL"
    ).fetchone()[0]
    return {"all_time": all_time, "last_7d": _window(conn, since_7d)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_whisper_health.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/whisper_health.py tests/test_whisper_health.py
git commit -m "feat(engine): whisper-health coverage/precision aggregation

Read-only metric over whisper_log + affinity (all_time + last_7d), anchored in
whisper_log via JOIN ... was_injected = 1 so coverage cannot exceed 100% and
the 7d window stays a single cohort. Legacy NULL feedback surfaced as
unlinked_feedback_rows. Follow-up to PR #40 review.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Wire `whisper_health` into `engine.stats()`

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (the `stats()` method, ~L1213; `datetime, timezone` already imported at L12)
- Test: `tests/test_whisper_health.py` (add empty-shape + seeded integration tests)

- [ ] **Step 1: Add the failing integration tests**

Append to `tests/test_whisper_health.py`. Uses the existing `engine` fixture from
`tests/conftest.py` (`MemoryEngine(settings)` + `startup()`/`shutdown()`):

```python
def test_stats_exposes_whisper_health(engine):
    out = engine.stats()
    assert "whisper_health" in out
    wh = out["whisper_health"]
    assert set(wh) == {"all_time", "last_7d"}
    assert set(wh["last_7d"]) == {
        "injected", "feedback_rows", "coverage",
        "positive", "negative", "precision",
    }
    assert set(wh["all_time"]) == {
        "injected", "feedback_rows", "coverage",
        "positive", "negative", "precision", "unlinked_feedback_rows",
    }
    assert wh["all_time"]["injected"] == 0
    assert wh["all_time"]["coverage"] is None


def test_stats_whisper_health_seeded(engine):
    # I2 (council r2): exercise real schema (NOT NULL cols + JOIN), not just empty.
    from datetime import datetime, timezone

    conn = engine.db.conn
    conn.execute(
        "INSERT INTO whisper_log "
        "(session_id, prompt_hash, prompt_vec, node_id, score, was_injected, logged_at) "
        "VALUES ('s1', 'h1', X'00', 'n1', 0.5, 1, ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO affinity "
        "(prompt_vec, node_id, signal, source, confirmed_at, session_id, whisper_log_id) "
        "VALUES (X'00', 'n1', 1, 'explicit', datetime('now'), 's1', ?)",
        (wid,),
    )
    wh = engine.stats()["whisper_health"]["all_time"]
    assert wh["injected"] == 1
    assert wh["feedback_rows"] == 1
    assert wh["coverage"] == 1.0
    assert wh["precision"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_whisper_health.py -k stats -v`
Expected: FAIL — `KeyError: 'whisper_health'`

- [ ] **Step 3: Wire the call into `stats()`**

Add the import near the top of `src/ormah/engine/memory_engine.py` (with the other intra-package imports):

```python
from ormah.engine.whisper_health import compute_whisper_health
```

In the `stats()` return dict, add one key (keep the existing keys unchanged):

```python
            "embedding_schema_version": int(ver_row["value"]) if ver_row else 0,
            "whisper_health": compute_whisper_health(
                self.db.conn, datetime.now(timezone.utc)
            ),
```

- [ ] **Step 4: Run the full whisper-health suite**

Run: `.venv/bin/python -m pytest tests/test_whisper_health.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_whisper_health.py
git commit -m "feat(engine): expose whisper_health in stats()

GET /admin/stats and 'ormah stats' now surface coverage/precision.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: API regression assert (council M3)

**Files:**
- Modify: `tests/test_api/test_routes.py` (the `test_stats` function, L69-72)

- [ ] **Step 1: Add the assert**

Edit `test_stats` to also assert the new key (the route is `return engine.stats()`,
so this guards against `whisper_health` silently disappearing from `/admin/stats`):

```python
def test_stats(client):
    resp = client.get("/admin/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "total_nodes" in body
    assert "whisper_health" in body
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/python -m pytest tests/test_api/test_routes.py::test_stats -v`
Expected: PASS

- [ ] **Step 3: Regression — stats + whisper across the suite**

Run: `.venv/bin/python -m pytest tests/ -k "stats or whisper" -v`
Expected: PASS (no regressions)

- [ ] **Step 4: Commit**

```bash
git add tests/test_api/test_routes.py
git commit -m "test(api): assert whisper_health present in /admin/stats

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Follow-up (out of scope here)

Open an issue: `submit_feedback` resolves the *latest* whisper_log per node without
requiring `was_injected = 1`, so feedback can attach to a held-back row and be excluded
from whisper-health (undercount). Fix is to attribute feedback to the surfaced/injected
whisper_log_id. Tracked separately — this PR stays read-only.

---

## Self-Review

**Spec + council coverage:**
- `compute_whisper_health(conn, now)` + isolated file → Task 1 ✓
- 6-field windows + `unlinked_feedback_rows` on all_time → Task 1 impl + Task 2 shape asserts ✓
- `None` on zero denominator → `test_empty_store_ratios_none`, `test_injection_without_feedback` ✓
- Coverage cannot exceed 100% (C1) → `test_held_back_candidate_feedback_excluded`, `test_distinct_guards_against_double_count` ✓
- last_7d single cohort (I1 r1) → `test_last_7d_old_injection_recent_feedback` ✓
- confirmed_at format-skew safe (I2 r1) → `test_mixed_confirmed_at_format_still_counted` ✓
- Legacy NULL surfaced not counted (I1 r2) → `test_legacy_null_whisper_log_id_surfaced_not_counted` ✓
- Seeded integration on real schema (I2 r2) → `test_stats_whisper_health_seeded` ✓
- DISTINCT-guard rename + production note (M2) → `test_distinct_guards_against_double_count` ✓
- API regression assert (M3) → Task 3 ✓
- logged_at ISO invariant + held-back undercount (M4/M1) → documented in module docstring ✓
- Wire into `stats()`, no signature/route change → Task 2 ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code.

**Type consistency:** `compute_whisper_health(conn, now)` signature identical across Task 1 def, Task 1 tests, and Task 2 wiring. Field names consistent across impl, tests, and the Task 2 shape asserts; `unlinked_feedback_rows` appears only on `all_time` in both impl and asserts.
