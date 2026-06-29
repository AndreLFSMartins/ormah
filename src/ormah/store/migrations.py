"""One-shot data migrations for the markdown store.

Run a migration against your configured store:
    python -m ormah.store.migrations null-space
"""

from __future__ import annotations

from pathlib import Path

import frontmatter

from ormah.index.builder import IndexBuilder
from ormah.index.db import Database
from ormah.models.node import normalize_space
from ormah.store.file_store import FileStore
from ormah.store.markdown import parse_node


def migrate_null_space(nodes_dir: Path, db_path: Path) -> tuple[int, int]:
    """Coerce literal 'null'/'none'/'' space strings to None (#22).

    A handful of stored nodes carried the placeholder string ``space='null'``
    (not SQL NULL), landing them in a phantom "null" space group. The write-path
    guard (``MemoryNode`` field validator) prevents new ones; this cleans the
    existing files and rebuilds the index. Idempotent.

    Returns ``(files_fixed, nodes_reindexed)``.
    """
    fs = FileStore(nodes_dir)
    fixed = 0
    for path in fs.list_paths():
        raw = frontmatter.loads(path.read_text(encoding="utf-8")).metadata.get("space")
        if isinstance(raw, str) and normalize_space(raw) != raw:
            # parse_node runs the validator (normalizes); save re-serializes clean.
            fs.save(parse_node(path.read_text(encoding="utf-8")))
            fixed += 1
    db = Database(db_path)
    db.init_schema()  # no-op on an existing DB; creates tables on a fresh one
    reindexed = IndexBuilder(db, fs).full_rebuild()
    return fixed, reindexed


def main(argv: list[str] | None = None) -> None:
    import sys

    from ormah.config import Settings

    args = argv if argv is not None else sys.argv[1:]
    if args != ["null-space"]:
        print("usage: python -m ormah.store.migrations null-space")
        raise SystemExit(2)

    settings = Settings()
    fixed, reindexed = migrate_null_space(settings.nodes_dir, settings.db_path)
    print(f"migrated {fixed} file(s); reindexed {reindexed} node(s)")


if __name__ == "__main__":
    main()
