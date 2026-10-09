"""SYSTEM Telegram family vs the CIO interdict (2026-10-09).

C4 put the interdict at the lowest send layer keyed on CIO_TELEGRAM_INTERDICT
alone. The autonomy watchdog unit sets that flag for the CIO path AND
SYSTEM_TELEGRAM_ENABLED=1 for its own ops-bot family, so from 2026-09-19 every
SYSTEM heartbeat and health alert was refused (INTERDICTED_TEST_OR_FLAG).

These tests pin the scoped rule, hermetically (every HTTP layer stubbed, a
counter instead of a network, a tmp ledger root, the comms ledger stubbed):

* CIO / financial / general sends stay under CIO_TELEGRAM_INTERDICT.
* A SYSTEM_OPS send confirmed by the transport is under SYSTEM_TELEGRAM_INTERDICT.
* PYTEST_CURRENT_TEST interdicts everything.
* No other module, string, CIO token or CIO chat can claim SYSTEM_OPS.
* Heartbeat once per NY date; one alert per transition kind per NY date.
* The what-would-send dry run sends and records nothing.

This file imports telegram_transport to prove the interdict, so it is named in
check_telegram_chokepoint.APPROVED_TOOLING like the other interdict tests.
"""
from __future__ import annotations

import inspect
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("requests")

import telegram_transport as T  # noqa: E402
from scripts.lib.autonomy_watchdog import engine as E  # noqa: E402
from scripts.lib.autonomy_watchdog import telegram_system as TG  # noqa: E402
from scripts.lib.autonomy_watchdog.io import read_jsonl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OPS_TOKEN = "ops-token-test"
OPS_CHAT = "1001"
CIO_TOKEN = "cio-token-test"
CIO_CHAT = "2002"
# 13:00 UTC = 09:00 ET (EDT): after the 08:15 ET daily window.
DAY1 = datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)
DAY1_LATER = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)
DAY2 = datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc)


@pytest.fixture
def live_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The watchdog unit's env, minus pytest, with every send path stubbed."""
    (tmp_path / "data" / "cio").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("COMMS_EDITOR_MODE", "off")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", OPS_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", OPS_CHAT)
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", CIO_TOKEN)
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", CIO_CHAT)
    monkeypatch.setenv("SYSTEM_TELEGRAM_ENABLED", "1")
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "1")
    for k in ("SYSTEM_TELEGRAM_INTERDICT", "TRADE_AI_CI", "TELEGRAM_CIO_ALLOWLIST"):
        monkeypatch.delenv(k, raising=False)

    posts: list[dict] = []

    def fake_post(url, payload):
        posts.append({"url": url, "payload": dict(payload)})
        return {"ok": True, "result": {"message_id": 500 + len(posts)}}, 200

    def must_not_post(*_a, **_k):  # the requests-backed default poster
        posts.append({"url": "requests", "payload": {}})
        raise AssertionError("real HTTP layer reached")

    monkeypatch.setattr(TG, "_http_post", fake_post)
    monkeypatch.setattr(T, "_http_post", must_not_post)
    fake_alert = types.ModuleType("telegram_alert")
    fake_alert.record_operator_message = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "telegram_alert", fake_alert)
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    return {"root": tmp_path, "posts": posts, "env": env}


def _as_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove PYTEST_CURRENT_TEST for the call phase.

    pytest rewrites it when the call phase starts (after fixtures), so a fixture
    cannot do this; each test that must look like the unit calls it first.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


def _counting_post():
    calls: list[dict] = []

    def post(url, payload):
        calls.append(payload)
        return {"ok": True, "status_code": 200, "response": {"ok": True, "result": {"message_id": 9}}}

    return calls, post


# ── CIO / financial family still interdicted ──────────────────────────────────


def test_cio_family_still_interdicted_with_system_enabled(live_env, monkeypatch):
    _as_unit(monkeypatch)
    calls, post = _counting_post()
    r = T.deliver_text(token=CIO_TOKEN, chat_id=CIO_CHAT, text="CIO: BUY NVDA", post=post)
    assert r.get("interdicted") is True
    assert calls == []


def test_send_message_has_no_family_parameter():
    """The CIO wrapper and send_telegram reach the transport through send_message,
    which cannot carry a SYSTEM claim at all."""
    assert "family" not in inspect.signature(T.send_message).parameters
    assert "family" not in inspect.signature(T.send_document).parameters


def test_cio_module_claiming_system_family_stays_blocked(live_env, monkeypatch):
    """A financial/CIO module passing family=SYSTEM_OPS, with the ops token and chat
    and SYSTEM_TELEGRAM_ENABLED=1, is still under CIO_TELEGRAM_INTERDICT."""
    _as_unit(monkeypatch)
    from scripts.lib import cio_telegram_transport as cio_mod

    calls, post = _counting_post()
    g = dict(vars(cio_mod))
    g.update({"T": T, "post": post, "OPS_TOKEN": OPS_TOKEN, "OPS_CHAT": OPS_CHAT})
    exec(  # noqa: S102 — runs a call whose frame globals are the CIO module's
        "result = T.deliver_text(token=OPS_TOKEN, chat_id=OPS_CHAT, text='financial_action: BUY',"
        " post=post, family=T.SendFamily.SYSTEM_OPS)",
        g,
    )
    assert g["result"].get("interdicted") is True
    assert calls == []


# ── SYSTEM family delivered when enabled ──────────────────────────────────────


def test_system_heartbeat_delivered_when_enabled(live_env, monkeypatch):
    _as_unit(monkeypatch)
    out = TG.send_daily("heartbeat body", root=live_env["root"], env=live_env["env"], now=DAY1)
    assert out["ok"] is True, out
    assert out["message_id"] == 501
    assert len(live_env["posts"]) == 1
    p = live_env["posts"][0]
    assert p["payload"]["chat_id"] == OPS_CHAT
    assert "/bot" + OPS_TOKEN + "/" in p["url"]
    ledger = read_jsonl(live_env["root"] / "data" / "cio" / "system_telegram_sends.jsonl")
    assert ledger[-1]["ok"] is True and ledger[-1]["financial_action"] is False


def test_system_interdict_switch_governs_system_family(live_env, monkeypatch):
    """SYSTEM_TELEGRAM_INTERDICT in the process env stops the SYSTEM family at the
    transport even when the caller's env dict does not carry it."""
    _as_unit(monkeypatch)
    env = dict(live_env["env"])
    monkeypatch.setenv("SYSTEM_TELEGRAM_INTERDICT", "1")
    out = TG.send_system("x", identity="system-alert:2026-10-09:t", kind="t", root=live_env["root"], env=env)
    assert out["ok"] is False
    assert out["reason"] == "INTERDICTED_TEST_OR_FLAG"
    assert live_env["posts"] == []


def test_cio_interdict_off_does_not_unlock_system_interdict(live_env, monkeypatch):
    _as_unit(monkeypatch)
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "0")
    monkeypatch.setenv("SYSTEM_TELEGRAM_INTERDICT", "1")
    out = TG.send_system("x", identity="system-alert:2026-10-09:u", kind="u", root=live_env["root"],
                         env=dict(live_env["env"]))
    assert out["ok"] is False and live_env["posts"] == []


# ── pytest always interdicts ──────────────────────────────────────────────────


def test_pytest_always_interdicts_every_family(live_env, monkeypatch):
    _as_unit(monkeypatch)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x")
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "0")
    out = TG.send_system("x", identity="system-alert:2026-10-09:p", kind="p", root=live_env["root"],
                         env=dict(live_env["env"]))
    assert out["ok"] is False and live_env["posts"] == []
    calls, post = _counting_post()
    assert T.deliver_text(token=CIO_TOKEN, chat_id=CIO_CHAT, text="x", post=post).get("interdicted") is True
    assert calls == []
    assert T._blocked(T._SYSTEM_GRANT) is True and T._blocked(None) is True


# ── spoofing refused ──────────────────────────────────────────────────────────


def test_spoof_from_non_system_module_refused(live_env, monkeypatch):
    _as_unit(monkeypatch)
    calls, post = _counting_post()
    r = T.deliver_text(token=OPS_TOKEN, chat_id=OPS_CHAT, text="x", post=post, family=T.SendFamily.SYSTEM_OPS)
    assert r.get("interdicted") is True and calls == []


def test_spoof_with_string_family_refused(live_env, monkeypatch):
    _as_unit(monkeypatch)
    calls, post = _counting_post()
    for fam in ("system_ops", "SYSTEM_OPS", "TRADE_AI_SYSTEM"):
        r = T.deliver_text(token=OPS_TOKEN, chat_id=OPS_CHAT, text="x", post=post, family=fam)
        assert r.get("interdicted") is True
    assert calls == []


@pytest.mark.parametrize(
    "setup,reason",
    [
        ({"SYSTEM_TELEGRAM_ENABLED": None}, "system_telegram_not_enabled"),
        ({"SYSTEM_TELEGRAM_ENABLED": "0"}, "system_telegram_not_enabled"),
        ({"TELEGRAM_CIO_BOT_TOKEN": OPS_TOKEN}, "token_is_cio_bot"),
        ({"TELEGRAM_CIO_CHAT_IDS": OPS_CHAT}, "chat_is_cio_chat"),
        ({"TELEGRAM_CIO_ALLOWLIST": OPS_CHAT}, "chat_is_cio_chat"),
    ],
)
def test_system_module_cannot_send_as_system_into_cio_lane(live_env, monkeypatch, setup, reason):
    _as_unit(monkeypatch)
    for k, v in setup.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    grant, why = T._resolve_system_grant(
        T.SendFamily.SYSTEM_OPS, token=OPS_TOKEN, chat_id=OPS_CHAT, caller=TG.__name__)
    assert grant is None and why == reason
    out = TG.send_system("x", identity="system-alert:2026-10-09:s", kind="s", root=live_env["root"],
                         env=dict(os.environ))
    assert out["ok"] is False and live_env["posts"] == []


def test_grant_reasons(live_env, monkeypatch):
    _as_unit(monkeypatch)
    r = T._resolve_system_grant
    S = T.SendFamily.SYSTEM_OPS
    assert r(T.SendFamily.OPERATOR, token=OPS_TOKEN, chat_id=OPS_CHAT, caller=TG.__name__)[1] == "operator_family"
    assert r("system_ops", token=OPS_TOKEN, chat_id=OPS_CHAT, caller=TG.__name__)[1] == "family_not_typed"
    assert r(S, token=OPS_TOKEN, chat_id=OPS_CHAT, caller="scripts.lib.cio_telegram_transport")[1] == \
        "caller_not_system_module"
    assert r(S, token=CIO_TOKEN, chat_id=OPS_CHAT, caller=TG.__name__)[1] == "token_not_ops_bot"
    assert r(S, token=OPS_TOKEN, chat_id=CIO_CHAT, caller=TG.__name__)[1] == "chat_not_ops_chat"
    grant, why = r(S, token=OPS_TOKEN, chat_id=OPS_CHAT, caller=TG.__name__)
    assert grant is T._SYSTEM_GRANT and why == "granted"


def test_system_grant_and_family_claim_never_leave_their_modules():
    """Ratchet: the private grant stays in the transport, and only the SYSTEM
    sender passes family=SYSTEM_OPS."""
    allowed_claim = {"scripts/lib/autonomy_watchdog/telegram_system.py", "scripts/telegram_transport.py"}
    for folder in ("scripts", "apps"):
        for p in (ROOT / folder).rglob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            text = p.read_text(encoding="utf-8", errors="replace")
            if rel != "scripts/telegram_transport.py":
                assert "_SYSTEM_GRANT" not in text, rel
                assert "_grant=" not in text or "_deliver_text_raw" not in text, rel
            if rel not in allowed_claim:
                assert "SendFamily.SYSTEM_OPS" not in text, rel


# ── volume: heartbeat once per day, alerts once per transition kind per day ───


def test_heartbeat_once_per_day(live_env, monkeypatch):
    _as_unit(monkeypatch)
    root, env = live_env["root"], live_env["env"]
    for now in (DAY1, DAY1, DAY1_LATER):
        out = TG.send_daily("hb", root=root, env=env, now=now)
        assert out["ok"] is True
    assert len(live_env["posts"]) == 1
    TG.send_daily("hb", root=root, env=env, now=DAY2)
    assert len(live_env["posts"]) == 2


def test_failed_heartbeat_is_retried_then_stops(live_env, monkeypatch):
    _as_unit(monkeypatch)
    root, env = live_env["root"], live_env["env"]
    monkeypatch.setenv("SYSTEM_TELEGRAM_INTERDICT", "1")
    assert TG.send_daily("hb", root=root, env=env, now=DAY1)["ok"] is False
    monkeypatch.delenv("SYSTEM_TELEGRAM_INTERDICT")
    assert TG.send_daily("hb", root=root, env=env, now=DAY1)["ok"] is True
    assert TG.send_daily("hb", root=root, env=env, now=DAY1).get("deduped") is True
    assert len(live_env["posts"]) == 1


def _drive_cycles(monkeypatch, root, statuses, now=DAY1):
    """Run run_cycle once per release status with collectors stubbed."""
    def fake_receipt(_bundle, now=None):
        return {"generated_at": (now or DAY1).isoformat(), "overall": "X", "components": []}

    monkeypatch.setattr(E, "collect_all", lambda **_k: {})
    monkeypatch.setattr(E, "persist_receipt", lambda *_a, **_k: None)
    monkeypatch.setattr(E, "format_text", lambda _rec: "hb")
    outs = []
    for st in statuses:
        def br(_b, now=None, _st=st):
            r = fake_receipt(_b, now)
            r["components"] = [{"component": "release", "status": _st}]
            return r
        monkeypatch.setattr(E, "build_receipt", br)
        outs.append(E.run_cycle(root=root, now=now))
    return outs


def test_transition_alert_deduped_per_kind_per_day(live_env, monkeypatch):
    _as_unit(monkeypatch)
    outs = _drive_cycles(monkeypatch, live_env["root"],
                         ["HEALTHY", "DEGRADED", "HEALTHY", "DEGRADED", "HEALTHY", "DEGRADED"])
    assert all(o["ok"] for o in outs)
    texts = [p["payload"]["text"] for p in live_env["posts"]]
    alerts = [t for t in texts if t.startswith("TRADE AI SYSTEM ALERT")]
    assert alerts == ["TRADE AI SYSTEM ALERT\nrelease: HEALTHY -> DEGRADED"]
    assert texts.count("hb") == 1
    assert len(live_env["posts"]) == 2


def test_what_would_send_sends_and_records_nothing(live_env, monkeypatch):
    _as_unit(monkeypatch)
    root = live_env["root"]
    _drive_cycles(monkeypatch, root, ["HEALTHY"])
    n_posts = len(live_env["posts"])  # the heartbeat from the seeding cycle
    ledger = root / "data" / "cio" / "system_telegram_sends.jsonl"
    before = ledger.read_text(encoding="utf-8")

    def br(_b, now=None):
        return {"generated_at": DAY1.isoformat(), "overall": "DEGRADED",
                "components": [{"component": "release", "status": "DEGRADED"}]}
    monkeypatch.setattr(E, "build_receipt", br)
    out = E.run_cycle(root=root, now=DAY1, dry_run=True, send_telegram=False)
    assert len(live_env["posts"]) == n_posts
    assert ledger.read_text(encoding="utf-8") == before
    daily = out["telegram"]["daily"]
    assert daily["would_send"] is False and daily["reason"] == "deduped"
    (alert,) = out["telegram"]["alerts"]
    assert alert["would_send"] is True and alert["kind"] == "release_HEALTHY_to_DEGRADED"
    assert alert["transport_gate"]["governing_switch"] == "SYSTEM_TELEGRAM_INTERDICT"

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import autonomy_watchdog as CLI  # noqa: PLC0415
    text = CLI.format_would_send(out)
    assert "WOULD SEND] release_HEALTHY_to_DEGRADED" in text and "nothing sent" in text
    plan = CLI.would_send_plan(out)
    assert plan["would_send_count"] == 1 and plan["sent"] is False


def test_what_would_send_reports_interdict(live_env, monkeypatch):
    _as_unit(monkeypatch)
    monkeypatch.setenv("SYSTEM_TELEGRAM_INTERDICT", "1")
    out = TG.preview_daily("hb", root=live_env["root"], env=dict(live_env["env"]), now=DAY1)
    assert out["would_send"] is False and out["reason"] == "interdicted:SYSTEM_TELEGRAM_INTERDICT"
    early = TG.preview_daily("hb", root=live_env["root"], env=dict(live_env["env"]),
                             now=datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc))
    assert early["reason"] == "before_0815_et"
    assert live_env["posts"] == []
