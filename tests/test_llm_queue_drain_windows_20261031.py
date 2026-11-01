"""Deep overnight LLM queue drain: operator windows, lane chain, triage, and a dry run that writes nothing.

Operator 2026-10-31: weekends + market holidays drain all day; trading days 21:00-04:00 ET; budget ceilings stay;
DeepSeek only outside its billing peak. Live finding the same day: run_deep_overnight_llm_queue.py --dry-run ran
recover_stale_running (an UPDATE) and committed before reaching the dry-run branch. Hermetic: no DB, no network.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import llm_queue_drain_policy as dp  # noqa: E402

POLICY = dp.load_policy()

# Alarm-firing coverage (tests/test_alarm_coverage.py): the drain's one send_telegram site, _send_page, is fired by
# test_the_outage_page_reaches_the_telegram_transport with the transport stubbed.
COVERS = ["scripts/run_deep_overnight_llm_queue.py"]


@pytest.fixture(autouse=True)
def _isolated_breaker(tmp_path, monkeypatch):
    """Each test gets its own persisted breaker file (round 3: the breaker survives across runs by design)."""
    path = tmp_path / "breaker.json"
    monkeypatch.setenv("TRADEAI_DRAIN_BREAKER_STATE", str(path))
    # Never the live clock: main() without --drain-window applies the --hard-stop 03:00 default against
    # datetime.now(), so these tests would pass only between 00:00 and 03:00 local time.
    import run_deep_overnight_llm_queue as drain

    monkeypatch.setattr(drain, "past_hard_stop", lambda hard_stop_str: False)
    return path
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


def test_call_cloud_empty_model_output_is_a_failed_job_not_a_crash():
    from lib.llm_fallback import AllLanesFailed

    def empty(prompt, **kw):
        raise AllLanesFailed([
            {"lane": "anthropic", "ok": False, "error": "RuntimeError: POLICY_NOT_ALLOWED", "skipped_reason": ""},
            {"lane": "grok", "ok": False, "error": "empty response", "skipped_reason": ""},
        ])

    assert w.call_cloud("p", POLICY, fallback=empty, now=_utc(2026, 10, 31, 18))[0] is None


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
    assert w.classify_cloud_failure(exc)[0] == "outage"
    assert w.classify_cloud_failure(TimeoutError("read timed out"))[0] == "outage"


def test_job_specific_input_limit_is_not_a_run_stopping_refusal():
    assert w.classify_cloud_failure(RuntimeError("INPUT_LIMIT_EXCEEDED: 40000 > 32000"))[0] == "job"


def _a(lane, error, ok=False, skipped=""):
    return {"lane": lane, "ok": ok, "error": error, "skipped_reason": skipped}


class _AllLanesFailed(RuntimeError):
    def __init__(self, attempts):
        self.attempts = attempts
        super().__init__("all lanes failed")


# Reviewer round 2 (2026-11-01, probe_cls.py): only empty/unparseable output from a lane that RETURNED, or the
# job-specific gate code, is the job's fault. Everything else is an outage: pending, attempt uncounted, run stops.
@pytest.mark.parametrize(
    "attempts,kind",
    [
        ([_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED: promotional adapter requires governed routing"),
          _a("grok", "unavailable", skipped="reported unavailable"),
          _a("chatgpt", "RuntimeError: AUTH_EXPIRED: ChatGPT session ended"),
          _a("deepseek-flash", "RuntimeError: COST_CONFIGURATION_INVALID: process daily_cost_cap_usd required")], "outage"),
        ([_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED"), _a("grok", "unavailable"),
          _a("chatgpt", "HTTPError: 400 Client Error: Bad Request for url: http://127.0.0.1:10531/v1/chat/completions")],
         "outage"),
        ([_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED"),
          _a("grok", "ConnectionError: HTTPConnectionPool(host='127.0.0.1', port=10530): Max retries exceeded"),
          _a("chatgpt", "ConnectionError: refused")], "outage"),
        ([_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED"), _a("grok", "unavailable"), _a("chatgpt", "unavailable"),
          _a("deepseek-flash", "DeferredToOffPeak: deferred to off-peak")], "outage"),
        ([_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED"), _a("grok", "unavailable"), _a("chatgpt", "unavailable"),
          _a("deepseek-flash", "RuntimeError: INPUT_LIMIT_EXCEEDED: prompt ~40000 tokens exceeds process "
             "max_input_tokens=32000")], "job"),
        ([_a("anthropic", "AnthropicError: INPUT_LIMIT_EXCEEDED")], "job"),
        ([_a("grok", "ValueError: model said 'COST_CAP_EXCEEDED is not a field'")], "job"),
        ([_a("grok", "ValueError: model said 'INPUT_LIMIT_EXCEEDED' somewhere")], "job"),
        ([_a("grok", "HTTPError: 500 body mentions INPUT_LIMIT_EXCEEDED")], "outage"),
        ([_a("grok", "ConnectionError: INPUT_LIMIT_EXCEEDED")], "outage"),  # code only counts from the gate's types
        ([_a("grok", "unavailable"), _a("chatgpt", "RuntimeError: " + "x" * 190 + " COST_CAP_EXCEEDED")], "outage"),
        ([_a("grok", "unavailable"), _a("chatgpt", ("RuntimeError: INPUT_LIMIT_EXCEEDED: " + "y" * 300)[:200])], "job"),
        ([_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED"), _a("grok", "unavailable"), _a("chatgpt", "unavailable")],
         "outage"),
        ([_a("grok", "empty response"), _a("chatgpt", "ConnectionError: refused")], "job"),
        ([], "outage"),
    ],
)
def test_classification_is_structured_not_substring(attempts, kind):
    assert w.classify_cloud_failure(_AllLanesFailed(attempts))[0] == kind


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
    """Records SQL. With a ``store`` it also keeps each row's metadata_json across runs, as the real table does
    (round 11: the rejection strike lives in the job's own metadata_json)."""

    def __init__(self, log, rows, store=None):
        self.log, self.rows, self.last, self.store = log, rows, "", store
        self.description = [(c,) for c in _COLS]
        self.rowcount = 0

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.log.append((flat, params))
        self.last = sql
        if self.store is not None and "SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) ||" in flat:
            self.store.setdefault(params[1], {}).update(json.loads(params[0]))
        elif self.store is not None and "SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) -" in flat:
            self.store.setdefault(params[1], {}).pop(params[0], None)

    def fetchall(self):
        if not ("FROM deep_overnight_llm_queue" in self.last and "pending" in self.last):
            return []
        if self.store is None:
            return list(self.rows)
        meta_at = _COLS.index("metadata_json")
        return [tuple(dict(r[meta_at] or {}, **self.store.get(r[0], {})) if i == meta_at else v
                      for i, v in enumerate(r)) for r in self.rows]

    def fetchone(self):
        return (0,)

    def close(self):
        pass


class _RecConn:
    def __init__(self, log, rows, store=None):
        self.log, self.rows, self.store = log, rows, store

    def cursor(self):
        return _RecCur(self.log, self.rows, self.store)

    def commit(self):
        self.log.append(("COMMIT", None))

    def rollback(self):
        pass

    def close(self):
        pass


def _run(monkeypatch, argv, rows=(), windows=None, store=None):
    log: list = []
    monkeypatch.setattr(w, "get_db_connection", lambda: _RecConn(log, list(rows), store))
    monkeypatch.setattr(w, "log", lambda m: None)
    monkeypatch.setattr(w, "build_prompt", lambda job, *a, **k: f"JOB{job['id']}")
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
    assert [p[1] for _, p in undo] == [7, 8] and "PROCESS_NOT_REGISTERED" in undo[0][1][0]
    running = [p for s, p in log if "SET status = 'running'" in s]
    assert running == [(7,), (8,)], "one refusal tries the next job; the second refusal stops the run"


def _raise_all_failed(*attempts):
    def gen(prompt, **kw):
        raise _AllLanesFailed(list(attempts))

    return gen


def test_model_failure_still_counts_an_attempt(monkeypatch):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(_a("grok", "empty response")))
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



@pytest.mark.parametrize(
    "attempts",
    [
        (_a("grok", "unavailable"), _a("chatgpt", "RuntimeError: AUTH_EXPIRED: ChatGPT session ended")),
        (_a("grok", "unavailable"), _a("chatgpt", "HTTPError: 400 Client Error: Bad Request")),
        (_a("grok", "ConnectionError: refused"), _a("chatgpt", "ConnectionError: refused")),
        (_a("chatgpt", "unavailable"), _a("deepseek-flash", "DeferredToOffPeak: deferred to off-peak")),
    ],
)
def test_lane_outage_never_fails_the_backlog(monkeypatch, attempts):
    """39 jobs sat at attempt 2: one outage run must not push any of them to 'failed'."""
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*attempts))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(21), _row(22), _row(23)])
    sqls = _sqls(log)
    assert not [s for s in sqls if "attempt_count >= 3 THEN 'failed'" in s]
    assert len([s for s in sqls if "GREATEST(attempt_count - 1, 0)" in s]) == 3
    assert [p for s, p in log if "SET status = 'running'" in s] == [(21,), (22,), (23,)], "3 refusals = outage"


def _sequence_generator(outcomes):
    seq = iter(outcomes)

    def gen(prompt, **kw):
        nxt = next(seq)
        if nxt is None:
            raise _AllLanesFailed([_a("grok", "empty response")])
        if nxt == "400":
            raise _AllLanesFailed([_a("grok", "HTTPError: 400 Client Error: Bad Request"),
                                   _a("chatgpt", "HTTPError: 400 Client Error: Bad Request")])
        return _Res()

    return gen


def test_circuit_breaker_stops_after_consecutive_failures(monkeypatch):
    import lib.llm_fallback as lf

    n = int(POLICY["max_consecutive_failures"])
    assert n >= 2
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator([None] * (n + 3)))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", str(n + 3)], rows=[_row(30 + i) for i in range(n + 3)])
    assert len([p for s, p in log if "SET status = 'running'" in s]) == n
    assert len([s for s in _sqls(log) if "attempt_count >= 3 THEN 'failed'" in s]) == n


def test_circuit_breaker_counts_only_consecutive_failures(monkeypatch):
    import lib.llm_fallback as lf

    n = int(POLICY["max_consecutive_failures"])
    outcomes = [None] * (n - 1) + ["ok"] + [None] * (n - 1) + ["ok"]
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(outcomes))
    rows = [_row(50 + i) for i in range(len(outcomes))]
    log = _run(monkeypatch, ["--route", "cloud", "--limit", str(len(outcomes))], rows=rows)
    assert len([p for s, p in log if "SET status = 'running'" in s]) == len(outcomes)


def test_probe_error_skip_is_not_reported_as_a_lane_error():
    kind, reason = w.classify_cloud_failure(_AllLanesFailed([
        _a("grok", "", skipped="availability probe error: OSError"),
        _a("grok", "empty response"),
    ]))
    assert kind == "job"
    assert "availability probe error" not in reason and reason == "grok: empty response"


def test_an_answering_lane_is_never_an_outage():
    # AllLanesFailed never normally carries ok=True; if it ever does, a lane answered, so it is not an outage.
    assert w.classify_cloud_failure(_AllLanesFailed([_a("grok", "", ok=True)]))[0] == "job"



# ── round 3: the next job decides; a persisted breaker remembers outages across cron runs ────────────────────────

_HTTP400 = (_a("grok", "HTTPError: 400 Client Error: Bad Request"), _a("chatgpt", "HTTPError: 400 Client Error: Bad Request"))


def _counted_ids(log):
    return [p[0] for s, p in log if s.startswith("UPDATE deep_overnight_llm_queue SET attempt_count = attempt_count + 1")]


def _struck_ids(log):
    return [p[1] for s, p in log if "SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) ||" in s]


def test_refusal_is_struck_then_charged_on_a_second_run(monkeypatch):
    """Round 11: a confirmed request rejection is a strike (not an attempt) on its first run and is charged only
    when it recurs, confirmed again, on a DIFFERENT run. The strike lives in the job's own metadata_json."""
    import lib.llm_fallback as lf

    store = {}
    rows = [_row(61), _row(62), _row(63)]
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["400", "ok", "ok"]))
    first = _run(monkeypatch, ["--route", "cloud", "--limit", "3"], rows=rows, store=store)
    assert _counted_ids(first) == [] and _struck_ids(first) == [61]
    assert "drain_rejection_strike" in store[61]
    assert [p for s, p in first if "SET status = 'running'" in s] == [(61,), (62,), (63,)]
    # Job 61's prompt is the one rejected (job-specific, not call-order: round 15 runs a struck job after the
    # run's first answer, so a call-order "first call fails" would now hit job 62 -- a blip, not a bad prompt).
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({61}))
    second = _run(monkeypatch, ["--route", "cloud", "--limit", "3"], rows=rows, store=store)
    assert [p for s, p in second if "SET status = 'running'" in s] == [(62,), (61,), (63,)]
    assert _counted_ids(second) == [61] and "drain_rejection_strike" not in store[61], "charged; strike cleared"


def test_a_counted_failure_never_confirms_a_rejection(monkeypatch):
    """Round 11: an empty reply (a counted failure) is not an answer; it confirms no earlier rejection."""
    import lib.llm_fallback as lf

    store = {}
    for _ in range(3):
        monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["400", None]))
        log = _run(monkeypatch, ["--route", "cloud", "--limit", "2"], rows=[_row(64), _row(65)], store=store)
        assert _counted_ids(log) == [] and _struck_ids(log) == []


def test_job_specific_400_is_counted_when_the_next_job_is_answered(monkeypatch, _isolated_breaker):
    """Corrected adversarial test (round 6, two strikes since round 11): ONE job's prompt is rejected by every lane,
    the others are answered. Struck on the first run, charged on the second."""
    import lib.llm_fallback as lf

    store, counted = {}, []
    for _ in range(2):
        monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({71}))
        log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(71), _row(72), _row(73)],
                   store=store)
        counted += _counted_ids(log)
        assert len([p for s, p in log if "status = 'done'" in s]) == 2
    assert counted == [71]


def test_bad_probe_job_does_not_stall_the_queue_after_an_outage(monkeypatch, _isolated_breaker):
    """Breaker open; the probe (jobs[1]) is a prompt every lane rejects; the head is fine (reviewer round 6)."""
    import lib.llm_fallback as lf

    state = w._fresh_breaker()
    w.trip_breaker(state, "outage", "earlier outage", POLICY)
    w.save_breaker(_isolated_breaker, state)
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["400", "ok", "ok"]))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2), _row(3)], store={})
    assert [p for s, p in log if "SET status = 'running'" in s] == [(2,), (1,), (3,)]
    assert _struck_ids(log) == [2] and _counted_ids(log) == [], "first confirmation is a strike, not a charge"
    assert len([p for s, p in log if "status = 'done'" in s]) == 2
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


def test_probe_and_head_both_refused_extends_the_breaker_and_charges_nobody(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    state = w._fresh_breaker()
    w.trip_breaker(state, "outage", "earlier outage", POLICY)
    w.save_breaker(_isolated_breaker, state)
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2), _row(3)])
    assert [p for s, p in log if "SET status = 'running'" in s] == [(2,), (1,), (3,)]
    assert _counted_ids(log) == []
    assert w.load_breaker(_isolated_breaker)["outage"]["trips"] == 2


def test_outage_breaker_persists_and_the_next_run_tries_one_job(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(81), _row(82), _row(83)])
    state = w.load_breaker(_isolated_breaker)
    assert w.breaker_open(state, "outage"), "three non-request refusals in a row open the breaker"
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(81), _row(82), _row(83)])
    assert [p for s, p in log if "SET status = 'running'" in s] == [(82,), (81,), (83,)], "probe first, then the head"
    assert _counted_ids(log) == []
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok", "ok", "ok"]))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(81), _row(82), _row(83)])
    assert len([p for s, p in log if "SET status = 'running'" in s]) == 3, "an answered probe closes the breaker"
    state = w.load_breaker(_isolated_breaker)
    assert not w.breaker_open(state, "outage")


def test_failure_breaker_persists_so_a_bad_lane_burns_one_job_per_run(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    n = int(POLICY["max_consecutive_failures"])
    rows = [_row(90 + i) for i in range(n + 2)]
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator([None] * 50))
    first = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=rows)
    assert len([p for s, p in first if "SET status = 'running'" in s]) == n
    assert w.breaker_open(w.load_breaker(_isolated_breaker), "failure")
    second = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=rows)
    assert len([p for s, p in second if "SET status = 'running'" in s]) == 1
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok"] * 50))
    third = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=rows)
    assert len([p for s, p in third if "SET status = 'running'" in s]) == len(rows)
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "failure")


def test_cooldown_doubles_and_is_capped():
    state = w._fresh_breaker()
    t0 = _utc(2026, 11, 1, 12)
    got = [w.trip_breaker(state, "outage", "x", POLICY, now=t0) for _ in range(7)]
    base, cap = float(POLICY["breaker_cooldown_min"]), float(POLICY["breaker_cooldown_max_min"])
    assert got[:3] == [base, base * 2, base * 4] and max(got) == cap and got[-1] == cap
    assert w.breaker_open(state, "outage", now=t0) and not w.breaker_open(state, "outage", now=_utc(2026, 11, 2, 12))


def test_unreadable_breaker_file_reads_closed(_isolated_breaker):
    _isolated_breaker.write_text("{not json", encoding="utf-8")
    state = w.load_breaker(_isolated_breaker)
    assert not w.breaker_open(state, "outage") and not w.breaker_open(state, "failure")
    _isolated_breaker.write_text(json.dumps({"schema": "Other@v1", "outage": {"open_until": "2999-01-01T00:00:00+00:00"}}))
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


def test_one_job_queue_refused_stays_pending_uncounted(monkeypatch, _isolated_breaker):
    """Round 6: no next job can decide, so the job simply stays pending; nothing is ever charged for a refusal."""
    import lib.llm_fallback as lf

    counted = []
    for _ in range(6):
        monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_HTTP400))
        counted += _counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(99)]))
    assert counted == []
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "outage"), "one ambiguous refusal is not an outage"

# ── round 4: an outage never strikes; the probe is not the head; corrupt breaker fields never crash ──────────────

_CONN_REFUSED = (_a("grok", "ConnectionError: HTTPConnectionPool(host='127.0.0.1', port=10530): Max retries exceeded"),
                 _a("chatgpt", "ConnectionError: refused"))


def test_long_transport_outage_spends_no_attempts(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    spent = 0
    for _ in range(24):  # 12 h of half-hourly cron runs during a pure lane outage
        monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
        spent += len(_counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "5"],
                                       rows=[_row(1), _row(2), _row(3)])))
    assert spent == 0


@pytest.mark.parametrize(
    "attempts,expected",
    [
        (_HTTP400, True),
        ((_a("grok", "HTTPError: 413 Payload Too Large"), _a("chatgpt", "HTTPError: 422 Unprocessable")), True),
        ((_a("grok", "KeyError: 'choices'"), _a("chatgpt", "HTTPError: 400 Bad Request")), True),
        # round 6: diagnostic only; lanes that did not run (unavailable, gate refusal, deferral) are ignored
        ((_a("grok", "HTTPError: 413 Payload Too Large"), _a("chatgpt", "unavailable")), True),
        ((_a("grok", "unavailable"), _a("chatgpt", "HTTPError: 400 Client Error: Bad Request")), True),
        ((_a("grok", "KeyError: 'choices'"),), True),
        ((_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED: promotional adapter requires governed routing"),
          _a("grok", "HTTPError: 400 Bad Request"), _a("chatgpt", "HTTPError: 400 Bad Request")), True),
        ((_a("grok", "HTTPError: 400 Bad Request"),
          _a("deepseek-flash", "RuntimeError: COST_CONFIGURATION_INVALID: process daily_cost_cap_usd required")), True),
        ((_a("grok", "HTTPError: 400 Bad Request"), _a("deepseek-flash", "DeferredToOffPeak: deferred")), True),
        ((_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED"), _a("deepseek-flash", "ManualRequired: m")), False),
        ((_a("grok", "HTTPError: 400 Bad Request"), _a("chatgpt", "RuntimeError: AUTH_EXPIRED: x")), False),
        ((_a("grok", "HTTPError: 400 Bad Request"), _a("chatgpt", "ValueError: POLICY_NOT_ALLOWED")), False),
        # two lanes agreeing on a non-request status is still not this prompt's fault
        ((_a("grok", "HTTPError: 401 Unauthorized"), _a("chatgpt", "HTTPError: 401 Unauthorized")), False),
        ((_a("grok", "HTTPError: 429 Too Many Requests"), _a("chatgpt", "HTTPError: 429 Too Many")), False),
        ((_a("grok", "HTTPError: 502 Bad Gateway"), _a("chatgpt", "HTTPError: 503 Unavailable")), False),
        ((_a("grok", "ReadTimeout: read timed out"), _a("chatgpt", "ReadTimeout: read timed out")), False),
        # every lane that ran must reject; an unavailable lane neither rejects nor blocks
        ((_a("grok", "HTTPError: 400 Bad Request"), _a("chatgpt", "HTTPError: 400 Bad Request"),
          _a("deepseek-flash", "ConnectionError: refused")), False),
        ((_a("grok", "HTTPError: 400 Bad Request"), _a("chatgpt", "HTTPError: 400 Bad Request"),
          _a("deepseek-flash", "unavailable")), True),
        ((_a("grok", "HTTPError: 400 Bad Request"), _a("chatgpt", "ConnectionError: refused")), False),
        ((_a("grok", "HTTPError: 401 Unauthorized"),), False),
        ((_a("grok", "HTTPError: 429 Too Many Requests"),), False),
        ((_a("grok", "HTTPError: 502 Bad Gateway"),), False),
        ((_a("grok", "ReadTimeout: read timed out"),), False),
        ((_a("grok", "RuntimeError: AUTH_EXPIRED: session ended"),), False),
        ((_a("grok", "unavailable"), _a("chatgpt", "unavailable")), False),
        ((), False),
    ],
)
def test_request_rejected_is_structured(attempts, expected):
    assert w.request_rejected(_AllLanesFailed(list(attempts))) is expected


def test_probe_answered_closes_the_breaker_and_the_head_runs_next(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2), _row(3)])
    assert w.breaker_open(w.load_breaker(_isolated_breaker), "outage")
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok", "ok", "ok"]))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2), _row(3)])
    assert [p for s, p in log if "SET status = 'running'" in s] == [(2,), (1,), (3,)]
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


@pytest.mark.parametrize(
    "doc",
    [
        {"outage": {"trips": 1, "open_until": "2099-01-01T00:00:00"}},  # naive timestamp
        {"outage": {"trips": "x", "open_until": 12345}, "failure": {"trips": None}},
        {"outage": "not a dict", "failure": [], "strikes": {"7": "x", "8": -2, "9": 2}},
        {"outage": {"open_until": "not a date"}},
        {"outage": {"trips": -5, "open_until": None}, "failure": {"trips": -1}},
    ],
)
def test_corrupt_breaker_fields_never_crash(monkeypatch, _isolated_breaker, doc):
    import lib.llm_fallback as lf

    _isolated_breaker.write_text(json.dumps({"schema": w.BREAKER_SCHEMA, **doc}), encoding="utf-8")
    state = w.load_breaker(_isolated_breaker)
    for kind in ("outage", "failure"):
        assert isinstance(state[kind]["trips"], int) and state[kind]["trips"] >= 0
        assert state[kind]["open_until"] is None or isinstance(state[kind]["open_until"], str)
        w.breaker_open(state, kind)
        w.trip_breaker(dict(state), kind, "r", POLICY)
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)])


def test_naive_open_until_reads_as_utc():
    state = w._fresh_breaker()
    state["outage"]["open_until"] = "2026-11-01T12:00:00"
    assert w.breaker_open(state, "outage", now=_utc(2026, 11, 1, 11, 59))
    assert not w.breaker_open(state, "outage", now=_utc(2026, 11, 1, 12, 1))



def test_trip_tolerates_a_raw_corrupt_trips_value():
    state = w._fresh_breaker()
    state["outage"]["trips"] = "x"
    w.trip_breaker(state, "outage", "r", POLICY)
    assert state["outage"]["trips"] == 1


def test_one_job_queue_in_a_transport_outage_is_never_struck(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    spent = 0
    for _ in range(6):
        monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
        spent += len(_counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(5)])))
    assert spent == 0



def test_long_systemic_single_lane_400_outage_spends_no_attempts(monkeypatch, _isolated_breaker):
    """Grok unavailable + ChatGPT answering 400 to every request for 12 h (reviewer round 5): no attempts spent."""
    import lib.llm_fallback as lf

    systemic = (_a("grok", "unavailable", skipped="reported unavailable"),
                _a("chatgpt", "HTTPError: 400 Client Error: Bad Request for url: http://127.0.0.1:10531/v1/chat"))
    spent = 0
    for _ in range(24):
        monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*systemic))
        spent += len(_counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "5"],
                                       rows=[_row(1), _row(2), _row(3)])))
    assert spent == 0



# ── pre-activation: rotating probe; one page for a long outage ────────────────────────────────────────────────────

def _bad_ids_generator(bad):
    def gen(prompt, **kw):
        if int(prompt[3:]) in bad:
            raise _AllLanesFailed(list(_HTTP400))
        return _Res()

    return gen


def _done(log):
    return [p[-1] for s, p in log if "status = 'done'" in s]


@pytest.mark.parametrize("trips,n,expected", [(0, 4, 1), (1, 4, 1), (2, 4, 2), (3, 4, 3), (9, 4, 3), (5, 2, 1), (3, 1, 0)])
def test_probe_index_rotates_with_trip_count(trips, n, expected):
    state = w._fresh_breaker()
    state["outage"]["trips"] = trips
    assert w.probe_index(state, n) == expected


def test_two_adjacent_bad_jobs_at_the_head_do_not_wedge_the_drain(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    rows = [_row(1), _row(2), _row(3), _row(4)]
    done = []
    for _ in range(4):
        monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({1, 2}))
        done += _done(_run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=rows))
    assert 3 in done, f"good job 3 never ran behind two bad heads: {done}"


def test_two_job_queue_both_bad_charges_nobody(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    counted = []
    for _ in range(6):
        monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({1, 2}))
        counted += _counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)]))
    assert counted == []


def _long_open_breaker(path, hours_ago, **extra):
    state = w._fresh_breaker()
    t0 = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    w.trip_breaker(state, "outage", "earlier outage", POLICY, now=t0)
    state["outage"]["open_until"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    state["outage"].update(extra)
    w.save_breaker(path, state)
    return state["outage"]["since"]


def _pages(monkeypatch, accept=True):
    sent = []

    def fake(message):
        sent.append(message)
        return accept

    monkeypatch.setattr(w, "_send_page", fake)
    return sent


def test_long_outage_pages_once(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    since = _long_open_breaker(_isolated_breaker, hours_ago=7)
    sent = _pages(monkeypatch)
    for _ in range(3):
        monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
        _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)])
    assert len(sent) == 1 and "every lane has refused" in sent[0] and "/" not in sent[0]
    assert w.load_breaker(_isolated_breaker)["outage"]["paged_since"] == since


def test_the_outage_page_reaches_the_telegram_transport(monkeypatch, _isolated_breaker):
    """Firing test for the alarm: the real _send_page runs and the message reaches telegram_alert.send_telegram
    (stubbed: nothing leaves the machine) once, at P2, under the drain's producer id."""
    import lib.llm_fallback as lf
    import telegram_alert

    calls = []

    def transport(message, *args, **kwargs):
        calls.append((message, kwargs))
        return True

    monkeypatch.setattr(telegram_alert, "send_telegram", transport)
    _long_open_breaker(_isolated_breaker, hours_ago=7)
    for _ in range(2):
        monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
        _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)])
    assert len(calls) == 1
    message, kwargs = calls[0]
    assert "every lane has refused" in message
    assert kwargs == {"priority": "P2", "producer": "deep_overnight_llm_drain"}


def test_long_outage_page_retries_after_a_failed_send(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    _long_open_breaker(_isolated_breaker, hours_ago=7)
    sent = _pages(monkeypatch, accept=False)
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)])
    assert len(sent) == 1 and "paged_since" not in w.load_breaker(_isolated_breaker)["outage"]
    sent = _pages(monkeypatch, accept=True)
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)])
    assert len(sent) == 1 and "paged_since" in w.load_breaker(_isolated_breaker)["outage"]


def test_short_outage_does_not_page(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    _long_open_breaker(_isolated_breaker, hours_ago=float(POLICY["outage_page_after_hours"]) - 1)
    sent = _pages(monkeypatch)
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)])
    assert sent == []


def test_a_broken_notifier_never_crashes_the_drain(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    _long_open_breaker(_isolated_breaker, hours_ago=7)
    monkeypatch.setattr(w, "_send_page", lambda m: (_ for _ in ()).throw(OSError("telegram down")))
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)])
    assert "paged_since" not in w.load_breaker(_isolated_breaker)["outage"]


def test_a_new_outage_after_recovery_pages_again(monkeypatch, _isolated_breaker):
    state = w._fresh_breaker()
    t0 = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
    w.trip_breaker(state, "outage", "a", POLICY, now=t0)
    sent = _pages(monkeypatch)
    assert w.maybe_page_long_outage(state, POLICY, now=t0 + timedelta(hours=7))
    assert not w.maybe_page_long_outage(state, POLICY, now=t0 + timedelta(hours=8))
    w.close_breaker(state, "outage")
    w.trip_breaker(state, "outage", "b", POLICY, now=t0 + timedelta(hours=20))
    assert state["outage"]["since"] == (t0 + timedelta(hours=20)).isoformat()
    w.trip_breaker(state, "outage", "b", POLICY, now=t0 + timedelta(hours=21))
    assert state["outage"]["since"] == (t0 + timedelta(hours=20)).isoformat(), "since is kept across trips"
    assert w.maybe_page_long_outage(state, POLICY, now=t0 + timedelta(hours=27)) and len(sent) == 2



# ── round 8: throughput with bad jobs at the head; credential-free page text; claim before send ────────────────

def test_two_bad_jobs_at_the_head_do_not_throttle_the_drain(monkeypatch, _isolated_breaker):
    """[B1, B2, G3..G22], limit 5, 6 runs (the fake queue never shrinks): every run drains 3 good jobs; B1 and B2 are
    struck on one run and charged on the next (two strikes), without ever tripping the outage breaker."""
    import lib.llm_fallback as lf

    rows = [_row(i) for i in range(1, 23)]
    done, counted, store = [], [], {}
    for _ in range(6):
        monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({1, 2}))
        log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=rows, store=store)
        done += _done(log)
        counted += _counted_ids(log)
    assert len(done) >= 15 and set(counted) == {1, 2}
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


def test_rejections_after_an_answer_are_not_charged_without_a_later_answer(monkeypatch, _isolated_breaker):
    """Round 10: an earlier answer proves nothing about a later 400 (a systemic or throttling 400 looks the same).
    Without a LATER answer nobody is charged. Round 12: request rejections never trip the outage breaker; an
    unbroken run of max_consecutive_request_rejections ends the run instead (no trip, no flap)."""
    import lib.llm_fallback as lf

    bound = int(POLICY["max_consecutive_request_rejections"])
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok"] + ["400"] * (bound + 5)))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "30"], rows=[_row(100 + i) for i in range(bound + 5)],
               store={})
    assert _counted_ids(log) == [] and _struck_ids(log) == []
    # rounds 13-14: lanes answered earlier, so after the bound ONE probe is tried; it is rejected, so the run ends
    assert len([p for s, p in log if "SET status = 'running'" in s]) == 1 + bound + 1
    state = w.load_breaker(_isolated_breaker)
    assert not w.breaker_open(state, "outage") and state["flaps"] == 0
    assert "no_progress" not in state, "a run with an answer is progress"


def test_rejection_between_two_answers_is_charged_on_its_second_run(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    store, counted = {}, []
    for _ in range(2):
        monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok", "400", "ok"]))
        counted += _counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "5"],
                                     rows=[_row(1), _row(2), _row(3)], store=store))
    assert counted == [2]


def test_a_bad_job_that_is_always_last_stays_pending(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    counted = []
    for _ in range(6):
        monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({3}))
        counted += _counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "5"],
                                     rows=[_row(1), _row(2), _row(3)]))
    assert counted == []
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


@pytest.mark.parametrize(
    "attempts",
    [
        (_a("grok", "KeyError: 'choices'"), _a("chatgpt", "KeyError: 'choices'")),
        (_a("grok", "JSONDecodeError: Expecting value: line 1 column 1 (char 0)"),
         _a("chatgpt", "JSONDecodeError: Expecting value: line 1 column 1 (char 0)")),
    ],
)
def test_proxy_bodies_are_ambiguous_not_the_jobs_failure(attempts):
    exc = _AllLanesFailed(list(attempts))
    assert w.classify_cloud_failure(exc)[0] == "outage"
    assert w.request_rejected(exc) is True


def test_proxy_login_page_for_a_whole_run_charges_nobody(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    html = (_a("grok", "JSONDecodeError: Expecting value: line 1 column 1 (char 0)"),
            _a("chatgpt", "JSONDecodeError: Expecting value: line 1 column 1 (char 0)"))
    counted = 0
    for _ in range(6):
        monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*html))
        log = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=[_row(800 + i) for i in range(10)])
        counted += len(_counted_ids(log)) + len([s for s in _sqls(log) if "attempt_count >= 3 THEN 'failed'" in s])
    assert counted == 0


def test_two_refusals_at_the_end_of_the_queue_open_the_outage_breaker(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)])
    assert _counted_ids(log) == []
    assert w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("grok: unavailable; chatgpt: HTTPError: 400 for url: https://x.example/v1?api_key=SECRETabc123&t=1",
         "grok unavailable; chatgpt HTTP 400"),
        ("anthropic: RuntimeError: POLICY_NOT_ALLOWED: detail https://h/?token=SECRETxyz",
         "anthropic POLICY_NOT_ALLOWED"),
        ("grok: ConnectionError: HTTPConnectionPool(host='127.0.0.1', port=10530): password=hunter2",
         "grok ConnectionError"),
        ("chatgpt: RuntimeError: AUTH_EXPIRED: Bearer SECRETtok", "chatgpt RuntimeError"),
        ("https://u:SECRETpw@h/x: boom; grok: unavailable", "grok unavailable"),
        ("", "no lane detail"),
    ],
)
def test_page_summary_never_carries_free_text(reason, expected):
    out = w.safe_reason_summary(reason)
    assert out == expected and "SECRET" not in out and "hunter2" not in out


def test_page_claim_is_recorded_before_the_send(monkeypatch):
    state = w._fresh_breaker()
    t0 = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
    w.trip_breaker(state, "outage", "grok: unavailable", POLICY, now=t0)
    order = []
    monkeypatch.setattr(w, "_send_page", lambda m: order.append(("send", dict(state["outage"]).get("paging_claim"))) or True)
    persisted = []
    assert w.maybe_page_long_outage(state, POLICY, now=t0 + timedelta(hours=7),
                                    persist=lambda st: persisted.append(json.loads(json.dumps(st))))
    assert order and order[0][1] is not None, "the claim must exist when the send happens"
    assert persisted[0]["outage"].get("paging_claim"), "the claim is persisted before the send"
    assert persisted[-1]["outage"]["paged_since"] == state["outage"]["since"]


def test_unpersistable_claim_means_no_send(monkeypatch):
    state = w._fresh_breaker()
    t0 = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
    w.trip_breaker(state, "outage", "grok: unavailable", POLICY, now=t0)
    sent = _pages(monkeypatch)

    def broken(st):
        raise OSError("disk full")

    assert not w.maybe_page_long_outage(state, POLICY, now=t0 + timedelta(hours=7), persist=broken)
    assert sent == [] and "paging_claim" not in state["outage"]


def test_a_fresh_claim_blocks_a_second_page_and_a_stale_one_retries(monkeypatch):
    state = w._fresh_breaker()
    t0 = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
    w.trip_breaker(state, "outage", "grok: unavailable", POLICY, now=t0)
    now = t0 + timedelta(hours=7)
    state["outage"]["paging_claim"] = {"since": state["outage"]["since"], "at": now.isoformat()}  # send in doubt
    sent = _pages(monkeypatch)
    assert not w.maybe_page_long_outage(state, POLICY, now=now + timedelta(minutes=10)) and sent == []
    assert w.maybe_page_long_outage(state, POLICY, now=now + timedelta(hours=2)) and len(sent) == 1


def test_page_claim_survives_a_restart(_isolated_breaker):
    state = w._fresh_breaker()
    w.trip_breaker(state, "outage", "grok: unavailable", POLICY)
    state["outage"]["paging_claim"] = {"since": state["outage"]["since"], "at": "2026-11-01T07:00:00+00:00"}
    w.save_breaker(_isolated_breaker, state)
    assert w.load_breaker(_isolated_breaker)["outage"]["paging_claim"]["since"] == state["outage"]["since"]


def test_outage_stops_after_outage_after_refusals_not_at_the_end_of_the_queue(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    n = int(POLICY["outage_after_refusals"])
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=[_row(200 + i) for i in range(n + 3)])
    assert [p for s, p in log if "SET status = 'running'" in s] == [(200 + i,) for i in range(n)]
    assert _counted_ids(log) == [] and w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


def test_page_text_never_carries_the_raw_reason(monkeypatch):
    state = w._fresh_breaker()
    t0 = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
    w.trip_breaker(state, "outage", "grok: unavailable; chatgpt: HTTPError: 400 for url: "
                   "https://x.example/v1?api_key=SECRETabc123&t=1", POLICY, now=t0)
    sent = _pages(monkeypatch)
    assert w.maybe_page_long_outage(state, POLICY, now=t0 + timedelta(hours=7))
    assert "SECRETabc123" not in sent[0] and "api_key" not in sent[0] and "chatgpt HTTP 400" in sent[0]


def test_long_outage_pages_from_a_mid_run_trip(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    _long_open_breaker(_isolated_breaker, hours_ago=7)
    sent = _pages(monkeypatch)
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=[_row(300 + i) for i in range(6)])
    assert len([p for s, p in log if "SET status = 'running'" in s]) == int(POLICY["outage_after_refusals"])
    assert len(sent) == 1


# ── round 9: only a request rejection is ever charged; a flapping lane backs off ─────────────────────────────────

_TRANSIENT = {
    "429": (_a("grok", "HTTPError: 429 Too Many Requests"), _a("chatgpt", "HTTPError: 429 Too Many Requests")),
    "503": (_a("grok", "HTTPError: 503 Service Unavailable"), _a("chatgpt", "HTTPError: 502 Bad Gateway")),
    "timeout": (_a("grok", "ReadTimeout: read timed out"), _a("chatgpt", "ReadTimeout: read timed out")),
    "transport": _CONN_REFUSED,
    "unavailable": (_a("grok", "unavailable"), _a("chatgpt", "unavailable")),
    "gate": (_a("anthropic", "RuntimeError: POLICY_NOT_ALLOWED"), _a("grok", "RuntimeError: COST_CAP_EXCEEDED: x")),
}


def _answers_then(n_ok, attempts):
    calls = {"n": 0}

    def gen(prompt, **kw):
        calls["n"] += 1
        if calls["n"] <= n_ok:
            return _Res()
        raise _AllLanesFailed(list(attempts))

    return gen


@pytest.mark.parametrize("kind", sorted(_TRANSIENT))
def test_transient_refusal_after_an_answer_is_never_charged(monkeypatch, _isolated_breaker, kind):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _answers_then(2, _TRANSIENT[kind]))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "20"], rows=[_row(400 + i) for i in range(20)])
    assert _counted_ids(log) == []
    assert len(_done(log)) == 2
    assert w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


@pytest.mark.parametrize("kind", sorted(_TRANSIENT))
def test_transient_refusal_before_an_answer_is_never_charged(monkeypatch, _isolated_breaker, kind):
    import lib.llm_fallback as lf

    seq = iter([False, True, True])

    def gen(prompt, **kw):
        if next(seq):
            return _Res()
        raise _AllLanesFailed(list(_TRANSIENT[kind]))

    monkeypatch.setattr(lf, "generate_with_fallback", gen)
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2), _row(3)], store={})
    assert _counted_ids(log) == [] and len(_done(log)) == 2
    assert _struck_ids(log) == [], "a transient refusal is never even struck"


def test_rate_limit_over_many_runs_never_charges_good_jobs(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    counted, done = [], []
    for _ in range(12):
        monkeypatch.setattr(lf, "generate_with_fallback", _answers_then(2, _TRANSIENT["429"]))
        log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=[_row(i) for i in range(1, 30)])
        counted += _counted_ids(log)
        done += _done(log)
    assert counted == [] and len(done) == 24


def test_flapping_lane_backs_off_and_a_clean_run_resets_it(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    rows = [_row(500 + i) for i in range(40)]
    monkeypatch.setattr(lf, "generate_with_fallback", _answers_then(2, _TRANSIENT["429"]))
    _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=rows)
    assert w.load_breaker(_isolated_breaker)["flaps"] == 1, "an outage after answers is a flap"
    monkeypatch.setattr(lf, "generate_with_fallback", _answers_then(2, _TRANSIENT["429"]))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=rows)
    assert len([p for s, p in log if "SET status = 'running'" in s]) <= 2 + int(POLICY["outage_after_refusals"])
    assert w.load_breaker(_isolated_breaker)["flaps"] == 2
    # volume is halved per flap: with 3 flaps, 40 jobs -> 5 taken; all answered -> clean run resets the counter
    state = w.load_breaker(_isolated_breaker)
    w.close_breaker(state, "outage")
    state["flaps"] = 3
    w.save_breaker(_isolated_breaker, state)
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok"] * 50))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=rows)
    assert len(_done(log)) == 40 >> 3
    assert w.load_breaker(_isolated_breaker)["flaps"] == 0


def test_flap_floor_keeps_two_jobs(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    state = w._fresh_breaker()
    state["flaps"] = 10
    w.save_breaker(_isolated_breaker, state)
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok"] * 10))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=[_row(600 + i) for i in range(6)])
    assert len(_done(log)) == 2


def test_an_outage_with_no_answers_is_not_a_flap(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=[_row(700 + i) for i in range(5)])
    assert w.load_breaker(_isolated_breaker)["flaps"] == 0


@pytest.mark.parametrize("raw,expected", [("x", 0), (-3, 0), (99, 10), (2, 2), (None, 0)])
def test_flaps_are_sanitized_on_load(_isolated_breaker, raw, expected):
    _isolated_breaker.write_text(json.dumps({"schema": w.BREAKER_SCHEMA, "flaps": raw}), encoding="utf-8")
    assert w.load_breaker(_isolated_breaker)["flaps"] == expected


# ── round 11: a real answer confirms; ratio guard; two strikes across runs ──────────────────────────────────────

@pytest.mark.parametrize("seen,limit", [(1, 2), (5, 2), (10, 2), (20, 2), (21, 3), (30, 3), (100, 10)])
def test_systemic_rejection_limit(seen, limit):
    assert w.systemic_rejection_limit(seen) == limit


def test_alternating_throttle_400_strikes_nobody(monkeypatch, _isolated_breaker):
    """A token-bucket provider that 400s every other call: about half the run is 'rejected' -> systemic."""
    import lib.llm_fallback as lf

    store, counted, struck = {}, [], []
    for _ in range(6):
        monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok", "400"] * 20))
        log = _run(monkeypatch, ["--route", "cloud", "--limit", "20"], rows=[_row(900 + i) for i in range(20)],
                   store=store)
        counted += _counted_ids(log)
        struck += _struck_ids(log)
    assert counted == [] and struck == [] and store == {}


def test_ratio_guard_boundary(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    # 2 rejections among 10 jobs: at the limit -> struck (not charged)
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok", "ok", "400", "400"] + ["ok"] * 6))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=[_row(950 + i) for i in range(10)], store={})
    assert sorted(_struck_ids(log)) == [952, 953] and _counted_ids(log) == []
    # 3 rejections among 10 jobs: over the limit -> systemic, nobody struck
    monkeypatch.setattr(lf, "generate_with_fallback",
                        _sequence_generator(["ok", "400", "ok", "400", "ok", "400"] + ["ok"] * 4))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=[_row(960 + i) for i in range(10)], store={})
    assert _struck_ids(log) == [] and _counted_ids(log) == []


def test_empty_replies_after_rejections_strike_nobody(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    store = {}
    for _ in range(3):
        monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["400", "400", None, None, None]))
        log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(970 + i) for i in range(5)],
                   store=store)
        assert not {970, 971} & set(_counted_ids(log)) and _struck_ids(log) == []


def test_a_strike_from_the_same_run_never_charges():
    log = []

    class Cur:
        def execute(self, sql, params=None):
            log.append((" ".join(sql.split()), params))

    run_a, run_b = "2026-11-01T01:00:00+00:00", "2026-11-01T02:00:00+00:00"
    charged, struck = w.apply_rejection_strikes(Cur(), [(5, "r", {w.STRIKE_KEY: run_a})], run_a, 10)
    assert charged == [] and struck == [5]
    charged, struck = w.apply_rejection_strikes(Cur(), [(5, "r", {w.STRIKE_KEY: run_a})], run_b, 10)
    assert charged == [5] and struck == []


def test_a_strike_is_never_an_attempt():
    log = []

    class Cur:
        def execute(self, sql, params=None):
            log.append(" ".join(sql.split()))

    w.apply_rejection_strikes(Cur(), [(5, "r", {})], "RUN-A", 10)
    assert log and not [s for s in log if "attempt_count" in s]


@pytest.mark.parametrize("meta,expected", [({"a": 1}, {"a": 1}), ('{"a": 1}', {"a": 1}), ("not json", {}),
                                           (None, {}), ([1, 2], {})])
def test_job_metadata_is_read_safely(meta, expected):
    assert w._job_meta({"metadata_json": meta}) == expected


# ── round 12: request rejections never trip the outage breaker; bound + no-progress record; expiry; clear ──────

def test_three_bad_jobs_at_the_head_do_not_stall_the_drain(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    rows = [_row(i) for i in range(1, 41)]
    done = []
    for _ in range(4):
        monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({1, 2, 3}))
        log = _run(monkeypatch, ["--route", "cloud", "--limit", "40"], rows=rows, store={})
        done += _done(log)
    assert len(done) == 4 * 37
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "outage")


def test_request_rejection_bound_ends_the_run_without_tripping_and_records_no_progress(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    bound = int(POLICY["max_consecutive_request_rejections"])
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_HTTP400))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "40"], rows=[_row(i) for i in range(1, 31)])
    probes = len(w.probe_positions(30 - bound, bound, int(POLICY["max_probes_per_run"])))
    assert len([p for s, p in log if "SET status = 'running'" in s]) == bound + probes, "bound, then rejected probes"
    state = w.load_breaker(_isolated_breaker)
    assert not w.breaker_open(state, "outage") and state["flaps"] == 0
    assert state["no_progress"]["runs"] == 1, "a run with no answer at all must be recorded as no progress"
    _run(monkeypatch, ["--route", "cloud", "--limit", "40"], rows=[_row(i) for i in range(1, 31)])
    assert w.load_breaker(_isolated_breaker)["no_progress"]["runs"] == 2


def test_no_progress_pages_after_the_threshold_and_clears_on_an_answer(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    state = w._fresh_breaker()
    state["no_progress"] = {"since": (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(), "runs": 5,
                            "reason": "grok: HTTPError: 400 Bad Request"}
    w.save_breaker(_isolated_breaker, state)
    sent = _pages(monkeypatch)
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_HTTP400))
    _run(monkeypatch, ["--route", "cloud", "--limit", "40"], rows=[_row(i) for i in range(1, 31)])
    _run(monkeypatch, ["--route", "cloud", "--limit", "40"], rows=[_row(i) for i in range(1, 31)])
    assert len(sent) == 1 and "no progress" in sent[0] and "grok HTTP 400" in sent[0]
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok"] * 5))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(i) for i in range(1, 6)])
    assert "no_progress" not in w.load_breaker(_isolated_breaker)


def test_no_progress_record_survives_a_restart_and_is_sanitized(_isolated_breaker):
    _isolated_breaker.write_text(json.dumps({"schema": w.BREAKER_SCHEMA, "no_progress": {
        "since": "2026-11-01T00:00:00+00:00", "runs": "3", "paged_since": "2026-11-01T00:00:00+00:00"}}))
    npr = w.load_breaker(_isolated_breaker)["no_progress"]
    assert npr["runs"] == 3 and npr["paged_since"] == "2026-11-01T00:00:00+00:00"
    _isolated_breaker.write_text(json.dumps({"schema": w.BREAKER_SCHEMA, "no_progress": {"since": 5, "runs": 2}}))
    assert "no_progress" not in w.load_breaker(_isolated_breaker)


@pytest.mark.parametrize(
    "prev,run_id,fresh",
    [
        ("2026-11-01T00:00:00+00:00", "2026-11-03T00:00:00+00:00", True),
        ("2026-09-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00", False),  # two months old
        ("2026-10-25T00:00:00+00:00", "2026-11-01T00:00:00+00:00", True),   # exactly 7 days
        ("2026-10-24T23:00:00+00:00", "2026-11-01T00:00:00+00:00", False),  # just past 7 days
        ("2026-11-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00", False),  # same run
        ("2026-11-02T00:00:00+00:00", "2026-11-01T00:00:00+00:00", False),  # from the future
        ("not a date", "2026-11-01T00:00:00+00:00", False),
        (None, "2026-11-01T00:00:00+00:00", False),
        ("2026-11-01T00:00:00", "2026-11-02T00:00:00+00:00", True),         # naive read as UTC
    ],
)
def test_strike_freshness(prev, run_id, fresh):
    assert w._strike_is_fresh(prev, run_id, 7) is fresh


def test_an_expired_strike_is_overwritten_not_charged(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    store = {1: {w.STRIKE_KEY: "2026-09-01T00:00:00+00:00"}}
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({1}))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2), _row(3)], store=store)
    assert _counted_ids(log) == [] and _struck_ids(log) == [1]
    assert store[1][w.STRIKE_KEY] != "2026-09-01T00:00:00+00:00"


def test_a_success_clears_a_strike(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    store = {1: {w.STRIKE_KEY: datetime.now(timezone.utc).isoformat()}}
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok", "ok"]))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1), _row(2)], store=store)
    assert w.STRIKE_KEY not in store[1]


def test_rejections_interleaved_with_answers_never_hit_the_bound(monkeypatch, _isolated_breaker):
    """The bound is on CONSECUTIVE rejections with no answer between them: an answer resets it."""
    import lib.llm_fallback as lf

    n = int(POLICY["max_consecutive_request_rejections"]) + 4
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["400", "ok"] * n))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=[_row(1000 + i) for i in range(2 * n)],
               store={})
    assert len([p for s, p in log if "SET status = 'running'" in s]) == 2 * n



# ── round 13/14: forward geometric probes past a bad block of any length; systemic only if every probe is rejected ──

def _running(log):
    return [p[0] for s, p in log if "SET status = 'running'" in s]


@pytest.mark.parametrize(
    "n,bound,allowed,expected",
    [
        (90, 10, 4, [0, 20, 40, 80]),
        (30, 10, 4, [0, 20, 29]),
        (20, 10, 4, [0, 19]),
        (1, 10, 4, [0]),
        (0, 10, 4, []),
        (90, 10, 1, [0]),
        (90, 10, 0, []),
    ],
)
def test_probe_positions_are_forward_and_geometric(n, bound, allowed, expected):
    assert w.probe_positions(n, bound, allowed) == expected


@pytest.mark.parametrize("block", [10, 12, 40, 50, 85])
def test_a_bad_block_of_any_length_at_the_head_does_not_starve_the_queue(monkeypatch, _isolated_breaker, block):
    import lib.llm_fallback as lf

    rows = [_row(i) for i in range(1, 101)]
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, block + 1))))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=rows, store={})
    assert sorted(_done(log)) == list(range(block + 1, 101)), "every good job in the fetch drains"
    ran = _running(log)
    assert len(ran) == len(set(ran)), "each job is tried at most once per run"
    assert _counted_ids(log) == []
    assert not w.breaker_open(w.load_breaker(_isolated_breaker), "outage")
    assert "no_progress" not in w.load_breaker(_isolated_breaker), "a probe answer is progress"


def test_good_jobs_after_a_block_drain_in_priority_order(monkeypatch, _isolated_breaker):
    """B1-B12, G13..: the probe at +0 (job 11) is rejected, +2b (job 31) answers, then 12..30 run FORWARD before 32+."""
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, 13))))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=[_row(i) for i in range(1, 101)], store={})
    ran = _running(log)
    assert ran[:12] == list(range(1, 11)) + [11, 31]
    assert ran[12:31] == [j for j in range(12, 32) if j != 31] and ran[31:] == list(range(32, 101))


def test_probe_answer_confirms_the_block_struck_now_charged_next_run(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    bound = int(POLICY["max_consecutive_request_rejections"])
    rows = [_row(i) for i in range(1, 121)]
    store = {}
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, bound + 1))))
    first = _run(monkeypatch, ["--route", "cloud", "--limit", "120"], rows=rows, store=store)
    assert _running(first)[bound] == bound + 1, "the first probe is the next untried job, never the tail"
    assert sorted(_struck_ids(first)) == list(range(1, bound + 1)) and _counted_ids(first) == []
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, bound + 1))))
    second = _run(monkeypatch, ["--route", "cloud", "--limit", "120"], rows=rows, store=store)
    assert sorted(_counted_ids(second)) == list(range(1, bound + 1))


def test_all_400_systemic_ends_after_every_probe_is_rejected_and_charges_nobody(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    bound = int(POLICY["max_consecutive_request_rejections"])
    cap = int(POLICY["max_probes_per_run"])
    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_HTTP400))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=[_row(i) for i in range(1, 101)], store={})
    expected_probes = [bound + 1 + i for i in w.probe_positions(100 - bound, bound, cap)]
    assert _running(log) == list(range(1, bound + 1)) + expected_probes, "never burns the whole limit"
    assert 100 not in _running(log), "the tail is never the default probe"
    assert _counted_ids(log) == [] and _struck_ids(log) == []
    state = w.load_breaker(_isolated_breaker)
    assert not w.breaker_open(state, "outage") and state["no_progress"]["runs"] == 1


def test_a_rejected_first_probe_does_not_end_the_run(monkeypatch, _isolated_breaker):
    """Bad head and the first probe position bad too: a later probe answers, and the run drains (round 14)."""
    import lib.llm_fallback as lf

    bad = set(range(1, 12)) | {99, 100}
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(bad))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=[_row(i) for i in range(1, 101)], store={})
    assert sorted(_done(log)) == list(range(12, 99))


def test_after_answers_a_block_gets_a_single_probe(monkeypatch, _isolated_breaker):
    """Lanes answered earlier in this run: a systemic 400 burst costs the bound plus ONE probe."""
    import lib.llm_fallback as lf

    bound = int(POLICY["max_consecutive_request_rejections"])
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok"] * 5 + ["400"] * 200))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "60"], rows=[_row(i) for i in range(1, 61)], store={})
    assert len(_running(log)) == 5 + bound + 1
    assert "no_progress" not in w.load_breaker(_isolated_breaker)


def test_probes_disabled_by_config_end_the_run_at_the_bound(monkeypatch, _isolated_breaker):
    import importlib

    import lib.llm_fallback as lf

    bound = int(POLICY["max_consecutive_request_rejections"])
    for mod in {id(m): m for m in (dp, importlib.import_module("lib.llm_queue_drain_policy"))}.values():
        monkeypatch.setattr(mod, "load_policy", lambda *a, **k: dict(POLICY, max_probes_per_run=0))
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, 20))))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "50"], rows=[_row(i) for i in range(1, 51)], store={})
    assert len(_running(log)) == bound and _done(log) == []


def test_small_fetch_of_all_bad_jobs_records_no_progress(monkeypatch, _isolated_breaker):
    """--limit below the bound (or a run shrunk by a flap): the fetch runs out with rejections and no answer."""
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_HTTP400))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(i) for i in range(1, 6)], store={})
    assert w.load_breaker(_isolated_breaker)["no_progress"]["runs"] == 1
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(i) for i in range(1, 6)], store={})
    assert w.load_breaker(_isolated_breaker)["no_progress"]["runs"] == 2


def test_a_transient_outage_does_not_record_no_progress(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(i) for i in range(1, 6)], store={})
    assert "no_progress" not in w.load_breaker(_isolated_breaker)


def test_time_budget_cut_does_the_top_good_jobs_first(monkeypatch, _isolated_breaker):
    """60 s per call, 25-minute budget: B1-B10, then G11-G20 must be the first good jobs done."""
    import lib.llm_fallback as lf

    clock = {"t": 0.0}
    monkeypatch.setattr(w.time, "monotonic", lambda: clock["t"])
    bad = set(range(1, 11))

    def gen(prompt, **kw):
        clock["t"] += 60.0
        if int(prompt[3:]) in bad:
            raise _AllLanesFailed(list(_HTTP400))
        return _Res()

    monkeypatch.setattr(lf, "generate_with_fallback", gen)
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100", "--time-budget-min", "25"],
               rows=[_row(i) for i in range(1, 101)], store={})
    done = _done(log)
    assert set(range(11, 21)) <= set(done) and done[:10] == list(range(11, 21))


def test_stall_is_recorded_at_the_bound_and_cleared_when_the_probe_answers(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    state = w._fresh_breaker()
    state["no_progress"] = {"since": (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(), "runs": 13,
                            "reason": "grok: HTTPError: 400 Bad Request"}
    w.save_breaker(_isolated_breaker, state)
    sent = _pages(monkeypatch)
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, 13))))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "40"], rows=[_row(i) for i in range(1, 51)], store={})
    assert len(sent) == 1, "a 7 h stall is paged at the bound, before the probe"
    assert len(_done(log)) == 38 and "no_progress" not in w.load_breaker(_isolated_breaker)  # the fake ignores LIMIT



def test_an_old_stall_is_not_paged_when_this_run_had_answers_before_the_bound(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    bound = int(POLICY["max_consecutive_request_rejections"])
    state = w._fresh_breaker()
    state["no_progress"] = {"since": (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(), "runs": 4,
                            "reason": "x"}
    w.save_breaker(_isolated_breaker, state)
    sent = _pages(monkeypatch)
    monkeypatch.setattr(lf, "generate_with_fallback", _sequence_generator(["ok"] + ["400"] * (bound + 1)))
    _run(monkeypatch, ["--route", "cloud", "--limit", "30"], rows=[_row(i) for i in range(1, 31)], store={})
    assert sent == [], "answers in this run are progress: no stall page"
    assert "no_progress" not in w.load_breaker(_isolated_breaker)



def test_the_probe_budget_is_per_run(monkeypatch, _isolated_breaker):
    """A head block uses the run's probes; a second block later in the run gets none and ends the run."""
    import lib.llm_fallback as lf

    bad = set(range(1, 11)) | set(range(12, 22))
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(bad))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "100"], rows=[_row(i) for i in range(1, 101)], store={})
    assert _running(log) == list(range(1, 11)) + [11] + list(range(12, 22))


def test_a_rejection_then_a_transient_outage_records_no_progress_only_as_an_outage(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    seq = iter([_HTTP400, _CONN_REFUSED, _CONN_REFUSED, _CONN_REFUSED])

    def gen(prompt, **kw):
        raise _AllLanesFailed(list(next(seq)))

    monkeypatch.setattr(lf, "generate_with_fallback", gen)
    _run(monkeypatch, ["--route", "cloud", "--limit", "10"], rows=[_row(i) for i in range(1, 5)], store={})
    state = w.load_breaker(_isolated_breaker)
    assert w.breaker_open(state, "outage") and "no_progress" not in state


def test_a_single_transient_refusal_records_no_progress_never(monkeypatch, _isolated_breaker):
    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", _raise_all_failed(*_CONN_REFUSED))
    _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(1)], store={})
    assert "no_progress" not in w.load_breaker(_isolated_breaker)


# Round 15 (review of #2438/#2439): a blip at the start of every run must never charge good jobs.
def _blip_then_ok(n_bad, total=200):
    return _sequence_generator(["400"] * n_bad + ["ok"] * total)


def test_a_start_of_run_blip_on_every_run_never_charges_a_good_job(monkeypatch):
    """A proxy that 400s the first 8 calls of EVERY run; every job is good. Struck jobs used to stay at the head, so
    the next run's blip hit exactly the same jobs and a later answer confirmed it: their second strike."""
    import lib.llm_fallback as lf

    store, rows, counted = {}, [_row(i) for i in range(1, 41)], []
    for _ in range(6):
        monkeypatch.setattr(lf, "generate_with_fallback", _blip_then_ok(8))
        counted += _counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "40"], rows=rows, store=store))
    assert counted == []


def test_struck_jobs_run_right_after_the_runs_first_answer(monkeypatch):
    import lib.llm_fallback as lf

    stamp = datetime.now(timezone.utc).isoformat()
    store = {1: {w.STRIKE_KEY: stamp}, 2: {w.STRIKE_KEY: stamp}}
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set()))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(i) for i in range(1, 6)], store=store)
    assert _running(log) == [3, 1, 2, 4, 5]


def test_struck_jobs_wait_while_the_run_has_no_answer(monkeypatch):
    """Before the first answer a struck job is not tried: a blip that lasts the whole run never reaches it."""
    import lib.llm_fallback as lf

    stamp = datetime.now(timezone.utc).isoformat()
    store = {1: {w.STRIKE_KEY: stamp}}
    monkeypatch.setattr(lf, "generate_with_fallback", _blip_then_ok(50))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(i) for i in range(1, 5)], store=store)
    assert 1 not in _running(log) and _counted_ids(log) == []
    assert store[1][w.STRIKE_KEY] == stamp


def test_an_expired_strike_is_not_deferred(monkeypatch):
    import lib.llm_fallback as lf

    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set()))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(i) for i in range(1, 4)],
               store={1: {w.STRIKE_KEY: old}})
    assert _running(log) == [1, 2, 3]


def test_when_every_fetched_job_is_struck_they_run_in_order(monkeypatch):
    import lib.llm_fallback as lf

    stamp = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set()))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=[_row(i) for i in range(1, 4)],
               store={i: {w.STRIKE_KEY: stamp} for i in range(1, 4)})
    assert _running(log) == [1, 2, 3]


def test_a_bad_struck_job_is_still_charged_on_its_second_run(monkeypatch):
    """The deferral must not shield a really bad prompt: it runs after the first answer, is rejected, and the next
    answer confirms it -- charged on the second run, as before."""
    import lib.llm_fallback as lf

    store, rows = {}, [_row(i) for i in range(1, 6)]
    counted = []
    for _ in range(2):
        monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator({1}))
        counted += _counted_ids(_run(monkeypatch, ["--route", "cloud", "--limit", "5"], rows=rows, store=store))
    assert counted == [1]


def test_a_released_struck_block_longer_than_the_bound_does_not_end_the_run(monkeypatch):
    """12 struck jobs, all still bad, run right after the first answer. They are exempt from the request-rejection
    bound: after an answer only one probe is allowed, and it would land in the same block and end the run."""
    import lib.llm_fallback as lf

    stamp = datetime.now(timezone.utc).isoformat()
    store = {i: {w.STRIKE_KEY: stamp} for i in range(1, 13)}
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, 13))))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "40"], rows=[_row(i) for i in range(1, 41)], store=store)
    assert _running(log) == [13, *range(1, 11), 14, 11, 12, *range(15, 41)]
    assert sorted(_done(log)) == list(range(13, 41))


def test_struck_jobs_are_released_in_chunks_of_the_bound_each_behind_an_answer(monkeypatch):
    """24 struck jobs, all still bad: a chunk of at most the bound runs after each real answer, so every chunk is
    confirmed by the answer that follows it even when a time budget cuts the run short."""
    import lib.llm_fallback as lf

    bound = int(POLICY["max_consecutive_request_rejections"])
    stamp = datetime.now(timezone.utc).isoformat()
    store = {i: {w.STRIKE_KEY: stamp} for i in range(1, 25)}
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, 25))))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "60"], rows=[_row(i) for i in range(1, 61)], store=store)
    assert bound == 10
    assert _running(log)[:27] == [25, *range(1, 11), 26, *range(11, 21), 27, *range(21, 25)]
    assert sorted(_done(log)) == list(range(25, 61))


def test_a_bad_job_right_after_a_struck_chunk_does_not_end_the_run(monkeypatch):
    """The released chunk is exempt from the bound. Counted, its 10 rejections would trip the bound; after an answer
    only one probe is allowed, it would hit the next (bad) job, and the run would end as systemic."""
    import lib.llm_fallback as lf

    stamp = datetime.now(timezone.utc).isoformat()
    store = {i: {w.STRIKE_KEY: stamp} for i in range(1, 11)}
    monkeypatch.setattr(lf, "generate_with_fallback", _bad_ids_generator(set(range(1, 11)) | {12, 13}))
    log = _run(monkeypatch, ["--route", "cloud", "--limit", "30"], rows=[_row(i) for i in range(1, 31)], store=store)
    assert _running(log) == [11, *range(1, 11), *range(12, 31)]
    assert sorted(_done(log)) == [11, *range(14, 31)]
