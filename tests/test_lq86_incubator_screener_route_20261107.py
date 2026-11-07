"""A refused run says so once, at run level, and does not exit 0 — ten silent weeks is the bug.

LQ-20261107-86, 2026-11-07. ``incubator-llm-screener`` is a weekday 08:10 ET cron line. Its process is
registered ``default_mode: manual`` and ``llm_consumption._seed_registry`` rewrites ``llm_process_config.mode``
from that registry value on every process start, so ``llm_lane.generate`` refused every symbol with
``manual approval required for incubator_llm_screener (deepseek-flash)``. Measured live: 10/10 symbols refused per
run, ``incubator_universe.llm_screen_at`` max 2026-08-27 10:00 ET, ``llm_process_config.updated_at`` re-seeded
2026-11-07 09:32 ET — and through all of it the run wrote its log (the lane's declared output signal), printed
``Screened: 0``, and exited 0.

The old code had no run-level decision: it walked every candidate, logged the same warning ten times and returned
None. The new ``preflight()`` asks the governor once; a refusal is one line naming the gate and the operator
decision that would change it, the per-symbol loop is skipped, and the process exits ``EXIT_REFUSED``. The gate is
NOT bypassed: arming an LLM lane is an operator decision (AGENTS.md §17).

Hermetic: no DB, no network, no provider.
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


# ── fakes ────────────────────────────────────────────────────────────────────

class Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(" ".join(str(sql).split()))

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
        return [s for s in self.cur.sql if s.startswith("UPDATE")]


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


# ── preflight: one decision per run ─────────────────────────────────────────

def test_a_manual_mode_refusal_is_one_line_naming_the_gate(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": False, "reason": "manual_mode", "mode": "manual"})
    mode, refusal = ils.preflight()
    assert mode == ils.ROUTE_IN_PROCESS
    assert "manual_mode" in refusal
    assert "llm_process_registry.json" in refusal, "the refusal must name what would unblock it"


def test_an_allowed_lane_has_no_refusal(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": True, "reason": None, "mode": "automated"})
    assert ils.preflight() == (ils.ROUTE_IN_PROCESS, None)


def test_the_env_flag_wins_and_the_bridge_does_not_read_mode(monkeypatch):
    monkeypatch.setenv(ils.VIA_BRIDGE_ENV, "1")
    _governor(monkeypatch, {"allow": False, "reason": "manual_mode", "mode": "manual"})
    assert ils.preflight() == (ils.ROUTE_ENV, None)


def test_an_unreadable_governor_does_not_invent_a_refusal(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, None)
    assert ils.preflight() == (ils.ROUTE_UNKNOWN, None)


# ── main: the exit code and the log line, not just the loop ────────────────

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


def test_a_refused_run_does_not_screen_anything_and_exits_refused(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": False, "reason": "manual_mode", "mode": "manual"})
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        types.SimpleNamespace(send_telegram=lambda *a, **k: True))
    calls = []
    rc, conn = _run_main(monkeypatch, ["--run"], CANDIDATES,
                         lambda *a, **k: calls.append(a) or {"status": "error"})
    assert calls == [], "a refused run must not walk the candidates"
    assert rc == ils.EXIT_REFUSED
    assert conn.closed


def test_a_run_the_governor_allows_still_exits_clean(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": True, "reason": None, "mode": "automated"})
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        types.SimpleNamespace(send_telegram=lambda *a, **k: True))
    results = [{"symbol": s, "status": "screened", "verdict": "HOLD", "grade": "C", "confidence": 50}
               for s in ("AAA", "BBB", "CCC")]
    rc, _ = _run_main(monkeypatch, ["--run"], CANDIDATES, results)
    assert rc == 0


def test_an_allowed_run_that_screens_nothing_is_not_exit_zero(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)
    _governor(monkeypatch, {"allow": True, "reason": None, "mode": "automated"})
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        types.SimpleNamespace(send_telegram=lambda *a, **k: True))
    results = [{"symbol": s, "status": "error",
                "error": "manual approval required for incubator_llm_screener (deepseek-flash)"}
               for s in ("AAA", "BBB", "CCC")]
    rc, _ = _run_main(monkeypatch, ["--run"], CANDIDATES, results)
    assert rc == ils.EXIT_NO_SCREENS


def test_a_dry_run_neither_probes_the_governor_nor_calls_a_model(monkeypatch):
    monkeypatch.delenv(ils.VIA_BRIDGE_ENV, raising=False)

    def boom(*a, **k):
        raise AssertionError("a dry run must not ask the governor")

    monkeypatch.setattr(ils, "governor_decision", boom)
    seen = []

    def fake_screen(conn, candidate, dry_run=False, via_bridge=None):
        seen.append(dry_run)
        return {"symbol": candidate["symbol"], "status": "dry_run"}

    rc, _ = _run_main(monkeypatch, ["--dry-run"], CANDIDATES, fake_screen)
    assert seen == [True, True, True]
    assert rc == 0

    # …and the real screen_one returns before it reads enrichment or reaches a provider.
    def no_io(*a, **k):
        raise AssertionError("a dry run must not read enrichment data")

    monkeypatch.setattr(ils, "fetch_news", no_io)
    assert ils.screen_one(Conn(), dict(CANDIDATE), dry_run=True) == {
        "symbol": "AAA", "status": "dry_run"}


# ── screen_one still routes on the plan it is given ────────────────────────

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
    assert [c[0] for c in calls] == ["incubator_llm_screener"]
    assert len(conn.updates()) == 1, "the screen must be written"


def test_the_in_process_path_uses_the_deepseek_lane(monkeypatch):
    _no_enrichment(monkeypatch)
    generated = []

    def generate(prompt, *, lane, timeout, process_id):
        generated.append((lane, process_id))
        return json.dumps({"screen_grade": "C", "verdict": "HOLD", "confidence": 50})

    monkeypatch.setitem(sys.modules, "llm_lane", types.SimpleNamespace(generate=generate))
    monkeypatch.setattr(LBR, "require_text_via_bridge",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("bridge called")))
    out = ils.screen_one(Conn(), dict(CANDIDATE), via_bridge=False)
    assert out["status"] == "screened" and out["model"] == "deepseek-flash"
    assert generated == [("deepseek-flash", "incubator_llm_screener")]
