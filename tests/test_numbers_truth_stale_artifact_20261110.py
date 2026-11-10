"""LQ-20261107-1739 — page on broker truth, never on page drift.

The 19:4x dry run paged three fingerprints, and all three compared the CIO overnight-brief ARTIFACT (built before the
XAR stop existed, on an older release) with today's broker book. XAR had a working 229.33 x100 stop at the broker:
the operator could act on none of it, so those pages were false positives. The contract this module pins:

  * a stop/coverage finding whose SHOWN side is a producer artifact older than the truth read is marked
    ``stale_artifact`` by the audit; the engine heals that producer FIRST, then tickets it, and NEVER pages it;
  * a freshly rebuilt artifact whose mismatch survives is the page's own defect again and pages normally;
  * ``NT_UNPROTECTED`` truth excludes holdings the broker cannot carry a resting stop for (mutual funds), classified
    from the row's own ``asset_type`` — never from a symbol list;
  * the page-worthy event is broker truth: a held, stoppable position whose stop order EXPIRED at the close, with
    the phone sentence "your stop expired at the close (Day order)".

Synthetic fixtures only: no store, no broker, no sender. The live capture was read, never copied into the tree.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import numbers_truth_strikes as S  # noqa: E402
from scripts import numbers_truth_audit as A  # noqa: E402
from scripts.lib.instrument_normalize import is_stopless_asset  # noqa: E402

NOW = datetime(2026, 11, 10, 0, 38, tzinfo=timezone.utc)

CONFIG = {
    "rate_limit": {"per_lane_per_hour": 1},
    "page_codes": ["NT_STOP_PRICE_MISMATCH", "NT_STOP_QTY_MISMATCH", "NT_UNPROTECTED", "NT_STOP_EXPIRED"],
    "known_disagreement": [],
    "healable": {"cio-overnight-brief": {"mode": "live"}},
    "by_figure_id": {"cio.stop_advice.stop_now": "cio-overnight-brief",
                     "cio.stop_advice.stop_qty": "cio-overnight-brief",
                     "cio.uncovered_count": "cio-overnight-brief"},
    "by_page": {},
    "default_lane": None,
    "escalation": {"domain": "data", "kind_ticket": "numbers_truth_ticket",
                   "kind_cleared": "numbers_truth_cleared"},
}


def _write(path: Path, doc) -> Path:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    tmp.replace(path)
    return path


def _config(tmp_path: Path, **overrides) -> Path:
    return _write(tmp_path / "heal.json", {**CONFIG, **overrides})


def _finding(code: str, *, figure="cio.stop_advice.stop_now", symbol="xar", account="schwab_rollover_ira",
             shown=None, truth=None, reason=None) -> dict:
    return {
        "fingerprint": S.fingerprint("/cio", figure, account, symbol),
        "page": "/cio", "figure_id": figure, "account": account, "symbol": symbol,
        "severity": "P0", "status": "MISMATCH", "code": code,
        "detail": f"{code} synthetic",
        "shown": shown or {"value": None, "source": "artifact:data/runtime/cio_overnight_brief/latest.json"},
        "truth": truth or {"value": 229.33, "provider": "stop_lifecycle", "as_of": "2026-11-10T00:35:10+00:00"},
        "reason": reason,
    }


def _boom(**_kw):
    raise AssertionError("no sender may be reached")


# ── the engine: a stale artifact heals first, tickets, and never pages ────────────────────────────────────────


def test_a_stale_artifact_heals_its_producer_first_and_never_pages(tmp_path):
    state = tmp_path / "state.json"
    f = _finding("NT_STOP_PRICE_MISMATCH", reason="stale_artifact")
    got = S.run(findings=[f], state_path_=state, config_path=_config(tmp_path), apply=True, now=NOW,
                heal=lambda **kw: {"accepted": True, "run_id": "syn:1"}, escalate=_boom, critical=_boom)
    assert [d["action"] for d in got["decisions"]] == [S.ACTION_HEAL]
    assert got["decisions"][0]["lane"] == "cio-overnight-brief"
    assert got["decisions"][0]["paged"] is False
    assert got["counts"]["heals"] == 1 and got["counts"]["tickets"] == 0


def test_the_next_audit_tickets_the_stale_artifact_without_ever_paging(tmp_path):
    state = tmp_path / "state.json"
    f = _finding("NT_STOP_QTY_MISMATCH", reason="stale_artifact")
    cfg = _config(tmp_path)
    S.run(findings=[f], state_path_=state, config_path=cfg, apply=True, now=NOW,
          heal=lambda **kw: {"accepted": True, "run_id": "syn:1"}, escalate=_boom, critical=_boom)
    got = S.run(findings=[f], state_path_=state, config_path=cfg, apply=True,
                now=NOW + timedelta(hours=1), heal=_boom, escalate=_boom, critical=_boom)
    assert [d["action"] for d in got["decisions"]] == [S.ACTION_TICKET]
    assert got["decisions"][0]["reason"] == S.STALE_ARTIFACT
    assert got["decisions"][0]["paged"] is False
    taken = got["actions"][0] if "actions" in got else None
    assert taken is None or "critical" not in taken


def test_a_fresh_artifacts_surviving_mismatch_is_the_pages_defect_and_pages(tmp_path):
    f = _finding("NT_STOP_PRICE_MISMATCH")  # no stale_artifact reason: the artifact was rebuilt and still disagrees
    calls = []
    state = tmp_path / "state.json"
    _write(state, {"schema": S.STATE_SCHEMA, "figures": {
        f["fingerprint"]: {"consecutive_fails": 3, "status": "striking", "page": "/cio",
                           "figure_id": f["figure_id"], "account": f["account"], "symbol": f["symbol"],
                           "check": f["code"]}}})

    def critical(*, decision, now=None):
        calls.append(decision)
        return {"ok": True, "delivered": True}

    got = S.run(findings=[f], state_path_=state, config_path=_config(tmp_path), apply=True,
                now=NOW, heal=_boom, escalate=lambda **kw: {"ok": True, "queued": True}, critical=critical,
                inbox=tmp_path / "inbox")
    assert [d["action"] for d in got["decisions"]] == [S.ACTION_TICKET]
    assert got["decisions"][0]["paged"] is True
    assert len(calls) == 1


# ── the broker-truth page: an expired Day stop ───────────────────────────────────────────────────────────────


def test_an_expired_day_stop_pages_the_operator_sentence(tmp_path):
    f = _finding("NT_STOP_EXPIRED", symbol="spcx", account="schwab_taxable", figure="cio.uncovered_count",
                 shown={"value": 132.65, "qty": 200, "source": "stop_lifecycle", "status": "expired",
                        "order_id": "1008604668754", "as_of": "2026-11-10T00:40:09+00:00"},
                 truth={"value": None, "provider": "stop_lifecycle", "working": False,
                        "as_of": "2026-11-10T00:40:09+00:00"})
    state = tmp_path / "state.json"
    _write(state, {"schema": S.STATE_SCHEMA, "figures": {
        f["fingerprint"]: {"consecutive_fails": 3, "status": "striking", "page": "/cio",
                           "figure_id": f["figure_id"], "account": f["account"], "symbol": f["symbol"],
                           "check": f["code"]}}})
    got = S.run(findings=[f], state_path_=state, config_path=_config(tmp_path), apply=True,
                now=NOW, heal=_boom, escalate=lambda **kw: {"ok": True, "queued": True},
                critical=lambda **kw: {"ok": True, "delivered": True}, inbox=tmp_path / "inbox")
    decision = got["decisions"][0]
    assert decision["action"] == S.ACTION_TICKET and decision["paged"] is True
    event = S.critical_event(decision)
    # The phone sentence names the account the way the operator does, not the internal key.
    assert event["trigger"] == "no working stop; your 132.65 Day stop expired at the close"
    assert event["account"] == "Schwab Individual"
    assert event["action"] == "place a new stop before the next open"
    assert event["what"] == (
        "SPCX 200 sh Schwab Individual: no working stop; your 132.65 Day stop expired at the close. "
        "Place a new stop before the next open.")


def test_the_expired_stop_phone_text_is_one_readable_sentence():
    """The acceptance reading (LQ-1739): one sentence, under the text cap, no fingerprint, no path, no key."""
    from scripts.lib import critical_texts as CT

    f = _finding("NT_STOP_EXPIRED", symbol="spcx", account="schwab_taxable", figure="cio.uncovered_count",
                 shown={"value": 132.65, "qty": 200, "source": "stop_lifecycle", "status": "expired",
                        "order_id": "1008604668754"},
                 truth={"value": None, "provider": "stop_lifecycle", "working": False})
    f.update({"check": f["code"], "fails": 4, "served": f["shown"]})  # the engine's decision shape
    text = CT.format_text(S.critical_event(f), max_chars=CT.MAX_TEXT_CHARS)
    assert text == ("ACT NOW SPCX (Schwab Individual) no working stop; your 132.65 Day stop expired at the "
                    "close. Suggest place a new stop before the next open. CC Risk")
    assert len(text) <= CT.MAX_TEXT_CHARS
    for noise in ("/cio", "NT_", "schwab_taxable", "stop_lifecycle", "uncovered_count", "x200"):
        assert noise not in text


# ── the audit: mutual funds are not coverage gaps; the expired stop is broker truth ──────────────────────────


def _position(account, symbol, asset_type, qty=100.0):
    return {"account_key": account, "symbol": symbol, "qty": qty, "asset_type": asset_type, "is_cash": False,
            "broker_market_value": qty * 10.0}


def _stop(account, symbol, *, status, lifecycle, stop_price=100.0, qty=100.0, order_id="O-1"):
    return {"account": account, "symbol": symbol, "status": status, "lifecycle": lifecycle,
            "stop_price": stop_price, "qty": qty, "order_id": order_id, "snapshot_at": "2026-11-10T00:40:09+00:00"}


def _bundle(positions, stops):
    b = A.Bundle()
    b.put("positions", rows=positions, as_of=NOW)
    b.put("stops", rows=stops, as_of=NOW)
    return b


def test_a_mutual_fund_is_not_counted_uncovered_but_an_etf_is():
    bundle = _bundle(
        [_position("ira", "AMANX", "MUTUAL_FUND"), _position("ira", "XLV", "ETF"),
         _position("taxable", "SPCX", "EQUITY")],
        [_stop("ira", "ANET", status="working", lifecycle="working")],
    )
    cov = A.truth_bundle_coverage(bundle, {}, now=NOW, session=False)
    assert cov["status"] == "ok"
    assert cov["rows"]["uncovered"] == 2  # XLV + SPCX: the mutual fund is not a stoppable holding
    keys = {f["key"] for f in cov["rows"]["findings"] if f["code"] == "UNCOVERED"}
    assert keys == {"uncovered:ira:XLV", "uncovered:taxable:SPCX"}


def test_the_expired_stop_is_reported_as_broker_truth_with_the_operator_words():
    bundle = _bundle(
        [_position("taxable", "SPCX", "EQUITY")],
        [_stop("taxable", "SPCX", status="expired", lifecycle="cancelled", stop_price=132.65, qty=200,
               order_id="1008604668754")],
    )
    row = {"page": "/cio", "figure_id": "cio.uncovered_count", "severity": "P0", "producer_lane": "cio-overnight-brief",
           "served_from": {"value": ["/counts/uncovered_positions"]}}
    doc = {"counts": {"uncovered_positions": 1}}
    found = A.coverage(row, bundle, doc, {"source": "artifact:data/runtime/cio_overnight_brief/latest.json",
                                          "as_of": (NOW - timedelta(hours=3)).isoformat()}, now=NOW, session=False)
    expired = [f for f in found if f["code"] == "NT_STOP_EXPIRED"]
    assert len(expired) == 1
    f = expired[0]
    assert "your stop expired at the close (Day order)" in f["detail"]
    assert f["account"] == "taxable" and f["symbol"] == "SPCX"
    assert f["shown"]["value"] == 132.65 and f["shown"]["qty"] == 200
    assert f["shown"]["order_id"] == "1008604668754"


def test_a_working_stop_after_an_expired_one_is_not_a_page():
    bundle = _bundle(
        [_position("taxable", "SPCX", "EQUITY")],
        [_stop("taxable", "SPCX", status="expired", lifecycle="cancelled"),
         _stop("taxable", "SPCX", status="pending_activation", lifecycle="working", stop_price=140.0)],
    )
    res = {"findings": [{"code": "UNCOVERED", "alert": True, "account": "taxable", "symbol": "SPCX"}]}
    assert A.expired_stop_events({"page": "/cio", "figure_id": "cio.uncovered_count"}, bundle, {}, res) == []


def test_is_stopless_asset_reads_the_asset_type_never_the_symbol():
    assert is_stopless_asset("MUTUAL_FUND") and is_stopless_asset("MUTUALFUND") and is_stopless_asset("mutual fund")
    assert not is_stopless_asset("ETF") and not is_stopless_asset("EQUITY")
    assert not is_stopless_asset(None)  # an unknown type is stoppable-eligible: never silently drop a name


# ── the audit marks drift as drift; a rebuilt brief is fresh ────────────────────────────────────────────────


def test_an_old_artifact_mismatch_is_marked_stale_artifact():
    f = _finding("NT_STOP_PRICE_MISMATCH")
    f["truth"] = {"value": 229.33, "provider": "stop_lifecycle", "as_of": NOW.isoformat()}
    A.mark_stale_artifacts([f], {"source": "artifact:data/runtime/cio_overnight_brief/latest.json",
                                 "as_of": (NOW - timedelta(hours=3, minutes=20)).isoformat()})
    assert f["reason"] == "stale_artifact"


def test_a_fresh_artifact_mismatch_stays_pageable():
    f = _finding("NT_STOP_PRICE_MISMATCH")
    f["truth"] = {"value": 229.33, "provider": "stop_lifecycle", "as_of": NOW.isoformat()}
    A.mark_stale_artifacts([f], {"source": "artifact:data/runtime/cio_overnight_brief/latest.json",
                                 "as_of": (NOW - timedelta(minutes=5)).isoformat()})
    assert f.get("reason") is None


def test_an_api_served_finding_is_never_marked_stale():
    f = _finding("NT_STOP_PRICE_MISMATCH")
    f["truth"] = {"value": 229.33, "provider": "stop_lifecycle", "as_of": NOW.isoformat()}
    A.mark_stale_artifacts([f], {"source": "api:/api/v2/portfolio/holdings", "as_of": None})
    assert f.get("reason") is None


def test_the_shipped_config_pages_the_broker_truth_code():
    from scripts.lib import numbers_truth_strikes as strikes

    cfg = json.loads((ROOT / "config/numbers_truth_heal.json").read_text(encoding="utf-8"))
    assert "NT_STOP_EXPIRED" in strikes.page_codes(cfg)
    assert cfg["known_disagreement"] == []


def test_the_shipped_page_set_is_exactly_the_expired_stop_code(tmp_path):
    """LQ-1759: tonight only the genuine page pages. The page set is a config list, pinned at exactly one code."""
    from scripts.lib import numbers_truth_strikes as strikes

    cfg = json.loads((ROOT / "config/numbers_truth_heal.json").read_text(encoding="utf-8"))
    assert strikes.page_codes(cfg) == frozenset({"NT_STOP_EXPIRED"})


def test_the_unprotected_count_never_pages_even_at_strike_four(tmp_path):
    """The 1749 proof's false positive: /cio uncovered_count counted a mutual fund and paged with a path.

    The producer fix is LQ-1740; until it folds, this face must reach the operator as a FINDING and a ticket only.
    """
    f = _finding("NT_UNPROTECTED", figure="cio.uncovered_count", symbol=None, account=None,
                 shown={"value": 2}, truth={"value": 3})
    state = tmp_path / "state.json"
    _write(state, {"schema": S.STATE_SCHEMA, "figures": {
        f["fingerprint"]: {"consecutive_fails": 3, "status": "striking", "page": "/cio",
                           "figure_id": f["figure_id"], "account": f["account"], "symbol": "",
                           "check": f["code"]}}})
    got = S.run(findings=[f], state_path_=state, config_path=ROOT / "config/numbers_truth_heal.json",
                apply=True, now=NOW, heal=_boom, escalate=lambda **kw: {"ok": True, "queued": True},
                critical=_boom, inbox=tmp_path / "inbox")
    decision = got["decisions"][0]
    assert decision["action"] == S.ACTION_TICKET
    assert decision["paged"] is False
    assert got["actions"][0]["taken"]["page_suppressed"] == "code_not_in_page_codes"
    assert got["counts"]["paged"] == 0


def test_the_heal_lane_resolves_a_route_page_with_its_leading_slash():
    f = _finding("NT_STOP_PRICE_MISMATCH")
    lane, why = S.heal_lane(f, {**CONFIG, "by_page": {"cio": "cio-overnight-brief"}})
    assert (lane, why) == ("cio-overnight-brief", "")


def test_every_default_write_resolves_under_the_given_state_root(tmp_path, monkeypatch):
    """LQ-1739 leak note: a replay against a throwaway state root wrote 26 FINDING files into the LIVE lead inbox.

    With a state path under a throwaway root, the FINDING, the escalation intent and a heal request must all resolve
    under that root. The live resolver is armed to fail here, so any fallback to it fails the test by name rather
    than by a quiet write into the operator's inbox.
    """
    from scripts.lib import n8n_cc_wave_c as W

    def _live_root_must_not_be_asked(*_a, **_kw):
        raise AssertionError("a default writer fell back to the live state root")

    monkeypatch.setattr(W, "state_root", _live_root_must_not_be_asked)

    root = tmp_path / "root"
    state = root / "data" / "runtime" / "numbers_truth_state.json"
    state.parent.mkdir(parents=True)
    # two findings: one that must write a FINDING file, one whose code pages (escalation intent, no sender injected)
    no_heal = _finding("NT_AUTHORITY_STATIC", figure="authority.static", symbol=None, account=None)
    paged = _finding("NT_STOP_PRICE_MISMATCH")  # no stale reason: pages
    _write(state, {"schema": S.STATE_SCHEMA, "figures": {
        paged["fingerprint"]: {"consecutive_fails": 3, "status": "striking", "page": "/cio",
                               "figure_id": paged["figure_id"], "account": paged["account"],
                               "symbol": paged["symbol"], "check": paged["code"]}}})

    S.run(findings=[no_heal, paged], state_path_=state, config_path=_config(tmp_path), apply=True, now=NOW,
          heal=_boom, critical=_boom, inbox=None)

    inbox = root / "data" / "coordination" / "coordinator" / "inbox" / "claude-lead"
    written = sorted(p.name for p in inbox.glob("FINDING-*.md"))
    assert written and all(p.startswith("FINDING-LQ-AUTO-") for p in written)
    assert (root / "data" / "runtime" / "numbers_truth_state.json").exists()


def test_a_broker_truth_expired_stop_is_never_marked_stale():
    f = _finding("NT_STOP_EXPIRED", shown={"value": 132.65, "qty": 200, "source": "stop_lifecycle"},
                 truth={"value": None, "provider": "stop_lifecycle", "as_of": NOW.isoformat()})
    A.mark_stale_artifacts([f], {"source": "artifact:data/runtime/cio_overnight_brief/latest.json",
                                 "as_of": (NOW - timedelta(hours=3)).isoformat()})
    assert f.get("reason") is None
