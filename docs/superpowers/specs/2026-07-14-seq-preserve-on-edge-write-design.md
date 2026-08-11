# Preserve `seq` when only connections change (#126)

**Date:** 2026-07-14
**Issue:** [#126](https://github.com/r-spade/ormah/issues/126)
**Status:** approved (André, 2026-07-14)

## Problem

The auto_linker re-queues the very nodes it just processed, so the backlog never drains — it sits at ~95% of the store (14,178 of 14,942 nodes measured on the live Beta).

`seq` is a **change-sequence**: `IndexBuilder._index_file_nodes_only` allocates a fresh `seq` from `meta.node_seq_next` on *every* index pass ([builder.py:176-187](../../../src/ormah/index/builder.py#L176-L187)). The auto_linker enqueues by `seq > watermark` ([auto_linker.py:36](../../../src/ormah/background/auto_linker.py#L36)), so **any reindexed node goes back to the end of the queue**.

The code states the contract it violates (builder.py:178-180):

> Every **content** (re)write lands the node at the head, so reindex/import/restore re-enter the delta regardless of frontmatter timestamps. **Metadata-only UPDATEs elsewhere do not pass through here.**

Writing an edge breaks that contract. `_apply_edge` persists the connection into the node's markdown:

```python
mem_node.connections.append(Connection(...))
mem_node.touch_updated()
engine.file_store.save(mem_node)      # rewrites the .md
```

File changes → `file_hash` changes → `index_updater` (every 60s) reindexes → `seq` bumped → node re-enters the queue. But nothing relevant to linking changed: same content, same embedding, same vector neighbours, and the pairs are already in `auto_link_checked`. The reprocessing cannot discover anything.

`conflict_detector` writes edges the same way and causes the same effect.

### Evidence (live store, 2026-07-14)

- `seq` does not correlate with `created`: nodes from 2026-06-27 carry seq 175,154 / 439,329 / 766,207.
- Of the 13,103 nodes with `seq > 700,000`, **11,833 (90%)** were created before today but updated today — i.e. old nodes re-queued by an edge write.
- Re-queue rate: **~352 nodes/hour**.
- 17% of the next 300 queued nodes had already been judged (present in `auto_link_checked`).

Not a correctness bug — it converges (a re-queued node whose pairs are all checked produces no new edge, so it is not touched again). It is a **throughput tax** that pins the backlog at ≈ store size.

## Design

### Content fingerprint

A node re-enters the queue only when its **content fingerprint** changes:

```
(title, content, type, space)
```

Rationale — these are exactly the inputs that can change a linking decision:

| field | why it matters |
|---|---|
| `title`, `content` | feed the embedding (`embedding_text`) **and** the LLM judge prompt |
| `type` | shown to the LLM judge (`_LLM_LINK_PAIR`) |
| `space` | shown to the LLM judge **and** drives `cross_space_penalty` in candidate selection |

Everything else preserves `seq`: `connections` (the bug), `tags`, `tier`, `confidence`, `importance`, `access_count`, `last_accessed`, `stability`, `archived_at`.

`tags` are deliberately excluded: they feed FTS, never the linker.

### Flow

The obstacle: both incremental paths delete the row *before* the `seq` is allocated, so the old content is gone by the time we need to compare it.

```python
# update_index (builder.py:110-113)      # index_single (builder.py:127-129)
self._remove_node(node.id, keep_vectors=True)   self._remove_node(node.id)
self._index_file(path)                          self._index_file(path)
```

Fix: read the row **before** `_remove_node` and thread it through as `prior`.

```python
def _prior_row(self, node_id: str):
    """Row needed to decide whether this reindex is a content change."""
    return self.db.conn.execute(
        "SELECT title, content, type, space, seq FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()

def _index_file_nodes_only(self, path: Path, prior=None) -> None:
    ...
    # INSERT OR REPLACE INTO nodes (...)
    if prior is not None and _same_fingerprint(prior, node):
        seq = prior["seq"]                      # connection/metadata-only -> keep place in queue
        conn.execute("UPDATE nodes SET seq = ? WHERE id = ?", (seq, node.id))
    else:
        # existing behaviour: allocate from the durable counter, land at the head
        ...
```

`_index_file(path, prior=None)` just forwards `prior` to `_index_file_nodes_only`.

### Why `full_rebuild` needs no change

`full_rebuild` does `DELETE FROM nodes`, clears `auto_link_watermark`, then calls `_index_file_nodes_only(path)` with no `prior`. Table is empty → `prior is None` → every node gets a fresh `seq`, and the cleared watermark means the whole store is reprocessed. That is the correct behaviour for a mass reindex, and it is preserved.

Restore/import are likewise unaffected: if the restored file is byte-identical, `file_hash` matches and `update_index` never enters the update branch at all (builder.py:110).

### Scope

One file: `src/ormah/index/builder.py`. Six touch points:

| # | element | change |
|---|---|---|
| 1 | `_content_fingerprint(row_or_node)` | new helper |
| 2 | `_prior_row(node_id)` | new helper |
| 3 | `_index_file_nodes_only(path, prior=None)` | conditional `seq` allocation |
| 4 | `_index_file(path, prior=None)` | forward `prior` |
| 5 | `update_index()` | capture `prior` before `_remove_node` |
| 6 | `index_single()` | capture `prior` before `_remove_node` |

Fixing it in the builder (not in the callers) covers `conflict_detector` and the six `memory_engine.index_single` call-sites for free.

### Data migration

None. The ~11,833 already-re-queued nodes get processed once (cheap — their pairs are in `auto_link_checked`, so no LLM call), leave the queue, and do not come back. The backlog drains on its own.

## Testing (TDD — tests first)

**The failing test that defines the bug:**

- `test_edge_write_does_not_bump_seq` — persist a connection into a node's markdown, reindex via the builder, assert `seq` is unchanged. Fails today.

**Fingerprint must bump (one test per field):**

- `test_content_change_bumps_seq`
- `test_title_change_bumps_seq`
- `test_type_change_bumps_seq`
- `test_space_change_bumps_seq`

**Must not bump:**

- `test_tags_only_change_does_not_bump_seq`

**Regression:**

- `test_full_rebuild_allocates_new_seq` — mass reindex still lands every node at the head and clears the watermark.

**Existing tests that must stay green:**

- `test_seq_bumped_on_rewrite` (content rewrite still bumps)
- `test_metadata_update_does_not_bump_seq` (direct SQL UPDATE, bypasses builder)
- `test_select_nodes_after_seq`

## Out of scope

- `_apply_edge` keeps calling `touch_updated()`. `updated` will still change on an edge write — it is informational metadata and no longer affects the queue.
- The `seq`/`change_seq` split (option 3 in #126) is not pursued; the fingerprint check achieves the same result without a schema change.

## Risks

- **Long content:** `embedding_text` truncates content at 512 chars, but the LLM judge sees the full content. The fingerprint therefore compares the **full** `content`, not the truncated form — conservative on purpose: an edit past char 512 changes the judge's input even when the embedding is unchanged.
- **Test isolation:** pytest must run with an isolated `HOME` (`HOME=$(mktemp -d) pytest`), otherwise the developer's real `~/.config/ormah/.env` breaks collection (issue #106).
- **Working tree:** `/Users/andre/Documents/GitHub/Tools/ormah` is the Beta and serves the live server — never check out branches there. Implementation happens in `/Users/andre/Documents/GitHub/ormah-dev` (origin = fork `AndreLFSMartins`, upstream = `r-spade`).
