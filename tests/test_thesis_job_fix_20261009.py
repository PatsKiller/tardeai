"""Symbol-thesis job repair (operator 2026-10-09: "fix the thesis job").

In the 5 days to 2026-10-09 the acquisition ledger held 315 rows and 6 PUBLISHED. Causes and the fixes tested here:
- the same unchanged evidence BLOCKED hourly (AA 58x, AAP 55x) -> blocked_backoff skips it for 24h;
- outside the off-peak window synthesis was deferred to a queue that keeps no answer, and the provider dedupe then
  refused every later attempt (48 DEFERRED + 43 DEDUPE_SKIP) -> offpeak_wait leaves the request open, and a
  DEDUPE_SKIP releases the stale completion and asks once more;
- replies truncated at 1600 output tokens (17 parse:no_json_object) -> 3200, and an unusable answer is released.
Fakes only: no network, no LLM, no database.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_symbol_thesis_acquisition as acq  # noqa: E402
from scripts.lib import symbol_thesis_synthesis as syn  # noqa: E402

NOW = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
CAT = {"contradictory_n": 0, "structured_n": 38, "supporting_n": 0}


def _row(sym, status, hours_ago, catalog=CAT):
    return {"symbol": sym, "status": status, "catalog": catalog, "as_of": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_backoff_after_repeated_blocks_on_unchanged_evidence():
    ledger = [_row("AA", "BLOCKED", h) for h in (3, 2, 1)]
    assert acq.blocked_backoff(ledger, "AA", now=NOW).startswith("BACKOFF_BLOCKED")
    # new evidence (counts changed) -> retry
    changed = ledger[:-1] + [_row("AA", "BLOCKED", 1, {**CAT, "supporting_n": 2})]
    assert acq.blocked_backoff(changed, "AA", now=NOW) is None
    # a non-blocked outcome in the tail -> retry
    assert acq.blocked_backoff(ledger[:-1] + [_row("AA", "SYNTHESIS_FAILED", 1)], "AA", now=NOW) is None
    # older than the window -> retry
    assert acq.blocked_backoff([_row("AA", "BLOCKED", h) for h in (30, 29, 28)], "AA", now=NOW) is None
    assert acq.blocked_backoff(ledger, "AAP", now=NOW) is None


def test_backed_off_symbols_are_skipped_and_not_ledgered(tmp_path, monkeypatch):
    led = tmp_path / acq.LEDGER_REL
    led.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    led.write_text("".join(json.dumps({"symbol": "AA", "status": "BLOCKED", "catalog": CAT,
                                       "as_of": (now - timedelta(hours=h)).isoformat()}) + "\n" for h in (3, 2, 1)))
    calls = []
    monkeypatch.setattr(acq, "run_one", lambda sym, **k: calls.append(sym) or {"symbol": sym, "status": "BLOCKED"})
    out = acq.run(root=tmp_path, symbols=["AA", "HPE"], apply=True, max_llm=6)
    assert calls == ["HPE"]
    assert out["statuses"] == {"BACKOFF_BLOCKED": 1, "BLOCKED": 1}
    assert len(led.read_text().splitlines()) == 4               # only HPE's row was appended


def test_offpeak_wait_reports_deferral(monkeypatch):
    from scripts.lib import llm_deferral as ld

    class D:
        defer, reason, run_after = True, "OUTSIDE_OFFPEAK_WINDOW", NOW
    monkeypatch.setattr(ld, "evaluate", lambda pid, **k: D())
    import lib.llm_deferral as ld2
    monkeypatch.setattr(ld2, "evaluate", lambda pid, **k: D())
    assert acq.offpeak_wait().startswith("OUTSIDE_OFFPEAK_WINDOW")

    class N:
        defer, reason, run_after = False, "IN_OFFPEAK_WINDOW", None
    monkeypatch.setattr(ld2, "evaluate", lambda pid, **k: N())
    monkeypatch.setattr(ld, "evaluate", lambda pid, **k: N())
    assert acq.offpeak_wait() is None


def test_run_one_waits_instead_of_deferring():
    src = (ROOT / "scripts/run_symbol_thesis_acquisition.py").read_text(encoding="utf-8")
    wait_at = src.index("wait = offpeak_wait()")
    assert wait_at < src.index("synth = synthesize_thesis_via_flash(")
    assert 'out["status"] = "WAITING_FOR_OFFPEAK"' in src


def _flash_stub(monkeypatch, responses, released):
    import scripts.lib.agent_flash_governance as g

    seq = iter(responses)
    monkeypatch.setattr(g, "governed_flash_call", lambda *a, **k: next(seq))
    monkeypatch.setattr(g, "release_completed", lambda key: released.append(key) or True)
    monkeypatch.setattr(syn, "_build_flash_synthesis_prompt", lambda s, p: "prompt")


PACKET = {"gate": "READY_FOR_SYNTHESIS", "packet_id": "pk1"}
GOOD = json.dumps({"summary": "A sufficiently long thesis summary that clears the forty character floor.",
                   "stance": "WATCH"})


def test_dedupe_skip_releases_and_retries_once(monkeypatch):
    released = []
    _flash_stub(monkeypatch, [
        {"success": False, "error": "DEDUPE_SKIP: identical evidence already answered", "evidence_hash": "ek1"},
        {"success": True, "response": GOOD, "evidence_hash": "ek1", "model_used": "deepseek-flash"},
    ], released)
    out = syn.synthesize_thesis_via_flash("HPE", PACKET, call_llm=True)
    assert out["ok"] is True and released == ["ek1"]


def test_truncated_reply_is_released_not_left_poisoned(monkeypatch):
    released = []
    _flash_stub(monkeypatch, [{"success": True, "response": '{"summary": "HPE\'s central gap is now', "evidence_hash": "ek2"}],
                released)
    out = syn.synthesize_thesis_via_flash("HPE", PACKET, call_llm=True)
    assert out["ok"] is False and out["error"] == "parse:no_json_object" and released == ["ek2"]


def test_output_budget_and_run_budget_raised():
    import inspect

    assert inspect.signature(syn.synthesize_thesis_via_flash).parameters["max_tokens"].default == 3200
    reg = json.loads((ROOT / "config/llm_process_registry.json").read_text(encoding="utf-8"))
    proc = next(p for p in reg["processes"] if p["id"] == "watchlist_steph_flash_narrative")
    assert proc["max_output_tokens"] == 3200 and proc["daily_cost_cap_usd"] == 1.0
    sh = (ROOT / "scripts/run_governed_symbol_thesis_acquisition.sh").read_text(encoding="utf-8")
    assert 'MAX_LLM="${TRADEAI_GOVERNED_THESIS_MAX_LLM:-6}"' in sh
    assert 'TIMEOUT_SEC="${TRADEAI_GOVERNED_THESIS_TIMEOUT_SEC:-900}"' in sh
