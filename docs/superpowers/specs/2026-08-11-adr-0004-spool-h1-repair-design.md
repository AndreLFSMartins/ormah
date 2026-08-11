# ADR-0004 — repairing the two defects that break H1 in the ingest spool

**Date:** 2026-08-11 · **Branch:** `fix/adr4-spool-h1` (worktree `Tools/ormah-wt-adr4-h1`, cut from `local-main`)
**Source of the diagnosis:** `docs/adr/0004-async-ingest-nudge-server-cursor.md`, Amendment 2026-08-11 (commit `b02592f`)

## Problem

H1 — *an outage must never discard real data* — is the rule the spool's failure classing exists
to serve. Both halves of that classing are wrong in the code as shipped, and they compose into a
queue that neither retries nor records. Production, 2026-08-11: 1040 occurrences of
`Ingest drain run error: int too large to convert to float` across 8 jobs, ended only by manual
deletion of the queue.

This spec repairs the two defects. It does not revisit the diagnosis — that work is closed in the
ADR amendment and must not be re-derived.

### Defect 1 — the backoff cap guards the product, not the arithmetic

```python
delay = min(_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), _BACKOFF_MAX_SECONDS)  # ingest_spool.py:247
```

`2 ** (attempts - 1)` is an arbitrary-precision `int`; `min(…, 300.0)` only ever sees the product.
Past attempt 1024 the float multiplication raises before any capping happens, and it raises *before*
`self._write_job(name, payload, _PENDING)` (`:272`) — so **no retry is ever persisted**. This is not
a cap that dead-letters; it is a break that strands. At the 300 s ceiling, attempt 1025 arrives after
roughly 3.5 days of continuous retry, so any genuine provider outage of that length hits the same
wall.

Reproduced by execution: `attempts=1024 → 300.0`, `attempts=1025 → OverflowError: int too large to
convert to float`.

### Defect 2 — a deleted transcript is classed as an external failure

```python
except OSError as e:
    logger.warning("Cannot read %s: %s", path, e)   # session_watcher.py:879
    return IngestResult.TRANSIENT                   # :880
```

`FileNotFoundError` is an `OSError`, so a permanently deleted transcript is indistinguishable from
`EIO`/`EACCES` and becomes `TRANSIENT` → `requeue(job, failure_class="external")` → retried forever.
`requeue`'s own docstring says the opposite in as many words: *"deterministic (malformed job,
**transcript deleted**, path no longer under any watch root): a retry cannot change the outcome, so
the job is dead-lettered immediately"* (`ingest_spool.py:241-242`). This is what fed the 8 jobs to
attempt 1025.

### Not in scope

The re-admission loop (`session_watcher.py:1419-1420` → `recover` → `pending/`) is a third-order
consequence, not a separate defect: it disappears once the arithmetic stops raising. The ADR is
explicit that adding machinery there would treat the symptom. **No change is made for it.**

## Constraints discovered before designing

Each was verified against the tree at `b4f6ac0`, not assumed:

1. **`ingest_spool.py` does not exist in `upstream/main`.** The whole spool is `local-main`-only
   code. Defect 1 therefore has no upstream contribution path today, and FORK-WORKFLOW Recipe A
   (branch cut from `upstream/main`) is impossible for it. The branch is cut from `local-main`.
2. **Defect 2's `try/except` block is byte-identical at `upstream/main:755-764`.** It is
   contributable — but upstream has no spool, no `failure_class`, and no dead-letter, so the fix
   has a different shape there. That PR is a separate piece of work, deliberately not attempted
   here.
3. **`IngestResult` is identical local and upstream** (`OK` / `NO_PROGRESS` / `TRANSIENT`). There is
   no deterministic member to reuse.
4. **`_ingest_session` has exactly one call site** (`session_watcher.py:1452`) and `IngestResult` is
   confined to `session_watcher.py` within `src/`. A new enum member costs one branch in one place.
5. **`NO_PROGRESS` is not a usable substitute.** Its drain path falls through to
   `self.spool.complete(job)` (`:1499`) unless `_idle_with_unsafe_tail` or `shrink_pending` holds —
   i.e. the job would vanish with no dead-letter record, which is the opposite of the contract.
6. **A false-positive `ENOENT` is self-healing on discovering roots.** `reconcile()` does a
   disk-truth `rglob("*.jsonl")` and re-enqueues any transcript whose cursor sits behind EOF
   (`:1594-1611`), with `enqueue` idempotent per `(path, boundary)`. A transcript that briefly
   disappears and returns is picked up again.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Fix both defects, overflow first | Fixing only the classing leaves the 3.5-day wall armed for the exact scenario ADR-0004 exists to protect |
| D2 | Work in a worktree cut from `local-main` | The only base where defect 1 compiles; Golden rule 1 forbids `checkout` in `Tools/ormah`, which the running Beta serves |
| D3 | Dead-letter a deleted transcript immediately | It is the contract `requeue` already declares; the ADR rejects extra machinery; the dead-letter *preserves* the payload in `failed/` with an `.error` sidecar, so it is a record, not a destruction |
| D4 | Clamp the exponent; leave `min()` as the authority | Smallest change that removes the raise, and behaviour-preserving for every attempt count that previously computed |

Accepted with D3: on an acceptance-only root (`discover=False`) the `reconcile` sweep never runs
(`:1571-1572`), so there is no safety net for a false-positive `ENOENT` there. Branching policy per
root type is outside ADR-0004's scope and was declined.

## The change

### `src/ormah/background/ingest_spool.py`

A new constant beside the existing backoff constants (`:36-37`), and the clamp at `:247`:

```python
shift = min(attempts - 1, _BACKOFF_MAX_SHIFT)
delay = min(_BACKOFF_BASE_SECONDS * (2 ** shift), _BACKOFF_MAX_SECONDS)
```

`_BACKOFF_MAX_SHIFT = 62`. With base `2.0` and ceiling `300.0` the delay saturates at shift 8
(`2.0 × 2**8 = 512 > 300`), so **any** clamp at or above 8 returns exactly the same `min(...)` for
every attempt count that used to compute — the clamp is behaviour-preserving by construction, not by
measurement. 62 keeps the product (~9.2 × 10¹⁸) far below the float maximum while leaving the outer
`min()` as the single authority over the value, so the clamp does not silently become wrong if the
constants are retuned. The only behaviour that changes is where it was already broken: attempts
≥ 1025 now yields 300.0 instead of raising.

### `src/ormah/background/session_watcher.py`

A new enum member:

```python
GONE = "gone"   # the transcript no longer exists -> deterministic, dead-letter, never retry
```

A more specific handler placed **before** the existing `except OSError` (`:876-880`), and the same
treatment for the `path.stat()` immediately below (`:881-885`), which loses the same race:

```python
except FileNotFoundError:
    return IngestResult.GONE
except OSError as e:
    logger.warning("Cannot read %s: %s", path, e)
    return IngestResult.TRANSIENT
```

And one branch at the single call site, before the `TRANSIENT` check (`:1458`):

```python
if result is IngestResult.GONE:
    self.spool.requeue(job, failure_class="transcript_deleted")
    return
```

`requeue` already dead-letters every `failure_class` other than `"external"`, so **`requeue` itself
is not modified**. `EIO`/`EACCES` remain `TRANSIENT` and keep retrying forever, as H1 requires.

## Tests

TDD: each test must fail first, and fail for the stated reason — a green test imported from another
base has already hidden a defect once in this project's history.

| test | file | must first fail with | passes when |
|---|---|---|---|
| `test_requeue_external_backoff_saturates_instead_of_overflowing` | `tests/test_background/test_ingest_spool.py` | `OverflowError: int too large to convert to float` | `attempts` 1025 persisted, `not_before ≈ now + 300`, `pending_count() == 1`, `failed/` empty |
| `test_deleted_transcript_is_dead_lettered_not_retried_forever` | `tests/test_background/test_session_watcher.py` | job returns to `pending/` as `external` | one job in `failed/` with `transcript_deleted` in the `.error` sidecar, `pending/` empty |

The first follows the existing pattern of rewriting `not_before`/`attempts` in the on-disk payload to
advance the state without sleeping (`test_ingest_spool.py:195-199`). The second uses the
`_handler_with_spool` harness already present at `test_session_watcher.py:206`.

Regression guard: `test_requeue_external_retries_forever_with_persisted_growing_backoff` (`:167`) and
`test_requeue_deterministic_failure_dead_letters_with_original_bytes` (`:303`) must both stay green —
they pin the two contracts this change sits between.

## Risks

- **Assumed, to be verified during implementation:** that `_file_hash` and `path.stat()` are the only
  places a deleted transcript surfaces as `FileNotFoundError` on the drain path. If the parser below
  also raises it, that path lands in a different `except` and stays misclassified. This is checked in
  implementation, not treated as settled.
- **Verified:** acceptance-only roots have no `reconcile` net (see D3).
- **Verified:** the branch carries `local-main`'s private docs, so `.git/hooks/pre-push` (fail-closed,
  shared by all worktrees) will reject pushing it to `fork`. The work stays local; the upstream PR for
  defect 2 needs its own branch from `upstream/main`.
