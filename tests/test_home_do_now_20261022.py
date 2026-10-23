"""Home "Do now" queue — HomeDoNow@v1 (operator-approved Home redesign, 2026-10-22).

One queue replaces Needs action, Requires attention, Operator inbox, Top risks and Platform on Home. The projection
(scripts/lib/data_broker/home_do_now.py) composes existing sources; these tests pin its invariants:
* the same fact from several sources is ONE item that lists every source (dedupe by id);
* money at risk sorts first, then severity, then protect > decide > fix;
* working-stop coverage from the held-exit-coverage receipt is the truth when measured; otherwise the no-stop items
  say "no stop on record … not measured";
* an unreadable / timed-out / malformed source is an item and makes ``all_sources_answered`` false;
* every source carries as_of, its basis, age and stale;
* nothing here can reach a broker, an order path or a store write.
Hermetic: in-memory payloads, a fake db_query. No database, no network, no broker.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.data_broker import home_do_now as H  # noqa: E402

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
ISO = NOW.isoformat()


def _pos(sym, value, account="schwab_rollover_ira", stop=None, dist=None, triggered=False, max_loss=0, excluded=False):
    return {"symbol": sym, "account": account, "market_value": value, "stop_price": stop, "distance_to_stop_pct": dist,
            "triggered": triggered, "max_loss_dollar": max_loss, "risk_excluded": excluded, "day_change_pct": -5.4}


def _risk(*positions, computed_at=None, heat=0.1):
    return {"computed_at": computed_at or (NOW - timedelta(seconds=30)).isoformat(),
            "portfolio": {"heat_pct": heat}, "positions": list(positions), "ok": True}


def _na(*items, answered=True, as_of=None):
    return {"schema": "NeedsAction@v1", "as_of": as_of or ISO, "all_sources_answered": answered, "total": len(items),
            "items": list(items), "sources": {"health": {"status": "OK" if answered else "UNAVAILABLE"}}}


def _na_item(sev, title, source, **ev):
    return {"severity": sev, "title": title, "why": "w", "where": "/v3/health", "source": source, "since": ISO,
            "evidence": ev or None}


def _inbox(items=(), **counts):
    return {"total_count": len(items), "items": list(items), **counts}


def _receipt(findings, verdict="GAPS", ok_at=None, status="ok"):
    return {H.COVERAGE_LANE: {"lane_id": H.COVERAGE_LANE, "status": status, "ok_at": ok_at or ISO,
                              "summary": {"as_of": ok_at or ISO, "coverage_verdict": verdict, "findings": findings}}}


def _uncovered(acct, sym):
    return {"code": "UNCOVERED", "key": f"uncovered:{acct}:{sym}", "detail": f"{acct} {sym}: held 10, no WORKING stop",
            "alert": True}


NO_RECEIPT = {H.COVERAGE_LANE: {"status": "NO_RECEIPT"}}


def build(**payloads):
    probes = {}
    for name, v in payloads.items():
        if isinstance(v, Exception):
            def boom(e=v):
                raise e
            probes[name] = boom
        elif callable(v):
            probes[name] = v
        else:
            probes[name] = (lambda x=v: x)
    return H.build(probes, now=NOW, timeout_s=2.0)


def base(**over):
    p = dict(needs_action=_na(), inbox=_inbox(), risk=_risk(), desk_truth=NO_RECEIPT,
             proposals={"pending": 0}, deploy={"ok": True, "events": [], "recent_14d_count": 0})
    p.update(over)
    return p


def ids(out):
    return [i["id"] for i in out["items"]]


# ── shape + all-clear honesty ─────────────────────────────────────────────────────────────────────────────────


def test_empty_book_answers_and_reports_every_source_with_freshness():
    out = build(**base())
    assert out["schema"] == "HomeDoNow@v1" and out["authority"] == "READ_ONLY_ADVISORY"
    assert out["items"] == [] and out["all_sources_answered"] is True and out["status"] == "OK"
    assert set(out["sources"]) == {"needs_action", "inbox", "risk", "desk_truth", "proposals", "deploy"}
    assert out["sources"]["needs_action"]["as_of_basis"] == "payload.as_of"
    assert out["sources"]["risk"]["as_of_basis"] == "risk_snapshot.computed_at"
    assert out["sources"]["inbox"]["as_of_basis"] == "read_at"  # the inbox has no clock of its own; it says so
    assert out["sources"]["desk_truth"]["status"] == "NO_RECEIPT"
    for s in out["sources"].values():
        assert {"status", "as_of_basis", "stale", "ms"} <= set(s)


@pytest.mark.parametrize("bad", ["needs_action", "inbox", "risk", "proposals", "deploy", "desk_truth"])
def test_a_source_that_raises_is_an_item_never_an_omission(bad):
    out = build(**base(**{bad: RuntimeError("db down")}))
    assert out["all_sources_answered"] is False and out["status"] == "PARTIAL"
    assert out["sources"][bad]["status"] == "UNAVAILABLE" and "db down" in out["sources"][bad]["error"]
    it = next(i for i in out["items"] if i["id"] == f"source:{bad}")
    assert it["category"] == "fix" and it["severity"] == "P2"


def test_malformed_payload_is_unavailable():
    out = build(**base(risk={"positions": "nope"}, proposals={"pending": None}))
    assert out["sources"]["risk"]["status"] == "UNAVAILABLE"
    assert out["sources"]["proposals"]["status"] == "UNAVAILABLE"
    assert out["numbers"]["status"] == "UNAVAILABLE"  # no invented zeros for the three numbers


def test_timeout_is_unavailable():
    out = H.build({"inbox": lambda: time.sleep(1.5) or _inbox()}, now=NOW, timeout_s=0.2)
    assert out["sources"]["inbox"]["status"] == "UNAVAILABLE" and "timed out" in out["sources"]["inbox"]["error"]


def test_needs_action_partial_makes_the_queue_partial():
    out = build(**base(needs_action=_na(answered=False)))
    assert out["sources"]["needs_action"]["status"] == "PARTIAL" and out["all_sources_answered"] is False
    assert out["sources"]["needs_action"]["unavailable"] == ["health"]


def test_old_source_is_stale():
    out = build(**base(needs_action=_na(as_of=(NOW - timedelta(minutes=20)).isoformat()),
                       risk=_risk(computed_at=(NOW - timedelta(hours=1)).isoformat())))
    assert out["sources"]["needs_action"]["stale"] is True and out["sources"]["needs_action"]["age_s"] == 1200
    assert out["sources"]["risk"]["stale"] is True and out["any_source_stale"] is True
    assert out["numbers"]["stale"] is True


# ── protect: stops, dedupe, coverage truth ─────────────────────────────────────────────────────────────────────


def test_one_symbol_from_three_sources_is_one_item():
    out = build(**base(
        risk=_risk(_pos("SPCX", 116_000)),
        inbox=_inbox([{"type": "stop", "symbol": "SPCX", "priority": "P0", "detail": "STOP_TRIGGERED SPCX",
                       "at": ISO}], stops=1),
        needs_action=_na(_na_item("P2", "UNCOVERED: x SPCX", "desk_truth", key="uncovered:schwab_rollover_ira:SPCX")),
    ))
    spcx = [i for i in out["items"] if i["id"] == "stop:SPCX"]
    assert len(spcx) == 1
    it = spcx[0]
    assert it["severity"] == "P0" and it["category"] == "protect"  # most severe wins
    assert set(it["sources"]) == {"risk", "inbox", "needs_action:desk_truth"} and it["merged"] == 3
    assert it["money_at_risk_usd"] == 116_000 and it["money_basis"] == "market value with no stop"
    assert out["rolled_up"]["raw_items"] > out["rolled_up"]["after_dedupe"]


def test_no_stop_fallback_is_labelled_not_measured_when_no_receipt():
    out = build(**base(risk=_risk(_pos("SPCX", 116_000), _pos("V", 20_000), _pos("XLB", 25_000, stop=50.39, dist=5))))
    it = next(i for i in out["items"] if i["id"] == "stop:SPCX")
    assert "no stop on record" in it["why"] and "not measured" in it["why"]
    roll = next(i for i in out["items"] if i["id"] == "stops:unprotected")
    assert roll["title"] == "2 positions with no stop" and roll["money_at_risk_usd"] == 136_000
    n = out["numbers"]
    assert n["unprotected_positions"] == 2 and n["unprotected_source"] == "risk"
    # 2026-10-22 operator "approve all" item G: Home is positions_store reader batch #3; with no held probe wired the
    # source is still holdings.json and says why (tests/test_positions_reader_batch3_home_20261022.py).
    assert n["positions_source"].startswith("holdings.json via data_broker.risk_snapshot")
    assert n["heat_pct"] == 0.1 and n["heat_limit_pct"] == 5.0


def test_measured_coverage_is_the_truth_for_no_stop_items():
    # V has no stop on record but the broker has a working stop (not UNCOVERED); SPCX has a planned stop on record
    # but no WORKING stop at the broker. Measured coverage wins both ways.
    out = build(**base(
        risk=_risk(_pos("SPCX", 116_000, stop=90.0, dist=10), _pos("V", 20_000)),
        desk_truth=_receipt([_uncovered("schwab_rollover_ira", "SPCX")]),
    ))
    assert "stop:V" not in ids(out)
    it = next(i for i in out["items"] if i["id"] == "stop:SPCX")
    assert it["sources"] == ["desk_truth"] and "no WORKING stop at the broker" in it["why"]
    assert out["numbers"]["unprotected_positions"] == 1 and out["numbers"]["unprotected_source"] == "desk_truth"
    assert out["sources"]["desk_truth"]["coverage"]["measured"] is True


@pytest.mark.parametrize("receipt", [
    _receipt([], verdict="NOT_MEASURED"),
    _receipt([], ok_at=(NOW - timedelta(hours=30)).isoformat()),
    _receipt([], status="failed"),
])
def test_unmeasured_coverage_never_counts_as_covered(receipt):
    out = build(**base(risk=_risk(_pos("V", 20_000)), desk_truth=receipt))
    assert "stop:V" in ids(out) and out["numbers"]["unprotected_source"] == "risk"


def test_triggered_and_near_stop():
    out = build(**base(risk=_risk(_pos("NEM", 30_000, stop=100, dist=-1, triggered=True),
                                  _pos("XLB", 25_000, stop=50.39, dist=1.6, max_loss=420),
                                  _pos("PAPER", 9_000, excluded=True))))
    nem = next(i for i in out["items"] if i["id"] == "stop:NEM")
    assert nem["severity"] == "P0" and "below its stop" in nem["title"]
    xlb = next(i for i in out["items"] if i["id"] == "stop:XLB")
    assert xlb["severity"] == "P2" and xlb["title"] == "XLB stop 1.6% away" and xlb["money_at_risk_usd"] == 420
    assert not any("PAPER" in i["id"] for i in out["items"])  # paper positions are risk-excluded


def test_small_unprotected_positions_only_in_the_rollup():
    out = build(**base(risk=_risk(_pos("DUST", 500))))
    assert "stop:DUST" not in ids(out) and "stops:unprotected" in ids(out)


# ── decide / fix mapping, rollups, floors ──────────────────────────────────────────────────────────────────────


def test_needs_action_mapping_and_rollup():
    out = build(**base(needs_action=_na(
        _na_item("P1", "Kill switch is on", "health"),
        _na_item("P2", "Approval package awaiting decision: X", "approvals"),
        _na_item("P2", "ledger:finnhub dead", "data_sources"),
        _na_item("P2", "ledger:polygon error", "data_sources"),
        _na_item("P1", "systemd unit x.service is failed", "systemd"),
    )))
    by = {i["id"]: i for i in out["items"]}
    assert by["na:health:Kill switch is on"]["category"] == "protect"
    assert by["na:approvals:Approval package awaiting decision: X"]["category"] == "decide"
    assert by["na:data_sources:P2"]["title"] == "2 data sources down or erroring"
    assert by["na:systemd:systemd unit x.service is failed"]["category"] == "fix"
    assert by["na:systemd:systemd unit x.service is failed"]["action"]["label"] == "Open Jobs"


def test_inbox_rollups_say_when_a_count_is_a_floor():
    rows = [{"type": "cio_review", "symbol": f"S{i}", "priority": "P1", "at": ISO} for i in range(40)]
    rows += [{"type": "siem", "priority": "P0", "detail": "risk — kill", "at": ISO}]
    out = build(**base(inbox=_inbox(rows, cio_review=40, siem=1)))
    by = {i["id"]: i for i in out["items"]}
    assert by["inbox:cio_review"]["title"].startswith("40+ CIO decisions")
    assert by["inbox:siem"]["severity"] == "P0" and by["inbox:siem"]["category"] == "fix"


def test_proposals_count_owns_the_title_and_merges_inbox_rows():
    out = build(**base(
        proposals={"pending": 43, "oldest_at": (NOW - timedelta(days=2)).isoformat(), "symbols": ["GDDY", "NOW"]},
        inbox=_inbox([{"type": "proposal", "symbol": "GDDY", "priority": "P0", "at": ISO}], proposals=1),
    ))
    it = next(i for i in out["items"] if i["id"] == "proposals:pending")
    assert it["title"] == "43 paper proposals waiting" and set(it["sources"]) == {"proposals", "inbox"}
    assert "Oldest 2 d" in it["why"]


def test_deploy_item():
    out = build(**base(deploy={"ok": True, "recent_14d_count": 3,
                               "events": [{"symbol": "NFLX", "proceeds_usd": 28067, "sold_at": "2026-10-20"}]}))
    it = next(i for i in out["items"] if i["id"] == "deploy:open")
    assert it["title"] == "Redeploy $28,067 from the NFLX sale" and it["category"] == "decide"


def test_sort_is_money_first_then_severity_then_category():
    out = build(**base(
        risk=_risk(_pos("SPCX", 116_000), _pos("XLB", 25_000, stop=50, dist=1.6, max_loss=420)),
        needs_action=_na(_na_item("P0", "a P0 fix with no money", "systemd"), _na_item("P3", "zz", "queue")),
        proposals={"pending": 2, "symbols": ["A"]},
    ))
    order = ids(out)
    assert order[0] == "stops:unprotected" and order[1] == "stop:SPCX" and order[2] == "stop:XLB"
    assert order.index("na:systemd:a P0 fix with no money") < order.index("proposals:pending")
    assert order[-1] == "na:queue:zz"
    assert out["counts"]["all"] == len(out["items"]) == sum(out["counts"][c] for c in H.CATEGORIES)


# ── probes and wiring ──────────────────────────────────────────────────────────────────────────────────────────


def test_probe_pending_proposals_reads_only_and_none_is_unavailable():
    seen = []

    def q(sql, params=None, fetch="all"):
        seen.append(sql)
        return {"n": 5, "oldest": NOW} if fetch == "one" else [{"symbol": "NEM"}]

    out = H.probe_pending_proposals(q)
    assert out == {"pending": 5, "oldest_at": ISO, "symbols": ["NEM"]}
    assert all(s.lstrip().upper().startswith("SELECT") for s in seen)
    with pytest.raises(H.SourceUnavailable):
        H.probe_pending_proposals(lambda *a, **k: None)


def test_route_and_catalog_registration():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    assert '"/api/v2/home/do-now": lambda: _home_do_now(),' in src
    body = src[src.index("def _home_do_now("):src.index("def _queue_pending(")]
    assert "_HOME_DO_NOW_CACHE" in body and "max_age_s=120" in body
    assert not re.search(r"(?<![\w])risk\(\)", body) and "open_trades_intelligence" not in body  # no broker-stop overlay, no broker read
    from lib.data_broker.catalog import PROJECTIONS
    row = next(p for p in PROJECTIONS if p["id"] == "home_do_now")
    assert row["http"] == ["/api/v2/home/do-now"] and row["read_only"] is True and row["provider_calls"] == 0


def test_projection_cannot_reach_a_broker_order_or_writer():
    src = (ROOT / "scripts" / "lib" / "data_broker" / "home_do_now.py").read_text()
    for banned in ("place_order", "brokers", "open_trades_intelligence", "trading_lock", "send_telegram",
                   "INSERT ", "UPDATE ", "DELETE ", "write_text", "FROM positions_current", "JOIN positions_current"):
        assert banned not in src.split('"""', 2)[2], banned
