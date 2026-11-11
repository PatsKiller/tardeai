"""Release status gate, QA-GOLDEN-RULES E15 (LQ-20261107-1902): DEPLOYED / LIVE / VERIFIED computed from /proc.

Hermetic: a fake systemctl, a fake /proc cwd, a tmp releases directory with a real CURRENT symlink. Every unit,
release name and path is synthetic.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import current_bound_units as cbu  # noqa: E402
from scripts.lib import release_status as rsl  # noqa: E402
import scripts.release_status as cli  # noqa: E402

ET = ZoneInfo("America/New_York")
FRAG = str(cbu.USER_UNIT_DIR)
NIGHT = datetime(2026, 11, 11, 20, 5, tzinfo=ET)  # Wednesday 20:05 ET: loopback allowed, market closed
NOON = datetime(2026, 11, 11, 12, 0, tzinfo=ET)  # Wednesday noon: loopback forbidden, market open
SAT = datetime(2026, 11, 14, 12, 0, tzinfo=ET)


@pytest.fixture()
def rel(tmp_path):
    base = tmp_path / "releases"
    new = base / "aaaa111-synthetic-new"
    old = base / "bbbb222-synthetic-old"
    for d in (new, old):
        d.mkdir(parents=True)
    (new / "BUILD_SHA").write_text("aaaa111fffffffffffffffffffffffffffffffff\n")
    (base / "CURRENT").symlink_to(new)
    (base / "EXPECTED_RELEASE").write_text(str(new) + "\n")
    return {"base": base, "new": str(new), "old": str(old), "link": f"{base}/CURRENT"}


def unit(link, pid, cwd, argv="/v/python x.py"):
    return {
        "WorkingDirectory": link,
        "ExecStart": f"{{ path=/v/python ; argv[]={argv} ; }}",
        "MainPID": str(pid),
        "Environment": "",
        "EnvironmentFiles": "",
        "FragmentPath": f"{FRAG}/u.service",
        "Transient": "no",
        "_cwd": cwd,
    }


def world(rel, lag=(), unreadable=()):
    names = [
        "portfolio-server.service",
        "tradeai-health-agent.service",
        "tradeai-ops-applier.service",
        "tradeai-active-trader-motion.service",
        "tradeai-telegram-callback-poller.service",
    ]
    units = {}
    for i, n in enumerate(names, start=100):
        cwd = rel["old"] if n in lag else ("" if n in unreadable else rel["new"])
        units[n] = unit(rel["link"], i, cwd)
    # not intended services: other names bound to CURRENT (their own lists, their own receipt)
    units["grok-oauth-proxy.service"] = unit(rel["link"], 200, rel["old"])
    units["heartbeat-receiver.service"] = unit(rel["link"], 201, rel["old"])
    units["unrelated.service"] = unit("/home/x", 202, "/home/x")
    return units


def fake_run(units):
    def run(cmd):
        if "list-units" in cmd:
            return "\n".join(f"{n} loaded active running x" for n in units) + "\n"
        if "show" in cmd:
            props = units.get(cmd[-1], unit("/none", 0, ""))
            return "\n".join(f"{k}={v}" for k, v in props.items() if not k.startswith("_")) + "\n"
        raise AssertionError(cmd)

    return run


def fake_cwd(units):
    by_pid = {int(v["MainPID"]): v["_cwd"] for v in units.values()}
    return lambda pid: by_pid.get(pid, "")


def compute(rel, units, now=NIGHT, fetch=lambda url: {"ok": True}, **kw):
    return rsl.compute(
        releases_base=rel["base"], run=fake_run(units), cwd_of=fake_cwd(units), now=now,
        is_open=kw.pop("is_open", False), fetch=fetch, **kw,
    )


# ------------------------------------------------------------------------------------------------ the three words
def test_all_units_on_target_is_live_and_verified_when_probes_pass(rel):
    rs = compute(rel, world(rel))
    assert rs.status == rsl.VERIFIED
    assert rs.lagging == [] and rs.unknown == []
    assert {p.status for p in rs.probes} == {rsl.PASS}


def test_one_lagging_unit_is_deployed_not_live(rel):
    rs = compute(rel, world(rel, lag={"tradeai-ops-applier.service"}))
    assert rs.status == rsl.DEPLOYED
    assert rs.lagging == ["tradeai-ops-applier.service"]
    assert rs.probes == []  # no acceptance probe is run on a release that is not LIVE


def test_the_three_by_design_skips_hold_the_release_at_deployed(rel):
    lag = {"tradeai-ops-applier.service", "tradeai-active-trader-motion.service",
           "tradeai-telegram-callback-poller.service"}
    rs = compute(rel, world(rel, lag=lag), is_open=True)
    assert rs.status == rsl.DEPLOYED
    assert set(rs.lagging) == lag


def test_unreadable_cwd_is_unknown_and_never_counts_as_live(rel):
    rs = compute(rel, world(rel, unreadable={"tradeai-health-agent.service"}))
    assert rs.status == rsl.DEPLOYED
    assert rs.unknown == ["tradeai-health-agent.service"] and rs.lagging == []
    unit_row = next(u for u in rs.units if u.name == "tradeai-health-agent.service")
    assert unit_row.on_target is None and unit_row.restart_command


def test_units_outside_tradeai_and_portfolio_server_do_not_decide_the_status(rel):
    # grok-oauth-proxy and heartbeat-receiver sit on the OLD release in this world and must not matter.
    rs = compute(rel, world(rel))
    names = {u.name for u in rs.units}
    assert "grok-oauth-proxy.service" not in names and "heartbeat-receiver.service" not in names
    assert rs.status == rsl.VERIFIED


def test_no_current_symlink_is_undetermined(tmp_path):
    rs = rsl.compute(releases_base=tmp_path / "nothing", run=lambda c: "", now=NIGHT, is_open=False)
    assert rs.status == rsl.UNDETERMINED and "CURRENT" in rs.reason


def test_no_bound_units_is_undetermined_never_live(rel):
    rs = compute(rel, {})
    assert rs.status == rsl.UNDETERMINED


def test_a_dangling_current_is_undetermined(rel):
    link = rel["base"] / "CURRENT"
    link.unlink()
    link.symlink_to(rel["base"] / "gone")
    rs = compute(rel, world(rel))
    assert rs.status == rsl.UNDETERMINED


# ------------------------------------------------------------------------------------------------ restart lines
def test_each_lagging_unit_gets_the_exact_restart_line(rel):
    rs = compute(rel, world(rel, lag={"tradeai-ops-applier.service", "tradeai-health-agent.service"}))
    lines = {u.name: u.restart_command for u in rs.units}
    assert lines["tradeai-ops-applier.service"] == "systemctl --user restart tradeai-ops-applier.service"
    assert lines["tradeai-health-agent.service"] == "systemctl --user restart tradeai-health-agent.service"
    assert lines["portfolio-server.service"] == ""  # on target: no line
    out = rsl.human(rs)
    assert "systemctl --user restart tradeai-ops-applier.service" in out
    assert "systemctl --user restart portfolio-server.service" not in out


def test_callback_poller_carries_the_market_hours_caution(rel):
    rs = compute(rel, world(rel, lag={"tradeai-telegram-callback-poller.service"}), now=NOON, is_open=True)
    row = next(u for u in rs.units if u.name == "tradeai-telegram-callback-poller.service")
    assert row.restart_command == "systemctl --user restart tradeai-telegram-callback-poller.service"
    assert "MARKET-HOURS CAUTION" in row.note and "20:00 ET" in row.note
    assert row.action == "page_only"  # the activation's own rule (current_bound_units) is reused, not copied
    assert "MARKET-HOURS CAUTION" in rsl.human(rs)


def test_the_activation_rule_is_reused_not_duplicated():
    src = (ROOT / "scripts" / "lib" / "release_status.py").read_text()
    assert "current_bound_units" in src
    for literal in ("tradeai-health-agent.service", "grok-oauth-proxy.service"):
        assert literal not in src  # no copy of the restart lists
    assert "HISTORICAL_DEFAULTS" not in src and "PAGE_ONLY_NAMED" not in src


# ------------------------------------------------------------------------------------------------ the probes
def test_health_probe_never_runs_in_the_market_window_and_leaves_the_release_live(rel):
    calls = []
    rs = compute(rel, world(rel), now=NOON, fetch=lambda url: calls.append(url) or {"ok": True})
    assert calls == []  # AGENTS.md 28.8: not one loopback request 04:00-16:15 ET on a market day
    assert rs.status == rsl.LIVE  # a skipped probe is not a pass: unknown beats wrong
    assert next(p for p in rs.probes if p.name == "portfolio_health").status == rsl.SKIPPED


@pytest.mark.parametrize("now,allowed", [
    (datetime(2026, 11, 11, 3, 59, tzinfo=ET), True),
    (datetime(2026, 11, 11, 4, 0, tzinfo=ET), False),
    (datetime(2026, 11, 11, 16, 14, tzinfo=ET), False),
    (datetime(2026, 11, 11, 16, 15, tzinfo=ET), True),
    (SAT, True),
])
def test_loopback_window_boundaries(now, allowed):
    assert rsl.loopback_allowed(now) is allowed


def test_failed_health_probe_keeps_the_release_at_live(rel):
    rs = compute(rel, world(rel), fetch=lambda url: {"ok": False})
    assert rs.status == rsl.LIVE
    assert next(p for p in rs.probes if p.name == "portfolio_health").status == rsl.FAIL


def test_unreachable_health_endpoint_is_a_fail_not_an_exception(rel):
    def boom(url):
        raise OSError("refused")

    rs = compute(rel, world(rel), fetch=boom)
    assert rs.status == rsl.LIVE
    assert next(p for p in rs.probes if p.name == "portfolio_health").detail == "OSError"


def test_a_stale_expected_release_pin_blocks_verified(rel):
    (rel["base"] / "EXPECTED_RELEASE").write_text(rel["old"] + "\n")
    rs = compute(rel, world(rel))
    assert rs.status == rsl.LIVE
    assert next(p for p in rs.probes if p.name == "expected_release_pin").status == rsl.FAIL


def test_missing_build_sha_blocks_verified(rel):
    (Path(rel["new"]) / "BUILD_SHA").unlink()
    assert compute(rel, world(rel)).status == rsl.LIVE


def test_build_sha_must_match_the_release_name(rel):
    (Path(rel["new"]) / "BUILD_SHA").write_text("cccc333" + "0" * 33 + "\n")
    assert compute(rel, world(rel)).status == rsl.LIVE


def test_no_probes_requested_stops_at_live(rel):
    assert compute(rel, world(rel), run_probes=False).status == rsl.LIVE


# ------------------------------------------------------------------------------------------------ cli + alert
def test_exit_codes_and_log_line(rel):
    ok = compute(rel, world(rel))
    bad = compute(rel, world(rel, lag={"tradeai-ops-applier.service"}))
    assert cli.exit_code(ok) == 0 and cli.exit_code(bad) == 2
    assert cli.exit_code(rsl.ReleaseStatus()) == 3
    line = cli.log_line(bad)
    assert "DEPLOYED, not LIVE" in line and "tradeai-ops-applier.service" in line and "\n" not in line
    assert "VERIFIED" in cli.log_line(ok)


def test_json_output_is_complete(rel):
    d = compute(rel, world(rel, lag={"tradeai-ops-applier.service"})).to_dict()
    json.dumps(d)
    assert d["schema"] == "ReleaseStatus@v1" and d["status"] == "DEPLOYED"
    assert d["units"][0].keys() >= {"name", "pid", "cwd", "release", "on_target", "restart_command", "note"}


def test_alert_fires_when_not_live_and_carries_the_restart_lines(rel):
    sent = []
    rs = compute(rel, world(rel, lag={"tradeai-ops-applier.service", "tradeai-telegram-callback-poller.service"}))
    res = cli.escalate(rs, alert=lambda r, sig: sent.append(rsl.alert_text(r)) or True, recent=lambda sig: False)
    assert res["needed"] and res["sent"] and len(sent) == 1
    assert "systemctl --user restart tradeai-ops-applier.service" in sent[0]
    assert "systemctl --user restart tradeai-telegram-callback-poller.service" in sent[0]
    assert "MARKET-HOURS CAUTION" in sent[0]


def test_alert_does_not_fire_when_live_or_verified(rel):
    def never(*a):
        raise AssertionError("must not alert")

    for rs in (compute(rel, world(rel)), compute(rel, world(rel), now=NOON)):
        assert cli.escalate(rs, alert=never, recent=never)["needed"] is False


def test_alert_fires_when_undetermined(rel):
    sent = []
    res = cli.escalate(rsl.ReleaseStatus(reason="no CURRENT"), alert=lambda r, s: sent.append(1) or True,
                       recent=lambda s: False)
    assert res["sent"] and sent


def test_alert_is_deduplicated_per_signature_and_a_write_failure_is_reported(rel):
    rs = compute(rel, world(rel, lag={"tradeai-ops-applier.service"}))
    res = cli.escalate(rs, alert=lambda r, s: pytest.fail("duplicate page"), recent=lambda s: True)
    assert res["suppressed_cooldown"] and not res["sent"]

    def broken(r, s):
        raise RuntimeError("db down")

    res = cli.escalate(rs, alert=broken, recent=lambda s: False)
    assert res["error"] == "RuntimeError" and not res["sent"]


def test_signature_changes_with_the_lagging_set(rel):
    a = compute(rel, world(rel, lag={"tradeai-ops-applier.service"}))
    b = compute(rel, world(rel, lag={"tradeai-ops-applier.service", "tradeai-health-agent.service"}))
    assert cli.signature(a) != cli.signature(b)


# ------------------------------------------------------------------------------------------------ activation wiring
DEPLOY = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text()


def promote_body():
    m = re.search(r"^cmd_promote\(\) \{\n(.*?)^\}\n", DEPLOY, re.S | re.M)
    assert m, "cmd_promote not found"
    return m.group(1)


def test_promote_runs_release_status_after_the_restart_step_and_before_the_final_line():
    body = promote_body()
    restart = body.index("restart_root_frozen_units")
    status = body.index("release_status_step")
    final = body.index("PROMOTE OK release_status")
    assert restart < status < final


def test_promote_never_prints_live_unconditionally():
    body = promote_body()
    assert "PROMOTE OK live=" not in body  # the old unconditional word is gone
    assert "RELEASE_STATUS" in body


def test_release_status_step_is_report_only():
    m = re.search(r"^release_status_step\(\) \{\n(.*?)^\}\n", DEPLOY, re.S | re.M)
    assert m, "release_status_step not defined"
    step = m.group(1)
    assert "release_status.py" in step and "--log-line" in step
    assert "systemctl" not in step  # report only: no new restarts, no systemctl at all
    assert "|| true" in step or "|| rc=$?" in step  # a status read can never fail a promote that already activated


@pytest.mark.parametrize("printed,expected", [
    ("RELEASE r1 is DEPLOYED, not LIVE: tradeai-ops-applier.service still on another release", "DEPLOYED"),
    ("RELEASE r1 is LIVE: all 9 intended units run r1", "LIVE"),
    ("", "UNKNOWN"),
])
def test_shell_step_sets_the_word_and_never_fails_the_promote(tmp_path, printed, expected):
    """Run the REAL release_status_step under set -euo pipefail with a stub interpreter."""
    import subprocess

    m = re.search(r"^RELEASE_STATUS=\"UNKNOWN\"\nrelease_status_step\(\) \{\n.*?^\}\n", DEPLOY, re.S | re.M)
    assert m
    stub = tmp_path / "py"
    stub.write_text(f"#!/bin/bash\nprintf '%s' {json.dumps(printed)}\n[ -n {json.dumps(printed)} ] || exit 1\n")
    stub.chmod(0o755)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "release_status.py").write_text("")
    script = (f"set -euo pipefail\nlog() {{ echo \"LOG $*\"; }}\nROOT={tmp_path}\nVENV_PYTHON={stub}\n"
              f"{m.group(0)}\nrelease_status_step /x\necho WORD=$RELEASE_STATUS\n")
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert f"WORD={expected}" in out.stdout
