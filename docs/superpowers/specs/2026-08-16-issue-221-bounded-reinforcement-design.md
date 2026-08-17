# Design — Issue #221: bound stability reinforcement and add a per-day cooldown

**Issue:** [r-spade/ormah#221](https://github.com/r-spade/ormah/issues/221)
**Landing order:** #220 (PR #234, open) → #222 (PR #235, open) → **#221** → #223
**Decision source:** #191 (closed design decision), transcribed in `docs/lifecycle/2026-08-14-issue-dossier.md` §4.
**Branch / worktree:** `fix/221-bounded-reinforcement` in `../ormah-wt-221`, cut from `upstream/main` @ `a28837b`.

## Problem

`_touch_access` (`src/ormah/engine/memory_engine.py:1936`) grows stability with an unbounded
spacing factor:

```python
retrievability = math.exp(-days_since / node.stability)
new_stability = node.stability * self.settings.fsrs_stability_growth * (retrievability ** -0.2)
```

Three defects follow:

1. **Unbounded spacing.** As `R → 0`, `R^-0.2 → ∞`. An `S=1` node touched after 30 days gets
   `R^-0.2 = 403.43`, so one event can take it from `S=1` to the `365` cap.
2. **Same-session compounding.** The `days_since >= 0.001` floor lets ten immediate touches
   produce `1.5^10 ≈ 57×` growth.
3. **Underflow crash.** For `t/S > ~745`, `math.exp(-t/S)` underflows to `0.0` and `0.0 ** -0.2`
   raises `ZeroDivisionError` (verified: `ZeroDivisionError: 0.0 cannot be raised to a negative
   power`). A node with `S = 0.5` untouched for 10,000 days reaches that state.

Separately, `exp(-t/S)` is written out three times — `memory_engine.py:1946`,
`decay_manager.py:57`, `importance_scorer.py:84` — so a curve change means editing three call
sites that can silently diverge.

## Decision (from #191)

```text
R       = exp(-t / S)                              # curve unchanged
spacing = min(R^-0.2, fsrs_spacing_cap)
S'      = min(S × (1 + g × S^-w × spacing), fsrs_max_stability)
g = 0.5   w = 0.5                                  # initial policy, configurable, not fitted
```

At most **one numeric stability increase per node per day**. Every use still advances the
recency/decay anchor, so the two timestamps must move independently.

Centralize the lifecycle math instead of duplicating formulas, and replace the boolean
migration flag with an integer lifecycle-model version.

Arithmetic verified before writing this spec (`/usr/bin/python3`, constants above):

| Acceptance criterion | Computed |
|---|---|
| `S=1`, 30 days | `spacing = 2.0` → `S' = 2.0` exactly |
| Closely spaced updates `S=1 → 365` | **74** updates (`t=1d` and `spacing=1` both give 74) |
| Old-node spacing | `t/S = 20000` → `2.0`, no exception |

## Changes

### 1. New module `src/ormah/lifecycle.py`

Pure functions, no I/O and no DB access, at the package root so `engine/` and `background/`
both import it without either depending on the other.

```python
def retrievability(days_since: float, stability: float) -> float
def spacing_factor(days_since: float, stability: float, cap: float) -> float
def reinforced_stability(stability: float, days_since: float, *, growth_factor: float,
                         growth_exponent: float, spacing_cap: float,
                         max_stability: float, initial_stability: float) -> float
def reinforcement_due(last_review: datetime | None, now: datetime,
                      cooldown_days: float) -> bool
```

**Underflow (AC2).** `spacing_factor` never computes `R` and then raises it to a negative
power. `R^-0.2 == exp(0.2 × t/S)` identically, so the helper works on the exponent directly and
returns `cap` as soon as `0.2 × t/S >= log(cap)` — `math.exp` is never called with a large
argument, and no intermediate underflows. Finite for any age.

**Zero stability.** `Node.stability` is `Field(ge=0.0)`, so `S = 0` is representable and
`exp(-t/0)` raises. Every helper falls back to `initial_stability` when `stability` is falsy.
(#220 adds an equivalent guard at the same site; see *Interaction with #220* below.)

Rounding stays as today: `round(min(new_stability, max_stability), 2)`.

### 2. `src/ormah/engine/memory_engine.py` — `_touch_access`

The inline math goes away. The function becomes:

1. Always: `last_accessed = now`, `access_count += 1`.
2. Only when `lifecycle.reinforcement_due(node.last_review, now, cooldown)`:
   `stability = lifecycle.reinforced_stability(...)` and `last_review = now`.
3. Write both disk and DB, as today.

The method also becomes `@_serialized_memory_operation` (council round 3). Step 2 is a
check-then-write pair on `last_review`, and the paths that reach it — `recall_node`,
`recall_search_structured`, `recall_search` — carry no such decorator, unlike `remember`/`update`.
Two concurrent recalls on the FastAPI threadpool would both read a stale `last_review`, both
conclude they are off cooldown, and both bump: the cooldown would hold per session and fail under
concurrency. `_memory_operation_lock` is an `RLock`, so the call sites already holding it re-enter
safely, and taking it here covers the Markdown write and the DB write as one unit — which a
conditional `UPDATE … WHERE last_review < ?` would not, since the file store is the source of
truth.

`access_count` keeps incrementing on every call — the cooldown governs the *numeric stability
update*, which is what the issue bounds. Splitting surfacing from confirmed use is #220's job,
not this one.

The five call sites (`memory_engine.py:646, 775, 811, 892, 938`) are untouched.

### 3. `src/ormah/background/decay_manager.py`

`math.exp(-days_since / stability)` is replaced by `lifecycle.retrievability(...)`, and the
anchor is **inverted** from `last_review or last_accessed` to `last_accessed or last_review`.

The stored `stability` is passed **raw**, with
`fallback_stability=settings.fsrs_initial_stability` — the same fallback reinforcement uses. The
current code pre-coerces `stability` to a literal `1.0` when falsy; keeping that while
reinforcement falls back to the configured value is how two paths that claim to share one
implementation silently disagree (council round 3). `Node.stability` is `Field(ge=0.0)`, so `0` is
a representable state: with `fsrs_initial_stability = 30`, a seven-day-old zero-stability node
reads `R ≈ 0.79` under the shared fallback and `R ≈ 0.0009` under the hardcoded one — the
difference between surviving and being archived.

Rationale: with the cooldown, `last_review` can lag the last use by up to one cooldown period.
Anchoring decay on it would let an actively used node look stale — the AC "every confirmed use
still advances its recency/decay anchor" requires the use timestamp. The two-way fallback is
kept so a row missing either column still decays instead of being skipped.

`importance_scorer.py:81-84` receives **the anchor flip only** — not the shared helper. See
*Out of scope* for why it was originally excluded, what the council review found, and why the
formula there must be left alone.

### 4. `src/ormah/config.py`

Removed: `fsrs_stability_growth` (today `1.5`, a *base multiplier*). The new `g` is an
*additive* term with a different meaning; reusing the name would silently reinterpret any
existing `ORMAH_FSRS_STABILITY_GROWTH` value. `model_config` sets `extra: "ignore"`, so an old
`.env` carrying the removed key still loads.

Added, with validators:

| Field | Default | Validation |
|---|---|---|
| `fsrs_growth_factor` | `0.5` | finite, `> 0` |
| `fsrs_growth_exponent` | `0.5` | finite, `> 0` |
| `fsrs_spacing_cap` | `2.0` | finite, `>= 1.0` |
| `fsrs_reinforcement_cooldown_days` | `1.0` | finite, `>= 0` |

`fsrs_growth_factor` and `fsrs_growth_exponent` join the existing `_fsrs_positive` validator;
the other two get their own. A new `_fsrs_finite` validator covers all four plus the
pre-existing `fsrs_initial_stability` and `fsrs_max_stability` — council finding I2: none of the
bounds checks reject NaN (`v <= 0` is False for it) and infinity satisfies them outright, so
`ORMAH_FSRS_GROWTH_FACTOR=nan` would propagate NaN into `stability` and into the Markdown
frontmatter.

### 5. Lifecycle-model version

`meta.fsrs_migrated` (`'1'` / absent) is replaced by `meta.lifecycle_model_version`, an integer
stored store-wide in the existing `meta` table (`src/ormah/index/schema.sql:67`).

`_migrate_fsrs` in `memory_engine.py:159` becomes version-aware:

- New key absent, `fsrs_migrated = '1'` present → backfill version `1`, skip the seed.
- New key absent, `fsrs_migrated` absent, but some node carries `last_review` → version `1`,
  skip the seed.
- New key absent, `fsrs_migrated` absent, no node carries `last_review` → run the
  `access_count` seed once, as today.
- Key present but unreadable → version `1` (fail closed), skip the seed.

Both keys are written together, so a rollback to a binary that only knows `fsrs_migrated` does
not reseed a store built under #221.

**Downgrade is not supported** (council round 3; decision: André, 2026-08-16). The dual write
stops a *reseed*; it does not stop the old binary from *writing*. Rolled back, that binary keeps
applying the unbounded formula to `stability` while `lifecycle_model_version = '2'` stays
untouched — it has never heard of the key. The next upgrade reads `2`, returns early, and
certifies old-model values as bounded-model values: `S=1` reinforced over 30 days lands near the
old `365` ceiling instead of `2.0`, and decay runs on that for months. The version can only
record which model wrote a value for as long as every writer respects it, and a pre-#221 binary
is not such a writer. Detecting an old-model write needs durable per-node provenance, a
`v2 → old binary → v2` integration test and a recovery policy for contaminated values — out of
scope here, its own issue if the policy proves insufficient. Nothing in this issue, its PR body
or its docs may describe the dual-key write as making rollback safe.

The `last_review` condition comes from council finding C3: `backup.py:331-334` excludes
`index.db` from every backup, so a fresh-device restore or a deleted index arrives with an
empty `meta` table and would otherwise be mistaken for a pre-FSRS store — running the seed over
valid stabilities and rewriting the Markdown that holds them. `last_review` is the durable
signal that survives this: it is written to the frontmatter (`markdown.py:72-73`) and restored
on rebuild (`builder.py:161`). Treating an unreadable version as `0` was the same mistake in
miniature — skipping a needed seed is inert, running an unneeded one is destructive.
- Version `< 2` → write `2` (bounded reinforcement).

Version `2` records *which model produced the stored stabilities*; it does not rescale them.
Rescaling is explicitly out of scope — #191 rules that a future curve migration must preserve
each node's archival deadline rather than apply a constant factor, and this issue introduces no
curve change to migrate.

### Interaction with #220 and #222 (neither landed)

Both PRs are open against `r-spade:main`; this island is cut from `upstream/main`, so neither is
present here.

- **#220** renames `_touch_access` → `_record_confirmed_use` and adds a zero-stability guard in
  the same block. Because this design moves the math into `lifecycle.py`, the rebase conflict is
  confined to the function signature and a few lines of its body — the helper calls survive as
  written. #220's local guard becomes redundant with `lifecycle.py`'s, and the helper's version
  wins on rebase.
- **#222** rewrites `importance_scorer.py`'s recency signal to its own half-life, removing
  `stability` from that job entirely.

**Accepted consequence, stated explicitly:** without #220 in this branch, `_touch_access` is
still called from surfacing paths. The cooldown therefore also throttles surfacing-driven
inflation. That is the desired direction, but it changes real-node numbers before #220 lands.

### Out of scope

- ~~`importance_scorer.py`~~ — **moved into scope by the council review (2026-08-16, finding
  C2).** The original reasoning was that the AC names only the decay manager and the
  reinforcement path, and that #222 already decouples that job from stability. That missed a
  defect this issue creates: the scorer reads `last_review or last_accessed` with weight `0.33`
  (`importance_scorer.py:81-84`, `config.py:144`), and the cooldown introduced here is exactly
  what makes `last_review` lag. An `S=1` node used today but reinforced yesterday sees its
  recency term fall from `~1.0` to `~0.37` — about `0.21` off importance, enough to cross the
  `0.5` gate and demote a memory in active use. The fix is the same anchor flip applied to the
  decay manager — **and only that**. Council round 2 (2026-08-16, both peers, `high`) rejected the
  first draft, which also routed the scorer through `lifecycle.retrievability` and read
  `r["stability"]`. Verified against `fix/222-retrievability-only-decay`: that branch selects
  `id, access_count, last_accessed, importance, last_review` — no `stability` — and computes
  `_recency_signal(days_ago, half_life)` on importance's own clock. Post-rebase the draft would
  either raise an uncaught `IndexError` (`sqlite3.Row` on a missing column; `IndexError` is not a
  subclass of `ValueError` or `TypeError`) and abort `run_importance_scoring` for every node, or
  reinstate FSRS in a job #222 deliberately removed it from. The earlier claim of orthogonality
  with #222 was wrong. Both timestamp columns are selected on either version, so the anchor flip
  alone applies cleanly.
- **The same-device restore path** — `full_rebuild` preserves `meta` and `reload_restored_graph`
  never calls `_migrate_fsrs`, so a pre-FSRS backup restored onto a migrated install skips the
  seed. Found by both peers in council round 2 (`high`). It is a **pre-existing** defect —
  `_migrate_fsrs` already returns early on `if fsrs_migrated: return` on `a28837b` — so it is
  tracked as its own issue — r-spade/ormah#236 — rather than widening this one (decision: André, 2026-08-16). What this
  issue owes: not claiming the C3 `last_review` guard covers restore in general. It covers the
  empty-`meta` case only.
- `tier_manager.py`, promotion floors, and the initial-lease work — #223.
- Any rescale or backfill of existing `stability` values.
- Splitting surfacing from confirmed use — #220.

## Testing

TDD, one test per acceptance criterion, in `tests/test_engine/test_lifecycle.py` (new) plus
edits to the existing decay and engine suites.

**`lifecycle.py` unit tests**

- `S=1`, `t=30d` → `reinforced_stability` returns exactly `2.0` (AC1).
- `t/S = 20000` → `spacing_factor` returns `cap` and raises nothing (AC2).
- Iterating `reinforced_stability` from `S=1` with `t=1d` reaches `365.0` in **74** steps, and
  each step's *ratio* `S'/S` is strictly smaller than the previous one — `1.61 → 1.45 → 1.36 → …`
  (AC3). Assert the ratio, **not** the absolute increment: the increment is `g·√S·spacing`, which
  *grows* with `S` (`0.61 → 0.72 → 0.83 → 0.95`, verified by execution). "Growth diminishes" is a
  statement about the relative step. An earlier draft of this spec asserted the opposite and would
  have produced a test that can never pass.
- `stability=0` → falls back to `initial_stability` instead of raising.
- `retrievability` matches `exp(-t/S)` on a table of known pairs, and is `<= 1.0` for `t >= 0`.

**Engine tests**

- Ten `_touch_access` calls inside one day → `stability` and `last_review` change exactly once;
  `last_accessed` advances on all ten and `access_count` reaches ten (AC4).
- A call after the cooldown elapses → `stability` moves again.
- **Two `_touch_access` calls on one node from two threads, released by a `threading.Barrier`, →
  one stability bump, both accesses counted (AC4 under concurrency).** The sequential test above
  cannot see this: it is the interleaving that breaks the cooldown, and the recall paths that
  reach `_touch_access` are not serialized, so the interleaving is the production shape. The
  barrier is load-bearing — a bare thread pair can serialize by luck and green on broken code.
- `tests/test_engine/test_mutation_stamping.py:95` (`test_touch_access_does_not_advance_updated`)
  must still pass unchanged.

**Decay tests** — every one of these must set `importance = 0.2` first. Council finding C1:
`run_decay` skips a node when `importance >= decay_importance_threshold`, and both the node
default and the threshold are `0.5` with a `>=` gate, so a test at the default never reaches the
retrievability code. The anchor test in particular must be observed **failing** on `a28837b`
before the flip, or it proves nothing.

- Same `(days_since, stability)` input produces the same `R` through `run_decay`'s path and
  through `lifecycle.retrievability` — one implementation, asserted numerically (AC5).
- A node whose `last_accessed` is fresh but whose `last_review` is one cooldown old is **not**
  demoted (the inverted anchor).
- **A `stability = 0` node last used seven days ago, with `fsrs_initial_stability = 30`, is not
  demoted.** This is the only test that distinguishes the shared fallback from a hardcoded `1.0`:
  the two give `R ≈ 0.79` and `R ≈ 0.0009`, and the `0.3` decay threshold sits between them. At the
  default `fsrs_initial_stability = 1.0` the two are indistinguishable, so the non-default value is
  load-bearing, not decoration.
- Existing `test_decay_manager.py` cases must stay green.

**Importance-anchor test — the lag must be ≥ 7 days, and 30 is the value to use.** Council round 2
caught the first draft using a 1-day lag with `approx(0.33, abs=0.02)`. Recomputed: after #222 the
14-day half-life turns a 1-day lag into `importance = 0.3141`, inside the `[0.3100, 0.3500]`
window, so the test passes **whether or not the anchor was flipped** — a false green guarding the
exact regression it exists to catch. At 30 days the old anchor yields `~0.075` post-#222 and
`~0.0` pre-#222 (`exp(-30)` at `S=1`), so it is red under both formulas. That matters because this
branch is written against `a28837b` and rebased onto #222.

**Version tests**

- Store with `fsrs_migrated='1'` and no new key → backfills `lifecycle_model_version = 1`, does
  not re-seed, then advances to `2` (AC6).
- Fresh store → seed runs once, version ends at `2`.
- Store with no `meta` at all but a node carrying `last_review` (the rebuilt-index case) →
  stability untouched, version ends at `2`. Removing the guard must make this test report the
  seeded value instead.
- Unreadable version → treated as migrated, seed does not run.
- `fsrs_migrated` is present after any migration path — this proves an older binary will not
  **reseed**, and nothing more. It is not a rollback-safety test; downgrade is unsupported.

**Config tests**

- Each new knob rejects its invalid range (AC7).
- Every lifecycle float rejects `nan`, `inf` and `-inf`, from the constructor and from the
  environment (council finding I2). Verified against the current code: `Settings` accepts both
  `nan` and `inf` today, because `v <= 0`, `v < 1` and `v < 0` are all False for NaN and
  infinity satisfies them outright.
- An `.env` carrying the removed `fsrs_stability_growth` still loads (`extra: "ignore"`).

**Verification command.** Run inside the worktree with its own venv:
`./.venv/bin/python -m pytest tests/ -v`. A bare `python -m pytest` imports the `ormah`
installed from `local-main` and produces a false green.

## Docs

- `docs/12 - Configuration Reference.md` — remove `fsrs_stability_growth`, document the four new
  knobs (AC7).
- `docs/05 - Background Jobs.md` — decay's anchor description.
- `docs/01 - Data Model.md` — `last_accessed` vs `last_review` now move independently.

## Fork workflow

Per `FORK-WORKFLOW.md` Recipe A. The island already exists:
`git worktree add -b fix/221-bounded-reinforcement ../ormah-wt-221 upstream/main` (gate verified:
zero commits over the base at creation). Work happens in the worktree — this checkout stays on
`local-main` and serves the running Beta. Push to `fork`, PR against `r-spade:main`.

This spec and its plan live on `local-main` only: `docs/superpowers/` is in the pre-push
`PROTECTED` allowlist, so committing them inside the island would block the push.
