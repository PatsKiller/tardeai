"""Deep overnight LLM queue drain: operator windows, lane chain, triage, and a dry run that writes nothing.

Operator 2026-10-31: weekends + market holidays drain all day; trading days 21:00-04:00 ET; budget ceilings stay;
DeepSeek only outside its billing peak. Live finding the same day: run_deep_overnight_llm_queue.py --dry-run ran
recover_stale_running (an UPDATE) and committed before reaching the dry-run branch. Hermetic: no DB, no network.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import llm_queue_drain_policy as dp  # noqa: E402

POLICY = dp.load_policy()
TRADING = lambda now: now.astimezone(dp.ET).weekday() < 5  # noqa: E731 - weekday calendar for the tests


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "now,expected,reason",
    [
        (_utc(2026, 10, 31, 18), True, "non_trading_day"),  # Sat 14:00 ET
        (_utc(2026, 11, 2, 20), False, "trading_day_hours"),  # Mon 15:00 EST
        (_utc(2026, 11, 3, 3), True, "night_21-04_et"),  # Mon 22:00 EST
        (_utc(2026, 11, 3, 8, 30), True, "night_21-04_et"),  # Tue 03:30 EST
        (_utc(2026, 11, 3, 9), False, "trading_day_hours"),  # Tue 04:00 EST - window closed
        (_utc(2026, 11, 3, 1, 59), False, "trading_day_hours"),  # Mon 20:59 EST
        (_utc(2026, 11, 3, 2, 0), True, "night_21-04_et"),  # Mon 21:00 EST - window opens (inclusive)
        (_utc(2026, 11, 3, 8, 59), True, "night_21-04_et"),  # Tue 03:59 EST - last open minute
    ],
)
def test_window_state(now, expected, reason):
    ws = dp.window_state(now, POLICY, is_trading_day=TRADING)
    assert ws == {"unrestricted": expected, "reason": reason}


def test_market_holiday_is_unrestricted_all_day():
    ws = dp.window_state(_utc(2026, 11, 26, 17), POLICY, is_trading_day=lambda n: False)  # Thanksgiving noon
    assert ws["unrestricted"] is True and ws["reason"] == "non_trading_day"


def test_chain_drops_deepseek_inside_its_peak_only():
    peak = dp.provider_chain(_utc(2026, 11, 2, 2), POLICY)  # Mon 02:00 UTC: DeepSeek peak
    off = dp.provider_chain(_utc(2026, 11, 2, 12), POLICY)  # Mon 12:00 UTC: off-peak
    weekend = dp.provider_chain(_utc(2026, 10, 31, 2), POLICY)  # Sat: no peak at all
    assert peak == ["anthropic", "grok", "chatgpt"]
    assert off == weekend == ["anthropic", "grok", "chatgpt", "deepseek-flash"]


def test_triage_keeps_only_strategy_classification_on_symbols_still_tracked():
    sql, params = dp.triage_filter_sql(POLICY)
    assert "ticker_snapshot_daily" in sql and params == ["strategy_classification", 14]


import run_deep_overnight_llm_queue as w  # noqa: E402


class _Res:
    text, lane = "ok", "grok"

    def provenance_line(self):
        return "served by grok (substituted)"


def test_call_cloud_routes_through_the_budget_gated_chain(monkeypatch):
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw)
        return _Res()

    text, _rt, model = w.call_cloud("p", POLICY, fallback=fake, now=_utc(2026, 11, 2, 2))
    assert (text, model) == ("ok", "cloud:grok")
    assert seen["lane"] == "anthropic" and seen["extra_lanes"] == ["grok", "chatgpt"]
    assert seen["allow_paid"] is False and seen["process_id"] == "deep_overnight_llm_drain"
    w.call_cloud("p", POLICY, fallback=fake, now=_utc(2026, 11, 2, 12))
    assert seen["allow_paid"] is True and seen["extra_lanes"][-1] == "deepseek-flash"


def test_call_cloud_model_failure_is_a_failed_job_not_a_crash():
    from lib.llm_fallback import AllLanesFailed

    def timeouts(prompt, **kw):
        raise AllLanesFailed([
            {"lane": "anthropic", "ok": False, "error": "RuntimeError: POLICY_NOT_ALLOWED", "skipped_reason": ""},
            {"lane": "grok", "ok": False, "error": "TimeoutError: read timed out", "skipped_reason": ""},
        ])

    assert w.call_cloud("p", POLICY, fallback=timeouts, now=_utc(2026, 10, 31, 18))[0] is None


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("PROCESS_NOT_REGISTERED"),
        RuntimeError("COST_CAP_EXCEEDED: process cap"),
        RuntimeError("CREDIT_EXHAUSTED: durable total cap"),
    ],
)
def test_call_cloud_gate_refusal_raises_refused(error):
    def refuse(prompt, **kw):
        raise error

    with pytest.raises(w.CloudRefused):
        w.call_cloud("p", POLICY, fallback=refuse, now=_utc(2026, 10, 31, 18))


def test_all_lanes_refused_or_unavailable_is_a_refusal():
    from lib.llm_fallback import AllLanesFailed

    exc = AllLanesFailed([
        {"lane": "anthropic", "ok": False, "error": "RuntimeError: POLICY_NOT_ALLOWED", "skipped_reason": ""},
        {"lane": "grok", "ok": False, "error": "unavailable", "skipped_reason": "reported unavailable"},
        {"lane": "chatgpt", "ok": False, "error": "", "skipped_reason": "availability probe error: OSError"},
        {"lane": "chatgpt", "ok": False, "error": "RuntimeError: COST_CAP_EXCEEDED: {...}", "skipped_reason": ""},
    ])
    assert w.classify_cloud_failure(exc)
    assert w.classify_cloud_failure(RuntimeError("read timed out")) is None


def test_job_specific_input_limit_is_not_a_run_stopping_refusal():
    assert w.classify_cloud_failure(RuntimeError("INPUT_LIMIT_EXCEEDED: 40000 > 32000")) is None


class _Cur:
    def __init__(self, log):
        self.log, self.description = (
            log,
            [
                ("id",),
                ("job_type",),
                ("symbol",),
                ("trade_id",),
                ("journal_id",),
                ("priority_tier",),
                ("priority_score",),
                ("reason_codes",),
            ],
        )

    def execute(self, sql, params=None):
        self.log.append(sql.strip().split()[0].upper())

    def fetchall(self):
        return [(1, "strategy_classification", "AAPL", None, None, "P1", 50, ["x"])]


class _Conn:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return _Cur(self.log)

    def commit(self):
        self.log.append("COMMIT")

    def close(self):
        pass


def test_dry_run_writes_nothing(monkeypatch):
    log: list[str] = []
    monkeypatch.setattr(w, "get_db_connection", lambda: _Conn(log))
    monkeypatch.setattr(w, "log", lambda m: None)
    monkeypatch.setattr(sys, "argv", ["x", "--dry-run", "--triaged", "--limit", "5"])
    w.main()
    assert log == ["SELECT"]  # no UPDATE (recover_stale_running), no COMMIT


def _patch_window(monkeypatch, fn):
    """Patch window_state on the module main() imports at call time. Another test in the same session may have
    reloaded lib.*, so the module imported at the top of this file is not necessarily that one."""
    import importlib

    for mod in {id(m): m for m in (dp, importlib.import_module("lib.llm_queue_drain_policy"))}.values():
        monkeypatch.setattr(mod, "window_state", fn)


def test_drain_window_refuses_outside_the_window_before_touching_the_db(monkeypatch):
    monkeypatch.setattr(w, "get_db_connection", lambda: pytest.fail("connected outside the window"))
    monkeypatch.setattr(w, "log", lambda m: None)
    _patch_window(monkeypatch, lambda now=None, policy=None, **k: {"unrestricted": False, "reason": "t"})
    monkeypatch.setattr(sys, "argv", ["x", "--drain-window", "--route", "cloud"])
    w.main()


# ── full main() path against a recording fake DB (reviewer probes 2026-11-01) ──────────────────────────────────

_COLS = ("id", "job_type", "symbol", "trade_id", "journal_id", "account", "priority_tier", "priority_score",
         "reason_codes", "last_qwen_summary", "last_qwen_confidence", "metadata_json", "attempt_count",
         "input_hash", "source_table", "source_id")


def _row(job_id, attempts=2):
    return (job_id, "strategy_classification", "AAPL", None, None, None, "P1", 50, ["x"], None, None, {},
            attempts, "h", None, None)


class _RecCur:
    def __init__(self, log, rows):
        self.log, self.rows, self.last = log, rows, ""
        self.description = [(c,) for c in _COLS]
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))
        self.last = sql

    def fetchall(self):
        return list(self.rows) if "FROM deep_overnight_llm_queue" in self.last and "pending" in self.last else []

    def fetchone(self):
        return (0,)

    def close(self):
        pass


class _RecConn:
    def __init__(self, log, rows):
        self.log, self.rows = log, rows

    def cursor(self):
        return _RecCur(self.log, self.rows)

    def commit(self):
        self.log.append(("COMMIT", None))

    def rollback(self):
        pass

    def close(self):
        pass


def _run(monkeypatch, argv, rows=(), windows=None):
    log: list = []
    monkeypatch.setattr(w, "get_db_connection", lambda: _RecConn(log, list(rows)))
    monkeypatch.setattr(w, "log", lambda m: None)
    monkeypatch.setattr(w, "build_prompt", lambda *a, **k: "p")
    monkeypatch.setattr(w, "_extract_and_register_gaps", lambda *a, **k: None, raising=False)
    if windows is not None:
        seq = iter(windows)
        _patch_window(monkeypatch, lambda now=None, policy=None, **k: {"unrestricted": next(seq), "reason": "t"})
    monkeypatch.setattr(sys, "argv", ["x", *argv])
    w.main()
    return log


def _sqls(log):
    return [s for s, _ in log if s != "COMMIT"]


def test_gate_refusal_does_not_burn_attempts_and_stops_the_run(monkeypatch):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback",
                        lambda prompt, **kw: (_ for _ in ()).throw(RuntimeError("PROCESS_NOT_REGISTERED")))
    log = _run(monkeypatch, ["--route", "cloud", "--drain-window", "--triaged", "--limit", "5"],
               rows=[_row(7), _row(8)], windows=[True, True, True, True])
    sqls = _sqls(log)
    assert not [s for s in sqls if "attempt_count >= 3 THEN 'failed'" in s], "refusal walked the job toward failed"
    undo = [(s, p) for s, p in log if "GREATEST(attempt_count - 1, 0)" in s]
    assert len(undo) == 1 and undo[0][1][1] == 7 and "PROCESS_NOT_REGISTERED" in undo[0][1][0]
    running = [p for s, p in log if "SET status = 'running'" in s]
    assert running == [(7,)], "the run must stop at the first refusal"


def test_model_failure_still_counts_an_attempt(monkeypatch):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback",
                        lambda prompt, **kw: (_ for _ in ()).throw(TimeoutError("read timed out")))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "1"], rows=[_row(9)])
    assert [s for s in _sqls(log) if "attempt_count >= 3 THEN 'failed'" in s]
    assert not [s for s in _sqls(log) if "GREATEST(attempt_count - 1, 0)" in s]


def test_triaged_simple_selection_carries_the_predicate(monkeypatch):
    log = _run(monkeypatch, ["--dry-run", "--triaged", "--limit", "5"])
    sel = [(s, p) for s, p in log if "FROM deep_overnight_llm_queue" in s]
    assert sel and all("ticker_snapshot_daily" in s for s, _ in sel)
    assert sel[0][1][-3:] == ["strategy_classification", 14, 5]


def test_triaged_with_balanced_policy_still_applies_triage(monkeypatch):
    log = _run(monkeypatch, ["--dry-run", "--triaged", "--quota-policy", "balanced",
                             "--job-types", "rag_content_curation,strategy_classification"])
    sel = [(s, p) for s, p in log if "FROM deep_overnight_llm_queue" in s]
    assert sel, "no selection ran"
    assert all("ticker_snapshot_daily" in s for s, _ in sel), "triage predicate missing from balanced selection"
    assert all("strategy_classification" in p and 14 in p for _, p in sel)


def test_untriaged_balanced_selection_is_unchanged(monkeypatch):
    log = _run(monkeypatch, ["--dry-run", "--quota-policy", "balanced", "--job-types", "strategy_classification"])
    assert not [s for s in _sqls(log) if "ticker_snapshot_daily" in s]


def test_window_closing_mid_run_stops_before_the_next_job(monkeypatch):
    log = _run(monkeypatch, ["--route", "cloud", "--drain-window", "--limit", "5"],
               rows=[_row(11), _row(12)], windows=[True, False])
    assert not [s for s in _sqls(log) if "SET status = 'running'" in s], "processed a job after the window closed"


def test_cloud_route_caps_limit_at_per_run_job_limit(monkeypatch):
    cap = int(POLICY["per_run_job_limit"])
    log = _run(monkeypatch, ["--route", "cloud", "--dry-run", "--limit", str(cap * 5)], windows=[True])
    sel = [p for s, p in log if "FROM deep_overnight_llm_queue" in s]
    assert sel and sel[0][-1] == cap


def test_drain_process_is_registered_with_placeholder_caps_and_no_credit_admission():
    import json

    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    rows = [p for p in reg["processes"] if p.get("id") == POLICY["process_id"]]
    assert len(rows) == 1
    proc = rows[0]
    assert proc["anthropic_first"] is True and proc["fallback_allowed"] is True
    assert proc["daily_cost_cap_usd"] == 0 and proc["daily_soft_cap"] == 0  # the operator sets these
    from lib.anthropic_routing import credit_admitted

    assert credit_admitted(proc) is False


def test_empty_lane_chain_is_a_refusal_not_a_failed_job():
    empty = dict(POLICY, provider_order=["deepseek-flash"])  # inside DeepSeek's peak nothing is left
    with pytest.raises(w.CloudRefused):
        w.call_cloud("p", empty, fallback=lambda *a, **k: pytest.fail("called a model"), now=_utc(2026, 11, 2, 2))
