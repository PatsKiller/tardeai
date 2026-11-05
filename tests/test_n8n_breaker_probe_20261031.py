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
    released = [
        {
            "lane_id": "lane",
            "opened_at": (NOW - timedelta(hours=30)).isoformat(),
            "released_at": "y",
            "released_by": CFG["released_by"],
            "open": False,
        }
    ]

    def runs(*states):
        return {"lane": [{"run_id": f"r{i}", "slot_key": "s1", "state": s} for i, s in enumerate(states)]}

    assert BP.decide(released, runs("RUN_DONE"), probing, CFG, NOW)[0]["action"] == "pass"
    bad = BP.decide(released, runs("RUN_FAILED"), probing, CFG, NOW)
    assert bad[0]["action"] == "fail" and bad[0]["consecutive"] == 3
    # a lock-skipped run still means the probe slot was requested: the gate closes; no verdict yet (round 2)
    assert BP.decide(released, runs("RUN_SKIPPED_LOCK"), probing, CFG, NOW)[0]["action"] == "gate"
    old = {"lane": {**probing["lane"], "probing_since": (NOW - timedelta(hours=7)).isoformat()}}
    assert BP.decide(released, {}, old, CFG, NOW)[0]["action"] == "timeout"
    st = BP.next_state(probing, bad[0], NOW)
    assert st["lane"]["probes"] == 1 and st["lane"]["probing_since"] is None
    assert BP.next_state(probing, BP.decide(released, runs("RUN_DONE"), probing, CFG, NOW)[0], NOW) == {}


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


def _run(led, lane, state, at, slot="slot-1"):
    led._conn.execute(
        "INSERT INTO runs (run_id, lane_id, mode, state, requested_at, finished_at, slot_key) VALUES (?,?,?,?,?,?,?)",
        (f"r-{state}-{at}", lane, "live", state, at, at, slot),
    )


def test_end_to_end_probe_then_fail_reopens_then_pass(env):
    root, led, sent, cfg_p = env
    store = LedgerRunStore(led)
    store.open_breaker("lane-a", 3, (datetime.now(timezone.utc) - timedelta(hours=30)).timestamp())
    assert cli.main(["--apply", "--config", str(cfg_p)]) == 0
    assert store.breaker("lane-a")["open"] is False  # released for the probe
    assert store.breaker("lane-a")["released_by"] == "auto:half_open_probe"
    assert sent and "probe" in sent[-1]["message"] and sent[-1]["message_class"] == CFG["message_class"]
    _run(led, "lane-a", "RUN_FAILED", (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat())
    assert cli.main(["--apply", "--config", str(cfg_p)]) == 0
    assert store.breaker("lane-a")["open"] is True  # re-opened at the first failure
    state = json.loads((root / CFG["state_rel"]).read_text())
    assert state["lane-a"]["probes"] == 1
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
    assert CFG["enabled"] is False and CFG["never_probe_extra"] == []
    for word in ("scalp", "sender", "secret", "deploy", "guard", "position", "paper", "broker", "stop", "execution"):
        assert word in BP.NEVER_PROBE
    assert BP.blocked("Tradeai-SCALP-feed", CFG)  # case-insensitive
    assert BP.blocked("x-broker", {**CFG, "never_probe_extra": []})  # config cannot remove the floor
    assert BP.blocked("my-lane", {**CFG, "never_probe_extra": ["my-"]}) and not BP.blocked("my-lane", CFG)
    assert BP.blocked("cio-ask-lifecycle", CFG, stage="canary") == "live canary lane"


# ---------------------------------------------------------------- review 2026-10-31 (BLOCK on #2379): regressions
def test_one_probe_per_tick_oldest_first():
    acts = {a["lane"]: a for a in BP.decide([_br("newer", 30), _br("oldest", 90), _br("mid", 60)], {}, {}, CFG, NOW)}
    assert acts["oldest"]["action"] == "probe"
    assert acts["mid"]["action"] == "wait" and acts["newer"]["action"] == "wait"


def test_operator_hold_and_another_actor_yield():
    assert BP.decide([_br("held", 90)], {}, {}, CFG, NOW, holds=["held"])[0]["action"] == "held"
    probing = {"lane": {"probes": 0, "probing_since": (NOW - timedelta(hours=1)).isoformat()}}
    by_operator = [
        {"lane_id": "lane", "opened_at": (NOW - timedelta(hours=30)).isoformat(), "released_by": "john", "open": False}
    ]
    assert BP.decide(by_operator, {}, probing, CFG, NOW)[0]["action"] == "yield"
    reopened = [
        {"lane_id": "lane", "opened_at": (NOW - timedelta(minutes=10)).isoformat(), "released_by": None, "open": True}
    ]
    assert BP.decide(reopened, {}, probing, CFG, NOW)[0]["action"] == "yield"


def test_judges_exactly_one_probe_slot():
    probing = {"lane": {"probes": 0, "probing_since": (NOW - timedelta(hours=1)).isoformat(), "consecutive": 3}}
    rel = [
        {
            "lane_id": "lane",
            "opened_at": (NOW - timedelta(hours=30)).isoformat(),
            "released_by": CFG["released_by"],
            "open": False,
        }
    ]
    runs = {"lane": [{"run_id": "a", "slot_key": "s1", "state": "RUN_REQUESTED"}]}
    assert BP.decide(rel, runs, probing, CFG, NOW)[0]["action"] == "gate"  # slot requested: close the gate now
    gate_at = (NOW - timedelta(minutes=5)).isoformat()
    gated = [{"lane_id": "lane", "opened_at": gate_at, "released_by": None, "open": True}]
    st = {"lane": {**probing["lane"], "gate_opened_at": gate_at}}
    runs = {
        "lane": [
            {"run_id": "a", "slot_key": "s1", "state": "RUN_SKIPPED_LOCK"},
            {"run_id": "b", "slot_key": "s2", "state": "RUN_DONE"},
        ]
    }  # a LATER slot never decides
    assert BP.decide(gated, runs, st, CFG, NOW)[0]["action"] == "wait"
    runs["lane"].insert(1, {"run_id": "c", "slot_key": "s1", "state": "RUN_DONE"})
    (p,) = BP.decide(gated, runs, st, CFG, NOW)
    assert p["action"] == "pass" and p["gated"] is True  # the CLI releases the gated breaker for good


def test_state_written_before_release_and_failed_action_receipted(env, monkeypatch):
    root, led, sent, cfg_p = env
    store = LedgerRunStore(led)
    store.open_breaker("lane-w", 3, (datetime.now(timezone.utc) - timedelta(hours=30)).timestamp())
    seen = {}

    def boom(self, lane, by, now):
        seen["state_at_release"] = json.loads((root / CFG["state_rel"]).read_text())
        raise RuntimeError("ledger busy")

    monkeypatch.setattr(LedgerRunStore, "release_breaker", boom)
    assert cli.main(["--apply", "--config", str(cfg_p)]) == 1
    assert seen["state_at_release"]["lane-w"]["probing_since"]  # written ahead of the release
    assert "lane-w" not in json.loads((root / CFG["state_rel"]).read_text())  # rolled back: nothing was released
    (rec,) = [json.loads(x) for x in (root / CFG["receipts_rel"]).read_text().splitlines()]
    assert rec["action"] == "probe" and rec["applied"] is False and "ledger busy" in rec["error"]


# ---------------------------------------------------------------- review round 2 (2026-10-31)
def test_yield_keeps_the_backoff():
    st = {"lane": {"probes": 2, "probing_since": NOW.isoformat()}}
    after = BP.next_state(st, {"lane": "lane", "action": "yield"}, NOW)
    assert after["lane"]["probes"] == 2 and after["lane"]["probing_since"] is None


def test_at_most_one_lane_probing_at_once():
    st = {"busy": {"probes": 0, "probing_since": NOW.isoformat()}}
    rows = [
        _br("other", 90),
        {
            "lane_id": "busy",
            "opened_at": (NOW - timedelta(hours=99)).isoformat(),
            "released_by": CFG["released_by"],
            "open": False,
        },
    ]
    acts = {a["lane"]: a for a in BP.decide(rows, {}, st, CFG, NOW)}
    assert acts["other"]["action"] == "wait" and "max_concurrent" in acts["other"]["why"]


def test_unreadable_holds_or_registry_fail_closed(tmp_path):
    assert BP.decide([_br("x", 90)], {}, {}, CFG, NOW, holds=None)[0]["why"] == "holds file unreadable"
    assert BP.decide([_br("x", 90)], {}, {}, CFG, NOW, stages=None)[0]["why"] == "lane registry unreadable"
    p = tmp_path / "holds.json"
    p.write_text("{not json")
    assert cli.read_holds(p) is None and cli.read_holds(tmp_path / "absent.json") == []


def test_end_to_end_gate_closes_after_the_first_slot_then_pass_reopens(env):
    root, led, sent, cfg_p = env
    store = LedgerRunStore(led)
    store.open_breaker("lane-g", 3, (datetime.now(timezone.utc) - timedelta(hours=30)).timestamp())
    assert cli.main(["--apply", "--config", str(cfg_p)]) == 0
    assert store.breaker("lane-g")["open"] is False  # probe released
    t = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    led._conn.execute(
        "INSERT INTO runs (run_id, lane_id, mode, state, requested_at, slot_key) VALUES (?,?,?,?,?,?)",
        ("r1", "lane-g", "live", "RUN_REQUESTED", t, "s1"),
    )
    assert cli.main(["--apply", "--config", str(cfg_p)]) == 0
    assert store.breaker("lane-g")["open"] is True  # gate: no second slot can start
    led._conn.execute("UPDATE runs SET state = 'RUN_DONE', finished_at = ? WHERE run_id = 'r1'", (t,))
    assert cli.main(["--apply", "--config", str(cfg_p)]) == 0
    assert store.breaker("lane-g")["open"] is False  # the one slot passed: released for good
    assert "lane-g" not in json.loads((root / CFG["state_rel"]).read_text())
    kinds = [json.loads(x)["action"] for x in (root / CFG["receipts_rel"]).read_text().splitlines()]
    assert kinds == ["probe", "gate", "pass"]


def test_unreadable_registry_returns_none(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "lane_registry.json").write_text("{broken")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    assert cli.lane_stages() is None  # fail closed: decide() then starts no probe
