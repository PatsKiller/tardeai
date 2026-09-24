"""Missing CIO stance → classification follow-up (OPERATOR 2026-09-23).

The CIO engine only covers symbols with an ACTIVE classification plus a rule
evaluation. The drain gives a held symbol both, deterministically (no LLM), so
the next engine run writes a real stance. No DB: every seam is injected.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import drain_cio_stance_classification as drain  # noqa: E402
from lib import cio_stance_review_request as rr  # noqa: E402

NOW = datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)
REGISTRY = {"sector_rotation", "dividend_growth_compounder", "core_growth_compounder"}


def _req(sym, *, minutes_ago=5, classify=True):
    return {
        "symbol": sym,
        "as_of": (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "classification_requested": classify,
        "research_id": f"res_{sym.lower()}",
    }


class Fake:
    """Records writes; returns a canned per-symbol state and match list."""

    def __init__(self, states, matches):
        self.states, self.matches = states, matches
        self.writes, self.rules = [], []

    def state(self, _conn, sym):
        return {"registry": REGISTRY, "scan": {"symbol": sym}, **self.states.get(sym, {})}

    def match(self, scan):
        return self.matches.get(scan["symbol"], [])

    def write(self, _conn, sym, match, prior, request):
        self.writes.append((sym, match["strategy_id"], prior, request["as_of"]))

    def rules_fn(self, sym, *, apply, proposed=None):
        self.rules.append((sym, apply, (proposed or {}).get("strategy_type")))
        return {"strategy_type": (proposed or {}).get("strategy_type"), "baseline_action": "RESEARCH_MORE"}

    def seams(self):
        return {"state_fn": self.state, "match_fn": self.match, "write_fn": self.write, "rules_fn": self.rules_fn}


def _match(st, conf=0.7):
    return [{"strategy_id": st, "confidence": conf, "match_source": "deterministic", "match_reasons": ["x"]}]


def test_inactive_symbol_is_classified_and_rule_evaluated_on_apply(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_STANCE_CLASSIFY_RECEIPTS", str(tmp_path / "r.jsonl"))
    f = Fake(
        {"STLD": {"prior_strategy_type": "core_growth_compounder", "active": False}},
        {"STLD": _match("sector_rotation")},
    )
    rep = drain.run(apply=True, now=NOW, ledger_rows=[_req("STLD")], conn=object(), **f.seams())
    assert rep["counts"] == {"applied": 1}
    assert f.writes == [("STLD", "sector_rotation", "core_growth_compounder", _req("STLD")["as_of"])]
    assert f.rules == [("STLD", True, "sector_rotation")]
    row = json.loads((tmp_path / "r.jsonl").read_text().splitlines()[0])
    assert row["status"] == "applied" and row["mbi_behavior"] == 0


def test_dry_run_writes_nothing_but_shows_the_rule_evaluation(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_STANCE_CLASSIFY_RECEIPTS", str(tmp_path / "r.jsonl"))
    f = Fake({"HOOD": {"prior_strategy_type": "dividend_growth_compounder"}}, {"HOOD": _match("sector_rotation")})
    rep = drain.run(apply=False, now=NOW, ledger_rows=[_req("HOOD")], conn=object(), **f.seams())
    assert rep["counts"] == {"would_apply": 1}
    assert f.writes == []
    assert f.rules == [("HOOD", False, "sector_rotation")]
    assert rep["results"][0]["rule_evaluation"]["baseline_action"] == "RESEARCH_MORE"
    assert not (tmp_path / "r.jsonl").exists()


def test_no_match_below_floor_is_terminal_and_not_written(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_STANCE_CLASSIFY_RECEIPTS", str(tmp_path / "r.jsonl"))
    f = Fake({}, {"SLB": _match("sector_rotation", conf=0.4)})
    rep = drain.run(apply=True, now=NOW, ledger_rows=[_req("SLB")], conn=object(), **f.seams())
    assert rep["counts"] == {"no_deterministic_match": 1}
    assert f.writes == [] and f.rules == []
    again = drain.run(apply=True, now=NOW, ledger_rows=[_req("SLB")], conn=object(), **f.seams())
    assert again["pending"] == 0  # terminal for this request


def test_strategy_type_outside_registry_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_STANCE_CLASSIFY_RECEIPTS", str(tmp_path / "r.jsonl"))
    f = Fake({}, {"AES": _match("not_a_strategy")})
    rep = drain.run(apply=True, now=NOW, ledger_rows=[_req("AES")], conn=object(), **f.seams())
    assert rep["counts"] == {"invalid_strategy_type": 1} and f.writes == []


def test_already_active_only_fills_a_missing_rule_evaluation(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_STANCE_CLASSIFY_RECEIPTS", str(tmp_path / "r.jsonl"))
    f = Fake({"PLTR": {"active": True, "prior_strategy_type": "sector_rotation", "has_rule_evaluation": False}}, {})
    rep = drain.run(apply=True, now=NOW, ledger_rows=[_req("PLTR")], conn=object(), **f.seams())
    assert rep["counts"] == {"already_classified": 1}
    assert f.writes == [] and f.rules == [("PLTR", True, None)]


def test_missing_classifier_inputs_is_an_error_not_a_verdict(monkeypatch, tmp_path):
    """No enrichment cache must NOT permanently mark the request 'no match'."""
    monkeypatch.setenv("CIO_STANCE_CLASSIFY_RECEIPTS", str(tmp_path / "r.jsonl"))
    f = Fake({}, {})

    def boom(_scan):
        raise RuntimeError("classifier_inputs_unavailable")

    seams = {**f.seams(), "match_fn": boom}

    class Conn:
        def rollback(self):
            pass

    rep = drain.run(apply=True, now=NOW, ledger_rows=[_req("WDAY")], conn=Conn(), **seams)
    assert list(rep["counts"]) == ["error:classifier_inputs_unavailable"]
    retry = drain.run(apply=True, now=NOW, ledger_rows=[_req("WDAY")], conn=Conn(), **seams)
    assert retry["pending"] == 1  # still pending — retried next run


def test_pending_takes_newest_request_per_symbol_and_honours_lookback():
    rows = [
        _req("STLD", minutes_ago=90),
        _req("STLD", minutes_ago=5),
        _req("OLD", minutes_ago=60 * 24 * 30),
        _req("NOPE", classify=False),
    ]
    todo = drain.pending_requests(rows, [], now=NOW, lookback_days=7)
    assert [(r["symbol"], r["as_of"]) for r in todo] == [("STLD", _req("STLD")["as_of"])]


def test_review_ledger_row_carries_classification_requested(monkeypatch, tmp_path):
    ledger = tmp_path / "req.jsonl"
    monkeypatch.setenv("CIO_STANCE_REVIEW_REQUESTS", str(ledger))
    out = rr.request_cio_review(
        "STLD",
        source="send_telegram_proposal_alert",
        now=NOW,
        emitter=lambda s, src: {"ok": True, "research_id": "res_x"},
    )
    assert out["classification_requested"] is True
    row = json.loads(ledger.read_text().splitlines()[0])
    assert row["classification_requested"] is True
    again = rr.request_cio_review(
        "STLD",
        source="send_telegram_proposal_alert",
        now=NOW,
        emitter=lambda s, src: {"ok": True, "research_id": "res_y"},
    )
    assert again["review_status"] == "deduped" and again["classification_requested"] is True


def test_classification_follow_up_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_STANCE_REVIEW_REQUESTS", str(tmp_path / "req.jsonl"))
    monkeypatch.setenv("CIO_STANCE_CLASSIFY_DISABLE", "1")
    out = rr.request_cio_review(
        "AES", source="screener_go_alerts", now=NOW, emitter=lambda s, src: {"ok": True, "research_id": "res_z"}
    )
    assert out["classification_requested"] is False


def test_receipts_path_is_off_under_pytest_by_default(monkeypatch):
    monkeypatch.delenv("CIO_STANCE_CLASSIFY_RECEIPTS", raising=False)
    assert drain.receipts_path() is None
