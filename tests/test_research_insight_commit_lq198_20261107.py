"""LQ-20261107-198: the batch path shared one connection and never committed, so close() rolled back every row
while the receipt reported them as produced. Each successful row must be committed; a failed row rolls back alone."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_insight_extractor as rie  # noqa: E402


class FakeCur:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self):
        self.log = []

    def commit(self):
        self.log.append("commit")

    def rollback(self):
        self.log.append("rollback")

    def close(self):
        self.log.append("close")


def _run(monkeypatch, fn, rows, fail_ids=()):
    conn = FakeConn()
    monkeypatch.setattr(rie, "_open_session", lambda dry: {"conn": conn, "cur": FakeCur(rows)})

    def fake_extract(text, *, source_reference, **kw):
        conn.log.append(f"insert:{source_reference}")
        if any(source_reference.endswith(f":{i}") for i in fail_ids):
            raise RuntimeError("boom")
        return {"id": 1, "active": True}

    monkeypatch.setattr(rie, "extract_insight", lambda text, **kw: fake_extract(text, **kw))
    errors = []
    out = fn(errors=errors, skips={})
    return conn.log, out, errors


def test_news_rows_committed_before_close(monkeypatch):
    rows = [{"id": i, "title": "A long enough headline", "summary": "with a summary"} for i in (1, 2)]
    log, out, _ = _run(monkeypatch, rie.extract_from_news, rows)
    assert len(out) == 2
    assert log == ["insert:news:1", "commit", "insert:news:2", "commit", "close"]


def test_catalyst_failed_row_rolls_back_alone(monkeypatch):
    rows = [{"id": i, "headline": "A long enough headline", "description": "and text"} for i in (1, 2, 3)]
    log, out, errors = _run(monkeypatch, rie.extract_from_catalysts, rows, fail_ids=(2,))
    assert len(out) == 2 and len(errors) == 1
    assert log == ["insert:catalyst:1", "commit", "insert:catalyst:2", "rollback",
                   "insert:catalyst:3", "commit", "close"]
