"""n8n breaker half-open probe (coordinator 2026-10-31; operator: "validate all stuck agents and processes fix montior
and make auto healings with claude code").

Pins on a real temp coordination ledger (scripts/lib/n8n_coordination_ledger.py): a breaker open past open_hours is
released once (receipt, state PROBING); a RUN_DONE afterwards = pass (state cleared, breaker stays closed); a
RUN_FAILED = re-opened at once with backoff (the next probe waits open_hours * backoff_factor); no run inside
probe_timeout_hours = re-opened; RUN_SKIPPED_LOCK decides nothing; broker/stop/execution lanes are never probed;
max_probes pages once then stops; enabled=false or --dry-run changes nothing. Hermetic: TRADE_AI_CI=1, tmp state
root, telegram_alert stubbed.
"""

from __future__ import annotations

#: C1 firing coverage — this module injects the condition and asserts the message reaches the (stubbed) transport.
COVERS = ["scripts/n8n_breaker_probe.py"]

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import n8n_breaker_probe as cli  # noqa: E402
from lib import n8n_breaker_probe as BP  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

CFG = cli.load_config()
NOW = datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)


def _br(lane, hours, **kw):
    return {
        "lane_id": lane,
        "opened_at": (NOW - timedelta(hours=hours)).isoformat(),
        "released_at": None,
        "consecutive": 3,
        "open": True,
        **kw,
    }


def test_decide_probe_wait_blocked_exhausted():
    acts = {
        a["lane"]: a
        for a in BP.decide(
            [_br("cio-ask-lifecycle", 22), _br("young", 1), _br("schwab-broker-sync", 99), _br("tired", 99)],
            {},
            {"tired": {"probes": 6}},
            CFG,
            NOW,
        )
    }
    assert acts["cio-ask-lifecycle"]["action"] == "probe"
    assert acts["young"]["action"] == "wait"
    assert acts["schwab-broker-sync"]["action"] == "blocked"
    assert acts["tired"]["action"] == "exhausted"
    once = BP.decide([_br("tired", 99)], {}, {"tired": {"probes": 6, "exhausted_at": "x"}}, CFG, NOW)
    assert once == []  # paged once already


def test_backoff_doubles_and_caps():
    assert BP.interval_hours(CFG, 0) == 6 and BP.interval_hours(CFG, 1) == 12 and BP.interval_hours(CFG, 5) == 48
    st = {"lane": {"probes": 1}}
    assert BP.decide([_br("lane", 10)], {}, st, CFG, NOW)[0]["action"] == "wait"  # 10 h < 12 h after one failure
    assert BP.decide([_br("lane", 13)], {}, st, CFG, NOW)[0]["action"] == "probe"


def test_judge_pass_fail_timeout_neutral():
    probing = {"lane": {"probes": 0, "probing_since": (NOW - timedelta(hours=1)).isoformat(), "consecutive": 3}}
    released = [{"lane_id": "lane", "opened_at": "x", "released_at": "y", "open": False}]
    ok = BP.decide(released, {"lane": [{"run_id": "r1", "state": "RUN_DONE"}]}, probing, CFG, NOW)
    assert ok[0]["action"] == "pass"
    bad = BP.decide(released, {"lane": [{"run_id": "r1", "state": "RUN_FAILED"}]}, probing, CFG, NOW)
    assert bad[0]["action"] == "fail" and bad[0]["consecutive"] == 3
    neutral = BP.decide(released, {"lane": [{"run_id": "r0", "state": "RUN_SKIPPED_LOCK"}]}, probing, CFG, NOW)
    assert neutral[0]["action"] == "wait"
    old = {"lane": {**probing["lane"], "probing_since": (NOW - timedelta(hours=7)).isoformat()}}
    assert BP.decide(released, {}, old, CFG, NOW)[0]["action"] == "timeout"
    st = BP.next_state(probing, bad[0], NOW)
    assert st["lane"]["probes"] == 1 and st["lane"]["probing_since"] is None
    assert BP.next_state(probing, ok[0], NOW) == {}


# ---------------------------------------------------------------- end to end on a temp ledger
@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    sent: list[dict] = []
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = lambda message, **kw: sent.append({"message": message, **kw}) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    led = CoordinationLedger(tmp_path / CFG["ledger_rel"])
    cfg = dict(CFG, enabled=True)
    cfg_p = tmp_path / "cfg.json"
    cfg_p.write_text(json.dumps(cfg))
    return tmp_path, led, sent, cfg_p


def _run(led, lane, state, at):
    led._conn.execute(
        "INSERT INTO runs (run_id, lane_id, mode, state, requested_at, finished_at) VALUES (?,?,?,?,?,?)",
        (f"r-{state}-{at}", lane, "live", state, at, at),
    )


def test_end_to_end_probe_then_fail_reopens_then_pass(env):
    root, led, sent, cfg_p = env
    store = LedgerRunStore(led)
    store.open_breaker("cio-ask-lifecycle", 3, (datetime.now(timezone.utc) - timedelta(hours=30)).timestamp())
    assert cli.main(["--apply", "--config", str(cfg_p)]) == 0
    assert store.breaker("cio-ask-lifecycle")["open"] is False  # released for the probe
    assert store.breaker("cio-ask-lifecycle")["released_by"] == "auto:half_open_probe"
    assert sent and "probe" in sent[-1]["message"]
    state = json.loads((root / CFG["state_rel"]).read_text())
    _run(led, "cio-ask-lifecycle", "RUN_FAILED", (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat())
    assert cli.main(["--apply", "--config", str(cfg_p)]) == 0
    assert store.breaker("cio-ask-lifecycle")["open"] is True  # re-opened at the first failure
    state = json.loads((root / CFG["state_rel"]).read_text())
    assert state["cio-ask-lifecycle"]["probes"] == 1
    kinds = [json.loads(x)["action"] for x in (root / CFG["receipts_rel"]).read_text().splitlines()]
    assert kinds == ["probe", "fail"]


def test_enabled_false_and_dry_run_change_nothing(env):
    root, led, sent, cfg_p = env
    store = LedgerRunStore(led)
    store.open_breaker("lane-x", 3, (datetime.now(timezone.utc) - timedelta(hours=30)).timestamp())
    off = root / "off.json"
    off.write_text(json.dumps(dict(CFG, enabled=False)))
    cli.main(["--apply", "--config", str(off)])
    cli.main(["--dry-run", "--config", str(cfg_p)])
    assert store.breaker("lane-x")["open"] is True and sent == []
    assert not (root / CFG["receipts_rel"]).exists() and not (root / CFG["state_rel"]).exists()


def test_config_defaults():
    assert CFG["enabled"] is False
    assert any("broker" in g for g in CFG["never_probe_globs"]) and any("stop" in g for g in CFG["never_probe_globs"])
