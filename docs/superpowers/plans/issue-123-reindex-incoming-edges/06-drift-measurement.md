# Task 6: Fix the drift measurement — and decide whether task 7 is needed at all

Read `00-overview.md` first.

> **This task writes no shippable code and opens no PR.** It produces one number and a
> go/no-go. Task 7 must not start until it has run.

**Files:**
- Create: a throwaway measurement script in a temp dir. **Not** in the repo — it is an
  instrument, not a deliverable.

**Interfaces:**
- Consumes: nothing.
- Produces: `missing_live_target`, the count of connections declared in markdown whose target
  node is alive but which have no row in `edges`. Task 7's acceptance test is that number
  reaching 0.

## Why this is a task and not a footnote

The repair slice has no success criterion without it. "How many edges did we recover" is
unanswerable today: the ad-hoc script written during design printed `declared=0` while
`parse_node` raised `KeyError: 'id'`.

**Root cause, verified:** that script walked `memory_root.rglob("*.md")`. The store's own
enumerator is `FileStore.list_paths()` (`file_store.py:192`), which is
`self.nodes_dir.glob("*.md")` — **non-recursive, and scoped to `nodes_dir`**. The recursive walk
swept in markdown that is not a node: 5629 files under the memory root against 5413 rows in
`nodes`.

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
import sqlite3

from ormah.store.file_store import FileStore
from ormah.store.markdown import parse_node

root = pathlib.Path.home() / ".local/share/ormah/memory"
store = FileStore(root / "nodes")
db = sqlite3.connect(f"file:{root / 'index.db'}?mode=ro", uri=True)

alive = {r[0] for r in db.execute("SELECT id FROM nodes")}
edges = set()
for s, t in db.execute("SELECT source_id, target_id FROM edges"):
    edges.add((s, t))
    edges.add((t, s))

declared = dead = missing = 0
for path in store.list_paths():
    node = parse_node(path.read_text(encoding="utf-8"))
    for c in node.connections:
        declared += 1
        if c.target not in alive:
            dead += 1
        elif (node.id, c.target) not in edges:
            missing += 1

print(f"declared={declared} dead_target={dead} missing_live_target={missing}")
```

Three corrections against the broken version: `store.list_paths()` instead of `rglob`,
`parse_node(path.read_text(...))` because `parse_node` takes **text** (that is how `builder.py`
calls it), and the pair check is direction-agnostic because `_index_file_edges` canonicalises the
direction and stores only one of the two.

**Do not wrap the loop in a bare `except`.** A parse failure here is a finding to report, not
noise to swallow — swallowing it is what produced `declared=0` in the first place.

- [ ] **Step 3: Run it**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python "$SCRATCH/drift.py"
```

Expected shape: `declared` in the low tens of thousands, `dead_target` small (targets legitimately
gone; the FK guard in `_index_file_edges` skips those), `missing_live_target` the real loss.

The connection is opened read-only (`mode=ro`), so this is safe to run against the live store with
the daemon up.

- [ ] **Step 4: The go/no-go**

Report `missing_live_target` to André with one of these two readings:

- **Materially above zero** → task 7 is worth building. Record the number; it is the acceptance
  test.
- **At or near zero** → **stop, and do not build task 7.** The Beta was rebuilt on 2026-08-21 and
  tasks 1-5 stop new loss, so there may be nothing left to repair. Building a repair for a store
  that is already whole is work with no deliverable. Report the number and let André decide.

Either way, this task ends with a number and a recommendation — not with code.
