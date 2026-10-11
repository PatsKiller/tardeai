"""Release-pinned daemons follow every promote/rollback (packets/unit-code-roots, 2026-10-10).

Four user daemons ran a032116e7 for four days because their one-off exact-SHA drop-ins were never
rewritten by the deploy. Hermetic: a fake systemd user dir, a fake releases base and a fake systemctl.
Nothing here reads the host's ~/.config/systemd/user or calls the real systemctl.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_pin_daemons as rpd  # noqa: E402

DEPLOY = ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"
OLD = "a032116e7-main-exact-phase2-20261006-153254"
PREV = "8ddf2ad59-main-exact-phase2-20261010-183820"
NEW = "464524b1b-main-exact-phase2-20261010-220000"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): _sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    base = tmp_path / "releases" / "portfolio-server"
    for name in (OLD, PREV, NEW):
        (base / name / "scripts").mkdir(parents=True)
    (base / "CURRENT").symlink_to(base / PREV)
    units = tmp_path / "systemd-user"
    units.mkdir()
    log = tmp_path / "systemctl.log"
    fake = tmp_path / "fake-systemctl"
    fake.write_text(
        "#!/bin/bash\n"
        'echo "$*" >> "$FAKE_SYSTEMCTL_LOG"\n'
        'if [[ "$2" == "is-active" ]]; then [[ " $FAKE_ACTIVE " == *" ${@: -1} "* ]] && exit 0 || exit 3; fi\n'
        "exit 0\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("FAKE_SYSTEMCTL_LOG", str(log))
    monkeypatch.setenv("FAKE_ACTIVE", "heartbeat-receiver.service grok-oauth-proxy.service")
    monkeypatch.delenv("TRADE_AI_CI", raising=False)

    def unit(name: str, fragment: str, dropins: dict[str, str]) -> Path:
        (units / name).write_text(fragment)
        d = units / f"{name}.d"
        d.mkdir()
        for fn, body in dropins.items():
            (d / fn).write_text(body)
        return d

    pinned = lambda rel, script, py="/usr/bin/python3": (  # noqa: E731
        f"[Service]\nWorkingDirectory={base / rel}\nExecStart=\nExecStart={py} {base / rel}/scripts/{script}\n"
    )
    # 1. pin-only one-off (archived + replaced)
    unit("heartbeat-receiver.service", "[Unit]\nDescription=hb\n[Service]\nExecStart=/usr/bin/python3 x.py\n",
         {"20-exact-sha-release.conf": pinned(OLD, "heartbeat_receiver.py")})
    # 2. one-off that also carries other directives (kept, overridden by the managed drop-in)
    unit("grok-oauth-proxy.service", "[Service]\nExecStart=/usr/bin/python3 y.py\n",
         {"20-exact-sha-release.conf": pinned(OLD, "grok_oauth_proxy.py")
          + f"Environment=PYTHONPATH={base / OLD}/scripts\nEnvironment=GROK_PORT=8899\nRestart=always\n"})
    # 3. broker-adjacent by code path (scripts/active_trader/**): never modified
    unit("tradeai-motion-x.service", "[Service]\nExecStart=/bin/true\n",
         {"10-user-exact-sha.conf": f"[Service]\nWorkingDirectory={base / OLD}\nExecStart=\n"
                                    f"ExecStart=/usr/bin/python3 {base / OLD}/scripts/active_trader/motion.py\n"})
    # 4. shadowed: the pin is overridden by a later CURRENT drop-in (the 95-code-root-current.conf case)
    unit("chatgpt-oauth-proxy.service", "[Service]\nExecStart=/usr/bin/python3 z.py\n",
         {"20-exact-sha-release.conf": pinned(OLD, "chatgpt_oauth_proxy.py"),
          "95-code-root-current.conf": f"[Service]\nWorkingDirectory={base}/CURRENT\nExecStart=\n"
                                       f"ExecStart=/usr/bin/python3 {base}/CURRENT/scripts/chatgpt_oauth_proxy.py\n"})
    # 5. excluded: portfolio-server's drop-in is the deploy's own write_systemd()
    unit("portfolio-server.service", "[Service]\n", {"20-exact-sha-release.conf": pinned(OLD, "portfolio_server.py")})
    # 6. no pin at all
    unit("tradeai-plain.service", "[Service]\nExecStart=/bin/true\n", {"10-env.conf": "[Service]\nEnvironment=A=1\n"})
    receipts = tmp_path / "receipts"

    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/release_pin_daemons.py"), *args,
             "--unit-dir", str(units), "--releases-base", str(base), "--receipt-dir", str(receipts),
             "--systemctl", str(fake)],
            capture_output=True, text=True, env={**os.environ},
        )

    return {"base": base, "units": units, "log": log, "fake": fake, "cli": cli, "receipts": receipts,
            "tmp": tmp_path}


def _plans(env, target=NEW):
    cfg = rpd.load_config()
    return {p.unit: p for p in rpd.build_plan(env["units"], env["base"] / target, env["base"], cfg)}


def test_plan_classifies_every_pinned_unit(env):
    plans = _plans(env)
    assert plans["heartbeat-receiver.service"].status == "rewrite"
    assert plans["heartbeat-receiver.service"].archive == ["20-exact-sha-release.conf"]
    assert plans["grok-oauth-proxy.service"].status == "rewrite"
    assert plans["grok-oauth-proxy.service"].kept == ["20-exact-sha-release.conf"]
    assert plans["tradeai-motion-x.service"].status == "broker_adjacent"
    assert "pinned-broker-adjacent: operator action" in plans["tradeai-motion-x.service"].reason
    assert "scripts/active_trader" in plans["tradeai-motion-x.service"].reason
    assert plans["chatgpt-oauth-proxy.service"].status == "shadowed"
    assert "portfolio-server.service" not in plans
    assert "tradeai-plain.service" not in plans


def test_dry_run_prints_the_plan_and_writes_nothing(env):
    before = _tree(env["units"])
    r = env["cli"]("plan", "--target", str(env["base"] / NEW))
    assert r.returncode == 0, r.stderr
    assert "DRY RUN" in r.stdout
    assert "STALE PINS" in r.stdout and "heartbeat-receiver.service" in r.stdout
    assert "BROKER_ADJACENT" in r.stdout and "pinned-broker-adjacent: operator action" in r.stdout
    assert _tree(env["units"]) == before
    assert not env["receipts"].exists()
    assert not env["log"].exists()


def test_apply_rewrites_stale_pins_archives_one_offs_and_spares_broker_unit(env):
    motion = env["units"] / "tradeai-motion-x.service.d" / "10-user-exact-sha.conf"
    motion_sha = _sha(motion)
    hb_one_off = env["units"] / "heartbeat-receiver.service.d" / "20-exact-sha-release.conf"
    hb_sha = _sha(hb_one_off)
    grok_one_off = env["units"] / "grok-oauth-proxy.service.d" / "20-exact-sha-release.conf"
    grok_sha = _sha(grok_one_off)

    r = env["cli"]("apply", "--target", str(env["base"] / NEW), "--deploy-restarted", "grok-oauth-proxy.service")
    assert r.returncode == 0, r.stdout + r.stderr

    # heartbeat: managed drop-in names NEW; the pin-only one-off is archived, not deleted.
    hb_managed = env["units"] / "heartbeat-receiver.service.d" / "90-release-pin.conf"
    text = hb_managed.read_text()
    assert f"WorkingDirectory={env['base'] / NEW}\n" in text
    assert f"ExecStart=\nExecStart=/usr/bin/python3 {env['base'] / NEW}/scripts/heartbeat_receiver.py\n" in text
    assert OLD not in text.split("[Service]", 1)[1]
    assert not hb_one_off.exists()
    archived = list((env["units"] / ".release-pin-archive").rglob("20-exact-sha-release.conf"))
    assert [_sha(p) for p in archived] == [hb_sha]
    assert any((env["units"] / ".release-pin-archive").rglob("TRIPWIRE.README"))

    # grok: the one-off carries Restart/GROK_PORT, so it stays; the managed file overrides its pins.
    assert _sha(grok_one_off) == grok_sha
    g = (env["units"] / "grok-oauth-proxy.service.d" / "90-release-pin.conf").read_text()
    assert f"Environment=PYTHONPATH={env['base'] / NEW}/scripts" in g
    assert "GROK_PORT" not in g and "Restart" not in g

    # broker-adjacent: byte-identical, listed for the operator.
    assert _sha(motion) == motion_sha
    assert not (motion.parent / "90-release-pin.conf").exists()

    # shadowed and excluded units untouched.
    assert not (env["units"] / "chatgpt-oauth-proxy.service.d" / "90-release-pin.conf").exists()
    assert not (env["units"] / "portfolio-server.service.d" / "90-release-pin.conf").exists()

    calls = env["log"].read_text().splitlines()
    assert calls.count("--user daemon-reload") == 1
    assert not [c for c in calls if c.startswith("--user restart")]  # allowlist empty by default

    rec = json.loads(Path(re.search(r"receipt → (\S+)", r.stdout).group(1)).read_text())
    assert rec["schema"] == "ReleasePinReceipt@v1"
    rows = {u["unit"]: u for u in rec["units"]}
    assert rows["heartbeat-receiver.service"]["restart"] == "restart pending"
    assert rows["grok-oauth-proxy.service"]["restart"] == "restarted by deploy (bound unit)"
    assert rows["tradeai-motion-x.service"]["status"] == "broker_adjacent"
    assert rows["heartbeat-receiver.service"]["archived"][0]["sha256"] == hb_sha
    assert (env["receipts"] / "last_apply.json").is_file()

    # effective config after apply: every non-broker unit resolves to NEW.
    after = _plans(env)
    assert after["heartbeat-receiver.service"].status == "current"
    assert after["grok-oauth-proxy.service"].status == "current"
    assert after["tradeai-motion-x.service"].status == "broker_adjacent"


def test_apply_is_idempotent(env):
    t = str(env["base"] / NEW)
    assert env["cli"]("apply", "--target", t).returncode == 0
    snap = _tree(env["units"])
    calls = env["log"].read_text()
    r2 = env["cli"]("apply", "--target", t)
    assert r2.returncode == 0, r2.stderr
    assert _tree(env["units"]) == snap
    assert env["log"].read_text() == calls  # no second daemon-reload, no restarts
    rec = json.loads(Path(re.search(r"receipt → (\S+)", r2.stdout).group(1)).read_text())
    assert not [u for u in rec["units"] if u.get("managed_path")]


def test_next_promote_rewrites_the_managed_file_and_archives_the_old_one(env):
    assert env["cli"]("apply", "--target", str(env["base"] / PREV)).returncode == 0
    managed = env["units"] / "heartbeat-receiver.service.d" / "90-release-pin.conf"
    prev_sha = _sha(managed)
    assert env["cli"]("apply", "--target", str(env["base"] / NEW)).returncode == 0
    assert str(env["base"] / NEW) in managed.read_text()
    assert prev_sha in {_sha(p) for p in (env["units"] / ".release-pin-archive").rglob("90-release-pin.conf")}


def test_rollback_restores_archived_drop_ins(env):
    hb_dir = env["units"] / "heartbeat-receiver.service.d"
    before = _tree(hb_dir)
    assert env["cli"]("apply", "--target", str(env["base"] / NEW)).returncode == 0
    assert _tree(hb_dir) != before
    r = env["cli"]("rollback", "--target", str(env["base"] / PREV), "--from", str(env["base"] / NEW))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "restored drop-ins archived by the promote" in r.stdout
    assert _tree(hb_dir) == before  # one-off back in place, byte-identical; managed file archived
    assert any((env["units"] / ".release-pin-archive").rglob("90-release-pin.conf"))
    assert not (env["receipts"] / "last_apply.json").exists()
    assert list(env["receipts"].glob("last_apply.restored-*.json"))


def test_rollback_without_matching_receipt_rewrites_to_target(env):
    r = env["cli"]("rollback", "--target", str(env["base"] / PREV), "--from", str(env["base"] / NEW))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no matching promote receipt" in r.stdout
    assert str(env["base"] / PREV) in (env["units"] / "heartbeat-receiver.service.d" / "90-release-pin.conf").read_text()


def test_restore_refuses_when_managed_drop_in_was_hand_edited(env):
    r = env["cli"]("apply", "--target", str(env["base"] / NEW))
    receipt = re.search(r"receipt → (\S+)", r.stdout).group(1)
    managed = env["units"] / "heartbeat-receiver.service.d" / "90-release-pin.conf"
    managed.write_text(managed.read_text() + "Environment=HAND=1\n")
    r2 = env["cli"]("restore", "--receipt", receipt)
    assert r2.returncode == 3
    assert "drift" in r2.stdout
    assert managed.is_file()


def test_blocked_when_a_later_mixed_drop_in_holds_the_stale_pin(env):
    d = env["units"] / "heartbeat-receiver.service.d"
    (d / "99-late.conf").write_text(f"[Service]\nWorkingDirectory={env['base'] / OLD}\nEnvironment=X=1\n")
    r = env["cli"]("apply", "--target", str(env["base"] / NEW))
    assert r.returncode == 3
    assert "operator action" in r.stdout
    assert not (d / "90-release-pin.conf").exists()


def test_restart_allowlist_restarts_only_listed_units(env, tmp_path):
    cfg = json.loads((ROOT / "config/release_pin_daemons.json").read_text())
    cfg["restart_allowlist"] = ["heartbeat-receiver.service"]
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg))
    r = env["cli"]("apply", "--target", str(env["base"] / NEW), "--config", str(cfg_path))
    assert r.returncode == 0, r.stderr
    restarts = [c for c in env["log"].read_text().splitlines() if c.startswith("--user restart")]
    assert restarts == ["--user restart heartbeat-receiver.service"]


def test_broker_adjacent_by_unit_name_is_never_modified(env):
    d = env["units"] / "tradeai-active-trader-motion.service.d"
    d.mkdir()
    one_off = d / "10-user-exact-sha.conf"
    one_off.write_text(f"[Service]\nWorkingDirectory={env['base'] / OLD}\n")
    sha = _sha(one_off)
    r = env["cli"]("apply", "--target", str(env["base"] / NEW))
    assert r.returncode == 0
    assert "tradeai-active-trader-motion.service: pinned-broker-adjacent: operator action" in r.stdout
    assert _sha(one_off) == sha and sorted(p.name for p in d.iterdir()) == ["10-user-exact-sha.conf"]


def test_broker_globs_come_from_the_guard_rules_and_fail_closed(tmp_path):
    cfg = rpd.load_config()
    assert "**/scripts/active_trader/**" in cfg.broker_globs
    assert "**/scripts/brokers/**" in cfg.broker_globs
    bad = json.loads((ROOT / "config/release_pin_daemons.json").read_text())
    bad["broker_rule_id"] = "no.such.rule"
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(rpd.Refused):
        rpd.load_config(p)


def test_ci_guard_refuses_the_real_unit_dir(env, monkeypatch):
    monkeypatch.setattr(rpd, "REAL_UNIT_DIR", env["units"])
    monkeypatch.setenv("TRADE_AI_CI", "1")
    with pytest.raises(rpd.Refused):
        rpd._guard_live(env["units"])


def test_fake_unit_dir_never_drives_the_real_systemctl(env, monkeypatch):
    monkeypatch.delenv("TRADEAI_SYSTEMCTL", raising=False)
    s = rpd.Systemctl(None, env["units"])
    assert s.cmd == "systemctl" and s.enabled is False
    assert s.run("daemon-reload") == 0 and s.calls  # recorded, never executed
    assert s.is_active("heartbeat-receiver.service") is False


def test_tripwire_fires_when_a_live_unit_references_the_archive(env):
    assert env["cli"]("apply", "--target", str(env["base"] / NEW)).returncode == 0
    assert env["cli"]("tripwire").returncode == 0
    (env["units"] / "heartbeat-receiver.service.d" / "50-bad.conf").write_text(
        f"[Service]\nEnvironmentFile={env['units']}/.release-pin-archive/x/y.conf\n")
    r = env["cli"]("tripwire")
    assert r.returncode == 3 and "TRIPWIRE" in r.stdout


def test_target_must_be_a_concrete_release(env):
    r = env["cli"]("plan", "--target", str(env["base"] / "CURRENT"))
    assert r.returncode == 2 and "concrete release" in r.stderr
    r = env["cli"]("plan", "--target", str(env["tmp"] / "elsewhere"))
    assert r.returncode == 2


# --------------------------------------------------------------------------- deploy script wiring


def _fn(src: str, name: str) -> str:
    return re.search(rf"^{name}\(\) \{{.*?^\}}", src, re.M | re.S).group()


def test_deploy_promote_rewrites_pins_after_health_and_before_bound_restart():
    src = DEPLOY.read_text(encoding="utf-8")
    promote = _fn(src, "cmd_promote")
    assert promote.index('release_pin_step plan "$dir"') < promote.index('activate_release "$dir" "$sha"')
    assert promote.index('health_check "promote"') < promote.index('release_pin_step apply "$dir"')
    assert promote.index('release_pin_step apply "$dir"') < promote.index('restart_root_frozen_units "$dir"')


def test_deploy_rollback_restores_pins_from_the_promote_it_undoes():
    src = DEPLOY.read_text(encoding="utf-8")
    rb = _fn(src, "cmd_rollback")
    assert rb.index('rolled_from="$(current_release)"') < rb.index('activate_release "$target"')
    assert 'release_pin_step rollback "$target" "$rolled_from"' in rb
    assert "pins)" in src and "release_pin_step plan" in src


def test_deploy_keeps_one_bound_units_literal():
    # dims_governance and test_release_pin_and_validator parse the first/only default list.
    src = DEPLOY.read_text(encoding="utf-8")
    assert src.count("TRADEAI_CURRENT_BOUND_UNITS:-") == 1


def test_deploy_pin_step_runs_against_fake_tree(env, tmp_path):
    """Exercise release_pin_step from the real script with a fake tree: bound units resolve from the
    restart function, the receipt path is captured, and plan mode writes nothing."""
    src = DEPLOY.read_text(encoding="utf-8")
    body = "\n".join([
        "set -euo pipefail",
        'log() { echo "$*"; }',
        f'ROOT="{ROOT}"',
        f'VENV_PYTHON="{sys.executable}"',
        _fn(src, "restart_root_frozen_units"),
        "RELEASE_PIN_RECEIPT=''",
        _fn(src, "release_pin_step"),
        'release_pin_step "$1" "$2"',
        'echo "RECEIPT=$RELEASE_PIN_RECEIPT"',
    ])
    script = tmp_path / "step.sh"
    script.write_text(body)
    run_env = {**os.environ, "TRADEAI_SYSTEMD_USER_DIR": str(env["units"]),
               "TRADEAI_RELEASES_BASE": str(env["base"]), "TRADEAI_RELEASE_PIN_RECEIPT_DIR": str(env["receipts"]),
               "TRADEAI_SYSTEMCTL": str(env["fake"])}
    run_env.pop("TRADEAI_CURRENT_BOUND_UNITS", None)
    before = _tree(env["units"])
    r = subprocess.run(["bash", str(script), "plan", str(env["base"] / NEW)], capture_output=True, text=True,
                       env=run_env)
    assert r.returncode == 0, r.stderr
    assert "pins:" in r.stdout and "DRY RUN" in r.stdout
    assert _tree(env["units"]) == before
    r = subprocess.run(["bash", str(script), "apply", str(env["base"] / NEW)], capture_output=True, text=True,
                       env=run_env)
    assert r.returncode == 0, r.stderr
    receipt = re.search(r"RECEIPT=(\S+)", r.stdout).group(1)
    rec = json.loads(Path(receipt).read_text())
    assert {u["unit"] for u in rec["units"] if u.get("managed_path")} == {
        "heartbeat-receiver.service", "grok-oauth-proxy.service"}
    # warn mode lists but never writes
    run_env["TRADEAI_RELEASE_PIN_MODE"] = "warn"
    snap = _tree(env["units"])
    r = subprocess.run(["bash", str(script), "apply", str(env["base"] / PREV)], capture_output=True, text=True,
                       env=run_env)
    assert r.returncode == 0
    assert "were NOT rewritten" in r.stdout
    assert _tree(env["units"]) == snap
