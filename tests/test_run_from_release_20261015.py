"""Run-from-release tooling (WS7-01 / WS8-14): crontab generator, drop-in generator, verifier, write-path scan.

Hermetic: a fake dev tree, a fake releases base with a CURRENT symlink, crontab text written inline, and a fake
subprocess runner. Nothing here reads the host crontab, calls systemctl or bwrap, or touches a release dir.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_from_release as rfr  # noqa: E402

BROKER_RULES = ROOT / "config" / "agents_guard_hook_rules.json"


@pytest.fixture()
def lay(tmp_path):
    dev = tmp_path / "dev"
    (dev / ".venv" / "bin").mkdir(parents=True)
    base = tmp_path / "releases" / "portfolio-server"
    rel = base / "abc1234-main-exact-phase2-20261015-010101"
    (rel / "scripts").mkdir(parents=True)
    (rel / "data").mkdir()
    (rel / "state").mkdir()
    persistent = tmp_path / "persistent-state" / "logs"
    persistent.mkdir(parents=True)
    (rel / "logs").symlink_to(persistent)
    (base / "CURRENT").symlink_to(rel)
    cfg_path = tmp_path / "cohorts.json"
    cfg_path.write_text(
        json.dumps(
            {
                "layout": {
                    "dev_root": str(dev),
                    "releases_base": str(base),
                    "worktree_root_patterns": [str(tmp_path / "wt-") + "[^/\\s]+"],
                },
                "exclude_units": ["portfolio-server.service"],
                "broker_adjacent_markers": ["schwab", "stop_supervisor"],
                "cohorts": [
                    {
                        "id": "c1",
                        "title": "reports",
                        "match": [r"\$PY scripts/report_[a-z_]+\.py"],
                        "exclude": ["telegram"],
                    },
                    {"id": "c2", "title": "python", "match": [r"\$PY [^|;&]*scripts/[a-z_]+\.py"]},
                    {"id": "c3", "title": "wrappers", "match": [r"\.sh\b"]},
                    {"id": "c4", "title": "broker", "match": ["."], "broker_adjacent_allowed": True},
                ],
            }
        )
    )
    cfg = rfr.load_config(cfg_path, BROKER_RULES)
    return {
        "tmp": tmp_path,
        "dev": dev,
        "base": base,
        "rel": rel,
        "current": base / "CURRENT",
        "cfg": cfg,
        "cfg_path": cfg_path,
    }


def _crontab(lay) -> str:
    cur, dev = lay["current"], lay["dev"]
    return "\n".join(
        [
            "SHELL=/bin/bash",
            f"PROJ={cur}",
            f"PY={dev}/.venv/bin/python",
            "# a comment",
            "30 7 * * 1-5 cd $PROJ && $PY scripts/report_alpha.py --days 7 >> logs/a.log 2>&1",
            "30 8 * * 1-5 cd $PROJ && $PY scripts/report_beta.py --telegram >> logs/b.log 2>&1",
            "*/5 9-15 * * 1-5 cd $PROJ && $PY scripts/unified_stop_supervisor.py --apply >> logs/s.log 2>&1",
            "0 3 * * * cd $PROJ && $PY scripts/ingest_gamma.py --date $(date +\\%F) >> logs/g.log 2>&1",
            f"15 6 * * 1-5 {cur}/scripts/run_pinned.sh full",
            "0 18 * * * cd /home/other-app && .venv/bin/python3 scripts/x.py >> logs/x.log 2>&1",
            f"@reboot sleep 60 && cd {cur} && $PY scripts/report_boot.py",
            "",
        ]
    )


def _wrappers(lay):
    s = lay["rel"] / "scripts"
    (s / "run_pinned.sh").write_text(f'#!/bin/bash\nPROJ="{lay["dev"]}"\ncd "$PROJ"\n$PY scripts/x.py\n')
    (s / "run_soft.sh").write_text(f'#!/bin/bash\nPROJ="${{PROJ:-{lay["dev"]}}}"\n')
    (s / "run_clean.sh").write_text('#!/bin/bash\ncd "$PROJ" && "$PY" scripts/x.py\n')


# --------------------------------------------------------------------------- parsing / classification


def test_parse_crontab_kinds(lay):
    lines = rfr.parse_crontab(_crontab(lay))
    kinds = [ln.kind for ln in lines]
    assert kinds[:4] == ["env", "env", "env", "comment"]
    jobs = [ln for ln in lines if ln.kind == "job"]
    assert len(jobs) == 7
    assert jobs[-1].schedule == "@reboot"
    assert jobs[0].schedule == "30 7 * * 1-5"


def test_classify_dev_venv_and_wrapper_verdicts(lay):
    _wrappers(lay)
    inv = rfr.inventory(_crontab(lay), lay["cfg"], {}, {})
    jobs = {j["lineno"]: j for j in inv["jobs"]}
    assert jobs[5]["interpreter"] == "dev_venv" and jobs[5]["root"] == "current" and jobs[5]["executes_dev"]
    assert jobs[9]["wrapper"]["verdict"] == "pins_dev" and jobs[9]["executes_dev"]
    assert jobs[10]["root"] == "external" and not jobs[10]["trade_ai"]
    assert jobs[7]["broker_adjacent"]
    assert inv["crontab"]["wrappers"]["pins_dev"] == 1
    soft = rfr.scan_wrapper(lay["rel"] / "scripts" / "run_soft.sh", lay["cfg"].layout)
    clean = rfr.scan_wrapper(lay["rel"] / "scripts" / "run_clean.sh", lay["cfg"].layout)
    assert soft["verdict"] == "dev_default" and clean["verdict"] == "clean"


# --------------------------------------------------------------------------- crontab generator


def test_cohort_prefix_only_selected_lines(lay):
    live = _crontab(lay)
    res = rfr.generate_crontab(live, lay["cfg"], cohorts=["c1"])
    out = res.text.splitlines()
    i = out.index(f"PY={lay['dev']}/.venv/bin/python")
    assert out[i + 1] == f"RPY={lay['current']}/.venv/bin/python"
    assert out[i + 2] == f"TRADEAI_CODE_ROOT={lay['current']}"
    prefixed = [x for x in out if "TRADEAI_RUN_FROM_RELEASE=c1" in x]
    # report_alpha and report_boot; report_beta is excluded (telegram), the stop supervisor is broker-adjacent.
    assert len(prefixed) == 2
    assert all("$RPY scripts/report_" in x for x in prefixed)
    assert not any("report_beta" in x for x in prefixed)
    assert not any("unified_stop_supervisor" in x and "RUN_FROM_RELEASE" in x for x in out)
    assert res.summary["lines_prefixed"] == 2
    # untouched lines are byte-identical
    for x in live.splitlines():
        if "report_alpha" not in x and "report_boot" not in x:
            assert x in out
    assert any(x.startswith("@reboot export PY=$RPY") for x in out)


def test_broker_adjacent_only_in_allowed_cohort(lay):
    res = rfr.generate_crontab(_crontab(lay), lay["cfg"], cohorts=["c2"])
    assert not any("unified_stop_supervisor" in x and "RUN_FROM_RELEASE" in x for x in res.text.splitlines())
    res4 = rfr.generate_crontab(_crontab(lay), lay["cfg"], cohorts=["c4"])
    assert any("unified_stop_supervisor" in x and "RUN_FROM_RELEASE=c4" in x for x in res4.text.splitlines())


def test_percent_escape_preserved(lay):
    res = rfr.generate_crontab(_crontab(lay), lay["cfg"], cohorts=["c2"])
    line = next(x for x in res.text.splitlines() if "ingest_gamma" in x)
    assert "$(date +\\%F)" in line and "RUN_FROM_RELEASE=c2" in line


def test_revert_round_trip_is_exact(lay):
    live = _crontab(lay)
    cand = rfr.generate_crontab(live, lay["cfg"], cohorts=["c1", "c2"]).text
    one = rfr.generate_crontab(cand, lay["cfg"], revert=["c1"]).text
    assert "TRADEAI_RUN_FROM_RELEASE=c1" not in one and "TRADEAI_RUN_FROM_RELEASE=c2" in one
    both = rfr.generate_crontab(one, lay["cfg"], revert=["c2"]).text
    assert both == live


def test_revert_keeps_odd_whitespace_byte_exact(lay):
    live = _crontab(lay) + "0 7,8 * * 1-5  cd $PROJ && $PY scripts/report_wide.py\n"
    cand = rfr.generate_crontab(live, lay["cfg"], cohorts=["c1"]).text
    assert "0 7,8 * * 1-5  export PY=$RPY" in cand
    assert rfr.generate_crontab(cand, lay["cfg"], revert=["c1"]).text == live


def test_keep_declared_fallbacks(lay):
    live = _crontab(lay)
    # registry names `$PY scripts/report_alpha` -> prefix only; registry pins `30 7 * * 1-5 cd` -> refused
    prefix_only = rfr.generate_crontab(
        live, lay["cfg"], cohorts=["c1"], keep_declared=lambda old, new: "$RPY scripts" not in new
    )
    alpha = next(x for x in prefix_only.text.splitlines() if "report_alpha" in x)
    assert "TRADEAI_RUN_FROM_RELEASE=c1" in alpha and "$PY scripts/report_alpha.py" in alpha
    pinned = rfr.generate_crontab(
        live,
        lay["cfg"],
        cohorts=["c1"],
        keep_declared=lambda old, new: "30 7 * * 1-5 cd" in new or "report_alpha" not in new,
    )
    assert any(c["change"].startswith("refused: lane registry") for c in pinned.changed)
    assert (
        "30 7 * * 1-5 cd $PROJ && $PY scripts/report_alpha.py --days 7 >> logs/a.log 2>&1" in pinned.text.splitlines()
    )


def test_final_repoints_header_and_strips(lay):
    cand = rfr.generate_crontab(_crontab(lay), lay["cfg"], cohorts=["c1"]).text
    fin = rfr.generate_crontab(cand, lay["cfg"], final=True).text
    assert f"PY={lay['current']}/.venv/bin/python" in fin.splitlines()
    assert "RUN_FROM_RELEASE" not in fin and "$RPY" not in fin
    assert "$PY scripts/report_alpha.py" in fin


def test_literal_dev_path_refused(lay):
    text = _crontab(lay) + f"0 1 * * * cd {lay['dev']} && $PY scripts/report_dev.py\n"
    res = rfr.generate_crontab(text, lay["cfg"], cohorts=["c1"])
    assert any(c["change"] == "refused: literal dev path" for c in res.changed)
    assert f"0 1 * * * cd {lay['dev']} && $PY scripts/report_dev.py" in res.text.splitlines()


def test_unknown_cohort_and_missing_header(lay):
    with pytest.raises(SystemExit):
        rfr.generate_crontab(_crontab(lay), lay["cfg"], cohorts=["nope"])
    no_py = "\n".join(x for x in _crontab(lay).splitlines() if not x.startswith("PY="))
    with pytest.raises(SystemExit):
        rfr.generate_crontab(no_py, lay["cfg"], cohorts=["c1"])


def test_lane_gate_identity_is_ok():
    text = "SHELL=/bin/bash\n0 1 * * * echo hi\n"
    gate = rfr.lane_gate(text, text)
    assert gate["ok"] and gate["undeclared_before"] == gate["undeclared_after"]


# --------------------------------------------------------------------------- forced-run script


def test_forced_run_script_is_probe_only_and_valid_bash(lay):
    cand = rfr.generate_crontab(_crontab(lay), lay["cfg"], cohorts=["c1", "c2"]).text
    script = rfr.forced_run_script(cand, "c1")
    assert 'RUN="${RUN:-0}"' in script and "env -i" in script and 'test -x "$RPY"' in script
    p = lay["tmp"] / "fr.sh"
    p.write_text(script)
    assert subprocess.run(["bash", "-n", str(p)]).returncode == 0
    assert "ingest_gamma" not in script  # c2 only
    script2 = rfr.forced_run_script(cand, "c2")
    assert "+%F" in script2 and "\\%" not in script2.split("ingest_gamma", 1)[1].split("\n", 1)[0]


def test_forced_run_refuses_unescaped_percent(lay):
    text = _crontab(lay) + "0 2 * * * cd $PROJ && $PY scripts/report_pct.py --fmt %Y\n"
    cand = rfr.generate_crontab(text, lay["cfg"], cohorts=["c1"]).text
    assert "unescaped %" in rfr.forced_run_script(cand, "c1")


# --------------------------------------------------------------------------- unit drop-ins


def _cat(lay, *, oneshot=True, extra=""):
    dev, cur = lay["dev"], lay["current"]
    return (
        "# /home/x/.config/systemd/user/demo.service\n"
        "[Unit]\nDescription=demo\n[Service]\n"
        + ("Type=oneshot\n" if oneshot else "Restart=always\n")
        + f"WorkingDirectory={dev}\n"
        f"Environment=PATH={dev}/.venv/bin:/usr/bin\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        f"EnvironmentFile=-{dev}/.env\n"
        f"ExecStart={dev}/.venv/bin/python \\\n  scripts/report_alpha.py --apply\n"
        "\n# /home/x/.config/systemd/user/demo.service.d/10-x.conf\n[Service]\n"
        f"Environment=PYTHONPATH={cur}/scripts\n" + extra
    )


def test_unit_classify_and_dropin(lay):
    info = rfr.classify_unit("demo.service", _cat(lay), lay["cfg"], "static")
    assert info["root"] == "dev" and info["interpreter"] == "dev_venv" and info["unit_cohort"] == "u1"
    text = rfr.render_dropin(info, lay["cfg"])
    cur = str(lay["current"])
    assert f"WorkingDirectory={cur}" in text
    assert f'Environment="PATH={cur}/.venv/bin:/usr/bin"' in text
    assert "ExecStart=\nExecStart=" in text
    assert f"ExecStart={cur}/.venv/bin/python scripts/report_alpha.py --apply" in text
    assert "# EnvironmentFile=" in text  # reported, never rewritten
    assert "BLOCKED" not in text and "DAEMON" not in text


def test_unit_daemon_and_blockers(lay):
    extra = f"Environment=HERMES_HOME={lay['dev']}/sidecar/.hermes\nExecStartPre={lay['dev']}/missing/bin/tool\n"
    info = rfr.classify_unit("demo.service", _cat(lay, oneshot=False, extra=extra), lay["cfg"], "enabled")
    assert info["daemon"] and info["unit_cohort"] == "u2"
    text = rfr.render_dropin(info, lay["cfg"])
    assert "DAEMON" in text and "BLOCKED" in text
    assert any("HERMES_HOME" in b for b in info["blockers"])
    assert any("missing" in b and "absent in CURRENT" in b for b in info["blockers"])


def test_unit_exclusion_and_broker(lay):
    info = rfr.classify_unit("portfolio-server.service", _cat(lay), lay["cfg"])
    assert rfr.render_dropin(info, lay["cfg"], lay["cfg"].exclude_units) is None
    b = rfr.classify_unit("schwab-thing.service", _cat(lay), lay["cfg"])
    assert b["unit_cohort"] == "u3" and b["broker_adjacent"]


def test_execstart_reset_in_dropin_is_honoured(lay):
    cat = _cat(lay) + f"ExecStart=\nExecStart={lay['current']}/.venv/bin/python scripts/report_alpha.py\n"
    eff = rfr.effective(rfr.parse_systemctl_cat(cat))
    assert len(eff["ExecStart"]) == 1 and str(lay["current"]) in eff["ExecStart"][0].value


# --------------------------------------------------------------------------- verifier


def test_help_safety(tmp_path):
    safe = tmp_path / "safe.py"
    safe.write_text(
        "import argparse\nfrom pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
        "def main():\n    argparse.ArgumentParser().parse_args()\nif __name__ == '__main__':\n    main()\n"
    )
    assert rfr.help_safety(safe)[0]
    side = tmp_path / "side.py"
    side.write_text("import argparse\nconnect_db()\nif __name__ == '__main__':\n    pass\n")
    ok, why = rfr.help_safety(side)
    assert not ok and "connect_db" in why
    noarg = tmp_path / "noarg.py"
    noarg.write_text("import sys\nif __name__ == '__main__':\n    print(1)\n")
    assert not rfr.help_safety(noarg)[0]
    logf = tmp_path / "logf.py"
    logf.write_text(
        "import argparse, logging\nlogging.basicConfig(filename='x.log')\nif __name__ == '__main__':\n  pass\n"
    )
    assert not rfr.help_safety(logf)[0]


class FakeRun:
    def __init__(self, rc=0, out="usage: x [-h]\n"):
        self.calls = []
        self.rc, self.out = rc, out

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, self.rc, self.out, "")


def _job(lay, command, lineno=5):
    ln = rfr.CronLine(lineno, f"0 1 * * * {command}", "job", "0 1 * * *", command)
    env = {"PROJ": str(lay["current"]), "PY": f"{lay['dev']}/.venv/bin/python", "HOME": rfr.HOME}
    return rfr.classify_job(ln, env, lay["cfg"], {})


def test_verify_python_help_is_sandboxed(lay):
    (lay["rel"] / "scripts" / "report_alpha.py").write_text(
        "import argparse\nif __name__ == '__main__':\n    argparse.ArgumentParser().parse_args()\n"
    )
    run = FakeRun()
    job = _job(lay, "cd $PROJ && $RPY scripts/report_alpha.py --days 7")
    res = rfr.verify_job(job, lay["cfg"], "/opt/venv/bin/python", str(lay["tmp"]), runner=run)
    assert res["result"] == "pass"
    argv, kw = run.calls[0]
    assert argv[0] == "bwrap" and "--unshare-net" in argv and argv[-1] == "--help"
    assert argv[argv.index("--ro-bind") + 1] == "/"
    assert kw["cwd"] == str(lay["rel"])  # CURRENT resolved
    assert kw["env"]["TRADEAI_VENV_PYTHON"] == "/opt/venv/bin/python"


def test_verify_help_failure_and_missing(lay):
    (lay["rel"] / "scripts" / "report_alpha.py").write_text(
        "import argparse\nif __name__ == '__main__':\n    argparse.ArgumentParser().parse_args()\n"
    )
    res = rfr.verify_job(
        _job(lay, "cd $PROJ && $PY scripts/report_alpha.py"),
        lay["cfg"],
        "/p",
        "/tmp",
        runner=FakeRun(rc=1, out="ModuleNotFoundError: No module named 'psycopg2'"),
    )
    assert res["result"] == "fail" and "psycopg2" in res["reason"]
    res2 = rfr.verify_job(_job(lay, "cd $PROJ && $PY scripts/nope.py"), lay["cfg"], "/p", "/tmp", runner=FakeRun())
    assert res2["result"] == "fail" and "missing" in res2["reason"]


def test_verify_unsafe_script_gets_import_probe_not_execution(lay):
    (lay["rel"] / "scripts" / "ingest.py").write_text("import json\nimport requests\nrun_now()\n")
    run = FakeRun(rc=0, out="[]")
    res = rfr.verify_job(_job(lay, "cd $PROJ && $PY scripts/ingest.py"), lay["cfg"], "/p", "/tmp", runner=run)
    assert res["result"] == "pass_imports"
    argv = run.calls[0][0]
    assert "-c" in argv and "ingest.py" not in " ".join(argv[argv.index("-c") + 1 : argv.index("-c") + 2])
    assert json.loads(argv[argv.index("-c") + 2]) == ["json", "requests"]
    run3 = FakeRun(rc=3, out='["requests"]')
    res3 = rfr.verify_job(_job(lay, "cd $PROJ && $PY scripts/ingest.py"), lay["cfg"], "/p", "/tmp", runner=run3)
    assert res3["result"] == "fail" and "requests" in res3["reason"]


def test_verify_shell_and_inline(lay):
    _wrappers(lay)
    run = FakeRun(rc=0, out="")
    res = rfr.verify_job(
        _job(lay, f"{lay['current']}/scripts/run_pinned.sh full"), lay["cfg"], "/p", "/tmp", runner=run
    )
    assert res["result"] == "fail" and "hard-codes the dev tree" in res["reason"]
    assert run.calls[0][0][:2] == ["bash", "-n"]
    ok = rfr.verify_job(_job(lay, "cd $PROJ && bash scripts/run_clean.sh"), lay["cfg"], "/p", "/tmp", runner=run)
    assert ok["result"] == "pass"
    inl = rfr.verify_job(_job(lay, "cd $PROJ && python3 -c 'import x'"), lay["cfg"], "/p", "/tmp", runner=run)
    assert inl["result"] == "skip"


def test_optional_imports_are_not_required(tmp_path):
    p = tmp_path / "s.py"
    p.write_text("import os\ntry:\n    import fancy\nexcept ImportError:\n    fancy = None\nfrom x.y import z\n")
    assert rfr.top_level_imports(p) == ["os", "x"]


# --------------------------------------------------------------------------- write-path scan


def test_write_paths_linked_vs_release_local(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "w.py").write_text(
        "import json, os\nfrom pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parents[1]\n"
        "OUT = ROOT / 'data' / 'cio'\n"
        "def go():\n"
        "    OUT.mkdir(parents=True, exist_ok=True)\n"
        "    (OUT / 'x.json').write_text('{}')\n"
        "    with open(ROOT / 'state' / 'hermes.jsonl', 'a') as fh:\n"
        "        fh.write('x')\n"
        "    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'gen'))\n"
        "    print(ROOT / 'data' / 'read_only.json')\n"
    )
    release = tmp_path / "rel"
    (release / "data").mkdir(parents=True)
    ps = tmp_path / "ps" / "cio"
    ps.mkdir(parents=True)
    (release / "data" / "cio").symlink_to(ps)
    (release / "state").mkdir()
    rep = rfr.scan_repo_write_paths(repo, release)
    paths = {(h["path"], h["status"].split(":")[0]) for h in rep["hits"]}
    assert ("data/cio", "linked") in paths and ("data/cio/x.json", "linked") in paths
    assert ("state/hermes.jsonl", "release-local") in paths
    assert ("config/gen", "release-local") in paths
    assert not any(h["path"] == "data/read_only.json" for h in rep["hits"])
    assert rep["write_sites_release_local"] == 2 and rep["write_sites_linked"] == 2


def test_cli_crontab_writes_only_out(lay, tmp_path):
    src = tmp_path / "live.txt"
    src.write_text(_crontab(lay))
    out = tmp_path / "out"
    rc = rfr.main(
        [
            "--config",
            str(lay["cfg_path"]),
            "crontab",
            "--crontab-file",
            str(src),
            "--cohorts",
            "c1",
            "--out",
            str(out),
            "--no-lane-gate",
        ]
    )
    assert rc == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "crontab.candidate",
        "crontab.diff",
        "crontab.live",
        "crontab.summary.json",
    ]
    assert src.read_text() == _crontab(lay)
