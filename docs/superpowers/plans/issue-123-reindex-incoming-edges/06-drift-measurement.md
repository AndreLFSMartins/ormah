# Task 6: Measure the drift — the acceptance number for task 7


> ⚠️ **Measures the Beta's live store on purpose.** This task reads
> `~/.local/share/ormah/memory/index.db`, a product of `local-main` — that is intentional and is
> why its numbers may never be cited in a PR against `upstream/main`. It writes no code, so the
> `upstream/main` re-anchor of tasks 1-5 does not apply to it.

Read `00-overview.md` first.

> **This task writes no shippable code and opens no PR.** It produces three numbers that become
> task 7's acceptance criteria. It is **not** a go/no-go: council round 1 established that the
> decision to build task 7 cannot be made from a measurement of this machine. See
> *Why this is not a gate* below.

**Files:**
- Create: a throwaway measurement script in a temp dir. **Not** in the repo — it is an
  instrument, not a deliverable.

**Interfaces:**
- Consumes: nothing.
- Produces: `missing_directed`, `missing_typed` and `missing_live_target` — the counts of
  connections declared in markdown whose target node is alive but which have no matching row in
  `edges`, under three progressively stricter notions of edge identity. Task 7's acceptance test
  is `missing_typed` reaching 0.

## Why this is a task and not a footnote

The repair slice has no success criterion without it. "How many edges did we recover" is
unanswerable today: the ad-hoc script written during design printed `declared=0` while
`parse_node` raised `KeyError: 'id'`.

**Root cause, verified:** that script walked `memory_root.rglob("*.md")`. The store's own
enumerator is `FileStore.list_paths()` (`file_store.py:192`), which is
`self.nodes_dir.glob("*.md")` — **non-recursive, and scoped to `nodes_dir`**. The recursive walk
swept in markdown that is not a node: 5629 files under the memory root against 5413 rows in
`nodes`.

## Why this is not a gate — council round 1

The earlier version of this task ended in "at or near zero → do not build task 7". Both peers
rejected that, on three separate grounds, and all three were confirmed:

1. **Wrong place.** The measurement runs against `~/.local/share/ormah/memory`, a store written by
   `local-main`. The PR is for `r-spade/ormah:main`. An installation that never ran
   `/admin/rebuild` since 2026-07-14 keeps shrinking regardless of what this machine reports, and
   its only recovery is the ~222 s full rebuild. *(Cursor)*
2. **Wrong moment.** Task 5 opens a PR; it does not deploy. The running daemon still serves the
   destructive code, so any snapshot taken here goes stale immediately. *(Codex — verified: the
   Beta daemon has been up since 2026-08-20 20:14 on the old tree.)*
3. **Wrong metric.** The old script symmetrised the pair and ignored `edge_type`, so it could not
   see a directed loss whose reverse survived, and a live `supports` row masked a missing
   `contradicts` for the same pair. *(Codex — measured: it undercounts by 2,182.)*

**This task therefore produces acceptance numbers, never a cancellation.** Whether task 7 ships is
André's call, informed by these numbers plus the fact that the bug has been in `upstream/main`
since 2026-07-14.

## The measurement already has a first reading

Run on 2026-08-21 during the council review, against the live Beta store (5,530 node files,
0 parse failures):

| Metric | Value |
|---|---|
| `declared` | 34,083 |
| `dead_target` | 847 |
| `missing_live_target` (symmetrised — the OLD metric) | 12,562 |
| `missing_directed` (`(source, target)` exact) | **14,744** |
| `missing_typed` (`(source, target, edge_type)`) | **14,747** |
| declared pairs that are reciprocal | 4,198 of 28,439 (~15%) |
| rows in `edges` | 18,266 (distinct `(s, t)` = 16,857) |

Two things this settles:

- **The loss is real.** The hypothesis that ~34k declared connections were merely double-counted
  reciprocal declarations of ~17k pairs is refuted: only ~15% of declared pairs are reciprocal.
- **The old metric was blind to 2,182 directed losses**, exactly as the council predicted.

Re-run it — do not trust the table. It is a reading of a live, changing store, and `edges` grows
continuously as `auto_linker` runs.

## Run this against the BETA's venv, not an island

`~/.local/share/ormah/memory/` was written by `local-main` — the server, the MCP processes and
the whisper hook all import from `Tools/ormah/src/ormah`. Parsing that store with
`upstream/main`'s `parse_node` would read one tree's data with another tree's code. Use
`Tools/ormah/.venv`, and prove it before trusting the number.

- [ ] **Step 1: Pick a scratch dir and prove the interpreter**

```bash
SCRATCH="$(mktemp -d -t ormah-drift)"; echo "$SCRATCH"
cd /Users/andre/Documents/GitHub/Tools/ormah
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: `/Users/andre/Documents/GitHub/Tools/ormah/src/ormah/__init__.py`. Any other path means
you are about to measure with the wrong code.

- [ ] **Step 2: Write the measurement**

Write to `$SCRATCH/drift.py`:

```python
import pathlib
import shutil
import sqlite3
import tempfile

from ormah.store.file_store import FileStore
from ormah.store.markdown import parse_node

root = pathlib.Path.home() / ".local/share/ormah/memory"
store = FileStore(root / "nodes")

# Read a CONSISTENT copy, not the live file. A `mode=ro` URI connection cannot
# take the -shm lock, so it silently falls back to the database file alone and
# ignores the WAL — a stale snapshot with no error raised. Measured on
# 2026-08-21: 14,977 edges via `mode=ro` against 18,220 actually present.
tmp = pathlib.Path(tempfile.mkdtemp())
for suffix in ("", "-wal", "-shm"):
    src = root / f"index.db{suffix}"
    if src.exists():
        shutil.copy(src, tmp / f"index.db{suffix}")
db = sqlite3.connect(tmp / "index.db")

alive = {r[0] for r in db.execute("SELECT id FROM nodes")}

# Three notions of edge identity, from loosest to strictest. `_index_file_edges`
# canonicalises direction, so the symmetrised set is the loosest defensible read
# — but it cannot see a directed loss whose reverse survived, and none of the
# three is meaningful without edge_type, which canonicalisation is scoped by.
sym, directed, typed = set(), set(), set()
for s, t, et in db.execute("SELECT source_id, target_id, edge_type FROM edges"):
    directed.add((s, t))
    sym.add((s, t))
    sym.add((t, s))
    typed.add((s, t, et))

declared = dead = 0
missing_sym = missing_directed = missing_typed = 0
declared_pairs = set()

for path in store.list_paths():
    node = parse_node(path.read_text(encoding="utf-8"))
    for c in node.connections:
        declared += 1
        if c.target not in alive:
            dead += 1
            continue
        declared_pairs.add((node.id, c.target))
        if (node.id, c.target) not in sym:
            missing_sym += 1
        if (node.id, c.target) not in directed:
            missing_directed += 1
        if (node.id, c.target, c.edge.value) not in typed:
            missing_typed += 1

reciprocal = sum(1 for (a, b) in declared_pairs if (b, a) in declared_pairs)

print(f"declared={declared} dead_target={dead}")
print(f"missing_live_target={missing_sym} (symmetrised — undercounts)")
print(f"missing_directed={missing_directed}")
print(f"missing_typed={missing_typed}   <-- task 7's acceptance number")
print(f"declared_pairs={len(declared_pairs)} reciprocal={reciprocal}")
print(f"edges_rows={len(typed)} distinct_pairs={len(directed)}")

shutil.rmtree(tmp)
```

Four corrections against the broken version: `store.list_paths()` instead of `rglob`,
`parse_node(path.read_text(...))` because `parse_node` takes **text** (that is how `builder.py`
calls it), a WAL-consistent copy instead of a `mode=ro` connection, and three metrics instead of
one symmetrised count.

**Do not wrap the loop in a bare `except`.** A parse failure here is a finding to report, not
noise to swallow — swallowing it is what produced `declared=0` in the first place.

- [ ] **Step 3: Run it**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python "$SCRATCH/drift.py"
```

Expected shape: `declared` in the low tens of thousands, `dead_target` in the high hundreds
(targets legitimately gone; the FK guard in `_index_file_edges` skips those), and
`missing_typed >= missing_directed >= missing_live_target`. If that ordering is violated the
script is wrong, not the store — the stricter the key, the more misses it can see.

Copying the DB is safe with the daemon up; nothing is written back to the live store.

- [ ] **Step 4: Record the numbers as acceptance criteria**

Report all three to André, plus `declared`, `dead_target` and the reciprocal count. Then:

- **`missing_typed` is task 7's acceptance number.** After `repair_edges` runs, re-running this
  script must print `missing_typed=0`.
- **Record `missing_directed` too.** The gap between it and `missing_live_target` is the number of
  losses the symmetrised metric cannot see; it is the evidence that the metric had to change.
- **Do not recommend skipping task 7 on the strength of this machine.** If every number came back
  zero here, that would say this store is currently whole — not that `upstream/main` is. The bug
  has been in `main` since 2026-07-14, and a near-zero reading taken while the Beta daemon still
  runs the destructive code is stale the moment it is printed.

This task ends with numbers, not with code and not with a cancellation.
