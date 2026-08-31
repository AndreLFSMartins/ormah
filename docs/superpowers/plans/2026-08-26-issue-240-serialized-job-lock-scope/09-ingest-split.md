# Task 9: split `ingest_conversation` extract from apply

Read `00-overview.md` first. Requires Task 1 only (uses `memory_operation()`, not the epoch — see below). Independent of Tasks 3–8.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` — `ingest_conversation` (`:2404-2483`)
- Test: `tests/test_engine/test_ingest.py` (append)

**Interfaces:**
- Consumes: `MemoryEngine.memory_operation()` (already exists, `:549`) — **not** `memory_operation_at`. `ingest_conversation` is not a scheduled background job; it is called synchronously from the API/CLI on a request thread, with no restore-epoch concept upstream. It gets the plain lock, scoped per item instead of for the whole call.
- Produces: nothing other tasks depend on.

## Why this one is different from Tasks 3–8

Every other task converts a job whose *whole run* held `L_mem`. `ingest_conversation` is not a job — it is one synchronous call, and the spec's fix here is narrower: **stop locking the extraction** (`_extract_memories_llm`, an LLM call — `:2494`) while still locking each apply correctly. `self.remember(req, ...)` (`:2478`) is already `@_serialized_memory_operation`, so removing the outer decorator does not unlock storage — it unlocks only the extraction and the dedup check.

**The debt this creates:** `_is_duplicate_memory` (`:2831`) reads outside the lock now. Two concurrent `ingest_conversation` calls extracting overlapping content can both read "not a duplicate" before either writes. Revalidate inside the same acquisition that calls `remember`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_engine/test_ingest.py`.

**Why two tests, and which one is the canary.** The first is the structural regression test —
it asserts *where the lock is held*, which is the entire change, and it fails today. The second
is the behavioural one from the spec (two concurrent ingests, one node); it also fails today,
but for a mechanical reason (see Step 2), and its lasting job is to prove that releasing the
lock did not open a duplicate window.

**A `threading.Barrier` must never sit inside `memory_operation()`.** That lock is a mutex:
only one thread is ever inside it, so a two-party barrier there can never be satisfied and
always times out. Every synchronisation point below is in the *unlocked* extraction phase.

```python
def test_extraction_runs_unlocked_and_dedup_stores_under_one_acquisition(engine):
    """The change, stated structurally: the LLM extraction stops holding L_mem, and the
    dedup check moves inside the same acquisition as the write it guards (#240)."""
    from tests.test_background.lock_probe import install_probe

    fake_llm_response = json.dumps({
        "memories": [{
            "content": "The team standardized on FastAPI for every new backend service",
            "type": "fact",
            "title": "FastAPI standard",
            "tags": [],
            "about_self": False,
        }]
    })

    probe = install_probe(engine)
    lock_held_during_extract = []
    lock_held_during_dedup = []

    real_extract = engine._extract_memories_llm
    real_is_duplicate = engine._is_duplicate_memory

    def watched_extract(content):
        lock_held_during_extract.append(probe.held)
        return real_extract(content)

    def watched_is_duplicate(content):
        lock_held_during_dedup.append(probe.held)
        return real_is_duplicate(content)

    engine._extract_memories_llm = watched_extract
    engine._is_duplicate_memory = watched_is_duplicate

    with patch(_LLM_PATCH, return_value=fake_llm_response):
        created = engine.ingest_conversation(
            content="A long enough conversation about backend architecture." * 5)

    assert created, "nothing was ingested — the fixture stopped exercising the store path"
    assert lock_held_during_extract == [False], "L_mem was held across the LLM extraction"
    assert lock_held_during_dedup, "the dedup check never ran"
    assert all(lock_held_during_dedup), "the dedup check ran outside the lock that guards the write"


def test_concurrent_ingests_of_the_same_content_create_one_node(engine):
    """Two ingests racing on the same content must still produce one node (#240).

    The barrier sits in the *extraction* phase, which this change makes unlocked, so both
    threads finish extracting before either reaches its apply step. That is the window the
    in-lock dedup revalidation has to close.
    """
    import threading

    fake_llm_response = json.dumps({
        "memories": [{
            "content": "The team standardized on FastAPI for every new backend service",
            "type": "fact",
            "title": "FastAPI standard",
            "tags": [],
            "about_self": False,
        }]
    })

    barrier = threading.Barrier(2)
    real_extract = engine._extract_memories_llm

    def synced_extract(content):
        result = real_extract(content)
        barrier.wait(timeout=10.0)  # both threads leave extraction together
        return result

    engine._extract_memories_llm = synced_extract
    errors: list[BaseException] = []

    def run():
        try:
            with patch(_LLM_PATCH, return_value=fake_llm_response):
                engine.ingest_conversation(
                    content="A long enough conversation about backend architecture." * 5)
        except BaseException as exc:  # noqa: BLE001 — the test asserts on what was raised
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20.0)

    assert not errors, f"an ingest raised: {errors}"
    assert not any(t.is_alive() for t in threads)
    rows = engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM nodes WHERE title = 'FastAPI standard'"
    ).fetchone()
    assert rows["c"] == 1
```

- [ ] **Step 2: Run them to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_engine/test_ingest.py -q -k "unlocked or concurrent"
```

Expected, each for its own reason:

- `..._extraction_runs_unlocked...`: `assert [True] == [False]` — today `@_serialized_memory_operation`
  wraps the whole call, so the extraction runs with `L_mem` held. This is the bug, stated directly.
- `..._concurrent_ingests...`: `BrokenBarrierError` collected in `errors` — today the whole call is
  serialised, so the second thread cannot even *enter* extraction until the first has finished the
  entire ingest, and the barrier times out. That failure is itself evidence of the bug: the two
  ingests are fully serialised end to end, LLM call included.

- [ ] **Step 3: Rewrite `ingest_conversation`**

Remove the decorator (`:2404`):

```python
    def ingest_conversation(
        self,
        content: str,
        space: str | None = None,
        agent_id: str | None = None,
        dry_run: bool = False,
        extra_tags: list[str] | None = None,
    ) -> list[dict] | str:
```

Replace the per-item dedup-and-store block (`:2440-2478`, from the `for mem in extracted:` loop's dedup check through the `remember` call) with:

```python
        created = []
        skipped = 0
        for mem in extracted:
            if not isinstance(mem, dict):
                continue
            mem_content = mem.get("content", "").strip()
            if not mem_content:
                continue

            try:
                node_type = NodeType(mem.get("type", "fact"))
            except ValueError:
                node_type = NodeType.fact

            mem_title = mem.get("title") or _generate_title(mem_content)

            # Default confidence for auto-ingested memories: 0.7
            confidence = mem.get("confidence", 0.7)

            tags = mem.get("tags", []) + ["auto-ingested"] + (extra_tags or [])

            if dry_run:
                # Dry run never writes, so a loose pre-check is fine here — there is
                # no race to revalidate against.
                if self._is_duplicate_memory(mem_content):
                    skipped += 1
                    continue
                created.append({
                    "title": mem_title,
                    "content": mem_content,
                    "type": node_type.value,
                    "tags": tags,
                    "about_self": mem.get("about_self", False),
                    "confidence": confidence,
                })
                continue

            # Dedup check and store must be one exclusive step: extraction ran
            # unlocked, so another concurrent ingest could have written the same
            # content since. Re-checking outside this lock would race the same
            # way the old whole-call lock accidentally prevented (#240).
            with self.memory_operation():
                if self._is_duplicate_memory(mem_content):
                    logger.debug("Skipping duplicate: %s", mem.get("title", mem_content[:40]))
                    skipped += 1
                    continue

                req = CreateNodeRequest(
                    content=mem_content,
                    type=node_type,
                    title=mem_title,
                    tags=tags,
                    space=space,
                    about_self=mem.get("about_self", False),
                    confidence=confidence,
                )
                node_id, _ = self.remember(req, agent_id=agent_id or "ingester")
            created.append({
                "node_id": node_id,
                "title": mem_title,
            })
```

`self.remember` stays inside `with self.memory_operation():` even though it is itself `@_serialized_memory_operation` — the same `RLock`, so the nesting is free, and it is what makes the dedup check and the store atomic as one unit.

- [ ] **Step 4: Run the whole ingest file**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_engine/test_ingest.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: all pass, ruff clean, including every pre-existing dry-run/confidence/truncation test in the file.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_ingest.py
git commit -m "fix(ingest): unlock extraction, revalidate dedup atomically with the write (#240)"
```
