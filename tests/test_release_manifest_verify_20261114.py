"""Hermetic tests for scripts/release_manifest_verify.py (LEAD 14:27Z manifest verification).

Every host read is injected: systemctl text, /proc readers, crontab text, lane rows and the file-exists
test. The only real filesystem use is a tmp releases base holding two release dirs and a CURRENT symlink.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_manifest_verify as rmv  # noqa: E402

ACT = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
AFTER = ACT + timedelta(minutes=5)
BEFORE = ACT - timedelta(hours=1)


@pytest.fixture()
def host(tmp_path):
    base = tmp_path / "releases"
    new, old = base / "rel-new", base / "rel-old"
    for d in (new / "scripts", old / "scripts"):
        d.mkdir(parents=True)
    (base / "CURRENT").symlink_to(new)
    canon = tmp_path / "canon"
    (canon / "scripts").mkdir(parents=True)
    return {"base": base, "cur": base / "CURRENT", "new": str(new), "old": str(old), "canon": str(canon)}


def _show(units):
    blocks = []
    for u in units:
        argv = u.pop("argv")
        u.setdefault("ExecStart", f"{{ path=/bin/x ; argv[]={argv} ; ignore_errors=no }}")
        blocks.append("\n".join(f"{k}={v}" for k, v in u.items()))
    return "\n\n".join(blocks)


def _run_for(units):
    names = "\n".join(f"{u['Id']} enabled enabled" for u in units)
    shown = _show([dict(u) for u in units])

    def run(cmd):
        if "list-unit-files" in cmd:
            return names
        if "show" in cmd:
            return shown
        raise AssertionError(f"unexpected host command {cmd}")
    return run


def _build(host, units, *, cwd=None, start=None, cmdline=None, crontab="", lanes=(), exists=None):
    return rmv.build(host["cur"], ACT, host["canon"], run=_run_for(units),
                     proc_cwd=lambda pid: (cwd or {}).get(pid), proc_start=lambda pid: (start or {}).get(pid),
                     proc_cmdline=lambda pid: (cmdline or {}).get(pid, []), exists=exists or (lambda p: False),
                     crontab_text=crontab, lane_rows=list(lanes))


def _one(entries, name):
    hit = [e for e in entries if e.name == name]
    assert len(hit) == 1, [e.name for e in entries]
    return hit[0]


def _svc(name, argv, wd="", pid=0, **kw):
    return {"Id": name, "argv": argv, "WorkingDirectory": wd, "ActiveState": "active" if pid else "inactive",
            "Type": kw.get("Type", "oneshot"), "TriggeredBy": kw.get("TriggeredBy", "x.timer"), "MainPID": str(pid),
            "FragmentPath": "/u/" + name, "Transient": "no"}


def test_running_unit_started_after_activation_in_current_passes(host):
    u = _svc("tradeai-a.service", f"/venv/bin/python {host['cur']}/scripts/a.py", wd=str(host["cur"]), pid=11,
             Type="simple", TriggeredBy="")
    e = _one(_build(host, [u], cwd={11: host["new"]}, start={11: AFTER},
                    cmdline={11: ["/venv/bin/python", f"{host['new']}/scripts/a.py"]}), "tradeai-a.service")
    assert (e.verdict, e.observed) == (rmv.PASS, "rel-new")


def test_running_unit_started_before_activation_fails(host):
    u = _svc("tradeai-a.service", f"python {host['cur']}/scripts/a.py", wd=str(host["cur"]), pid=11)
    e = _one(_build(host, [u], cwd={11: host["new"]}, start={11: BEFORE},
                    cmdline={11: ["python", "scripts/a.py"]}), "tradeai-a.service")
    assert e.verdict == rmv.FAIL and "started before activation" in e.evidence


def test_running_unit_with_cwd_in_old_release_fails(host):
    u = _svc("tradeai-a.service", f"python {host['cur']}/scripts/a.py", wd=str(host["cur"]), pid=11)
    e = _one(_build(host, [u], cwd={11: host["old"]}, start={11: AFTER},
                    cmdline={11: ["python", "scripts/a.py"]}), "tradeai-a.service")
    assert (e.verdict, e.observed) == (rmv.FAIL, "rel-old")


def test_unreadable_proc_is_unknown_not_pass(host):
    u = _svc("tradeai-a.service", f"python {host['cur']}/scripts/a.py", wd=str(host["cur"]), pid=11)
    e = _one(_build(host, [u]), "tradeai-a.service")
    assert e.verdict == rmv.UNKNOWN


def test_overlay_script_is_judged_by_cwd_and_start(host):
    shim = "/opt/overlay/bin/shim.py"
    u = _svc("tradeai-h.service", f"python {shim}", wd=str(host["cur"]), pid=12)
    e = _one(_build(host, [u], cwd={12: host["new"]}, start={12: AFTER}, cmdline={12: ["python", shim]}),
             "tradeai-h.service")
    assert e.verdict == rmv.PASS and "overlay" in e.evidence


def test_next_run_pinned_to_old_release_fails(host):
    u = _svc("tradeai-b.service", f"python {host['old']}/scripts/b.py")
    e = _one(_build(host, [u]), "tradeai-b.service")
    assert e.verdict == rmv.FAIL and "rel-old" in e.evidence


def test_next_run_via_current_passes_and_canonical_is_not_release(host):
    ok = _svc("tradeai-b.service", f"python {host['cur']}/scripts/b.py")
    canon = _svc("tradeai-c.service", f"python {host['canon']}/scripts/c.py")
    es = _build(host, [ok, canon])
    assert _one(es, "tradeai-b.service").verdict == rmv.PASS
    assert _one(es, "tradeai-c.service").verdict == rmv.NOT_RELEASE


def test_inactive_long_running_service_is_unknown_not_pass(host):
    u = _svc("tradeai-d.service", f"python {host['cur']}/scripts/d.py", Type="simple", TriggeredBy="")
    assert _one(_build(host, [u]), "tradeai-d.service").verdict == rmv.UNKNOWN


def test_unit_whose_script_is_relative_to_wd_is_listed(host):
    u = _svc("tradeai-e.service", "python scripts/e.py", wd=str(host["cur"]))
    assert _one(_build(host, [u]), "tradeai-e.service").verdict == rmv.PASS


def _loop(first, second, rel="scripts/w.py"):
    return (f"/bin/bash -lc 'for CAND in {first} {second}; do if [ -f \"$CAND/{rel}\" ]; then cd \"$CAND\"; "
            f"exec \"$PY\" {rel} --apply; fi; done; exit 1'")


def test_candidate_loop_resolves_to_first_existing_candidate(host):
    canon_first = _svc("tradeai-w.service", _loop(host["canon"], host["cur"]))
    cur_first = _svc("tradeai-v.service", _loop(host["cur"], host["canon"]))
    es = _build(host, [canon_first, cur_first], exists=lambda p: True)
    w, v = _one(es, "tradeai-w.service"), _one(es, "tradeai-v.service")
    assert (w.verdict, w.observed) == (rmv.NOT_RELEASE, "CANONICAL")
    assert v.verdict == rmv.PASS and "candidate loop" in v.evidence
    # canonical lacks the script -> the loop falls through to CURRENT
    es = _build(host, [canon_first], exists=lambda p: not p.startswith(host["canon"]))
    assert _one(es, "tradeai-w.service").verdict == rmv.PASS


def test_candidate_loop_with_no_candidate_fails(host):
    u = _svc("tradeai-w.service", _loop(host["canon"], host["cur"]))
    assert _one(_build(host, [u], exists=lambda p: False), "tradeai-w.service").verdict == rmv.FAIL


def test_crontab_variable_expansion_and_pinning(host):
    tab = (f"PROJ={host['cur']}\nOLD={host['old']}\n"
           "*/5 * * * * cd $PROJ && python scripts/a.py >> /tmp/x.log 2>&1\n"
           "0 1 * * * python $OLD/scripts/b.py\n# 0 2 * * * python $OLD/scripts/c.py\n")
    es = [e for e in _build(host, [], crontab=tab) if e.kind == "cron"]
    assert [e.verdict for e in es] == [rmv.PASS, rmv.FAIL]


def test_n8n_lanes_follow_executor_and_code_root_override_fails(host):
    lanes = [{"dispatch": {"mode": "live"}, "state": "ACTIVE"}, {"dispatch": {"mode": "shadow"}, "state": "ACTIVE"}]
    u = _svc("tradeai-n8n-run-executor.service", f"python {host['cur']}/scripts/n8n_run_executor.py",
             wd=str(host["cur"]), pid=13, Type="simple", TriggeredBy="")
    base = dict(cwd={13: host["new"]}, start={13: AFTER}, lanes=lanes)
    ok = _one(_build(host, [dict(u)], cmdline={13: ["python", "scripts/n8n_run_executor.py"]}, **base), "n8n-lanes (1)")
    assert ok.verdict == rmv.PASS
    bad = _one(_build(host, [dict(u)], cmdline={13: ["python", "scripts/n8n_run_executor.py", "--code-root", "/x"]},
                      **base), "n8n-lanes (1)")
    assert bad.verdict == rmv.FAIL


def test_n8n_lanes_without_executor_is_unknown(host):
    e = _one(_build(host, [], lanes=[{"dispatch": {"mode": "live"}, "state": "ACTIVE"}]), "n8n-lanes (1)")
    assert e.verdict == rmv.UNKNOWN


def test_no_host_write_and_no_environment_read(host):
    seen = []

    def run(cmd):
        seen.append(cmd)
        return "" if "list-unit-files" in cmd else ""
    rmv.build(host["cur"], ACT, host["canon"], run=run, crontab_text="", lane_rows=[])
    flat = " ".join(" ".join(c) for c in seen)
    assert "Environment" not in flat
    assert not any(w in flat for w in ("restart", "start ", "stop", "reload", "daemon-reload", "kill"))


def test_command_loading_code_from_release_and_canonical_is_mixed_fail(host):
    u = _svc("tradeai-m.service", f"python {host['cur']}/scripts/m.py --plugin {host['canon']}/scripts/p.py")
    e = _one(_build(host, [u]), "tradeai-m.service")
    assert e.verdict == rmv.FAIL and "mixed code roots" in e.evidence
