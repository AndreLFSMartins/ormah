# Task 3: Documentation

> Part of `docs/superpowers/plans/2026-08-16-issue-222/`. **Read `00-overview.md` first** —
> it carries the Global Constraints and the council findings that every task must honor.

**Files:**
- Modify: `docs/05 - Background Jobs.md:124-129`, `:137`, `:154`
- Modify: `docs/12 - Configuration Reference.md:184`

**Interfaces:**
- Consumes: the behavior established in Tasks 1 and 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Fix the "Importance and Decay" section**

In `docs/05 - Background Jobs.md`, replace lines 124-129:

```markdown
## Importance and Decay

- `importance_scorer` computes a normalized multi-signal importance value
- `decay_manager` uses FSRS-style retrievability and importance to decide whether to demote working memories

High-importance nodes are protected from decay.
```

with:

```markdown
## Importance and Decay

- `importance_scorer` computes a normalized multi-signal importance value
- `decay_manager` uses FSRS-style retrievability alone to decide whether to demote working memories

Importance does not protect a node from decay. Cumulative signals such as access
and edge counts could otherwise push a stale node permanently above any threshold.
Archival is reversible dormancy, not deletion — a demoted node stays reachable by
deliberate recall. Use the `core` tier for permanent whisper eligibility.

One exception, and it is deliberate: when bounded forgetting is armed
(`deletion_enabled` together with `archival_soft_cap > 0`), the cap backstop can
evict an archival node without waiting for `deletion_min_archival_days`, including
one demoted earlier in the same maintenance pass. Both settings are off by default
and that path is gated on the lifecycle work (#28/#31).
```

> Council C1: the unqualified version of this paragraph ("a demoted node stays reachable") is
> false under a supported #28 configuration. The exception sentence is not optional.

- [ ] **Step 2: Fix the recency-signal description**

In `docs/05 - Background Jobs.md`, replace line 137:

```markdown
3. **Recency signal**: how retrievable the node currently is, using FSRS-style `exp(-days_ago / stability)`
```

with:

```markdown
3. **Recency signal**: how recently the node was touched, using half-life decay `exp(-ln(2) * days_ago / importance_recency_half_life_days)` — independent of FSRS stability
```

- [ ] **Step 3: Delete the stale nuance paragraph**

In `docs/05 - Background Jobs.md`, delete this line (line 154) entirely, along with the blank line that follows it:

```markdown
Important current nuance: `importance_recency_half_life_days` exists in configuration, but the current scorer implementation uses FSRS stability for the recency term instead.
```

- [ ] **Step 3b: Correct the sentence above it**

Line 152 credits "recall and search hits" with lifecycle writes; #220 already made surfacing non-mutating, so it is now wrong. Replace:

```markdown
This score is not static. Recall and search hits update `access_count`, `last_accessed`, `last_review`, and `stability`, so a memory's importance changes over time as it is used, connected, or left untouched.
```

with:

```markdown
This score is not static. Confirmed use updates `access_count`, `last_accessed`, `last_review`, and `stability`, so a memory's importance changes over time as it is used, connected, or left untouched. Merely appearing in a search result does not (see #220).
```

- [ ] **Step 4: Fix the configuration reference**

`docs/12 - Configuration Reference.md` uses a two-column `| Setting | Default |` table, so the row stays as-is and the qualification goes in prose. Leave line 184 unchanged and insert this paragraph immediately after the table (i.e. after line 184, before the blank line preceding `## Whisper-Out and Nudge`):

```markdown

`decay_importance_threshold` protects high-importance archival nodes from bounded
forgetting. It does not affect `working -> archival` decay, which depends on
retrievability alone (#222).
```

- [ ] **Step 5: Verify no doc still claims the old behavior**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
grep -rn "High-importance nodes are protected from decay\|uses FSRS stability for the recency term\|retrievability and importance" docs/
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
git add "docs/05 - Background Jobs.md" "docs/12 - Configuration Reference.md"
git commit -m "docs: retrievability alone drives decay; importance recency has its own half-life (#222)

Also qualifies the archival reachability claim: the bounded-forgetting cap
backstop can evict a just-demoted node when deletion and archival_soft_cap are
armed (both off by default, gated on #28/#31).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git show --stat HEAD
```

Expected: exactly 2 files.
