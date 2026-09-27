"""Symbol-news curation, SLA and priority acquisition (operator 2026-09-27). Hermetic."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import symbol_news_curation as snc  # noqa: E402
from scripts.lib import symbol_thesis_priority as stp  # noqa: E402

NOW = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
S = snc.settings({"max_age_days": 30, "max_per_symbol": 3, "blocked_sources": ["spamwire"]})


def _row(i, title, src="yahoo_rss", days=1):
    return {"id": i, "title": title, "source": src, "created_at": NOW - timedelta(days=days)}


def test_name_tokens_from_profile_description():
    assert snc.name_tokens("Dell Technologies Inc — Computer Hardware.") == ["dell"]
    assert snc.name_tokens("The Boeing Company - Aerospace") == ["boeing"]
    assert snc.name_tokens(None) == []


def test_select_needs_headline_to_name_the_company_and_prefers_primary():
    rows = [_row(1, "AI Trade Picks Up Again as Investors Pile Back Into Stocks"),
            _row(2, "Dell Rises 7% as Morgan Stanley Lifts Odds on $756 Bull Case"),
            _row(3, "DELL 10-Q quarterly report", src="sec_edgar_premarket", days=2),
            _row(4, "Dell vs. HPE: Which AI Server Stock Is the Better Buy?", days=40),
            _row(5, "Dell insider sells", src="spamwire"),
            _row(6, "Topic roundup mentions Dell", src="topic_ai")]
    picked = snc.select(rows, "DELL", ["dell"], S, now=NOW)
    assert [r["id"] for r in picked] == [3, 2]
    assert picked[0]["_reason"] == "symbol_gap_curation: primary filing"
    assert "headline names DELL" in picked[1]["_reason"]


def test_ticker_match_is_a_whole_word():
    assert snc.names_the_company("V beats earnings", "V", [])
    assert not snc.names_the_company("Various stocks rise", "V", [])


class _Cur:
    def __init__(self, rows):
        self.rows, self.q, self.updates = rows, None, []

    def execute(self, sql, params=None):
        self.q = sql
        if "UPDATE news_articles" in sql:
            self.updates.append(params)
            self.rowcount = 1

    def fetchone(self):
        if "symbol_profiles" in self.q:
            return {"description_1s": "Dell Technologies Inc — Computer Hardware."}
        return {"n": 35815, "syms": 2688}

    def fetchall(self):
        return self.rows


def test_curate_symbol_dry_run_approves_nothing_apply_writes_with_reason(monkeypatch):
    rows = [_row(2, "Dell Rises 7% as Morgan Stanley Lifts Odds"), _row(1, "Market wrap")]
    cur = _Cur(rows)
    dry = snc.curate_symbol(cur, "dell", S, apply=False, now=NOW)
    assert dry["selected"] == 1 and dry["approved"] == 0 and cur.updates == []
    import lib.writers.news_articles_writer as w
    calls = []
    monkeypatch.setattr(w, "set_rag_status", lambda c, i, st, why: calls.append((i, st, why)) or 1)
    done = snc.curate_symbol(_Cur(rows), "DELL", S, apply=True, now=NOW)
    assert done["approved"] == 1 and calls[0][0] == 2 and calls[0][1] == "approved"
    assert calls[0][2].startswith("symbol_gap_curation:")


def test_sla_breach_only_when_no_approved_evidence_and_pending_is_old():
    rows = [{"symbol": "DELL", "n": 57, "oldest": NOW - timedelta(hours=60), "approved_recent": 0},
            {"symbol": "V", "n": 12, "oldest": NOW - timedelta(hours=80), "approved_recent": 3},
            {"symbol": "HOOD", "n": 2, "oldest": NOW - timedelta(hours=5), "approved_recent": 0}]
    rep = snc.sla_report(_Cur(rows), ["DELL", "V", "HOOD"], S, now=NOW)
    assert [b["symbol"] for b in rep["breaches"]] == ["DELL"]
    assert rep["platform_pending_30d"] == 35815


def test_priority_request_opens_and_closes_on_publish(tmp_path):
    (tmp_path / "data/cio").mkdir(parents=True)
    stp.request("dell", reason="options CIO MORE_RESEARCH", source="test", root=tmp_path, now=NOW)
    assert stp.open_requests(tmp_path, now=NOW) == ["DELL"]
    led = tmp_path / "data/cio/symbol_thesis_acquisition_ledger.jsonl"
    led.write_text(json.dumps({"symbol": "DELL", "status": "BLOCKED", "as_of": (NOW + timedelta(hours=1)).isoformat()}) + "\n")
    assert stp.open_requests(tmp_path, now=NOW) == ["DELL"]
    with led.open("a") as fh:
        fh.write(json.dumps({"symbol": "DELL", "status": "PUBLISHED", "as_of": (NOW + timedelta(hours=2)).isoformat()}) + "\n")
    assert stp.open_requests(tmp_path, now=NOW) == []
    assert stp.open_requests(tmp_path, now=NOW + timedelta(days=8)) == []  # aged out
