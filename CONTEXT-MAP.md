# Ormah — Context Map

This repo has more than one bounded context. Each has its own glossary; terms are **not**
interchangeable across them (a **Cursor** in Ingest and a **Watermark** in Maintenance are both
"how far did we get", and conflating them has already produced a wrong diagnosis).

| Context | Glossary | Covers |
|---|---|---|
| **Ingest & Extraction** | [`CONTEXT.md`](CONTEXT.md) | Turning conversation transcripts into memory nodes: lanes, cursors, batches, the extractor, the relevance gate. |
| **Maintenance** | [`src/ormah/background/CONTEXT.md`](src/ormah/background/CONTEXT.md) | Curating the graph *after* nodes exist: linking, dedup/merge, conflict detection, consolidation, decay and forgetting. |

Decisions live in [`docs/adr/`](docs/adr/) for both contexts — the series is repo-wide, not
per-context, and is local-only (never reaches an upstream PR).

## Why the Ingest glossary stays at the root

The skill's multi-context layout puts each `CONTEXT.md` under `src/<context>/`. Maintenance maps
cleanly onto `src/ormah/background/`, so its glossary lives there. Ingest does not map onto one
directory — it spans the session watcher, the hook lane, the API routes and the extraction prompt —
so its glossary stays at the repo root rather than being filed under a directory that would
misrepresent its boundary.

## The seam between them

Ingest **produces** nodes; Maintenance **curates** them. Volume created by Ingest is what makes
Maintenance expensive — the near-duplicates the **Duplicate merger** works on are manufactured
upstream of it, which is why ADR-0002's relevance gate keeps being cited in Maintenance decisions.
The two contexts share the store and nothing else: no Maintenance job reads a **Cursor**, and no
Ingest lane reads a **Watermark**.
