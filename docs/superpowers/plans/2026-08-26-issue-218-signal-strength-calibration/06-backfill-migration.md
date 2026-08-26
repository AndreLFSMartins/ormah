### Task 6: Backfill historical rows

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` — a version constant near `LIFECYCLE_MODEL_VERSION`
  (line 61), a new `_migrate_signal_strength` method, and one call in `startup()`
- Test: `tests/test_engine/test_signal_strength_backfill.py` (create)

**Interfaces:**
- Consumes, from Task 2: `signal_strength.strength_from_evidence(source, polarity, evidence_json)`,
  `.HEURISTIC_SOURCE`, `.LLM_JUDGE_SOURCE`, `.VERBATIM_NODE_ID`, `.IMPLICIT`, `.UNKNOWN`,
  `.token_overlap_strength`, `.judge_strength`
- Consumes, from Task 5: the `from ormah import signal_strength` import in `memory_engine.py`.
  If Task 5 has not run, add it here instead.
- Produces: `MemoryEngine._migrate_signal_strength() -> None`,
  `SIGNAL_STRENGTH_LADDER_VERSION: int`

**Why:** existing rows keep their old values. The 1,587 `token_overlap` rows sitting at `0.85` land
**inside the new judge band** (0.82–0.90), so the column would go on lying — now about which
channel produced the row.

**Why it is cheap:** the recompute is exact, not estimated. Measured on a live store, **zero**
`signals` rows lack `evidence`: heuristic rows carry `match` and `overlap_ratio`, judge rows carry
`confidence` and their own `min_confidence`, and feedback rows are identified by `source`.

The migration touches only the `signals` table — no `file_store` call — so it does not participate
in the db-lock/memory-lock ordering hazard documented on `_record_confirmed_use`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_signal_strength_backfill.py`:

```python
"""The #218 backfill recomputes historical strength exactly, and only once."""

import json

import pytest

from ormah import signal_strength as ss


def _seed(engine, *, source, polarity, evidence, strength=0.85):
    """Insert a signals row with a stale strength.

    whisper_log_id stays NULL: the unique index on
    (whisper_log_id, signal_type, source) is partial on whisper_log_id IS NOT NULL,
    so NULL rows never collide however many are seeded.
    """
    cursor = engine.db.conn.execute(
        "INSERT INTO signals "
        "(whisper_log_id, node_id, signal_type, polarity, strength, source, evidence, created) "
        "VALUES (NULL, 'seed-node', 'seeded', ?, ?, ?, ?, datetime('now'))",
        (polarity, strength, source, json.dumps(evidence) if evidence is not None else None),
    )
    engine.db.conn.commit()
    return cursor.lastrowid


def _rerun(engine):
    """Clear the version stamp so the guarded migration runs again."""
    engine.db.conn.execute(
        "DELETE FROM meta WHERE key = 'signal_strength_ladder_version'"
    )
    engine.db.conn.commit()
    engine._migrate_signal_strength()


def _row(engine, signal_id):
    return engine.db.conn.execute(
        "SELECT strength, polarity, evidence FROM signals WHERE id = ?", (signal_id,)
    ).fetchone()


def test_backfill_recomputes_each_channel_exactly(engine):
    verbatim = _seed(
        engine, source=ss.HEURISTIC_SOURCE, polarity=1, evidence={"match": "node_id"}
    )
    overlap = _seed(
        engine,
        source=ss.HEURISTIC_SOURCE,
        polarity=1,
        evidence={"match": "token_overlap", "overlap_ratio": 1.167},
    )
    judged = _seed(
        engine,
        source=ss.LLM_JUDGE_SOURCE,
        polarity=1,
        evidence={"confidence": 0.88, "min_confidence": 0.75},
    )
    implicit = _seed(engine, source="implicit", polarity=1, evidence={"source": "implicit"},
                     strength=1.0)

    _rerun(engine)

    assert _row(engine, verbatim)["strength"] == ss.VERBATIM_NODE_ID
    assert _row(engine, overlap)["strength"] == pytest.approx(ss.token_overlap_strength(1.167))
    assert _row(engine, judged)["strength"] == pytest.approx(ss.judge_strength(0.88, 0.75, 1))
    assert _row(engine, implicit)["strength"] == ss.IMPLICIT


def test_backfill_uses_the_rows_own_min_confidence(engine):
    """Not today's setting — the judge stamped it on the row when it wrote it."""
    lenient = _seed(
        engine, source=ss.LLM_JUDGE_SOURCE, polarity=1,
        evidence={"confidence": 0.80, "min_confidence": 0.75},
    )
    strict = _seed(
        engine, source=ss.LLM_JUDGE_SOURCE, polarity=1,
        evidence={"confidence": 0.80, "min_confidence": 0.80},
    )

    _rerun(engine)

    assert _row(engine, lenient)["strength"] > _row(engine, strict)["strength"]


def test_backfill_zeroes_rows_that_assert_nothing(engine):
    uncertain = _seed(
        engine, source=ss.LLM_JUDGE_SOURCE, polarity=0,
        evidence={"confidence": 0.35, "min_confidence": 0.75},
    )

    _rerun(engine)

    assert _row(engine, uncertain)["strength"] == 0.0


def test_backfill_survives_missing_evidence(engine):
    orphan = _seed(engine, source=ss.HEURISTIC_SOURCE, polarity=1, evidence=None)

    _rerun(engine)

    assert _row(engine, orphan)["strength"] == ss.UNKNOWN


def test_backfill_leaves_evidence_and_polarity_untouched(engine):
    evidence = {"match": "token_overlap", "overlap_ratio": 1.167}
    signal_id = _seed(engine, source=ss.HEURISTIC_SOURCE, polarity=1, evidence=evidence)
    before = _row(engine, signal_id)

    _rerun(engine)

    after = _row(engine, signal_id)
    assert after["evidence"] == before["evidence"]
    assert after["polarity"] == before["polarity"]
    assert after["strength"] != before["strength"]


def test_backfill_is_idempotent(engine):
    signal_id = _seed(
        engine,
        source=ss.HEURISTIC_SOURCE,
        polarity=1,
        evidence={"match": "token_overlap", "overlap_ratio": 1.167},
    )

    _rerun(engine)
    once = _row(engine, signal_id)["strength"]
    _rerun(engine)
    twice = _row(engine, signal_id)["strength"]

    assert once == twice


def test_backfill_does_not_rerun_once_stamped(engine):
    """The version guard, not the recompute, is what makes the second boot free."""
    signal_id = _seed(
        engine, source=ss.HEURISTIC_SOURCE, polarity=1, evidence={"match": "node_id"}
    )
    _rerun(engine)

    engine.db.conn.execute("UPDATE signals SET strength = 0.123 WHERE id = ?", (signal_id,))
    engine.db.conn.commit()
    engine._migrate_signal_strength()

    assert _row(engine, signal_id)["strength"] == 0.123
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/test_signal_strength_backfill.py -q > /tmp/218-t6-red.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t6-red.txt
tail -10 /tmp/218-t6-red.txt
```

Expected: 7 failed with `AttributeError: 'MemoryEngine' object has no attribute
'_migrate_signal_strength'`.

- [ ] **Step 3: Add the version constant**

In `src/ormah/engine/memory_engine.py`, after `LIFECYCLE_MODEL_VERSION = 2` (line 61):

```python
# Evidence-ladder version for signals.strength (#218). Bump when the ladder's
# values or mappings change, so a stamped store recomputes from its evidence.
SIGNAL_STRENGTH_LADDER_VERSION = 1
```

- [ ] **Step 4: Add the migration**

Add this method to `MemoryEngine`, next to `_migrate_fsrs`:

```python
    def _migrate_signal_strength(self) -> None:
        """Recompute signals.strength onto the #218 ordinal evidence ladder.

        Exact rather than estimated: every row carries the evidence its own channel
        needs, and the judge stamps the min_confidence in force when the row was
        written -- so a row recomputes to what it would have stored had the ladder
        existed then, not to what today's settings would produce.

        Re-runnable by construction: evidence is never written, so a later revision
        of the ladder recomputes from the same untouched source. Only strength moves.

        No file_store call, so this does not take db-lock before memory-lock and
        stays outside the ordering hazard documented on _record_confirmed_use.
        """
        stamp = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'signal_strength_ladder_version'"
        ).fetchone()
        try:
            version = int(stamp["value"]) if stamp else 0
        except (TypeError, ValueError):
            version = 0
        if version >= SIGNAL_STRENGTH_LADDER_VERSION:
            return

        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id, source, polarity, evidence FROM signals").fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE signals SET strength = ? WHERE id = ?",
                    (
                        signal_strength.strength_from_evidence(
                            row["source"], row["polarity"], row["evidence"]
                        ),
                        row["id"],
                    ),
                )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES "
                "('signal_strength_ladder_version', ?)",
                (str(SIGNAL_STRENGTH_LADDER_VERSION),),
            )
        logger.info(
            "Recomputed strength on %d signal rows (#218 ladder v%d)",
            len(rows),
            SIGNAL_STRENGTH_LADDER_VERSION,
        )
```

- [ ] **Step 5: Call it from `startup()`**

In `startup()`, immediately after `self._migrate_fsrs()`:

```python
        # One-time FSRS data migration: seed stability from access patterns
        self._migrate_fsrs()
        self._migrate_signal_strength()
```

It runs before the server serves, alongside the other one-time migrations.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/test_signal_strength_backfill.py -q > /tmp/218-t6-green.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t6-green.txt
tail -5 /tmp/218-t6-green.txt
```

Expected: `PYTEST_EXIT=0`, 7 passed.

- [ ] **Step 7: Run the whole suite under the import gate**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q \
  > /tmp/218-final.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-final.txt
tail -10 /tmp/218-final.txt
```

Expected: the import path contains `ormah-wt-218/`, `PYTEST_EXIT=0`, and a passing count equal to
Task 1's baseline **plus 39** (19 + 6 + 2 + 5 + 7 new tests). A count below baseline is a
regression, not a flake — find it before reporting done.

- [ ] **Step 8: Lint and commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
git add src/ormah/engine/memory_engine.py tests/test_engine/test_signal_strength_backfill.py
git commit -m "fix(signals): backfill historical strength onto the #218 ladder

Existing rows keep pre-ladder values, and the token_overlap rows pinned at 0.85
land inside the new judge band -- so the column would go on lying, now about
which channel produced the row.

The recompute is exact rather than estimated: no signals row lacks evidence,
heuristic rows carry match and overlap_ratio, and judge rows carry the
min_confidence in force when they were written. evidence is never touched, so
the migration is re-runnable if the ladder is later revised.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 9: Report the island's state**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
git log --oneline upstream/main..HEAD
```

Expected: exactly five commits, all yours (Tasks 2–6). Anything else in that log means the island
was cut from the wrong base — rebuild it before pushing. Do **not** push or open a PR in this
plan; that is a separate decision.
