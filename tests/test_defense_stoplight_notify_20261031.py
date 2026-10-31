"""Inverse-hedge stoplight notifications (DSN-20261031-market-risk-engine P0-T7, design §11 item 4).

The desk ran SHADOW (notify=False) from 2026-07-18; PSQ went THESIS GREEN at 17:55 ET on 2026-10-29, the evening
before the selloff, and nothing was sent (RCA finding 4). The operator promoted the desk on 2026-10-31. Pins: a
listed transition reaches the (stubbed) transport with the policy's priority/dedupe/producer; unlisted transitions
and a disabled policy never send; a dry run renders and sends nothing; a transport failure surfaces on the result;
the card carries no behaviour word (MBI_BEHAVIOR = 0); the promote decision is recorded; the desk script routes
every send through the library and no longer imports the legacy helper. Hermetic: telegram_alert stubbed.
"""

from __future__ import annotations

#: C1 firing coverage — the tests below inject a THESIS GREEN transition and assert the card reaches the transport.
COVERS = ["scripts/lib/market_risk/stoplight_notify.py"]

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.market_risk import stoplight_notify as sn  # noqa: E402

CFG = sn.load_config()
NOW = datetime(2026, 10, 29, 21, 55, tzinfo=timezone.utc)  # 17:55 ET 10-29: the transition nobody heard about
THESIS_GREEN = {
    "inverse": "PSQ",
    "bench": "QQQ",
    "light": "THESIS",
    "state": "GREEN",
    "label": "HEDGE ELIGIBLE",
    "reason": "desk HEDGE card active for QQQ; book exposure over the materiality floor",
    "as_of": "2026-10-29",
}


@pytest.fixture
def transport(monkeypatch):
    calls: list[dict] = []

    def send_telegram(message, **kw):
        calls.append({"message": message, **kw})
        return True

    monkeypatch.setitem(sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=send_telegram))
    return calls


def test_policy_is_enabled_and_lists_the_three_transitions():
    assert CFG["enabled"] is True
    assert {(t["light"], t["state"]) for t in CFG["transitions"]} == {
        ("THESIS", "GREEN"),
        ("ENTRY", "GREEN"),
        ("EXIT", "RED"),
    }
    assert CFG["priority"] == "P2" and int(CFG["dedupe_minutes"]) > 0
    assert CFG["message_class"] == "market_risk"


def test_thesis_green_reaches_the_transport_with_policy_values(transport):
    r = sn.emit(THESIS_GREEN, cfg=CFG, dry_run=False, now=NOW)
    assert r["sent"] is True and r["accepted"] is True and r["error"] is None
    assert len(transport) == 1
    c = transport[0]
    assert c["priority"] == CFG["priority"]
    assert c["dedupe_minutes"] == int(CFG["dedupe_minutes"])
    assert c["producer"] == CFG["producer"]
    assert c["message_class"] == CFG["message_class"]
    assert "PSQ/QQQ" in c["message"] and "THESIS GREEN" in c["message"] and "HEDGE ELIGIBLE" in c["message"]
    assert "as_of 2026-10-29" in c["message"]


def test_entry_green_and_exit_red_send_amber_and_unlisted_do_not(transport):
    sn.emit({**THESIS_GREEN, "light": "ENTRY", "state": "GREEN", "label": "ENTER"}, cfg=CFG, dry_run=False, now=NOW)
    sn.emit({**THESIS_GREEN, "light": "EXIT", "state": "RED", "label": "EXIT"}, cfg=CFG, dry_run=False, now=NOW)
    assert len(transport) == 2
    for light, state in (("THESIS", "AMBER"), ("ENTRY", "RED"), ("MANAGE", "GREEN"), ("EXIT", "GREEN")):
        r = sn.emit({**THESIS_GREEN, "light": light, "state": state}, cfg=CFG, dry_run=False, now=NOW)
        assert r["sent"] is False and "message" not in r
    assert len(transport) == 2


def test_disabled_policy_never_sends(transport):
    r = sn.emit(THESIS_GREEN, cfg={**CFG, "enabled": False}, dry_run=False, now=NOW)
    assert r["sent"] is False and transport == []


def test_dry_run_renders_and_sends_nothing(transport, capsys):
    r = sn.emit(THESIS_GREEN, cfg=CFG, dry_run=True, now=NOW)
    assert r["sent"] is False and r["accepted"] is None and "THESIS GREEN" in r["message"]
    assert "DRY RUN would send P2" in capsys.readouterr().out
    assert transport == []


def test_transport_failure_is_surfaced_not_swallowed(monkeypatch, capsys):
    def boom(message, **kw):
        raise RuntimeError("telegram down")

    monkeypatch.setitem(sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=boom))
    r = sn.emit(THESIS_GREEN, cfg=CFG, dry_run=False, now=NOW)
    assert r["sent"] is True and r["accepted"] is False and "telegram down" in r["error"]
    assert "send failed" in capsys.readouterr().err


def test_card_is_advisory_only():
    msg = sn.render({**THESIS_GREEN, "_cfg_transitions": CFG["transitions"]}, "Thu 10-29 17:55 EDT")
    assert "no order, size or stop is implied" in msg
    body = "\n".join(line for line in msg.splitlines() if not line.startswith("Advisory.")).lower()
    for w in sn.BEHAVIOR_WORDS:  # the disclaimer names the words it forbids; the card body never does
        assert w not in body, w


def test_bad_policy_fails_closed(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"enabled": True, "priority": "P2"}), encoding="utf-8")
    with pytest.raises(sn.StoplightNotifyConfigError):
        sn.load_config(p)
    p.write_text(json.dumps({**CFG, "priority": "URGENT"}), encoding="utf-8")
    with pytest.raises(sn.StoplightNotifyConfigError):
        sn.load_config(p)


def test_promote_decision_is_recorded_with_the_operator_words():
    c = json.loads((ROOT / "config" / "promote_criteria.json").read_text(encoding="utf-8"))
    d = c["decisions"]["inverse_stoplight_telegram"]
    assert d["decision"] == "PROMOTE" and d["decided_by"] == "operator" and d["decided_at"] == "2026-10-31"
    assert "I approve everything" in d["operator_words"]
    assert any(a["entry"] == "inverse_stoplight_telegram" for a in c["amendments"])  # post-lock edits are amended


def test_desk_script_routes_through_the_library_only():
    src = (ROOT / "scripts" / "defense_inverse_stoplights.py").read_text(encoding="utf-8")
    assert "from options_lifecycle_alerts import _telegram" not in src
    assert "_telegram(" not in src
    assert "stoplight_notify" in src and '_should_notify(light, st["state"], ncfg)' in src
    assert "--dry-run" in src
