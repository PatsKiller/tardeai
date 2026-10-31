"""Post-promote restart of CURRENT-bound user units: derive the list, keep the never-list, verify, receipt, page P1.

2026-10-31: tradeai-ops-applier, grok/chatgpt-oauth-proxy and heartbeat-receiver stayed on old releases after
promotes because the deploy restarted a fixed list. Hermetic: fake systemctl runner and fake /proc cwd.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from scripts.lib import current_bound_units as cbu  # noqa: E402

COVERS = ["scripts/current_bound_units.py"]

BASE = "/rel"
NEW = f"{BASE}/new-release"
OLD = f"{BASE}/old-release"

UNITS = {
    # name: (WorkingDirectory, ExecStart, pid, cwd)
    "tradeai-ops-applier.service": (f"{BASE}/CURRENT", "{ path=/v/python ; argv[]=/v/python x }", 11, OLD),
    "grok-oauth-proxy.service": (f"{BASE}/CURRENT", "{ path=/usr/bin/python3 }", 12, OLD),
    "tradeai-health-agent.service": (f"{BASE}/CURRENT", "{ path=/v/python }", 13, NEW),
    "portfolio-server.service": (NEW, "{ path=/v/python }", 14, NEW),
    "tradeai-active-trader-motion.service": (f"{BASE}/CURRENT", "{ path=/v/python }", 15, OLD),
    "tradeai-scalp-live.service": (f"{BASE}/CURRENT", "{ path=/v/python }", 16, OLD),
    "Tradeai-Telegram-Sender.service": (f"{BASE}/CURRENT", "{ path=/v/python }", 17, OLD),
    "unrelated.service": ("/home/x", "{ path=/usr/bin/foo }", 18, "/home/x"),
    "exec-bound.service": (
        "/home/x",
        f"{{ path=/v/python ; argv[]=/v/python {BASE}/CURRENT/scripts/x.py }}",
        19,
        "/home/x",
    ),
}


def fake_run(units=UNITS):
    def run(cmd):
        if "list-units" in cmd:
            return "\n".join(f"{n} loaded active running x" for n in units) + "\n"
        if "show" in cmd:
            wd, ex, pid, _ = units[cmd[-1]]
            return f"WorkingDirectory={wd}\nExecStart={ex}\nMainPID={pid}\n"
        raise AssertionError(cmd)

    return run


def fake_cwd(units=UNITS):
    by_pid = {v[2]: v[3] for v in units.values()}
    return lambda pid: by_pid.get(pid, "")


def _plan(**kw):
    return cbu.plan(NEW, releases_base=BASE, run=fake_run(), cwd_of=fake_cwd(), **kw)


def test_derives_the_stale_units_the_fixed_list_missed():
    p = _plan()
    assert "tradeai-ops-applier.service" in p.restart
    assert "grok-oauth-proxy.service" in p.restart
    assert "exec-bound.service" in p.restart  # ExecStart names CURRENT
    assert "unrelated.service" not in p.restart + p.page_only


def test_never_list_and_separately_handled_are_page_only_never_restart():
    p = _plan()
    for name in (
        "portfolio-server.service",
        "tradeai-active-trader-motion.service",
        "tradeai-scalp-live.service",
        "Tradeai-Telegram-Sender.service",  # case-insensitive
    ):
        assert name in p.page_only, name
        assert name not in p.restart, name


def test_config_can_extend_but_not_shrink_the_never_list():
    p = _plan(extra_never=["oauth-proxy"])
    assert "grok-oauth-proxy.service" in p.page_only
    assert cbu.never_reason("tradeai-scalp-live.service", extra_never=[]) == "scalp"
    # word-part match: 'order' must not match 'recorder'
    assert cbu.never_reason("tradeai-micro-recorder.service") is None
    assert cbu.never_reason("tradeai-order-router.service") == "order"


def test_stale_flag_reads_the_live_cwd():
    p = _plan()
    stale = {u.name for u in p.units if u.stale}
    assert "tradeai-ops-applier.service" in stale
    assert "tradeai-health-agent.service" not in stale


def test_verify_requires_cwd_inside_the_new_release():
    out = cbu.verify(
        NEW, ["tradeai-health-agent.service", "tradeai-ops-applier.service"], run=fake_run(), cwd_of=fake_cwd()
    )
    assert out["tradeai-health-agent.service"]["ok"] is True
    assert out["tradeai-ops-applier.service"]["ok"] is False


def _cli(monkeypatch, tmp_path, argv, sent):
    import scripts.current_bound_units as cli

    mod = cli.cbu  # the module object the CLI actually uses
    orig_plan, orig_verify = mod.plan, mod.verify
    monkeypatch.setattr(
        mod, "plan", lambda cur, **kw: orig_plan(cur, releases_base=BASE, run=fake_run(), cwd_of=fake_cwd(), **kw)
    )
    monkeypatch.setattr(
        mod, "verify", lambda cur, units, **kw: orig_verify(cur, units, run=fake_run(), cwd_of=fake_cwd())
    )

    def fake_send(message, **kw):
        sent.append((message, kw))
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", fake_send)
    return cli.main(argv + ["--state-root", str(tmp_path)] if argv[0] == "verify" else argv)


def test_firing_verify_pages_p1_and_writes_a_receipt_when_a_restarted_unit_stays_stale(monkeypatch, tmp_path):
    sent: list = []
    rc = _cli(monkeypatch, tmp_path, ["verify", "--current", NEW, "--restarted", "tradeai-ops-applier.service"], sent)
    assert rc == 2
    assert len(sent) == 1
    msg, kw = sent[0]
    assert kw["priority"] == "P1" and kw["producer"] == "deploy_current_bound_units"
    assert "tradeai-ops-applier.service" in msg and "RELEASE NOT REACHED" in msg
    rec = json.loads((tmp_path / "data/runtime/current_bound_units_last.json").read_text())
    assert rec["failed"] == ["tradeai-ops-applier.service"] and rec["paged"] is True
    assert (tmp_path / "data/runtime/current_bound_units_history.jsonl").read_text().strip()


def test_firing_stale_never_list_unit_pages_without_restart(monkeypatch, tmp_path):
    sent: list = []
    rc = _cli(monkeypatch, tmp_path, ["verify", "--current", NEW, "--restarted", "tradeai-health-agent.service"], sent)
    assert rc == 0
    assert len(sent) == 1 and "tradeai-active-trader-motion.service" in sent[0][0]
    assert "restart it yourself" in sent[0][0]


def test_dry_run_sends_nothing_and_writes_no_receipt(monkeypatch, tmp_path):
    sent: list = []
    _cli(
        monkeypatch,
        tmp_path,
        ["verify", "--current", NEW, "--restarted", "tradeai-ops-applier.service", "--dry-run"],
        sent,
    )
    assert sent == []
    assert not (tmp_path / "data/runtime/current_bound_units_last.json").exists()


def test_page_failure_is_not_swallowed(monkeypatch, tmp_path):
    import scripts.current_bound_units as cli

    monkeypatch.setattr(cli, "deliver", lambda m: (False, "RuntimeError: down"))
    sent: list = []
    rc = _cli(monkeypatch, tmp_path, ["verify", "--current", NEW, "--restarted", "tradeai-health-agent.service"], sent)
    assert rc == 3
    rec = json.loads((tmp_path / "data/runtime/current_bound_units_last.json").read_text())
    assert rec["page_error"] == "RuntimeError: down"


SH = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text(encoding="utf-8")


def _body(fn: str) -> str:
    m = re.search(rf"^{fn}\(\) \{{\n(.*?)^\}}", SH, re.S | re.M)
    assert m, fn
    return m.group(1)


def test_shell_restart_happens_after_health_check_in_promote_and_rollback():
    for fn in ("cmd_promote", "cmd_rollback"):
        body = _body(fn)
        assert body.index("health_check") < body.index("restart_root_frozen_units"), fn


def test_shell_unions_fixed_and_derived_lists_and_verifies():
    body = _body("restart_root_frozen_units")
    assert "tradeai-health-agent.service" in body  # fixed defaults kept
    assert "plan --current" in body and "--names" in body
    assert "TRADEAI_CURRENT_BOUND_UNITS" in body  # operator override kept
    assert 'current_bound_units.py" verify' in body


def _run_restart(tmp_path, env_extra=None, derived="tradeai-ops-applier.service tradeai-health-agent.service"):
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "restarts"
    (fake / "systemctl").write_text(
        '#!/bin/bash\nif [[ "$*" == *" restart "* ]]; then echo "${@: -1}" >> "%s"; fi\n'
        'if [[ "$*" == *"MainPID"* ]]; then echo 123; fi\nexit 0\n' % log
    )
    (fake / "sleep").write_text("#!/bin/bash\nexit 0\n")
    (fake / "readlink").write_text("#!/bin/bash\necho /rel/new\n")
    py = tmp_path / "py"
    calls = tmp_path / "pycalls"
    py.write_text(
        '#!/bin/bash\necho "$*" >> "%s"\nif [[ "$*" == *" plan "* ]]; then echo %s; fi\nexit 0\n' % (calls, derived)
    )
    for f in (*fake.iterdir(), py):
        f.chmod(0o755)
    fn = _body("restart_root_frozen_units")
    script = (
        f"log() {{ :; }}\nVENV_PYTHON={py}\nROOT=/x\nrestart_root_frozen_units() {{\n{fn}}}\n"
        "restart_root_frozen_units /rel/new"
    )
    env = {"PATH": f"{fake}:/usr/bin:/bin", **(env_extra or {})}
    rc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env).returncode
    restarted = log.read_text().split() if log.exists() else []
    return rc, restarted, calls.read_text() if calls.exists() else ""


def test_shell_union_dedupes_keeps_defaults_and_verifies(tmp_path):
    rc, restarted, calls = _run_restart(tmp_path)
    assert rc == 0
    assert restarted.count("tradeai-health-agent.service") == 1
    assert "tradeai-ops-applier.service" in restarted and "cio-governed-bridge.service" in restarted
    assert " verify " in f" {calls} " and "--restarted" in calls


def test_shell_operator_override_replaces_the_list(tmp_path):
    rc, restarted, _ = _run_restart(tmp_path, {"TRADEAI_CURRENT_BOUND_UNITS": "only.service"})
    assert restarted == ["only.service"]


@pytest.mark.parametrize(
    "name",
    [
        "tradeai-secret-render.service",
        "tradeai-guard.service",
        "tradeai-deploy-on-main.service",
        "tradeai-positions-sync.service",
        "tradeai-paper-exec.service",
        "tradeai-dof-sql.service",
    ],
)
def test_never_list_covers_23_14_classes(name):
    assert cbu.never_reason(name)
