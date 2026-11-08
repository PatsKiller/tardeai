"""CIO_ASK_SNAPSHOT_SHARED: one collect parses the CIO record store once, not once per entity (LQ-20261107-484).

Live 2026-11-07 19:00 ET: internal.cio_record_research (15 s) and market.quote (6 s) both timed out. The record source
called load_snapshot() per entity: a ~420 MB jsonl, ~3.5 s of GIL-holding CPU each, on a host at load 19. Synthetic."""
import threading
from datetime import datetime, timezone

from scripts.lib import cio_ask_research as R
from scripts.lib.data_broker import cio_company_facts as C

NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)


def _ent(n):
    return R.Entity(label=f"Example {n}", kind="listed", symbol=f"EX{n}", security_guid=f"g{n}", identity_status="RESOLVED")


def test_snapshot_loaded_once_per_context_across_threads(monkeypatch):
    calls = []
    monkeypatch.setattr(C, "load_snapshot", lambda root=None, **k: calls.append(root) or {})
    ctx = R.ResearchContext(question="q", now=NOW, state_root="/nonexistent-synthetic")
    out = []
    ts = [threading.Thread(target=lambda: out.append(R._cio_snapshot(ctx))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 1 and len(out) == 6 and all(o is out[0] for o in out)


def test_each_context_gets_its_own_snapshot(monkeypatch):
    calls = []
    monkeypatch.setattr(C, "load_snapshot", lambda root=None, **k: calls.append(1) or {})
    for _ in range(2):
        R._cio_snapshot(R.ResearchContext(question="q", now=NOW))
    assert len(calls) == 2  # no cross-run cache: a later collect must see appended records


def test_record_source_per_entity_does_not_reload(monkeypatch):
    calls = []
    monkeypatch.setattr(C, "load_snapshot", lambda root=None, **k: calls.append(1) or {})
    ctx = R.ResearchContext(question="q", now=NOW)
    for n in range(4):
        R._src_cio_record_research(_ent(n), ctx)
    assert len(calls) == 1
