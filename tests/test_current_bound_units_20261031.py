"""Post-promote restart of CURRENT-bound user units (AGENTS.md 28.1.0 §25.10): fail-closed filter, verify, receipt,
P1. Every reviewer-A/B failing input is a regression test here. Hermetic: fake systemctl and fake /proc cwd; the
shell tests run the REAL restart_root_frozen_units under ``set -euo pipefail`` with a fake systemctl on PATH.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from scripts.lib import current_bound_units as cbu  # noqa: E402

COVERS = ["scripts/current_bound_units.py", "scripts/lib/current_bound_units.py"]

BASE = "/rel"
LINK = f"{BASE}/CURRENT"
NEW = f"{BASE}/new-release"
OLD = f"{BASE}/old-release"
FRAG = str(cbu.USER_UNIT_DIR)


def u(wd=LINK, argv="/v/python x.py", pid=1, cwd=OLD, env="", frag=None, transient="no"):
    return {
        "WorkingDirectory": wd,
        "ExecStart": f"{{ path=/v/python ; argv[]={argv} ; }}",
        "MainPID": str(pid),
        "Environment": env,
        "EnvironmentFiles": "",
        "FragmentPath": frag if frag is not None else f"{FRAG}/unit.service",
        "Transient": transient,
        "_cwd": cwd,
    }


def units_fixture():
    return {
        "tradeai-ops-applier.service": u(pid=11),
        "grok-oauth-proxy.service": u(argv=f"/usr/bin/python3 {LINK}/scripts/grok_oauth_proxy.py", pid=12),
        "heartbeat-receiver.service": u(pid=13),
        "tradeai-health-agent.service": u(pid=14, cwd=NEW),
        "tradeai-n8n-run-executor.service": u(argv=f"/v/python {LINK}/scripts/n8n_run_executor.py", pid=15),
        "tradeai-telegram-callback-poller.service": u(pid=16),
        "portfolio-server.service": u(wd=NEW, pid=17, cwd=NEW),
        "tradeai-active-trader-motion.service": u(pid=18),
        "stoploss-watcher.service": u(pid=19),
        "random-new.service": u(pid=20),
        "exec-only.service": u(wd="/home/x", argv=f"/v/python {LINK}/scripts/x.py", pid=21, cwd="/home/x"),
        "env-only.service": u(wd="/home/x", env=f"APP_ROOT={LINK}", pid=22, cwd="/home/x"),
        "cwd-only.service": u(wd="/home/x", pid=23, cwd=OLD),
        "transient-run.service": u(pid=24, transient="yes"),
        "foreign-frag.service": u(pid=25, frag="/etc/systemd/user/foreign.service"),
        "curfoo.service": u(wd=f"{LINK}-foo", pid=26, cwd="/home/y"),
        "chatgpt-oauth-proxy.service": u(argv=f"/usr/bin/python3 {LINK}/scripts/broker_bridge.py", pid=27),
        "unrelated.service": u(wd="/home/x", pid=28, cwd="/home/x"),
    }


def fake_run(units):
    def run(cmd):
        if "list-units" in cmd:
            assert "--state=running" in cmd  # only running units are candidates
            return "\n".join(f"{n} loaded active running x" for n in units) + "\n"
        if "show" in cmd:
            props = units.get(cmd[-1], u(wd="/none", pid=0, cwd=""))
            return "\n".join(f"{k}={v}" for k, v in props.items() if not k.startswith("_")) + "\n"
        raise AssertionError(cmd)

    return run


def fake_cwd(units):
    by_pid = {int(v["MainPID"]): v["_cwd"] for v in units.values()}
    return lambda pid: by_pid.get(pid, "")


def _plan(units=None, **kw):
    units = units or units_fixture()
    kw.setdefault("is_open", False)
    kw.setdefault("extra_never", [])
    return cbu.plan(NEW, releases_base=BASE, run=fake_run(units), cwd_of=fake_cwd(units), **kw)


# ------------------------------------------------------------------ fail-closed decisions
def test_only_listed_units_restart_never_discovered_ones():
    p = _plan()
    assert set(p.restart) == {
        "grok-oauth-proxy.service",
        "heartbeat-receiver.service",
        "tradeai-health-agent.service",
        "tradeai-n8n-run-executor.service",
        "tradeai-telegram-callback-poller.service",
    }
    for name in ("random-new.service", "stoploss-watcher.service", "tradeai-active-trader-motion.service"):
        assert name in p.page_only, name


def test_ops_applier_and_portfolio_server_never_restart():
    p = _plan()
    assert "tradeai-ops-applier.service" in p.page_only
    assert "portfolio-server.service" in p.page_only


def test_callback_poller_page_only_while_any_session_open():
    p = _plan(is_open=True)
    assert "tradeai-telegram-callback-poller.service" in p.page_only
    assert "tradeai-health-agent.service" in p.restart


def test_market_open_window_and_holidays():
    et = cbu.ET
    td = lambda d: d.weekday() < 5  # noqa: E731
    assert cbu.market_open(datetime(2026, 11, 2, 4, 0, tzinfo=et), trading_day=td)
    assert cbu.market_open(datetime(2026, 11, 2, 19, 59, tzinfo=et), trading_day=td)
    assert not cbu.market_open(datetime(2026, 11, 2, 20, 0, tzinfo=et), trading_day=td)
    assert not cbu.market_open(datetime(2026, 11, 1, 12, 0, tzinfo=et), trading_day=td)  # Sunday
    assert not cbu.market_open(datetime(2026, 11, 26, 12, 0, tzinfo=et), trading_day=lambda d: False)


@pytest.mark.parametrize(
    "name",
    [
        "stoploss-watcher.service",
        "tradeai-gain-guardian.service",
        "holding-protection-advisor.service",
        "activetrader-motion.service",
        "tradeai-mbi-writer.service",
        "tradeai-2fa-relay.service",
        "bws-render.service",
        "render-env.service",
        "snaptrade-sync.service",
        "tradeai-kill-switch.service",
        "sizing-engine.service",
        "scalplive.service",
        "tradeai-secret-render.service",
        "tradeai-deploy-on-main.service",
        "tradeai-guard.service",
        "tradeai-dof-sql.service",
    ],
)
def test_hard_never_list_by_name(name):
    ok, reason = cbu.decide(
        name, argv="/v/python x.py", wd=LINK, env="", installed=True, current_link=LINK, is_market_open=False
    )
    assert not ok and reason.startswith("never:"), (name, reason)


def test_hard_never_matches_argv_and_paths_not_only_name():
    for argv in (f"/v/python {LINK}/scripts/active_trader/motion.py", f"/v/python {LINK}/scripts/brokers/x.py"):
        ok, reason = cbu.decide(
            "grok-oauth-proxy.service",
            argv=argv,
            wd=LINK,
            env="",
            installed=True,
            current_link=LINK,
            is_market_open=False,
        )
        assert not ok and reason.startswith("never:"), argv
    p = _plan()
    assert "chatgpt-oauth-proxy.service" in p.page_only  # argv names a broker bridge


def test_hard_never_applies_to_defaults_and_override_too():
    keep, refused = cbu.filter_units(
        ["tradeai-health-agent.service", "stoploss-watcher.service", "tradeai-ops-applier.service"],
        releases_base=BASE,
        run=fake_run(units_fixture()),
        is_open=False,
        extra_never=[],
    )
    assert keep == ["tradeai-health-agent.service"]
    assert set(refused) == {"stoploss-watcher.service", "tradeai-ops-applier.service"}


def test_extra_never_env_extends(monkeypatch):
    monkeypatch.setenv("TRADEAI_CURRENT_BOUND_EXTRA_NEVER", "heartbeat")
    p = _plan(extra_never=None)
    assert "heartbeat-receiver.service" in p.page_only
    assert cbu.extra_never_tokens() == ["heartbeat"]


def test_only_working_directory_binding_restarts():
    p = _plan()
    for name in ("exec-only.service", "env-only.service", "cwd-only.service"):
        assert name in p.page_only, name
    reasons = {x.name: x.reason for x in p.units}
    assert reasons["env-only.service"] == "not_working_directory_bound"


def test_transient_and_foreign_units_never_restart():
    units = units_fixture()
    units["tradeai-health-agent.service"] = u(pid=14, transient="yes")
    units["heartbeat-receiver.service"] = u(pid=13, frag="/etc/systemd/user/hb.service")
    p = _plan(units)
    assert "tradeai-health-agent.service" in p.page_only
    assert "heartbeat-receiver.service" in p.page_only


def test_full_path_match_current_foo_is_not_current():
    assert not cbu.path_names_current(f"{LINK}-foo", LINK)
    assert cbu.path_names_current(LINK, LINK)
    assert cbu.path_names_current(f"/v/python {LINK}/scripts/x.py", LINK)
    assert "curfoo.service" not in [x.name for x in _plan().units]


def test_restart_cap_is_a_circuit_breaker(monkeypatch):
    monkeypatch.setattr(cbu, "MAX_RESTARTS", 2)
    p = _plan()
    assert len(p.restart) == 2
    assert any(x.reason == "restart_cap_reached" for x in p.units)


def test_names_output_excludes_page_only(monkeypatch, capsys):
    import scripts.current_bound_units as cli

    units = units_fixture()
    orig = cli.cbu.plan
    monkeypatch.setattr(
        cli.cbu,
        "plan",
        lambda cur, **kw: orig(
            cur, releases_base=BASE, run=fake_run(units), cwd_of=fake_cwd(units), is_open=False, extra_never=[]
        ),
    )
    cli.main(["plan", "--current", NEW, "--names"])
    names = capsys.readouterr().out.split()
    assert "tradeai-ops-applier.service" not in names and "random-new.service" not in names
    assert "grok-oauth-proxy.service" in names


def test_run_survives_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("systemctl", 20)

    monkeypatch.setattr(cbu.subprocess, "run", boom)
    assert cbu._run(["systemctl"]) == ""


def test_verify_prefix_rule():
    units = {"a.service": u(pid=1, cwd=f"{NEW}/scripts"), "b.service": u(pid=2, cwd=OLD)}
    out = cbu.verify(NEW, ["a.service", "b.service"], run=fake_run(units), cwd_of=fake_cwd(units))
    assert out["a.service"]["ok"] and not out["b.service"]["ok"]


# ------------------------------------------------------------------ CLI verify (the judge): firing, receipt, P1
def _cli(monkeypatch, tmp_path, argv, sent, units=None, deliver=None):
    import scripts.current_bound_units as cli

    units = units or units_fixture()
    mod = cli.cbu
    op, ov = mod.plan, mod.verify
    monkeypatch.setattr(
        mod,
        "plan",
        lambda cur, **kw: op(
            cur, releases_base=BASE, run=fake_run(units), cwd_of=fake_cwd(units), is_open=False, extra_never=[]
        ),
    )
    monkeypatch.setattr(
        mod, "verify", lambda cur, names, **kw: ov(cur, names, run=fake_run(units), cwd_of=fake_cwd(units))
    )

    def fake_send(message, **kw):
        sent.append((message, kw))
        return True

    fake_send._tradeai_test_double = True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", fake_send)
    if deliver:
        monkeypatch.setattr(cli, "deliver", deliver)
    return cli.main(argv + (["--state-root", str(tmp_path)] if argv[0] == "verify" else []))


def test_firing_failed_restart_is_receipted_and_paged(monkeypatch, tmp_path):
    sent: list = []
    rc = _cli(
        monkeypatch,
        tmp_path,
        [
            "verify",
            "--current",
            NEW,
            "--restarted",
            "tradeai-health-agent.service",
            "--restart-failed",
            "grok-oauth-proxy.service",
        ],
        sent,
    )
    assert rc == 2
    rec = json.loads((tmp_path / "data/runtime/current_bound_units_last.json").read_text())
    assert rec["restart_failed"] == ["grok-oauth-proxy.service"]
    assert "grok-oauth-proxy.service" in rec["failed"] and rec["paged"] is True
    msg, kw = sent[0]
    assert "restart FAILED" in msg and kw["priority"] == "P1" and kw["producer"] == "deploy_current_bound_units"


def test_firing_stale_restarted_unit_pages(monkeypatch, tmp_path):
    sent: list = []
    rc = _cli(monkeypatch, tmp_path, ["verify", "--current", NEW, "--restarted", "heartbeat-receiver.service"], sent)
    assert rc == 2 and "heartbeat-receiver.service" in sent[0][0]


def test_rollback_page_says_rollback(monkeypatch, tmp_path):
    sent: list = []
    _cli(
        monkeypatch,
        tmp_path,
        ["verify", "--current", NEW, "--event", "rollback", "--restarted", "heartbeat-receiver.service"],
        sent,
    )
    assert "after rollback" in sent[0][0]


def test_page_body_is_stable_per_unit_per_day_no_release_name(monkeypatch, tmp_path):
    sent: list = []
    _cli(monkeypatch, tmp_path, ["verify", "--current", NEW, "--restarted", "tradeai-health-agent.service"], sent)
    _cli(
        monkeypatch,
        tmp_path,
        ["verify", "--current", f"{BASE}/newer-release", "--restarted", "tradeai-health-agent.service"],
        sent,
    )
    assert "new-release" not in sent[0][0] and "old-release" not in sent[0][0]
    assert sent[0][1]["dedupe_minutes"] == 1440


def test_dry_run_sends_nothing_writes_nothing(monkeypatch, tmp_path):
    sent: list = []
    _cli(
        monkeypatch,
        tmp_path,
        ["verify", "--current", NEW, "--restarted", "heartbeat-receiver.service", "--dry-run"],
        sent,
    )
    assert sent == [] and not (tmp_path / "data/runtime/current_bound_units_last.json").exists()


def test_page_failure_not_swallowed(monkeypatch, tmp_path):
    sent: list = []
    rc = _cli(
        monkeypatch,
        tmp_path,
        ["verify", "--current", NEW, "--restarted", "tradeai-health-agent.service"],
        sent,
        deliver=lambda m: (False, "RuntimeError: down"),
    )
    assert rc == 3
    assert json.loads((tmp_path / "data/runtime/current_bound_units_last.json").read_text())["page_error"]


# ------------------------------------------------------------------ the REAL bash function under set -euo pipefail
SH = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SH, re.M | re.S)
    assert m, name
    return m.group(0)


def _bash(
    tmp_path, *, override=None, plan_names="", filter_out=None, fail_restart="", cwd=NEW, py=True, event="promote"
):
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    log = tmp_path / "restarts"
    (fake / "systemctl").write_text(
        "#!/bin/bash\n"
        f'if [[ "$1 $2" == "--user restart" ]]; then echo "$3" >> "{log}"; [[ " {fail_restart} " == *" $3 "* ]] && exit 1; exit 0; fi\n'
        'if [[ "$*" == *"MainPID"* ]]; then echo 123; fi\nexit 0\n'
    )
    (fake / "sleep").write_text("#!/bin/bash\nexit 0\n")
    (fake / "readlink").write_text(f"#!/bin/bash\necho {cwd}\n")
    calls = tmp_path / "pycalls"
    pyf = tmp_path / "py"
    filt = "" if filter_out is None else filter_out
    pyf.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{calls}"\n'
        f'case "$2" in plan) echo "{plan_names}";; filter) '
        + (f'echo "{filt}";;' if filter_out is not None else 'shift 3; echo "$*";;')
        + " verify) exit 0;; esac\nexit 0\n"
    )
    for f in (*fake.iterdir(), pyf):
        f.chmod(0o755)
    pre = 'set -euo pipefail\nlog() { echo "LOG $*"; }\nROOT=/x\n'
    if py:
        pre += f"VENV_PYTHON={pyf}\n"
    script = (
        pre + _fn("restart_root_frozen_units") + f"restart_root_frozen_units {NEW} {event} && echo RC0 || echo RCNZ\n"
    )
    env = {"PATH": f"{fake}:/usr/bin:/bin"}
    if override is not None:
        env["TRADEAI_CURRENT_BOUND_UNITS"] = override
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, cwd=tmp_path)
    restarted = log.read_text().split() if log.exists() else []
    return r, restarted, (calls.read_text() if calls.exists() else "")


def test_bash_glob_override_cannot_expand(tmp_path):
    (tmp_path / "evil.service").write_text("")
    r, restarted, _ = _bash(tmp_path, override="*.service", py=False)
    assert "evil.service" not in restarted and restarted == []
    r, restarted, calls = _bash(tmp_path, override="*.service")  # filter echoes its input unchanged
    assert "evil.service" not in calls and "evil.service" not in restarted


def test_bash_override_goes_through_filter(tmp_path):
    r, restarted, calls = _bash(
        tmp_path,
        override="stoploss-watcher.service tradeai-health-agent.service",
        filter_out="tradeai-health-agent.service",
    )
    assert restarted == ["tradeai-health-agent.service"]
    assert "filter --units" in calls and "stoploss-watcher.service" in calls


def test_bash_without_python_restarts_only_literal_defaults(tmp_path):
    r, restarted, _ = _bash(tmp_path, override="tradeai-n8n-run-executor.service random.service", py=False)
    assert restarted == ["tradeai-n8n-run-executor.service"]


def test_bash_failed_restart_is_passed_to_verify_and_returns_nonzero(tmp_path):
    r, restarted, calls = _bash(
        tmp_path,
        filter_out="tradeai-health-agent.service grok-oauth-proxy.service",
        fail_restart="grok-oauth-proxy.service",
    )
    assert "RCNZ" in r.stdout
    verify = [ln for ln in calls.splitlines() if " verify " in f" {ln} "][0]
    assert "--restart-failed grok-oauth-proxy.service" in verify
    assert "--restarted tradeai-health-agent.service" in verify


def test_bash_subdirectory_cwd_counts_as_new_release(tmp_path):
    r, _, _ = _bash(tmp_path, filter_out="tradeai-health-agent.service", cwd=f"{NEW}/scripts")
    assert "RC0" in r.stdout


def test_bash_rollback_event_passed(tmp_path):
    _, _, calls = _bash(tmp_path, filter_out="tradeai-health-agent.service", event="rollback")
    assert "--event rollback" in calls


def test_bash_derived_names_join_candidates(tmp_path):
    _, _, calls = _bash(tmp_path, plan_names="grok-oauth-proxy.service")
    filt = [ln for ln in calls.splitlines() if " filter " in f" {ln} "][0]
    assert "grok-oauth-proxy.service" in filt and "tradeai-health-agent.service" in filt


def test_callers_are_non_fatal_and_after_health():
    for fn, arg in (("cmd_promote", "promote"), ("cmd_rollback", "rollback")):
        body = _fn(fn)
        assert body.index("health_check") < body.index("restart_root_frozen_units")
        line = [ln for ln in body.splitlines() if "restart_root_frozen_units" in ln][0]
        assert ("||" in line or line.strip().startswith("if !")) and arg in line, line


def test_literal_default_kept_for_parsers():
    fn = _fn("restart_root_frozen_units")
    line = [ln for ln in fn.splitlines() if "TRADEAI_CURRENT_BOUND_UNITS:-" in ln][0]
    for name in cbu.HISTORICAL_DEFAULTS:
        assert name in line, name
    m = re.search(r"TRADEAI_CURRENT_BOUND_UNITS:-([^}\"]*)", SH)
    assert m and "cio-governed-bridge.service" in m.group(1)


# ------------------------------------------------------------------ follow-up: hard safety under a harness
def test_harness_refuses_real_send_and_production_root_write(monkeypatch, tmp_path):
    """A reviewer harness once ran verify for real and paged the operator with fake data. Never again."""
    import scripts.current_bound_units as cli
    import telegram_alert

    realish = tmp_path / "trade-ai-releases" / "persistent-state"
    realish.mkdir(parents=True)
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(realish))
    called: list = []
    real = telegram_alert.send_telegram
    monkeypatch.setattr(telegram_alert, "send_telegram", real)  # the REAL sender stays in place

    def no_network(*a, **k):
        called.append(a)
        raise AssertionError("network reached")

    monkeypatch.setattr(telegram_alert, "_legacy_send", no_network, raising=False)
    units = units_fixture()
    op, ov = cli.cbu.plan, cli.cbu.verify
    monkeypatch.setattr(
        cli.cbu,
        "plan",
        lambda cur, **kw: op(
            cur, releases_base=BASE, run=fake_run(units), cwd_of=fake_cwd(units), is_open=False, extra_never=[]
        ),
    )
    monkeypatch.setattr(
        cli.cbu, "verify", lambda cur, names, **kw: ov(cur, names, run=fake_run(units), cwd_of=fake_cwd(units))
    )
    rc = cli.main(["verify", "--current", NEW, "--restarted", "heartbeat-receiver.service", "--json"])
    assert rc == 4  # the alarm itself was suppressed: distinct exit code
    assert called == []
    assert not any(realish.rglob("*")), "nothing may be written under the production state root"
    # the default root (TRADEAI_PERSISTENT_STATE_ROOT) is used when --state-root is absent
    assert cli._state_root(None) == realish
    ok, err = cli.deliver("x")
    assert ok is False and err.startswith("refused: TRADE_AI_CI")


def test_harness_allows_tmp_root_and_test_double(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    import scripts.current_bound_units as cli

    monkeypatch.delenv("TRADEAI_PERSISTENT_STATE_ROOT", raising=False)
    assert cli.write_refused(tmp_path / "scratch") is None
    assert cli.write_refused(cli.DEFAULT_STATE_ROOT) is not None
    monkeypatch.delenv("TRADE_AI_CI")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert cli.write_refused(cli.DEFAULT_STATE_ROOT) is None  # production run: allowed


def test_stale_unit_skipped_by_narrowed_override_still_pages(monkeypatch, tmp_path):
    sent: list = []
    # grok-oauth-proxy is restartable and stale, but this deploy's list did not include it
    rc = _cli(monkeypatch, tmp_path, ["verify", "--current", NEW, "--restarted", "tradeai-health-agent.service"], sent)
    assert rc == 0
    assert "grok-oauth-proxy.service" in sent[0][0] and "not_in_this_deploy_list" in sent[0][0]


@pytest.mark.parametrize(
    "name",
    [
        "tradeai-positions-sync.service",
        "stop-drift.service",
        "account-sync.service",
        "telegram-sender.service",
        "order-execution.service",
        "db-retention.service",
        "tradeai-agent-loop.service",
    ],
)
def test_23_14_word_tokens(name):
    ok, reason = cbu.decide(
        name, argv="/v/python x.py", wd=LINK, env="", installed=True, current_link=LINK, is_market_open=False
    )
    assert not ok and reason.startswith("never:"), (name, reason)


def test_word_tokens_are_components_not_substrings_and_skip_env_names():
    # trade-ai-releases path, a 'stopwatch' word and an env var NAME containing SENDER must not veto
    ok, reason = cbu.decide(
        "tradeai-health-agent.service",
        argv="/v/python "
        + "/".join(["", "srv", "trade-ai-releases", "portfolio-server", "CURRENT", "scripts", "stopwatch_agent.py"]),
        wd=LINK,
        env="COMMS_INBOUND_SENDER_ALLOWLIST=1",
        installed=True,
        current_link=LINK,
        is_market_open=False,
    )
    assert ok, reason


# ------------------------------------------------------------------ follow-up 2: the bypasses reviewer A found
def _real_sender_reached(monkeypatch):
    import telegram_alert

    reached: list = []

    def no_network(*a, **k):
        reached.append(a)
        raise AssertionError("real sender reached")

    # Stub the real sender's transport so a bypass is detected without any network.
    monkeypatch.setattr(telegram_alert, "_legacy_send", no_network, raising=False)
    monkeypatch.setattr(telegram_alert, "_intent_send", no_network, raising=False)
    return telegram_alert, reached


@pytest.mark.parametrize("kind", ["mock_wraps", "partial", "lambda", "scripts_module", "unmarked_mock"])
def test_wrapped_or_reexported_real_sender_is_refused(monkeypatch, kind):
    import functools
    from unittest import mock

    import scripts.current_bound_units as cli

    monkeypatch.setenv("TRADE_AI_CI", "1")
    ta, reached = _real_sender_reached(monkeypatch)
    real = ta.send_telegram
    if kind == "mock_wraps":
        wrapper = mock.Mock(wraps=real)
    elif kind == "partial":
        wrapper = functools.partial(real)
    elif kind == "lambda":
        wrapper = lambda m, **k: real(m, **k)  # noqa: E731
    elif kind == "unmarked_mock":
        wrapper = mock.Mock(return_value=True)  # auto-attributes are truthy; only an explicit marker counts
    else:
        import scripts.telegram_alert as sta

        wrapper = sta.send_telegram
    monkeypatch.setattr(ta, "send_telegram", wrapper)
    ok, err = cli.deliver("x")
    assert ok is False and err.startswith("refused"), kind
    assert reached == []


def test_marked_test_double_is_allowed(monkeypatch):
    import scripts.current_bound_units as cli
    import telegram_alert

    monkeypatch.setenv("TRADE_AI_CI", "1")
    calls = []

    def double(message, **kw):
        calls.append(message)
        return True

    double._tradeai_test_double = True
    monkeypatch.setattr(telegram_alert, "send_telegram", double)
    assert cli.deliver("x") == (True, None) and calls == ["x"]


def test_symlinked_runtime_dir_into_production_is_refused(monkeypatch, tmp_path):
    import scripts.current_bound_units as cli

    prod = tmp_path / "prod-state"
    (prod / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(prod))
    monkeypatch.setenv("TRADE_AI_CI", "1")
    scratch = tmp_path / "scratch"
    (scratch / "data").mkdir(parents=True)
    (scratch / "data" / "runtime").symlink_to(prod / "data" / "runtime")
    assert cli.write_refused(scratch) is not None
    # a plain scratch root with no symlink is fine
    plain = tmp_path / "plain"
    plain.mkdir()
    assert cli.write_refused(plain) is None


@pytest.mark.parametrize(
    "value,expect",
    [("1", True), ("true", True), ("TRUE", True), ("0", False), ("false", False), ("", False), ("yes", False)],
)
def test_harness_env_parsing_is_strict(monkeypatch, value, expect):
    import scripts.current_bound_units as cli

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TRADEAI_TEST_HARNESS", raising=False)
    monkeypatch.setenv("TRADE_AI_CI", value)
    assert (cli.harness_reason() is not None) is expect


def test_receipt_records_harness_reason(monkeypatch, tmp_path):
    sent: list = []
    _cli(monkeypatch, tmp_path, ["verify", "--current", NEW, "--restarted", "tradeai-health-agent.service"], sent)
    rec = json.loads((tmp_path / "data/runtime/current_bound_units_last.json").read_text())
    assert "harness_reason" in rec and rec["harness_reason"]


# ------------------------------------------------------------------ follow-up 3: reviewer B's should-fix notes
def test_parent_of_protected_root_is_refused(monkeypatch, tmp_path):
    import scripts.current_bound_units as cli

    prod = tmp_path / "releases" / "persistent-state"
    prod.mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(prod))
    monkeypatch.setenv("TRADE_AI_CI", "1")
    assert cli.write_refused(tmp_path / "releases") is not None  # root is a PARENT of the protected root


def test_force_variable_survives_and_ci_vars_do_not(monkeypatch):
    import scripts.current_bound_units as cli

    for v in ("TRADE_AI_CI", "TRADEAI_TEST_HARNESS", "PYTEST_CURRENT_TEST"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("TRADEAI_TEST_HARNESS_FORCE", "1")
    assert cli.harness_reason() == "TRADEAI_TEST_HARNESS_FORCE"


def test_deploy_strips_leaked_ci_vars_only_in_deploy_context(tmp_path):
    """Inside cmd_promote/cmd_rollback (CBU_DEPLOY_CONTEXT=1) leaked TRADE_AI_CI/TRADEAI_TEST_HARNESS are stripped;
    PYTEST_CURRENT_TEST never is."""
    _, _, calls = _bash_env(
        tmp_path,
        {"TRADE_AI_CI": "1", "TRADEAI_TEST_HARNESS": "1", "PYTEST_CURRENT_TEST": "x", "CBU_DEPLOY_CONTEXT": "1"},
    )
    verify = [ln for ln in calls.splitlines() if " verify " in f" {ln} "][0]
    assert "CI=<unset>" in verify and "HARNESS=<unset>" in verify and "PYT=x" in verify


def test_harness_sourcing_the_function_keeps_its_guard(tmp_path):
    """B-R4: a harness that sources restart_root_frozen_units outside a deploy must NOT have its guard stripped."""
    _, _, calls = _bash_env(tmp_path, {"TRADE_AI_CI": "1", "TRADEAI_TEST_HARNESS": "1", "PYTEST_CURRENT_TEST": "x"})
    verify = [ln for ln in calls.splitlines() if " verify " in f" {ln} "][0]
    assert "CI=1" in verify and "HARNESS=1" in verify and "PYT=x" in verify


def test_deploy_context_marker_is_set_in_promote_and_rollback():
    for fn in ("cmd_promote", "cmd_rollback"):
        assert "local CBU_DEPLOY_CONTEXT=1" in _fn(fn), fn


def _real_cli_harness(tmp_path, extra_env):
    """The REAL restart function and the REAL current_bound_units CLI, with an UNMARKED stub sender that records any
    call to a file (no network possible), a fake systemctl, and a real-looking scratch state root."""
    import os
    import sys

    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "systemctl").write_text(
        "#!/bin/bash\n"
        'if [[ "$1 $2" == "--user restart" ]]; then exit 0; fi\n'
        'if [[ "$*" == *"list-units"* ]]; then echo "stale-x.service loaded active running x"; exit 0; fi\n'
        f'if [[ "$*" == *" show "* ]]; then printf "WorkingDirectory={BASE}/CURRENT\\nExecStart=\\nMainPID=0\\n'
        f'Environment=\\nEnvironmentFiles=\\nFragmentPath=\\nTransient=no\\n"; exit 0; fi\n'
        "exit 0\n"
    )
    (fake / "sleep").write_text("#!/bin/bash\nexit 0\n")
    (fake / "readlink").write_text(f"#!/bin/bash\necho {OLD}\n")
    sends = tmp_path / "sends.log"
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    wrap = tmp_path / "wrap.py"
    wrap.write_text(
        "import runpy, sys, types\n"
        "m = types.ModuleType('telegram_alert')\n"
        "def send_telegram(message, **kw):\n"
        f"    open({str(sends)!r}, 'a').write(message + '\\n')\n"
        "    return True\n"
        "m.send_telegram = send_telegram  # UNMARKED on purpose: a harness must refuse it\n"
        "sys.modules['telegram_alert'] = m\n"
        "script = sys.argv[1]; sys.argv = sys.argv[1:]\n"
        "runpy.run_path(script, run_name='__main__')\n"
    )
    pyw = tmp_path / "pyw"
    pyw.write_text(f'#!/bin/bash\nexec {sys.executable} {wrap} "$@"\n')
    for f in (*fake.iterdir(), pyw):
        f.chmod(0o755)
    realish = tmp_path / "trade-ai-releases" / "persistent-state"
    realish.mkdir(parents=True, exist_ok=True)
    script = (
        f'set -euo pipefail\nlog() {{ echo "LOG $*"; }}\nROOT={ROOT}\nVENV_PYTHON={pyw}\n'
        + _fn("restart_root_frozen_units")
        + f"restart_root_frozen_units {NEW} promote || true\n"
    )
    env = {
        "PATH": f"{fake}:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "TRADEAI_PERSISTENT_STATE_ROOT": str(realish),
        "TRADEAI_RELEASES_BASE": BASE,
        "TRADEAI_CURRENT_BOUND_UNITS": "tradeai-health-agent.service",
        **extra_env,
    }
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, cwd=tmp_path)
    return r, (sends.read_text() if sends.exists() else ""), realish


def test_real_cli_under_ci_harness_never_sends_or_writes(tmp_path):
    """B-R4 regression: TRADE_AI_CI=1, no FORCE, real function + real CLI: no send, no receipt under the root."""
    r, sent, realish = _real_cli_harness(tmp_path, {"TRADE_AI_CI": "1"})
    assert sent == "", r.stdout + r.stderr
    assert not any(realish.rglob("*")), "nothing may be written under the real-looking state root"
    assert "REFUSED" in r.stdout or "refused" in r.stderr, r.stdout + r.stderr


def test_real_cli_in_deploy_context_keeps_pytest_guard(tmp_path):
    """Even inside a deploy context, PYTEST_CURRENT_TEST is never stripped, so a pytest run cannot page."""
    r, sent, realish = _real_cli_harness(
        tmp_path, {"TRADE_AI_CI": "1", "PYTEST_CURRENT_TEST": "t::x", "CBU_DEPLOY_CONTEXT": "1"}
    )
    assert sent == "", r.stdout + r.stderr
    assert not any(realish.rglob("*"))


def test_deploy_logs_error_on_refusal_exit_4(tmp_path):
    r, _, _ = _bash_env(tmp_path, {}, verify_rc=4)
    assert "ERROR current-bound verify REFUSED" in r.stdout


def test_override_replaces_the_list_no_union(tmp_path):
    r, restarted, calls = _bash_env(
        tmp_path, {"TRADEAI_CURRENT_BOUND_UNITS": "tradeai-health-agent.service"}, plan_names="grok-oauth-proxy.service"
    )
    assert " plan " not in f" {calls} "  # no union with the derived names
    assert restarted == ["tradeai-health-agent.service"]


def _bash_env(tmp_path, env_extra, *, plan_names="", verify_rc=0):
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    log = tmp_path / "restarts"
    (fake / "systemctl").write_text(
        "#!/bin/bash\n"
        f'if [[ "$1 $2" == "--user restart" ]]; then echo "$3" >> "{log}"; exit 0; fi\n'
        'if [[ "$*" == *"MainPID"* ]]; then echo 123; fi\nexit 0\n'
    )
    (fake / "sleep").write_text("#!/bin/bash\nexit 0\n")
    (fake / "readlink").write_text(f"#!/bin/bash\necho {NEW}\n")
    calls = tmp_path / "pycalls"
    pyf = tmp_path / "py"
    pyf.write_text(
        "#!/bin/bash\n"
        f'echo "$* CI=${{TRADE_AI_CI-<unset>}} HARNESS=${{TRADEAI_TEST_HARNESS-<unset>}} '
        f'PYT=${{PYTEST_CURRENT_TEST-<unset>}}" >> "{calls}"\n'
        f'case "$2" in plan) echo "{plan_names}";; filter) shift 3; echo "$*";; verify) exit {verify_rc};; esac\nexit 0\n'
    )
    for f in (*fake.iterdir(), pyf):
        f.chmod(0o755)
    script = (
        f'set -euo pipefail\nlog() {{ echo "LOG $*"; }}\nROOT=/x\nVENV_PYTHON={pyf}\n'
        + _fn("restart_root_frozen_units")
        + f"restart_root_frozen_units {NEW} promote && echo RC0 || echo RCNZ\n"
    )
    env = {"PATH": f"{fake}:/usr/bin:/bin", **env_extra}
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, cwd=tmp_path)
    restarted = log.read_text().split() if log.exists() else []
    return r, restarted, (calls.read_text() if calls.exists() else "")


def test_real_cli_positive_control_without_harness_reaches_the_stub(tmp_path):
    """Positive control: with no harness variable the same setup DOES call the (stub) sender and writes the
    receipt, so the two tests above prove the guard and not a broken harness."""
    r, sent, realish = _real_cli_harness(tmp_path, {})
    assert "RELEASE NOT REACHED" in sent, r.stdout + r.stderr
    assert (realish / "data/runtime/current_bound_units_last.json").exists()
