"""LQ-20261107-2215: portfolio-server per-request memory — candidate fixes, fail-before / pass-after.

COVERS = ["scripts/lib/data_broker/cio_prospect.py", "scripts/lib/data_broker/trade_journey.py",
          "scripts/lib/cio_ask_store.py", "scripts/lib/cio_ask_core.py", "scripts/lib/cio_ask_api.py",
          "scripts/lib/whole_site_truth.py", "scripts/control_plane_api.py"]

Synthetic fixtures only (tmp_path, made-up symbols "ZZQA"/"ZZQB"); no host store, no live server, no
network, no broker, no model call.

A  the stance reader parsed the 61 MB prospect shadow on every call and discarded it
B  GET /cio/asks?group_by=… parsed the ask ledger (2 * threads + 3) times
C  the surface-authority child probed every collection domain under two roots that are the same files
E  /control-plane/research held every row of a 97 MB JSONL to answer a 50-row page
"""
from __future__ import annotations

import json
import sys
import tracemalloc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_ask_api as api  # noqa: E402
from scripts.lib import cio_ask_core as core  # noqa: E402
from scripts.lib.cio_ask_store import AskEventStore  # noqa: E402

GUID_A = "aaaaaaaa-0000-4000-8000-00000000000a"
GUID_B = "bbbbbbbb-0000-4000-8000-00000000000b"


# ── A: the discarded shadow parse ────────────────────────────────────────────────────────────────────────────────
def test_A_stance_reader_never_parses_the_shadow_it_discards(monkeypatch):
    # trade_journey imports ``lib.data_broker.cio_prospect`` (scripts/ on sys.path), a different module object
    # from ``scripts.lib.data_broker.cio_prospect``; patch the one it actually calls.
    from lib.data_broker import cio_prospect as cp
    from scripts.lib.data_broker import trade_journey as tj

    loads = []
    monkeypatch.setattr(cp, "_load_shadow", lambda base: (loads.append(base), ({"prospects": [{"symbol": "ZZQA"}]}, "x"))[1])
    monkeypatch.setattr(tj, "_db_query", lambda: None)
    monkeypatch.setattr(cp._ir(), "prospect_store_status",
                        lambda table_probe=None: {"live": False, "mode": "shadow", "reasons": ["dual_write_flag_off"]})
    rows, why = tj._cio_prospects(["ZZQA"])
    assert (rows, why) == (None, "shadow")  # unchanged answer: the store is not live
    assert loads == [], f"the shadow was parsed {len(loads)}x for a result that is thrown away"


def test_A_load_shadow_false_still_says_shadow_and_never_looks_empty_live(tmp_path):
    from scripts.lib.data_broker import cio_prospect as cp

    p = tmp_path / "cio_prospect_shadow.json"
    p.write_text(json.dumps({"as_of": "2026-11-11T00:00:00+00:00", "prospects": [{"symbol": "ZZQA", "stage": "watch"}]}))
    status = {"live": False, "mode": "shadow", "reasons": ["dual_write_flag_off"]}
    full = cp.get_prospects(shadow_base=p, status=status)
    lean = cp.get_prospects(shadow_base=p, status=status, load_shadow=False)
    assert full["count"] == 1 and full["source"]["kind"] == "shadow"
    assert lean["source"]["kind"] == "shadow" and lean["source"]["shadow_loaded"] is False
    assert lean["count"] == 0 and lean["store_status"]["live"] is False
    # the default is unchanged for every other caller of get_prospects
    assert full["source"]["shadow_loaded"] is True


# ── B: one ledger parse per request ──────────────────────────────────────────────────────────────────────────────
def _ent(sym, guid):
    return {"name": sym, "kind": "security", "symbol": sym, "security_guid": guid, "resolution": "CONFIRMED"}


def _ledger(tmp_path, n_threads=6):
    st = AskEventStore(tmp_path / "cio_ask_events.jsonl")
    for i in range(n_threads):
        tid, aid = f"thr_{i:016x}", f"ask_{i:016x}"
        sym, guid = ("ZZQA", GUID_A) if i % 2 else ("ZZQB", GUID_B)
        at = f"2026-11-0{1 + i % 9}T14:00:00+00:00"
        st.append("ask.asked", {"thread_id": tid, "ask_id": aid, "question": f"synthetic q{i} {sym}", "channel": "cc",
                                "asked_at": at, "turn_kind": "ask"}, event_id=f"a:{aid}")
        st.append("ask.entity_resolved", {"thread_id": tid, "ask_id": aid, "entity": _ent(sym, guid)}, event_id=f"e:{aid}")
        st.append("ask.answer_version", {"thread_id": tid, "ask_id": aid, "answer": {
            "version": 1, "status": "quick", "depth": "quick", "summary": "synthetic", "produced_at": at}}, event_id=f"v:{aid}")
        st.append("ask.check_finished", {"thread_id": tid, "outcome": "deferred", "reason": "synthetic"}, event_id=f"c:{aid}")
    return st


def _count_parses(monkeypatch, store):
    n = {"parses": 0}
    real = store._iter_raw

    def counted(*a, **k):
        n["parses"] += 1
        return real(*a, **k)

    monkeypatch.setattr(store, "_iter_raw", counted)
    return n


def test_B_threads_parses_the_ledger_once_not_once_per_thread(tmp_path, monkeypatch):
    st = _ledger(tmp_path, n_threads=6)
    n = _count_parses(monkeypatch, st)
    st.threads()
    assert n["parses"] == 1, f"threads() parsed the ledger {n['parses']}x for 6 threads"


def test_B_threads_projection_is_unchanged(tmp_path):
    """Same lifecycle as the per-thread re-parse produced (the old algorithm, computed here directly)."""
    from scripts.lib.cio_ask_lifecycle import project_lifecycle

    st = _ledger(tmp_path, n_threads=5)
    th = st.threads()
    assert len(th) == 5
    for tid, t in th.items():
        assert t["lifecycle"] == project_lifecycle(t, st.events(thread_id=tid))
    snap_threads, snap_events = st.snapshot()
    assert snap_threads == th and snap_events == st.events()


class _Deps:
    def __init__(self, store):
        self.store = store
        self.facts_for = lambda e: {}
        self.stance_for = lambda syms: {}


def _ctx(deps):
    return api.Ctx(principal=lambda: "tailnet:operator@example.invalid", listener=lambda: "serve_proxy",
                   csrf=lambda m, p: (True, ""), allowed_logins=frozenset({"operator@example.invalid"}), deps=deps)


def test_B_grouped_asks_get_parses_the_ledger_once(tmp_path, monkeypatch):
    st = _ledger(tmp_path, n_threads=6)
    monkeypatch.setattr(core, "_deps", lambda d: d)
    n = _count_parses(monkeypatch, st)
    s, body = api.handle("/api/v2/cio/asks", "GET", query={"group_by": "security"}, ctx=_ctx(_Deps(st)))
    assert s == 200 and body["data"]["grouped"]["group_by"] == "security" and len(body["data"]["threads"]) == 6
    assert n["parses"] == 1, f"one GET parsed the ledger {n['parses']}x"


def test_B_grouped_asks_answer_is_unchanged(tmp_path, monkeypatch):
    from scripts.lib import cio_ask_groups as groups

    st = _ledger(tmp_path, n_threads=6)
    monkeypatch.setattr(core, "_deps", lambda d: d)
    deps = _Deps(st)
    s, body = api.handle("/api/v2/cio/asks", "GET", query={"group_by": "security"}, ctx=_ctx(deps))
    assert body["data"]["threads"] == core.list_threads(deps=deps, limit=50)
    want = groups.group_questions(st.threads(), group_by="security", q="", channel=None, events=st.events(),
                                  facts_for=deps.facts_for, stance_for=deps.stance_for)
    got = body["data"]["grouped"]
    assert {g["key"]: g["counts"] for g in got["groups"]} == {g["key"]: g["counts"] for g in want["groups"]}
    # the ungrouped list is unchanged too
    s2, plain = api.handle("/api/v2/cio/asks", "GET", ctx=_ctx(deps))
    assert s2 == 200 and plain["data"]["threads"] == body["data"]["threads"] and "grouped" not in plain["data"]


# ── C: the surface-authority child probes each set of files once ─────────────────────────────────────────────────
@pytest.fixture
def symlinked_roots(tmp_path, monkeypatch):
    """Served layout: the checkout's data/* are symlinks into the state root."""
    state, checkout = tmp_path / "state", tmp_path / "checkout"
    (state / "data" / "runtime").mkdir(parents=True)
    (state / "data" / "runtime" / "identity_registry.json").write_text(json.dumps([{"id": "e1", "kind": "entity"}]))
    (state / "data" / "cio").mkdir(parents=True)
    checkout.mkdir()
    (checkout / "data").symlink_to(state / "data")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    return state, checkout


def _stub_probes(monkeypatch, wst):
    calls = []

    def probe(domain, state_root, root):
        calls.append((domain, str(state_root)))
        return {"served": True, "http_status": 200, "ok": True, "data_quality": "AVAILABLE",
                "evidence_class": None, "freshness": None, "item_count": 1, "reason": None}

    monkeypatch.setattr(wst, "_probe_domain", probe)
    return calls


def test_C_collection_domains_are_probed_once_when_both_roots_are_the_same_files(symlinked_roots, monkeypatch):
    from scripts.lib import whole_site_truth as wst
    import control_plane_api as cpa

    state, checkout = symlinked_roots
    calls = _stub_probes(monkeypatch, wst)
    rep = wst.control_plane_surface_authority(checkout)
    domains = {s["domain"] for s in wst.CONTROL_PLANE_SURFACES.values() if s["domain"]}
    collections = {d for d in domains if cpa.CONTROL_PLANE_DOMAINS[d]["kind"] == "collection"}
    computed = domains - collections
    assert collections and computed
    # each (domain, root) at most once per call, and a collection never twice
    assert len(calls) == len(set(calls)), f"repeated probes: {sorted(calls)}"
    per_domain = {d: sum(1 for c in calls if c[0] == d) for d in domains}
    assert all(per_domain[d] == 1 for d in collections), per_domain
    assert all(per_domain[d] == 2 for d in computed), per_domain  # computed domains are still probed under both roots
    for s in rep["surfaces"]:
        if s["live_domain"] in collections:
            assert s["live"]["checkout"]["probe"] == "same_files_as_served"


def test_C_different_files_are_still_probed_and_disagreement_still_reported(tmp_path, monkeypatch):
    from scripts.lib import whole_site_truth as wst

    state, checkout = tmp_path / "state", tmp_path / "checkout"
    (state / "data" / "runtime").mkdir(parents=True)
    (state / "data" / "runtime" / "identity_registry.json").write_text(json.dumps([{"id": "e1", "kind": "entity"}]))
    (checkout / "data" / "runtime").mkdir(parents=True)  # a real directory, not the state root: different files
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    rep = wst.control_plane_surface_authority(checkout)
    ident = next(s for s in rep["surfaces"] if s["live_domain"] == "identity")
    assert ident["live"]["checkout"]["probe"] == "probed"
    assert ident["live"]["data_quality"] == "AVAILABLE"
    assert ident["live"]["checkout"]["data_quality"] != "AVAILABLE"
    assert ident["live"]["roots_disagree"] is True


# ── E: a page of a plain JSONL source holds the page, not the file ───────────────────────────────────────────────
N_ROWS = 4000


@pytest.fixture
def research_root(tmp_path, monkeypatch):
    p = tmp_path / "data" / "cio" / "hermes_research_requests.jsonl"
    p.parent.mkdir(parents=True)
    pad = "x" * 1500
    with p.open("w") as fh:
        for i in range(N_ROWS):
            fh.write(json.dumps({"request_id": f"req_{i:05d}", "symbol": "ZZQA", "status": "done", "note": pad}) + "\n")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return p


def test_E_research_page_peak_memory_is_bounded_by_the_page(research_root):
    import control_plane_api as cpa

    size = research_root.stat().st_size
    tracemalloc.start()
    try:
        s, body = cpa.handle("/api/v3/control-plane/research")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert s == 200 and body["data_quality"] == "AVAILABLE"
    assert peak < size / 4, f"peak {peak / 1e6:.1f} MB to page a {size / 1e6:.1f} MB file"


def test_E_research_page_rows_and_total_are_unchanged(research_root):
    import control_plane_api as cpa

    s, body = cpa.handle("/api/v3/control-plane/research")
    items = body["data"]["items"]
    assert [r["request_id"] for r in items] == [f"req_{i:05d}" for i in range(50)]
    assert body["data"]["pagination"] == {"limit": 50, "offset": 0, "total": N_ROWS}
    s, body = cpa.handle("/api/v3/control-plane/research", query={"offset": str(N_ROWS - 10), "limit": "50"})
    assert [r["request_id"] for r in body["data"]["items"]] == [f"req_{i:05d}" for i in range(N_ROWS - 10, N_ROWS)]
    assert body["data"]["pagination"]["total"] == N_ROWS


def test_E_one_corrupt_line_is_still_invalid_schema(research_root):
    import control_plane_api as cpa

    with research_root.open("a") as fh:
        fh.write("{not json\n")
    s, body = cpa.handle("/api/v3/control-plane/research")
    assert body["data_quality"] != "AVAILABLE"
    assert body["data"]["items"] == []
