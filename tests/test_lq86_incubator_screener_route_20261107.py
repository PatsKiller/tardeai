"""A refused run says so once, at run level, and does not exit 0 — ten silent weeks is the bug.

LQ-20261107-86, 2026-11-07. ``incubator-llm-screener`` is a weekday 08:10 ET cron line. Its process was
registered ``default_mode: manual`` and ``llm_consumption._seed_registry`` rewrites ``llm_process_config.mode``
from that registry value on every process start, so the in-process gate refused every symbol with
``manual approval required for incubator_llm_screener (deepseek-flash)``. Measured live: 10/10 symbols refused per
run, ``incubator_universe.llm_screen_at`` max 2026-08-27 10:00 ET, and through all of it the run wrote its log,
printed ``Screened: 0``, and exited 0.

Four things are fixed here and each has a test that fails on the old behaviour:

1. one run-level decision naming the gate (``preflight``), not ten identical per-symbol warnings;
2. the route the gate will actually take is reported, and the provider/model that ANSWERED is read from the gate's
   own provenance instead of the constant "deepseek-flash" written into ``incubator_universe.llm_screen_model``;
3. the lane's declared ``output_signal`` (``data/runtime/incubator-llm-screener_last.json``, json_key ``ok_at``) is
   written on every real exit — success, governor refusal and zero screens alike — and never from a dry run;
4. the registry arms the lane on the FREE promotional credit lane (bulk/Haiku) the operator chose on 2026-11-07,
   with the per-process caps untouched.

Hermetic: no real DB, no network, no provider, no write outside ``tmp_path``.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import incubator_llm_screener as ils   # noqa: E402
from lib import llm_bridge_route as LBR   # noqa: E402

RECEIPT = "incubator-llm-screener_last.json"


# ── fakes ────────────────────────────────────────────────────────────────────

class Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(str(sql).split()), params))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class Conn:
    def __init__(self):
        self.cur = Cur()
        self.commits = 0
        self.closed = False

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True

    def updates(self):
        return [(s, p) for s, p in self.cur.sql if s.startswith("UPDATE")]


CANDIDATE = {"symbol": "AAA", "latest_score": 55, "strategy_id": ""}
CANDIDATES = [dict(CANDIDATE, symbol=s) for s in ("AAA", "BBB", "CCC")]


def _no_enrichment(monkeypatch):
    for fn, value in (("fetch_news", []), ("fetch_social", []), ("fetch_technical", {})):
        monkeypatch.setattr(ils, fn, lambda conn, symbol, _v=value: _v)
    monkeypatch.setattr(ils, "build_screen_prompt", lambda *a, **k: "SCREEN PROMPT")
    monkeypatch.setitem(sys.modules, "web_news_fetcher",
                        types.SimpleNamespace(fetch_web_news=lambda *a, **k: []))
    monkeypatch.delenv("CLOUD_REVIEW", raising=False)


def _governor(monkeypatch, decision):
    monkeypatch.setattr(ils, "governor_decision", lambda *a, **k: decision)


def _allow(monkeypatch, label="anthropic promotional credit [bulk:claude-haiku-5-5]"):
    """An allowed run whose lane label is fixed: promo_route_label reads llm_process_config, so pin it (no DB)."""
    _governor(monkeypatch, {"allow": True, "reason": None, "mode": "automated"})
    monkeypatch.setattr(ils, "promo_route_label", lambda *a, **k: label)


def _state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return tmp_path / "data" / "runtime" / RECEIPT


# ── preflight: one decision per run ─────────────────────────────────────────

def test_a_manual_mode_refusal_is_one_line_naming_the_gate(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": False, "reason": "manual_mode", "mode": "manual"})
    route, refusal, label = ils.preflight()
    assert route == ils.ROUTE_IN_PROCESS
    assert "manual_mode" in refusal
    assert "llm_process_registry.json" in refusal, "the refusal must name what would unblock it"
    assert label == "", "a refused run has no serving lane to label"


def test_an_allowed_lane_has_no_refusal_and_names_the_credit_lane(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _allow(monkeypatch)
    route, refusal, label = ils.preflight()
    assert (route, refusal) == (ils.ROUTE_IN_PROCESS, None)
    assert label == "anthropic promotional credit [bulk:claude-haiku-5-5]"


def test_a_run_with_no_usable_credit_says_it_falls_to_paid_deepseek(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": True, "reason": None, "mode": "automated"})
    monkeypatch.setattr(ils, "promo_route_label", lambda *a, **k: "")
    _route, refusal, label = ils.preflight()
    assert refusal is None
    assert label == ils.paid_route_label()
    assert "deepseek" in label and "cap" in label


def test_the_env_flag_wins_and_the_bridge_does_not_read_mode(monkeypatch):
    monkeypatch.setenv(ils.VIA_BRIDGE_ENV, "1")
    _governor(monkeypatch, {"allow": False, "reason": "manual_mode", "mode": "manual"})
    route, refusal, label = ils.preflight()
    assert (route, refusal) == (ils.ROUTE_ENV, None)
    assert "bridge" in label


def test_an_unreadable_governor_does_not_invent_a_refusal(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, ils.UNREADABLE)
    route, refusal, label = ils.preflight()
    assert (route, refusal) == (ils.ROUTE_UNKNOWN, None)
    assert "unknown" in label


def test_an_unreadable_credit_book_is_reported_unknown_not_as_the_paid_lane(monkeypatch):
    """A policy that cannot be READ is an unknown route: claiming the paid DeepSeek lane would be a guess."""
    import lib.anthropic_routing as promo
    import lib.llm_consumption as lc

    monkeypatch.setattr(lc, "get_process_config", lambda _pid: {"registered": True})
    monkeypatch.setattr(promo, "active", lambda *a, **k: (_ for _ in ()).throw(OSError("book gone")))
    label = ils.promo_route_label()
    assert label == ils.ROUTE_LABEL_UNKNOWN
    assert label != ils.paid_route_label()


# ── main: the exit code, the receipt and the log line, not just the loop ────

def _run_main(monkeypatch, argv, candidates, screen_results=None, conn=None):
    conn = conn or Conn()
    monkeypatch.setattr(ils, "get_db", lambda: conn)
    monkeypatch.setattr(ils, "fetch_candidates", lambda c, limit=10: list(candidates))
    monkeypatch.setattr(sys, "argv", ["incubator_llm_screener.py"] + argv)
    if screen_results is not None:
        if callable(screen_results):
            monkeypatch.setattr(ils, "screen_one", screen_results)
        else:
            monkeypatch.setattr(ils, "screen_one", lambda *a, **k: dict(screen_results.pop(0)))
    return ils.main(), conn


def _telegram(monkeypatch):
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        types.SimpleNamespace(send_telegram=lambda *a, **k: True))


def test_a_refused_run_screens_nothing_exits_refused_and_writes_a_failed_receipt(monkeypatch, tmp_path):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": False, "reason": "manual_mode", "mode": "manual"})
    _telegram(monkeypatch)
    receipt = _state_root(monkeypatch, tmp_path)
    calls = []
    rc, conn = _run_main(monkeypatch, ["--run"], CANDIDATES,
                         lambda *a, **k: calls.append(a) or {"status": "error"})
    assert calls == [], "a refused run must not walk the candidates"
    assert rc == ils.EXIT_REFUSED
    assert conn.closed
    doc = json.loads(receipt.read_text())
    assert doc["lane_id"] == "incubator-llm-screener"
    assert doc["status"] == "failed" and doc["exit"] == ils.EXIT_REFUSED
    assert doc["ok_at"] is None, "a refused run must not advance the freshness key"
    assert doc["produced_count"] == 0 and doc["attempted_count"] == len(CANDIDATES)
    assert doc["empty_reason"] == "governor_refused"
    assert doc["skipped_reasons"] == {"governor_refused": len(CANDIDATES)}


def test_a_good_run_writes_an_ok_receipt_with_the_serving_providers(monkeypatch, tmp_path):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _allow(monkeypatch)
    _telegram(monkeypatch)
    receipt = _state_root(monkeypatch, tmp_path)
    results = [{"symbol": s, "status": "screened", "verdict": "HOLD", "grade": "C",
                "confidence": 50, "provider": "anthropic"} for s in ("AAA", "BBB", "CCC")]
    rc, _ = _run_main(monkeypatch, ["--run"], CANDIDATES, results)
    assert rc == 0
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "ok" and doc["ok_at"], "a real success advances ok_at"
    assert doc["schema"].endswith("@v2")
    assert doc["produced_count"] == 3 and doc["attempted_count"] == 3
    assert doc["summary"]["providers"] == {"anthropic": 3}
    assert doc["summary"]["screened"] == 3
    assert "promotional credit" in doc["summary"]["route"], "the receipt must name the lane that ran"


def test_an_allowed_run_that_screens_nothing_is_not_exit_zero_and_does_not_stay_green(monkeypatch, tmp_path):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _allow(monkeypatch)
    _telegram(monkeypatch)
    receipt = _state_root(monkeypatch, tmp_path)
    results = [{"symbol": s, "status": "error", "error": "COST_CAP_EXCEEDED: global cap"}
               for s in ("AAA", "BBB", "CCC")]
    rc, _ = _run_main(monkeypatch, ["--run"], CANDIDATES, results)
    assert rc == ils.EXIT_NO_SCREENS
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None
    assert doc["empty_reason"] == "no_screens"
    assert doc["skipped_reasons"] == {"screen_error": 3}


def test_an_unexpected_failure_writes_the_receipt_and_still_raises(monkeypatch, tmp_path):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    receipt = _state_root(monkeypatch, tmp_path)
    conn = Conn()
    monkeypatch.setattr(ils, "get_db", lambda: conn)
    monkeypatch.setattr(ils, "fetch_candidates",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    monkeypatch.setattr(sys, "argv", ["incubator_llm_screener.py", "--run"])
    try:
        ils.main()
    except RuntimeError:
        pass
    else:  # pragma: no cover - the exception must reach cron's exit path
        raise AssertionError("main must not swallow an unexpected failure")
    assert conn.closed
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "failed" and doc["error"] == "RuntimeError"
    assert doc["skipped_reasons"] == {"run_failed": 1}


def test_a_dry_run_writes_no_receipt_at_all(monkeypatch, tmp_path):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": True, "reason": None, "mode": "automated"})
    receipt = _state_root(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise AssertionError("a dry run must not ask the governor")

    monkeypatch.setattr(ils, "governor_decision", boom)

    # A dry run must not read enrichment either: the real screen_one returns before that point.
    def no_io(*a, **k):
        raise AssertionError("a dry run must not read enrichment data")

    monkeypatch.setattr(ils, "fetch_news", no_io)
    monkeypatch.setattr(ils, "fetch_social", no_io)
    monkeypatch.setattr(ils, "fetch_technical", no_io)

    rc, _ = _run_main(monkeypatch, ["--dry-run"], CANDIDATES)
    assert rc == 0
    assert not receipt.exists(), "a dry run may not write the lane's declared signal"
    assert ils.screen_one(Conn(), dict(CANDIDATE), dry_run=True) == {
        "symbol": "AAA", "status": "dry_run"}


# ── screen_one routes on the plan it is given, and records who answered ─────

def test_the_bridge_path_screens_without_touching_the_in_process_lane(monkeypatch):
    _no_enrichment(monkeypatch)
    monkeypatch.setitem(sys.modules, "llm_lane", types.SimpleNamespace(
        generate=lambda *a, **k: (_ for _ in ()).throw(AssertionError("in-process lane called"))))
    calls = []

    def fake_bridge(process_id, prompt, *, timeout_s=60.0, max_tokens=None, manual_trigger=False):
        calls.append((process_id, prompt))
        return json.dumps({"screen_grade": "B", "verdict": "PROMOTE", "confidence": 61, "reasoning": "r"})

    monkeypatch.setattr(LBR, "require_text_via_bridge", fake_bridge)
    conn = Conn()
    out = ils.screen_one(conn, dict(CANDIDATE), via_bridge=True)
    assert out["status"] == "screened" and out["model"] == "governed-bridge"
    assert out["provider"] == "cio_governed_bridge"
    assert [c[0] for c in calls] == ["incubator_llm_screener"]
    assert len(conn.updates()) == 1, "the screen must be written"


def _fake_gate(monkeypatch, text, provenance):
    import lib.llm_consumption as lc
    seen = []

    def gate(prompt, *, lane, process_id, task_summary=None, timeout=90, max_tokens=2048,
             return_provenance=False, **_kw):
        seen.append({"lane": lane, "process_id": process_id, "return_provenance": return_provenance})
        assert return_provenance is True, "the run cannot name its provider without provenance"
        return text, provenance

    monkeypatch.setattr(lc, "gate_and_generate", gate)
    return seen


def test_the_credit_lane_answers_and_the_row_says_the_model_that_did(monkeypatch):
    """The gate may serve the deepseek-flash lane with an Anthropic model; the row must not claim DeepSeek."""
    _no_enrichment(monkeypatch)
    seen = _fake_gate(monkeypatch,
                      json.dumps({"screen_grade": "A", "verdict": "PROMOTE", "confidence": 70}),
                      {"provider": "anthropic", "returned_model": "claude-haiku-5-5"})
    conn = Conn()
    out = ils.screen_one(conn, dict(CANDIDATE), via_bridge=False)
    assert seen == [{"lane": "deepseek-flash", "process_id": "incubator_llm_screener",
                     "return_provenance": True}]
    assert out["status"] == "screened"
    assert (out["provider"], out["model"]) == ("anthropic", "claude-haiku-5-5")
    written = conn.updates()[0][1]
    assert written[3] == "claude-haiku-5-5", f"llm_screen_model must be the answering model: {written[3]}"


def test_a_paid_deepseek_answer_is_recorded_as_deepseek(monkeypatch):
    _no_enrichment(monkeypatch)
    _fake_gate(monkeypatch, json.dumps({"screen_grade": "C", "verdict": "HOLD", "confidence": 50}),
               {"requested_model_id": "deepseek-flash", "returned_model": "deepseek-flash"})
    out = ils.screen_one(Conn(), dict(CANDIDATE), via_bridge=False)
    assert (out["provider"], out["model"]) == ("deepseek", "deepseek-flash")


def test_a_gate_with_no_provenance_says_unknown_not_deepseek(monkeypatch):
    _no_enrichment(monkeypatch)
    _fake_gate(monkeypatch, json.dumps({"screen_grade": "C", "verdict": "HOLD", "confidence": 50}), {})
    out = ils.screen_one(Conn(), dict(CANDIDATE), via_bridge=False)
    assert (out["provider"], out["model"]) == ("unknown", "unknown"), "never a guessed provider"


# ── the registry this lane runs on ─────────────────────────────────────────

def test_the_registry_arms_the_lane_on_the_free_credit_lane_with_caps_intact():
    """LQ-20261107-86 route: automated (so the governor allows the cron run) + anthropic_first + bulk tier.

    Fails on the old registry (``default_mode: manual``), which is what refused every symbol for ten weeks.
    """
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text())
    row = next(p for p in reg["processes"] if p["id"] == "incubator_llm_screener")
    assert row["default_mode"] == "automated"
    assert row.get("anthropic_first") is True, "the free credit lane must be tried before paid DeepSeek"
    assert row["daily_soft_cap"] == 30 and row["daily_cost_cap_usd"] == 0.1, "caps stay as the operator set them"

    credit = json.loads((ROOT / "config" / "anthropic_credit_policy.json").read_text())
    assert "incubator_llm_screener" in credit["bulk_processes"], "FAST must resolve to the bulk (Haiku) tier"
    assert credit["models"]["bulk"] == "claude-haiku-5-5"
    assert credit["enabled"] is True
