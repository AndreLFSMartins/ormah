---
status: accepted
---

# Prefix resolution stays in the FileStore, verified

The **Whisper** only ever shows an agent a **Short id** (8 hex chars, 32 bits), and every agent
surface passes that string straight through to `FileStore` — `POST /agent/update/{node_id}` reaches
`file_store.load(node_id)` untouched. So `_find_file()` is, de facto, the file-side resolver of
**Node references**, and it resolved them by globbing `*_{short_id}.md` and returning `matches[0]`
without reading the frontmatter. We keep prefix tolerance where it is and make it **verified**:
parse each glob match, accept only a node whose **Full id** matches, and resolve ambiguity to
nothing.

## Why not the obvious alternative

Making `FileStore` full-id-only — pushing **Prefix resolution** up to a single resolver at the
engine boundary — is the cleaner shape, and it is what we eventually want. It is not what we did,
because it means migrating ~20 `file_store.load` call sites, and each one missed degrades silently
into "Memory not found" for an agent holding a whispered id. That is a refactor with its own
review, not a rider on a data-loss fix.

## Consequences

- **Three resolvers, three semantics, on purpose (for now).** `Graph.get_node` (`LIKE ? LIMIT 1`)
  accepts *any* prefix and is still blind to ambiguity; `_resolve_feedback_node_id` detects
  ambiguity and errors; `FileStore._find_file` now accepts a **Full id** or an exact 8-char
  **Short id** only, and returns `None` (plus a warning log) on ambiguity. A colliding **Short id**
  can therefore make `recall_node` and `update_node` disagree about which node it names. Tracked
  separately; converging them is the follow-up this ADR defers, not an oversight.
- **The narrower prefix width in the store is deliberate.** Filenames end in the 8-char **Short
  id**, so any other prefix width would force an O(N) cache build on every short lookup — to serve
  a caller that does not exist, since the Whisper emits exactly 8.
- **The filename scheme keeps the Short id.** `{type}_{slug}_{short_id}.md` means two nodes can
  still land on one filename when type *and* slug *and* **Short id** all collide. Putting the
  **Full id** in the name would end the class outright, but it rewrites every file in every
  existing store and drags sync, backup and restore with it — too much for a store whose real
  collision rate is a rare subset of an already rare event. Instead `_path_for()` gains a
  collision-time guard: if the computed path already holds a *different* node, extend the suffix.
  No existing filename changes.
- **The cache is keyed by Full id only**, and written only after verification. One key per node
  makes `delete`/`soft_delete` correct without enumerating aliases; the price is that a Short id
  lookup re-globs each time — irrelevant on an interactive path.
- **A cache hit is still validated by `cached.exists()` alone.** Re-parsing on every hit would
  destroy the O(1) the cache exists for. The residual hole — a file replaced by a different node
  behind the store's back, which is the watcher's territory — is pinned by a test that fixes
  current behaviour rather than treated as a bug.
