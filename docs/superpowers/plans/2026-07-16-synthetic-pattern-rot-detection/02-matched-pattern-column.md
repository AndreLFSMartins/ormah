# Task 2: record which pattern fired in `whisper_decisions`

**Files:**
- Modify: `src/ormah/index/schema.sql:222-238`
- Modify: `src/ormah/index/db.py` (new `_migrate_whisper_decisions_schema`, called from `_migrate()` near L254)
- Modify: `src/ormah/engine/context_builder.py:293-327` (`_log_decision`)
- Modify: `src/ormah/engine/memory_engine.py:1257-1273` (`note_synthetic_whisper_skip`)
- Modify: `src/ormah/api/routes_agent.py` (pass `matched_pattern=matched`)
- Test: `tests/test_engine/test_whisper_context.py`
- Test: `tests/test_index/` (migration test — see Step 6)

**Interfaces:**
- Consumes: `match_synthetic_pattern(...) -> str | None` from task 1, bound to local `matched` at `routes_agent.py`.
- Produces: column `whisper_decisions.matched_pattern TEXT` (NULL except on `silent_synthetic` rows), holding the regex source. Task 3 reads it with `SELECT matched_pattern, MAX(logged_at) ... GROUP BY matched_pattern`.

**Why `whisper_decisions` and not a new table:** it is already one-row-per-call, already receives `silent_synthetic` (`memory_engine.py:1270`), and is already indexed on `logged_at` — which is exactly what the rot query needs. The table stores `prompt_hash` only, never prompt text (`schema.sql:221`); this column does not change that.

---

- [ ] **Step 1: Write the failing test**

Append to class `TestSyntheticPromptEndpoint` in `tests/test_engine/test_whisper_context.py`. This needs a **real** engine (the class's mocked engine cannot write rows) — use the `engine` fixture from `tests/conftest.py:132-137`:

```python
def test_boundary_records_which_builtin_pattern_fired(engine):
    """Rot detection is impossible without knowing WHICH pattern matched (#143)."""
    engine.note_synthetic_whisper_skip(
        prompt="<task-notification>done",
        session_id="s-1",
        matched_pattern=r"<task-notification>",
    )
    row = engine.db.conn.execute(
        "SELECT outcome, matched_pattern FROM whisper_decisions WHERE session_id = 's-1'"
    ).fetchone()
    assert row["outcome"] == "silent_synthetic"
    assert row["matched_pattern"] == r"<task-notification>"


def test_boundary_records_an_operator_pattern_verbatim(engine):
    engine.note_synthetic_whisper_skip(
        prompt="BATCH JOB 7", session_id="s-2", matched_pattern=r"BATCH JOB",
    )
    row = engine.db.conn.execute(
        "SELECT matched_pattern FROM whisper_decisions WHERE session_id = 's-2'"
    ).fetchone()
    assert row["matched_pattern"] == r"BATCH JOB"


def test_non_synthetic_decisions_leave_matched_pattern_null(engine):
    """Only silent_synthetic rows carry a pattern; everything else stays NULL."""
    engine.context_builder._log_decision(
        session_id="s-3", space=None, prompt="a human prompt",
        intent=None, outcome="silent_short",
    )
    row = engine.db.conn.execute(
        "SELECT matched_pattern FROM whisper_decisions WHERE session_id = 's-3'"
    ).fetchone()
    assert row["matched_pattern"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_engine/test_whisper_context.py -k "matched_pattern or which_builtin" -v`
Expected: FAIL — `TypeError: note_synthetic_whisper_skip() got an unexpected keyword argument 'matched_pattern'`

- [ ] **Step 3: Add the column for fresh installs**

In `src/ormah/index/schema.sql`, in the `whisper_decisions` table (L222-236), add the column **last, after `logged_at`** — matching where `ALTER TABLE` puts it on migrated DBs, so fresh and migrated schemas agree:

```sql
    candidate_count INTEGER DEFAULT 0,  -- results returned by search before filtering
    injected_count  INTEGER DEFAULT 0,  -- memories actually injected
    max_gate_score  REAL,               -- best absolute gate score among candidates
    logged_at       TEXT NOT NULL,
    matched_pattern TEXT                -- synthetic pattern source that fired;
                                        -- NULL unless outcome='silent_synthetic' (#143)
);
```

- [ ] **Step 4: Add the migration for existing DBs**

In `src/ormah/index/db.py`, add this method next to `_migrate_whisper_log_schema` (L313), following its exact idiom:

```python
    def _migrate_whisper_decisions_schema(self, conn: sqlite3.Connection) -> None:
        """Record which synthetic pattern fired, so rot detection has a signal (#143)."""
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(whisper_decisions)").fetchall()
        }
        if "matched_pattern" not in cols:
            conn.execute("ALTER TABLE whisper_decisions ADD COLUMN matched_pattern TEXT")
```

Then call it inside `_migrate()` (the method spanning L129-278), right after the existing pair at L254-255:

```python
            self._migrate_whisper_log_schema(conn)
            self._migrate_retrieval_event_schema(conn)
            self._migrate_whisper_decisions_schema(conn)
```

This is safe on a DB where `whisper_decisions` does not exist yet: `init_schema()` (L91) runs `executescript(schema)` — which has `CREATE TABLE IF NOT EXISTS` — before calling `_migrate()`.

- [ ] **Step 5: Thread the value through the three layers**

`src/ormah/engine/context_builder.py`, `_log_decision` (L293-327) — add the parameter and the column:

```python
    def _log_decision(
        self,
        *,
        session_id: str | None,
        space: str | None,
        prompt: str,
        intent,
        outcome: str,
        candidate_count: int = 0,
        injected_count: int = 0,
        max_gate_score: float | None = None,
        matched_pattern: str | None = None,
    ) -> None:
```

and inside the `try`, replace the INSERT with:

```python
                conn.execute(
                    "INSERT INTO whisper_decisions "
                    "(session_id, space, prompt_hash, intent, outcome, "
                    "candidate_count, injected_count, max_gate_score, logged_at, "
                    "matched_pattern) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (session_id, space, prompt_hash, intent_str, outcome,
                     candidate_count, injected_count, max_gate_score,
                     datetime.now(timezone.utc).isoformat(), matched_pattern),
                )
```

`src/ormah/engine/memory_engine.py`, `note_synthetic_whisper_skip` (L1257-1273) — add the parameter and forward it (keep the existing docstring, append the last line):

```python
    def note_synthetic_whisper_skip(
        self,
        prompt: str,
        space: str | None = None,
        session_id: str | None = None,
        matched_pattern: str | None = None,
    ) -> None:
```

```python
        self.context_builder._log_decision(
            session_id=session_id, space=space, prompt=prompt,
            intent=None, outcome="silent_synthetic",
            matched_pattern=matched_pattern,
        )
```

`src/ormah/api/routes_agent.py` — in the block task 1 wrote, pass the local through:

```python
            await anyio.to_thread.run_sync(
                lambda: engine.note_synthetic_whisper_skip(
                    prompt=prompt, space=space, session_id=session_id,
                    matched_pattern=matched,
                )
            )
```

- [ ] **Step 6: Write the migration test**

Create `tests/test_index/test_whisper_decisions_migration.py`:

```python
"""The matched_pattern column must appear on pre-#143 databases too."""

from __future__ import annotations

from ormah.index.db import Database


def test_migration_adds_matched_pattern_to_an_existing_db(tmp_path):
    db_path = tmp_path / "old.db"  # Database.__init__ takes a Path, not a str (db.py:21)

    # A pre-#143 whisper_decisions: same shape, no matched_pattern.
    legacy = Database(db_path)
    with legacy.transaction() as conn:
        conn.execute("DROP TABLE IF EXISTS whisper_decisions")
        conn.execute(
            "CREATE TABLE whisper_decisions ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, space TEXT,"
            "  prompt_hash TEXT NOT NULL, intent TEXT, outcome TEXT NOT NULL,"
            "  candidate_count INTEGER DEFAULT 0, injected_count INTEGER DEFAULT 0,"
            "  max_gate_score REAL, logged_at TEXT NOT NULL)"
        )
    legacy.close()

    migrated = Database(db_path)  # Path, never str — db.py:23 calls db_path.parent.mkdir()
    migrated.init_schema()
    cols = {
        row[1]
        for row in migrated.conn.execute("PRAGMA table_info(whisper_decisions)").fetchall()
    }
    migrated.close()

    assert "matched_pattern" in cols
```

`Database.__init__(db_path: Path)` is at `db.py:21`, `init_schema()` at `:91`, and `close()` at `:682` — all three exist as used above. `init_schema()` runs `executescript(schema)` and then `_migrate()`, which is what makes the second open perform the migration.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_engine/test_whisper_context.py tests/test_index/test_whisper_decisions_migration.py -v`
Expected: PASS

- [ ] **Step 8: Run the full suite — this task edits a shared write path**

Run: `make test`
Expected: no new failures. `_log_decision` is called from every whisper outcome; a broken INSERT here breaks all of them. Compare against the pre-task baseline; `tests/test_engine/test_whisper_context.py` has the densest coverage of this path.

- [ ] **Step 9: Lint and commit**

```bash
make lint
git add src/ormah/index/schema.sql src/ormah/index/db.py \
        src/ormah/engine/context_builder.py src/ormah/engine/memory_engine.py \
        src/ormah/api/routes_agent.py tests/
git commit -m "feat(whisper): record which synthetic pattern fired in whisper_decisions (#143)"
```
