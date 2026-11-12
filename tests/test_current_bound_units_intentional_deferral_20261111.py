"""LQ-20261107-2082 (E21): the release verifier records every standing policy refusal as intentionally deferred and
never pages "RELEASE NOT REACHED" for it, while a genuinely stale unit still pages.

Synthetic only: ``cbu.plan`` / ``cbu.verify`` / ``cbu.market_open`` are stubbed, ``deliver`` raises if called, and
every receipt write is ``--dry-run``. No systemctl, no /proc, no Telegram, no email, no DB.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lib.current_bound_units as real_cbu  # noqa: E402
from lib import release_status as rsl  # noqa: E402

CURRENT = "/rel/new-20261111"
MOTION = "tradeai-active-trader-motion.service"
OPS = "tradeai-ops-applier.service"
POLLER = "tradeai-telegram-callback-poller.service"
HEALTH = "tradeai-health-agent.service"
NEWBIE = "tradeai-some-new-daemon.service"

MOTION_R = "never:active-trader"
OPS_R = "ops_applier_writes_grants_killswitch_stop"
POLLER_R = "approval_and_oauth_handler_market_open"

_ORIG = {k: getattr(real_cbu, k) for k in ("plan", "verify", "market_open")}


@pytest.fixture(autouse=True)
def _restore_cbu():
    yield
    for k, v in _ORIG.items():
        setattr(real_cbu, k, v)


def _load():
    path = Path(os.environ.get("CBU_UNDER_TEST", ROOT / "scripts" / "current_bound_units.py"))
    spec = importlib.util.spec_from_file_location("cbu_under_test_2082", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _unit(name, action, reason, stale=True):
    return real_cbu.Unit(name, f"{CURRENT}/old", "argv", 100, "/rel/old-release", stale, action, reason)


def _deferred_three(market_open):
    poller = _unit(POLLER, "page_only", POLLER_R) if market_open else _unit(POLLER, "restart", "historical_default")
    return [_unit(MOTION, "page_only", MOTION_R), _unit(OPS, "page_only", OPS_R), poller]


def _run(tmp_path, units, *, market_open, restarted=(), restart_failed=(), refused=(), as_json=False):
    mod = _load()
    plan = real_cbu.Plan(current=CURRENT, units=units)
    mod.cbu.plan = lambda current, **kw: plan
    mod.cbu.verify = lambda current, names: {n: {"ok": True, "pid": 1, "cwd": CURRENT} for n in names}
    mod.cbu.market_open = lambda *a, **k: market_open

    def no_send(msg):  # pragma: no cover - a send here is the bug
        raise AssertionError(f"deliver called (no send allowed): {msg[:80]}")

    mod.deliver = no_send
    argv = ["verify", "--current", CURRENT, "--event", "promote", "--dry-run", "--state-root", str(tmp_path),
            "--restarted", " ".join(restarted), "--restart-failed", " ".join(restart_failed),
            "--refused", " ".join(refused)]
    if as_json:
        argv.append("--json")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        rc = mod.main(argv)
    return rc, buf.getvalue()


def _receipt(text):
    start = text.rfind('{\n  "schema"')
    assert start >= 0, text
    return json.loads(text[start:])


def _names(entries):
    return [u["name"] for u in entries]


def test_a_all_three_deferred_market_open_pages_nothing(tmp_path):
    rc, out = _run(tmp_path, _deferred_three(True), market_open=True, as_json=True)
    r = _receipt(out)
    assert rc == 0
    assert _names(r["intentionally_deferred"]) == [MOTION, OPS, POLLER]
    assert _names(r["stale_page_only"]) == []
    assert _names(r["deferred_market_close"]) == [POLLER]
    assert {u["name"]: u["category"] for u in r["intentionally_deferred"]} == {
        MOTION: "hard_never", OPS: "page_only_named", POLLER: "market_hours"}
    assert all(u["restart_command"] == f"systemctl --user restart {u['name']}" for u in r["intentionally_deferred"])
    assert "RELEASE NOT REACHED" not in out

    rc2, human = _run(tmp_path, _deferred_three(True), market_open=True)
    assert rc2 == 0
    assert "Release activated" in human
    assert "0 services updated" in human
    assert "3 services intentionally deferred" in human
    assert f"Operator action required: systemctl --user restart {MOTION} {OPS} {POLLER}" in human
    assert f"  {POLLER}: only after 20:00 ET on trading days" in human
    assert "RELEASE NOT REACHED" not in human


def test_b_market_closed_poller_is_genuinely_stale_and_pages(tmp_path):
    rc, out = _run(tmp_path, _deferred_three(False), market_open=False)
    r = None
    rc2, j = _run(tmp_path, _deferred_three(False), market_open=False, as_json=True)
    r = _receipt(j)
    assert rc == 0 and rc2 == 0
    assert _names(r["intentionally_deferred"]) == [MOTION, OPS]
    assert _names(r["stale_page_only"]) == [POLLER]
    assert "RELEASE NOT REACHED" in out
    assert f"*{POLLER}*: on an old release, not restarted by the deploy (not_in_this_deploy_list)" in out
    assert "after the US session closes" not in out
    assert "Release NOT fully activated" in out
    assert "2 services intentionally deferred" in out
    assert f"Operator action required: systemctl --user restart {MOTION} {OPS}" in out


def test_c_nothing_stale_means_zero_deferred(tmp_path):
    units = [_unit(MOTION, "page_only", MOTION_R, stale=False), _unit(OPS, "page_only", OPS_R, stale=False),
             _unit(POLLER, "page_only", POLLER_R, stale=False)]
    rc, out = _run(tmp_path, units, market_open=True, restarted=[HEALTH, POLLER, OPS])
    r = _receipt(_run(tmp_path, units, market_open=True, restarted=[HEALTH, POLLER, OPS], as_json=True)[1])
    assert rc == 0
    assert r["intentionally_deferred"] == [] and r["stale_page_only"] == []
    assert "Release activated" in out
    assert "3 services updated" in out
    assert "0 services intentionally deferred" in out
    assert "Operator action required" not in out
    assert "RELEASE NOT REACHED" not in out


def test_d_a_real_stale_unit_still_pages_and_the_page_names_the_deferred(tmp_path):
    units = _deferred_three(True) + [_unit(HEALTH, "restart", "historical_default")]
    rc, out = _run(tmp_path, units, market_open=True)
    r = _receipt(_run(tmp_path, units, market_open=True, as_json=True)[1])
    assert rc == 0
    assert _names(r["intentionally_deferred"]) == [MOTION, OPS, POLLER]
    assert _names(r["stale_page_only"]) == [HEALTH]
    assert "RELEASE NOT REACHED" in out
    assert f"*{HEALTH}*: on an old release, not restarted by the deploy (not_in_this_deploy_list)" in out
    for name in (MOTION, OPS, POLLER):
        assert f"*{name}*" in out
    assert f"*{POLLER}*: held on the old release by the market-hours guard" in out
    assert "after the US session closes (20:00 ET)" in out


def test_e_no_policy_reason_is_not_deferred(tmp_path):
    units = _deferred_three(True) + [_unit(NEWBIE, "page_only", "not_on_restart_safe_list")]
    rc, out = _run(tmp_path, units, market_open=True)
    r = _receipt(_run(tmp_path, units, market_open=True, as_json=True)[1])
    assert rc == 0
    assert _names(r["stale_page_only"]) == [NEWBIE]
    assert _names(r["intentionally_deferred"]) == [MOTION, OPS, POLLER]
    assert "RELEASE NOT REACHED" in out and f"*{NEWBIE}*" in out


def test_f_only_the_poller_after_the_close_pages(tmp_path):
    units = [_unit(POLLER, "restart", "historical_default")]
    rc, out = _run(tmp_path, units, market_open=False)
    r = _receipt(_run(tmp_path, units, market_open=False, as_json=True)[1])
    assert rc == 0
    assert r["intentionally_deferred"] == []
    assert _names(r["stale_page_only"]) == [POLLER]
    assert "RELEASE NOT REACHED" in out


def test_g_units_passed_as_refused_are_not_recorded_twice(tmp_path):
    rc, out = _run(tmp_path, _deferred_three(True), market_open=True,
                   refused=[MOTION, OPS, POLLER], as_json=True)
    r = _receipt(out)
    assert rc == 0
    assert r["intentionally_deferred"] == [] and r["stale_page_only"] == []
    assert r["refused_market_busy"] == [MOTION, OPS, POLLER]
    assert "RELEASE NOT REACHED" not in out


def test_h_a_failed_restart_pages_but_deferrals_stay_recorded(tmp_path):
    units = _deferred_three(True)
    rc, out = _run(tmp_path, units, market_open=True, restart_failed=[HEALTH])
    r = _receipt(_run(tmp_path, units, market_open=True, restart_failed=[HEALTH], as_json=True)[1])
    assert rc == 2
    assert _names(r["intentionally_deferred"]) == [MOTION, OPS, POLLER]
    assert "RELEASE NOT REACHED" in out and f"*{HEALTH}*: restart FAILED" in out
    assert "Release NOT fully activated" in out
    assert f"Operator action required: systemctl --user restart {MOTION} {OPS} {POLLER}" in out


def test_i_hard_never_is_deferred_even_with_markets_closed(tmp_path):
    units = [_unit(MOTION, "page_only", MOTION_R)]
    rc, out = _run(tmp_path, units, market_open=False)
    r = _receipt(_run(tmp_path, units, market_open=False, as_json=True)[1])
    assert rc == 0
    assert _names(r["intentionally_deferred"]) == [MOTION]
    assert r["intentionally_deferred"][0]["category"] == "hard_never"
    assert r["intentionally_deferred"][0]["category"] != "market_hours"
    assert "RELEASE NOT REACHED" not in out
    assert "1 services intentionally deferred" in out
    assert "after the US session closes" not in out


def test_j_release_status_lag_lines_read_the_deferral(tmp_path):
    plan = real_cbu.Plan(current=CURRENT, units=_deferred_three(True) + [_unit(HEALTH, "restart", "historical_default")])
    units = rsl.build_units(plan, CURRENT, "/rel", is_market_open=True)
    by = {u.name: u for u in units}
    assert by[MOTION].deferred == "hard_never"
    assert by[OPS].deferred == "page_only_named"
    assert by[POLLER].deferred == "market_hours"
    assert by[HEALTH].on_target is False and by[HEALTH].deferred == ""
    rs = rsl.ReleaseStatus(status=rsl.DEPLOYED, target=CURRENT, target_name="new-20261111", units=units,
                           lagging=[u.name for u in units if u.on_target is False])
    human = rsl.human(rs)
    assert f"[LAG] {MOTION}" in human and "[intentionally deferred: hard_never; never:active-trader]" in human
    assert f"[LAG] {HEALTH}" in human and "intentionally deferred" not in human.split(f"[LAG] {HEALTH}")[1].splitlines()[0]
    alert = rsl.alert_text(rs)
    assert "intentionally deferred: never:active-trader" in alert
    assert f"{HEALTH}" in alert and alert.count("intentionally deferred") == 3
