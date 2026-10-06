"""The all-nodes write in importance_scorer must commit in bounded chunks."""

from ormah.background.importance_scorer import _commit_updates_chunked


class _RecordingDB:
    def __init__(self):
        self.transactions = 0
        self.executed = 0

    def transaction(self):
        db = self

        class _Ctx:
            def __enter__(self_inner):
                db.transactions += 1
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def execute(self_inner, *a, **k):
                db.executed += 1

        return _Ctx()


def test_commit_updates_chunked_splits_into_batches():
    db = _RecordingDB()
    updates = [(0.5, f"id-{i}") for i in range(250)]

    _commit_updates_chunked(db, updates, chunk_size=100)

    # 250 updates / 100 per chunk = 3 transactions (100, 100, 50)
    assert db.transactions == 3
    assert db.executed == 250


def test_commit_updates_chunked_empty():
    db = _RecordingDB()
    _commit_updates_chunked(db, [], chunk_size=100)
    assert db.transactions == 0
