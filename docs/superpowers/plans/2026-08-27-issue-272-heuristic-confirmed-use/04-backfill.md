# Task 4: Backfill the Rows the Defect Already Wrote

**Depends on:** Task 1 only. May run in parallel with Tasks 2 and 3.
**Read `00-overview.md` first — its Global Constraints apply.**

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (`:66` version constant, `:167` call site, new method after `_migrate_signal_strength` ends at `:259`)
- Test: `tests/test_engine/test_confirmed_use_contract.py`

**Interfaces:**
- Consumes: `HEURISTIC_CONFIRM_FLOOR` and the `strength=` parameter on `_claim_confirmed_use` (Task 1).
- Produces: nothing for later tasks.

## Background

The defect already ran in production. Tasks 1–3 fix future whispers; the exact-match rows already in
`signals` would stay unclaimed forever, because the gate runs at write time. Expected volume on the
measured store (2026-08-26): **42 pairs** — 29 `node_id`, 13 `sentence`, 0 `title` — out of 1,629. The
1,587 `token_overlap` rows are correctly left alone.

## Two rules this migration must not break

1. **It must run AFTER `_migrate_signal_strength`.** This migration reads `signals.strength`, and that
   is the migration which normalises the column onto the ladder. Running first would compare pre-ladder
   values against a ladder-derived floor.
2. **Reinforcement runs after the transaction commits.** `_record_confirmed_use` does file I/O; calling
   it inside would take `db_lock` before `memory_lock` (#220 §4.3).

## Why a rescan, not a one-time stamp

Copied from `_migrate_signal_strength`'s reasoning, which applies unchanged: a one-time stamp cannot
repair what an OLD binary writes AFTER the stamp is set — a rollback then re-upgrade, or the second
unmanaged server process of #238. Those rows would stay unclaimed forever on a table the stamp calls
migrated.

---

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_engine/test_confirmed_use_contract.py`:

```python
def _seed_heuristic_signal(engine, node_id, whisper_log_id, strength, match="node_id"):
    """Write a positive heuristic signal row as the pre-#272 code would have."""
    engine.db.conn.execute(
        """
        INSERT INTO signals
            (whisper_log_id, node_id, signal_type, polarity, strength, source,
             session_id, surface, space, prompt_hash, evidence, created)
        VALUES (?, ?, 'whisper_referenced', 1, ?, 'transcript_watcher_heuristic',
                's1', 'transcript', 'myproject', 'h', ?, datetime('now'))
        """,
        (whisper_log_id, node_id, strength, json.dumps({"match": match})),
    )
    engine.db.conn.commit()


def test_backfill_claims_and_reinforces_historical_verbatim_rows(engine):
    """#272 D4: the rows the defect already wrote are repaired at boot."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)
    _seed_heuristic_signal(engine, target, log_id, strength=0.98)

    before = _snapshot(engine, target)
    engine._migrate_heuristic_confirmed_use()

    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ? AND node_id = ?",
        (log_id, target),
    ).fetchone()
    assert claim is not None, "the backfill claimed nothing"
    assert _snapshot(engine, target) != before, "the backfill claimed but did not reinforce"


def test_backfill_is_idempotent(engine):
    """#272 D4: a second boot must not reinforce the same event again."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)
    _seed_heuristic_signal(engine, target, log_id, strength=0.98)

    engine._migrate_heuristic_confirmed_use()
    after_first = _snapshot(engine, target)

    engine._migrate_heuristic_confirmed_use()

    assert _snapshot(engine, target) == after_first, "the backfill reinforced twice"


@pytest.mark.parametrize("strength,match", [(0.40, "token_overlap"), (0.7799, "token_overlap")])
def test_backfill_skips_rows_below_the_floor(engine, strength, match):
    """#272 D4: the backfill uses the same floor as the live path."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)
    _seed_heuristic_signal(engine, target, log_id, strength=strength, match=match)

    before = _snapshot(engine, target)
    engine._migrate_heuristic_confirmed_use()

    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ?", (log_id,)
    ).fetchone()
    assert claim is None, "a below-floor row was backfilled"
    assert _snapshot(engine, target) == before


def test_backfill_skips_a_never_injected_event(engine):
    """#272 D4: was_injected = 1 is the provenance test the claim helper enforces.

    A memory the agent never saw cannot have been used, however the signal reads.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)
    engine.db.conn.execute("UPDATE whisper_log SET was_injected = 0 WHERE id = ?", (log_id,))
    engine.db.conn.commit()
    _seed_heuristic_signal(engine, target, log_id, strength=0.98)

    before = _snapshot(engine, target)
    engine._migrate_heuristic_confirmed_use()

    assert _snapshot(engine, target) == before, "a non-injected event was backfilled"


def test_backfill_skips_an_already_claimed_event(engine):
    """#272 D4: an event confirmed through another caller must not reinforce twice."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)
    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)
    _seed_heuristic_signal(engine, target, log_id, strength=0.98)

    after_feedback = _snapshot(engine, target)
    engine._migrate_heuristic_confirmed_use()

    assert _snapshot(engine, target) == after_feedback, "an already-claimed event reinforced again"


def test_backfill_cutoff_advances_to_the_highest_processed_id(engine):
    """#272 D4: the cutoff advances by processed id, never to MAX(id).

    Same defence-in-depth _migrate_signal_strength documents: a row committed by
    another writer between the SELECT and the stamp must not be skipped forever.
    A below-floor row is still 'processed' — it was examined and rejected.
    """
    strong, weak = _make_nodes(engine, count=2)
    strong_log = _seed_whisper_log(engine, strong, prompt="caching strong")
    _seed_heuristic_signal(engine, strong, strong_log, strength=0.98)
    # Seeded LAST and below the floor: the cutoff must still clear it, or the scan
    # window would grow forever on a store whose newest rows are all token_overlap.
    weak_log = _seed_whisper_log(engine, weak, prompt="caching weak")
    _seed_heuristic_signal(engine, weak, weak_log, strength=0.40, match="token_overlap")

    highest = engine.db.conn.execute(
        "SELECT MAX(id) AS m FROM signals WHERE source = 'transcript_watcher_heuristic'"
    ).fetchone()["m"]

    engine._migrate_heuristic_confirmed_use()

    cutoff = engine._meta_int("heuristic_confirmed_use_cutoff")
    assert cutoff == highest, (
        f"cutoff {cutoff} stopped short of the last processed id {highest} — "
        "a below-floor row was examined but not counted as processed"
    )
    assert engine._meta_int("heuristic_confirmed_use_version") == 1


def test_backfill_isolates_one_nodes_failure(engine):
    """#272 D4: one unreadable node must not cost every later node its repair."""
    first, second = _make_nodes(engine, count=2)
    for node_id in (first, second):
        log_id = _seed_whisper_log(engine, node_id, prompt=f"caching {node_id}")
        _seed_heuristic_signal(engine, node_id, log_id, strength=0.98)

    before_second = _snapshot(engine, second)
    real = engine._record_confirmed_use

    def flaky(node_id):
        if node_id == first:
            raise ZeroDivisionError("simulated mutator failure")
        return real(node_id)

    with patch.object(engine, "_record_confirmed_use", side_effect=flaky):
        engine._migrate_heuristic_confirmed_use()

    assert _snapshot(engine, second) != before_second, "node 2 lost its backfill"
```

Add `import json` to the test file's imports if it is not already there.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_engine/test_confirmed_use_contract.py -k backfill -v
```

Expected: FAIL — `AttributeError: 'MemoryEngine' object has no attribute '_migrate_heuristic_confirmed_use'`.

- [ ] **Step 3: Add the version constant**

In `memory_engine.py`, after `SIGNAL_STRENGTH_LADDER_VERSION` at `:66`:

```python
# Backfill version for the #272 heuristic confirmed-use repair. Bump to force a full
# re-scan when the floor or the selection changes.
HEURISTIC_CONFIRMED_USE_VERSION = 1
```

- [ ] **Step 4: Write the migration**

Add this method immediately after `_migrate_signal_strength` ends (`:259`, before `_migrate_fsrs`):

```python
    def _migrate_heuristic_confirmed_use(self) -> None:
        """Claim and reinforce heuristic rows the pre-#272 code left unclaimed.

        The heuristic detector recorded positive signals for years without ever taking
        a confirmed-use claim, because only the judge block called the helper. Those
        rows are evidence of real use that never reached the lifecycle. This repairs
        the ones whose evidence clears HEURISTIC_CONFIRM_FLOOR.

        MUST run after _migrate_signal_strength: it reads signals.strength, and that
        migration is what normalises the column onto the ladder. Running first would
        test pre-ladder values against a ladder-derived floor.

        Rescans on every boot rather than stamping once, for the reason
        _migrate_signal_strength documents: an old binary -- a rollback, or the second
        unmanaged process of #238 -- can write pre-fix rows AFTER a one-time stamp, and
        they would stay unclaimed forever on a table the stamp calls migrated.

        The claims are taken inside one transaction and the reinforcement runs after it
        commits: _record_confirmed_use does file I/O, so calling it inside would hold
        the process-wide write lock across N markdown saves and take db_lock before
        memory_lock, inverting the order every serialized writer uses (#220 4.3).
        """
        version = self._meta_int("heuristic_confirmed_use_version")
        lower_bound = (
            self._meta_int("heuristic_confirmed_use_cutoff")
            if version >= HEURISTIC_CONFIRMED_USE_VERSION
            else 0
        )

        confirmed_node_ids: list[str] = []
        with self.db.transaction() as conn:
            # The floor is applied in Python, not in the WHERE, so the cutoff can advance
            # over EVERY row examined. Filtering in SQL would leave the cutoff pinned to
            # the id of the last above-floor row, and since 97% of heuristic rows are
            # below it, the scan window would grow without bound — and would never
            # advance at all on a store whose newest heuristic rows are all token_overlap.
            rows = conn.execute(
                """
                SELECT s.id, s.whisper_log_id, s.node_id, s.strength
                FROM signals s
                JOIN whisper_log wl ON wl.id = s.whisper_log_id
                WHERE s.id > ?
                  AND s.source = ?
                  AND s.polarity = 1
                  AND wl.was_injected = 1
                ORDER BY s.id ASC
                """,
                (lower_bound, signal_strength.HEURISTIC_SOURCE),
            ).fetchall()
            processed_max = lower_bound
            for row in rows:
                if row["strength"] >= HEURISTIC_CONFIRM_FLOOR and self._claim_confirmed_use(
                    conn,
                    row["whisper_log_id"],
                    row["node_id"],
                    signal=1,
                    source="auto_heuristic",
                    strength=row["strength"],
                ):
                    confirmed_node_ids.append(row["node_id"])
                processed_max = max(processed_max, row["id"])
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES "
                "('heuristic_confirmed_use_version', ?)",
                (str(HEURISTIC_CONFIRMED_USE_VERSION),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES "
                "('heuristic_confirmed_use_cutoff', ?)",
                (str(processed_max),),
            )

        # Isolated per node: the claims are committed, so letting one failure escape
        # would abandon every later node with its claim taken and nothing to retry it.
        for node_id in confirmed_node_ids:
            try:
                self._record_confirmed_use(node_id)
            except Exception:
                logger.exception("confirmed-use backfill failed for node %s", node_id)

        if confirmed_node_ids:
            logger.info(
                "Backfilled confirmed use on %d heuristic events above id %d (#272)",
                len(confirmed_node_ids),
                lower_bound,
            )
```

The row's own `strength` is passed to the claim rather than the floor constant: the helper's gate is
then evaluating the same number the Python guard did, so the two cannot disagree if the floor moves.
The redundancy is deliberate — the guard keeps the loop honest about what it counted as processed, and
the helper stays the single authority on what confirms.

- [ ] **Step 5: Call it at boot, in the right order**

At `:167`, immediately after `self._migrate_signal_strength()`:

```python
        self._migrate_fsrs()
        self._migrate_signal_strength()
        # MUST follow _migrate_signal_strength — it reads the column that migration
        # normalises onto the ladder (#272).
        self._migrate_heuristic_confirmed_use()
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_engine/test_confirmed_use_contract.py -v 2>&1 | tail -30
```

Expected: PASS, all six new tests plus every pre-existing contract.

- [ ] **Step 7: Run the full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -20
```

- [ ] **Step 8: Lint and commit**

```bash
make lint
git add src/ormah/engine/memory_engine.py tests/test_engine/test_confirmed_use_contract.py
git commit -m "fix(feedback): backfill the confirmed use the heuristic never claimed (#272)

The defect already ran in production, and the gate runs at write time, so the
verbatim heuristic rows already in signals would stay unclaimed forever. A boot
migration repairs them, using the same floor and the same at-most-once claim as
the live path.

It rescans rather than stamping once, for the reason _migrate_signal_strength
documents: an old binary can write pre-fix rows after a one-time stamp. It must
run after that migration, which is what puts signals.strength on the ladder this
one reads."
```
