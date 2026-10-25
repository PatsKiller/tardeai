"""Batch 31: Watch "Resolve" — no false conflicts, always actionable, visible request state (operator 2026-10-25).

Live on cdb929ed5 every My Watchlist row (17/17) and every prospect (12/12) said "Ask the CIO" as a conflict only because
the canonical CIO stance was missing; the request went to the priority queue and the acquisition run's outcome
(e.g. FATN BLOCKED_PENDING_ACQUISITION_AND_CURATION five times) never reached the row. Disposable roots only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import api_v3_opportunities as api  # noqa: E402
from scripts.lib import site_payload_reads as reads  # noqa: E402
from scripts.lib import symbol_thesis_priority as stp  # noqa: E402

NOW = datetime(2026, 10, 25, 14, tzinfo=timezone.utc)
GAP = {"reason": "CIO stance or conviction unavailable for this security GUID"}


def _resolver(**truth):
    base = {"stance": None, "conviction": None, "as_of": None, "stale": True, "gap": None, "conflicts": []}
    return lambda guid, **kw: {**base, **truth}


def _row(sym="FATN", **kw):
    return {"symbol": sym, "security_guid": "guid-" + sym, "stance": None, "conviction": None, "conflicts": [],
            "next_action": {"kind": "propose", "label": "Propose"}, **kw}


# ── 1. a missing CIO stance is not a conflict ─────────────────────────────────────────────────────────────────

def test_missing_stance_is_cio_missing_not_a_conflict():
    out = reads.canonical_rows([_row(), _row("SCHD")], resolver=_resolver(gap=GAP), projection={})
    for r in out:
        assert r["next_action"]["kind"] == "cio_missing"
        assert r["next_action"]["label"] == "Ask the CIO for a view"
        assert r["next_action"]["reason"] == GAP["reason"] and r["next_action"]["gap"] == GAP
        assert r["conflicts"] == []
        assert GAP["reason"] in r["whats_missing"]


def test_missing_stance_never_hides_protect_or_an_existing_conflict():
    protect = _row(next_action={"kind": "protect", "label": "Protect first"})
    legacy = _row("NAVN", conflicts=[{"kind": "trade_ai_block", "summary": "Trade AI deterministic fail"}],
                  next_action={"kind": "resolve_conflict", "label": "Resolve conflict"})
    out = reads.canonical_rows([protect, legacy], resolver=_resolver(gap=GAP), projection={})
    assert out[0]["next_action"]["kind"] == "protect"
    assert out[1]["next_action"]["kind"] == "resolve_conflict"


def test_real_unresolved_finding_still_resolves_and_resolved_one_does_not():
    side = {"value": "HOLD", "source_label": "CIO", "as_of": NOW.isoformat()}
    open_c = {"summary": "stance disagrees", "source_a": side, "source_b": {**side, "value": "TRIM"}, "resolved": False}
    done_c = {**open_c, "resolved": True}
    truth = {"stance": "HOLD", "conviction": 60, "as_of": NOW.isoformat(), "stale": False}
    a = reads.canonical_rows([_row()], resolver=_resolver(conflicts=[open_c], **truth), projection={})[0]
    b = reads.canonical_rows([_row()], resolver=_resolver(conflicts=[done_c], **truth), projection={})[0]
    assert a["next_action"]["kind"] == "resolve_conflict"
    assert b["next_action"]["kind"] == "propose"  # a proven-resolved record is history, not a new blocker
    assert len(b["conflicts"]) == 1


def test_clean_cio_view_leaves_the_producer_step():
    out = reads.canonical_rows([_row()], resolver=_resolver(stance="WATCH", conviction=55, stale=False), projection={})
    assert out[0]["next_action"]["kind"] == "propose"


# ── 3. request state from the queue and the acquisition ledger ───────────────────────────────────────────────

def _write(root, rel, rows):
    path = root.joinpath(*rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _blocked(sym, at):
    return {"symbol": sym, "status": "BLOCKED", "as_of": at, "gate": "BLOCKED_PENDING_ACQUISITION_AND_CURATION",
            "block_reason": "BLOCKED_PENDING_ACQUISITION_AND_CURATION", "remaining_gaps": ["insufficient_contradictory_rag"],
            "pending_curation_n": 5}


def test_review_states_cover_none_queued_blocked_answered_expired(tmp_path):
    stp._STATE_CACHE.clear()
    t = lambda h: (NOW - timedelta(hours=h)).isoformat()  # noqa: E731
    _write(tmp_path, stp.RELPATH, [
        {"symbol": "FATN", "requested_at": t(30), "source": "operator_opportunity_view", "conflict_key": "k1", "request_id": "rr_1"},
        {"symbol": "QUE", "requested_at": t(24 * 20), "source": "sec_fundamentals_ingest"},
        {"symbol": "QUE", "requested_at": t(2), "source": "operator_opportunity_view"},
        {"symbol": "DONE", "requested_at": t(30), "source": "cio_opportunity_curator"},
        {"symbol": "OLD", "requested_at": t(24 * 10), "source": "operator_opportunity_view"},
    ])
    _write(tmp_path, stp.LEDGER_RELPATH, [_blocked("FATN", t(h)) for h in (5, 4, 3, 2, 1)] + [
        {"symbol": "DONE", "status": "PUBLISHED", "as_of": t(1)}])
    s = stp.review_states(["fatn", "QUE", "DONE", "OLD", "NEW"], tmp_path, now=NOW)
    assert s["NEW"]["status"] == "none" and s["NEW"]["open"] is False
    assert s["QUE"]["status"] == "queued" and s["QUE"]["label"] == "Queued for the CIO" and s["QUE"]["open"]
    assert s["QUE"]["queued_at"] == t(2) and s["QUE"]["requested_by"] == "operator_opportunity_view"  # aged-out ask ignored
    f = s["FATN"]
    assert f["status"] == "blocked" and f["open"] and f["attempts_since_request"] == 5
    assert f["label"].startswith("Blocked: waiting for evidence — no contradicting evidence on file yet")
    assert "5 new items awaiting curation" in f["label"]
    assert f["last_attempt"]["block_reason"] == "BLOCKED_PENDING_ACQUISITION_AND_CURATION"
    assert f["queued_at"] == t(30) and f["expires_at"] == (NOW - timedelta(hours=30) + timedelta(days=stp.TTL_DAYS)).isoformat()
    assert f["conflict_key"] == "k1" and f["request_id"] == "rr_1"
    assert s["DONE"]["status"] == "answered" and s["DONE"]["open"] is False
    assert s["OLD"]["status"] == "expired" and "ask again" in s["OLD"]["label"]


def test_attach_review_states_names_an_unreadable_source():
    def broken(symbols):
        raise OSError("disk")
    out = reads.attach_review_states([{"symbol": "fatn"}], reader=broken)
    assert out[0]["review_state"]["status"] == "unavailable" and "OSError" in out[0]["review_state"]["label"]
    ok = reads.attach_review_states([{"symbol": "fatn"}], reader=lambda s: {"FATN": {"status": "queued"}})
    assert ok[0]["review_state"] == {"status": "queued"}


def test_prospects_page_rows_carry_review_state():
    payload = {"lanes": [{"id": "actionable", "items": [_row()]}]}
    out = reads.prospects_page(payload, {}, stance_resolver=_resolver(gap=GAP), stance_projection={},
                               section_reader=lambda root, guids: {}, section_root=Path("."),
                               review_reader=lambda syms: {s: {"status": "blocked", "label": "Blocked: x"} for s in syms})
    item = out["lanes"][0]["items"][0]
    assert item["review_state"]["status"] == "blocked" and item["next_action"]["kind"] == "cio_missing"


# ── request_review returns the state; a conflict key is linked when the ledger exists ────────────────────────

def _stp(tmp_path, monkeypatch):
    stp._STATE_CACHE.clear()
    monkeypatch.setattr(stp, "_root", lambda root=None: tmp_path)
    monkeypatch.setattr(api, "_priority", lambda: stp)


def test_request_review_returns_visible_state_not_silent_already_queued(tmp_path, monkeypatch):
    _stp(tmp_path, monkeypatch)
    code, out = api.request_review("fatn", {"note": "Watch"})
    assert code == 200 and out["review_state"]["status"] == "queued" and out["request_id"].startswith("rr_")
    assert "conflict_ledger" not in out
    _write(tmp_path, stp.LEDGER_RELPATH, [_blocked("FATN", datetime.now(timezone.utc).isoformat())])
    code, again = api.request_review("FATN", {})
    assert again["already_open"] is True and again["review_state"]["status"] == "blocked"
    assert len(stp._rows(tmp_path.joinpath(*stp.RELPATH))) == 1


def test_conflict_key_without_ledger_is_a_named_noop(tmp_path, monkeypatch):
    _stp(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "_conflict_root", lambda: tmp_path / "state")
    code, out = api.request_review("FATN", {"conflict_key": "security:guid-FATN:U2:stance"},
                                   identity=lambda s, k: {"security_guid": "guid-FATN", "identity_status": "CONFIRMED"})
    assert code == 200 and out["conflict_ledger"] == {"recorded": False,
                                                      "reason": "conflict ledger not yet produced; the queue request stands"}
    saved = stp._rows(tmp_path.joinpath(*stp.RELPATH))[-1]
    assert saved["conflict_key"] == "security:guid-FATN:U2:stance" and saved["request_id"] == out["request_id"]
    assert saved["identity_status"] == "CONFIRMED" and saved["schema"] == "SymbolThesisPriorityRequest@v1"


class _Ledger:
    def __init__(self, guid="guid-FATN", label="FATN"):
        self.calls = []
        self.record = {"subject": {"kind": "security", "id": guid, "label": label}, "revision": 4}

    def records(self):
        return {"k1": self.record}

    def transition(self, key, event, **kw):
        self.calls.append((key, event, kw))
        return {"event_id": "conflict-x", "event": event}


def test_conflict_key_records_review_queued_with_readback(tmp_path, monkeypatch):
    _stp(tmp_path, monkeypatch)
    ledger = _Ledger()
    link = lambda sym, key, request_id: api._link_conflict(sym, key, request_id=request_id, ledger=ledger, root=tmp_path, now=NOW)  # noqa: E731
    _, out = api.request_review("FATN", {"conflict_key": "k1"}, link=link,
                                identity=lambda s, k: {"security_guid": "guid-FATN", "identity_status": "CONFIRMED"})
    assert out["conflict_ledger"] == {"recorded": True, "event_id": "conflict-x"}
    key, event, kw = ledger.calls[0]
    assert (key, event) == ("k1", "review_queued") and kw["review_request_id"] == out["request_id"] and kw["apply"] is True
    # A second ask for the same key while open is not duplicated; a different key files a linked request.
    _, again = api.request_review("FATN", {"conflict_key": "k1"}, link=link,
                                  identity=lambda s, k: {"security_guid": "guid-FATN", "identity_status": "CONFIRMED"})
    assert again["already_open"] is True and "conflict_ledger" not in again and len(ledger.calls) == 1


def test_unproven_identity_or_unknown_key_is_refused_with_reason(tmp_path, monkeypatch):
    _stp(tmp_path, monkeypatch)
    ledger = _Ledger(guid="guid-OTHER")
    link = lambda sym, key, request_id: api._link_conflict(sym, key, request_id=request_id, ledger=ledger, root=tmp_path, now=NOW)  # noqa: E731
    _, out = api.request_review("FATN", {"conflict_key": "k1"}, link=link,
                                identity=lambda s, k: {"security_guid": "guid-FATN", "identity_status": "CONFIRMED"})
    assert out["conflict_ledger"]["recorded"] is False and "identity" in out["conflict_ledger"]["reason"]
    _, out = api.request_review("FATN", {"conflict_key": "missing"}, link=link,
                                identity=lambda s, k: {"security_guid": "guid-FATN", "identity_status": "CONFIRMED"})
    assert out["conflict_ledger"] == {"recorded": False, "reason": "conflict key not found in the ledger"}
    assert ledger.calls == []
