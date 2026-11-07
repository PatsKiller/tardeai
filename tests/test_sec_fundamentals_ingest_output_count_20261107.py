"""sec-fundamentals-ingest: the receipt reports what the run WROTE, not what it looked at (LQ round-2).

Live evidence (2026-11-07 08:25 ET), from ``data/runtime/sec-fundamentals-ingest_last.json``: the lane
graded GOOD — "produced 13 by summary.symbols" — for a run whose own summary was

    {"symbols": 13, "failed": 0, "statuses": {"OK": 11, "NO_FACTS": 2},
     "facts_inserted": 0, "facts_updated": 0, "filing_events_new": 0, "filing_documents_new": 0}

i.e. it wrote nothing. That run was not the lane's own nightly cron either: the 21:30 cron's last real run
(2026-11-06 21:30 ET) wrote 94 facts, 7 filing events and 2 documents across 120 symbols, while
``symbol_news_curation_monitor.fundamentals_sla`` re-enters ``sec_fundamentals_ingest.main()`` in process
for its 13 SLA breaches and overwrote the lane receipt with the 13-symbol, 0-row sub-call.

``lib/run_quality.item_count`` walks its COUNT_KEYS in order, and ``symbols`` sits before any write
counter, so a population count won as a produced count and the page said the lane produced 13 rows when
the database gained none. The receipt now carries ``produced_count`` = rows written, ``attempted_count`` =
symbols examined, ``skipped_reasons``, and an ``empty_reason`` that distinguishes a genuinely idle run
(SEC returned facts the store already holds -> ``no_new_input``, a reviewed idle token) from a run pointed
at symbols that can never produce rows (a sentence naming the counts, which grades EMPTY with the cause).

Synthetic fixtures only: the repository is public. No database, no network.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts import sec_fundamentals_ingest as S  # noqa: E402
from lib import lane_last_receipt as LR  # noqa: E402
from lib import run_quality as Q  # noqa: E402

LANE = "sec-fundamentals-ingest"
RECEIPT = f"data/runtime/{LANE}_last.json"
SCRIPT = ROOT / "scripts" / "sec_fundamentals_ingest.py"
IDLE_REASONS = ROOT / "config" / "run_quality_idle_reasons.json"


# ── the summary the run returns ───────────────────────────────────────────────────────────────────


def _ok(symbol: str, *, inserted=0, updated=0, unchanged=0, events=0, docs=0) -> dict:
    return {"symbol": symbol, "status": "OK", "rows": 10, "inserted": inserted, "updated": updated,
            "unchanged": unchanged, "filing_events_new": events, "filing_documents_new": docs}


def test_a_productive_run_counts_the_rows_it_wrote():
    s = S._run_summary([_ok("AAA", inserted=90, unchanged=100), _ok("BBB", inserted=4, updated=3, events=7, docs=2)], ["AAA", "BBB"])
    assert s["produced_count"] == 106
    assert s["attempted_count"] == 2
    assert s["empty_reason"] is None
    assert s["facts_inserted"] == 94 and s["filing_events_new"] == 7 and s["filing_documents_new"] == 2


def test_a_sub_call_that_wrote_nothing_no_longer_claims_the_population_as_output():
    """The live 08:25 case: 13 symbols, every write counter 0, 11 OK symbols unchanged."""
    report = [_ok(f"S{i}", unchanged=101) for i in range(11)]
    report += [{"symbol": "AGBK", "status": "NO_FACTS", "rows": 0}, {"symbol": "AGI", "status": "NO_FACTS", "rows": 0}]
    s = S._run_summary(report, [f"S{i}" for i in range(11)] + ["AGBK", "AGI"])
    assert s["produced_count"] == 0
    assert s["symbols"] == 13 and s["attempted_count"] == 13
    assert s["empty_reason"] == "no_new_input"
    assert s["skipped_reasons"] == {"unchanged": 1111, "no_facts": 2}


def test_a_run_whose_symbols_have_no_facts_is_not_called_idle():
    """No rows were written AND nothing was already stored: the lane is pointed at symbols that cannot
    produce rows. A reviewed idle token would hide that; a sentence names it."""
    s = S._run_summary([{"symbol": "AGG", "status": "NO_CIK"}, {"symbol": "AGI", "status": "NO_FACTS"}], ["AGG", "AGI"])
    assert s["produced_count"] == 0
    reason = s["empty_reason"]
    assert reason and reason not in json.loads(IDLE_REASONS.read_text())["reasons"], reason
    assert "2 symbol(s) examined and nothing was written" in reason
    assert "no SEC CIK" in reason and "no company facts" in reason


def test_a_failed_symbol_does_not_get_an_idle_reason():
    s = S._run_summary([{"symbol": "AAA", "status": "ERROR", "error": "Boom: x"}], ["AAA"])
    assert s["failed"] == 1
    assert s["empty_reason"] is None


def test_a_run_with_nothing_to_examine_says_so_without_inventing_a_token():
    s = S._run_summary([], [])
    assert s["produced_count"] == 0 and s["empty_reason"]
    assert s["empty_reason"] not in json.loads(IDLE_REASONS.read_text())["reasons"]


# ── the receipt main() writes ─────────────────────────────────────────────────────────────────────


def _receipt(summary: dict) -> dict:
    """The exact call main() makes: the #1772 ``output=`` spelling, v2 fields additive on a v1 document."""
    return LR.build_receipt(
        LANE, ok=True, exit_code=0, started_at=START.isoformat(), finished_at=OK_AT.isoformat(),
        script="sec_fundamentals_ingest.py", summary=summary,
        output={"produced_count": summary["produced_count"], "attempted_count": summary["attempted_count"],
                "skipped_reasons": summary["skipped_reasons"], "empty_reason": summary["empty_reason"]})


NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = NOW - timedelta(minutes=30)
OK_AT = START + timedelta(seconds=26)


def _grade(receipt: dict) -> dict:
    run = {"mode": "live", "result": "succeeded", "started_at": START.isoformat(), "finished_at": OK_AT.isoformat(),
           "duration_s": 26.2, "run_id": "r1", "exit_code": 0, "reason": None, "source": "lane receipt"}
    row = {"lane_id": LANE, "state": "ACTIVE", "status": "ok", "runs": [run], "last_run": run}
    lane = {"lane_id": LANE, "state": "ACTIVE", "scheduler": {"kind": "cron"},
            "output_signal": {"kind": "json_key", "path": RECEIPT, "key": "ok_at"}}
    ev = {"receipt": receipt, "receipt_path": str(ROOT / RECEIPT),
          "output_at": datetime.fromisoformat(receipt["ok_at"]), "ledger": [], "history": [], "contract": None,
          "freshness": [], "freshness_known": True, "plausibility": [], "plausibility_known": True}
    return Q.grade(row, lane, ev, now=NOW)


def test_the_live_symptom_is_gone_a_zero_row_run_grades_idle_not_produced_13():
    report = [_ok(f"S{i}", unchanged=101) for i in range(11)] + [{"symbol": "AGBK", "status": "NO_FACTS", "rows": 0},
                                                                 {"symbol": "AGI", "status": "NO_FACTS", "rows": 0}]
    g = _grade(_receipt(S._run_summary(report, [f"S{i}" for i in range(11)] + ["AGBK", "AGI"])))
    assert (g["grade"], g["sub"]) == ("GOOD", "idle"), g["reasons"]
    assert "produced 13" not in g["reasons"][0]
    assert "no new input" in g["reasons"][0]


def test_a_productive_run_still_grades_on_the_rows_it_wrote():
    g = _grade(_receipt(S._run_summary([_ok("AAA", inserted=94, events=7, docs=2)], ["AAA"])))
    assert (g["grade"], g["sub"]) == ("GOOD", None), g["reasons"]
    assert "produced 103 by produced_count" in g["reasons"][0]


def test_a_run_with_nothing_to_ingest_grades_empty_with_the_cause_named():
    g = _grade(_receipt(S._run_summary([{"symbol": "AGG", "status": "NO_CIK"}], ["AGG"])))
    assert (g["grade"], g["sub"]) == ("EMPTY", "unexpected"), g["reasons"]
    assert "no SEC CIK" in g["reasons"][0]


def test_main_hands_the_counters_to_the_receipt():
    """Source-level: a future edit must not drop the output fields from the lane receipt again."""
    src = SCRIPT.read_text()
    call = src[src.index('write_lane_receipt("sec-fundamentals-ingest"'):]
    call = call[:call.index("\n    return rc")]
    assert "output={" in call, call
    for kw in ('"produced_count": summary["produced_count"]', '"attempted_count": summary["attempted_count"]',
               '"skipped_reasons": summary["skipped_reasons"]', '"empty_reason": summary["empty_reason"]'):
        assert kw in call, kw


def test_the_lane_reads_the_receipt_this_script_writes():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    lanes = reg["lanes"] if isinstance(reg, dict) and "lanes" in reg else reg
    lane = lanes[LANE] if isinstance(lanes, dict) else next(l for l in lanes if l.get("lane_id") == LANE)
    assert lane["output_signal"] == {"kind": "json_key", "path": RECEIPT, "key": "ok_at"}, lane["output_signal"]
    assert f'write_lane_receipt("{LANE}"' in SCRIPT.read_text()
